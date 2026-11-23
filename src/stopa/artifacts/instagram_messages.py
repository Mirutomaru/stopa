"""ETAPA B vlna 10 — Instagram Direct Messages parser (cloud export / warrant return).

AXIOM ekvivalenty: ``InstagramMessagesArtifact`` + ``CloudInstagramDirectMessagesArtifact``
+ ``CloudFacebookInstagramMessagesArtifact`` + ``InstagramDirectSharesArtifact``
(``Magnet.Artifacts.Cloud.*``) — konverzační zprávy a sdílený obsah z Instagramu.

Podporovaný formát: **JSON export konverzací** (Takeout / cloud export)::

    [{"id": "conv-1", "participants": ["user_a", "user_b"],
      "messages": [{"sender": "user_a", "text": "Ahoj!",
                    "timestamp": 1728000000, "type": "text"}]}]

   nebo ploché pole zpráv (warrant return)::

    [{"from": "user_a", "to": "user_b", "body": "Ahoj!", "time": "..."}]

Jedna zpráva = jeden artifact (``chat_message``, ``details.engine='instagram_messages'``).
Direct shares (sdílený media v DM) nesou ``share_type``; neznámá pole se ignoruje.

Detekce: **name-based** — SNS marker (``instagram``) + klíčová slova
(``messages``, ``direct_shares``); v dispatchi pre-pass na celé cestě PŘED
basename chainem (generic basenames kolidují s Google detektory).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_MESSAGES_PER_FILE = 20_000


@dataclass
class IgMessageRecord:
    """Jedna Instagram DM zpráva."""

    sender: str | None = None
    recipient: str | None = None
    text: str | None = None
    timestamp: int | None = None
    message_type: str | None = None  # text / image / video / share / ...
    conversation_id: str | None = None
    participants: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


def _to_int(value: Any) -> int | None:
    """Tolerantní konverze na int (int / numeric string)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _to_str(value: Any) -> str | None:
    """Tolerantní konverze na non-empty string."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_conversations(payload: Any) -> list[dict[str, Any]]:
    """Vytáhne seznam konverzačních objektů (pole nebo pod klíčem)."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("conversations", "messages", "value", "items"):
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def _extract_flat_messages(payload: Any) -> list[dict[str, Any]]:
    """Vytáhne plošné zprávy (warrant return formát bez konverzací)."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("messages", "value", "items"):
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def parse_instagram_messages(data: bytes) -> list[IgMessageRecord]:
    """ČISTÝ parser — Instagram DM JSON → záznamy.

    Podporuje oba formáty: konverzační (Takeout) i plošný (warrant return).

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez zpráv.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[IgMessageRecord] = []
    conversations = _extract_conversations(payload)

    # konverzační formát — objekty s vnořeným polem "messages"
    for conv in conversations[:MAX_MESSAGES_PER_FILE]:
        inner = conv.get("messages")
        if not isinstance(inner, list):
            continue
        conv_id = _to_str(conv.get("id"))
        participants_raw = conv.get("participants") or []
        participants = tuple(
            str(p) for p in participants_raw if isinstance(p, (str, int))
        )
        for msg in inner:
            if not isinstance(msg, dict):
                continue
            text = _to_str(msg.get("text", msg.get("body")))
            sender = _to_str(msg.get("sender", msg.get("from")))
            recipient = _to_str(msg.get("recipient", msg.get("to")))
            ts = _to_int(msg.get("timestamp", msg.get("time")))
            mtype = _to_str(msg.get("type")) or (
                "share" if msg.get("sharedMedia") else None
            )
            extra: dict[str, Any] = {}
            shared_media = msg.get("sharedMedia")
            if isinstance(shared_media, dict):
                url = _to_str(shared_media.get("url", shared_media.get("link")))
                if url:
                    extra["media_url"] = url[:300]
            records.append(
                IgMessageRecord(
                    sender=sender,
                    recipient=recipient,
                    text=text,
                    timestamp=ts,
                    message_type=mtype,
                    conversation_id=conv_id,
                    participants=participants,
                    extra=extra,
                )
            )

    if records:
        return records[:MAX_MESSAGES_PER_FILE]

    # plošný formát — zprávy přímo v poli (bez konverzačního obalu)
    for msg in _extract_flat_messages(payload)[:MAX_MESSAGES_PER_FILE]:
        text = _to_str(msg.get("body", msg.get("text")))
        sender = _to_str(msg.get("from", msg.get("sender")))
        recipient = _to_str(msg.get("to", msg.get("recipient")))
        ts = _to_int(msg.get("time", msg.get("timestamp")))
        if text is None and sender is None:
            continue
        records.append(
            IgMessageRecord(
                sender=sender,
                recipient=recipient,
                text=text,
                timestamp=ts,
                message_type=_to_str(msg.get("type")),
            )
        )

    if not records:
        raise TypeError("Nenalezeny Instagram DM zprávy")
    return records


def build_instagram_message_artifacts(
    records: list[IgMessageRecord],
) -> list[Artifact]:
    """ČISTÁ funkce: ze zpráv vytvoří artifacty (chat_message)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "instagram_messages"}
        if r.sender:
            details["sender"] = r.sender
        if r.recipient:
            details["recipient"] = r.recipient
        if r.message_type:
            details["message_type"] = r.message_type
        if r.conversation_id:
            details["conversation_id"] = r.conversation_id
        if r.participants:
            details["participants"] = list(r.participants)
        details.update(r.extra)

        title_parts = []
        if r.sender:
            title_parts.append(f"od {r.sender}")
        if r.recipient:
            title_parts.append(f"→ {r.recipient}")
        preview = (r.text or "")[:80]
        title = f"Instagram DM ({', '.join(title_parts)})" + (f": {preview}" if preview else "")

        artifacts.append(
            Artifact(
                artifact_type="chat_message",
                timestamp=None,  # epoch v details — konverze na ISO v reportu
                title=title[:120],
                details=details | ({"timestamp_epoch": r.timestamp} if r.timestamp is not None else {}),
                confidence=0.7 if (r.sender and r.text) else 0.5,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_instagram_message_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Instagram DM JSON → chat_message artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("InstagramMessages %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_instagram_messages(data)
    except (ValueError, TypeError) as e:
        logger.debug("InstagramMessages %s: %s", path.name, e)
        return []

    return build_instagram_message_artifacts(records)


def is_instagram_messages_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Instagram DM exportu.

    Vyžaduje SNS marker (``instagram``) v názvu/cestě + klíčová slova
    zpráv — generic basenames (``messages.json``) bez markery nepadnou,
    aby se nekradly Google Mail exporty.
    """
    lower = name.lower()
    if "instagram" not in lower:
        return False
    if not any(k in lower for k in ("message", "direct_share")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
