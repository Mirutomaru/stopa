"""ETAPA B vlna 5 — Google IM chat rodina parser (lokální profil / Takeout).

AXIOM ekvivalenty: ``GoogleChatArtifact``, ``GoogleHangoutsArtifact``,
``GooglePlusChatArtifact``, ``GoogleTalkArtifact``
(``Magnet.Artifacts.Cloud.Google.WarrantReturn.*``).

Podporovaný formát: **Takeout Hangouts/Chat JSON** (``Hangouts.json``)::

    {"conversations": [
        {"conversation": {"conversation_id": {"id": "cid-..."}, ...},
         "events": [
            {"event_type": "REGULAR_CHAT_MESSAGE",
             "chat_message": {"message_content": {
                 "segment": [{"type": "TEXT", "text": "..."}]}},
             "sender_id": {"gaia_id": "..."},
             "timestamp": "1369968040768557"}]}]}

   ``timestamp`` = **mikrosekundy od Unix epochy** (webkit time) → s = v/1e6.
   Text zpojený ze segmentů (type TEXT). Jeden REGULAR_CHAT_MESSAGE = jeden
   artifact (``chat_message``), engine rozlišuje chat/hangouts/plus/talk.

Detekce: **name-based** (``hangouts``, ``google_chat``, ``plus_chat``,
``talk``) + content check (JSON s ``conversations``).

Artifact type: ``chat_message`` — propojí se do chat view; details.engine
rozlišuje konkrétní Google IM službu.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_MESSAGES_PER_FILE = 5_000


@dataclass
class ChatMessage:
    """Jedna zpráva Google IM chatu."""

    conversation_id: str = ""
    sender_id: str = ""
    text: str = ""
    timestamp_s: float | None = None
    event_type: str = "REGULAR_CHAT_MESSAGE"


def _ts_to_seconds(value: Any) -> float | None:
    """Webkit time (µs od epochy) nebo epoch s/ms → sekundy."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(str(value).strip())
    except ValueError:
        return None
    # µs od epochy (16+ číslic) → s; ms (13+) → s; jinak už s
    if abs(v) > 1e15:
        return v / 1_000_000.0
    if abs(v) > 1e12:
        return v / 1_000.0
    return v


def _segments_text(content: Any) -> str:
    """Z message_content segmentů → text (jen type TEXT)."""
    if not isinstance(content, dict):
        return ""
    segments = content.get("segment")
    parts: list[str] = []
    if isinstance(segments, list):
        for seg in segments:
            if isinstance(seg, dict) and str(seg.get("type", "")).upper() == "TEXT":
                t = seg.get("text")
                if isinstance(t, str):
                    parts.append(t)
    return "".join(parts)


def parse_chat_messages(data: bytes) -> list[ChatMessage]:
    """ČISTÝ parser — Takeout Hangouts/Chat JSON → zprávy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne objekt s conversations.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    if not isinstance(payload, dict):
        raise TypeError("Očekáván JSON objekt s conversations")

    convs = payload.get("conversations")
    if not isinstance(convs, list):
        return []

    messages: list[ChatMessage] = []
    for conv in convs:
        if not isinstance(conv, dict):
            continue
        meta = conv.get("conversation") or {}
        cid_raw = (meta.get("conversation_id") or {}) if isinstance(meta, dict) else {}
        cid = str(cid_raw.get("id") or "") if isinstance(cid_raw, dict) else ""

        events = conv.get("events")
        if not isinstance(events, list):
            continue
        for ev in events:
            if len(messages) >= MAX_MESSAGES_PER_FILE:
                logger.warning("GoogleChat: limit %d zpráv", MAX_MESSAGES_PER_FILE)
                break
            if not isinstance(ev, dict):
                continue
            etype = str(ev.get("event_type") or "").upper()
            if "CHAT_MESSAGE" not in etype and "MESSAGE" not in etype:
                # jen textové zprávy (ne system events) — ale zachovej i ostatní s textem
                cm = ev.get("chat_message")
                if not isinstance(cm, dict):
                    continue

            sender_raw = ev.get("sender_id") or {}
            sender = str(sender_raw.get("gaia_id") or "") if isinstance(sender_raw, dict) else ""

            cm = ev.get("chat_message") or {}
            text = _segments_text(cm.get("message_content")) if isinstance(cm, dict) else ""
            if not text:
                continue

            ts_s = _ts_to_seconds(ev.get("timestamp"))
            messages.append(
                ChatMessage(
                    conversation_id=cid,
                    sender_id=sender,
                    text=text,
                    timestamp_s=ts_s,
                    event_type=str(ev.get("event_type") or ""),
                )
            )

    return messages


def is_google_chat_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Google IM chat exportu (Hangouts/Chat/Plus/Talk)."""
    lower = name.lower()
    if not any(k in lower for k in ("hangouts", "google_chat", "plus_chat", "talk")):
        return False
    return not (head and not head[:2048].lstrip().startswith(b"{"))


def build_chat_artifacts(messages: list[ChatMessage]) -> list[Artifact]:
    """ČISTÁ funkce: ze zpráv vytvoří artifacty (chat_message)."""
    artifacts: list[Artifact] = []
    for m in messages:
        preview = m.text[:80].replace("\n", " ")
        title = f"Google chat message: {preview}" if preview else "Google chat message"

        details: dict[str, Any] = {"engine": "google_takeout_chat"}
        if m.conversation_id:
            details["conversation_id"] = m.conversation_id
        if m.sender_id:
            details["sender_id"] = m.sender_id
        details["text"] = m.text

        ts = from_unix(m.timestamp_s) if m.timestamp_s is not None else None
        artifacts.append(
            Artifact(
                artifact_type="chat_message",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.85 if (m.text and m.timestamp_s is not None) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_google_chat_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Google IM chat → chat_message artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("GoogleChat %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        messages = parse_chat_messages(data)
    except (ValueError, TypeError) as e:
        logger.debug("GoogleChat %s: %s", path, e)
        return []

    return build_chat_artifacts(messages)
