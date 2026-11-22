"""CLI — jádrové case operace (ingest, files, stats, search, timeline, korelace, analytics).

P1-4 (refaktor god-file ``cli.py``): přesunuto bez změny chování;
facade ``stopa.cli`` re-exportuje implementace pro kompatibilitu.
"""
from __future__ import annotations

import argparse
import logging
import signal  # F2.4 — SIGINT/SIGTERM → graceful shutdown ingestu (stop_event)
import sys
import threading  # F2.4 — stop_event pro graceful shutdown
from pathlib import Path

from stopa.data.write_blocker_repository import WriteBlockerRepository  # F5.4
from stopa.domain.profiles import get_profile
from stopa.domain.write_blocker import (  # F5.4/P0.4 — write-blocker API + fail-closed brána
    ACTION_CHECK,
    ACTION_MODE_EXCEPTION,
    MODE_WARN_ONLY,
    gate_with_mode,
)
from stopa.models import EvidenceSource
from stopa.pipeline import load_hash_sets, process_source, run_timeline_intel

_log = logging.getLogger("stopa.cli.core")

from .._util import (
    _load_timesketch_auto_push,
    _load_wb_gate_mode,  # P0.4 — gate režim (fail-closed výchozí)
    _open_db,
    _print_json,
    _rich_progress,
    case_examiner,
)


