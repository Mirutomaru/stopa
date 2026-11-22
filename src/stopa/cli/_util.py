"""STOPA CLI — sdílené interní utilitní funkce (DB dir, settings.json, R0.4 výstup).

P1-4 (refaktor god-file ``cli.py``): přesunuto ze starého monolitického modulu
do oddělené vrstvy; chování je byte-přesně totožné s originálem. Importéři je
nadále používají přes re-export z facade ``stopa.cli`` (kompatibilitní povrch).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from stopa.data.db import CaseDB
from stopa.i18n import t  # P4-8 — katalogizace --json help textu

_log = logging.getLogger("stopa.cli")


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
        "--json", action="store_true", help=t("cli.opt.json.help")  # P4-8 i18n
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
