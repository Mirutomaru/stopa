"""STOPA CLI — argparse subpříkazy.

Použití:
  stopa case new "Karel Novák" --examiner "JUDr. M. Matúš"
  stopa add <case_id> /cesta/ke/zdroji [--profile forensic] [--hash-set bad.txt]
  stopa files <case_id> [--bad-ext] [--dups] [--family image] [--limit 50]
  stopa search <case_id> "dotaz" [--source ID]   # full-text (FTS5)
  stopa timeline <case_id> [--type browser_history] [--path text] [-v]
  stopa image <case_id> /cesta/ke/obrazu.img       # disk image (TSK) [+ --no-carve]
  stopa mobile <case_id> /obraz.img [--password HESLO]  # mobilní FDE/FBE unlock + TSK
  stopa stats <case_id>
  stopa verify <case_id> [--limit N]                     # E1 — re-hash + kontrola integrity (SHA-256/MD5)
  stopa audit <case_id> [--limit N] [-v]                 # E1 — neměnná stopa operací
  stopa backup <case_id> [--out DIR]                     # E1 — záloha case DB (SQLite .backup + integrity)
  stopa report <case_id> [--format html|pdf] [--out DIR] [--lang cs|en]  # court-ready report + chain of custody
  stopa export <case_id> --what artifacts|timeline|correlations --format csv|json|jsonl|xml|stix|l2tcsv|uco [--limit N] [--out SOUBOR] [--bundle]
  stopa serve [--port 8473]                                 # web GUI (FastAPI)
  stopa profiles

DB: cases/<case_id>.db (přesaditelné přes STOPA_DB_DIR).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("stopa.cli")

from stopa.data.db import CaseDB
from stopa.domain.mem_forensics import DEFAULT_PLUGINS as _VOL_DEFAULT_PLUGINS
from stopa.domain.profiles import PROFILES, get_profile
from stopa.models import Case, EvidenceSource
from stopa.pipeline import load_hash_sets, process_source, run_timeline_intel


def _db_dir() -> Path:
    d = Path(os.environ.get("STOPA_DB_DIR", "cases"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _open_db(case_id: str) -> CaseDB:
    db_path = _db_dir() / f"{case_id}.db"
    if not db_path.exists():
        raise SystemExit(f"Případ '{case_id}' nenalezen (chybí {db_path})")
    return CaseDB(db_path)


def _load_ai_redact_pii() -> bool:
    """STP-019 — PII redaktor toggle ze settings.json (default ON = maskovat)."""
    p = _db_dir() / "settings.json"
    if not p.exists():
        return True
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True
    return bool(data.get("ai_redact_pii", True)) if isinstance(data, dict) else True


def case_examiner(db: CaseDB, case_id: str) -> str | None:
    """Znalec případu — výchozí actor pro audit log operací."""
    case = db.get_case(case_id)
    return case.examiner if case else None


# ---------------------------------------------------------------------------
# R0.4 — CLI UX: --json výstup + progress bary (Rich, volitelná závislost)
# ---------------------------------------------------------------------------

def _add_json_flag(p: argparse.ArgumentParser) -> None:
    """Přidá standardní `--json` flag (R0.4 — strojově čitelný výstup)."""
    p.add_argument(
        "--json", action="store_true", help="strojově čitelný výstup (validní JSON na stdout)"
    )


def _print_json(payload: object) -> None:
    """Vypíše validní JSON na stdout (ensure_ascii=False; datetime/Path → str)."""
    print(json.dumps(payload, ensure_ascii=False, default=str))


def _rich_progress():
    """Rich Progress pro dlouhé operace (R0.4) — None pokud Rich chybí nebo není TTY."""
    if not sys.stdout.isatty():
        return None  # testy / pipeline — zachovat plain output
    try:
        from rich.console import Console
        from rich.progress import BarColumn, Progress, TaskID, TimeElapsedColumn

        console = Console()

        class _Bar:
            def __init__(self) -> None:
                self._progress = Progress(
                    "[progress.description]{task.description}",
                    BarColumn(),
                    "[progress.percentage]{task.percentage:>3.0f}%",
                    TimeElapsedColumn(),
                    console=console,
                    transient=True,
                )
                self._progress.start()

            def add(self, description: str, total: int) -> TaskID:
                return self._progress.add_task(description, total=total or 100)

            def update(self, task_id: TaskID, completed: float) -> None:
                try:
                    self._progress.update(task_id, completed=completed)
                except Exception as exc:  # noqa: BLE001 — progress je kosmetický, nikdy nepádí
                    _log.debug("Rich progress update selhalo: %s", exc)

            def stop(self) -> None:
                try:
                    self._progress.stop()
                except Exception as exc:  # noqa: BLE001 — viz výše
                    _log.debug("Rich progress stop selhala: %s", exc)

        return _Bar()
    except ImportError:
        return None


def cmd_case_new(args: argparse.Namespace) -> int:
    case = Case(name=args.name, examiner=args.examiner, notes=args.notes)
    db = CaseDB(_db_dir() / f"{case.id}.db")
    db.add_case(case)
    # P0 Core C4: Ed25519 klíčový pár případu (graceful degradation bez cryptography).
    try:
        db.ensure_integrity_key()
    except RuntimeError:  # chybí balík 'cryptography' — kontrolní body se vypnou
        pass
    # E1 Evidence Manager: neměnná stopa — vznik případu
    db.log_operation(
        "case_created",
        actor=case.examiner,
        details={"case_id": case.id, "name": case.name},
    )
    db.close()
    if getattr(args, "json", False):
        _print_json(
            {
                "case_id": case.id,
                "name": case.name,
                "examiner": case.examiner,
                "db_path": str(_db_dir() / f"{case.id}.db"),
            }
        )
        return 0
    print(f"Případ vytvořen: {case.id}")
    print(f"  název:   {case.name}")
    if case.examiner:
        print(f"  znalec:  {case.examiner}")
    print(f"  DB:      {_db_dir() / f'{case.id}.db'}")
    return 0


def cmd_case_auto_export(args: argparse.Namespace) -> int:
    """STP-069 — zapnout/vypnut automatický ZIP bundle po dokončení analýzy."""
    db = _open_db(args.case_id)
    try:
        enabled = args.state == "on"
        ok = db.update_case(args.case_id, auto_export_enabled=enabled)
        if not ok:
            raise SystemExit(f"Případ '{args.case_id}' neexistuje")
        case = db.get_case(args.case_id)
        # STP-070 — volitelný interval periodického auto-bundle (minuty).
        minutes: int | None = None
        if args.interval is not None:
            from stopa.domain.export_schedule import parse_interval_minutes

            try:
                minutes = parse_interval_minutes(args.interval)
            except ValueError as exc:
                raise SystemExit(str(exc))
            ok_int = db.set_auto_export_interval(args.case_id, minutes)
            if not ok_int:
                raise SystemExit(f"Případ '{args.case_id}' neexistuje")
        db.log_operation(
            "auto_export_toggled",
            actor=case.examiner if case else None,
            details={
                "case_id": args.case_id,
                "enabled": enabled,
                "interval_minutes": minutes,  # STP-070 (None = bez změny)
            },
        )
    finally:
        db.close()
    if getattr(args, "json", False):
        _print_json(
            {
                "case_id": args.case_id,
                "auto_export_enabled": enabled,
                "interval_minutes": minutes,
            }
        )
        return 0
    state = "ZAPNUTO" if enabled else "VYPNUTO"
    print(f"Automatický export (STP-069): {state} pro případ {args.case_id}")
    if minutes is not None:
        print(f"Interval periodického auto-bundle (STP-070): {minutes} min")
    return 0


def cmd_case_auto_interval(args: argparse.Namespace) -> int:
    """STP-070 — nastavit/vymazat interval periodického auto-bundle."""
    db = _open_db(args.case_id)
    try:
        if args.minutes == "off":
            minutes: int | None = None
        else:
            from stopa.domain.export_schedule import parse_interval_minutes

            try:
                minutes = parse_interval_minutes(args.minutes)
            except ValueError as exc:
                raise SystemExit(str(exc))
        ok = db.set_auto_export_interval(args.case_id, minutes)
        if not ok:
            raise SystemExit(f"Případ '{args.case_id}' neexistuje")
        case = db.get_case(args.case_id)
        db.log_operation(
            "auto_export_interval_set",
            actor=case.examiner if case else None,
            details={"case_id": args.case_id, "interval_minutes": minutes},
        )
    finally:
        db.close()
    if getattr(args, "json", False):
        _print_json({"case_id": args.case_id, "interval_minutes": minutes})
        return 0
    if minutes is None:
        print(f"Interval periodického auto-bundle (STP-070): VYMÁZÁN pro případ {args.case_id}")
    else:
        print(f"Interval periodického auto-bundle (STP-070): {minutes} min pro případ {args.case_id}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    db = _open_db(args.case_id)
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
    if not json_mode:
        print(f"Zpracovávám {len(args.paths)} zdrojů (profil: {profile.name})")
    for path_str in args.paths:
        root = Path(path_str).expanduser()
        if not root.exists():
            print(f"Zdroj neexistuje: {root}", file=sys.stderr)
            rc = 2
            source_summaries.append({"path": str(root), "error": "zdroj neexistuje"})
            continue
        source = EvidenceSource(case_id=args.case_id, kind="folder" if root.is_dir() else "file", path=str(root))
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
            }
        )
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
    """Full-text search (FTS5) — AXIOM-style vyhledávání napříč případem."""
    db = _open_db(args.case_id)
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


def cmd_decrypt(args: argparse.Namespace) -> int:
    """F1.1 — BitLocker / FileVault dešifrování (libbde/libfvde + STOPABLOCK).

    Detekce podle ``--type`` a magic na offsetu 0:
      * STOPABLK → syntetický whole-volume formát (čistý Python, AES-XTS)
      * bitlocker → reálný BVE obraz přes libbde (recovery key primární cesta)
      * filevault → Apple FDE přes libfvde (heslo)

    Výsledek = RAW plaintext do souboru (default: <obraz>.decrypted.img).
    """
    from stopa.data import bde_fvde
    from stopa.domain.fde_bitlocker import (
        FdeError,
        decrypt_block_stream,
        is_bitlocker_image,
    )

    img_path = Path(args.image).expanduser()
    if not img_path.is_file():
        print(f"Obraz neexistuje: {img_path}", file=sys.stderr)
        return 2

    out_path = (
        Path(args.out).expanduser()
        if args.out
        else img_path.with_suffix(".decrypted.img")
    )

    try:
        with open(img_path, "rb") as f:
            head = f.read(36)

        if is_bitlocker_image(head):
            # syntetický STOPABLOCK — credential z recovery key nebo hesla
            cred = args.recovery_key or args.password
            if not cred:
                print("Zadejte --recovery-key nebo --password", file=sys.stderr)
                return 2
            tmp_path, header = decrypt_block_stream(img_path, cred)
            tmp_path.replace(out_path)
            size = out_path.stat().st_size
            desc = f"STOPABLOCK ({header.fs_type}, AES-XTS-{header.key_len // 2}) — dešifrováno {size / 1e6:.2f} MB"
        elif args.type == "bitlocker":
            if not bde_fvde.bde_available():
                print("Chybí libbde (nainstalujte runtime knihovnu — viz STOPA_BDE_LIB)", file=sys.stderr)
                return 3
            res = bde_fvde.decrypt_bitlocker(img_path, password=args.password, recovery_key=args.recovery_key)
            res.plaintext_path.replace(out_path)
            size = out_path.stat().st_size
            desc = f"{res.description} — {size / 1e6:.2f} MB"
        elif args.type == "filevault":
            if not bde_fvde.fvde_available():
                print("Chybí libfvde (nainstalujte runtime knihovnu — viz STOPA_BDE_LIB)", file=sys.stderr)
                return 3
            if not args.password:
                print("FileVault vyžaduje --password", file=sys.stderr)
                return 2
            res = bde_fvde.decrypt_filevault(img_path, password=args.password)
            res.plaintext_path.replace(out_path)
            size = out_path.stat().st_size
            desc = f"{res.description} — {size / 1e6:.2f} MB"
        else:
            print(
                "Neznámý typ obrazu — zadejte --type bitlocker|filevault (nebo je to STOPABLOCK)",
                file=sys.stderr,
            )
            return 4
    except FdeError as e:
        print(f"FDE dešifrování selhalo: {e}", file=sys.stderr)
        return 1
    except bde_fvde.BdeError as e:
        print(f"BitLocker dešifrování selhalo: {e}", file=sys.stderr)
        return 1
    except bde_fvde.FvdeError as e:
        print(f"FileVault dešifrování selhalo: {e}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        _print_json({"image": str(img_path), "out": str(out_path), "description": desc})
    else:
        print(desc)
        print(f"Plaintext: {out_path}")
    return 0


def cmd_memory_analyze(args: argparse.Namespace) -> int:
    """F1.2 — Memory Forensics přes Volatility 3 (ROADMAP V2 Fáze 1).

    Spustí vybrané vol pluginy na memory dumpu, mapuje JSON výstup na
    STOPA artefakty + cross-plugin anomaly rules a ukládá do case DB
    (idempotentní replace per file). PII zásada: surové credential material
    se neukládá — jen typ + fingerprint.

    Exit codes: 0 = OK · 1 = vol chyba · 2 = špatné argumenty · 3 = vol chybí
    """
    import hashlib

    from stopa.data import volatility as vol_mod
    from stopa.domain.mem_forensics import (
        DEFAULT_PLUGINS,
        MemForensicsError,
        apply_cross_plugin_rules,
        parse_plugin_output,
        summarize,
        validate_plugins,
    )
    from stopa.models import EvidenceSource, FileRecord

    json_mode = getattr(args, "json", False)
    dump_path = Path(args.dump).expanduser()
    if not dump_path.is_file():
        print(f"Memory dump neexistuje: {dump_path}", file=sys.stderr)
        return 2

    # explicitní --plugin má prioritu; jinak výchozí sada (pslist/netscan/ldrmodules/malfind)
    try:
        chosen = list(args.plugin or [])
        if args.with_defaults:
            chosen = list(DEFAULT_PLUGINS) + [p for p in chosen if p not in DEFAULT_PLUGINS]
        plugins = validate_plugins(chosen) if chosen else list(DEFAULT_PLUGINS)
    except MemForensicsError as e:
        print(str(e), file=sys.stderr)
        return 2

    if not vol_mod.vol_available():
        msg = (
            "Volatility 3 není nainstalovaná — `pip install volatility3` do STOPA venv, "
            "nebo STOPA_VOL_BIN=/cesta/k/vol"
        )
        if json_mode:
            _print_json({"error": msg})
        else:
            print(msg, file=sys.stderr)
        return 3

    db = _open_db(args.case_id)
    try:
        # provenance: zdroj + soubor v DB (FK stability artefaktů).
        # Re-analyza stejného dumpu drží původní source → upsert_file konflikt
        # (source_id, rel_path) → replace_artifacts_for_file = idempotentní.
        existing = next(
            (s for s in db.list_sources(args.case_id) if s.path == str(dump_path)), None
        )
        source = existing or EvidenceSource(case_id=args.case_id, kind="file", path=str(dump_path))
        if existing is None:
            db.add_source(source)
        sha256 = hashlib.sha256()
        with open(dump_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                sha256.update(chunk)
        rec = FileRecord(
            source_id=source.id,
            rel_path=dump_path.name,
            name=dump_path.name,
            size_bytes=dump_path.stat().st_size,
            sha256=sha256.hexdigest(),
            signature_type="memory_dump",
        )
        file_id = db.upsert_file(rec)

        bar = None if json_mode else _rich_progress()
        state: dict[str, object] = {"task": None}

        def _progress(done: int, total: int, label: str = "") -> None:
            if bar is not None:
                if state["task"] is None and total:
                    state["task"] = bar.add(label or f"vol {done}/{total}", total)
                elif state["task"] is not None:
                    bar.update(state["task"], done)  # type: ignore[arg-type]

        results = vol_mod.run_vol_plugins(
            str(dump_path), plugins, timeout_s=args.timeout, progress=_progress
        )

        all_arts: list = []
        plugin_errors: dict[str, str] = {}
        for plugin in plugins:  # deterministické pořadí (pořadí validace)
            res = results.get(plugin)
            if res is None:
                continue
            try:
                arts = parse_plugin_output(plugin, res.rows)
            except MemForensicsError as e:
                plugin_errors[plugin] = str(e)[:500]
                continue
            for a in arts:
                a.source_id = source.id
                a.file_id = file_id
                a.rel_path = dump_path.name
            all_arts.extend(arts)

        added_flags = apply_cross_plugin_rules(all_arts)
        db.replace_artifacts_for_file(file_id, all_arts)

        summary = summarize(all_arts)
        if not json_mode:
            print()
            print(f"  {summary['total']} artefaktů z {len(plugins)} pluginů "
                  f"(+{added_flags} anomaly flags)")
            for t, n in summary["by_type"].items():
                print(f"    {t}: {n}")
            if summary["anomaly_flags"]:
                print("  Anomalie: " + ", ".join(
                    f"{k}={v}" for k, v in summary["anomaly_flags"].items()
                ))
            for p_name, err in plugin_errors.items():
                print(f"  ! {p_name}: {err}", file=sys.stderr)

        if json_mode:
            _print_json({
                "dump": str(dump_path),
                "case_id": args.case_id,
                "file_id": file_id,
                "plugins_run": plugins,
                "plugin_errors": plugin_errors,
                **summary,
            })
        return 0 if not plugin_errors or all_arts else (1 if not all_arts else 0)
    finally:
        db.close()


def cmd_pcap_analyze(args: argparse.Namespace) -> int:
    """F1.3 — Síťová forenzika přes Scapy (ROADMAP V2 Fáze 1).

    Přečte .pcap/.pcapng, reasambloví TCP streamy, extrahuje soubory z
    HTTP/FTP/SMB a detekuje IoC (DNS tunneling, C2 beaconing, …). Artefakty
    do case DB (idempotentní replace per file), surové body do
    <root>/extracted/<case_id>/network/. PII zásada: v DB jen fingerprint.

    Exit codes: 0 = OK · 1 = parse chyba · 2 = špatné argumenty · 3 = scapy chybí
    """
    import hashlib

    from stopa.data import pcap_io
    from stopa.domain.net_forensics import (
        PARSER_VERSION,
        detect_ftp,
        detect_smb,
        extract_http,
        reassemble_flows,
        run_ioc_rules,
    )
    from stopa.domain.net_forensics import (
        fingerprint_value as fingerprint_net_value,
    )
    from stopa.domain.net_forensics import (
        summarize as net_summarize,
    )
    from stopa.models import Artifact, EvidenceSource, FileRecord

    json_mode = getattr(args, "json", False)
    pcap_path = Path(args.pcap).expanduser()
    if not pcap_path.is_file():
        print(f"PCAP soubor neexistuje: {pcap_path}", file=sys.stderr)
        return 2

    if not pcap_io.scapy_available():
        msg = ("Scapy není nainstalovaná — `pip install scapy` do STOPA venv "
               "(volitelná runtime závislost pro F1.3)")
        if json_mode:
            _print_json({"error": msg})
        else:
            print(msg, file=sys.stderr)
        return 3

    db = _open_db(args.case_id)
    try:
        # provenance + idempotentní re-analyza (stejný pattern jako F1.2)
        existing = next(
            (s for s in db.list_sources(args.case_id) if s.path == str(pcap_path)), None
        )
        source = existing or EvidenceSource(case_id=args.case_id, kind="file", path=str(pcap_path))
        if existing is None:
            db.add_source(source)
        sha256 = hashlib.sha256()
        with open(pcap_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                sha256.update(chunk)
        rec = FileRecord(
            source_id=source.id,
            rel_path=pcap_path.name,
            name=pcap_path.name,
            size_bytes=pcap_path.stat().st_size,
            sha256=sha256.hexdigest(),
            signature_type="network_capture",
        )
        file_id = db.upsert_file(rec)

        bar = None if json_mode else _rich_progress()
        state: dict[str, object] = {"task": None}

        def _progress(done: int, total: int, label: str = "") -> None:
            if bar is not None and state["task"] is None and total:
                state["task"] = bar.add(label or "pcap", total)

        try:
            records = pcap_io.read_pcap(pcap_path, max_packets=args.max_packets)
        except pcap_io.PcapParseError as e:
            if json_mode:
                _print_json({"error": str(e)})
            else:
                print(f"PCAP parse chyba: {e}", file=sys.stderr)
            return 1

        _progress(1, 3, "TCP reassembly")
        streams = reassemble_flows(records)

        arts: list[Artifact] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        def _mk(atype: str, title: str, details: dict, flags: list[str] | None = None) -> Artifact:
            return Artifact(
                source_id=source.id, file_id=file_id, rel_path=pcap_path.name,
                artifact_type=atype, title=title, details=details,
                confidence=0.7 if flags else 0.9,
                parser_version=PARSER_VERSION, extracted_at=datetime.fromisoformat(now_iso),
                anomaly_flags=list(flags or []),
            )

        # 1) flow artefakty (reassembly výsledek — jen metadata + fingerprint)
        for key, st in streams.items():
            arts.append(_mk(
                "network_flow", f"TCP {key.label()}",
                {
                    "bytes": len(st.data),
                    "sha256_prefix": hashlib.sha256(st.data).hexdigest()[:16],
                    "packet_count": st.packet_count,
                    "first_time": st.first_time,
                    "last_time": st.last_time,
                },
            ))

        # 2) HTTP extrakce + FTP/SMB detekce → soubory do <case>/extracted/network/
        out_dir = db.path.parent / "extracted" / args.case_id / "network"
        out_dir.mkdir(parents=True, exist_ok=True)
        written: list[str] = []
        for key, st in streams.items():
            http_files = extract_http(st.data[:1 << 20], key.label())
            for i, f_ in enumerate(http_files):
                safe_name = Path(f_.filename).name or f"body_{i}.bin"
                dest = out_dir / safe_name
                n = 1
                while dest.exists():
                    stem, suf = os.path.splitext(safe_name)
                    dest = out_dir / f"{stem}_{n}{suf}"
                    n += 1
                dest.write_bytes(f_.raw)
                written.append(str(dest))
                arts.append(_mk(
                    "file_extract_candidate", safe_name,
                    {
                        "size_bytes": f_.size_bytes,
                        "sha256_prefix": f_.sha256_prefix,
                        "content_type": f_.content_type,
                        "extracted_to": str(dest),
                        "flow": key.label(),
                    },
                ))
            ftp_cmds = detect_ftp(st.data[:1 << 20])
            if ftp_cmds:
                arts.append(_mk("ftp_command", f"FTP {key.label()}",
                                {"commands": ftp_cmds}, ["ftp_activity"]))
            smb_hits = detect_smb(st.data[:1 << 20])
            if smb_hits:
                arts.append(_mk("smb_session", f"SMB {key.label()}",
                                {"headers": smb_hits}, ["smb_activity"]))

        # 3) DNS query artefakty (unikátní QNAME + fingerprint)
        seen_qnames: set[str] = set()
        for r in records:
            if r.dns_qname and r.dns_qname not in seen_qnames:
                seen_qnames.add(r.dns_qname)
                arts.append(_mk("dns_query", r.dns_qname, {
                    "fingerprint": fingerprint_net_value(r.dns_qname),
                    "src_ip": r.src_ip,
                }))

        # 4) IoC pravidla → artefakty ioc_<pattern>
        _progress(2, 3, "IoC detekce")
        iocs = run_ioc_rules(records, streams)
        for hit in iocs["dns_tunneling"]:
            arts.append(_mk("ioc_dns_tunneling", str(hit.get("qname")),
                            dict(hit), ["dns_tunneling"]))
        for hit in iocs["c2_beaconing"]:
            arts.append(_mk("ioc_c2_beaconing",
                            f"{hit.get('dst_ip')}:{hit.get('dst_port')}",
                            dict(hit), ["c2_beaconing"]))
        for hit in iocs["http_ioc"]:
            arts.append(_mk(
                "ioc_http", str(hit.get("url") or hit.get("flow")),
                {"flow": hit.get("flow"), "flags": hit.get("flags")},
                list(hit.get("flags") or []),
            ))
        if iocs["unusual_high_port_tcp"]:
            arts.append(_mk("ioc_unusual_high_port", f"{len(iocs['unusual_high_port_tcp'])} flowů",
                            {"flows": iocs["unusual_high_port_tcp"]}, ["unusual_high_port"]))

        db.replace_artifacts_for_file(file_id, arts)

        stats = net_summarize(records)
        if not json_mode:
            print()
            print(f"  {len(arts)} artefaktů z {stats['total_packets']} paketů "
                  f"(tcp={stats.get('tcp', 0)}, udp={stats.get('udp', 0)}, dns={stats['dns_queries']})")
            if written:
                print(f"  extrahováno souborů: {len(written)} → {out_dir}")
        if json_mode:
            _print_json({
                "pcap": str(pcap_path),
                "case_id": args.case_id,
                "file_id": file_id,
                **stats,
                "artifacts": len(arts),
                "extracted_files": written,
                "ioc_counts": {
                    "dns_tunneling": len(iocs["dns_tunneling"]),
                    "c2_beaconing": len(iocs["c2_beaconing"]),
                    "http_ioc": len(iocs["http_ioc"]),
                    "unusual_high_port_tcp": len(iocs["unusual_high_port_tcp"]),
                },
            })
        return 0
    finally:
        db.close()


def cmd_antiforensics(args: argparse.Namespace) -> int:
    """F1.4 — Anti-Forensics detekce (ROADMAP V2 Fáze 1).

    Prohledá artefakty případu po stopech maskování důkazů: timestomping,
    log clearing (EVTX 1102 + mezery v záznamech), USN journal truncation,
    hidden partitions (MBR), LSB steganografie v PNG/JPG a signatury
    anti-forenzních nástrojů. Nálezy uloží jako artefakty ``antiforensics/<type>``
    s confidence + timeline alerty (idempotentní replace per scan).

    Exit codes: 0 = OK · 1 = analytická chyba · 2 = špatné argumenty
    """
    import re as _re

    from stopa.domain import anti_forensics as af
    from stopa.models import Artifact, EvidenceSource, FileRecord

    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    try:
        # ── sběr vstupů — normalizace DB → dicty pro čistou doménovou vrstvu ──
        files_norm = [
            {
                "path": f.rel_path,
                "name": f.name,
                "mtime": f.mtime.isoformat() if f.mtime else None,
                "ctime": f.ctime.isoformat() if f.ctime else None,
                "atime": f.atime.isoformat() if f.atime else None,
            }
            for f in db.list_files()
        ]

        events_norm = []
        for a in db.list_artifacts(artifact_type="event_log_entry"):
            d = a.details or {}
            events_norm.append({
                "event_id": d.get("event_id"),
                "record_id": d.get("record_number"),
                "timestamp": a.timestamp.isoformat() if a.timestamp else None,
            })

        usn_norm = []
        for a in db.list_artifacts(artifact_type="usn_record"):
            m = _re.match(r"^USN (\d+):", a.title or "")
            if not m:
                continue
            usn_norm.append({
                "usn": int(m.group(1)),
                "reason": (a.details or {}).get("reason") or "",
            })

        # stego kandidáti — PNG/JPG v případu, vyřešené přes cesty zdrojů
        sources = {s.id: s for s in db.list_sources(args.case_id)}
        stego_paths: list[str] = []
        for f in db.list_files():
            ext = (f.extension or "").lower().lstrip(".")
            if ext not in ("png", "jpg", "jpeg"):
                continue
            src = sources.get(f.source_id)
            if src is None:
                continue
            cand = Path(src.path).expanduser() / f.rel_path
            if cand.is_file():
                stego_paths.append(str(cand))

        # volitelný diskový obraz --image (MBR/partition table + integrity)
        img_p: Path | None = None
        header512: bytes | None = None
        image_size = 0
        image_ext = ""
        img_arg = getattr(args, "image", None)
        if img_arg:
            img_p = Path(img_arg).expanduser()
            if not img_p.is_file():
                msg = f"Diskový obraz neexistuje: {img_p}"
                print(msg, file=sys.stderr)
                return 2
            with open(img_p, "rb") as fh:
                header512 = fh.read(512)
            image_size = img_p.stat().st_size
            image_ext = img_p.suffix.lstrip(".").lower()

        # ── detekce (čistá doménová vrstva, bez I/O mimo stego/obraz) ──
        report = af.detect_anti_forensics(
            files=files_norm, events=events_norm, usn_records=usn_norm,
            image_path=str(img_p) if img_p else None,
            image_size_bytes=image_size, image_ext=image_ext,
            header512=header512, stego_paths=stego_paths,
        )

        # ── ukládání: idempotentní replace pod syntetickým scan zdrojem (pattern F1.2/F1.3) ──
        marker = f"{args.case_id}/antiforensics-scan"
        existing_src = next(
            (s for s in db.list_sources(args.case_id) if s.path == marker), None
        )
        scan_source = existing_src or EvidenceSource(
            case_id=args.case_id, kind="file", path=marker
        )
        if existing_src is None:
            db.add_source(scan_source)
        rec = FileRecord(
            source_id=scan_source.id, rel_path="antiforensics-scan.bin",
            name="antiforensics-scan.bin", size_bytes=0, signature_type="analysis",
        )
        scan_file_id = db.upsert_file(rec)

        sev_conf = {"high": 0.9, "medium": 0.7, "low": 0.5}
        now_dt = datetime.now(timezone.utc)
        arts: list[Artifact] = []
        for check in sorted(report["by_check"]):
            items = report["by_check"][check]
            for i, item in enumerate(items):
                ev = item.get("evidence") or {}
                ts_dt = now_dt
                ts_origin = "derived"
                raw_ts = ev.get("timestamp")
                if raw_ts:
                    try:
                        parsed = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        ts_dt, ts_origin = parsed, "source"
                    except ValueError:
                        pass
                arts.append(Artifact(
                    source_id=scan_source.id, file_id=scan_file_id,
                    rel_path="antiforensics-scan.bin",
                    artifact_type=f"antiforensics/{check}",
                    title=item["description"][:160],
                    details={
                        "severity": item["severity"],
                        "risk_score": report["risk_score"],
                        **ev,
                    },
                    confidence=sev_conf.get(item["severity"], 0.5),
                    parser_version=af.PARSER_VERSION,
                    extracted_at=now_dt, timestamp=ts_dt, ts_origin=ts_origin,
                    anomaly_flags=[f"antiforensics:{check}"],
                ))
        # timeline alerty — idempotentní: scan zdroj je dedikovaný. Staré alerty
        # smažeme PŘED výměnou artifactů — odkazují na artefakty, které replace
        # maží, a FK timeline_events.artifact_id nemá ON DELETE (jinak porušení).
        db.clear_timeline_events(source_id=scan_source.id)
        db.replace_artifacts_for_file(scan_file_id, arts)
        for a in arts:
            check_name = a.artifact_type.split("/", 1)[1]
            db.add_timeline_event(
                source_id=scan_source.id, artifact_id=a.id, file_id=scan_file_id,
                rel_path="antiforensics-scan.bin",
                event_type=f"antiforensics_{check_name}",
                ts_utc=a.timestamp or now_dt, title=a.title, confidence=a.confidence,
                parser_version=af.PARSER_VERSION, extracted_at=now_dt,
                anomaly_flags=tuple(a.anomaly_flags), ts_origin=a.ts_origin,
            )
        db.commit()  # add_timeline_event nekonektuje commit — explicitně upevnit

        by_check_summary = {c: len(v) for c, v in report["by_check"].items()}
        if not json_mode:
            total = report["findings_count"]
            print()
            print(f"  Anti-forensics scan: {total} nálezů "
                  f"(risk score {report['risk_score']})")
            for check, n in sorted(by_check_summary.items()):
                print(f"    antiforensics/{check}: {n}")
            if not total:
                print("  — žádné stopy maskování důkazů nenalezeny ✓")
        if json_mode:
            _print_json({
                "case_id": args.case_id,
                **report,
                "artifacts_saved": len(arts),
                "files_scanned": len(files_norm),
                "events_scanned": len(events_norm),
                "usn_records_scanned": len(usn_norm),
                "stego_candidates": len(stego_paths),
            })
        return 0
    except Exception as e:  # noqa: BLE001 — analytická chyba ≠ pád CLI
        if json_mode:
            _print_json({"error": str(e)})
        else:
            print(f"Anti-forensics analýza selhala: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()


def cmd_profiles(args: argparse.Namespace) -> int:
    if getattr(args, "json", False):
        _print_json({
            name: {
                "compute_md5": p.compute_md5,
                "compute_sha1": p.compute_sha1,
                "compute_sha256": p.compute_sha256,
                "signature_analysis": bool(p.signature_analysis),
                "flag_bad_extensions": bool(p.flag_bad_extensions),
                "deduplicate": bool(p.deduplicate),
            }
            for name, p in sorted(PROFILES.items())
        })
        return 0
    print("Dostupné processing profily:")
    for name, p in sorted(PROFILES.items()):
        algs = "+".join(
            a for a, on in (("MD5", p.compute_md5), ("SHA1", p.compute_sha1), ("SHA256", p.compute_sha256)) if on
        ) or "—"
        print(f"  {name:10} hash={algs:8} signatury={'✓' if p.signature_analysis else '—'} "
              f"bad-ext={'✓' if p.flag_bad_extensions else '—'} dedupe={'✓' if p.deduplicate else '—'}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Forenzní report (FÁZE 7) — court-ready HTML/PDF + chain of custody."""
    from stopa.presentation.case_report import (
        default_report_name,
        generate_html_report,
        generate_pdf_report,
    )

    db = _open_db(args.case_id)
    out_dir = Path(args.out).expanduser() if args.out else _db_dir().parent / "reports"
    fmt = args.format
    lang = getattr(args, "lang", None)  # E10 i18n — výchozí cs řeší report vrstva
    try:
        if fmt == "pdf":
            path = generate_pdf_report(
                db, args.case_id, out_dir / default_report_name(args.case_id, "pdf"), lang=lang
            )
        else:
            path = generate_html_report(
                db, args.case_id, out_dir / default_report_name(args.case_id, "html"), lang=lang
            )
    except RuntimeError as e:
        if getattr(args, "json", False):
            _print_json({"error": str(e), "case_id": args.case_id})
        else:
            print(f"Report selhal: {e}", file=sys.stderr)
        db.close()
        return 2
    db.close()
    if getattr(args, "json", False):
        _print_json({"path": str(path), "format": fmt, "case_id": args.case_id})
        return 0
    print(f"Report vygenerován ({fmt.upper()}): {path}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """E10 — export dat případu do CSV/JSON (artifacts / timeline / correlations)."""
    from stopa.domain.export import (
        ARTIFACT_COLUMNS,
        CORRELATION_COLUMNS,
        TIMELINE_COLUMNS,
        artifact_records,
        correlation_records,
        timeline_records,
        to_csv,
        to_json,
        to_jsonl,
        to_l2tcsv,
        to_stix_bundle,
        to_xml,
    )
    from stopa.domain.uco import to_uco_json

    db = _open_db(args.case_id)

    # STP-068 — ZIP bundle všech datasetů (deterministický, s manifestem + SHA-256).
    if getattr(args, "bundle", False):
        from stopa.domain.export import to_zip_bundle

        case = db.get_case(args.case_id)
        if case is None:
            raise SystemExit(f"Případ '{args.case_id}' nenalezen v DB")
        generated_at_utc = case.created_at.isoformat()
        datasets = {
            "artifacts": artifact_records(db.list_artifacts(limit=args.limit)),
            "timeline": timeline_records(db.list_timeline_events(limit=args.limit)),
            "correlations": correlation_records(db.list_correlations(args.case_id)),
        }
        data = to_zip_bundle(datasets, args.case_id, generated_at_utc)
        out_path = Path(args.out).expanduser() if args.out else None
        if out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(data)
            print(f"ZIP bundle (3 datasety): {out_path}")
        else:
            sys.stdout.buffer.write(data)
        db.log_operation(
            "data_exported",
            actor=case_examiner(db, args.case_id),
            details={"what": "bundle", "format": "zip"},
        )
        db.add_integrity_checkpoint("export")
        db.close()
        return 0

    if args.what == "artifacts":
        records = artifact_records(db.list_artifacts(limit=args.limit))
        columns = ARTIFACT_COLUMNS
    elif args.what == "timeline":
        records = timeline_records(db.list_timeline_events(limit=args.limit))
        columns = TIMELINE_COLUMNS
    else:  # correlations
        records = correlation_records(db.list_correlations(args.case_id))
        columns = CORRELATION_COLUMNS

    if args.format == "csv":
        text = to_csv(records, columns)
    elif args.format == "jsonl":
        text = to_jsonl(records)
    elif args.format == "xml":
        text = to_xml(records, dataset=args.what)
    elif args.format == "stix":
        text = to_stix_bundle(records, dataset=args.what)
    elif args.format == "l2tcsv":
        text = to_l2tcsv(records, dataset=args.what)
    elif args.format == "uco":
        text = to_uco_json(records, dataset=args.what)
    else:  # json (default)
        text = to_json(records)

    out_path = Path(args.out).expanduser() if args.out else None
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(f"Export {len(records)} záznamů ({args.format.upper()}): {out_path}")
        # P0 Core C4: export manifest (deterministický hash + Ed25519 podpis).
        _write_export_manifest(db, args.case_id, out_path, text.encode("utf-8"))
    else:
        sys.stdout.write(text if text.endswith("\n") or args.format == "json" else text + "\n")
    db.log_operation(
        "data_exported",
        actor=case_examiner(db, args.case_id),
        details={"what": args.what, "format": args.format, "records": len(records)},
    )
    # P0 Core C4: kontrolní bod po exportu.
    db.add_integrity_checkpoint("export")
    db.close()
    return 0


def _write_export_manifest(db: CaseDB, case_id: str, out_path: Path, content: bytes) -> None:
    """P0 Core C4 — manifest vedle exportního souboru (reprodukovatelnost + podpis).

    Deterministický hash (stejný vstup + verze STOPA = stejný hash); pokud případ
    má Ed25519 klíč, manifest je podepsán (nezávislá kontrola veřejným klíčem).
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        tool_version = version("stopa")
    except PackageNotFoundError:  # dev run bez instalace / chybějící metadata
        tool_version = "1.0.0"
    from stopa.domain.integrity import build_manifest, manifest_hash, sign_manifest

    name = out_path.name
    manifest = build_manifest(case_id, tool_version, [(name, content)])
    payload: dict = {
        "case_id": case_id,
        "tool_version": tool_version,
        "manifest_hash": manifest_hash(manifest),
        "entries": [
            {"name": e.name, "sha256": e.sha256, "size": e.size} for e in manifest.entries
        ],
    }
    priv_row = db.conn.execute(
        "SELECT value FROM meta WHERE key = 'integrity_priv'"
    ).fetchone()
    if priv_row is not None and priv_row["value"]:
        payload["signature_b64"] = sign_manifest(manifest, priv_row["value"])
    manifest_path = out_path.with_name(out_path.name + ".manifest.json")
    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Export manifest: {manifest_path}")


def cmd_plaso_import(args: argparse.Namespace) -> int:
    """STP-057 — Plaso import: l2tcsv soubor → case (source + artifacts + timeline)."""
    from stopa.domain.plaso_import import import_l2tcsv

    path = Path(args.path).expanduser()
    if not path.is_file():
        raise SystemExit(f"Soubor nenalezen: {path}")
    text = path.read_text(encoding="utf-8")

    db = _open_db(args.case_id)
    try:
        summary = import_l2tcsv(db, args.case_id, text, source_path=str(path))
        if not getattr(args, "json", False):
            print(
                f"Plaso import: {summary['events_total']} událostí → "
                f"{summary['artifacts_imported']} artifactů, "
                f"{summary['timeline_events']} timeline eventů "
                f"(bez času: {summary['skipped_no_time']}) — source {summary['source_id']}"
            )
        db.log_operation(
            "plaso_import",
            actor=case_examiner(db, args.case_id),
            details={**summary, "file": str(path)},
        )
        # P0 Core C4: kontrolní bod po importu.
        db.add_integrity_checkpoint("plaso-import")
    finally:
        db.close()
    if getattr(args, "json", False):
        _print_json({**summary, "file": str(path)})
    return 0


def cmd_timesketch_push(args: argparse.Namespace) -> int:
    """STP-059 — Timesketch push: case data → nový sketch + timeline (l2tcsv)."""
    from stopa.data.timesketch_client import (
        TimesketchClient,
        TimesketchError,
        settings_from_env,
    )
    from stopa.domain.export import (
        artifact_records,
        correlation_records,
        timeline_records,
    )
    from stopa.domain.timesketch_push import push_to_timesketch

    db = _open_db(args.case_id)
    try:
        case = db.get_case(args.case_id)
        if args.what == "artifacts":
            records = artifact_records(db.list_artifacts())
        elif args.what == "timeline":
            records = timeline_records(db.list_timeline_events())
        else:  # correlations
            records = correlation_records(db.list_correlations(args.case_id))

        client = TimesketchClient(settings_from_env())
        try:
            summary = push_to_timesketch(client, case.name if case else args.case_id,
                                         args.what, records, limit=args.limit)
        except (TimesketchError, ValueError) as exc:
            raise SystemExit(f"Timesketch push selhal: {exc}") from exc

        if not getattr(args, "json", False):
            print(
                f"Timesketch push: {summary['records']} záznamů "
                f"(celkem {summary['total_records']}) → "
                f"sketch {summary['sketch_id']}, timeline {summary['timeline_id']} "
                f"(task {summary['task_id']})"
            )
        db.log_operation(
            "timesketch_pushed",
            actor=case_examiner(db, args.case_id),
            details={**summary, "what": args.what},
        )
        # P0 Core C4: kontrolní bod po pushi.
        db.add_integrity_checkpoint("timesketch-push")
    finally:
        db.close()
    if getattr(args, "json", False):
        _print_json({**summary, "what": args.what})
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """E1 Evidence Manager: re-hash všech souborů v případu a porovnání s evidencí.

    Důkaz integrity — SHA-256 + MD5 (chunked, read-only přístup k originálům).
    Výsledek se zapíše do neměnného audit logu (`hash_verified`).
    """
    from stopa.domain.hashing import hash_file

    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    sources = db.list_sources(args.case_id)
    if not sources:
        if json_mode:
            _print_json({"ok": 0, "mismatched": 0, "missing": 0, "skipped": 0,
                         "problems": [], "sources": 0})
        else:
            print("(žádné evidence sources)")
        db.close()
        return 0

    ok = mismatched = missing = skipped = 0
    problems: list[str] = []
    for src in sources:
        root = Path(src.path).expanduser()
        rows = db.conn.execute(
            "SELECT rel_path, sha256, md5 FROM files WHERE source_id = ? ORDER BY rel_path",
            (src.id,),
        ).fetchall()
        for r in rows:
            if root.is_file():
                p = root  # file zdroj — rel_path je jen jméno souboru
            else:
                p = root / r["rel_path"]
            if not p.exists():
                missing += 1
                problems.append(f"CHYBÍ: {src.path}/{r['rel_path']}")
                continue
            try:
                digests = hash_file(p, ["md5", "sha256"])
            except OSError as e:
                skipped += 1
                problems.append(f"NELZE ČÍST: {r['rel_path']}: {e}")
                continue
            bad = []
            if r["sha256"] and digests.get("sha256") != r["sha256"]:
                bad.append("SHA-256")
            if r["md5"] and digests.get("md5") != r["md5"]:
                bad.append("MD5")
            if bad:
                mismatched += 1
                problems.append(f"ROZDÍL ({', '.join(bad)}): {r['rel_path']}")
            else:
                ok += 1

    db.log_operation(
        "hash_verified",
        actor=case_examiner(db, args.case_id),
        details={
            "ok": ok,
            "mismatched": mismatched,
            "missing": missing,
            "skipped": skipped,
        },
    )
    if json_mode:
        _print_json({
            "ok": ok, "mismatched": mismatched, "missing": missing,
            "skipped": skipped, "problems": problems[: args.limit],
            "sources": len(sources),
        })
    else:
        print(f"Integrita: {ok} OK, {mismatched} rozdílů, {missing} chybí, {skipped} nečitelných")
        for p in problems[: args.limit]:
            print(f"  ! {p}")
        if len(problems) > args.limit:
            print(f"  … a dalších {len(problems) - args.limit}")
    db.close()
    return 1 if (mismatched or missing) else 0


def cmd_integrity(args: argparse.Namespace) -> int:
    """P0 Core C4 — Evidence Integrity 2.0: hash chaining + Ed25519 kontrolní body."""
    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)

    # 1) Hash chaining audit logu (ověřitelné bez klíče).
    report = db.verify_audit_chain()
    if not json_mode:
        if report.ok:
            print(f"Hash řetězec audit logu: OK ({report.rows_checked} řádků)")
        else:
            print(
                f"Hash řetězec audit logu: ROZBITÝ na řádku {report.broken_at_id}"
                f" — {report.reason}",
                file=sys.stderr,
            )

    # 2) Ed25519 klíč + kontrolní body.
    pub = db.integrity_public_key()
    if args.init_key and pub is None:
        _, new_pub = db.ensure_integrity_key()
        if not json_mode:
            print(f"Ed25519 klíč vygenerován: {new_pub[:16]}…")
        pub = new_pub
    elif pub is not None and not json_mode:
        print(f"Ed25519 veřejný klíč: {pub[:16]}… ({len(pub)} b64 znaků)")
    elif pub is None and not args.init_key and not json_mode:
        print("Ed25519 klíč: nevygenerován (použij --init-key)")

    cps = db.list_integrity_checkpoints()
    results: list[dict] = []
    if not cps and not json_mode:
        print("Kontrolní body: 0")
    elif cps:
        results = db.verify_integrity_checkpoints()
        ok_count = sum(1 for r in results if r.get("ok"))
        if not json_mode:
            print(f"Kontrolní body: {len(cps)} ({ok_count} platných podpisů)")
            for cp, res in zip(cps, results):
                mark = "✓" if res.get("ok") else "✗"
                print(
                    f"  [{mark}] #{cp['id']} audit_row={cp['audit_row_id']} "
                    f"{cp['reason'] or '—'} {cp['ts']}"
                )

    # 3) Nový kontrolní bod na požádání.
    new_cp_id = None
    if args.checkpoint:
        if db.integrity_public_key() is None:
            print("Klíč nevygenerován — použij --init-key", file=sys.stderr)
            db.close()
            return 2
        new_cp_id = db.add_integrity_checkpoint(args.checkpoint)
        if new_cp_id is None:
            print("Kontrolní bod neuložen (chybí klíč)", file=sys.stderr)
            db.close()
            return 2
        if not json_mode:
            print(f"Nový kontrolní bod #{new_cp_id} ({args.checkpoint})")

    if json_mode:
        _print_json({
            "audit_chain_ok": report.ok,
            "rows_checked": report.rows_checked,
            "broken_at_id": report.broken_at_id,
            "reason": None if report.ok else report.reason,
            "public_key": pub,
            "checkpoints_total": len(cps),
            "checkpoints_valid": sum(1 for r in results if r.get("ok")),
            "new_checkpoint_id": new_cp_id,
        })
    db.close()
    # exit code: 0 = řetězec OK, 1 = rozbitý řetězec
    return 0 if report.ok else 1


