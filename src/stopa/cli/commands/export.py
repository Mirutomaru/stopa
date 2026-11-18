"""CLI — vývoz a integrace (export/UCO, plaso L2TCSV, Timesketch push).

P1-4 (refaktor god-file ``cli.py``): přesunuto bez změny chování;
facade ``stopa.cli`` re-exportuje implementace pro kompatibilitu.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from stopa.data.db import CaseDB

from .._util import _open_db, _print_json, case_examiner


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
        to_timesketch_jsonl,
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
    elif args.format == "timesketch":
        # F6.1 — Timesketch JSONL (jeden event na řádek; round-trip bez ztráty přes extra).
        text = to_timesketch_jsonl(records, dataset=args.what)
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
    # F6.2 — volitelná validace STIX bundle (stix2-validator); chybějící stix2
    # = upozornění bez propadnutí exportu, skutečná schémová chyba → exit 1.
    if getattr(args, "validate_stix", False) and args.format == "stix":
        from stopa.domain.export import validate_stix_bundle

        ok, detail = validate_stix_bundle(text)
        print(f"STIX validace: {detail}")
        db.close()
        skipped = (not ok) and detail.startswith("stix2 není nainstalován")
        return 0 if (ok or skipped) else 1
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
        tool_version = "2.0.0"
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


