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
import signal  # F2.4 — SIGINT/SIGTERM → graceful shutdown ingestu (stop_event)
import sys
import threading  # F2.4 — stop_event pro graceful shutdown
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("stopa.cli")

from stopa.data.db import CaseDB
from stopa.data.write_blocker_repository import WriteBlockerRepository  # F5.4
from stopa.domain.mem_forensics import DEFAULT_PLUGINS as _VOL_DEFAULT_PLUGINS
from stopa.domain.profiles import PROFILES, get_profile
from stopa.domain.write_blocker import (  # F5.4 — write-blocker API
    detect_write_blocker,
    ingest_gate,
    known_vendor_ids,
    vendor_label,
)
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


def _load_require_write_blocker() -> bool:
    """F5.4 — write-blocker gate toggle ze settings.json (default OFF)."""
    p = _db_dir() / "settings.json"
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return bool(data.get("require_write_blocker", False)) if isinstance(data, dict) else False


def _load_timesketch_auto_push() -> bool:
    """F6.1 — opt-in auto-push do Timesketch po úspěšném ingestu (settings.json, default OFF)."""
    p = _db_dir() / "settings.json"
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return bool(data.get("timesketch_auto_push", False)) if isinstance(data, dict) else False


def _load_settings_dict() -> dict:
    """F6.4 — celý settings.json jako dict (pluginy: dirs/verified/sandbox). Chybí → {}."""
    p = _db_dir() / "settings.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_settings_dict(data: dict) -> None:
    """F6.4 — zápis settings.json (idempotentní, zachovává ostatní klíče)."""
    p = _db_dir() / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
    # F5.4 — write-blocker gate (settings.json require_write_blocker, default OFF;
    # exit 2 = brána blokuje ingest bez připojeného WB)
    wb_gate = ingest_gate(
        WriteBlockerRepository(db.conn, db.audit_repo).latest_state(),
        _load_require_write_blocker(),
    )
    if not wb_gate.allowed:
        print(f"⛔ {wb_gate.warning}", file=sys.stderr)
        return 2
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
            max_workers=args.workers,  # F2.4 — CLI --workers (default auto)
            pool=args.pool,  # F2.4 — CLI --pool (auto = procesy pro N>1)
            stop_event=_stop_ev,  # F2.4 — SIGINT/SIGTERM → graceful shutdown
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


@dataclass(frozen=True)
class _BytesHolder:
    """In-mem soubor z ZIP archivu (rel_path + bytes) — pro report.xml/VCF."""

    rel: str
    data: bytes


def cmd_import_mobile(args: argparse.Namespace) -> int:
    """F1.5 — Import mobilní extrakce (ROADMAP V2 Fáze 1).

    Podporované zdroje (--source):
      cellebrite — .ufd/.zip s report.xml (Cellebrite UFED evidence export),
                   volitelně i .vcf karty v archivu,
      msab       — .zip s .vcf kartami (MSAB XRY contacts export),
      adb        — složka Android logical dumpu; každá SQLite DB jde přes
                   existující extraktory (kontakty/WhatsApp msgstore/Signal).

    Artefakty do case DB idempotentně (replace per file), timeline events pro
    záznamy s časem, na konci korelace entit (AK: entity korelovány s
    existujícími kontakty případu).

    Exit codes: 0 = OK · 1 = nic neextrahováno / parse chyba · 2 = špatné argumenty
    """
    import hashlib
    import zipfile

    from stopa.domain.correlation import run_correlation
    from stopa.domain.mobile_forensics import (
        PARSER_VERSION,
        UfedParseError,
        contact_specs_from_card,
        models_to_artifact_specs,
        parse_ufdr_xml,
        parse_vcf,
    )
    from stopa.models import Artifact, EvidenceSource, FileRecord

    json_mode = getattr(args, "json", False)
    dump_path = Path(args.dump).expanduser()
    source_kind = args.source

    # ── vstupní soubory per typ zdroje ───────────────────────────────
    # [(rel_path, bytes|None)] — bytes pro textové parsery, None = DB (path)
    inputs: list[tuple[str, _BytesHolder | Path]] = []
    parse_errors: dict[str, str] = {}

    def _hash_file(p: Path) -> str:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    if source_kind == "adb":
        if not dump_path.is_dir():
            print(f"ADB logical dump musí být složka: {dump_path}", file=sys.stderr)
            return 2
        for p in sorted(dump_path.rglob("*")):
            if not p.is_file():
                continue
            suf = p.suffix.lower()
            rel = p.relative_to(dump_path).as_posix()
            if suf in (".db", ".sqlite"):
                inputs.append((rel, p))
            elif suf == ".vcf":
                inputs.append((rel, p))  # VCF z backupu (řídké, ale levné)
    else:
        if not dump_path.exists():
            print(f"Soubor neexistuje: {dump_path}", file=sys.stderr)
            return 2

        def _archive_members() -> list[tuple[str, bytes]] | None:
            """ZIP (.ufd/.zip) → [(rel_path, bytes)]; složka → [..] z disk."""
            if dump_path.is_dir():  # rozbalený export — procházíme přímo
                out = []
                for p in sorted(dump_path.rglob("*")):
                    if not p.is_file() or p.stat().st_size > 256 * (1 << 20):
                        continue
                    out.append((p.relative_to(dump_path).as_posix(), p.read_bytes()))
                return out
            if dump_path.suffix.lower() in (".zip", ".ufd"):
                try:
                    with zipfile.ZipFile(dump_path) as zf:
                        return [
                            (zi.filename, zf.read(zi))
                            for zi in zf.infolist()
                            if not zi.is_dir() and zi.file_size <= 256 * (1 << 20)
                        ]
                except zipfile.BadZipFile as e:
                    print(f"Neplatné ZIP/UFDR archív: {e}", file=sys.stderr)
                    return None
            print(
                f"Nerozpoznaný formát pro --source {source_kind} "
                "(očekávám .ufd/.zip/složku): " + str(dump_path),
                file=sys.stderr,
            )
            return None

        members = _archive_members()
        if members is None:
            return 2
        for rel, data in members:
            low = rel.lower()
            if source_kind == "cellebrite" and (low.endswith("report.xml") or ".vcf" in low) or source_kind == "msab" and low.endswith(".vcf"):
                inputs.append((rel, _BytesHolder(rel, data)))

    if not inputs:
        msg = (
            f"Žádné vstupní soubory pro --source {source_kind} v {dump_path}"
            + (" (očekávám report.xml)" if source_kind == "cellebrite" else "")
            + (" (očekávám *.vcf)" if source_kind == "msab" else "")
        )
        print(msg, file=sys.stderr)
        return 2

    db = _open_db(args.case_id)
    try:
        # provenance: zdroj podle cesty (re-import → stejný source, idempotentní)
        existing = next(
            (s for s in db.list_sources(args.case_id) if s.path == str(dump_path)), None
        )
        kind = "folder" if source_kind == "adb" else "file"
        source = existing or EvidenceSource(case_id=args.case_id, kind=kind, path=str(dump_path))
        if existing is None:
            db.add_source(source)

        # F1.4 pitfall — re-ingest: timeline events (FK artifact_id bez ON DELETE)
        # se vyčistí PŘED replace artifactů, jinak visící reference.
        if existing is not None:
            db.clear_timeline_events(source_id=source.id)

        all_arts: list[Artifact] = []
        file_ids: dict[str, str] = {}  # rel_path → file_id (idempotentní upsert)

        for rel, holder in inputs:
            size = len(holder.data) if isinstance(holder, _BytesHolder) else holder.stat().st_size
            sha = hashlib.sha256(holder.data).hexdigest() if isinstance(
                holder, _BytesHolder) else (_hash_file(holder))
            rec = FileRecord(
                source_id=source.id, rel_path=rel, name=Path(rel).name,
                size_bytes=size, sha256=sha, signature_type=None,
            )
            file_id = db.upsert_file(rec)
            file_ids[rel] = file_id

            arts_for_file: list[Artifact] = []
            if isinstance(holder, _BytesHolder):
                data = holder.data
                low = rel.lower()
                try:
                    specs: list = []
                    if low.endswith("report.xml"):
                        models, unknown = parse_ufdr_xml(data)
                        specs = models_to_artifact_specs(models)
                        if unknown:
                            note = "neznámé typy: " + ",".join(sorted(set(unknown))[:8])
                            parse_errors[rel] = (parse_errors.get(rel, "") + " " + note).strip()
                    elif low.endswith(".vcf"):
                        text = data.decode("utf-8", errors="replace")
                        cards = parse_vcf(text)
                        specs = [s for card in cards for s in contact_specs_from_card(card, engine=source_kind)]
                except (UfedParseError, UnicodeDecodeError) as e:
                    parse_errors[rel] = str(e)[:300]
                    continue
                arts_for_file = [
                    Artifact(artifact_type=s.artifact_type, title=s.title,
                             timestamp=s.timestamp, details=dict(s.details),
                             parser_version=f"import-mobile/{PARSER_VERSION}")
                    for s in specs
                ]
            else:  # adb: SQLite DB / VCF z disku
                if holder.suffix.lower() == ".vcf":
                    text = holder.read_text(encoding="utf-8", errors="replace")
                    cards = parse_vcf(text)
                    arts_for_file = [
                        Artifact(artifact_type=s.artifact_type, title=s.title,
                                 timestamp=s.timestamp, details=dict(s.details),
                                 parser_version=f"import-mobile/{PARSER_VERSION}")
                        for card in cards for s in contact_specs_from_card(card, engine="adb")
                    ]
                else:
                    from stopa.artifacts.sqlite_extract import extract_sqlite_artifacts

                    arts_for_file = [
                        a.model_copy(deep=True) for a in extract_sqlite_artifacts(holder)
                    ]
                    if not arts_for_file and holder.suffix.lower() != ".db":
                        pass  # generic triage vrací [] jen pro neznámé schéma — OK

            for a in arts_for_file:
                a.source_id = source.id
                a.file_id = file_id
                a.rel_path = rel
            db.replace_artifacts_for_file(file_id, arts_for_file)
            all_arts.extend(arts_for_file)

        # timeline events (po artifactech — FK artifact_id musí existovat)
        tl_count = 0
        for a in all_arts:
            if a.timestamp is None:
                continue
            db.add_timeline_event(
                source_id=source.id, artifact_id=a.id, file_id=a.file_id,
                rel_path=a.rel_path, event_type=a.artifact_type, ts_utc=a.timestamp,
                title=a.title, parser_version=f"import-mobile/{PARSER_VERSION}",
                anomaly_flags=list(a.anomaly_flags), ts_origin="source",
            )
            tl_count += 1

        db.commit()

        # AK: entity korelovány s existujícími kontakty případu
        corr = run_correlation(db, args.case_id)

        by_type: dict[str, int] = {}
        for a in all_arts:
            by_type[a.artifact_type] = by_type.get(a.artifact_type, 0) + 1

        if not json_mode:
            print(f"  {len(all_arts)} artefaktů ze {len(inputs)} souborů "
                  f"(timeline: {tl_count})")
            for t_name in sorted(by_type):
                print(f"    {t_name}: {by_type[t_name]}")
            if parse_errors:
                for rel, err in list(parse_errors.items())[:10]:
                    print(f"  ! {rel}: {err}", file=sys.stderr)
            print(
                f"Korelace entit: {corr['entities']} entit, "
                f"{corr['correlations_total']} propojení"
            )

        if json_mode:
            _print_json({
                "dump": str(dump_path),
                "case_id": args.case_id,
                "source_kind": source_kind,
                "files_processed": len(inputs),
                "artifacts": len(all_arts),
                "timeline_events": tl_count,
                "by_type": by_type,
                "parse_errors": parse_errors,
                **corr,
            })

        return 0 if all_arts else 1
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


