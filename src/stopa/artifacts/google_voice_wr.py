"""ETAPA B vlna 8 — Google Voice warrant return parser.

AXIOM ekvivalenty: ``GoogleVoiceTexts2025Artifact`` +
``GoogleVoicemail2025Artifact`` + ``GoogleVoiceContactsMetadata2026Artifact`` +
``GoogleVoiceSubscriberInformation2026Artifact``.

Podporovaný formát: **Google Voice warrant return JSON** (defenzivní parsing —
formát je proprietární, subtypy se auto-detekují podle markerů)::

    # SMS/MMS texty
    [{"from": "+1555...", "to": "...", "body": "text",
      "timestampMsInEpoch": 1704067200000, "direction": "inbound"}]

    # Hlasové schránky
    [{"id": "...", "fromNumber": "+1555...", "durationSeconds": 42,
      "timestampMsInEpoch": ..., "transcript": "..."}]

    # Kontakty (metadata)
    [{"name": "John Doe", "phoneNumber": "+1555...", "emailAddress": "..."}]

    # Informace o předplatiteli
    {"subscriberNumber": "+1555...", "carrierName": "...", "planType": "..."}

   Subtyp → artifact type:
   - texty → ``sms_message`` (odchozí/příchozí podle direction)
   - voicemail → ``voicemail``
   - kontakty → ``contact``
   - subscriber info → ``google_account`` (snapshot, timestamp=None)

Detekce: **name-based** (``voice``, ``voicemail``, ``gvoice``) + content check
(JSON s voice-like klíči).

Artifact types: ``sms_message`` / ``voicemail`` / ``contact`` / ``google_account``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_ENTRIES_PER_FILE = 5_000


@dataclass
class VoiceRecord:
    """Jeden záznam Google Voice (subtyp určen auto-detekcí)."""

    kind: str  # "sms" | "voicemail" | "contact" | "subscriber"
    name: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    timestamp_s: float | None = None


def _epoch_ms_to_seconds(value: Any) -> float | None:
    """Epoch ms / s → epoch sekundy (tolerantně)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (ValueError, TypeError):
        text = str(value).strip()
        if not text:
            return None
        try:
            v = float(text)
        except ValueError:
            return None
    if v <= 0:
        return None
    # heuristika: ms vs s
    if v > 1e12:
        v /= 1000.0
    return v


def _detect_kind(payload: Any) -> str | None:
    """Auto-detekce subtypu podle markerů v payloadu."""
    keys: set[str] = set()

    def collect(obj: Any) -> None:
        if isinstance(obj, dict):
            for k in obj:
                keys.add(str(k).lower())
        elif isinstance(obj, list):
            for item in obj[:5]:  # jen vzorek — velká pole nebrzdí detekci
                collect(item)

    collect(payload)

    if any(k in keys for k in ("timestampmsinepoch", "body")) and (
        "from" in keys or "to" in keys or "direction" in keys
    ):
        return "sms"
    if any(k in keys for k in ("durationseconds", "transcript", "voicemailid")):
        return "voicemail"
    if any(k in keys for k in ("subscribernumber", "carriername", "plantype")):
        return "subscriber"
    if any(k in keys for k in ("phonenumber", "emailaddress")) and "name" in keys:
        return "contact"
    return None


