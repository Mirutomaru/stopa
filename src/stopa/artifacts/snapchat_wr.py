"""ETAPA B vlna 10 — Snapchat Warrant Return parser (cloud export).

AXIOM ekvivalenty: ``SnapchatMessagesWarrantReturnArtifact`` +
``SnapchatGroupChatMessagesArtifact`` + ``SnapchatFriendsArtifact`` +
``SnapchatGeolocationArtifact`` + ``SnapchatIpHistoryArtifact`` +
``SnapchatAccountInformationArtifact`` (``Magnet.Artifacts.Cloud.*``).

Podporovaný formát: **JSON export** (warrant return / cloud export)::

    Zprávy: [{"from": "user_a", "to": "user_b", "body": "Ahoj!",
              "time": 1728000000, "group_id": null}]
    Přátelé: [{"username": "friend_1", "full_name": "..."}]
    Geolokace: [{"latitude": 50.09, "longitude": 14.43, "time": ...}]
    IP historie: [{"ip_address": "1.2.3.4", "time": ..., "event_type": "login"}]
    Účet: {"username": "...", "email": "...", "phone_number": "..."}

Artifact mapping (jeden záznam = jeden artifact):
- zprávy → ``chat_message`` (``details.engine='snapchat_wr'``, group_id pro skupiny)
- přátelé + účet → ``contact`` (``mimetype='sns:snapchat:*'`` — E4 entity extrakce)
- geolokace → ``location_data``; IP historie → ``network_connection``

Detekce: **name-based** — SNS marker (``snapchat``) v názvu/cestě + klíčová
slova obsahu; v dispatchi pre-pass na celé cestě PŘED basename chainem.
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

MAX_RECORDS_PER_FILE = 20_000


@dataclass
class ScMessageRecord:
    """Jedna Snapchat zpráva (DM nebo skupinová)."""

    sender: str | None = None
    recipient: str | None = None
    text: str | None = None
    timestamp: int | None = None
    group_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScContactRecord:
    """Jeden Snapchat kontakt (přítel / účet)."""

    username: str | None = None
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    relationship: str | None = None  # friend / account


@dataclass
class ScLocationRecord:
    """Jeden geolokační bod."""

    latitude: float | None = None
    longitude: float | None = None
    timestamp: int | None = None
    accuracy: float | None = None


@dataclass
class ScIpRecord:
    """Jeden IP záznam historie."""

    ip_address: str | None = None
    timestamp: int | None = None
    event_type: str | None = None


def _to_int(value: Any) -> int | None:
    """Tolerantní konverze na int (int / numeric string)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _to_float(value: Any) -> float | None:
    """Tolerantní konverze na float."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _to_str(value: Any) -> str | None:
    """Tolerantní konverze na non-empty string."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_list(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """Vytáhne seznam záznamů (pole nebo pod jedním z klíčů)."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in keys:
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def parse_snapchat_messages(data: bytes) -> list[ScMessageRecord]:
    """ČISTÝ parser — Snapchat zprávy JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez zpráv.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[ScMessageRecord] = []
    items = _extract_list(payload, ("messages", "conversations", "value", "items"))

    for item in items[:MAX_RECORDS_PER_FILE]:
        # konverzační formát — vnořené zprávy
        inner = item.get("messages")
        if isinstance(inner, list):
            group_id = _to_str(item.get("group_id", item.get("id")))
            for msg in inner:
                if not isinstance(msg, dict):
                    continue
                records.append(
                    ScMessageRecord(
                        sender=_to_str(msg.get("from", msg.get("sender"))),
                        recipient=_to_str(msg.get("to", msg.get("recipient"))),
                        text=_to_str(msg.get("body", msg.get("text"))),
                        timestamp=_to_int(msg.get("time", msg.get("timestamp"))),
                        group_id=group_id,
                    )
                )
            continue

        # plošný formát — zpráva přímo v položce
        text = _to_str(item.get("body", item.get("text")))
        sender = _to_str(item.get("from", item.get("sender")))
        if text is None and sender is None:
            continue
        records.append(
            ScMessageRecord(
                sender=sender,
                recipient=_to_str(item.get("to", item.get("recipient"))),
                text=text,
                timestamp=_to_int(item.get("time", item.get("timestamp"))),
                group_id=_to_str(item.get("group_id")),
            )
        )

    if not records:
        raise TypeError("Nenalezeny Snapchat zprávy")
    return records


def parse_snapchat_contacts(data: bytes) -> list[ScContactRecord]:
    """ČISTÝ parser — Snapchat přátelé/účet JSON → kontakty.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez kontaktů.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[ScContactRecord] = []

    # účet — jediný objekt s identitou
    if isinstance(payload, dict):
        username = _to_str(payload.get("username", payload.get("user")))
        email = _to_str(payload.get("email"))
        phone = _to_str(payload.get("phone_number", payload.get("phone")))
        full_name = _to_str(payload.get("full_name", payload.get("name")))
        if username or email or phone:
            records.append(
                ScContactRecord(
                    username=username,
                    full_name=full_name,
                    email=email,
                    phone=phone,
                    relationship="account",
                )
            )

    # přátelé — seznam
    for item in _extract_list(payload, ("friends", "contacts", "value")):
        username = _to_str(item.get("username", item.get("user")))
        if not username and not _to_str(item.get("full_name", item.get("name"))):
            continue
        records.append(
            ScContactRecord(
                username=username,
                full_name=_to_str(item.get("full_name", item.get("name"))),
                email=_to_str(item.get("email")),
                phone=_to_str(item.get("phone_number", item.get("phone"))),
                relationship="friend",
            )
        )

    if not records:
        raise TypeError("Nenalezeny Snapchat kontakty")
    return records