_K3_CHAIN_MAP = {
    "bitcoin": "btc", "btc": "btc", "bitcoin-cash": "btc",
    "ethereum": "eth", "eth": "eth", "bsc": "eth", "polygon": "eth",
}


def _k3_norm_chain(chain: str | None) -> str:
    return _K3_CHAIN_MAP.get((chain or "").lower(), "unknown")


def cmd_onchain(args: argparse.Namespace) -> int:
    """K3 On-chain analýza — clustering + graf transakcí + risk scoring (offline-first).

    Vstup: adresy extrahované z crypto artefaktů případu. Síť je opt-in
    (--api-key / --etherscan-key); jinak jen bundlované sankční listy + cache.
    """
    from stopa.domain.crypto.clustering import cluster_common_input, detect_change_addresses
    from stopa.domain.crypto.onchain_api import (
        BlockchairClient,
        EtherscanClient,
        OnchainApiError,
        TxCache,
    )
    from stopa.domain.crypto.risk_scoring import score_addresses as k3_score
    from stopa.domain.crypto.tx_graph import (
        build_graph,
        detect_cycles,
        expand_paths,
        top_recipients,
        top_senders,
    )

    db = _open_db(args.case_id)
    try:
        # 1) sběr adres z crypto artefaktů (value → chain; první detekce má přednost)
        addrs: dict[str, str] = {}
        for atype in ("crypto_detection", "crypto_wallet"):
            for art in db.list_artifacts(artifact_type=atype):
                d = art.details or {}
                for a in d.get("addresses") or []:  # AddressValidation dump
                    if not isinstance(a, dict):
                        continue
                    v = (a.get("raw_value") or "").strip()
                    if v and v not in addrs:
                        addrs[v] = _k3_norm_chain(a.get("chain"))
                for w in d.get("wallets") or []:  # WalletDetection dump
                    for v in w.get("public_addresses") or []:
                        if isinstance(v, str) and v.strip() and v not in addrs:
                            addrs[v] = "unknown"

        # 2) risk scoring — bundlované OFAC/EU listy (offline, deterministické)
        scores = k3_score(list(addrs))

        # 3) transakce: cache + volitelná síť
        cache_path = _db_dir() / f"{args.case_id}.txcache.json"
        cache = TxCache(cache_path)
        txs_by_addr = cache.load() or {}
        warnings: list[str] = []

        clients: dict[str, object] = {}
        if not args.no_network and args.api_key:
            try:
                clients["btc"] = BlockchairClient(args.api_key)
            except OnchainApiError as exc:
                warnings.append(f"blockchair: {exc}")
        if not args.no_network and getattr(args, "etherscan_key", None):
            try:
                clients["eth"] = EtherscanClient(args.etherscan_key)
            except OnchainApiError as exc:
                warnings.append(f"etherscan: {exc}")

        for addr in sorted(addrs):
            if addr in txs_by_addr:
                continue  # cache hit — offline-first
            chain = addrs[addr]
            client = clients.get(chain)
            if client is None:
                continue  # bez klienta (nebo neznámý chain) zůstáváme offline
            try:
                txs_by_addr[addr] = client.fetch_address_txs(addr)  # type: ignore[union-attr]
            except OnchainApiError as exc:
                warnings.append(f"{addr[:16]}…: {exc}")

        if clients and not args.no_network:
            try:
                cache.save(txs_by_addr)
            except OnchainApiError as exc:
                warnings.append(str(exc))

        all_txs = list({t.txid: t for tx_list in txs_by_addr.values() for t in tx_list}.values())

        # 4) clustering + graf (jen pokud jsou transakce k dispozici)
        clusters_out: list[dict] = []
        graph_out: dict | None = None
        cycles: list[list[str]] = []
        paths_from_risk: dict[str, list[list[str]]] = {}
        change: set[str] = set()

        if all_txs:
            clusters = cluster_common_input(all_txs)
            own_all = set(addrs)  # všechny adresy případu = „vlastní" pro change-detekci
            change = detect_change_addresses(all_txs, own_all)
            ranked = sorted(
                clusters, key=lambda c: (-len(c.addresses), c.cluster_id)
            )[:50]
            clusters_out = [c.model_dump() for c in ranked]

            graph = build_graph(all_txs)
            cycles = detect_cycles(graph, max_len=4)
            risky = [a for a in sorted(addrs) if scores[a].level in ("high", "critical")]
            for a in risky:
                paths_from_risk[a] = expand_paths(graph, a, depth=args.depth)[:20]

            graph_out = {
                "nodes_total": len(graph.nodes),
                "edges_total": len(graph.edges),
                "top_senders": [list(x) for x in top_senders(graph)],
                "top_recipients": [list(x) for x in top_recipients(graph)],
            }

        result = {
            "case_id": args.case_id,
            "addresses_total": len(addrs),
            "address_scores": [
                {
                    "address": a,
                    "chain": addrs[a],
                    "score": scores[a].score,
                    "level": scores[a].level,
                    "reasons": scores[a].reasons,
                }
                for a in sorted(addrs)
            ],
            "high_risk_count": sum(1 for s in scores.values() if s.level in ("high", "critical")),
            "transactions_loaded": len(all_txs),
            "clusters": clusters_out,
            "change_addresses": sorted(change) if all_txs else [],
            "graph": graph_out,
            "cycles": cycles,
            "paths_from_risk": paths_from_risk,
            "cache_path": str(cache_path),
            "cache_last_error": cache.last_error,
            "warnings": warnings,
        }

        if getattr(args, "json", False):
            _print_json(result)
            return 0

        print(f"K3 on-chain: {args.case_id}")
        print(f"  adres v případě: {len(addrs)} (high/critical: {result['high_risk_count']})")
        for a in sorted(addrs):
            s = scores[a]
            if s.level != "none":
                print(f"  [{s.level}] {a} — score={s.score}")
                for r in s.reasons[:2]:
                    print(f"      {r}")
        if all_txs:
            print(f"  transakcí načteno: {len(all_txs)} (cache: {cache_path})")
            print(f"  clusterů: {len(clusters_out)}, cyklů: {len(cycles)}")
            for c in clusters_out[:10]:
                print(f"    C{c['cluster_id']}: {', '.join(c['addresses'])} [{'; '.join(c['txids'][:3])}]")
        else:
            print("  transakce bez cache/sítě — clustering nebyl proveden (offline scoring OK)")
        for w in warnings:
            print(f"  warning: {w}", file=sys.stderr)
        return 0
    finally:
        db.close()


