"""ETAPA B vlna 7 — Skype Warrant Return parser.

AXIOM ekvivalenty: ``SkypeWarrantReturnAccountDetailsArtifact`` +
``SkypeWarrantReturnChatHistoryRecordsArtifact`` +
``SkypeWarrantReturnConnectionHistoryArtifact`` +
``SkypeWarrantReturnContactsArtifact``.

Podporovaný formát: **Skype warrant return JSON** — 4 subtypy, auto-detekce
podle obsahu (filenames se liší)::

    # AccountDetails (jeden objekt)
    {"account": "skype:user", "email": "u@example.com", "displayName": "User"}

    # ChatHistoryRecords (pole zpráv)
    [{"conversationId": "...", "from": "8:a", "to": "8:b",
      "message": "text", "composetime": "2016-01-01T00:00:00.000Z"}, ...]

    # ConnectionHistory (pole kontaktů se stavem)
    [{"contact": "skype:x", "status": "accepted", "dateAdded": "..."}, ...]

    # Contacts (pole kontaktů)
    [{"displayName": "X", "msnId": "8:x", "email": "x@example.com"}, ...]

   Jeden záznam = jeden artifact. Subtypy generují různé ``artifact_type``:
   chat → ``messenger_message``, contacts/connection → ``contact``,
   account → ``skype_account``. Čas ISO 8601 / epoch ms tolerantně.

Detekce: **name-based** (``skype``) + content check (msnId/conversationId/
composetime markery).

Artifact types: ``messenger_message``, ``contact``, ``skype_account``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_ENTRIES_PER_FILE = 5_000


@dataclass
class SkypeRecord:
    """Jeden záznam Skype warrant returnu (subtyp určen parserem)."""

    sub_type: str = ""  # account | chat | connection | contact
    title: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    timestamp_s: float | None = None


def _parse_skype_time(value: Any) -> float | None:
    """ISO 8601 / epoch s/ms → epoch sekundy (tolerantní)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        # epoch ms vs s heuristika
        return v / 1000.0 if abs(v) > 1e12 else v
    text = str(value).strip()
    if not text:
        return None
    digits = text.replace(".", "", 1).lstrip("-")
    if digits.isdigit():
        try:
            v = float(text)
            return v / 1000.0 if len(digits) >= 13 else v
        except ValueError:
            return None
    iso = text.replace("Z", "+00:00")
    # Skype formát "2016-01-01T00:00:00.000+00:00" — fromisoformat zvládne
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        # fallback — odříznout frakci a zkusit znovu
        try:
            base = iso.split(".")[0]
            dt = datetime.fromisoformat(base)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            return None


def _s(value: Any) -> str:
    """Tolerantní string extrakce."""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, list):
        for item in value:
            s = _s(item)
            if s:
                return s
        return ""
    return str(value).strip()


def _detect_subtype(payload: Any) -> str:
    """Auto-detekce subtypu podle obsahu."""
    if isinstance(payload, dict):
        # AccountDetails — jeden objekt s account/email na top-level
        if any(k in payload for k in ("account", "msnId")) and (
            "email" in payload or "displayName" in payload
        ):
            return "account"
        return "unknown"

    if not isinstance(payload, list) or not payload:
        return "unknown"

    # vzorka prvního záznamu pro detekci
    sample = next((x for x in payload[:5] if isinstance(x, dict)), {})
    keys = set(sample.keys())

    if "conversationId" in keys or ("composetime" in keys and "message" in keys):
        return "chat"
    if "status" in keys and ("dateAdded" in keys or "contact" in keys):
        return "connection"
    if "msnId" in keys or ("displayName" in keys and "email" in keys):
        return "contact"
    return "unknown"


def _unwrap_list(payload: Any) -> list[dict[str, Any]]:
    """Normalizace na list dictů (objekt → [objekt], list → list)."""
    if isinstance(payload, dict):
        for key in ("records", "items", "contacts", "messages", "history"):
            v = payload.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        return [payload]
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


