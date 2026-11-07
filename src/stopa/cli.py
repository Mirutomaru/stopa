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
  stopa export <case_id> --what artifacts|timeline|correlations --format csv|json|jsonl|xml|stix|l2tcsv|uco [--limit N] [--out SOUBOR]
  stopa serve [--port 8473]                                 # web GUI (FastAPI)
  stopa profiles

DB: cases/<case_id>.db (přesaditelné přes STOPA_DB_DIR).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from stopa.data.db import CaseDB
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
    print(f"Případ vytvořen: {case.id}")
    print(f"  název:   {case.name}")
    if case.examiner:
        print(f"  znalec:  {case.examiner}")
    print(f"  DB:      {_db_dir() / f'{case.id}.db'}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    db = _open_db(args.case_id)
    profile = get_profile(args.profile)  # early validace jména profilu

    hash_sets: dict[str, set[str]] | None = None
    if args.hash_set:
        paths = [Path(p) for p in args.hash_set]
        missing = [str(p) for p in paths if not p.exists()]
        if missing:
            print(f"Chybějící hash sety: {', '.join(missing)}", file=sys.stderr)
            return 2
        hash_sets = load_hash_sets(paths)

    rc = 0
    print(f"Zpracovávám {len(args.paths)} zdrojů (profil: {profile.name})")
    for path_str in args.paths:
        root = Path(path_str).expanduser()
        if not root.exists():
            print(f"Zdroj neexistuje: {root}", file=sys.stderr)
            rc = 2
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

        def _progress(done: int, total: int, label: str = source.path) -> None:
            pct = (done / total * 100) if total else 100.0
            print(f"\r  {label}: {done}/{total} souborů ({pct:.0f}%)", end="", flush=True)

        result = process_source(
            db, source.id, root, args.profile, hash_sets, _progress,
            resume=getattr(args, "resume", False),
        )
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
    # STP-018 Timeline Intelligence 2.0 — post-pass nad celou case DB (rozpory + duplikáty).
    try:
        intel = run_timeline_intel(db)
        if intel["events"]:
            print(
                f"    timeline intel: {intel['contradiction_groups']} rozporových skupin, "
                f"{intel['dup_groups']} dup. skupin ({intel['events']} událostí)"
            )
    except Exception as exc:  # noqa: BLE001 — analytický bonus, ne pád ingestu
        print(f"    ! timeline intel: {exc}", file=sys.stderr)
    # P0 Core C4: kontrolní bod po ingestu (podpis hashu posledního audit řádku).
    db.add_integrity_checkpoint("ingest")
    db.close()
    return rc


def cmd_files(args: argparse.Namespace) -> int:
    db = _open_db(args.case_id)
    records = db.list_files(
        bad_extensions_only=args.bad_ext,
        duplicates_only=args.dups,
        signature_family=args.family,
        limit=args.limit,
    )
    if not records:
        print("(žádné záznamy)")
        return 0
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
        print(f"{r.rel_path}  [{sig}] {r.size_bytes:,} B{flag_str}")
    db.close()
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    db = _open_db(args.case_id)
    case = db.get_case(args.case_id)
    sources = db.list_sources(args.case_id)
    s = db.stats()
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
    if not records:
        print(f"(žádné soubory neodpovídají dotazu: {args.query!r})")
        return 0
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
        print(f"{r.rel_path}  [{sig}] {r.size_bytes:,} B{flag_str}")
    print(f"\nCELKEM: {len(records)} souborů (dotaz: {args.query!r})")
    db.close()
    return 0


def cmd_timeline(args: argparse.Namespace) -> int:
    """AXIOM-style timeline — chronologický přehled extrahovaných artifactů.

    STP-018: ``--intel`` spustí Timeline Intelligence 2.0 post-pass (rozpory +
    duplikáty napříč zdroji) a vypíše analytické skupiny nad materializovanou timeline.
    """
    db = _open_db(args.case_id)

    if getattr(args, "intel", False):
        from stopa.domain.timeline_intel import (
            FLAG_CONCURRENT_ACTIVITY,
            FLAG_CROSS_SOURCE_DUP,
        )

        summary = run_timeline_intel(db, window_seconds=getattr(args, "window", 60.0))
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
        print("(žádné artifacty — použij profil s extract_artifacts)")
        return 0
    for a in arts:
        ts = a.timestamp.strftime("%Y-%m-%d %H:%M") if a.timestamp else "—" * 16
        title = (a.title or "")[:80]
        print(f"{ts}  [{a.artifact_type}] {title}")
        if args.verbose and a.rel_path:
            print(f"          └─ {a.rel_path}")
    stats = db.artifact_stats(args.source)
    by_type = ", ".join(f"{k}: {v}" for k, v in sorted(stats.items()) if k != "total")
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
    )
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