def cmd_darkweb(args: argparse.Namespace) -> int:
    """K4 Dark Web & Illicit Activity — ransom note + marketplace + mixer detektory.

    Skenuje textové soubory zdrojů případu (kind=file, podporované extenze,
    ≤ 4 MB); výsledek = ransom note šablony, marketplace důkazy a zmínky mixerů.
    """
    from stopa.domain.crypto.darkweb import (
        detect_marketplace_data,
        detect_mixer_mentions,
        detect_ransom_note,
    )

    _text_exts = {".txt", ".md", ".log", ".html", ".htm", ".csv"}
    max_bytes = 4 * 1024 * 1024

    db = _open_db(args.case_id)
    try:
        files_to_scan: list[tuple[str, str]] = []  # (label, abspath)
        if args.file:
            for p in args.file:
                files_to_scan.append((p, os.path.abspath(p)))
        else:
            for src in db.list_sources(args.case_id):
                if src.kind != "file":
                    continue
                ap = os.path.abspath(src.path)
                ext = os.path.splitext(ap)[1].lower()
                if ext not in _text_exts or not os.path.isfile(ap):
                    continue
                try:
                    if os.path.getsize(ap) > max_bytes:
                        continue
                except OSError:
                    continue
                files_to_scan.append((src.id, ap))

        notes_found: list[dict] = []
        marketplace_found: list[dict] = []
        mixer_mentions: set[str] = set()
        scanned: list[str] = []
        for label, path in sorted(files_to_scan):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read(max_bytes)
            except OSError as exc:
                print(f"  warning: {path}: {exc}", file=sys.stderr)
                continue
            scanned.append(label)
            rn = detect_ransom_note(text)
            if rn.is_ransom_note:
                notes_found.append(
                    {"file": label, **rn.model_dump()}
                )
            mp = detect_marketplace_data(text)
            if mp.is_marketplace:
                marketplace_found.append({"file": label, **mp.model_dump()})
            mixer_mentions.update(detect_mixer_mentions(text))

        result = {
            "case_id": args.case_id,
            "files_scanned": len(scanned),
            "ransom_notes": notes_found,
            "marketplace_evidence": marketplace_found,
            "mixer_mentions": sorted(mixer_mentions),
        }
        if getattr(args, "json", False):
            _print_json(result)
            return 0

        print(f"K4 dark web: {args.case_id} (naskenováno souborů: {len(scanned)})")
        for n in notes_found:
            fam = f" [{n['family']}]" if n["family"] else ""
            print(
                f"  RANSOM NOTE → {n['file']}{fam} "
                f"(score={n['score']}, adresy={len(n['addresses'])})"
            )
            for a in n["addresses"]:
                print(f"    - {a}")
        for m in marketplace_found:
            print(
                f"  MARKETPLACE → {m['file']} (score={m['score']}, "
                f"pgp={m['pgp_keys']}, adresy={len(m['addresses'])})"
            )
            for a in m["addresses"]:
                print(f"    - {a}")
        if mixer_mentions:
            print(f"  MIXER ZMÍNKY: {', '.join(sorted(mixer_mentions))}")
        if not notes_found and not marketplace_found and not mixer_mentions:
            print("  žádné ransom/marketplace/mixer indikátory nenalezeny")
        return 0
    finally:
        db.close()


def cmd_crypto_report(args: argparse.Namespace) -> int:
    """K4.5 — SWGDE krypto report (10 sekcí, md|html|json, Ed25519 podpis)."""
    from stopa.domain.crypto.onchain_api import TxCache
    from stopa.presentation.crypto_report import generate_crypto_report

    db = _open_db(args.case_id)
    try:
        # on-chain TX z K3 cache (pokud existuje) → timeline + fund-flow sekce
        txs_by_addr: dict[str, list] | None = None
        cache_path = _db_dir() / f"{args.case_id}.txcache.json"
        if cache_path.exists():
            try:
                cache = TxCache(cache_path)
                txs_by_addr = cache.load() or None
            except Exception as exc:  # noqa: BLE001 — report jde i bez cache
                print(f"  warning: TxCache {cache_path}: {exc}", file=sys.stderr)

        out: Path | None = None
        if args.out:
            out = Path(args.out).expanduser().resolve()
        else:
            default_name = f"crypto_report.{args.format}"
            out = (_db_dir() / "reports" / f"{args.case_id}.{default_name}")

        res = generate_crypto_report(
            db, args.case_id, args.format, out=out, txs_by_addr=txs_by_addr
        )
        if getattr(args, "json", False):
            payload = {k: v for k, v in res.model_dump().items() if k != "content"}
            payload["out"] = str(out)
            _print_json(payload)
            return 0

        print(f"K4.5 SWGDE report: {args.case_id} [{res.format}]")
        for k, v in sorted(res.stats.items()):
            print(f"  {k}: {v}")
        if res.sha256_hex:
            print(f"  sha256: {res.sha256_hex[:16]}…")
        print(f"  podpis: {'Ed25519 OK' if res.signature_b64 else 'nepodepsán (graceful)'}")
        print(f"  → {out}")
        return 0
    finally:
        db.close()


def cmd_advanced(args: argparse.Namespace) -> int:
    """K5 Advanced — DeFi + NFT + cross-chain bridge + privacy coins (+ copilot).

    Skenuje textové soubory zdrojů případu (jako K4 darkweb); cross-chain analýza
    běží nad K3 TxCache (pokud existuje); AI copilot = deterministický fallback
    (LLM v CLI bez explicitního klíče nevolejeme).
    """
    from stopa.domain.crypto.bridges import analyze_cross_chain, detect_bridge_in_text
    from stopa.domain.crypto.defi import detect_defi_in_text
    from stopa.domain.crypto.nft import detect_nft_in_text
    from stopa.domain.crypto.onchain_api import TxCache
    from stopa.domain.crypto.privacy_coins import detect_privacy_in_text
    from stopa.intelligence.crypto_copilot import run_crypto_copilot

    _text_exts = {".txt", ".md", ".log", ".html", ".htm", ".csv"}
    max_bytes = 4 * 1024 * 1024

    db = _open_db(args.case_id)
    try:
        files_to_scan: list[tuple[str, str]] = []
        if args.file:
            for p in args.file:
                files_to_scan.append((p, os.path.abspath(p)))
        else:
            for src in db.list_sources(args.case_id):
                if src.kind != "file":
                    continue
                ap = os.path.abspath(src.path)
                ext = os.path.splitext(ap)[1].lower()
                if ext not in _text_exts or not os.path.isfile(ap):
                    continue
                try:
                    if os.path.getsize(ap) > max_bytes:
                        continue
                except OSError:
                    continue
                files_to_scan.append((src.id, ap))

        defi_findings = []
        nft_findings = []
        bridge_mentions = []
        privacy_findings = []
        scanned: list[str] = []
        for label, path in sorted(files_to_scan):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read(max_bytes)
            except OSError as exc:
                print(f"  warning: {path}: {exc}", file=sys.stderr)
                continue
            scanned.append(label)
            defi_findings.extend(detect_defi_in_text(text, origin=label))
            nf = detect_nft_in_text(text, origin=label)
            if nf is not None:
                nft_findings.append(nf.model_dump())
            bf = detect_bridge_in_text(text, origin=label)
            if bf is not None:
                bridge_mentions.append(bf.model_dump())
            privacy_findings.extend(detect_privacy_in_text(text, origin=label))

        # cross-chain analýza nad K3 TxCache (adresy per chain)
        per_chain: dict[str, set[str]] = {}
        cache_path = _db_dir() / f"{args.case_id}.txcache.json"
        if cache_path.exists():
            try:
                txs_by_addr = TxCache(cache_path).load() or {}
                for addr, txs in txs_by_addr.items():
                    for t in txs:
                        per_chain.setdefault(t.chain.lower(), set()).add(addr)
            except Exception as exc:  # noqa: BLE001 — jde i bez cache
                print(f"  warning: TxCache {cache_path}: {exc}", file=sys.stderr)
        bridge_links = analyze_cross_chain({c: sorted(a) for c, a in per_chain.items()})

        # kritické sankční shody z K3 (adresy crypto artefaktů) — pro copilota
        critical_sanctions = 0
        from stopa.domain.crypto.risk_scoring import score_addresses as k3_score

        addrs: set[str] = set()
        for art in db.list_artifacts(artifact_type="crypto_detection"):
            d = art.details or {}
            for a in d.get("addresses") or []:
                if isinstance(a, dict) and (a.get("raw_value") or "").strip():
                    addrs.add((a["raw_value"] or "").strip())
        if addrs:
            critical_sanctions = sum(1 for sc in k3_score(sorted(addrs)).values() if sc.score >= 100)

        summary = {
            "case_id": args.case_id,
            "defi_findings": len(defi_findings),
            "nft_findings": len(nft_findings),
            "bridge_links": len(bridge_links),
            "privacy_findings": len(privacy_findings),
            "critical_sanctions": critical_sanctions,
        }
        copilot = run_crypto_copilot(None, summary)

        result = {
            "case_id": args.case_id,
            "files_scanned": len(scanned),
            "defi_findings": [f.model_dump() for f in defi_findings],
            "nft_findings": nft_findings,
            "bridge_text_mentions": bridge_mentions,
            "cross_chain_links": [l.model_dump() for l in bridge_links],
            "privacy_findings": [f.model_dump() for f in privacy_findings],
            "copilot": copilot.to_dict(),
        }
        if getattr(args, "json", False):
            _print_json(result)
            return 0

        print(f"K5 advanced: {args.case_id} (naskenováno souborů: {len(scanned)})")
        for f in defi_findings:
            terms = ", ".join(f.matched_terms) or "—"
            addrs_txt = f", adresy={', '.join(f.matched_addresses)}" if f.matched_addresses else ""
            print(
                f"  DEFI → {f.protocol} [{f.origin}] (score={f.score}, termíny: {terms}{addrs_txt})"
            )
        for nf in nft_findings:
            coll = ", ".join(nf["collections"]) or "—"
            mkt = ", ".join(nf["marketplaces"]) or "—"
            tids = ",".join(str(t) for t in nf["token_ids"]) or "—"
            print(
                f"  NFT → [{nf['origin']}] (score={nf['score']}, sbírky: {coll}, "
                f"marketplaces: {mkt}, token_id: {tids})"
            )
        for bf in bridge_mentions:
            print(f"  BRIDGE TEXT → [{bf['origin']}]: {', '.join(bf['bridges'])}")
        for l in bridge_links:
            bn = f" ({l.bridge_name})" if l.bridge_name else ""
            print(
                f"  CROSS-CHAIN LINK → {l.entity} chains={','.join(l.chains)} "
                f"[{l.evidence}{bn}]"
            )
        for pf in privacy_findings:
            val = pf.value if pf.evidence_kind != "text_term" else ""
            print(
                f"  PRIVACY → {pf.coin}:{pf.evidence_kind}"
                + (f" {val}" if val else "")
                + f" [{pf.origin}]"
            )
        c = copilot.to_dict()
        print(f"  COPILOT: risk={c['risk_level']} (source={c['source']})")
        for kf in c["key_findings"]:
            print(f"    - {kf}")
        if not defi_findings and not nft_findings and not bridge_mentions \
                and not bridge_links and not privacy_findings:
            print("  žádné K5 indikátory nenalezeny")
        return 0
    finally:
        db.close()


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

    # F5.1 — Merkle zamčení případu: DB-only ověření všech pečetí (nezávislé na
    # E1 re-hashování; nový audit řádek pečeť neruší — snapshot s předponou).
    seal_reports = db.seal_repo.verify_all()
    seals_valid = sum(1 for r in seal_reports if r["ok"])

    db.log_operation(
        "hash_verified",
        actor=case_examiner(db, args.case_id),
        details={
            "ok": ok,
            "mismatched": mismatched,
            "missing": missing,
            "skipped": skipped,
            "seals_total": len(seal_reports),
            "seals_valid": seals_valid,
        },
    )
    if json_mode:
        _print_json({
            "ok": ok, "mismatched": mismatched, "missing": missing,
            "skipped": skipped, "problems": problems[: args.limit],
            "sources": len(sources),
            "merkle_seal": {
                "total": len(seal_reports),
                "valid": seals_valid,
                "seals": seal_reports,
            },
        })
    else:
        print(f"Integrita: {ok} OK, {mismatched} rozdílů, {missing} chybí, {skipped} nečitelných")
        for p in problems[: args.limit]:
            print(f"  ! {p}")
        if len(problems) > args.limit:
            print(f"  … a dalších {len(problems) - args.limit}")
        if seal_reports:
            print(f"Merkle zamčení (F5.1): {len(seal_reports)} pečetí — {seals_valid} platných")
            for r in seal_reports:
                if r["ok"]:
                    status = "root OK, podpis OK"
                else:
                    changed = ", ".join(r["changed_tables"]) or "—"
                    status = (f"root {'OK' if r['root_ok'] else 'ROZDÍL'} ({changed}), "
                              f"podpis {'OK' if r['sig_ok'] else 'NEPLATNÝ'}")
                print(f"  [{'✓' if r['ok'] else '✗'}] #{r['id']} {r['ts']} — {status}")
        else:
            print("Merkle zamčení (F5.1): žádné pečetě (stopa seal <case_id>)")
    db.close()
    return 1 if (mismatched or missing or seals_valid != len(seal_reports)) else 0


