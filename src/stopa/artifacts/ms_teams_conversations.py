"""ETAPA B vlna 12 — Microsoft Teams Conversations parser (cloud export / warrant return).

AXIOM ekvivalent: ``CloudMicrosoftTeamsConversationsArtifact``
(``Magnet.Artifacts.Cloud.Microsoft.Teams.Conversations.*``) — konverzační
zprávy z Microsoft Teams.

Podporovaný formát: **JSON export konverzací** (defenzivní parsing)::

    [{"conversationId": "19:...", "channelName": "Allgemein",
      "messages": [
        {"senderDisplayName": "John Doe", "body": "ahoj",
         "createdDateTime": "2024-10-03T12:00:00Z"}]}]

   nebo flat formát (warrant return)::

    [{"from": "Jane Roe", "text": "zpráva", "timestamp": 1727956800}]

Jeden message = jeden artifact (``chat_message``, ``details.engine='ms_teams_conversations'``,
``mimetype='ms:teams'``). Neznámá pole se ignoruje.

Detekce: **name-based** — Microsoft marker + klíčová slova Teams konverzací;
v dispatchi pre-pass na celé cestě PŘED basename chainem (generic basenames
kolidují s ostatními chat detektory).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_MESSAGES_PER_FILE = 5_000


@dataclass
class TeamsMessageRecord:
    """Jeden Teams message."""

    sender: str | None = None
    text: str | None = None
    conversation: str | None = None
    timestamp_s: float | None = None


def _to_str(value: Any) -> str | None:
    """Tolerantní konverze na non-empty string."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_list(value: Any) -> list[Any]:
    """Normalizuje pole / scalar / None na list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


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


def parse_teams_conversations(data: bytes) -> list[TeamsMessageRecord]:
    """ČISTÝ parser — Teams conversations JSON → záznamy.

    Podporuje konverzační formát (seznam konverzací s vnořenými messages) i
    flat formát (seznam zpráv).

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez zpráv.
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[TeamsMessageRecord] = []

    def add_message(item: dict[str, Any], conversation: str | None = None) -> None:
        sender = _to_str(
            item.get("senderDisplayName", item.get("from", item.get("sender")))
        )
        text = _to_str(
            item.get("body", item.get("text", item.get("content", item.get("message"))))
        )
        ts_s = _to_epoch(
            item.get(
                "createdDateTime",
                item.get("timestamp", item.get("date")),
            )
        )
        if not text and not sender:
            return
        records.append(
            TeamsMessageRecord(
                sender=sender,
                text=text,
                conversation=conversation,
                timestamp_s=ts_s,
            )
        )

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            # konverzační objekt s vnořenými messages?
            msgs = obj.get("messages")
            conv_name = _to_str(
                obj.get("channelName", obj.get("conversationTitle", obj.get("topic")))
            ) or _to_str(obj.get("conversationId"))
            if isinstance(msgs, list):
                for m in msgs:
                    if isinstance(m, dict):
                        add_message(m, conv_name)
                return
            # jinak — samotný message?
            if any(k in obj for k in ("body", "text", "content", "message")) and (
                "senderDisplayName" in obj or "from" in obj or "createdDateTime" in obj
            ):
                add_message(obj)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(payload)

    records = records[:MAX_MESSAGES_PER_FILE]
    if not records:
        raise TypeError("Nenalezeny Teams konverzační zprávy")
    return records


def build_teams_conversation_artifacts(
    records: list[TeamsMessageRecord],
) -> list[Artifact]:
    """ČISTÁ funkce: z Teams zpráv vytvoří artifacty (chat_message)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {
            "engine": "ms_teams_conversations",
            "mimetype": "ms:teams",
        }
        if r.sender:
            details["from"] = r.sender
        if r.conversation:
            details["conversation"] = r.conversation
        if r.text:
            details["body"] = r.text[:500]

        title = f"Teams Message: {r.sender or '?'}"
        ts = None
        if r.timestamp_s is not None:
            try:
                ts = from_unix(r.timestamp_s)
            except ValueError:
                ts = None

        artifacts.append(
            Artifact(
                artifact_type="chat_message",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.85 if r.text else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_teams_conversation_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Teams conversations JSON → chat_message artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("TeamsConversations %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_teams_conversations(data)
    except (ValueError, TypeError) as e:
        logger.debug("TeamsConversations %s: %s", path.name, e)
        return []

    return build_teams_conversation_artifacts(records)


def is_ms_teams_conversations_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Teams conversations exportu.

    Vyžaduje Microsoft marker (``microsoft``/``teams``) v názvu/cestě +
    klíčová slova konverzací — generic ``messages.json`` bez markery nepadne,
    aby se nekradly cizí chaty.
    """
    lower = name.lower()
    if not any(k in lower for k in ("microsoft", "teams")):
        return False
    if not any(k in lower for k in ("conversation", "message", "chat")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