def cmd_add(args: argparse.Namespace) -> int:
    db = _open_db(args.case_id)
    # F5.4/P0.4 — write-blocker gate (settings.json; forenzní profil má
    # výchozí fail-closed režim, P0.4: "Forensic profile: fail-closed").
    # exit 2 = brána blokuje ingest bez potvrzené ochrany proti zápisu.
    # P0.4: každá kontrola se audituje (wb_check), laboratorní warn_only navíc
    # jako explicitní výjimka (wb_mode_exception).
    wb_repo = WriteBlockerRepository(db.conn, db.audit_repo)
    wb_mode = _load_wb_gate_mode(profile_name=getattr(args, "profile", None) or "forensic")
    wb_check = gate_with_mode(
        wb_repo.latest_state(), wb_mode, connection=getattr(args, "method", None)
    )
    db.log_operation(
        ACTION_CHECK,
        actor=case_examiner(db, args.case_id),
        details={
            "allowed": wb_check.allowed,
            "protection_class": wb_check.protection_class,
            "mode": wb_mode,
            "device_id": wb_check.device_id,
            "connection": wb_check.connection,
            "extra_warnings": list(wb_check.extra_warnings),
        },
    )
    if wb_mode == MODE_WARN_ONLY:
        db.log_operation(
            ACTION_MODE_EXCEPTION, actor=case_examiner(db, args.case_id), details={"mode": wb_mode}
        )
    if not wb_check.allowed:
        print(f"⛔ {wb_check.warning}", file=sys.stderr)
        for w in wb_check.extra_warnings:
            print(f"⚠️  {w}", file=sys.stderr)
        return 2
    if wb_check.warning is not None:
        # měkké varování (warn_only režim / neznámé VID/PID) — ingest pokračuje
        print(f"⚠️  {wb_check.warning}", file=sys.stderr)
        for w in wb_check.extra_warnings:
            print(f"⚠️  {w}", file=sys.stderr)
    profile = get_profile(args.profile)  # early validace jména profilu
    json_mode = getattr(args, "json", False)

    hash_sets: dict[str, set[str]] | None = None
    if args.hash_set:
        paths = [Path(p) for p in args.hash_set]
        missing = [str(p) for p in paths if not p.exists()]
        if missing:
            print(f"Chybějící hash sety: {', '.join(missing)}", file=sys.stderr)
            return 2
        hash_sets = load_hash_sets(paths)

    rc = 0
    bar = None if json_mode else _rich_progress()
    source_summaries: list[dict] = []
    # R0.4 — stav Rich progress tasku; musí být venku ze smyčky (B023), ať se neresetuje per zdroj
    _bar_state: dict[str, object] = {"task": None}
    # F2.4 — graceful shutdown: SIGINT/SIGTERM → stop_event; pipeline dojedou in-flight
    # úlohy + commitne checkpoint (pokračování přes --resume bez ztráty dat).
    _stop_ev = threading.Event()

    def _f24_stop_handler(signum: int, _frame: object) -> None:
        _stop_ev.set()

    _prev_signal_handlers = {
        sig: signal.signal(sig, _f24_stop_handler) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    if not json_mode:
        print(f"Zpracovávám {len(args.paths)} zdrojů (profil: {profile.name})")
    for path_str in args.paths:
        root = Path(path_str).expanduser()
        if not root.exists():
            print(f"Zdroj neexistuje: {root}", file=sys.stderr)
            rc = 2
            source_summaries.append({"path": str(root), "error": "zdroj neexistuje"})
            continue
        kind = "folder" if root.is_dir() else "file"
        # E3/F2.4 — idempotentní zdroj: při --resume už existuje zdroj se stejnou cestou;
        # musíme opakovat jeho ID, ať skip-set (files WHERE source_id=?) najde zpracované soubory.
        existing = next(
            (s for s in db.list_sources(args.case_id) if s.path == str(root)), None
        )
        source = existing or EvidenceSource(case_id=args.case_id, kind=kind, path=str(root))
        if existing is None:
            db.add_source(source)
        # E1 Evidence Manager: custody metadata + neměnná stopa nabytí důkazu
        db.set_custody_item(
            source.id,
            acquired_at=source.added_at,
            method=getattr(args, "method", None),
            custodian=getattr(args, "custodian", None),
        )
        db.log_operation(
            "source_added",
            actor=getattr(args, "custodian", None) or case_examiner(db, args.case_id),
            details={
                "source_id": source.id,
                "path": str(root),
                "kind": source.kind,
                "method": getattr(args, "method", None),
            },
        )
        _bar_state["task"] = None  # nový Rich task per zdroj (label/total se liší)

        def _progress(done: int, total: int, label: str = source.path) -> None:
            if bar is not None:
                # R0.4 — Rich progress (lazy task: total je známé až po walku)
                if _bar_state["task"] is None and total:
                    _bar_state["task"] = bar.add(label, total)
                elif _bar_state["task"] is not None:
                    bar.update(_bar_state["task"], done)  # type: ignore[arg-type]
            elif not json_mode:
                pct = (done / total * 100) if total else 100.0
                print(f"\r  {label}: {done}/{total} souborů ({pct:.0f}%)", end="", flush=True)

        result = process_source(
            db, source.id, root, args.profile, hash_sets, _progress,
            resume=getattr(args, "resume", False),
            resume_mode=getattr(args, "resume_mode", None),  # P0.1 — fast (výchozí) / strict
            max_workers=args.workers,  # F2.4 — CLI --workers (default auto)
            pool=args.pool,  # F2.4 — CLI --pool (auto = procesy pro N>1)
            stop_event=_stop_ev,  # F2.4 — SIGINT/SIGTERM → graceful shutdown
            disk_budget_bytes=(  # P2-1 — CLI --disk-budget MB (0 = bez limitu)
                int(getattr(args, "disk_budget", 0)) * 1024 * 1024
                if getattr(args, "disk_budget", 0)
                else None
            ),
        )
        if bar is not None and _bar_state["task"] is not None:
            # dokončit task (100 %) — Rich transient bar
            try:
                bar.update(_bar_state["task"], max(result.files_total, 1))  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001 — progress je kosmetický
                _log.debug("Rich progress dokončení selhalo: %s", exc)
        if not json_mode:
            if result.files_total:
                print()
            print(f"  [{result.profile}] {result.files_total} souborů, {result.bytes_total / 1e6:.2f} MB")
            print(
                f"    signatury: {result.signatures_detected}, "
                f"bad ext: {result.bad_extensions}, duplikáty: {result.duplicates}, "
                f"hash-set trefy: {result.hash_set_hits}"
            )
            if result.artifacts_extracted:
                print(f"    artifacty extrahovány: {result.artifacts_extracted}")
            for err in result.errors[:5]:
                print(f"    ! {err}", file=sys.stderr)
        source_summaries.append(
            {
                "source_id": source.id,
                "path": str(root),
                "kind": source.kind,
                "profile": result.profile,
                "files_total": result.files_total,
                "bytes_total": result.bytes_total,
                "signatures_detected": result.signatures_detected,
                "bad_extensions": result.bad_extensions,
                "duplicates": result.duplicates,
                "hash_set_hits": result.hash_set_hits,
                "artifacts_extracted": result.artifacts_extracted,
                "errors": list(result.errors),
                # F2.4 — graceful shutdown: checkpoint uložen, pokračování přes --resume
                "interrupted": result.interrupted,
            }
        )
        if result.interrupted:
            if not json_mode:
                print("  ⚠ přerušeno — checkpoint uložen; pokračování přes --resume")
            rc = max(rc, 130)  # konvence SIGINT — skripty vědí, že mají spustit resume
    # F2.4 — obnovit původní signal handlery (default KeyboardInterrupt apod.)
    for _sig, _prev in _prev_signal_handlers.items():
        signal.signal(_sig, _prev)
    if bar is not None:
        bar.stop()

    # STP-018 Timeline Intelligence 2.0 — post-pass nad celou case DB (rozpory + duplikáty).
    intel_summary: dict | None = None
    try:
        intel = run_timeline_intel(db)
        if intel["events"]:
            intel_summary = {
                "contradiction_groups": intel["contradiction_groups"],
                "dup_groups": intel["dup_groups"],
                "events": intel["events"],
            }
            if not json_mode:
                print(
                    f"    timeline intel: {intel['contradiction_groups']} rozporových skupin, "
                    f"{intel['dup_groups']} dup. skupin ({intel['events']} událostí)"
                )
    except Exception as exc:  # noqa: BLE001 — analytický bonus, ne pád ingestu
        if not json_mode:
            print(f"    ! timeline intel: {exc}", file=sys.stderr)
    # F6.1 — opt-in auto-push do Timesketch po úspěšném ingestu (settings.json
    # timesketch_auto_push, default OFF; graceful degradation — selhání nepadá ingest).
    if rc == 0 and _load_timesketch_auto_push():
        try:
            from stopa.data.timesketch_client import TimesketchClient, settings_from_env
            from stopa.domain.export import timeline_records as _ts_timeline_records
            from stopa.domain.timesketch_push import push_to_timesketch

            case = db.get_case(args.case_id)
            ts_summary = push_to_timesketch(
                TimesketchClient(settings_from_env()),
                case.name if case else args.case_id,
                "timeline",
                _ts_timeline_records(db.list_timeline_events()),
            )
            db.log_operation(
                "timesketch_pushed",
                actor=case_examiner(db, args.case_id),
                details={**ts_summary, "what": "timeline", "auto": True},
            )
            if not json_mode:
                print(
                    f"    timesketch auto-push: {ts_summary['records']} záznamů → "
                    f"sketch {ts_summary['sketch_id']}"
                )
        except Exception as exc:  # noqa: BLE001 — opt-in bonus, ne pád ingestu
            if not json_mode:
                print(f"    ! timesketch auto-push: {exc}", file=sys.stderr)
    # P0 Core C4: kontrolní bod po ingestu (podpis hashu posledního audit řádku).
    db.add_integrity_checkpoint("ingest")
    db.close()
    if json_mode:
        _print_json(
            {
                "case_id": args.case_id,
                "profile": profile.name,
                "sources": source_summaries,
                "timeline_intel": intel_summary,
            }
        )
    return rc


def cmd_files(args: argparse.Namespace) -> int:
    db = _open_db(args.case_id)
    records = db.list_files(
        bad_extensions_only=args.bad_ext,
        duplicates_only=args.dups,
        signature_family=args.family,
        limit=args.limit,
    )
    if not records and getattr(args, "json", False):
        _print_json({"case_id": args.case_id, "files": [], "total": 0})
        db.close()
        return 0
    if not records:
        print("(žádné záznamy)")
        db.close()
        return 0
    file_rows = []
    for r in records:
        flags = []
        if r.bad_extension:
            flags.append("BAD-EXT")
        if r.is_duplicate_of:
            flags.append(f"DUP→{r.is_duplicate_of}")
        if r.hash_set_hit:
            flags.append(f"HASHSET:{r.hash_set_hit}")
        flag_str = f"  [{' '.join(flags)}]" if flags else ""
        sig = r.signature_type or "?"
        file_rows.append(
            {
                "rel_path": r.rel_path,
                "signature": sig,
                "size_bytes": r.size_bytes,
                "bad_extension": bool(r.bad_extension),
                "duplicate_of": r.is_duplicate_of,
                "hash_set_hit": r.hash_set_hit,
            }
        )
        if not getattr(args, "json", False):
            print(f"{r.rel_path}  [{sig}] {r.size_bytes:,} B{flag_str}")
    if getattr(args, "json", False):
        _print_json({"case_id": args.case_id, "files": file_rows, "total": len(file_rows)})
    db.close()
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    db = _open_db(args.case_id)
    case = db.get_case(args.case_id)
    sources = db.list_sources(args.case_id)
    s = db.stats()
    if getattr(args, "json", False):
        payload = {
            "case_id": args.case_id,
            "name": case.name if case else None,
            "examiner": case.examiner if case else None,
            "sources": [
                {
                    "id": src.id,
                    "kind": src.kind,
                    "path": src.path,
                    **{k: db.stats(src.id)[k] for k in ("files", "bytes", "bad_ext", "dups")},
                }
                for src in sources
            ],
            "totals": s,
        }
        _print_json(payload)
        db.close()
        return 0
    print(f"Případ: {case.name if case else args.case_id} ({args.case_id})")
    if case and case.examiner:
        print(f"Znalec: {case.examiner}")
    print(f"Zdroje: {len(sources)}")
    for src in sources:
        ss = db.stats(src.id)
        print(
            f"  - [{src.kind}] {src.path}: {ss['files']} souborů, "
            f"{ss['bytes'] / 1e6:.2f} MB, bad-ext {ss['bad_ext']}, duplikáty {ss['dups']}"
        )
    print(
        f"CELKEM: {s['files']} souborů, {s['bytes'] / 1e6:.2f} MB | "
        f"signatury: {s['signed']}, bad-ext: {s['bad_ext']}, duplikáty: {s['dups']}"
    )
    db.close()
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Full-text search (FTS5) — AXIOM-style vyhledávání napříč případem + P3-1 filtry."""
    db = _open_db(args.case_id)
    # P3-1 — s jakýmkoli pokročilým flagem jde přes SearchRepository; bez nich
    # zůstává původní cesta byte-identická (AK1).
    if any(
        (
            getattr(args, "kind", None),
            getattr(args, "entity", None),
            getattr(args, "size_min", None) is not None,
            getattr(args, "size_max", None) is not None,
            getattr(args, "mtime_from", None),
            getattr(args, "mtime_to", None),
            getattr(args, "rel_depth", None),
        )
    ):
        return _cmd_search_advanced(args, db)
    records = db.search(args.query, source_id=args.source, limit=args.limit)
    json_mode = getattr(args, "json", False)
    if not records:
        if json_mode:
            _print_json({"case_id": args.case_id, "query": args.query, "results": [], "total": 0})
        else:
            print(f"(žádné soubory neodpovídají dotazu: {args.query!r})")
        db.close()
        return 0
    results = []
    for r in records:
        flags = []
        if r.bad_extension:
            flags.append("BAD-EXT")
        if r.is_duplicate_of:
            flags.append(f"DUP→{r.is_duplicate_of}")
        if r.hash_set_hit:
            flags.append(f"HASHSET:{r.hash_set_hit}")
        flag_str = f"  [{' '.join(flags)}]" if flags else ""
        sig = r.signature_type or "?"
        results.append(
            {
                "rel_path": r.rel_path,
                "signature": sig,
                "size_bytes": r.size_bytes,
                "flags": [f for f in (r.bad_extension and "BAD-EXT", bool(r.is_duplicate_of) and f"DUP→{r.is_duplicate_of}", r.hash_set_hit and f"HASHSET:{r.hash_set_hit}") if f],
            }
        )
        if not json_mode:
            print(f"{r.rel_path}  [{sig}] {r.size_bytes:,} B{flag_str}")
    if json_mode:
        _print_json({"case_id": args.case_id, "query": args.query, "results": results, "total": len(results)})
    else:
        print(f"\nCELKEM: {len(records)} souborů (dotaz: {args.query!r})")
    db.close()
    return 0


def _cmd_search_advanced(args: argparse.Namespace, db) -> int:
    """P3-1 — strukturované vyhledávání se filtry a procházením grafu vztahů.

    Voláno z :func:`cmd_search`, když je zadán jakýkoli pokročilý flag
    (--kind/--entity/--size-min/--size-max/--mtime-from/--mtime-to/--rel-depth).
    Výstupní formát výsledků odpovídá původnímu search; JSON dostává aditivně
    klíče ``filters`` a ``related``, textový režim sekci VZTAHY.
    """
    from stopa.data.search_repository import SearchRepository
    from stopa.domain.search_adv import AdvancedSearchQuery, FilterSpec, RelationSpec

    try:
        spec = FilterSpec.from_iso(
            kind=args.kind,
            size_min=args.size_min,
            size_max=args.size_max,
            mtime_from=args.mtime_from,
            mtime_to=args.mtime_to,
            source_id=getattr(args, "source", None),
            entity=args.entity,
        )
        relations = RelationSpec(depth=args.rel_depth) if args.rel_depth else None
        query = AdvancedSearchQuery(
            text=args.query or None,
            scope="files",
            filters=spec,
            relations=relations,
            limit=getattr(args, "limit", 100),
        )
        result = SearchRepository(db.conn).search_advanced(query)
    except (ValueError, TypeError) as exc:
        print(f"Neplatný filtr: {exc}", file=sys.stderr)
        db.close()
        return 2

    json_mode = getattr(args, "json", False)
    results_out = []
    for r in result.results:
        flags = [f for f in (r.bad_extension and "BAD-EXT", bool(r.is_duplicate_of) and f"DUP→{r.is_duplicate_of}", r.hash_set_hit and f"HASHSET:{r.hash_set_hit}") if f]
        flag_str = f"  [{' '.join(flags)}]" if flags else ""
        sig = r.signature_type or "?"
        results_out.append(
            {
                "rel_path": r.rel_path,
                "signature": sig,
                "size_bytes": r.size_bytes,
                "flags": flags,
            }
        )
        if not json_mode:
            print(f"{r.rel_path}  [{sig}] {r.size_bytes:,} B{flag_str}")

    related_out = [
        {"rel_path": r.rel_path, "signature": r.signature_type or "?", "size_bytes": r.size_bytes}
        for r in result.related_files
    ]

    if json_mode:
        _print_json(
            {
                "case_id": args.case_id,
                "query": args.query,
                "results": results_out,
                "total": len(results_out),
                "filters": query.to_dict().get("filters", {}),
                "related": {"files": related_out, "nodes": list(result.related_nodes)},
            }
        )
    else:
        if not result.results and not related_out:
            print(f"(žádné soubory neodpovídají dotazu: {args.query!r})")
        if related_out or result.related_nodes:
            print(
                f"\nVZTAHY (hloubka {args.rel_depth}): {len(related_out)} souvisejících"
                f" souborů, {len(result.related_nodes)} uzlů grafu"
            )
            for r in result.related_files:
                sig = r.signature_type or "?"
                print(f"  {r.rel_path}  [{sig}] {r.size_bytes:,} B")
            for n in list(result.related_nodes)[:20]:
                rels = ",".join(n["relations"]) if n["relations"] else "?"
                print(f"  [{n['type']}] id={n['id']} depth={n['depth']} relations={rels}")
        if result.results:
            extra = f" (+{len(related_out)} souvisejících)" if related_out else ""
            print(f"\nCELKEM: {len(result.results)} souborů{extra} (dotaz: {args.query!r})")
    db.close()
    return 0


def cmd_timeline(args: argparse.Namespace) -> int:
    """AXIOM-style timeline — chronologický přehled extrahovaných artifactů.

    STP-018: ``--intel`` spustí Timeline Intelligence 2.0 post-pass (rozpory +
    duplikáty napříč zdroji) a vypíše analytické skupiny nad materializovanou timeline.
    """
    db = _open_db(args.case_id)
    json_mode = getattr(args, "json", False)

    if getattr(args, "intel", False):
        from stopa.domain.timeline_intel import (
            FLAG_CONCURRENT_ACTIVITY,
            FLAG_CROSS_SOURCE_DUP,
        )

        summary = run_timeline_intel(db, window_seconds=getattr(args, "window", 60.0))
        events = db.list_timeline_events(limit=10_000)
        contra = [e for e in events if FLAG_CONCURRENT_ACTIVITY in (e.get("anomaly_flags") or [])]
        dups = [e for e in events if FLAG_CROSS_SOURCE_DUP in (e.get("anomaly_flags") or [])]
        if json_mode:
            _print_json(
                {
                    "case_id": args.case_id,
                    "intel": summary,
                    "contradictions": contra,
                    "cross_source_dups": dups,
                }
            )
            db.close()
            return 0
        print(
            f"Timeline Intelligence 2.0: {summary['events']} událostí → "
            f"{summary['contradiction_groups']} rozporových skupin, "
            f"{summary['dup_groups']} dup. skupin"
        )
        events = db.list_timeline_events(limit=10_000)
        contra = [e for e in events if FLAG_CONCURRENT_ACTIVITY in (e.get("anomaly_flags") or [])]
        dups = [e for e in events if FLAG_CROSS_SOURCE_DUP in (e.get("anomaly_flags") or [])]
        if contra:
            print(f"\nROZPORY (souběžná aktivita subjektu) — {len(contra)} událostí:")
            by_group: dict[str, list[dict]] = {}
            for e in sorted(contra, key=lambda x: (x.get("contradiction_group_id") or "", x["ts_utc"])):
                by_group.setdefault(e["contradiction_group_id"], []).append(e)
            for gid, items in sorted(by_group.items()):
                subj = ", ".join(sorted({v for i in items for v in (i.get("subject_values") or [])}))[:100]
                print(f"  [{gid}] subjekt: {subj}")
                for e in items:
                    ts = e["ts_utc"].strftime("%Y-%m-%d %H:%M:%S") if e["ts_utc"] else "—" * 19
                    print(
                        f"    {ts}  [{e['event_type']}] {(e.get('title') or '')[:60]} "
                        f"(src={e['source_id']}, file={(e.get('rel_path') or '')[:40]})"
                    )
        if dups:
            print(f"\nDUPLIKÁTY NAPŘÍČ ZDROJI — {len(dups)} událostí:")
            by_group = {}
            for e in sorted(dups, key=lambda x: (x.get("dup_group_id") or "", x["ts_utc"])):
                by_group.setdefault(e["dup_group_id"], []).append(e)
            for gid, items in sorted(by_group.items()):
                print(f"  [{gid}] {len(items)}× {(items[0].get('title') or '')[:60]}")
                for e in items:
                    ts = e["ts_utc"].strftime("%Y-%m-%d %H:%M:%S") if e["ts_utc"] else "—" * 19
                    print(f"    {ts}  src={e['source_id']} file={(e.get('rel_path') or '')[:50]}")
        db.close()
        return 0

    arts = db.list_artifacts(
        source_id=args.source,
        artifact_type=args.type,
        rel_path_like=args.path,
        limit=args.limit,
    )
    if not arts:
        if json_mode:
            _print_json({"case_id": args.case_id, "artifacts": [], "total": 0})
        else:
            print("(žádné artifacty — použij profil s extract_artifacts)")
        db.close()
        return 0
    rows = []
    for a in arts:
        ts = a.timestamp.strftime("%Y-%m-%d %H:%M") if a.timestamp else None
        title = (a.title or "")[:80]
        rows.append(
            {
                "timestamp": ts,
                "artifact_type": a.artifact_type,
                "title": title,
                "rel_path": a.rel_path if args.verbose or json_mode else None,
            }
        )
        if not json_mode:
            print(f"{ts or '—' * 16}  [{a.artifact_type}] {title}")
            if args.verbose and a.rel_path:
                print(f"          └─ {a.rel_path}")
    stats = db.artifact_stats(args.source)
    by_type = ", ".join(f"{k}: {v}" for k, v in sorted(stats.items()) if k != "total")
    if json_mode:
        _print_json(
            {"case_id": args.case_id, "artifacts": rows, "total": len(rows), "by_type": stats}
        )
    else:
        print(f"\nCELKEM: {stats['total']} artifactů ({by_type})")
    db.close()
    return 0


def cmd_correlate(args: argparse.Namespace) -> int:
    """E4 — Entity + Correlation Engine (explicitní krok, ne při extrakci)."""
    from stopa.domain.correlation import run_correlation

    db = _open_db(args.case_id)
    case = db.get_case(args.case_id)
    summary = run_correlation(db, args.case_id)
    db.log_operation(
        "correlation_run",
        actor=case.examiner if case else None,
        details={
            "entities": summary["entities"],
            "correlations_total": summary["correlations_total"],
            "by_relation": summary["by_relation"],
            "merge_candidates": len(summary.get("merge_candidates", [])),
        },
    )

    if getattr(args, "json", False):
        payload: dict = {
            "case_id": args.case_id,
            "entities": summary["entities"],
            "correlations_total": summary["correlations_total"],
            "by_relation": summary["by_relation"],
            "merge_candidates": summary.get("merge_candidates", []),
        }
        if getattr(args, "verbose", False):
            payload["correlations"] = db.list_correlations(args.case_id)
        _print_json(payload)
    else:
        print(f"Entit: {summary['entities']}")
        total = summary["correlations_total"]
        if not total:
            print("Propojení: 0 (žádné entity napříč artifacty/soubory)")
        else:
            by_rel = ", ".join(
                f"{k}: {v}" for k, v in sorted(summary["by_relation"].items())
            )
            print(f"Propojení: {total} ({by_rel})")
            if args.verbose:
                for c in db.list_correlations(args.case_id):
                    a = c["entity_a"]
                    b = c["entity_b"]
                    label = a if a == b else f"{a} ↔ {b}"
                    print(f"  [{c['relation']}/{c['confidence']}] {label}")
                    for ev in c["evidence"][:5]:
                        path = ev.get("rel_path") or ""
                        print(f"      └─ {ev.get('detail', '')} {path}".rstrip())
        # P0 I3: detekce duplicitních entit (merge candidates) — heuristické páry.
        mc = summary.get("merge_candidates", [])
        if mc:
            print(f"Možné duplikity entit: {len(mc)}")
            for m in mc[:10]:
                print(f"  [{m['kind']}] {m['value_a']} ≈ {m['value_b']} — {m['reason']}")
    # P0 Core C4: kontrolní bod po korelaci.
    db.add_integrity_checkpoint("correlate")
    db.close()
    return 0


def cmd_analytics(args: argparse.Namespace) -> int:
    """F2.2 — DuckDB OLAP analytics nad timeline (agregace, histogram, top typy).

    Bez nainstalovaného duckdb ([analytics] extra) → explicitní hláška + exit 3
    (backward-kompatibilní: SQLite cesta zůstává pro standardní timeline/search).
    """
    from stopa.data.analytics import AnalyticsError, AnalyticsStore, duckdb_available

    if not duckdb_available():
        print("DuckDB není nainstalováno — pip install 'stopa[analytics]' (F2.2 OLAP)")
        return 3
    db = _open_db(args.case_id)
    db_path = str(db.path)
    db.close()
    try:
        store = AnalyticsStore(db_path)
        status = store.status()
        payload: dict[str, object] = {
            "case_id": args.case_id,
            "status": status,
            "top_event_types": store.top_event_types(limit=20),
            "entity_summary": store.entity_summary(),
        }
        if getattr(args, "dedupe", False):
            refreshed = store.refresh_blocks()
            payload["block_dedupe"] = {**store.dedupe_summary(), **refreshed}
        if getattr(args, "from_ts", None) and getattr(args, "to_ts", None):
            events = store.timeline_range(
                args.from_ts,
                args.to_ts,
                event_type=getattr(args, "type", None),
                limit=args.limit,
            )
            payload["timeline_window"] = {
                "from": args.from_ts,
                "to": args.to_ts,
                "events": events,
                "count": len(events),
            }
        if getattr(args, "json", False):
            _print_json(payload)
            return 0
        live = status.get("live") or {}
        print(
            f"DuckDB OLAP — {int(live.get('timeline_events', 0))} událostí "
            f"(fresh={status.get('fresh')}, readonly={status.get('readonly')})"
        )
        bd = payload.get("block_dedupe")
        if isinstance(bd, dict):
            print(
                f"\nF2.3 BLOCK DEDUP — {bd['files']} soubor(ů), "
                f"{bd['total_blocks']} bloků (unikátních {bd['unique_blocks']})"
            )
            print(
                f"  úspora deduplikace: {bd['savings_pct']} % "
                f"({bd['duplicated_bytes']} B z {bd['total_bytes']} B)"
            )
            for t in bd["top_duplicated"][:5]:
                print(f"  {t['sha256'][:16]}… ×{t['count']} ({t['length']} B/blok)")
        win = payload.get("timeline_window")
        if isinstance(win, dict):
            print(f"\nOKNO {win['from']} → {win['to']}: {win['count']} událostí")
            for e in win["events"][: args.limit]:  # type: ignore[union-attr]
                print(f"  {e['ts_utc']}  [{e['event_type']}]  {e.get('title') or ''}")
        else:
            hist = store.hourly_histogram()
            if hist:
                print("\nPO HODINÁCH:")
                for h in hist[:24]:
                    bar = "#" * min(60, max(1, int(h["events"] / 3) if h else 0))
                    print(f"  {h['hour']}  {bar} ({h['events']})")
            top = payload.get("top_event_types") or []
            if isinstance(top, list):
                print("\nTOP TYPY:")
                for t in top[:10]:
                    print(f"  {t['event_type']:24s} {t['count']}")
        return 0
    except AnalyticsError as exc:
        print(f"Analytics chyba: {exc}")
        return 2


def cmd_image(args: argparse.Namespace) -> int:
    """Disk image processing (FÁZE 5) — TSK file systems + carving."""
    from stopa.data.image_pipeline import process_disk_image
    from stopa.domain.profiles import get_profile

    db = _open_db(args.case_id)
    profile = get_profile(args.profile)
    img_path = Path(args.path).expanduser()
    if not img_path.exists():
        print(f"Obraz neexistuje: {img_path}", file=sys.stderr)
        return 2

    source = EvidenceSource(case_id=args.case_id, kind="file", path=str(img_path))
    db.add_source(source)
    summary = process_disk_image(
        db, source.id, img_path, profile, carve_free=not args.no_carve
    )
    if getattr(args, "json", False):
        _print_json(
            {
                "case_id": args.case_id,
                "source_id": source.id,
                "image_type": summary.image_type,
                "description": summary.description,
                "partitions": [
                    {"index": p.index, "fstype": p.fstype, "offset_sectors": p.offset_sectors}
                    for p in summary.partitions
                ],
                "files_total": summary.files_total,
                "bytes_total": summary.bytes_total,
                "signatures_detected": summary.signatures_detected,
                "carved_candidates": summary.carved_candidates,
                "errors": list(summary.errors),
            }
        )
    else:
        print(f"Disk image: {summary.image_type or 'neznámý'} — {summary.description or '?'}")
        for p in summary.partitions:
            print(f"  partice #{p.index}: {p.fstype} @ sektor {p.offset_sectors}")
        print(
            f"  soubory: {summary.files_total}, bajty: {summary.bytes_total / 1e6:.2f} MB, "
            f"signatury: {summary.signatures_detected}"
        )
        if summary.carved_candidates:
            print(f"  carving kandidáti (nealokovaný prostor): {summary.carved_candidates}")
        for err in summary.errors[:5]:
            print(f"  ! {err}", file=sys.stderr)
    db.close()
    return 0


def cmd_mobile(args: argparse.Namespace) -> int:
    """Mobilní physical obraz (FÁZE 6b) — FDE/FBE unlock + TSK."""
    from stopa.data.image_pipeline import process_mobile_image
    from stopa.domain.profiles import get_profile

    db = _open_db(args.case_id)
    profile = get_profile(args.profile)
    img_path = Path(args.path).expanduser()
    if not img_path.exists():
        print(f"Obraz neexistuje: {img_path}", file=sys.stderr)
        return 2

    source = EvidenceSource(case_id=args.case_id, kind="file", path=str(img_path))
    db.add_source(source)
    summary = process_mobile_image(
        db, source.id, img_path, profile,
        password=args.password, keyfile=getattr(args, "keyfile", None),
        carve_free=not args.no_carve,
        fde_type=getattr(args, "fde_type", None),
        recovery_key=getattr(args, "recovery_key", None),
    )
    if getattr(args, "json", False):
        _print_json(
            {
                "case_id": args.case_id,
                "source_id": source.id,
                "fde_unlocked": summary.fde_unlocked,
                "image_type": summary.image_type,
                "description": summary.description,
                "partitions": [
                    {"index": p.index, "fstype": p.fstype, "offset_sectors": p.offset_sectors}
                    for p in summary.partitions
                ],
                "files_total": summary.files_total,
                "bytes_total": summary.bytes_total,
                "signatures_detected": summary.signatures_detected,
                "carved_candidates": summary.carved_candidates,
                "errors": list(summary.errors),
            }
        )
    else:
        if summary.fde_unlocked:
            print(f"Mobilní FDE obraz: {summary.description}")
        else:
            print(f"Mobilní obraz: {summary.image_type or 'neznámý'} — {summary.description or '?'}")
        for p in summary.partitions:
            print(f"  partice #{p.index}: {p.fstype} @ sektor {p.offset_sectors}")
        print(
            f"  soubory: {summary.files_total}, bajty: {summary.bytes_total / 1e6:.2f} MB, "
            f"signatury: {summary.signatures_detected}"
        )
        if summary.carved_candidates:
            print(f"  carving kandidáti (nealokovaný prostor): {summary.carved_candidates}")
        for err in summary.errors[:5]:
            print(f"  ! {err}", file=sys.stderr)
    db.close()
    return 0


