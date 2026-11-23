"""ETAPA B vlna 14 — WhatsApp Cloud parser (cloud export / warrant return).

AXIOM ekvivalenty: ``CloudWhatsAppChatsArtifact`` + ``CloudWhatsAppBackupArtifact``
(``Magnet.Artifacts.Cloud.WhatsApp.*``) — konverzační zprávy a backup metadata
z WhatsApp cloud exportů.

Podporované formáty (defenzivní parsing, auto-detekce podtypu)::

    1. Chats::

        [{"chatName": "+420...", "messages": [
            {"sender": "Jan", "text": "Ahoj", "timestamp": 1728136800}, ...]}, ...]

        nebo plochý seznam zpráv s ``chatId``:

        [{"chatId": "...", "sender": "Jan", "text": "Ahoj",
          "timestamp": 1728136800, "type": "text"}, ...]

    2. Backup::

        [{"backupDate": "2025-01-15T09:00:00Z", "version": "2.24.10",
          "sizeBytes": 1048576, "encrypted": true}, ...]

Jeden záznam = jeden artifact (podtyp → konkrétní ``artifact_type``:
chat_message / file_metadata). Neznámá pole se ignorují.

Detekce: **name-based** — whatsapp marker + klíčová slova; v dispatchi pre-pass
na celé cestě PŘED basename chainem (generic basenames kolidují s ostatními
detektory).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_ITEMS_PER_FILE = 5_000


@dataclass
class WhatsAppRecord:
    """Jeden WhatsApp cloud záznam (podtyp + normalizovaná data)."""

    kind: str = ""  # chat | backup
    name: str | None = None
    sender: str | None = None
    text: str | None = None
    message_type: str | None = None
    created_s: float | None = None
    version: str | None = None
    size_bytes: int | None = None
    encrypted: bool | None = None


def _to_str(value: Any) -> str | None:
    """Tolerantní konverze na non-empty string."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_str(*values: Any) -> str | None:
    """První non-empty string z řetězce kandidátů."""
    for v in values:
        s = _to_str(v)
        if s:
            return s
    return None


def _to_int(value: Any) -> int | None:
    """Tolerantní konverze na nezáporné celé číslo."""
    try:
        num = int(float(value))
    except (ValueError, TypeError):
        return None
    return num if num >= 0 else None


def _to_bool(value: Any) -> bool | None:
    """Tolerantní konverze na bool."""
    if isinstance(value, bool):
        return value
    text = _to_str(value)
    if text is None:
        return None
    low = text.lower()
    if low in ("true", "1", "yes"):
        return True
    if low in ("false", "0", "no"):
        return False
    return None