def _extract_list(payload: Any) -> list[dict[str, Any]]:
    """Vytáhne seznam záznamů (pole nebo pole pod klíčem)."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("value", "items", "results", "messages", "contacts", "voicemails"):
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def parse_google_voice(data: bytes) -> tuple[str | None, list[VoiceRecord]]:
    """ČISTÝ parser — Google Voice JSON → (subtyp, záznamy).

    Returns:
        (kind, records) — kind je "sms"/"voicemail"/"contact"/"subscriber",
        nebo None pokud subtyp nebyl rozpoznán.

    Raises:
        ValueError: Neplatné JSON.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    kind = _detect_kind(payload)
    if kind is None:
        return None, []

    records: list[VoiceRecord] = []

    if kind == "subscriber":
        # snapshot — jeden záznam (objekt nebo první položka pole)
        item = payload if isinstance(payload, dict) else (_extract_list(payload) or [{}])[0]
        details: dict[str, Any] = {"engine": "google_voice", "subkind": "subscriber"}
        for key in ("subscriberNumber", "carrierName", "planType", "accountStatus"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                details[key.lower()] = val.strip()
        records.append(VoiceRecord(kind="subscriber", name=details.get("subscribernumber", "předplatitel"), details=details))
        return kind, records

    items = _extract_list(payload)
    for item in items[:MAX_ENTRIES_PER_FILE]:
        if kind == "sms":
            body = str(item.get("body") or "").strip()
            sender = str(item.get("from") or item.get("senderNumber") or "").strip()
            recipient = str(item.get("to") or item.get("recipientNumber") or "").strip()
            direction = str(item.get("direction") or "").strip().lower()
            if not body and not sender:
                continue
            details = {
                "engine": "google_voice",
                "subkind": "sms",
                "from": sender,
                "to": recipient,
                "body": body[:500],
            }
            if direction:
                details["direction"] = direction
            ts_s = _epoch_ms_to_seconds(item.get("timestampMsInEpoch", item.get("timestamp")))
            records.append(
                VoiceRecord(kind="sms", name=sender or recipient or "SMS", details=details, timestamp_s=ts_s)
            )

        elif kind == "voicemail":
            sender = str(item.get("fromNumber") or item.get("from") or "").strip()
            duration = item.get("durationSeconds", item.get("duration"))
            transcript = str(item.get("transcript") or "").strip()
            details: dict[str, Any] = {"engine": "google_voice", "subkind": "voicemail"}
            if sender:
                details["from"] = sender
            try:
                if duration is not None:
                    details["duration_seconds"] = int(duration)
            except (ValueError, TypeError):
                logger.debug("Google Voice duration %r nepárabilní → bez délky hovoru", duration)
            if transcript:
                details["transcript"] = transcript[:500]
            ts_s = _epoch_ms_to_seconds(item.get("timestampMsInEpoch", item.get("timestamp")))
            records.append(
                VoiceRecord(kind="voicemail", name=sender or "Voicemail", details=details, timestamp_s=ts_s)
            )

        elif kind == "contact":
            cname = str(item.get("name") or "").strip()
            phone = str(item.get("phoneNumber") or item.get("phone") or "").strip()
            email = str(item.get("emailAddress") or item.get("email") or "").strip()
            if not cname and not phone:
                continue
            details = {"engine": "google_voice", "subkind": "contact"}
            if phone:
                details["phone"] = phone
            if email:
                details["email"] = email
            records.append(VoiceRecord(kind="contact", name=cname or phone, details=details))

    return kind, records


def is_google_voice_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Google Voice exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("voice", "voicemail", "gvoice")):
        return False
    # vyhnout se kolizi s ios_voicemail (vlna 4, .db) a samsung voice recording
    if lower.endswith(".db") or "recording" in lower:
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
        joined = head[:2048].lower()
        if not any(
            k in joined
            for k in (b"timestampmsinepoch", b"subscribernumber", b"durationseconds", b"phonenumber")
        ):
            return False
    return True


def build_voice_artifacts(kind: str, records: list[VoiceRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty podle subtypu."""
    artifacts: list[Artifact] = []
    for r in records:
        if r.kind == "sms":
            atype, confidence = "sms_message", 0.85
        elif r.kind == "voicemail":
            atype, confidence = "voicemail", 0.85
        elif r.kind == "contact":
            atype, confidence = "contact", 0.7
        else:  # subscriber
            atype, confidence = "google_account", 0.6

        ts = None
        if r.timestamp_s is not None:
            try:
                ts = from_unix(r.timestamp_s)
            except ValueError:
                ts = None

        artifacts.append(
            Artifact(
                artifact_type=atype,
                timestamp=ts,
                title=f"Google Voice {r.name}"[:120],
                details=r.details,
                confidence=confidence,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_google_voice_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Google Voice JSON → sms/voicemail/contact/google_account."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("GoogleVoice %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        kind, records = parse_google_voice(data)
    except (ValueError, TypeError) as e:
        logger.debug("GoogleVoice %s: %s", path, e)
        return []

    if kind is None or not records:
        return []

    return build_voice_artifacts(kind, records)