def cmd_seal(args: argparse.Namespace) -> int:
    """F5.1 — Merkle zamčení případu: snapshot stavu zamčený podepsaným kořenem."""
    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    actor = case_examiner(db, args.case_id)
    try:
        seal = db.seal_case(reason=args.reason, actor=actor)
    except RuntimeError as e:  # chybí volitelný balík cryptography
        if not json_mode:
            print(f"Ed25519 nedostupné ({e})", file=sys.stderr)
        db.close()
        return 2
    if seal is None:
        msg = "Ed25519 klíč případu nevygenerován (vyžaduje balík cryptography)"
        if json_mode:
            _print_json({"ok": 0, "seal_id": None, "reason": "no_key"})
        else:
            print(msg, file=sys.stderr)
        db.close()
        return 2
    if json_mode:
        _print_json(seal)
    else:
        print(f"Případ zamčen (F5.1): pečeť #{seal['id']}")
        print(f"  Root: {seal['root_hash']}")
        print(
            f"  Rozsah: artifacts={seal['artifacts']}, "
            f"timeline_events={seal['timeline_events']}, audit_log={seal['audit_log']} řádků"
        )
        who = seal["sealed_by"] or "—"
        why = f" — {seal['reason']}" if seal["reason"] else ""
        print(f"  Zamčeno: {who} ({seal['ts']}){why}")
    db.close()
    return 0


def _ed25519_fingerprint(public_b64: str) -> str:
    """P0-2: krátký otisk veřejného klíče (SHA-256 raw klíče, první 8 B hex)."""
    import base64 as _b64
    import hashlib

    return hashlib.sha256(_b64.b64decode(public_b64)).hexdigest()[:16]


def _rotate_err(e: RuntimeError, json_mode: bool) -> None:
    """P0-2: jednotná chyba `rotate-key` (chybí cryptography)."""
    if json_mode:
        _print_json({"ok": False, "error": str(e)})
    else:
        print(f"Ed25519 nedostupné ({e})", file=sys.stderr)


def cmd_integrity_keys(args: argparse.Namespace) -> int:
    """P0-2 — export veřejného integrity klíče případu (nezávislá verifikace).

    Třetí strana drží pouze tento výstup + kontrolní body a může ověřit,
    že audit trail nebyl upraven od posledního kontrolního bodu. Exit 0 =
    klíč existuje; 2 = nevygenerován (použij `stopa integrity --init-key`).
    """
    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    try:
        pub = db.integrity_public_key()
        if pub is None:
            msg = "Ed25519 klíč nevygenerován (použij `stopa integrity --init-key`)"
            if json_mode:
                _print_json({"ok": False, "error": "no_key"})
            else:
                print(msg, file=sys.stderr)
            return 2
        out = {
            "case_id": args.case_id,
            "public_key_b64": pub,
            "fingerprint_sha256_8b": _ed25519_fingerprint(pub),
            # P0-2: každý kontrolní bod nesne i klíč podpisu (rotace-safe);
            # export obsahuje historii generací pro nezávislou verifikaci.
            "key_generations": [
                {
                    "checkpoint_id": cp["id"],
                    "ts": cp["ts"],
                    "reason": cp["reason"],
                    "public_key_b64": cp["public_key_b64"] or pub,
                    "fingerprint_sha256_8b": _ed25519_fingerprint(
                        cp["public_key_b64"] or pub
                    ),
                }
                for cp in db.list_integrity_checkpoints()
            ],
        }
        if json_mode:
            _print_json(out)
        else:
            print(f"Ed25519 veřejný klíč případu {args.case_id}:")
            print(f"  b64:       {pub}")
            print(f"  otisk:     {_ed25519_fingerprint(pub)} (SHA-256, první 8 B)")
            gens = out["key_generations"]
            if gens:
                print(f"  kontrolních bodů: {len(gens)}")
    finally:
        db.close()
    return 0


def cmd_rotate_key(args: argparse.Namespace) -> int:
    """P0-2 — rotace Ed25519 integrity klíče případu.

    Staré kontrolní body zůstávají ověřitelné (drží vlastní public key);
    nová generace je ukotvena rotačním bodem podepsaným NOVÝM klíčem.
    Exit 0 = rotace provedena; 2 = chybí cryptography / klíč nevygenerován.
    """
    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    try:
        if db.integrity_public_key() is None:
            # first-time init — zachováme staré chování `integrity --init-key`
            try:
                priv_raw, pub = db.ensure_integrity_key()  # RuntimeError bez crypto
            except RuntimeError as e:
                _rotate_err(e, json_mode)
                return 2
            del priv_raw
            out = {
                "rotated": False,
                "initialized": True,
                "public_key_b64": pub,
                "fingerprint_sha256_8b": _ed25519_fingerprint(pub),
            }
        else:
            try:
                out = db.audit_repo.rotate_integrity_key(reason=args.reason)
                if out is None:  # prakticky nedosažitelné (klíč existuje)
                    raise RuntimeError("rotace se nepodařila")
                out["fingerprint_sha256_8b"] = _ed25519_fingerprint(
                    out["public_key_b64"]
                )
            except RuntimeError as e:  # chybí volitelný balík cryptography
                _rotate_err(e, json_mode)
                return 2
        if json_mode:
            _print_json({"ok": True, **out})
        else:
            verb = "inicializován" if out.get("initialized") else "rotace provedena"
            print(f"P0-2 Ed25519 klíč {verb}:")
            old = out.get("old_public_key")
            if old:
                print(f"  starý otisk: {_ed25519_fingerprint(old)}")
            print(
                f"  nový otisk:  {out['fingerprint_sha256_8b']} "
                f"(SHA-256, první 8 B)"
            )
            cp_id = out.get("checkpoint_id")
            if cp_id is not None:
                print(f"  rotační kontrolní bod: #{cp_id} ({out.get('reason') or 'key_rotation'})")
    finally:
        db.close()
    return 0


