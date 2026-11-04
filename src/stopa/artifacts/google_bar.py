"""ETAPA B vlna 6 — Google Bar parser (Chrome/Edge address & search bar).

AXIOM ekvivalent: ``GoogleBarArtifact``
(``Magnet.Artifacts.GoogleBar.GoogleBarArtifact``).

Podporovaný formát: **Chrome / Chromium History SQLite DB** — tabulka
``search_terms``, která ukládá dotazy zadané do adresního/vyhledávacího
pole (omnibox). Každý unikátní term = jeden artifact s časem posledního
použití.

Sloupce ``search_terms``:
- ``term`` — text dotazu (NEURL, co uživatel napsal do lišty)
- ``time_last_used`` — Chrome epocha (µs od 1601-01-01) → konverze přes
  ``times.from_chrome_micros``
- ``weight`` / ``source`` — interní váha a zdroj (detaily, ne povinné)

Artifact type: ``browser_search`` — rozlišuje se od ``browser_history``
(visits = navštívené stránky; search = co uživatel hledal v liště).

Čistá logika bez IO (offline testovatelná); I/O jen v entrypointu.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from stopa.domain.times import from_chrome_micros
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_SEARCH_TERMS = 5_000  # obrana proti patologické DB

# tabulka musí mít aspoň tyto sloupce, ať je to reálná search_terms
_REQUIRED_COLS = {"term", "time_last_used"}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Sloupce tabulky (malá písmena); chybějící tabulka → prázdná množina."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()  # pevný název tabulky
    except sqlite3.Error:
        return set()
    return {r[1].lower() for r in rows}


def is_chrome_history_db(conn: sqlite3.Connection) -> bool:
    """Chrome/Edge History DB: tabulky ``visits`` + ``urls`` (+ volitelně search_terms)."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return "visits" in tables and "urls" in tables


def build_search_term_artifacts(rows: Iterable[Any]) -> list[Artifact]:
    """ČISTÁ funkce: z řádků ``search_terms`` vytvoří browser_search artifacty.

    Každý řádek = (term, time_last_used[, weight, source]). Term bez času
    → timestamp None (confidence nižší). Duplicitní term se deduplikuje
    (drží se poslední čas — DB je už seřazená podle relevance/času).
    """
    out: list[Artifact] = []
    seen: set[str] = set()
    for r in rows:
        try:
            d = dict(r) if not isinstance(r, dict) else r
            term = (d.get("term") or "").strip()
            if not term or term.lower() in ("", "null"):
                continue
            key = term.lower()
            raw_ts = d.get("time_last_used")
            ts: datetime | None = None
            try:
                if raw_ts is not None and int(raw_ts) > 0:
                    ts = from_chrome_micros(int(raw_ts))
            except (ValueError, TypeError):
                ts = None

            details: dict[str, Any] = {"engine": "chrome/edge", "source": "search_terms"}
            if d.get("weight") is not None:
                details["weight"] = int(d["weight"])
            if d.get("source") is not None:
                details["omnibox_source"] = int(d["source"])

            # deduplikace — první výskyt vyhrává (DB je seřazená)
            if key in seen:
                continue
            seen.add(key)

            out.append(
                Artifact(
                    artifact_type="browser_search",
                    timestamp=ts,
                    title=term[:500],
                    details=details,
                    confidence=0.8 if ts else 0.5,
                    parser_version=PARSER_VERSION,
                )
            )
        except Exception as e:  # noqa: BLE001 — jeden poškozený řádek nepotopí extrakci
            logger.debug("search_term row error: %s", e)
            continue
    return out[:MAX_SEARCH_TERMS]


def extract_search_terms(conn: sqlite3.Connection) -> list[Artifact]:
    """Z otevřené Chrome History DB vyčte ``search_terms`` → browser_search artifacty.

    Volá se jako bonus uvnitř ``_extract_chrome_history`` (sdílené SQLite
    dispatch). Chybějící tabulka / sloupce → prázdný výsledek, ne výjimka.
    """
    if not is_chrome_history_db(conn):
        return []
    cols = _table_columns(conn, "search_terms")
    if not _REQUIRED_COLS.issubset(cols):
        return []
    try:
        rows = conn.execute(
            "SELECT term, time_last_used, weight, source FROM search_terms"
            " WHERE term IS NOT NULL AND length(term) > 0"
            " ORDER BY time_last_used DESC LIMIT ?",
            (MAX_SEARCH_TERMS,),
        ).fetchall()
    except sqlite3.Error as e:
        logger.debug("search_terms select error: %s", e)
        return []
    return build_search_term_artifacts(rows)


def extract_google_bar_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Chrome History DB → browser_search artifacty.

    Otevře DB read-only, vyčte search_terms a zavře spojení. Chyby (IO,
    poškozená DB) → log + prázdný výsledek, nikdy ne výjimka.
    """
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return extract_search_terms(conn)
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as e:
        logger.warning("GoogleBar %s: nelze číst (%s)", path, e)
        return []
