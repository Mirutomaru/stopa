"""ETAPA B vlna 4 — DuckDuckGo Cookies parser (SQLite, Chromium schéma).

AXIOM ekvivalent: ``DuckDuckGoCookiesArtifact``
(``Magnet.Artifacts.dll``) — cookies DuckDuckGo prohlížeče. DDG browser je
Chromium-based → sdílí standardní cookie schéma::

    cookies (host_key, name, value, encrypted_value, path, expires_utc,
             last_access_utc, has_expires, is_persistent, is_secure, is_httponly)

Časová razítka = **µs od Windows epochy (1601)** — konverze přes
``times.from_chrome_micros``. Hodnota cookie bývá šifrovaná
(``encrypted_value``, Chromium v10+ AES-GCM) → plaintext ``value`` se
eviduje jen když je neprázdný; šifrovanou hodnotu neinterpretujeme.

Detekce: **schéma-based** (tabulka ``cookies`` s ``host_key`` + ``name``) —
volá se ze ``sqlite_extract`` dispatch chainu podle obsahu DB, ne podle
názvu souboru (pattern jako Kik).

Artifact type: ``browser_cookie`` — jeden cookie = jeden artifact.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

from stopa.domain.times import from_chrome_micros
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_COOKIES_PER_DB = 20_000


@dataclass
class Cookie:
    """Jeden cookie z Chromium schématu."""

    host_key: str = ""
    name: str = ""
    value: str = ""  # plaintext (prázdný když je jen encrypted_value)
    path: str = "/"
    expires_utc_raw: Any = None  # µs od 1601
    last_access_utc_raw: Any = None  # µs od 1601
    is_secure: bool = False
    is_httponly: bool = False


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {r[1] for r in rows}


def is_cookies_database(conn: sqlite3.Connection) -> bool:
    """Detekce Chromium cookie DB podle schématu.

    Tabulka ``cookies`` s ``host_key`` + ``name`` (+ ``value`` nebo
    ``encrypted_value``). Konkrétní sloupce vylučují obecné DB s náhodnou
    tabulkou ``cookies`` bez cookie polí.
    """
    tables = {r[0].lower() for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    if "cookies" not in tables:
        return False
    cols = _table_columns(conn, "cookies")
    if not {"host_key", "name"} <= cols:
        return False
    return bool({"value", "encrypted_value"} & cols)


def parse_cookies(rows: list[sqlite3.Row]) -> list[Cookie]:
    """ČISTÝ parser — řádky tabulky ``cookies`` → Cookie záznamy.

    Sloupce se mapují defenzivně; chybějící pole = defaultní hodnoty.
    """
    cookies: list[Cookie] = []
    for r in rows:
        d = {k.lower(): v for k, v in dict(r).items()}
        host_key = str(d.get("host_key") or "").strip()
        name = str(d.get("name") or "").strip()
        if not host_key or not name:
            continue
        value_raw = d.get("value")
        cookies.append(
            Cookie(
                host_key=host_key,
                name=name,
                value=str(value_raw) if value_raw is not None else "",
                path=str(d.get("path") or "/"),
                expires_utc_raw=d.get("expires_utc"),
                last_access_utc_raw=d.get("last_access_utc"),
                is_secure=bool(int(d.get("is_secure") or 0)),
                is_httponly=bool(int(d.get("is_httponly") or 0)),
            )
        )
    return cookies


def _convert_chrome_ts(raw: Any) -> Any:
    """Defenzivní konverze Chromium timestampu (µs od 1601) → datetime."""
    if raw is None:
        return None
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    try:
        return from_chrome_micros(v)
    except ValueError as e:
        logger.debug("cookie ts %r: %s", raw, e)
        return None


def build_cookie_artifacts(cookies: list[Cookie]) -> list[Artifact]:
    """ČISTÁ funkce: z cookie vytvoří artifacty (browser_cookie)."""
    artifacts: list[Artifact] = []
    for c in cookies:
        ts = _convert_chrome_ts(c.last_access_utc_raw) or _convert_chrome_ts(
            c.expires_utc_raw
        )
        details: dict[str, Any] = {
            "engine": "ddg_cookies",
            "host_key": c.host_key,
            "name": c.name,
            "path": c.path,
            "is_secure": c.is_secure,
            "is_httponly": c.is_httponly,
        }
        if c.value:
            details["value"] = c.value[:500]  # plaintext jen když existuje
        else:
            details["encrypted_only"] = True
        artifacts.append(
            Artifact(
                artifact_type="browser_cookie",
                timestamp=ts,
                title=f"Cookie {c.name} @ {c.host_key}",
                details=details,
                confidence=0.8 if ts else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_ddg_cookie_artifacts(conn: sqlite3.Connection) -> list[Artifact]:
    """Pipeline entrypoint — Chromium cookie DB → browser_cookie artifacty.

    Chyby (poškozená tabulka, chybějící sloupce) → log + prázdný výsledek,
    nikdy ne výjimka nahoru.
    """
    try:
        rows = conn.execute(
            "SELECT host_key, name, value, path, expires_utc, last_access_utc,"
            f" is_secure, is_httponly FROM cookies LIMIT {MAX_COOKIES_PER_DB}"
        ).fetchall()
    except sqlite3.Error as e:
        logger.warning("DDG cookies select: %s", e)
        return []

    cookies = parse_cookies(rows)
    if not cookies:
        return []
    return build_cookie_artifacts(cookies)
