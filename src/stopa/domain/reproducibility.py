"""STOPA — Reproducibility Engine (P0 Core, C5).

Každá analytická operace se zaznamená se vším potřebným k opakování a
porovnání výsledků: vstupní soubory + hashe, verze parserů, verze STOPA,
hash konfigurace, souhrn výstupů, čas zpracování a prostředí.

Čistá logika (modely + deterministické porovnání) bez I/O; tenká IO vrstva
(``record_operation`` / ``list_operations``) žije v CaseDB, orchestrace
replaye (``replay_extract``) v pipeline.py — stejný vzor jako C2/C4.
"""

from __future__ import annotations

import platform
import sqlite3
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def new_operation_id() -> str:
    """Deterministicky čitelné ID s prefixem (forenzní stopa v logech)."""
    return f"op-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class AnalysisOperation:
    """Neměnný záznam analytické operace (append-only).

    ``input_files`` — vstupní soubory se SHA-256 hashi (replay ověří, že se
    zpracovává totéž). ``outputs_json`` — deterministický souhrn výsledku pro
    porovnání při replay (files_total, artifacts_extracted, artifact_types…).
    """

    op_type: str  # extract | correlate | …
    case_id: str | None = None
    source_id: str | None = None
    input_files: tuple[dict[str, str | None], ...] = ()
    parser_versions: dict[str, str] = field(default_factory=dict)
    stopa_version: str | None = None
    config_hash: str | None = None  # SHA-256 normalizované konfigurace (profil + parametry)
    params_json: dict = field(default_factory=dict)  # parametry operace (replay: profil, …)
    outputs_json: dict = field(default_factory=dict)
    duration_ms: int | None = None
    env_json: dict = field(default_factory=dict)
    id: str = field(default_factory=new_operation_id)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class ComparisonReport:
    """Výsledek porovnání původního a nového (replay) výsledku operace."""

    identical: bool
    diffs: tuple[str, ...] = ()  # lidsky čitelné rozdíly ("klíč: stará → nová")


@dataclass(frozen=True)
class ReplayResult:
    """Výsledek replaye operace — vstupní ověření + porovnání výstupů.

    ``inputs_identical`` — vstupní soubory se neproměnily (SHA-256).
    ``outputs_identical`` — opakovaný běh dal stejný souhrn výsledků.
    """

    op_id: str
    inputs_identical: bool
    input_diffs: tuple[str, ...] = ()  # "rel_path: stará → nová" (None = chybí)
    outputs_identical: bool = False
    output_diffs: tuple[str, ...] = ()
    duration_ms: int | None = None


def verify_inputs(
    recorded: list[dict], current: dict[str, str | None]
) -> tuple[bool, tuple[str, ...]]:
    """Ověří, že vstupní soubory se neproměnily (rel_path → SHA-256).

    ``recorded`` — záznam operace (list of {rel_path, sha256}); ``current`` —
    aktuální hashe na disku. Chybějící soubor = None ≠ hash → rozdíl.
    """
    rec_map = {f["rel_path"]: f.get("sha256") for f in recorded}
    diffs: list[str] = []
    for path in sorted(set(rec_map) | set(current)):
        old_h = rec_map.get(path)
        new_h = current.get(path)
        if old_h != new_h:
            diffs.append(f"{path}: {old_h!r} → {new_h!r}")
    return (not diffs, tuple(diffs))


def env_snapshot() -> dict:
    """Snapshot prostředí pro reprodukovatelnost (Python / SQLite / platforma)."""
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "sqlite": sqlite3.sqlite_version,
    }


def compare_outputs(original: dict, new: dict) -> ComparisonReport:
    """Deterministické porovnání dvou souhrnů výsledků.

    Porovná se každý klíč přítomný v kterémkoli ze souhrnů; chybějící klíč =
    rozdíl (None ≠ 0). Vrací lidsky čitelný seznam rozdílu — prázdný = identické.
    """
    diffs: list[str] = []
    for key in sorted(set(original) | set(new)):
        old_v = original.get(key)
        new_v = new.get(key)
        if old_v != new_v:
            diffs.append(f"{key}: {old_v!r} → {new_v!r}")
    return ComparisonReport(identical=not diffs, diffs=tuple(diffs))