def cmd_profiles(_args: argparse.Namespace) -> int:
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
        print(f"Report selhal: {e}", file=sys.stderr)
        db.close()
        return 2
    db.close()
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
        tool_version = "0.1.0"
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
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """E1 Evidence Manager: re-hash všech souborů v případu a porovnání s evidencí.

    Důkaz integrity — SHA-256 + MD5 (chunked, read-only přístup k originálům).
    Výsledek se zapíše do neměnného audit logu (`hash_verified`).
    """
    from stopa.domain.hashing import hash_file

    db = _open_db(args.case_id)
    sources = db.list_sources(args.case_id)
    if not sources:
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
    print(f"Integrita: {ok} OK, {mismatched} rozdílů, {missing} chybí, {skipped} nečitelných")
    for p in problems[: args.limit]:
        print(f"  ! {p}")
    if len(problems) > args.limit:
        print(f"  … a dalších {len(problems) - args.limit}")
    db.close()
    return 1 if (mismatched or missing) else 0


def cmd_integrity(args: argparse.Namespace) -> int:
    """P0 Core C4 — Evidence Integrity 2.0: hash chaining + Ed25519 kontrolní body."""
    db = _open_db(args.case_id)

    # 1) Hash chaining audit logu (ověřitelné bez klíče).
    report = db.verify_audit_chain()
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
        print(f"Ed25519 klíč vygenerován: {new_pub[:16]}…")
        pub = new_pub
    elif pub is not None:
        print(f"Ed25519 veřejný klíč: {pub[:16]}… ({len(pub)} b64 znaků)")
    else:
        print("Ed25519 klíč: nevygenerován (použij --init-key)")

    cps = db.list_integrity_checkpoints()
    if not cps:
        print("Kontrolní body: 0")
    else:
        results = db.verify_integrity_checkpoints()
        ok_count = sum(1 for r in results if r.get("ok"))
        print(f"Kontrolní body: {len(cps)} ({ok_count} platných podpisů)")
        for cp, res in zip(cps, results):
            mark = "✓" if res.get("ok") else "✗"
            print(
                f"  [{mark}] #{cp['id']} audit_row={cp['audit_row_id']} "
                f"{cp['reason'] or '—'} {cp['ts']}"
            )

    # 3) Nový kontrolní bod na požádání.
    if args.checkpoint:
        if db.integrity_public_key() is None:
            print("Klíč nevygenerován — použij --init-key", file=sys.stderr)
            db.close()
            return 2
        cp_id = db.add_integrity_checkpoint(args.checkpoint)
        if cp_id is None:
            print("Kontrolní bod neuložen (chybí klíč)", file=sys.stderr)
            db.close()
            return 2
        print(f"Nový kontrolní bod #{cp_id} ({args.checkpoint})")

    db.close()
    # exit code: 0 = řetězec OK, 1 = rozbitý řetězec
    return 0 if report.ok else 1


def cmd_replay(args: argparse.Namespace) -> int:
    """P0 Core C5 — Reproducibility Engine: opakovat zaznamenanou operaci + porovnání."""
    from stopa.pipeline import replay_extract

    db = _open_db(args.case_id)
    ops = db.list_operations(case_id=args.case_id, op_type="extract")
    if not ops:
        print("Žádné zaznamenané extract operace (předtím `stopa add`)", file=sys.stderr)
        db.close()
        return 2

    target = db.get_operation(args.op) if args.op else ops[-1]
    if target is None:
        print(f"Operace nenalezena: {args.op}", file=sys.stderr)
        db.close()
        return 2

    src = db.get_source(target.source_id or "")
    if src is None:
        print(f"Zdroj operace neexistuje: {target.source_id}", file=sys.stderr)
        db.close()
        return 2
    root = Path(src.path).expanduser()
    if not root.exists():
        print(f"Zdroj už není na disku: {root}", file=sys.stderr)
        db.close()
        return 2

    print(f"Replay operace {target.id} (zdroj: {src.path})")
    res = replay_extract(target, root)

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
    return 0 if (res.inputs_identical and res.outputs_identical) else 1


