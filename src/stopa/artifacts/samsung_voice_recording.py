"""ETAPA B vlna 5 — Samsung Voice Recording parser (legacy mobile).

AXIOM ekvivalent: ``SamsungVoiceRecordingArtifact``
(``Magnet.Artifacts.LegacyMobile.Samsung.SamsungVoiceRecordingArtifact``).

Zdroj: SQLite DB aplikace **Samsung Voice Recorder**
(``com.sec.android.app.voicerec``) — ``voice_recorder.db`` /
``voicerecorder.db`` v ``/data/data/com.sec.android.app.voicerec/databases/``.

Formát (defenzivní, verze Androidu se liší): tabulka s názvem typu
``voicerec`` / ``voice_recorder`` / ``recordings`` a sloupcemi:
- ``name`` / ``title`` — název nahrávky
- ``path`` / ``file_path`` — cesta k audio souboru (.m4a/.mp3)
- ``duration`` — délka v **milisekundách** (některé verze: sekundy)
- ``date`` / ``time`` / ``created_at`` — epoch **ms** (Android konvence)

Detekce: schéma-based přes SQLite connection (pattern jako iOS voicemail).
Čistá funkce ``build_voice_recording_artifacts()`` nad řádky; IO entrypoint
``extract_samsung_voice_recording_artifacts(conn)``.

Artifact type: ``voice_recording`` — propojí se do audio view; details.engine
rozlišuje Samsung od iOS voicemailu.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

# Kandidátní tabulky (přesný název se liší verzí)
_CANDIDATE_TABLES = ("voicerec", "voice_recorder", "recordings", "recording")

# Minimální sloupce pro detekci (specifická kombinace)
_REQUIRED_COLS = {"name"}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {r[1].lower() for r in rows}


def _find_recording_table(conn: sqlite3.Connection) -> str | None:
    """Najdi tabulku s nahrávkami (první kandidát se sloupcem name)."""
    tables = {
        r[0].lower(): r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for candidate in _CANDIDATE_TABLES:
        real = tables.get(candidate)
        if real is None:
            continue
        cols = _table_columns(conn, real)
        if _REQUIRED_COLS <= cols:
            return real
    # fallback: libovolná tabulka s name + duration/path sloupci
    for lower_name, real in tables.items():
        if lower_name.startswith("sqlite_"):
            continue
        cols = _table_columns(conn, real)
        if {"name", "duration"} <= cols or {"name", "path"} <= cols:
            return real
    return None


def is_samsung_voice_recording_database(conn: sqlite3.Connection) -> bool:
    """Detekce Samsung voice recorder DB podle schématu."""
    return _find_recording_table(conn) is not None


def _pick(d: dict[str, Any], *keys: str) -> Any:
    """První existující klíč z d (lowercase)."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _duration_to_seconds(value: Any) -> int | None:
    """Délka v ms nebo s → sekundy (heuristika: >10_000 = ms)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(str(value).strip())
    except ValueError:
        return None
    if v <= 0:
        return None
    # Android konvence: milisekundy; >10_000 je jistě ms (ne s)
    seconds = v / 1000.0 if v > 10_000 else v
    return int(seconds)


def _timestamp_to_dt(value: Any):
    """Epoch ms/s → datetime (Android konvence: ms)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(str(value).strip())
    except ValueError:
        return None
    if v <= 0:
        return None
    # Android epocha = ms; >1e12 je jistě ms (ne s)
    seconds = v / 1000.0 if abs(v) > 1e12 else v
    try:
        return from_unix(seconds)
    except ValueError as e:
        logger.debug("voice_recording ts %r: %s", value, e)
        return None


def build_voice_recording_artifacts(rows: list[sqlite3.Row]) -> list[Artifact]:
    """ČISTÝ parser — řádky tabulky nahrávek → voice_recording artifacty."""
    artifacts: list[Artifact] = []
    for r in rows:
        d = {k.lower(): v for k, v in dict(r).items()}

        name = str(_pick(d, "name", "title") or "").strip()
        path = str(_pick(d, "path", "file_path", "filepath") or "").strip()
        if not name and not path:
            continue

        duration_s = _duration_to_seconds(_pick(d, "duration"))
        ts_raw = _pick(d, "date", "time", "created_at", "record_date")
        ts = _timestamp_to_dt(ts_raw)

        label = name or (path.rsplit("/", 1)[-1] if path else "(bez názvu)")
        title = f"Samsung voice recording: {label}"
        if duration_s is not None and duration_s > 0:
            minutes, secs = divmod(duration_s, 60)
            title += f" ({minutes}:{secs:02d})"

        details: dict[str, Any] = {"engine": "samsung_voice_recorder"}
        if name:
            details["name"] = name
        if path:
            details["path"] = path
        if duration_s is not None:
            details["duration_s"] = duration_s

        artifacts.append(
            Artifact(
                artifact_type="voice_recording",
                timestamp=ts,
                title=title[:200],
                details=details,
                confidence=0.8 if (name and ts is not None) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_samsung_voice_recording_artifacts(conn: sqlite3.Connection) -> list[Artifact]:
    """Pipeline entrypoint — Samsung voice recorder DB → voice_recording artifacty.

    Chyby (poškozená tabulka, chybějící sloupce) → log + prázdný výsledek,
    nikdy ne výjimka nahoru.
    """
    real = _find_recording_table(conn)
    if real is None:
        return []

    try:
        rows = conn.execute(f'SELECT * FROM "{real}" LIMIT 5000').fetchall()
    except sqlite3.Error as e:
        logger.warning("SamsungVoiceRecording select %s: %s", real, e)
        return []

    return build_voice_recording_artifacts(rows)