def _to_epoch(value: Any) -> float | None:
    """Tolerantní konverze času na epoch sekundy.

    Podporuje: int/float (sekundy i milisekundy), ISO 8601 stringy
    (s ``Z`` i offsetem). Neznámé tvary → None.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (ValueError, TypeError):
        text = _to_str(value)
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return float(dt.timestamp())
    # milisekundy — heuristika: epoch > 1e12 už jsou ms (rok ~33658)
    if abs(num) >= 10**12:
        num /= 1000.0
    return num if num > 0 else None


def _detect_kind(name: str, item: dict[str, Any]) -> str:
    """Určí WhatsApp podtyp podle cesty/názvu + tvaru položky."""
    lower = name.lower()
    # explicitní hint z cesty
    for marker, kind in (
        ("backup", "backup"),
        ("chat", "chat"),
        ("message", "chat"),
    ):
        if marker in lower:
            return kind
    # fallback podle klíčů
    if any(k in item for k in ("sender", "text")):
        return "chat"
    if any(k in item for k in ("backupDate", "version", "sizeBytes")):
        return "backup"
    return ""


def parse_whatsapp_cloud(data: bytes, kind_hint: str = "") -> list[WhatsAppRecord]:
    """ČISTÝ parser — WhatsApp cloud JSON → záznamy.

    Args:
        data: Obsah souboru (JSON).
        kind_hint: Volitelný hint podtypu z cesty; prázdně = auto-detekce.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez WhatsApp cloud záznamů.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[WhatsAppRecord] = []

    def add_chat(
        chat_name: str | None, item: dict[str, Any]
    ) -> None:
        sender = _first_str(item.get("sender"), item.get("from"))
        text = _to_str(item.get("text", item.get("body")))
        mtype = (_to_str(item.get("type")) or "").lower() or None
        ts = _to_epoch(
            item.get("timestamp", item.get("date", item.get("sentTimestamp")))
        )
        records.append(
            WhatsAppRecord(
                kind="chat",
                name=chat_name,
                sender=sender,
                text=text,
                message_type=mtype,
                created_s=ts,
            )
        )

    def add_backup(item: dict[str, Any]) -> None:
        version = _to_str(item.get("version"))
        size = _to_int(item.get("sizeBytes", item.get("size")))
        encrypted = _to_bool(item.get("encrypted"))
        records.append(
            WhatsAppRecord(
                kind="backup",
                name=f"WhatsApp backup {version or ''}".strip()[:120] or None,
                version=version,
                size_bytes=size,
                encrypted=encrypted,
                created_s=_to_epoch(item.get("backupDate", item.get("date"))),
            )
        )

    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("entries", "items", "chats", "messages", "backups"):
            val = payload.get(key)
            if isinstance(val, list):
                items.extend(x for x in val if isinstance(x, dict))
        # plochý objekt — jeden záznam
        if not items and any(
            k in payload
            for k in (
                "sender",
                "text",
                "backupDate",
                "version",
            )
        ):
            items = [payload]
    elif isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]

    hint_ok = kind_hint in ("chat", "backup")
    for item in items[:MAX_ITEMS_PER_FILE]:
        # konverzační forma: chatName + messages[]
        msgs = item.get("messages")
        if isinstance(msgs, list) and any(isinstance(m, dict) for m in msgs):
            chat_name = _to_str(item.get("chatName", item.get("chatId")))
            for msg in msgs:
                if isinstance(msg, dict):
                    add_chat(chat_name, msg)
            continue

        kind = (
            kind_hint
            if hint_ok
            else _detect_kind("", item)
        )
        if kind == "chat":
            chat_name = _to_str(item.get("chatName", item.get("chatId")))
            add_chat(chat_name, item)
        elif kind == "backup":
            add_backup(item)

    records = records[:MAX_ITEMS_PER_FILE]
    if not records:
        raise TypeError("Nenalezeny WhatsApp cloud záznamy")
    return records


def build_whatsapp_artifacts(records: list[WhatsAppRecord]) -> list[Artifact]:
    """ČISTÁ funkce: z WhatsApp cloud záznamů vytvoří artifacty."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "whatsapp_cloud", "kind": r.kind}

        ts = None
        if r.created_s is not None:
            try:
                ts = from_unix(r.created_s)
            except ValueError:
                ts = None

        if r.kind == "chat":
            title = f"WhatsApp zpráva: {r.name or '(bez chatu)'}"[:120]
            if r.sender:
                details["sender"] = r.sender
            if r.message_type:
                details["message_type"] = r.message_type
            if r.text:
                details["text"] = r.text[:500]
            artifacts.append(
                Artifact(
                    artifact_type="chat_message",
                    timestamp=ts,
                    title=title,
                    details=details,
                    confidence=0.85 if (r.name and ts) else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )

        elif r.kind == "backup":
            title = f"WhatsApp backup: {r.version or '(bez verze)'}"[:120]
            if r.size_bytes is not None:
                details["size_bytes"] = r.size_bytes
            if r.encrypted is not None:
                details["encrypted"] = r.encrypted
            artifacts.append(
                Artifact(
                    artifact_type="file_metadata",
                    timestamp=ts,
                    title=title,
                    details=details,
                    confidence=0.8 if ts else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )

    return artifacts


def extract_whatsapp_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — WhatsApp cloud JSON → artifacty (podtyp auto)."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("WhatsApp %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    # podtyp hint z cesty (detektor už marker ověřil)
    lower = str(path).lower()
    hint = ""
    for marker, kind in (
        ("backup", "backup"),
        ("chat", "chat"),
        ("message", "chat"),
    ):
        if marker in lower:
            hint = kind
            break

    try:
        records = parse_whatsapp_cloud(data, kind_hint=hint)
    except (ValueError, TypeError) as e:
        logger.debug("WhatsApp %s: %s", path.name, e)
        return []

    return build_whatsapp_artifacts(records)


def is_whatsapp_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce WhatsApp cloud exportu.

    Vyžaduje whatsapp marker v názvu/cestě — generic ``messages.json`` bez markery
    nepadne, aby se nekradly cizí soubory.
    """
    lower = name.lower()
    if "whatsapp" not in lower:
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