def cmd_replay(args: argparse.Namespace) -> int:
    """P0 Core C5 — Reproducibility Engine: opakovat zaznamenanou operaci + porovnání."""
    from stopa.pipeline import replay_extract

    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    ops = db.list_operations(case_id=args.case_id, op_type="extract")
    if not ops:
        if json_mode:
            _print_json({"error": "no_extract_operations"})
        else:
            print("Žádné zaznamenané extract operace (předtím `stopa add`)", file=sys.stderr)
        db.close()
        return 2

    target = db.get_operation(args.op) if args.op else ops[-1]
    if target is None:
        if json_mode:
            _print_json({"error": "operation_not_found", "op_id": args.op})
        else:
            print(f"Operace nenalezena: {args.op}", file=sys.stderr)
        db.close()
        return 2

    src = db.get_source(target.source_id or "")
    if src is None:
        if json_mode:
            _print_json({"error": "source_not_found", "source_id": target.source_id})
        else:
            print(f"Zdroj operace neexistuje: {target.source_id}", file=sys.stderr)
        db.close()
        return 2
    root = Path(src.path).expanduser()
    if not root.exists():
        if json_mode:
            _print_json({"error": "source_path_missing", "path": str(root)})
        else:
            print(f"Zdroj už není na disku: {root}", file=sys.stderr)
        db.close()
        return 2

    if not json_mode:
        print(f"Replay operace {target.id} (zdroj: {src.path})")
    res = replay_extract(target, root)

    if not json_mode:
        if res.inputs_identical:
            print("Vstupní soubory: OK (SHA-256 shodné se záznamem)")
        else:
            print(f"Vstupní soubory: ZMĚNĚNY ({len(res.input_diffs)} rozdílů)", file=sys.stderr)
            for d in res.input_diffs[:10]:
                print(f"  ! {d}", file=sys.stderr)

        if res.outputs_identical:
            print("Výstupní souhrn: IDENTICKÝ (operace je reprodukovatelná)")
        else:
            print(f"Výstupní souhrn: LIŠÍ ({len(res.output_diffs)} rozdílů)", file=sys.stderr)
            for d in res.output_diffs[:10]:
                print(f"  ! {d}", file=sys.stderr)

    db.log_operation(
        "operation_replayed",
        actor=case_examiner(db, args.case_id),
        details={
            "op_id": target.id,
            "inputs_identical": res.inputs_identical,
            "outputs_identical": res.outputs_identical,
        },
    )
    db.close()
    if json_mode:
        _print_json({
            "op_id": target.id,
            "source_path": src.path,
            "inputs_identical": res.inputs_identical,
            "outputs_identical": res.outputs_identical,
            "input_diffs": res.input_diffs[:10],
            "output_diffs": res.output_diffs[:10],
        })
    return 0 if (res.inputs_identical and res.outputs_identical) else 1


