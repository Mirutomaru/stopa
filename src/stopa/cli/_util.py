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


def _load_wb_gate_mode(profile_name: str = "forensic") -> str:
    """P0.4 — write-blocker gate režim ze settings.json (tenký wrapper).

    Režim rozliší :func:`stopa.domain.write_blocker.resolve_gate_mode`:
    explicitní ``wb_gate_mode`` > legacy bool ``require_write_blocker`` (F5.4,
    zachováno pro existující konfigurace) > výchozí podle profilu
    (forensic → fail_closed; ediscovery/quick → warn_only). Laboratorní
    warn_only si administrátor nastavuje explicitně a každá kontrola se
    eviduje jako výjimka v audit logu.
    """
    from stopa.domain.write_blocker import resolve_gate_mode  # lokální — bez cyklu

    return resolve_gate_mode(_load_settings_dict(), profile_name=profile_name)


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


# ---------------------------------------------------------------------------
# B7 — konzolidace CLI: skryté kompatibilitní aliasy pro seskupené příkazy
# ---------------------------------------------------------------------------

def register_alias(
    subparsers: argparse._SubParsersAction,
    alias_name: str,
    target: argparse.ArgumentParser,
) -> argparse.ArgumentParser:
    """B7 — skrytý BC alias (help=SUPPRESS) na seskupený kanonický příkaz.

    Klonuje argumentový povrch ``target`` do nového top-level subpříkazu se
    stejnym dispatchem (func + defaults), takže stará volání dál fungují;
    DeprecationWarning emituje :func:`stopa.cli.main` při dispatchi.
    """
    p = subparsers.add_parser(alias_name, help=argparse.SUPPRESS)
    # BC povrch helpu: příklad v epilogu (R0.4) + formatter musí být identické,
    # jinak `staré-jméno --help` ztratí sekci „Příklad:" (viz test_f12 E2E).
    if target.epilog is not None:
        p.formatter_class = target.formatter_class
        p.epilog = target.epilog
    if getattr(target, "description", None) is not None:
        p.description = target.description
    for action in target._actions:
        _clone_action(p, action)
    # func + vlastní defaults → identický dispatch jako kanonická cesta
    target_defaults = dict(getattr(target, "_defaults", {}) or {})  # argparse interní stav (veřejné .defaults neexistuje)
    if target_defaults:
        p.set_defaults(**target_defaults)
    return p


def _clone_action(dst: argparse.ArgumentParser, a: argparse.Action) -> None:
    """Klonuje jednu akci do ``dst``; neznámý typ hází (žádný tichý drift)."""
    kind = type(a).__name__
    if kind == "_HelpAction":
        return  # -h/--help si argparse přidá ke každému parseru automaticky
    common = {
        "const": a.const,
        "default": a.default,
        "type": a.type,
        "choices": a.choices,
        "help": a.help,
        "metavar": a.metavar,
    }
    if kind == "_PositionalAction" or (kind == "_StoreAction" and not a.option_strings):
        # positionál — dest se odvozuje ze jména (case_id → case_id; pojmenování neměníme).
        # Pozn.: v Pythonu 3.11 jsou positionály _StoreAction s prázdným option_strings,
        # _PositionalAction zůstává jako obrana pro ostatní verze.
        dst.add_argument(a.dest, nargs=a.nargs, **common)
        return
    if kind in ("_StoreTrueAction", "_StoreFalseAction"):
        # store_true/false nesnáší type/choices — obranná kontrola
        if a.type is not None or a.choices:
            raise NotImplementedError(f"B7 alias: neočekávaná akce {kind} s type/choices")
        action = "store_true" if kind == "_StoreTrueAction" else "store_false"
        dst.add_argument(
            *a.option_strings, dest=a.dest, action=action, default=a.default, help=a.help
        )
        return
    if kind == "_AppendAction":
        if a.type is not None or a.choices:
            raise NotImplementedError(f"B7 alias: neočekávaná akce {kind} s type/choices")
        dst.add_argument(
            *a.option_strings, dest=a.dest, action="append",
            default=a.default, help=a.help, metavar=a.metavar,
        )
        return
    if kind == "_CountAction":
        dst.add_argument(
            *a.option_strings, dest=a.dest, action="count", default=a.default, help=a.help
        )
        return
    if kind == "_StoreAction":
        dst.add_argument(
            *a.option_strings, dest=a.dest, action="store",
            nargs=a.nargs, required=a.required, **common,
        )
        return
    raise NotImplementedError(f"B7 alias: nepodporovaná argparse akce {kind}")


# B7 — deprecated top-level jména → nová poloha (konzolidační skupiny)
DEPRECATED_ALIASES: dict[str, str] = {
    "seal": "integrity seal",
    "seal-chain": "integrity chain",
    "integrity-keys": "integrity keys",
    "rotate-key": "integrity rotate-key",
    "import-mobile": "import mobile",
    "plaso-import": "import plaso",
    "image": "forensic image",
    "mobile": "forensic mobile",
    "memory-analyze": "forensic memory",
    "pcap-analyze": "forensic pcap",
    "decrypt": "forensic decrypt",
    "antiforensics-scan": "forensic anti",
    "onchain": "crypto onchain",
    "darkweb": "crypto darkweb",
    "crypto-report": "crypto report",
    "advanced": "crypto advanced",
    "compliance": "court swgde",
    "daubert": "court daubert",
}

# B7 — legacy forma `stopa integrity <case_id>` → podakce check (integrity = skupina)
INTEGRITY_SUBCOMMANDS: frozenset[str] = frozenset(
    {"check", "seal", "chain", "keys", "rotate-key"}
)


def rewrite_legacy_integrity(argv: list[str]) -> tuple[list[str], bool]:
    """B7 — BC přepis legacy formy ``stopa integrity <case_id>``.

    Vrací ``(argv, byl_přepsán)``. Přepíše jen tehdy, když druhý token není
    nová podakce ani -h/--help (ty obsluhuje help skupiny).
    """
    if (
        len(argv) >= 2
        and argv[0] == "integrity"
        and argv[1] not in INTEGRITY_SUBCOMMANDS
        and argv[1] not in ("-h", "--help")
    ):
        return ["integrity", "check", *argv[1:]], True
    return argv, False


def deprecation_warning_for(command: str | None, legacy_integrity: bool) -> str | None:
    """B7 — text DeprecationWarning pro staré top-level jméno (None = nový tvar)."""
    if legacy_integrity:
        return (
            "stopa integrity <case_id> je deprecated — použij stopa integrity check <case_id> (B7)"
        )
    if command in DEPRECATED_ALIASES:
        return (
            f"stopa {command} je deprecated — použij stopa {DEPRECATED_ALIASES[command]} (B7)"
        )
    return None


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
