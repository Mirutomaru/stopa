"""CLI — rodina příkazů `case` (vytvoření případu, STP-069/070 auto-bundle).

P1-4 (refaktor god-file ``cli.py``): přesunuto bez změny chování;
facade ``stopa.cli`` re-exportuje implementace pro kompatibilitu.
"""
from __future__ import annotations

import argparse

from stopa.data.case_registry_repository import auto_sync
from stopa.data.db import CaseDB
from stopa.models import Case

from .._util import _db_dir, _open_db, _print_json


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
    # P2-2 — centrální registr případů: automatický sync při vzniku případu (defenzivní)
    auto_sync(_db_dir(), case.id)
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
    """STP-069 — zapnout/vypnout automatický ZIP bundle po dokončení analýzy."""
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


def cmd_case_scale(args: argparse.Namespace) -> int:
    """B10 — klasifikace velikosti případu (+ volitelný FTS REBUILD)."""
    db = _open_db(args.case_id)
    try:
        report = db.case_scale()
        if args.rebuild_fts:
            rebuilt = db.rebuild_fts()
            report["fts_rebuilt"] = list(rebuilt["rebuilt"])
            case = db.get_case(args.case_id)
            db.log_operation(
                "case_scale_fts_rebuilt",
                actor=case.examiner if case else None,
                details={"case_id": args.case_id},
            )
    finally:
        db.close()
    if getattr(args, "json", False):
        _print_json({"case_id": args.case_id, **report})
        return 0
    print(f"Velikost případu {args.case_id}: tier={report['tier']}")
    print(f"  soubory (řádky):   {report['files_rows']:,}")
    print(f"  datový objem:      {report['total_bytes'] / 2**30:.1f} GiB")
    print(f"  artefakty (řádky): {report['artifacts_rows']:,}")
    print(f"  audit log (řádky): {report['audit_log_rows']:,}")
    if "fts_rebuilt" in report:
        print(f"  FTS REBUILD:       {', '.join(report['fts_rebuilt'])}")
    if report["procedures"]:
        print("Doporučené údržbové postupy:")
        for proc in report["procedures"]:
            print(f"  - {proc}")
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