def cmd_benchmark(args: argparse.Namespace) -> int:
    """P0 Core C6 — Benchmark Engine: deterministické benchmarky + detekce regresí."""
    from stopa.data.benchmark_engine import (
        check_regressions,
        run_benchmark,
        save_history,
    )

    json_mode = getattr(args, "json", False)
    if not json_mode:
        print(f"Benchmark suite: {args.suite}")
    results = run_benchmark(suite=args.suite)
    if not results:
        if json_mode:
            _print_json({"suite": args.suite, "results": [], "error": "all_workloads_failed"})
        else:
            print("Žádné výsledky (selhaly všechny workloads)", file=sys.stderr)
        return 2

    if not json_mode:
        for r in results:
            print(
                f"  {r.name:<24} {r.duration_ms:>10.3f} ms | "
                f"RAM peak {r.ram_peak_bytes / 1e6:>8.2f} MB | artefakty {r.artifacts}"
            )

    # historie + regresní detekce (jen s případem — meta benchmark_history)
    warnings: list = []
    if args.case_id:
        db = _open_db(args.case_id)
        warnings = check_regressions(db, results)
        save_history(db, results)
        db.log_operation(
            "benchmark_run",
            actor=case_examiner(db, args.case_id),
            details={"suite": args.suite, "results": len(results)},
        )
        db.close()
        if not json_mode:
            if warnings:
                print(f"\n⚠ Regrese výkonu (>20% proti baseline): {len(warnings)}")
                for w in warnings:
                    print(
                        f"  ! {w.name}: {w.baseline_ms:.3f} → {w.current_ms:.3f} ms "
                        f"(+{w.delta_pct}%)"
                    )
            else:
                print("\nRegrese výkonu: žádná (baseline OK)")

    if json_mode:
        _print_json({
            "suite": args.suite,
            "results": [
                {"name": r.name, "duration_ms": r.duration_ms,
                 "ram_peak_bytes": r.ram_peak_bytes, "artifacts": r.artifacts}
                for r in results
            ],
            "regressions": [
                {"name": w.name, "baseline_ms": w.baseline_ms,
                 "current_ms": w.current_ms, "delta_pct": w.delta_pct}
                for w in warnings
            ],
        })
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """P0 Core C6 — Evidence Validation Report per případ."""
    from stopa.data.validation_report import build_validation_report, report_to_json

    db = _open_db(args.case_id)
    rep = build_validation_report(db, args.case_id)
    cov = rep["coverage"]

    if not getattr(args, "json", False):
        print(f"Validační report: {args.case_id} ({rep['total_artifacts']} artefaktů)")
        for status, n in sorted(rep["by_status"].items()):
            print(f"  {status}: {n}")
        print(
            f"Coverage validace: {cov['covered_artifacts']}/{cov['total_artifacts']} "
            f"({cov['coverage_pct']}%)"
        )
        if cov["uncovered_parsers"]:
            print("Nepokrivené parsery: " + ", ".join(cov["uncovered_parsers"]))

    if args.json:
        print(report_to_json(rep))
    db.close()
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    """P0 Intelligence I1 — AI orchestrace (5 agentů, auto/explicitní routing)."""
    import json as _json

    from stopa.data.lmstudio_client import LmStudioClient, LmStudioUnavailable
    from stopa.intelligence import (
        OrchestrationError,
        audit_ai_query,
        build_case_context,
        orchestrate,
        prompt_hash,
        retrieve,
    )

    db = _open_db(args.case_id)
    try:
        client = LmStudioClient()
        health = client.health()
        if not health["available"]:
            if getattr(args, "json", False):
                _print_json({"error": "lmstudio_unavailable"})
            else:
                print("AI nedostupná — spusťte LM Studio (localhost:1234)")
            return 1

        context = build_case_context(db, args.case_id)
        # P0 Intelligence I2 — Forensic RAG: retrieval napříč vrstvami
        rag = retrieve(args.question, db=db, case_id=args.case_id)
        # STP-019 — PII redaktor (settings.json toggle, default ON)
        redact_pii = _load_ai_redact_pii()
        json_mode = getattr(args, "json", False)
        # R0.4 — progress bar u analyze (LLM volání trvá řádově desítky sekund)
        bar = None if json_mode else _rich_progress()
        task_id = bar.add("AI orchestrace…", 100) if bar is not None else None
        try:
            result = orchestrate(
                client.chat,
                context,
                args.question,
                agent_id=args.agent,
                rag=rag,
                redact_pii=redact_pii,
            )
        except LmStudioUnavailable as exc:
            if json_mode:
                _print_json({"error": "lmstudio_unavailable", "detail": str(exc)})
            else:
                print(f"AI nedostupná: {exc}")
            return 1
        except OrchestrationError as exc:
            if json_mode:
                _print_json({"error": "orchestration_failed", "detail": str(exc)})
            else:
                print(f"AI orchestrace selhala: {exc}")
            return 1
        finally:
            if bar is not None and task_id is not None:
                try:
                    bar.update(task_id, completed=100)
                    bar.stop()
                except Exception as exc:  # noqa: BLE001 — progress je kosmetický
                    _log.debug("Rich progress completion selhala: %s", exc)

        # audit AI dotazu (evidence modelu + promptu) — analysis_operations
        from stopa.intelligence.ai_orchestrator import build_prompt, route_agent

        profile = route_agent(args.question, args.agent)
        ph = prompt_hash(
            build_prompt(profile, context, args.question, rag=rag, redact_pii=redact_pii)
        )
        audit_ai_query(
            db,
            case_id=args.case_id,
            question=args.question,
            model=str(health.get("model") or None),
            prompt_sha256=ph,
            citations=result.citations,
            agent=result.agent_id,
        )

        db.log_operation(
            "ai_analyzed",
            actor="cli",
            details={
                "agent": result.agent_id,
                "question": args.question[:200],
                "citations": result.citations,
                "duration_ms": round(result.duration_ms, 1),
            },
        )

        if args.json:
            print(
                _json.dumps(
                    {
                        "agent": result.agent_id,
                        "output": result.output.model_dump(mode="json"),
                        "citations": result.citations,
                        "rag": {
                            "case": len(rag.case_chunks),
                            "technical": len(rag.technical_chunks),
                            "knowledge": len(rag.knowledge_chunks),
                        },
                        "prompt_chars": result.prompt_chars,
                        "duration_ms": round(result.duration_ms, 1),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            print(f"Agent: {result.agent_id} ({result.duration_ms:.0f} ms)")
            print(_json.dumps(result.output.model_dump(mode="json"), ensure_ascii=False, indent=2))
            if result.citations:
                print("Citace: " + ", ".join(result.citations))
        return 0
    finally:
        db.close()


def cmd_audit(args: argparse.Namespace) -> int:
    """E1 Evidence Manager: neměnná stopa operací (audit trail)."""
    db = _open_db(args.case_id)
    entries = db.list_audit_log(limit=args.limit, offset=args.offset)
    if getattr(args, "json", False):
        # chronologicky — nejstarší první (stopa čtená od začátku)
        _print_json([
            {
                "ts": e["ts"],
                "action": e["action"],
                "actor": e.get("actor"),
                "details": e["details"] if args.verbose else None,
            }
            for e in reversed(entries)
        ])
    elif not entries:
        print("(prázdný audit log)")
    else:
        # chronologicky — nejstarší první (stopa čtená od začátku)
        for e in reversed(entries):
            ts = e["ts"][:19].replace("T", " ")
            actor = f" [{e['actor']}]" if e.get("actor") else ""
            details = {k: v for k, v in e["details"].items() if not str(k).endswith("_total")}
            det = f"  {json.dumps(details, ensure_ascii=False)}" if details and args.verbose else ""
            print(f"{ts}  {e['action']}{actor}{det}")
    db.close()
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    """E1 Evidence Manager: záloha case DB (SQLite .backup() — konzistentní snapshot).

    Pravidlo 4: před migracemi vytvářej zálohu. Výchozí název <case>_backup_<ts>.db.
    """
    import sqlite3
    from datetime import datetime, timezone

    db = _open_db(args.case_id)
    out_dir = Path(args.out).expanduser() if args.out else _db_dir().parent / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"{args.case_id}_backup_{stamp}.db"

    src = db.conn
    dst = sqlite3.connect(out_path)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()

    # integrita zálohy — otevření + kontrola integrity (PRAGMA quick_check)
    chk = sqlite3.connect(out_path)
    ok = chk.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    n_files = chk.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    chk.close()

    db.log_operation(
        "db_backed_up",
        actor=case_examiner(db, args.case_id),
        details={
            "case_id": args.case_id,
            "path": str(out_path),
            "integrity_ok": ok,
            "files_in_backup": n_files,
        },
    )
    db.close()
    if not ok:
        if getattr(args, "json", False):
            _print_json({"error": "integrity_check_failed", "path": str(out_path)})
        else:
            print(f"Záloha selhala integritní kontrolou: {out_path}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        _print_json({
            "path": str(out_path),
            "size_mb": round(out_path.stat().st_size / 1e6, 2),
            "files_in_backup": n_files,
            "integrity_ok": ok,
        })
        return 0
    size = out_path.stat().st_size / 1e6
    print(f"Záloha vytvořena: {out_path} ({size:.2f} MB, {n_files} souborů, integrity OK)")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Web GUI (FÁZE web) — FastAPI nad analyze(), uvicorn server."""
    try:
        import uvicorn
    except ImportError:
        print("Chybí uvicorn — nainstalujte: pip install 'uvicorn[standard]'", file=sys.stderr)
        return 2

    from stopa.web.app import create_app

    # E12: bind address — CLI flag > settings.json > default 127.0.0.1
    host = args.host or _settings_bind_address() or "127.0.0.1"

    app = create_app()
    print(f"STOPA web GUI → http://{host}:{args.port} (Ctrl+C pro ukončení)")
    uvicorn.run(app, host=host, port=args.port, log_level="warning")
    return 0


def _settings_bind_address() -> str | None:
    """E12 — bind address z settings.json (None pokud není nastaveno)."""
    import json
    from pathlib import Path

    p = Path(os.environ.get("STOPA_DB_DIR", "cases")) / "settings.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        val = data.get("bind_address") if isinstance(data, dict) else None
        return str(val) if val else None
    except (json.JSONDecodeError, OSError):
        return None


# R0.4 — příklady pro --help (AK: každý subpříkaz ukazuje reálný příklad)
_SUBCOMMAND_EXAMPLES = {
    "new": 'stopa case new "Případ 2026-014" --examiner M.Matúš',
    "auto-export": "stopa case auto-export case-abc on --interval 30",
    "auto-interval": "stopa case auto-interval case-abc 30   # nebo 'off'",
    "add": "stopa add case-abc /mnt/evidence --profile forensic --resume",
    "files": "stopa files case-abc --family image --limit 50",
    "search": 'stopa search case-abc "invoice OR *.pdf" --source src-1',
    "stats": "stopa stats case-abc",
    "verify": "stopa verify case-abc --limit 20",
    "integrity": 'stopa integrity case-abc --init-key --checkpoint "před exportem"',
    "replay": "stopa replay case-abc op-123   # bez op = poslední extract",
    "benchmark": "stopa benchmark case-abc --suite all",
    "validate": "stopa validate case-abc",
    "analyze": 'stopa analyze case-abc "Kdo odeslal tento e-mail?"',
    "audit": "stopa audit case-abc -v --limit 50",
    "backup": "stopa backup case-abc --out /mnt/backup",
    "timeline": "stopa timeline case-abc --type browser_history --intel",
    "correlate": "stopa correlate case-abc -v",
    "image": "stopa image case-abc /path/disk.img --no-carve",
    "mobile": "stopa mobile case-abc /path/phone.img --password HESLO",
    "memory-analyze": "stopa memory-analyze case-abc /evidence/mem.raw --plugin windows.pslist",
    "pcap-analyze": "stopa pcap-analyze case-abc /evidence/capture.pcapng",
    "antiforensics-scan": "stopa antiforensics-scan case-abc [--image /evidence/disk.img]",
    "profiles": "stopa profiles",
    "report": "stopa report case-abc --format pdf --lang cs",
    "export": "stopa export case-abc --what timeline --format stix --bundle",
    "plaso-import": "stopa plaso-import case-abc /path/l2tcsv.txt",
    "timesketch-push": "stopa timesketch-push case-abc --what timeline --limit 1000",
    "serve": "stopa serve --port 8473",
    "install": "stopa install --dry-run   # nebo: stopa install (bez --dry-run)",
}


def _ex_sub(subparsers, name: str, *args, **kwargs) -> argparse.ArgumentParser:
    """add_parser + epilog s příkladem (R0.4); bez záznamu vrací parser beze změny."""
    p = subparsers.add_parser(name, *args, **kwargs)
    example = _SUBCOMMAND_EXAMPLES.get(name)
    if example:
        p.formatter_class = argparse.RawDescriptionHelpFormatter
        p.epilog = f"Příklad:\n  {example}"
    return p


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stopa", description=__doc__.splitlines()[0])
    # R0.3 — `stopa --version` vrací verzi balíčku (importlib metadata, dev fallback).
    try:
        from importlib.metadata import version as _pkg_version

        _ver = _pkg_version("stopa")
    except Exception:  # noqa: BLE001 — dev run bez instalace / chybějící metadata
        from stopa import __version__ as _ver
    parser.add_argument("--version", action="version", version=f"stopa {_ver}")
    sub = parser.add_subparsers(dest="command", required=True)

    case_p = _ex_sub(sub, "case", help="správa případů")
    case_sub = case_p.add_subparsers(dest="case_cmd", required=True)
    new_p = _ex_sub(case_sub, "new", help="vytvořit nový případ")
    new_p.add_argument("name", help="název případu")
    new_p.add_argument("--examiner", help="jméno znalce")
    new_p.add_argument("--notes", help="poznámky k případu")
    _add_json_flag(new_p)
    new_p.set_defaults(func=cmd_case_new)

    # STP-069 — opt-in automatický ZIP bundle po dokončení analýzy.
    autoexp_p = _ex_sub(case_sub, "auto-export", help="zapnout/vypnut automatický export (STP-069)"
    )
    autoexp_p.add_argument("case_id", help="ID případu")
    autoexp_p.add_argument("state", choices=["on", "off"], help="on = zapnout, off = vypnout")
    # STP-070 — volitelný interval periodického auto-bundle (minuty).
    autoexp_p.add_argument(
        "--interval",
        type=int,
        default=None,
        metavar="MINUTY",
        help="STP-070: interval periodického auto-bundle v minutách (5–43200)",
    )
    _add_json_flag(autoexp_p)
    autoexp_p.set_defaults(func=cmd_case_auto_export)

    # STP-070 — nastavení/vymazání intervalu periodického auto-bundle.
    autoint_p = _ex_sub(case_sub, "auto-interval", help="nastavit interval periodického auto-bundle (STP-070)"
    )
    autoint_p.add_argument("case_id", help="ID případu")
    autoint_p.add_argument(
        "minutes",
        help="interval v minutách (5–43200) nebo 'off' pro vymazání",
    )
    _add_json_flag(autoint_p)
    autoint_p.set_defaults(func=cmd_case_auto_interval)

    add_p = _ex_sub(sub, "add", help="přidat zdroj důkazů a zpracovat")
    add_p.add_argument("case_id", help="ID případu (z 'stopa case new')")
    add_p.add_argument("paths", nargs="+", help="složky nebo soubory ke zpracování")
    add_p.add_argument("--profile", default="forensic", choices=sorted(PROFILES),
                       help="processing profil (default: forensic)")
    add_p.add_argument("--hash-set", action="append", metavar="FILE",
                       help="known-bad hash set (text, 1 hash/řádek) — lze opakovat")
    add_p.add_argument("--custodian", default=None,
                       help="kdo nabytí důkazu eviduje (chain of custody)")
    add_p.add_argument("--method", default=None,
                       help="metoda nabytí (např. 'forensic copy', 'USB export')")
    add_p.add_argument("--resume", action="store_true",
                       help="E3 checkpointing — přeskočit soubory už v DB "
                            "(pokračovat po přerušeném běhu)")
    _add_json_flag(add_p)
    add_p.set_defaults(func=cmd_add)

    files_p = _ex_sub(sub, "files", help="seznam souborů v případu")
    files_p.add_argument("case_id")
    files_p.add_argument("--bad-ext", action="store_true", help="jen soubory s rozpornou příponou")
    files_p.add_argument("--dups", action="store_true", help="jen duplikáty")
    files_p.add_argument("--family", choices=["image", "document", "audio", "video", "media",
                                              "archive", "executable", "database", "compound"],
                         help="filtr podle rodiny signatury")
    files_p.add_argument("--limit", type=int, default=100)
    _add_json_flag(files_p)
    files_p.set_defaults(func=cmd_files)

    search_p = _ex_sub(sub, "search", help="full-text search (FTS5) napříč případem")
    search_p.add_argument("case_id")
    search_p.add_argument(
        "query",
        help='dotaz — FTS5 syntaxe: "fráze", *.jpg, pdf OR docx; jinak implicitní AND',
    )
    search_p.add_argument("--source", help="filtr podle evidence source ID")
    search_p.add_argument("--limit", type=int, default=100)
    _add_json_flag(search_p)
    search_p.set_defaults(func=cmd_search)

    stats_p = _ex_sub(sub, "stats", help="shrnutí případu")
    stats_p.add_argument("case_id")
    _add_json_flag(stats_p)
    stats_p.set_defaults(func=cmd_stats)

    ver_p = _ex_sub(sub, "verify", help="E1 — re-hash všech souborů a kontrola integrity (SHA-256/MD5)")
    ver_p.add_argument("case_id")
    ver_p.add_argument("--limit", type=int, default=20,
                       help="max. počet zobrazených problémů (default: 20)")
    _add_json_flag(ver_p)
    ver_p.set_defaults(func=cmd_verify)

    int_p = _ex_sub(sub, "integrity", help="P0 C4 — Evidence Integrity 2.0 (hash chaining + Ed25519 kontrolní body)"
    )
    int_p.add_argument("case_id")
    int_p.add_argument("--init-key", action="store_true",
                       help="vygenerovat Ed25519 klíčový pár případu (idempotentní)")
    int_p.add_argument("--checkpoint", metavar="DUVOD", default=None,
                       help="uložit nový kontrolní bod s uvedeným důvodem")
    _add_json_flag(int_p)
    int_p.set_defaults(func=cmd_integrity)

    rep_p = _ex_sub(sub, "replay", help="P0 C5 — Reproducibility Engine (opakovat operaci + porovnání výsledků)"
    )
    rep_p.add_argument("case_id")
    rep_p.add_argument("op", nargs="?", default=None,
                       help="ID operace (default: poslední extract)")
    _add_json_flag(rep_p)
    rep_p.set_defaults(func=cmd_replay)

    bm_p = _ex_sub(sub, "benchmark", help="P0 C6 — Benchmark Engine (deterministické benchmarky + regresní detekce)"
    )
    bm_p.add_argument("case_id", nargs="?", default=None,
                      help="případ pro historii/regrese (volitelné)")
    bm_p.add_argument("--suite", choices=["core", "parsers", "all"], default="core")
    _add_json_flag(bm_p)
    bm_p.set_defaults(func=cmd_benchmark)

    val_p = _ex_sub(sub, "validate", help="P0 C6 — Evidence Validation Report (parser × validace)"
    )
    val_p.add_argument("case_id")
    _add_json_flag(val_p)
    val_p.set_defaults(func=cmd_validate)

    ana_p = _ex_sub(sub, "analyze", help="P0 Intelligence I1 — AI orchestrace (5 agentů, auto/explicitní routing)"
    )
    ana_p.add_argument("case_id")
    ana_p.add_argument("question", help="analytický dotaz (čeština)")
    ana_p.add_argument(
        "--agent",
        choices=["case_analyst", "timeline_analyst", "artifact_analyst", "media_analyst", "report_analyst"],
        default=None,
        help="explicitní agent (default: auto-routing podle dotazu)",
    )
    _add_json_flag(ana_p)
    ana_p.set_defaults(func=cmd_analyze)

    aud_p = _ex_sub(sub, "audit", help="E1 — neměnná stopa operací (audit trail)")
    aud_p.add_argument("case_id")
    aud_p.add_argument("--limit", type=int, default=50,
                       help="max. počet záznamů (default: 50)")
    aud_p.add_argument("--offset", type=int, default=None,
                       help="posun od nejnovějšího záznamu")
    aud_p.add_argument("-v", "--verbose", action="store_true",
                       help="zobrazit i detaily operací (JSON)")
    _add_json_flag(aud_p)
    aud_p.set_defaults(func=cmd_audit)

    bak_p = _ex_sub(sub, "backup", help="E1 — záloha case DB (SQLite .backup, integrity check)")
    bak_p.add_argument("case_id")
    bak_p.add_argument("--out", metavar="DIR",
                       help="výstupní složka (default: backups/ vedle case DB)")
    _add_json_flag(bak_p)
    bak_p.set_defaults(func=cmd_backup)

    tl_p = _ex_sub(sub, "timeline", help="AXIOM-style timeline extrahovaných artifactů")
    tl_p.add_argument("case_id")
    tl_p.add_argument("--source", help="filtr podle evidence source ID")
    tl_p.add_argument("--type", dest="type", help="filtr podle typu artifactu (např. browser_history)")
    tl_p.add_argument("--path", help="filtr — cesta obsahuje text (LIKE %%text%%)")
    tl_p.add_argument("--limit", type=int, default=100)
    tl_p.add_argument("-v", "--verbose", action="store_true", help="zobrazit i zdrojové cesty")
    # STP-018 Timeline Intelligence 2.0 — post-pass: rozpory + duplikáty napříč zdroji
    tl_p.add_argument("--intel", action="store_true",
                      help="spustit Timeline Intelligence 2.0 (rozpory + duplikáty) a vypsat analytické skupiny")
    tl_p.add_argument("--window", type=float, default=60.0, metavar="SEC",
                      help="časové okno pro detekci rozporů v sekundách (default 60)")
    _add_json_flag(tl_p)
    tl_p.set_defaults(func=cmd_timeline)

    cor_p = _ex_sub(sub, "correlate", help="E4 — Entity + Correlation Engine (explicitní krok)")
    cor_p.add_argument("case_id")
    cor_p.add_argument("-v", "--verbose", action="store_true",
                       help="zobrazit detail propojení s evidence listy")
    _add_json_flag(cor_p)
    cor_p.set_defaults(func=cmd_correlate)

    img_p = _ex_sub(sub, "image", help="disk image (RAW/E01) — TSK file systems + carving")
    img_p.add_argument("case_id")
    img_p.add_argument("path", help="cesta k diskovému obrazu (.img/.dd/.raw/.e01)")
    img_p.add_argument("--profile", default="forensic", choices=sorted(PROFILES),
                       help="processing profil (default: forensic)")
    img_p.add_argument("--no-carve", action="store_true",
                       help="přeskočit carving nealokovaného prostoru")
    _add_json_flag(img_p)
    img_p.set_defaults(func=cmd_image)

    mob_p = _ex_sub(sub, "mobile", help="mobilní physical obraz — FDE/FBE unlock + TSK")
    mob_p.add_argument("case_id")
    mob_p.add_argument("path", help="cesta k mobilnímu obrazu (.img/.dd, volitelně FDE)")
    mob_p.add_argument("--password", metavar="HESLO", default=None,
                       help="FDE/FBE heslo (pokud je obraz šifrovaný)")
    mob_p.add_argument("--keyfile", metavar="SOUBOR", default=None,
                       help="extrahovaný klíč / passphrase soubor (má prioritu před --password)")
    mob_p.add_argument("--fde-type", choices=["bitlocker", "filevault"], default=None,
                       help="F1.1 — explicitní typ reálného FDE obrazu (libbde/libfvde); "
                            "syntetické formáty se detekují z magic automaticky")
    mob_p.add_argument("--recovery-key", metavar="KLÍČ", default=None,
                       help="F1.1 — BitLocker recovery key (primární cesta dle ROADMAP V2)")
    mob_p.add_argument("--profile", default="forensic", choices=sorted(PROFILES),
                       help="processing profil (default: forensic)")
    mob_p.add_argument("--no-carve", action="store_true",
                       help="přeskočit carving nealokovaného prostoru")
    _add_json_flag(mob_p)
    mob_p.set_defaults(func=cmd_mobile)

    dec_p = _ex_sub(sub, "decrypt", help="F1.1 — BitLocker/FileVault dešifrování (libbde/libfvde + STOPABLOCK)")
    dec_p.add_argument("image", help="cesta k šifrovanému obrazu")
    dec_p.add_argument("--type", choices=["bitlocker", "filevault"], default=None,
                       help="typ FDE obrazu (pokud není detekován z magic STOPABLK)")
    dec_p.add_argument("--recovery-key", metavar="KLÍČ", default=None,
                       help="BitLocker recovery key (48místný; primární cesta dle ROADMAP V2)")
    dec_p.add_argument("--password", metavar="HESLO", default=None,
                       help="FDE/FBE heslo")
    dec_p.add_argument("--out", metavar="SOUBOR", default=None,
                       help="výstupní plaintext (default: <obraz>.decrypted.img)")
    _add_json_flag(dec_p)
    dec_p.set_defaults(func=cmd_decrypt)

    mem_p = _ex_sub(sub, "memory-analyze", help="F1.2 — Memory Forensics přes Volatility 3 (volitelná runtime závislost)")
    mem_p.add_argument("case_id", help="ID případu")
    mem_p.add_argument("dump", help="cesta k memory dumpu (raw/LZMA/pcap)")
    mem_p.add_argument("--plugin", action="append", metavar="PLUGIN", default=None,
                       help=f"vol plugin (lze opakovat; bez = výchozí {', '.join(_VOL_DEFAULT_PLUGINS)})")
    mem_p.add_argument("--with-defaults", action="store_true",
                       help="přidá výchozí sadu k explicitním --plugin volbám")
    mem_p.add_argument("--timeout", type=int, default=600, metavar="S",
                       help="deadline jednoho pluginu v sekundách (default: 600)")
    _add_json_flag(mem_p)
    mem_p.set_defaults(func=cmd_memory_analyze)

    pcap_p = _ex_sub(sub, "pcap-analyze", help="F1.3 — Síťová forenzika: PCAP parser + TCP reassembly + IoC (Scapy)")
    pcap_p.add_argument("case_id", help="ID případu")
    pcap_p.add_argument("pcap", help="cesta k capture (.pcap/.pcapng)")
    pcap_p.add_argument("--max-packets", type=int, default=50_000, metavar="N",
                        help="strop počtu paketů (guard proti OOM; default: 50000)")
    _add_json_flag(pcap_p)
    pcap_p.set_defaults(func=cmd_pcap_analyze)

    af_p = _ex_sub(sub, "antiforensics-scan", help="F1.4 — Anti-Forensics detekce: timestomping, log clearing, USN truncation, hidden partitions, LSB steganografie")
    af_p.add_argument("case_id", help="ID případu")
    af_p.add_argument("--image", metavar="PATH", default=None,
                      help="volitelný diskový obraz pro MBR/partition table + integrity kontrolu")
    _add_json_flag(af_p)
    af_p.set_defaults(func=cmd_antiforensics)

    prof_p = _ex_sub(sub, "profiles", help="seznam processing profilů")
    _add_json_flag(prof_p)
    prof_p.set_defaults(func=cmd_profiles)

    rep_p = _ex_sub(sub, "report", help="forenzní report (HTML/PDF) + chain of custody")
    rep_p.add_argument("case_id")
    rep_p.add_argument("--format", choices=["html", "pdf"], default="html",
                       help="výstupní formát (default: html; pdf vyžaduje weasyprint)")
    rep_p.add_argument("--out", metavar="DIR",
                       help="výstupní složka (default: reports/ vedle case DB)")
    rep_p.add_argument("--lang", choices=["cs", "en"], default=None,
                       help="jazyk reportu (E10 i18n; default: cs)")
    _add_json_flag(rep_p)
    rep_p.set_defaults(func=cmd_report)

    exp_p = _ex_sub(sub, "export", help="E10/STP-023 — export dat případu do CSV/JSON/JSONL/XML/STIX")
    exp_p.add_argument("case_id")
    exp_p.add_argument("--what", choices=["artifacts", "timeline", "correlations"],
                       default="artifacts",
                       help="co exportovat (default: artifacts)")
    exp_p.add_argument("--format", choices=["csv", "json", "jsonl", "xml", "stix", "l2tcsv", "uco"], default="csv",
                       help="výstupní formát (default: csv; STP-023: jsonl/xml/stix; STP-054: l2tcsv; STP-055: uco)")
    exp_p.add_argument("--limit", type=int, default=None,
                       help="max. počet záznamů (artifacts/timeline; default: vše)")
    exp_p.add_argument("--out", metavar="SOUBOR",
                       help="výstupní soubor (default: stdout)")
    exp_p.add_argument("--bundle", action="store_true",
                       help="STP-068 — ZIP bundle všech datasetů (manifest + SHA-256, deterministický)")
    exp_p.set_defaults(func=cmd_export)

    pli_p = _ex_sub(sub, "plaso-import", help="STP-057 — Plaso import: l2tcsv soubor → case (source + artifacts + timeline)"
    )
    pli_p.add_argument("case_id")
    pli_p.add_argument("path", help="cesta k l2tcsv souboru (17 polí log2timeline.pl)")
    _add_json_flag(pli_p)
    pli_p.set_defaults(func=cmd_plaso_import)

    tsk_p = _ex_sub(sub, "timesketch-push",
        help="STP-059 — Timesketch push: case data → nový sketch + timeline (l2tcsv)",
    )
    tsk_p.add_argument("case_id")
    tsk_p.add_argument("--what", choices=["artifacts", "timeline", "correlations"],
                       default="timeline", help="dataset k pushnutí (default: timeline)")
    tsk_p.add_argument("--limit", type=int, default=None, metavar="N",
                       help="STP-065 — pushne jen první N záznamů datasetu (default: vše)")
    _add_json_flag(tsk_p)
    tsk_p.set_defaults(func=cmd_timesketch_push)

    srv_p = _ex_sub(sub, "serve", help="web GUI (FastAPI nad analyze())")
    srv_p.add_argument("--host", default=None,  # E12: None → settings.json → 127.0.0.1
                       help="bind address (default z Settings / 127.0.0.1)")
    srv_p.add_argument("--port", type=int, default=8473)
    srv_p.set_defaults(func=cmd_serve)

    # R0.2 — bootstrap installer: systémové závislosti + venv (detekce OS).
    ins_p = _ex_sub(sub, "install", help="R0.2 — nainstalovat systémové závislosti + venv (Ubuntu/Fedora/Alpine/macOS)")
    ins_p.add_argument("--dry-run", action="store_true",
                       help="jen vytisknout plán instalace, nic neinstalovat")
    ins_p.add_argument("--skip-system", action="store_true",
                       help="přeskočit systémové balíčky (jen venv + pip; bez sudo)")
    _add_json_flag(ins_p)
    ins_p.set_defaults(func=cmd_install)

    return parser


def cmd_install(args: argparse.Namespace) -> int:
    """R0.2 — ``stopa install``: detekce OS → plán → provedení (best-effort)."""
    from stopa import installer  # lazy — installer není v hot pathu CLI

    plan = installer.plan_install(skip_system=args.skip_system)
    if not getattr(args, "json", False):
        print(f"Detekováno: {plan.os_info.id} {plan.os_info.version}")
        for step in plan.steps:
            print(f"  - {step}")
        if args.dry_run:
            print("(dry-run — nic neinstalováno)")
            return 0
    rc = installer.run_plan(plan, dry_run=args.dry_run)
    _print_json({
        "ok": rc == 0,
        "os": plan.os_info.id,
        "version": plan.os_info.version,
        "package_manager": plan.package_manager,
        "system_packages": list(plan.system_packages),
        "needs_sudo": plan.needs_sudo,
        "venv_dir": str(plan.venv_dir),
        "dry_run": args.dry_run,
    })
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
