"""ETAPA B vlna 3 — Kik Messenger parser (SQLite, iOS + Android schémata).

AXIOM ekvivalent: ``KikLocalUserExtractor`` (``Magnet.Artifacts.Kik``) —
lokální uživatelé / kontakty Kik Messengeru. AXIOM Artifact Reference dále
popisuje „iOS Kik Messenger Users" (parsing) a „iOS Kik Messenger Messages"
(parsing + carving).

Podporovaná schémata:
- **iOS** ``kik.sqlite`` — tabulky s prefixem ``ZKIK*``::

    ZKIKUSER   (Z_PK, ZUSERNAME, ZDISPLAYNAME, ZEMAIL, ZFIRSTNAME,
                ZLASTNAME, ZIMAGEURL, ...)
    ZKIKMESSAGE(Z_PK, ZTEXT, ZSENDER, ZRECEIVER, ZTIMESTAMP, ...)

- **Android** — tabulky ``users`` / ``messages`` (sloupcové aliasy).

Detekce: **schéma-based** (přítomnost Kik tabulek) — volá se ze
``sqlite_extract`` dispatch chainu podle obsahu DB, ne podle názvu souboru.

Artifact types:
- uživatelé/kontakty → ``contact``
- zprávy            → ``messenger_message`` (propojí se do chat view)
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

from stopa.domain.times import detect_and_convert
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_USERS_PER_DB = 5_000
MAX_MESSAGES_PER_DB = 20_000

# iOS tabulky (prefix ZKIK) i Android aliasy — detekce schématu.
_KIK_USER_TABLES = ("ZKIKUSER", "users")
_KIK_MSG_TABLES = ("ZKIKMESSAGE", "messages")

# sloupcové aliasy → kanonické pole (defenzivní mapování, velká/malá písmena)
_USER_COL_ALIASES: dict[str, tuple[str, ...]] = {
    "user_id": ("Z_PK", "id", "_id", "userId"),
    "kik_id": ("ZUSERNAME", "username", "kikId", "handle"),
    "display_name": ("ZDISPLAYNAME", "displayName", "name"),
    "email": ("ZEMAIL", "email", "mail"),
    "first_name": ("ZFIRSTNAME", "firstName", "firstname"),
    "last_name": ("ZLASTNAME", "lastName", "lastname"),
    "image_url": ("ZIMAGEURL", "imageUrl", "profileImageUrl", "avatarUrl"),
}

_MSG_COL_ALIASES: dict[str, tuple[str, ...]] = {
    "text": ("ZTEXT", "text", "body", "message"),
    "sender_id": ("ZSENDER", "senderId", "fromUserId", "sender"),
    "receiver_id": ("ZRECEIVER", "receiverId", "toUserId", "receiver"),
    "timestamp": ("ZTIMESTAMP", "timestamp", "date", "created_at"),
}


@dataclass
class KikUser:
    """Jeden Kik uživatel / kontakt."""

    user_id: str = ""
    kik_id: str = ""
    display_name: str = ""
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    image_url: str = ""


@dataclass
class KikMessage:
    """Jedna Kik zpráva."""

    text: str = ""
    sender_id: str = ""
    receiver_id: str = ""
    timestamp_raw: Any = None


def _table_columns(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    """Vrátí {malé_jméno_sloupce: skutečné_jméno} pro tabulku."""
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {r[1].lower(): r[1] for r in rows}


def _pick(cols: dict[str, str], aliases: tuple[str, ...]) -> str | None:
    """Najde skutečný sloupec pro první existující alias (case-insensitive)."""
    for a in aliases:
        real = cols.get(a.lower())
        if real is not None:
            return real
    return None


def _find_table(conn: sqlite3.Connection, candidates: tuple[str, ...]) -> str | None:
    """Najde první existující tabulku z kandidátů (case-insensitive)."""
    tables = {r[0].lower(): r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    for c in candidates:
        real = tables.get(c.lower())
        if real is not None:
            return real
    return None


def is_kik_database(conn: sqlite3.Connection) -> bool:
    """Detekce Kik DB podle schématu.

    iOS ``kik.sqlite`` (tabulka ``ZKIKUSER``) stačí sama o sobě — prefix ZKIK
    je specifický. Android aliasy (``users``/``messages``) jsou obecné, proto
    vyžadujeme OBĚ tabulky, abychom neshodili jinou DB s ``users`` tabulkou.
    """
    user_tbl = _find_table(conn, _KIK_USER_TABLES)
    if user_tbl is None:
        return False
    cols = _table_columns(conn, user_tbl)
    # Kik DB musí mít identifikátor uživatele (username/kikId/id)
    if not any(_pick(cols, aliases) for aliases in _USER_COL_ALIASES.values()):
        return False
    # iOS ZKIK* je specifický — stačí. Android aliasy vyžadují i messages tabulku.
    if user_tbl.upper().startswith("ZKIK"):
        return True
    return _find_table(conn, _KIK_MSG_TABLES) is not None


def parse_kik_users(rows: list[sqlite3.Row]) -> list[KikUser]:
    """ČISTÝ parser — řádky ZKIKUSER → KikUser záznamy.

    Sloupce se mapují defenzivně (aliasy); chybějící pole = prázdný string.
    """
    users: list[KikUser] = []
    for r in rows:
        d = dict(r)
        low = {k.lower(): v for k, v in d.items()}

        def g(aliases: tuple[str, ...], _low: dict = low) -> str:
            for a in aliases:
                v = _low.get(a.lower())
                if v is not None and v != "":
                    return str(v)
            return ""

        users.append(
            KikUser(
                user_id=g(_USER_COL_ALIASES["user_id"]),
                kik_id=g(_USER_COL_ALIASES["kik_id"]),
                display_name=g(_USER_COL_ALIASES["display_name"]),
                email=g(_USER_COL_ALIASES["email"]),
                first_name=g(_USER_COL_ALIASES["first_name"]),
                last_name=g(_USER_COL_ALIASES["last_name"]),
                image_url=g(_USER_COL_ALIASES["image_url"]),
            )
        )
    return users


def parse_kik_messages(rows: list[sqlite3.Row]) -> list[KikMessage]:
    """ČISTÝ parser — řádky ZKIKMESSAGE → KikMessage záznamy."""
    msgs: list[KikMessage] = []
    for r in rows:
        d = dict(r)
        low = {k.lower(): v for k, v in d.items()}

        def g(aliases: tuple[str, ...], _low: dict = low) -> Any:
            for a in aliases:
                if a.lower() in _low and _low[a.lower()] is not None:
                    return _low[a.lower()]
            return None

        msgs.append(
            KikMessage(
                text=str(g(_MSG_COL_ALIASES["text"]) or ""),
                sender_id=str(g(_MSG_COL_ALIASES["sender_id"]) or ""),
                receiver_id=str(g(_MSG_COL_ALIASES["receiver_id"]) or ""),
                timestamp_raw=g(_MSG_COL_ALIASES["timestamp"]),
            )
        )
    return msgs


def _convert_ts(raw: Any) -> Any:
    """Defenzivní konverze Kik časového razítka (epoch s/ms/µs) → datetime."""
    if raw is None or isinstance(raw, str):
        return None
    try:
        return detect_and_convert(float(raw))
    except (ValueError, TypeError) as e:
        logger.debug("Kik ts %r: %s", raw, e)
        return None


def build_kik_artifacts(
    users: list[KikUser], messages: list[KikMessage]
) -> list[Artifact]:
    """ČISTÁ funkce: z Kik dat vytvoří artifacty (contact + messenger_message)."""
    artifacts: list[Artifact] = []

    # uživatelé → contact
    for u in users:
        name = u.display_name or u.kik_id or u.email or "(neznámý)"
        details: dict[str, Any] = {
            "engine": "kik_messenger",
            "user_id": u.user_id,
            "kik_id": u.kik_id,
            "display_name": u.display_name,
            "email": u.email,
            "first_name": u.first_name,
            "last_name": u.last_name,
        }
        if u.image_url:
            details["image_url"] = u.image_url
        artifacts.append(
            Artifact(
                artifact_type="contact",
                timestamp=None,  # snapshot kontaktů bez času
                title=f"Kik kontakt — {name}",
                details=details,
                confidence=0.8 if (u.kik_id or u.email) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )

    # zprávy → messenger_message
    for m in messages:
        ts = _convert_ts(m.timestamp_raw)
        text = m.text.strip()
        artifacts.append(
            Artifact(
                artifact_type="messenger_message",
                timestamp=ts,
                title=f"Kik {m.sender_id or '?'} → {m.receiver_id or '?'}: {text[:80]}",
                details={
                    "engine": "kik_messenger",
                    "sender_id": m.sender_id,
                    "receiver_id": m.receiver_id,
                    "text": text[:500],
                },
                confidence=0.7 if text else 0.5,
                parser_version=PARSER_VERSION,
            )
        )

    return artifacts


def extract_kik_artifacts(conn: sqlite3.Connection) -> list[Artifact]:
    """Pipeline entrypoint — Kik SQLite DB → contact + messenger_message artifacty.

    Chyby (poškozená tabulka, chybějící sloupce) → log + prázdný výsledek,
    nikdy ne výjimka nahoru.
    """
    user_tbl = _find_table(conn, _KIK_USER_TABLES)
    msg_tbl = _find_table(conn, _KIK_MSG_TABLES)

    users: list[KikUser] = []
    messages: list[KikMessage] = []

    if user_tbl is not None:
        try:
            rows = conn.execute(
                f'SELECT * FROM "{user_tbl}" LIMIT {MAX_USERS_PER_DB}'
            ).fetchall()
            users = parse_kik_users(rows)
        except sqlite3.Error as e:
            logger.warning("Kik users %s: %s", user_tbl, e)

    if msg_tbl is not None:
        try:
            rows = conn.execute(
                f'SELECT * FROM "{msg_tbl}" LIMIT {MAX_MESSAGES_PER_DB}'
            ).fetchall()
            messages = parse_kik_messages(rows)
        except sqlite3.Error as e:
            logger.warning("Kik messages %s: %s", msg_tbl, e)

    if not users and not messages:
        return []
    return build_kik_artifacts(users, messages)