def parse_snapchat_geolocation(data: bytes) -> list[ScLocationRecord]:
    """ČISTÝ parser — Snapchat geolokace JSON → body.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez bodů.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[ScLocationRecord] = []
    for item in _extract_list(payload, ("locations", "geolocation", "value")):
        lat = _to_float(item.get("latitude", item.get("lat")))
        lon = _to_float(item.get("longitude", item.get("lon")))
        if lat is None and lon is None:
            continue
        records.append(
            ScLocationRecord(
                latitude=lat,
                longitude=lon,
                timestamp=_to_int(item.get("time", item.get("timestamp"))),
                accuracy=_to_float(item.get("accuracy")),
            )
        )

    if not records:
        raise TypeError("Nenalezeny Snapchat geolokační body")
    return records


def parse_snapchat_ip_history(data: bytes) -> list[ScIpRecord]:
    """ČISTÝ parser — Snapchat IP historie JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez IP záznamů.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[ScIpRecord] = []
    for item in _extract_list(payload, ("ip_history", "ips", "value")):
        ip = _to_str(item.get("ip_address", item.get("ip")))
        if not ip:
            continue
        records.append(
            ScIpRecord(
                ip_address=ip,
                timestamp=_to_int(item.get("time", item.get("timestamp"))),
                event_type=_to_str(item.get("event_type", item.get("type"))),
            )
        )

    if not records:
        raise TypeError("Nenalezeny Snapchat IP záznamy")
    return records