def cmd_parser_status(args: argparse.Namespace) -> int:
    """P0-4 validation lab — per-parser validační status (registry level).

    Staví na C3 registry (`domain.validation_registry`): pro každý registrovaný
    parser vypíše validační status, pokrytí testy a reference dataset. Nevyžaduje
    case DB — jde o stav registrace parserové sady, ne jednotlivého případu.

    Exit: 0 = OK (případně --fail-on-unvalidated a vše validované);
          1 = chyba;
          2 = --fail-on-unvalidated a existují unvalidované parserty (CI gate).
    """
    json_mode = getattr(args, "json", False) or getattr(args, "format", None) == "json"
    fail_on_unvalidated = getattr(args, "fail_on_unvalidated", False)

    from stopa.data.parser_status_service import load_parser_status

    try:
        report = load_parser_status()
    except Exception as e:  # noqa: BLE001 — CLI obal: libovolná chyba → čitelný výstup
        if json_mode:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
        else:
            print(f"parser status selhal: {e}", file=sys.stderr)
        return 1

    if json_mode:
        print(json.dumps(report, ensure_ascii=False, default=str))
    else:
        print(
            f"Parser status (C3 registry + P0-4): "
            f"{report['validated']}/{report['count']} validováno, "
            f"reference datasety {report['dataset_coverage_pct']} %"
        )
        for r in report["parsers"]:
            ds = "✓" if r["reference_dataset"] else "-"
            lim = f", {r['limitations_count']} limitací" if r["limitations_count"] else ""
            print(
                f"{r['validation_status']:<12} {r['parser_id']:<34} "
                f"v{r['version']}  formáty={r['formats_count']}  "
                f"testy={r['direct_tests']}/{r['total_tests']}  dataset={ds}{lim}"
            )
        if report["unvalidated"]:
            print(f"\nUnvalidované parserty: {', '.join(report['unvalidated'])}")

    return (2 if fail_on_unvalidated and report["unvalidated"] else 0)


def cmd_reparse(args: argparse.Namespace) -> int:
    """F5.3 — re-run extrakce s deklarovánou verzí parseru + diff report.

    Semantika (staví na C5 Reproducibility Engine):
      1. base snapshot = nejnovější extract operace zdroje (analysis_operations),
      2. ověření vstupních souborů (SHA-256 na disku vs. snapshot),
      3. čistá dočasná DB — původní případ se nedotkne (append-only evidence);
         extrakce běží s prokládanou verzí parserové sady (pinned provenience),
      4. diff report: deterministický souhrn výstupů + mapy verzí parserů,
      5. snapshot storage — reparse se appenduje do analysis_operations.

    Exit: 0 = vstupy OK a výstupy identické (reprodukovatelné); 1 = chyba;
    2 = nalezeny rozdíly (vstupy nebo výstupy).
    """
    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    try:
        import tempfile
        import time as _time

        from stopa import __version__ as _stopa_ver
        from stopa.domain.hashing import hash_file
        from stopa.domain.reproducibility import (
            compare_outputs,
            verify_inputs,
            version_diffs,
        )
        from stopa.pipeline import parser_versions, process_source, summarize_outputs

        base_op = db.artifact_repo.latest_extract_op(source_id=args.source_id)
        if base_op is None:
            msg = "žádná zaznamenaná extrakční operace (op_type='extract') v případě"
            print(msg, file=sys.stderr) if not json_mode else _print_json(
                {"ok": False, "error": msg}
            )
            return 1
        source_id = base_op.source_id
        src_row = db.conn.execute(
            "SELECT path FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if src_row is None:
            raise KeyError(f"zdroj {source_id} nenalezen v DB")
        root = Path(src_row["path"])
        if not root.exists():
            raise FileNotFoundError(f"kořen zdroje neexistuje na disku: {root}")
        profile_name = base_op.params_json.get("profile", "forensic")

        # 1) vstupní ověření — aktuální hashe na disku vs. base snapshot (C5)
        current_hashes: dict[str, str | None] = {}
        for f in base_op.input_files:
            rel = f.get("rel_path") or ""
            p = root / rel if not root.is_file() else root
            try:
                digests = hash_file(p, ["sha256"]) or {}
                current_hashes[rel] = digests.get("sha256")
            except OSError:
                current_hashes[rel] = None  # soubor zmizel / nečitelný
        inputs_ok, input_diffs = verify_inputs(list(base_op.input_files), current_hashes)

        # 2) čistá dočasná DB — původní případ se nedotkne (append-only evidence)
        workdir = Path(args.workdir) if getattr(args, "workdir", None) else Path(
            tempfile.gettempdir()
        )
        tmp_db_path = workdir / f"stopa-reparse-{source_id}.db"
        t0 = _time.monotonic()
        replay_db = CaseDB(tmp_db_path)
        try:
            case = Case(name=f"reparse {source_id}")
            replay_db.add_case(case)
            src = EvidenceSource(
                case_id=case.id, kind="folder", path=str(root), size_bytes=None
            )
            replay_db.add_source(src)
            result = process_source(
                replay_db,
                src.id,
                root,
                profile_name=profile_name,
                pinned_parser_version=args.parser_version,
            )
        finally:
            replay_db.close()

        # 3) snapshot storage — reparse operace se appenduje do case DB (historie verzí)
        new_versions = {**parser_versions(), "pinned": args.parser_version}
        new_op_id = db.record_operation(
            "reparse",
            case_id=base_op.case_id,
            source_id=source_id,
            input_files=list(base_op.input_files),
            parser_versions=new_versions,
            stopa_version=_stopa_ver,
            config_hash=base_op.config_hash,
            params={
                "profile": profile_name,
                "pinned_parser_version": args.parser_version,
                "original_op_id": base_op.id,
            },
            outputs=summarize_outputs(result),
            duration_ms=int((_time.monotonic() - t0) * 1000),
        )
        db.log_operation(
            "reparse_completed",
            details={
                "source_id": source_id,
                "pinned_parser_version": args.parser_version,
                "original_op_id": base_op.id,
                "reparse_op_id": new_op_id,
                "inputs_identical": inputs_ok,
            },
        )

        # 4) diff report — výstupy + verze parserů (base vs. reparse)
        out_report = compare_outputs(base_op.outputs_json, summarize_outputs(result))
        vdiffs = version_diffs(base_op.parser_versions or {}, new_versions)
        out = {
            "ok": True,
            "case_id": db.path.stem,
            "source_id": source_id,
            "profile": profile_name,
            "pinned_parser_version": args.parser_version,
            "original_op_id": base_op.id,
            "reparse_op_id": new_op_id,
            "inputs_identical": inputs_ok,
            "input_diffs": list(input_diffs),
            "outputs_identical": out_report.identical,
            "output_diffs": list(out_report.diffs),
            "version_diffs": list(vdiffs),
        }
        if json_mode:
            _print_json(out)
        else:
            print(f"Reparse (F5.3) — zdroj {source_id}, prokládaná verze parseru: {args.parser_version}")
            print(f"  base snapshot: op {base_op.id} ({profile_name}) → reparse op {new_op_id}")
            if inputs_ok:
                print(f"  vstupní soubory: OK ({len(base_op.input_files)}× SHA-256 shodné)")
            else:
                print("  vstupní soubory: ZMĚNENY")
                for d in list(input_diffs)[:10]:
                    print(f"    - {d}")
                if len(input_diffs) > 10:
                    print(f"    … a dalších {len(input_diffs) - 10}")
            if out_report.identical:
                print("  výstupy: identické (reprodukovatelné)")
            else:
                print("  výstupy: LIŠÍ")
                for d in list(out_report.diffs)[:20]:
                    print(f"    - {d}")
            if vdiffs:
                print("  verze parserů:")
                for d in list(vdiffs)[:15]:
                    print(f"    - {d}")
        return 0 if (inputs_ok and out_report.identical) else 2
    except Exception as e:  # noqa: BLE001 — defenzivně: reparse nezanechá traceback
        if json_mode:
            _print_json({"ok": False, "error": f"reparse selhalo: {e}"})
        else:
            print(f"reparse selhalo: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()


# ── F5.4 — Write-blocker integration API (status/attach/remove) ────────────────
def cmd_wb_status(args: argparse.Namespace) -> int:
    """F5.4 — aktuální WB stav + rozhodnutí brány (exit 2 = blokováno)."""
    db = _open_db(args.case_id)
    repo = WriteBlockerRepository(db.conn, db.audit_repo)
    state = repo.latest_state()
    require = _load_require_write_blocker()
    gate = ingest_gate(state, require)
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "case_id": args.case_id,
                    "state": state,
                    "require_wb": require,
                    "allowed": gate.allowed,
                    "warning": gate.warning,
                },
                ensure_ascii=False,
            )
        )
    else:
        if state is None:
            print("WB: není připojen (žádný wb_* záznam v audit logu)")
        elif state.get("attached"):
            v = vendor_label(state.get("vendor")) or state.get("vendor") or "?"
            prod = f" {state['product']}" if state.get("product") else ""
            dev = f" ({state['device']})" if state.get("device") else ""
            print(
                f"WB: ✓ připojen — {v}{prod}{dev} "
                f"@ {state.get('ts') or '?'} by {state.get('actor') or '—'}"
            )
        else:
            reason = state.get("reason") or "—"
            print(f"WB: ⚠ odebrán ({reason}) @ {state.get('ts') or '?'}")
        gate_note = "zapnutá" if require else "vypnutá"
        verdict = "pouští ingest" if gate.allowed else "blokuje ingest"
        print(f"Brána (require_write_blocker): {gate_note} → {verdict}")
    return 0 if gate.allowed else 2