def cmd_benchmark(args: argparse.Namespace) -> int:
    """P0 Core C6 — Benchmark Engine: deterministické benchmarky + detekce regresí."""
    from stopa.data.benchmark_engine import (
        check_regressions,
        run_benchmark,
        save_history,
    )

    print(f"Benchmark suite: {args.suite}")
    results = run_benchmark(suite=args.suite)
    if not results:
        print("Žádné výsledky (selhaly všechny workloads)", file=sys.stderr)
        return 2

    for r in results:
        print(
            f"  {r.name:<24} {r.duration_ms:>10.3f} ms | "
            f"RAM peak {r.ram_peak_bytes / 1e6:>8.2f} MB | artefakty {r.artifacts}"
        )

    # historie + regresní detekce (jen s případem — meta benchmark_history)
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
        if warnings:
            print(f"\n⚠ Regrese výkonu (>20% proti baseline): {len(warnings)}")
            for w in warnings:
                print(
                    f"  ! {w.name}: {w.baseline_ms:.3f} → {w.current_ms:.3f} ms "
                    f"(+{w.delta_pct}%)"
                )
        else:
            print("\nRegrese výkonu: žádná (baseline OK)")

    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """P0 Core C6 — Evidence Validation Report per případ."""
    from stopa.data.validation_report import build_validation_report, report_to_json

    db = _open_db(args.case_id)
    rep = build_validation_report(db, args.case_id)
    cov = rep["coverage"]

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
            print("AI nedostupná — spusťte LM Studio (localhost:1234)")
            return 1

        context = build_case_context(db, args.case_id)
        # P0 Intelligence I2 — Forensic RAG: retrieval napříč vrstvami
        rag = retrieve(args.question, db=db, case_id=args.case_id)
        # STP-019 — PII redaktor (settings.json toggle, default ON)
        redact_pii = _load_ai_redact_pii()
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
            print(f"AI nedostupná: {exc}")
            return 1
        except OrchestrationError as exc:
            print(f"AI orchestrace selhala: {exc}")
            return 1

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
    if not entries:
        print("(prázdný audit log)")
        return 0
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
        print(f"Záloha selhala integritní kontrolou: {out_path}", file=sys.stderr)
        return 1
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stopa", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    case_p = sub.add_parser("case", help="správa případů")
    case_sub = case_p.add_subparsers(dest="case_cmd", required=True)
    new_p = case_sub.add_parser("new", help="vytvořit nový případ")
    new_p.add_argument("name", help="název případu")
    new_p.add_argument("--examiner", help="jméno znalce")
    new_p.add_argument("--notes", help="poznámky k případu")
    new_p.set_defaults(func=cmd_case_new)

    add_p = sub.add_parser("add", help="přidat zdroj důkazů a zpracovat")
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
    add_p.set_defaults(func=cmd_add)

    files_p = sub.add_parser("files", help="seznam souborů v případu")
    files_p.add_argument("case_id")
    files_p.add_argument("--bad-ext", action="store_true", help="jen soubory s rozpornou příponou")
    files_p.add_argument("--dups", action="store_true", help="jen duplikáty")
    files_p.add_argument("--family", choices=["image", "document", "audio", "video", "media",
                                              "archive", "executable", "database", "compound"],
                         help="filtr podle rodiny signatury")
    files_p.add_argument("--limit", type=int, default=100)
    files_p.set_defaults(func=cmd_files)

    search_p = sub.add_parser("search", help="full-text search (FTS5) napříč případem")
    search_p.add_argument("case_id")
    search_p.add_argument(
        "query",
        help='dotaz — FTS5 syntaxe: "fráze", *.jpg, pdf OR docx; jinak implicitní AND',
    )
    search_p.add_argument("--source", help="filtr podle evidence source ID")
    search_p.add_argument("--limit", type=int, default=100)
    search_p.set_defaults(func=cmd_search)

    stats_p = sub.add_parser("stats", help="shrnutí případu")
    stats_p.add_argument("case_id")
    stats_p.set_defaults(func=cmd_stats)

    ver_p = sub.add_parser("verify", help="E1 — re-hash všech souborů a kontrola integrity (SHA-256/MD5)")
    ver_p.add_argument("case_id")
    ver_p.add_argument("--limit", type=int, default=20,
                       help="max. počet zobrazených problémů (default: 20)")
    ver_p.set_defaults(func=cmd_verify)

    int_p = sub.add_parser(
        "integrity", help="P0 C4 — Evidence Integrity 2.0 (hash chaining + Ed25519 kontrolní body)"
    )
    int_p.add_argument("case_id")
    int_p.add_argument("--init-key", action="store_true",
                       help="vygenerovat Ed25519 klíčový pár případu (idempotentní)")
    int_p.add_argument("--checkpoint", metavar="DUVOD", default=None,
                       help="uložit nový kontrolní bod s uvedeným důvodem")
    int_p.set_defaults(func=cmd_integrity)

    rep_p = sub.add_parser(
        "replay", help="P0 C5 — Reproducibility Engine (opakovat operaci + porovnání výsledků)"
    )
    rep_p.add_argument("case_id")
    rep_p.add_argument("op", nargs="?", default=None,
                       help="ID operace (default: poslední extract)")
    rep_p.set_defaults(func=cmd_replay)

    bm_p = sub.add_parser(
        "benchmark", help="P0 C6 — Benchmark Engine (deterministické benchmarky + regresní detekce)"
    )
    bm_p.add_argument("case_id", nargs="?", default=None,
                      help="případ pro historii/regrese (volitelné)")
    bm_p.add_argument("--suite", choices=["core", "parsers", "all"], default="core")
    bm_p.set_defaults(func=cmd_benchmark)

    val_p = sub.add_parser(
        "validate", help="P0 C6 — Evidence Validation Report (parser × validace)"
    )
    val_p.add_argument("case_id")
    val_p.add_argument("--json", action="store_true", help="kompletní report jako JSON")
    val_p.set_defaults(func=cmd_validate)

    ana_p = sub.add_parser(
        "analyze", help="P0 Intelligence I1 — AI orchestrace (5 agentů, auto/explicitní routing)"
    )
    ana_p.add_argument("case_id")
    ana_p.add_argument("question", help="analytický dotaz (čeština)")
    ana_p.add_argument(
        "--agent",
        choices=["case_analyst", "timeline_analyst", "artifact_analyst", "media_analyst", "report_analyst"],
        default=None,
        help="explicitní agent (default: auto-routing podle dotazu)",
    )
    ana_p.add_argument("--json", action="store_true", help="výsledek jako JSON")
    ana_p.set_defaults(func=cmd_analyze)

    aud_p = sub.add_parser("audit", help="E1 — neměnná stopa operací (audit trail)")
    aud_p.add_argument("case_id")
    aud_p.add_argument("--limit", type=int, default=50,
                       help="max. počet záznamů (default: 50)")
    aud_p.add_argument("--offset", type=int, default=None,
                       help="posun od nejnovějšího záznamu")
    aud_p.add_argument("-v", "--verbose", action="store_true",
                       help="zobrazit i detaily operací (JSON)")
    aud_p.set_defaults(func=cmd_audit)

    bak_p = sub.add_parser("backup", help="E1 — záloha case DB (SQLite .backup, integrity check)")
    bak_p.add_argument("case_id")
    bak_p.add_argument("--out", metavar="DIR",
                       help="výstupní složka (default: backups/ vedle case DB)")
    bak_p.set_defaults(func=cmd_backup)

    tl_p = sub.add_parser("timeline", help="AXIOM-style timeline extrahovaných artifactů")
    tl_p.add_argument("case_id")
    tl_p.add_argument("--source", help="filtr podle evidence source ID")
    tl_p.add_argument("--type", dest="type", help="filtr podle typu artifactu (např. browser_history)")
    tl_p.add_argument("--path", help="filtr — cesta obsahuje text (LIKE %text%)")
    tl_p.add_argument("--limit", type=int, default=100)
    tl_p.add_argument("-v", "--verbose", action="store_true", help="zobrazit i zdrojové cesty")
    # STP-018 Timeline Intelligence 2.0 — post-pass: rozpory + duplikáty napříč zdroji
    tl_p.add_argument("--intel", action="store_true",
                      help="spustit Timeline Intelligence 2.0 (rozpory + duplikáty) a vypsat analytické skupiny")
    tl_p.add_argument("--window", type=float, default=60.0, metavar="SEC",
                      help="časové okno pro detekci rozporů v sekundách (default 60)")
    tl_p.set_defaults(func=cmd_timeline)

    cor_p = sub.add_parser("correlate", help="E4 — Entity + Correlation Engine (explicitní krok)")
    cor_p.add_argument("case_id")
    cor_p.add_argument("-v", "--verbose", action="store_true",
                       help="zobrazit detail propojení s evidence listy")
    cor_p.set_defaults(func=cmd_correlate)

    img_p = sub.add_parser("image", help="disk image (RAW/E01) — TSK file systems + carving")
    img_p.add_argument("case_id")
    img_p.add_argument("path", help="cesta k diskovému obrazu (.img/.dd/.raw/.e01)")
    img_p.add_argument("--profile", default="forensic", choices=sorted(PROFILES),
                       help="processing profil (default: forensic)")
    img_p.add_argument("--no-carve", action="store_true",
                       help="přeskočit carving nealokovaného prostoru")
    img_p.set_defaults(func=cmd_image)

    mob_p = sub.add_parser("mobile", help="mobilní physical obraz — FDE/FBE unlock + TSK")
    mob_p.add_argument("case_id")
    mob_p.add_argument("path", help="cesta k mobilnímu obrazu (.img/.dd, volitelně FDE)")
    mob_p.add_argument("--password", metavar="HESLO", default=None,
                       help="FDE/FBE heslo (pokud je obraz šifrovaný)")
    mob_p.add_argument("--keyfile", metavar="SOUBOR", default=None,
                       help="extrahovaný klíč / passphrase soubor (má prioritu před --password)")
    mob_p.add_argument("--profile", default="forensic", choices=sorted(PROFILES),
                       help="processing profil (default: forensic)")
    mob_p.add_argument("--no-carve", action="store_true",
                       help="přeskočit carving nealokovaného prostoru")
    mob_p.set_defaults(func=cmd_mobile)

    prof_p = sub.add_parser("profiles", help="seznam processing profilů")
    prof_p.set_defaults(func=cmd_profiles)

    rep_p = sub.add_parser("report", help="forenzní report (HTML/PDF) + chain of custody")
    rep_p.add_argument("case_id")
    rep_p.add_argument("--format", choices=["html", "pdf"], default="html",
                       help="výstupní formát (default: html; pdf vyžaduje weasyprint)")
    rep_p.add_argument("--out", metavar="DIR",
                       help="výstupní složka (default: reports/ vedle case DB)")
    rep_p.add_argument("--lang", choices=["cs", "en"], default=None,
                       help="jazyk reportu (E10 i18n; default: cs)")
    rep_p.set_defaults(func=cmd_report)

    exp_p = sub.add_parser("export", help="E10/STP-023 — export dat případu do CSV/JSON/JSONL/XML/STIX")
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
    exp_p.set_defaults(func=cmd_export)

    pli_p = sub.add_parser(
        "plaso-import", help="STP-057 — Plaso import: l2tcsv soubor → case (source + artifacts + timeline)"
    )
    pli_p.add_argument("case_id")
    pli_p.add_argument("path", help="cesta k l2tcsv souboru (17 polí log2timeline.pl)")
    pli_p.set_defaults(func=cmd_plaso_import)

    srv_p = sub.add_parser("serve", help="web GUI (FastAPI nad analyze())")
    srv_p.add_argument("--host", default=None,  # E12: None → settings.json → 127.0.0.1
                       help="bind address (default z Settings / 127.0.0.1)")
    srv_p.add_argument("--port", type=int, default=8473)
    srv_p.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