def build_snapchat_message_artifacts(records: list[ScMessageRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze zpráv vytvoří artifacty (chat_message)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "snapchat_wr"}
        if r.sender:
            details["sender"] = r.sender
        if r.recipient:
            details["recipient"] = r.recipient
        if r.group_id:
            details["group_id"] = r.group_id
        details.update(r.extra)

        title_parts = []
        if r.sender:
            title_parts.append(f"od {r.sender}")
        if r.recipient:
            title_parts.append(f"→ {r.recipient}")
        kind = "Skupina" if r.group_id else "DM"
        preview = (r.text or "")[:80]
        title = f"Snapchat {kind} ({', '.join(title_parts)})" + (f": {preview}" if preview else "")

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


def build_snapchat_contact_artifacts(records: list[ScContactRecord]) -> list[Artifact]:
    """ČISTÁ funkce: z kontaktů vytvoří artifacty (contact).

    E4 entity extrakce: title = hodnota pole, mimetype určuje typ entity
    (``sns:snapchat:email`` → email, ``sns:snapchat:phone`` → telefon).
    """
    artifacts: list[Artifact] = []
    for r in records:
        base_details: dict[str, Any] = {"engine": "snapchat_wr"}
        if r.relationship:
            base_details["relationship"] = r.relationship

        # hlavní kontakt — username (heuristická klasifikace v E4)
        if r.username:
            artifacts.append(
                Artifact(
                    artifact_type="contact",
                    timestamp=None,
                    title=f"Snapchat {r.relationship or 'user'}: {r.username}"[:120],
                    details=base_details | {"mimetype": "sns:snapchat:user"},
                    confidence=0.6,
                    parser_version=PARSER_VERSION,
                )
            )

        # email / telefon — samostatné kontakty pro E4 entity extrakci
        if r.email:
            artifacts.append(
                Artifact(
                    artifact_type="contact",
                    timestamp=None,
                    title=r.email[:120],
                    details=base_details | {"mimetype": "sns:snapchat:email"},
                    confidence=0.7,
                    parser_version=PARSER_VERSION,
                )
            )
        if r.phone:
            artifacts.append(
                Artifact(
                    artifact_type="contact",
                    timestamp=None,
                    title=r.phone[:120],
                    details=base_details | {"mimetype": "sns:snapchat:phone"},
                    confidence=0.7,
                    parser_version=PARSER_VERSION,
                )
            )

    return artifacts


def build_snapchat_location_artifacts(records: list[ScLocationRecord]) -> list[Artifact]:
    """ČISTÁ funkce: z geolokačních bodů vytvoří artifacty (location_data)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "snapchat_wr"}
        if r.latitude is not None:
            details["latitude"] = r.latitude
        if r.longitude is not None:
            details["longitude"] = r.longitude
        if r.accuracy is not None:
            details["accuracy_meters"] = r.accuracy

        coords = f"{r.latitude:.4f},{r.longitude:.4f}" if (r.latitude is not None and r.longitude is not None) else "?"
        title = f"Snapchat geolocation ({coords})"[:120]
        artifacts.append(
            Artifact(
                artifact_type="location_data",
                timestamp=None,  # epoch v details — konverze na ISO v reportu
                title=title,
                details=details | ({"timestamp_epoch": r.timestamp} if r.timestamp is not None else {}),
                confidence=0.7 if (r.latitude is not None and r.longitude is not None) else 0.4,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def build_snapchat_ip_artifacts(records: list[ScIpRecord]) -> list[Artifact]:
    """ČISTÁ funkce: z IP záznamů vytvoří artifacty (network_connection)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "snapchat_wr"}
        if r.ip_address:
            details["ip_address"] = r.ip_address
        if r.event_type:
            details["event_type"] = r.event_type

        title = f"Snapchat IP ({r.ip_address or '?'})" + (f" [{r.event_type}]" if r.event_type else "")
        artifacts.append(
            Artifact(
                artifact_type="network_connection",
                timestamp=None,  # epoch v details — konverze na ISO v reportu
                title=title[:120],
                details=details | ({"timestamp_epoch": r.timestamp} if r.timestamp is not None else {}),
                confidence=0.7 if r.ip_address else 0.4,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_snapchat_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Snapchat WR JSON → artifacty podle obsahu.

    Auto-detekce typu podle struktury payloadu (zprávy / přátelé / geolokace /
    IP historie / účet) — jeden soubor WR může nést více sekcí.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("SnapchatWR %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    artifacts: list[Artifact] = []
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.debug("SnapchatWR %s: neplatné JSON", path.name)
        return []

    # auto-detekce sekcí podle klíčů payloadu
    lower_keys = set()
    if isinstance(payload, dict):
        lower_keys = {str(k).lower() for k in payload}
    elif isinstance(payload, list) and payload:
        first = next((x for x in payload if isinstance(x, dict)), {})
        lower_keys = {str(k).lower() for k in first}

    try:
        if any(k in lower_keys for k in ("messages", "conversations")) or (
            isinstance(payload, list) and any(
                isinstance(x, dict) and ("body" in x or "text" in x) for x in payload[:5]
            )
        ):
            artifacts.extend(build_snapchat_message_artifacts(parse_snapchat_messages(data)))
    except (ValueError, TypeError):
        pass

    try:
        if any(k in lower_keys for k in ("friends", "contacts")) or (
            isinstance(payload, dict) and any(
                k in payload for k in ("username", "email", "phone_number")
            )
        ):
            artifacts.extend(build_snapchat_contact_artifacts(parse_snapchat_contacts(data)))
    except (ValueError, TypeError):
        pass

    try:
        if any(k in lower_keys for k in ("locations", "geolocation")) or (
            isinstance(payload, list) and any(
                isinstance(x, dict) and ("latitude" in x or "lat" in x) for x in payload[:5]
            )
        ):
            artifacts.extend(build_snapchat_location_artifacts(parse_snapchat_geolocation(data)))
    except (ValueError, TypeError):
        pass

    try:
        if any(k in lower_keys for k in ("ip_history", "ips")) or (
            isinstance(payload, list) and any(
                isinstance(x, dict) and ("ip_address" in x or "ip" in x) for x in payload[:5]
            )
        ):
            artifacts.extend(build_snapchat_ip_artifacts(parse_snapchat_ip_history(data)))
    except (ValueError, TypeError):
        pass

    return artifacts


def is_snapchat_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Snapchat WR exportu.

    Vyžaduje SNS marker (``snapchat``) v názvu/cestě — generic basenames bez
    markery nepadnou, aby se nekradly cizí exporty.
    """
    lower = name.lower()
    if "snapchat" not in lower:
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