def cmd_wb_attach(args: argparse.Namespace) -> int:
    """F5.4 — zaznamenat připojení WB (auto-detekce vendoru z --device)."""
    db = _open_db(args.case_id)
    repo = WriteBlockerRepository(db.conn, db.audit_repo)
    device = (args.device or "").strip()
    match = detect_write_blocker(device) if device else None
    vendor_id = args.vendor or (match.vendor_id if match else None)
    if not vendor_id:
        ids = ", ".join(known_vendor_ids())
        print(
            f"Auto-detekce vendoru nezdarila ({device!r}) — zadte --vendor {ids}",
            file=sys.stderr,
        )
        return 2
    row_id = repo.attach(
        vendor=vendor_id,
        product=args.product,
        device=device or None,
        notes=args.notes,
        actor=case_examiner(db, args.case_id),
    )
    label = vendor_label(vendor_id) or vendor_id
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "case_id": args.case_id,
                    "vendor": vendor_id,
                    "label": label,
                    "detected_from_device": match is not None and bool(device),
                    "audit_id": row_id,
                },
                ensure_ascii=False,
            )
        )
    else:
        src_note = f" (auto-detekce z {device!r})" if match else ""
        print(f"✓ WB připojen: {label}{src_note} [audit #{row_id}]")
    return 0


def cmd_wb_remove(args: argparse.Namespace) -> int:
    """F5.4 — zaznamenat odebrání WB."""
    db = _open_db(args.case_id)
    repo = WriteBlockerRepository(db.conn, db.audit_repo)
    row_id = repo.remove(reason=args.reason, actor=case_examiner(db, args.case_id))
    if getattr(args, "json", False):
        print(json.dumps({"case_id": args.case_id, "audit_id": row_id}, ensure_ascii=False))
    else:
        reason_note = f" ({args.reason})" if args.reason else ""
        print(f"✓ WB odebrán{reason_note} [audit #{row_id}]")
    return 0


def cmd_compliance(args: argparse.Namespace) -> int:
    """F5.2 — SWGDE/ISO 27037 compliance report (JSON + PDF, Ed25519 podpis)."""
    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    try:
        from stopa.presentation.compliance_report import generate_compliance_report

        out = generate_compliance_report(db, args.case_id, out_dir=args.out)
    except KeyError as e:  # případ nenalezen
        if json_mode:
            _print_json({"ok": False, "error": str(e)})
        else:
            print(str(e), file=sys.stderr)
        db.close()
        return 1
    if json_mode:
        import json as _json

        doc = _json.loads(out["json_path"].read_text(encoding="utf-8"))
        _print_json({"ok": True, **doc})
    else:
        signed = "podpsán (Ed25519)" if out["signature_b64"] else "nepodepsaný (chybí cryptography)"
        print(f"Compliance report (F5.2) — {args.case_id}, {signed}")
        print(f"  JSON: {out['json_path']}")
        pdf = out.get("pdf_path")
        if pdf is not None:
            print(f"  PDF:  {pdf}")
        else:
            print("  PDF:  chybí (balík weasyprint nenainstalován)", file=sys.stderr)
        if out.get("digest"):
            print(f"  Digest SHA-256: {out['digest']}")
    db.close()
    return 0


def cmd_daubert(args: argparse.Namespace) -> int:
    """F5.5 — Daubert challenge preparedness pack (1-click JSON balík pro soud)."""
    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    try:
        from stopa.presentation.daubert import generate_daubert_pack

        out = generate_daubert_pack(db, args.case_id, out_dir=args.out)
    except KeyError as e:  # případ nenalezen
        if json_mode:
            _print_json({"ok": False, "error": str(e)})
        else:
            print(str(e), file=sys.stderr)
        db.close()
        return 1
    if json_mode:
        import json as _json

        doc = _json.loads(out["json_path"].read_text(encoding="utf-8"))
        _print_json({"ok": True, **doc})
    else:
        signed = "podepsán (Ed25519)" if out["signature_b64"] else "nepodepsaný (chybí cryptography)"
        print(f"Daubert pack (F5.5) — {args.case_id}, {signed}")
        print(f"  JSON: {out['json_path']}")
        print(
            f"  Reference: {out['references_total']} "
            f"(parserů v případu: {out['case_parsers']})"
        )
        if out.get("digest"):
            print(f"  Digest SHA-256: {out['digest']}")
    db.close()
    return 0


def cmd_attack_map(args: argparse.Namespace) -> int:
    """F6.3 — MITRE ATT&CK mapping: heat-mapa taktik×technik + STIX intrusion-set."""
    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    try:
        from stopa.domain.mitre_attack import (
            ATTACK_TACTICS,
            build_attack_heatmap,
            to_stix_bundle_intrusion_set,
        )

        arts = db.list_artifacts(limit=10_000)
        hm = build_attack_heatmap(arts)
        case_name = None
        case = db.get_case(args.case_id)  # type: ignore[call-arg]
        if case is not None:
            case_name = getattr(case, "name", None)

        fmt = args.format
        if fmt == "stix":
            payload = to_stix_bundle_intrusion_set(
                args.case_id, case_name=case_name, heatmap=hm
            )
        else:
            import json as _json

            payload = _json.dumps(hm, ensure_ascii=False, indent=2)

        if args.out:
            from pathlib import Path

            out_path = Path(args.out).expanduser().resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(payload + "\n", encoding="utf-8")
            target = str(out_path)
        else:
            target = None

        s_ = hm["summary"]
        if json_mode:
            envelope: dict = {
                "ok": True,
                "format": fmt,
                "case_id": args.case_id,
                "out": target,
                **s_,
            }
            if target is None:  # celý payload v JSON obálce (jediný dokument na stdout)
                if fmt == "json":
                    envelope["heatmap"] = hm
                else:
                    import json as _stix_json

                    envelope["bundle"] = _stix_json.loads(payload)
            _print_json(envelope)
        else:
            print(
                f"ATT&CK map (F6.3) — {args.case_id}, formát {fmt}"
                + (f", výstup {target}" if target else "")
            )
            print(
                f"  Artefakty: {s_['artifacts_total']} "
                f"(mapováno {s_['mapped_artifacts']}, techniky {s_['techniques_hit']})"
            )
            by_tactic: dict[str, list[dict]] = {}
            for t in hm["techniques"]:
                by_tactic.setdefault(t["tactic"], []).append(t)
            for tid, tname in ATTACK_TACTICS:
                rows = by_tactic.get(tid)
                if not rows:
                    continue
                parts = ", ".join(
                    f"{r['id']} {r['name']}" + (f" (×{r['count']})" if r["count"] > 1 else "")
                    for r in sorted(rows, key=lambda x: x["id"])
                )
                print(f"  [{tid}] {tname}: {parts}")
    finally:
        db.close()
    return 0


# ── F6.4 — Plugin ecosystem ─────────────────────────────────────


def _plugin_row(p) -> dict:
    """LoadedPlugin → JSON-safe řádek (sdílené CLI + Web)."""
    return {
        "name": p.name,
        "version": p.version,
        "description": p.description,
        "author": p.author,
        "min_stopa_version": p.min_stopa_version,
        "verified": p.verified,
        "capabilities": list(p.capabilities),
        "issues": list(p.issues),
        "path": str(p.path),
    }


def _discover_plugin(args_name: str):
    """Najde plugin podle jména; vrací (plugin|None, settings)."""
    import stopa as _stopa_pkg
    from stopa.data.plugin_loader import discover_plugins

    settings = _load_settings_dict()
    plugins = discover_plugins(settings=settings, stopa_version=_stopa_pkg.__version__)
    return plugins.get(args_name), settings


def _plugin_manifest(name_path: Path):
    """Re-parse manifestu (data vrstva — spec pro rozřešení kapacit)."""
    from stopa.domain.plugins import parse_manifest

    return parse_manifest(json.loads((name_path / "plugin.json").read_text(encoding="utf-8")))


def _plugin_exec_cap_in_process(plugin, cap: str, args) -> object:
    """In-process běh jedné kapacity (ověřená cesta; sandbox = tenže kód v subprocessu)."""
    from stopa.data.plugin_loader import (
        profile_to_dict,
        resolve_ai_tools,
        resolve_extractors,
        resolve_triage_profiles,
    )

    manifest = _plugin_manifest(plugin.path)
    if cap == "extractor":
        key = getattr(args, "key", None) or ""
        spec = next((e for e in manifest.extractors if e.key == key), None)
        if spec is None:
            raise ValueError(f"extractor klíč {key!r} neexistuje v pluginu {plugin.name}")
        resolved = resolve_extractors(plugin.path, plugin.name, (spec,))
        out = []
        for f in getattr(args, "files", []) or []:
            arts = resolved[0].extract_fn(Path(f))
            out.extend(a.model_dump() if hasattr(a, "model_dump") else dict(a) for a in arts)
        return out
    if cap == "triage_profile":
        profiles = resolve_triage_profiles(plugin.path, plugin.name, manifest.triage_profiles)
        return [profile_to_dict(pr) for pr in profiles]
    if cap == "ai_tool":
        tools = resolve_ai_tools(plugin.path, plugin.name, manifest.ai_tools)
        want = getattr(args, "tool", None) or ""
        tool = next((t for t in tools if t.name == want), tools[0] if len(tools) == 1 else None)
        if tool is None:
            avail = ", ".join(t.name for t in tools)
            raise ValueError(f"AI tool {want!r} neexistuje (dostupné: {avail})")
        params_raw = getattr(args, "params", "{}") or "{}"
        params = json.loads(params_raw)
        case_id = getattr(args, "case_id", None)
        if not case_id:
            raise ValueError("ai_tool vyžaduje --case-id")
        db = _open_db(case_id)
        try:
            return tool.handler(db, case_id, params)
        finally:
            db.close()
    raise ValueError(f"neznámá kapacita {cap!r}")  # pragma: no cover


