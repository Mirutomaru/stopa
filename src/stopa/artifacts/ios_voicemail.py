"""ETAPA B vlna 4 — iOS Voicemail parser (voicemail.db).

AXIOM ekvivalent: ``VoiceMailArtifact`` (Magnet.Artifacts.dll) — hlasové
zprávy z iPhone voicemailu. Zdroj: tabulka ``voicemail`` v iOS
``HomeDomain-Library/Voicemail/voicemail.db``.

Formát (ověřený): sloupce ``date`` = unix epoch (s), ``trashed_date`` =
CFAbsoluteTime (s od 2001-01-01, 0 = nedělaná), ``sender``, ``callback_num``,
``duration`` (s), ``remote_uid``, ``flags``. Čistá funkce
``build_voicemail_artifacts()`` nad řádky; IO entrypoint
``extract_ios_voicemail_artifacts(conn)`` — schéma-based přes SQLite connection
(pattern jako Kik v sqlite_extract dispatch chainu).

Artifact type: ``voicemail`` (AXIOM VoiceMail).
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from stopa.domain.times import from_apple_absolute, from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

# Tabulka voicemail (iOS voicemail.db)
_VOICEMAIL_TABLE = "voicemail"

# Minimální sloupce pro detekci tabulky
_REQUIRED_COLS = {"date", "sender"}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {r[1].lower() for r in rows}


def is_ios_voicemail_database(conn: sqlite3.Connection) -> bool:
    """Detekce iOS voicemail.db podle schématu tabulky ``voicemail``."""
    tables = {
        r[0].lower(): r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    real = tables.get(_VOICEMAIL_TABLE.lower())
    if real is None:
        return False
    cols = _table_columns(conn, real)
    # 'voicemail' je obecný název — vyžadujeme date + sender (specifická kombinace)
    return _REQUIRED_COLS <= cols


def build_voicemail_artifacts(rows: list[sqlite3.Row]) -> list[Artifact]:
    """ČISTÝ parser — řádky tabulky voicemail → voicemail artifacty."""
    artifacts: list[Artifact] = []
    for r in rows:
        d = {k.lower(): v for k, v in dict(r).items()}

        date_raw = d.get("date")
        if not date_raw or int(date_raw) <= 0:
            continue
        try:
            ts = from_unix(int(date_raw))  # unix epoch (s)
        except ValueError as e:
            logger.debug("voicemail date %r: %s", date_raw, e)
            continue

        sender = str(d.get("sender") or "").strip()
        callback = str(d.get("callback_num") or "").strip()
        duration = d.get("duration")
        trashed_raw = d.get("trashed_date")

        # trashed_date = CFAbsoluteTime (0 = nedělaná)
        trashed_ts: Any = None
        if trashed_raw and int(trashed_raw) > 0:
            try:
                trashed_ts = from_apple_absolute(int(trashed_raw))
            except ValueError as e:
                logger.debug("voicemail trashed_date %r: %s", trashed_raw, e)

        title = f"Voicemail from {sender or '(unknown)'}"
        if duration is not None and int(duration) > 0:
            title += f" ({int(duration)} s)"

        details: dict[str, Any] = {
            "engine": "ios_voicemail",
            "duration_s": int(duration) if duration is not None else None,
            "trashed": trashed_ts is not None,
        }
        if callback:
            details["callback_num"] = callback
        if trashed_ts is not None:
            details["trashed_date"] = trashed_ts.isoformat()

        artifacts.append(
            Artifact(
                artifact_type="voicemail",
                timestamp=ts,
                title=title[:200],
                details=details,
                confidence=0.8 if sender else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_ios_voicemail_artifacts(conn: sqlite3.Connection) -> list[Artifact]:
    """Pipeline entrypoint — voicemail.db → voicemail artifacty.

    Chyby (poškozená tabulka, chybějící sloupce) → log + prázdný výsledek,
    nikdy ne výjimka nahoru.
    """
    tables = {
        r[0].lower(): r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    real = tables.get(_VOICEMAIL_TABLE.lower())
    if real is None:
        return []

    try:
        rows = conn.execute(
            f'SELECT * FROM "{real}" LIMIT 5000'
        ).fetchall()
    except sqlite3.Error as e:
        logger.warning("Voicemail select %s: %s", real, e)
        return []

    return build_voicemail_artifacts(rows)
