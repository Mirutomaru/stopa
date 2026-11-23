"""ETAPA B vlna 11 — Twitter/X Direct Messages parser (cloud export / warrant return).

AXIOM ekvivalenty: ``CloudTwitterDirectMessagesArtifact`` +
``CloudTwitterWarrantReturnDirectMessagesArtifact`` (``Magnet.Artifacts.Cloud.*``) —
soukromé konverzační zprávy mezi účty Twitteru/X.

Podporovaný formát: **JSON export DM** (Takeout / cloud export)::

    [{"id": "dm-1", "sender": "user_a", "recipient": "user_b",
      "text": "Ahoj!", "timestamp": 1728000000}]

   nebo konverzační formát::

    [{"conversation_id": "c-1", "participants": ["a", "b"],
      "messages": [{"sender": "a", "body": "Ahoj!", "time": "..."}]}]

Jedna zpráva = jeden artifact (``chat_message``, ``details.engine='twitter_messages'``).
Neznámá pole se ignoruje.

Detekce: **name-based** — SNS marker (``twitter``) + klíčová slova zpráv
(``message``, ``direct``); v dispatchi pre-pass na celé cestě PŘED basename
chainem (generic basenames kolidují s ostatními detektory).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_MESSAGES_PER_FILE = 20_000


@dataclass
class TwMessageRecord:
    """Jedna Twitter/X DM zpráva."""

    sender: str | None = None
    recipient: str | None = None
    text: str | None = None
    timestamp: int | None = None  # epoch sekundy
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


def _to_epoch(value: Any) -> int | None:
    """Tolerantní konverze času na epoch sekundy (int/ms/ISO 8601)."""
    if value is None or isinstance(value, bool):
        return None
    num = _to_int(value)
    if num is not None:
        # milisekundy — heuristika: epoch > 1e12 už jsou ms (rok ~33658)
        return num // 1_000 if abs(num) >= 10**12 else num
    text = _to_str(value)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _extract_messages(payload: Any) -> list[TwMessageRecord]:
    """Vytáhne zprávy — ploché pole i konverzační formát."""
    records: list[TwMessageRecord] = []

    def add(
        item: dict[str, Any],
        conversation_id: str | None = None,
        participants: tuple[str, ...] = (),
    ) -> None:
        sender = _to_str(item.get("sender", item.get("from")))
        recipient = _to_str(item.get("recipient", item.get("to")))
        text = _to_str(item.get("text", item.get("body", item.get("content"))))
        if not sender and not text:
            return
        records.append(
            TwMessageRecord(
                sender=sender,
                recipient=recipient,
                text=text,
                timestamp=_to_epoch(
                    item.get("timestamp", item.get("time", item.get("created_at")))
                ),
                conversation_id=conversation_id,
                participants=participants,
            )
        )

    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            # konverzační objekt s vnořenými zprávami?
            nested = item.get("messages")
            if isinstance(nested, list) and any(
                isinstance(m, dict) for m in nested[:3]
            ):
                conv_id = _to_str(item.get("id", item.get("conversation_id")))
                parts_raw = item.get("participants") or []
                participants = tuple(
                    str(p).strip()
                    for p in (parts_raw if isinstance(parts_raw, list) else [])
                    if str(p).strip()
                )
                for m in nested:
                    if isinstance(m, dict):
                        add(m, conv_id, participants)
            else:
                add(item)
    elif isinstance(payload, dict):
        for key in ("messages", "direct_messages", "conversations", "value"):
            val = payload.get(key)
            if not isinstance(val, list):
                continue
            for item in val:
                if isinstance(item, dict):
                    add(item)

    return records[:MAX_MESSAGES_PER_FILE]


def parse_twitter_messages(data: bytes) -> list[TwMessageRecord]:
    """ČISTÝ parser — Twitter/X DM JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez zpráv.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records = _extract_messages(payload)
    if not records:
        raise TypeError("Nenalezeny Twitter/X DM zprávy")
    return records


def build_twitter_message_artifacts(
    records: list[TwMessageRecord],
) -> list[Artifact]:
    """ČISTÁ funkce: ze zpráv vytvoří artifacty (chat_message)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "twitter_messages"}
        if r.sender:
            details["sender"] = r.sender
        if r.recipient:
            details["recipient"] = r.recipient
        if r.conversation_id:
            details["conversation_id"] = r.conversation_id
        if r.participants:
            details["participants"] = list(r.participants)

        title_parts = []
        if r.sender:
            title_parts.append(f"od {r.sender}")
        if r.recipient:
            title_parts.append(f"→ {r.recipient}")
        preview = (r.text or "")[:80]
        title = f"Twitter/X DM ({', '.join(title_parts)})" + (f": {preview}" if preview else "")

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


def extract_twitter_message_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Twitter/X DM JSON → chat_message artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("TwitterMessages %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_twitter_messages(data)
    except (ValueError, TypeError) as e:
        logger.debug("TwitterMessages %s: %s", path.name, e)
        return []

    return build_twitter_message_artifacts(records)


def is_twitter_messages_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Twitter/X DM exportu.

    Vyžaduje SNS marker (``twitter``) v názvu/cestě + klíčová slova zpráv —
    generic basenames bez markery nepadnou, aby se nekradly cizí exporty.
    """
    lower = name.lower()
    if "twitter" not in lower:
        return False
    if not any(k in lower for k in ("message", "direct")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