def cmd_plugin_list(args: argparse.Namespace) -> int:
    """F6.4 — seznam detekovaných pluginů (manifest + stav ověření)."""
    import stopa as _stopa_pkg
    from stopa.data.plugin_loader import discover_plugins

    settings = _load_settings_dict()
    plugins = discover_plugins(settings=settings, stopa_version=_stopa_pkg.__version__)
    rows = sorted(plugins.values(), key=lambda x: x.name)
    if getattr(args, "json", False):
        _print_json({"ok": True, "count": len(rows), "plugins": [_plugin_row(r) for r in rows]})
        return 0
    if not rows:
        print("Žádné pluginy nenalezeny (settings plugins_dirs / STOPA_PLUGINS_DIR / ~/.stopa/plugins)")
        return 0
    for p in rows:
        mark = "ověřený" if p.verified else "sandbox "
        caps = ",".join(p.capabilities) or "-"
        warn = f"  [{len(p.issues)} upozornění]" if p.issues else ""
        print(f"{p.name} v{p.version}  ({mark})  [{caps}]  {p.description}{warn}")
    return 0


def cmd_plugin_info(args: argparse.Namespace) -> int:
    """F6.4 — detail jednoho pluginu."""
    plugin, _ = _discover_plugin(args.name)
    if plugin is None:
        print(f"Plugin nenalezen: {args.name}", file=sys.stderr)
        return 1
    row = _plugin_row(plugin)
    if getattr(args, "json", False):
        _print_json({"ok": True, "plugin": row})
        return 0
    print(f"{row['name']} v{row['version']} — {row['description'] or '(bez popisu)'}")
    print(f"  autor:          {row['author'] or '-'}")
    print(f"  min_stopa:      {row['min_stopa_version']}")
    print(f"  stav:           {'ověřený (in-process)' if row['verified'] else 'neověřený (sandbox)'}")
    print(f"  kapacity:       {', '.join(row['capabilities']) or '-'}")
    print(f"  cesta:          {row['path']}")
    for issue in row["issues"]:
        print(f"  upozornění:     {issue}")
    return 0


def cmd_plugin_verify(args: argparse.Namespace) -> int:
    """F6.4 — správa allowlistu ověřených pluginů (settings.json plugins_verified)."""
    settings = _load_settings_dict()
    raw = settings.get("plugins_verified")
    names = {x for x in raw if isinstance(x, str)} if isinstance(raw, list) else set()
    action = "přidán" if args.add else "odebrán"
    if args.add:
        names.add(args.name)
    elif args.name not in names:
        print(f"Plugin {args.name} nebyl v allowlistu (nic neodebráno)", file=sys.stderr)
        return 1
    else:
        names.discard(args.name)
    settings["plugins_verified"] = sorted(names)
    _save_settings_dict(settings)
    print(f"{action}: {args.name} → allowlist {sorted(names)}")
    return 0