def parse_skype_warrant(data: bytes) -> list[SkypeRecord]:
    """ČISTÝ parser — Skype warrant return JSON → záznamy (auto-subtyp).

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale neznámý subtyp.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    subtype = _detect_subtype(payload)
    if subtype == "unknown":
        raise TypeError("Neznámý Skype warrant subtyp")

    records: list[SkypeRecord] = []

    if subtype == "account":
        obj = payload if isinstance(payload, dict) else {}
        account = _s(obj.get("account", obj.get("msnId")))
        email = _s(obj.get("email"))
        display = _s(obj.get("displayName", obj.get("name")))
        details: dict[str, Any] = {"engine": "skype_warrant"}
        if account:
            details["account"] = account
        if email:
            details["email"] = email
        records.append(
            SkypeRecord(
                sub_type="account",
                title=display or account[:50] or "Skype účet",
                details=details,
            )
        )
        return records

    items = _unwrap_list(payload)[:MAX_ENTRIES_PER_FILE]

    for item in items:
        if subtype == "chat":
            message = _s(item.get("message", item.get("content")))
            sender = _s(item.get("from", item.get("sender")))
            recipient = _s(item.get("to", item.get("recipient")))
            ts_s = _parse_skype_time(
                item.get("composetime", item.get("timestamp", item.get("time")))
            )
            details = {"engine": "skype_warrant"}
            if sender:
                details["sender"] = sender
            if recipient:
                details["recipient"] = recipient
            conv = _s(item.get("conversationId"))
            if conv:
                details["conversation_id"] = conv
            records.append(
                SkypeRecord(
                    sub_type="chat",
                    title=(message[:60] or "Skype zpráva"),
                    details=details,
                    timestamp_s=ts_s,
                )
            )

        elif subtype == "connection":
            contact = _s(item.get("contact", item.get("msnId")))
            status = _s(item.get("status"))
            ts_s = _parse_skype_time(
                item.get("dateAdded", item.get("timestamp", item.get("time")))
            )
            details = {"engine": "skype_warrant"}
            if contact:
                details["contact"] = contact
            if status:
                details["status"] = status
            records.append(
                SkypeRecord(
                    sub_type="connection",
                    title=contact[:60] or "Skype spojení",
                    details=details,
                    timestamp_s=ts_s,
                )
            )

        elif subtype == "contact":
            display = _s(item.get("displayName", item.get("name")))
            msn_id = _s(item.get("msnId"))
            email = _s(item.get("email"))
            details = {"engine": "skype_warrant"}
            if msn_id:
                details["msn_id"] = msn_id
            if email:
                details["email"] = email
            records.append(
                SkypeRecord(
                    sub_type="contact",
                    title=display or msn_id[:50] or "Skype kontakt",
                    details=details,
                )
            )

    return records


def is_skype_warrant_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Skype warrant returnu."""
    lower = name.lower()
    has_name = "skype" in lower
    if not has_name and not head:
        # bez skype v názvu + bez obsahu → zamítnout
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"[", b"{")):
            return False
        joined = head[:2048].lower()
        markers = (b"msnid", b"conversationid", b"composetime")
        has_marker = any(k in joined for k in markers)
        # skype v názvu → přijmout; jinak vyžadovat silný marker
        return has_name or has_marker
    # bez headu — přijmout jen skype v názvu
    return has_name


def build_skype_artifacts(records: list[SkypeRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (podle subtypu)."""
    artifacts: list[Artifact] = []
    for r in records:
        details = dict(r.details)
        ts = from_unix(r.timestamp_s) if r.timestamp_s is not None else None

        if r.sub_type == "chat":
            artifact_type = "messenger_message"
            confidence = 0.8 if (r.title and r.timestamp_s is not None) else 0.6
        elif r.sub_type in ("contact", "connection"):
            artifact_type = "contact"
            confidence = 0.7
        else:  # account
            artifact_type = "skype_account"
            confidence = 0.8

        artifacts.append(
            Artifact(
                artifact_type=artifact_type,
                timestamp=ts,
                title=f"Skype: {r.title}"[:120],
                details=details,
                confidence=confidence,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_skype_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Skype warrant JSON → artifacty (auto-subtyp)."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("SkypeWarrant %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_skype_warrant(data)
    except (ValueError, TypeError) as e:
        logger.debug("SkypeWarrant %s: %s", path, e)
        return []

    return build_skype_artifacts(records)