def cmd_plugin_run(args: argparse.Namespace) -> int:
    """F6.4 — běh kapacity pluginu; neověřený = sandbox subprocess s limity."""
    import stopa as _stopa_pkg
    from stopa.data.plugin_loader import discover_plugins, sandbox_exec
    from stopa.domain.plugins import sandbox_limits as parse_sandbox_limits

    settings = _load_settings_dict()
    plugins = discover_plugins(settings=settings, stopa_version=_stopa_pkg.__version__)
    plugin = plugins.get(args.name)
    if plugin is None:
        print(f"Plugin nenalezen: {args.name}", file=sys.stderr)
        return 1

    argv = [args.name, "--cap", args.cap]  # sandbox_exec doplní "plugin-run" sám
    if args.cap == "extractor":
        argv += ["--key", args.key or ""] + [f for x in (args.files or []) for f in ("--file", x)]
    elif args.cap == "ai_tool":
        if args.tool:
            argv += ["--tool", args.tool]
        if args.case_id:
            argv += ["--case-id", args.case_id]
        argv += ["--params", args.params or "{}"]

    sandboxed = not plugin.verified
    try:
        if sandboxed:
            # P0-3: workdir=None → sandbox_exec sám vytvoří izolovaný jednorázový workdir
            payload = sandbox_exec(
                argv, limits=parse_sandbox_limits(settings.get("plugin_sandbox")), workdir=None
            )
            result = payload.get("result")
        else:
            result = _plugin_exec_cap_in_process(plugin, args.cap, args)
    except (ValueError, TypeError, ImportError) as exc:
        print(f"Plugin běh selhal: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        _print_json({"ok": True, "name": plugin.name, "cap": args.cap, "sandboxed": sandboxed, "result": result})
    else:
        mode = "sandbox" if sandboxed else "in-process"
        print(f"{plugin.name} / {args.cap} ({mode}):")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_plugin_run_entry(args: argparse.Namespace) -> int:
    """F6.4 — interní entry point sandbox subprocessu (přímý běh, JSON stdout)."""
    plugin, _ = _discover_plugin(args.name)
    if plugin is None:
        print(json.dumps({"ok": False, "error": f"plugin nenalezen: {args.name}"}))
        return 1
    try:
        result = _plugin_exec_cap_in_process(plugin, args.cap, args)
        json.dumps(result, ensure_ascii=False)  # enforce JSON-safety dříve než tisk
    except Exception as exc:  # noqa: BLE001 — sandbox hlásí cokoliv jako error envelope
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    return 0


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
    "seal": "stopa seal case-abc --reason 'před soudním předložením'",
    "integrity-keys": "stopa integrity-keys case-abc --json",
    "rotate-key": "stopa rotate-key case-abc --reason 'legace v týmu'",
    "parser-status": "stopa parser-status --format json",
    "compliance": "stopa compliance case-abc --out ./reports   # SWGDE/ISO 27037 report",
    "daubert": "stopa daubert case-abc   # F5.5 — Daubert pack (peer-reviewed reference + error rates)",
    "attack-map": "stopa attack-map case-abc --format stix --out ./map.json   # F6.3 — MITRE ATT&CK heat-mapa",
    "reparse": "stopa reparse case-abc --parser-version 2.4   # F5.3 — pinned verze + diff report",
    "wb": "stopa wb attach case-abc --device 'Tableau TBW-100'   # F5.4 — WB připojení + auto-detekce",
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
    add_p.add_argument("--workers", type=int, default=None, metavar="N",
                       help="F2.4 počet worker procesů/vláken (default: min(8, jádra CPU))")
    add_p.add_argument("--pool", choices=["auto", "threads", "processes"], default="auto",
                       help="F2.4 typ poolu: auto = procesy pro N>1 (GIL), threads = E3 režim")
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

    seal_p = _ex_sub(sub, "seal",
                     help="F5.1 — Merkle zamčení případu (snapshot stavu zamčený podepsaným kořenem)")
    seal_p.add_argument("case_id")
    seal_p.add_argument("--reason", metavar="DUVOD", default=None,
                        help="důvod zamčení (např. 'před soudním předložením')")
    _add_json_flag(seal_p)
    seal_p.set_defaults(func=cmd_seal)

    ik_p = _ex_sub(sub, "integrity-keys",
                   help="P0-2 — export Ed25519 integrity klíče případu (nezávislá verifikace)")
    ik_p.add_argument("case_id")
    _add_json_flag(ik_p)
    ik_p.set_defaults(func=cmd_integrity_keys)

    rk_p = _ex_sub(sub, "rotate-key",
                   help="P0-2 — rotace Ed25519 integrity klíče (staré body zůstávají ověřitelné)")
    rk_p.add_argument("case_id")
    rk_p.add_argument("--reason", metavar="DUVOD", default=None,
                      help="důvod rotace (ukládá se do rotačního kontrolního bodu)")
    _add_json_flag(rk_p)
    rk_p.set_defaults(func=cmd_rotate_key)

    ps_p = _ex_sub(sub, "parser-status",
                   help="P0-4 validation lab — per-parser validační status (C3 registry + testy)")
    ps_p.add_argument("--format", choices=["text", "json"], default="text",
                      help="formát výstupu (default: textová tabulka)")
    _add_json_flag(ps_p)
    ps_p.add_argument("--fail-on-unvalidated", action="store_true",
                      help="CI gate: exit 2, pokud existují unvalidované parserty")
    ps_p.set_defaults(func=cmd_parser_status)

    comp_p = _ex_sub(sub, "compliance",
                     help="F5.2 — SWGDE/ISO 27037 compliance report (JSON+PDF, Ed25519 podpis)")
    comp_p.add_argument("case_id")
    comp_p.add_argument("--out", metavar="DIR", default=None,
                        help="výstupní adresář (default: složka case DB)")
    _add_json_flag(comp_p)
    comp_p.set_defaults(func=cmd_compliance)

    daubert_p = _ex_sub(
        sub, "daubert",
        help="F5.5 — Daubert challenge preparedness pack (1-click JSON pro soud)",
    )
    daubert_p.add_argument("case_id")
    daubert_p.add_argument("--out", metavar="DIR", default=None,
                           help="výstupní adresář (default: složka case DB)")
    _add_json_flag(daubert_p)
    daubert_p.set_defaults(func=cmd_daubert)

    attack_map_p = _ex_sub(
        sub, "attack-map",
        help="F6.3 — MITRE ATT&CK mapping: heat-mapa taktik×technik + STIX intrusion-set",
    )
    attack_map_p.add_argument("case_id")
    attack_map_p.add_argument("--format", choices=["json", "stix"], default="json",
                              help="json = heat-mapa (default); stix = intrusion-set bundle")
    attack_map_p.add_argument("--out", metavar="FILE", default=None,
                              help="výstupní soubor (default: stdout)")
    _add_json_flag(attack_map_p)
    attack_map_p.set_defaults(func=cmd_attack_map)

    # F6.4 — Plugin ecosystem
    plg_p = sub.add_parser("plugin", help="F6.4 — plugin ecosystem (list/info/verify/run)")
    plg_sub = plg_p.add_subparsers(dest="plugin_cmd", required=True, metavar="<podprikaz>")
    plg_list = plg_sub.add_parser("list", help="seznam detekovaných pluginů")
    _add_json_flag(plg_list)
    plg_list.set_defaults(func=cmd_plugin_list)
    plg_info = plg_sub.add_parser("info", help="detail jednoho pluginu")
    plg_info.add_argument("name")
    _add_json_flag(plg_info)
    plg_info.set_defaults(func=cmd_plugin_info)
    plg_verify = plg_sub.add_parser(
        "verify", help="správa allowlistu ověřených pluginů (settings.json plugins_verified)"
    )
    plg_verify.add_argument("name")
    _plg_vgroup = plg_verify.add_mutually_exclusive_group(required=True)
    _plg_vgroup.add_argument("--add", action="store_true", help="přidat do allowlistu (in-process)")
    _plg_vgroup.add_argument("--remove", action="store_true", help="odebrat ze allowlistu (sandbox)")
    plg_verify.set_defaults(func=cmd_plugin_verify)
    plg_run = plg_sub.add_parser("run", help="běh kapacity pluginu (neověřený → sandbox)")
    plg_run.add_argument("name")

    def _plg_cap_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--cap", choices=["extractor", "triage_profile", "ai_tool"], required=True,
                       help="kapacita k běhu")
        p.add_argument("--key", default=None, help="klíč extractoru (pro --cap extractor)")
        p.add_argument("--file", dest="files", action="append", default=[], metavar="FILE",
                       help="soubor pro extractor (zopakovatelné; pro --cap extractor)")
        p.add_argument("--tool", default=None, help="jméno AI toolu (pro --cap ai_tool)")
        p.add_argument("--case-id", dest="case_id", default=None,
                       help="case ID (vyžadováno pro --cap ai_tool)")
        p.add_argument("--params", default="{}", help="JSON parametry AI toolu")

    _plg_cap_args(plg_run)
    _add_json_flag(plg_run)
    plg_run.set_defaults(func=cmd_plugin_run)

    # skrytý interní entry point pro sandbox subprocess (přímý běh, JSON stdout)
    prun_p = sub.add_parser("plugin-run", help=argparse.SUPPRESS)
    prun_p.add_argument("name")
    _plg_cap_args(prun_p)
    prun_p.set_defaults(func=cmd_plugin_run_entry)

    rp_p = _ex_sub(sub, "reparse",
                   help="F5.3 — re-run extrakce s deklarovánou verzí parseru + diff report")
    rp_p.add_argument("case_id")
    rp_p.add_argument("--source-id", default=None, metavar="ID",
                      help="zdroj (default: zdroj nejnovější extract operace)")
    rp_p.add_argument("--parser-version", required=True, metavar="V",
                      help="prokládaná verze parserové sady (pinned provenience)")
    rp_p.add_argument("--workdir", default=None, metavar="DIR",
                      help="umístění dočasné reparse DB (default: systémový tmp)")
    _add_json_flag(rp_p)
    rp_p.set_defaults(func=cmd_reparse)

    # F5.4 — write-blocker integration API (status/attach/remove + ingest gate)
    wb_p = _ex_sub(sub, "wb", help="F5.4 — write-blocker: status/attach/remove")
    wb_sub = wb_p.add_subparsers(dest="wb_cmd", required=True)
    wbs_p = wb_sub.add_parser(
        "status", help="aktuální WB stav + rozhodnutí brány (exit 2 = blokováno)"
    )
    wbs_p.add_argument("case_id")
    _add_json_flag(wbs_p)
    wbs_p.set_defaults(func=cmd_wb_status)
    wba_p = wb_sub.add_parser(
        "attach", help="zaznamenat připojení WB (auto-detekce vendoru z --device)"
    )
    wba_p.add_argument("case_id")
    wba_p.add_argument("--device", default=None, metavar="DEV",
                       help="zařízení/product string (např. 'Tableau TBW-100')")
    wba_p.add_argument("--vendor", default=None, choices=known_vendor_ids(),
                       help="explicitní vendor (když auto-detekce nestačí)")
    wba_p.add_argument("--product", default=None, metavar="P",
                       help="model WB (volitelné)")
    wba_p.add_argument("--notes", default=None, metavar="N",
                       help="volný text poznámky")
    _add_json_flag(wba_p)
    wba_p.set_defaults(func=cmd_wb_attach)
    wbm_p = wb_sub.add_parser("remove", help="zaznamenat odebrání WB")
    wbm_p.add_argument("case_id")
    wbm_p.add_argument("--reason", default=None, metavar="R",
                       help="důvod odebrání (volitelné)")
    _add_json_flag(wbm_p)
    wbm_p.set_defaults(func=cmd_wb_remove)

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

    an_p = _ex_sub(sub, "analytics", help="F2.2 — DuckDB OLAP analytics nad timeline (agregace, histogram)")
    an_p.add_argument("case_id")
    an_p.add_argument("--from-ts", dest="from_ts", metavar="ISO", help="začátek okna (UTC ISO 8601)")
    an_p.add_argument("--to-ts", dest="to_ts", metavar="ISO", help="konec okna (UTC ISO 8601)")
    an_p.add_argument("--type", dest="type", help="filtr podle typu události")
    an_p.add_argument("--limit", type=int, default=100)
    an_p.add_argument(
        "--dedupe", action="store_true",
        help="F2.3 — CDC bloky souborových zdrojů + úspora deduplikace (block_hashes)",
    )
    _add_json_flag(an_p)
    an_p.set_defaults(func=cmd_analytics)

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

    mob_p = _ex_sub(sub, "import-mobile", help="F1.5 — Import mobilní extrakce (Cellebrite UFDR / MSAB VCF / ADB logical dump)")
    mob_p.add_argument("case_id", help="ID případu")
    mob_p.add_argument("dump", help="cesta k .ufd/.zip/složce s exportem")
    mob_p.add_argument("--source", choices=["cellebrite", "msab", "adb"], default="cellebrite",
                       help="typ zdroje (default: cellebrite)")
    _add_json_flag(mob_p)
    mob_p.set_defaults(func=cmd_import_mobile)

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
    exp_p.add_argument("--format", choices=["csv", "json", "jsonl", "xml", "stix", "l2tcsv", "timesketch", "uco"], default="csv",
                       help="výstupní formát (default: csv; STP-023: jsonl/xml/stix; STP-054: l2tcsv; F6.1: timesketch; STP-055: uco)")
    exp_p.add_argument("--limit", type=int, default=None,
                       help="max. počet záznamů (artifacts/timeline; default: vše)")
    exp_p.add_argument("--out", metavar="SOUBOR",
                       help="výstupní soubor (default: stdout)")
    exp_p.add_argument("--bundle", action="store_true",
                       help="STP-068 — ZIP bundle všech datasetů (manifest + SHA-256, deterministický)")
    exp_p.add_argument("--validate-stix", action="store_true", dest="validate_stix",
                       help="F6.2 — validovat STIX bundle stix2-validator (extras [stix]; "
                            "bez nainstalovaného stix2 se export nepropadá jen upozorní)")
    exp_p.set_defaults(func=cmd_export)

    oc_p = _ex_sub(sub, "onchain",
                   help="K3 On-chain analýza — clustering + graf transakcí + risk scoring (offline-first)")
    oc_p.add_argument("case_id")
    oc_p.add_argument("--api-key", default=None, metavar="KEY",
                      help="Blockchair API key — volitelná síť pro BTC (bez klíče jen cache + listy)")
    oc_p.add_argument("--etherscan-key", default=None, metavar="KEY",
                      help="Etherscan API key — volitelná síť pro ETH")
    oc_p.add_argument("--no-network", action="store_true",
                      help="použít jen cache + bundlované listy (ignorovat API klíče)")
    oc_p.add_argument("--depth", type=int, default=3,
                      help="hloubka expanze cest z high-risk adres v grafu (default: 3)")
    _add_json_flag(oc_p)
    oc_p.set_defaults(func=cmd_onchain)

    dw_p = _ex_sub(sub, "darkweb",
                   help="K4 Dark Web & Illicit Activity — ransom note + marketplace + mixer detektory")
    dw_p.add_argument("case_id")
    dw_p.add_argument("--file", action="append", default=None, metavar="SOUBOR",
                      help="skenovat konkrétní soubor (může být opakováno; default: textové zdroje případu)")
    _add_json_flag(dw_p)
    dw_p.set_defaults(func=cmd_darkweb)

    crp = _ex_sub(sub, "crypto-report",
                  help="K4.5 — SWGDE krypto report (10 sekcí; md|html|json + Ed25519 podpis)")
    crp.add_argument("case_id")
    crp.add_argument("--format", choices=["md", "html", "json"], default="md",
                     help="výstupní formát (default: md)")
    crp.add_argument("--out", metavar="SOUBOR",
                     help="výstupní soubor (default: <db_dir>/reports/<case>.crypto_report.<fmt>)")
    _add_json_flag(crp)
    crp.set_defaults(func=cmd_crypto_report)

    adv_p = _ex_sub(sub, "advanced",
                    help="K5 Advanced — DeFi + NFT + cross-chain bridge + privacy coins (+ AI copilot)")
    adv_p.add_argument("case_id")
    adv_p.add_argument("--file", action="append", default=None, metavar="SOUBOR",
                       help="skenovat konkrétní soubor (může být opakováno; default: textové zdroje případu)")
    _add_json_flag(adv_p)
    adv_p.set_defaults(func=cmd_advanced)

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
