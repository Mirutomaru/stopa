"""ETAPA B vlna 14 — Apple Cloud rodina parser (cloud export / warrant return).

AXIOM ekvivalenty: ``CloudAppleContactsArtifact`` + ``CloudAppleKeychainArtifact``
+ ``CloudAppleMailArtifact`` + ``CloudApplePhotosArtifact`` + ``CloudAppleBackupArtifact``
(``Magnet.Artifacts.Cloud.Apple.*``) — kontakty, keychain položky, e-maily, fotky a
backup položky z Apple/ICloud účtů.

Podporované formáty (defenzivní parsing, auto-detekce podtypu)::

    1. Kontakty (JSON list nebo wrapper)::

        [{"firstName": "Jan", "lastName": "Novák",
          "emailAddresses": ["jan@x.cz"], "phoneNumbers": ["+420..."]}, ...]

    2. Keychain položky::

        [{"label": "github.com", "account": "user", "type": "inetpw",
          "data": "base64...", "created": 1728136800}, ...]

    3. E-maily::

        [{"subject": "Re: faktura", "from": "a@b.cz", "to": ["c@d.cz"],
          "body": "...", "date": "2024-10-05T10:00:00Z"}, ...]

    4. Fotky::

        [{"filename": "IMG_0001.jpg", "creationDate": "2024-10-05T10:00:00Z",
          "latitude": 50.0, "longitude": 14.4}, ...]

    5. Backup položky::

        [{"name": "app.db", "domain": "AppDomain", "size": 2048,
          "relativePath": "/Backup/app.db"}, ...]

Jeden záznam = jeden artifact (podtyp → konkrétní ``artifact_type``:
contact / credential / email_message / document_metadata(photo) / file_metadata).
Neznámá pole se ignorují.

Detekce: **name-based** — apple/icloud marker + klíčová slova; v dispatchi
pre-pass na celé cestě PŘED basename chainem (generic basenames kolidují s
ostatními detektory).
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
class AppleCloudRecord:
    """Jeden Apple Cloud záznam (podtyp + normalizovaná data)."""

    kind: str = ""  # contact | keychain | mail | photo | backup
    name: str | None = None
    detail: str | None = None
    email: str | None = None
    phone: str | None = None
    body: str | None = None
    recipient: str | None = None
    sender: str | None = None
    size: int | None = None
    path: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    created_s: float | None = None


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


def _list_of_str(value: Any) -> list[str]:
    """Tolerantní konverze na seznam non-empty stringů."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            # dict položka (např. {"value": "x"}) — extrahuj 'value' apod.
            if isinstance(item, dict):
                for key in ("value", "address", "number", "email"):
                    s = _to_str(item.get(key))
                    if s:
                        out.append(s)
                        break
                continue
            s = _to_str(item)
            if s:
                out.append(s)
        return out
    # dict (např. {"value": "x"}) — vezmi 'value'/'address'/'number'
    if isinstance(value, dict):
        for key in ("value", "address", "number", "email"):
            s = _to_str(value.get(key))
            if s:
                return [s]
    return []


def _to_int(value: Any) -> int | None:
    """Tolerantní konverze na nezáporné celé číslo."""
    try:
        num = int(float(value))
    except (ValueError, TypeError):
        return None
    return num if num >= 0 else None


def _to_float(value: Any) -> float | None:
    """Tolerantní konverze na float."""
    try:
        num = float(value)
    except (ValueError, TypeError):
        return None
    return num


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
    """Určí Apple podtyp podle cesty/názvu + tvaru položky."""
    lower = name.lower()
    # explicitní hint z cesty
    for marker, kind in (
        ("contact", "contact"),
        ("keychain", "keychain"),
        ("mail", "mail"),
        ("photo", "photo"),
        ("backup", "backup"),
    ):
        if marker in lower:
            return kind
    # fallback podle klíčů
    if any(k in item for k in ("firstName", "lastName", "emailAddresses")):
        return "contact"
    if _to_str(item.get("label")) and (
        _to_str(item.get("account")) or _to_str(item.get("type"))
    ):
        return "keychain"
    if any(k in item for k in ("subject", "from", "body")):
        return "mail"
    if any(k in item for k in ("filename", "creationDate", "latitude")):
        return "photo"
    if any(k in item for k in ("relativePath", "domain")) and _to_str(item.get("name")):
        return "backup"
    return ""


def parse_apple_cloud(data: bytes, kind_hint: str = "") -> list[AppleCloudRecord]:
    """ČISTÝ parser — Apple Cloud JSON → záznamy.

    Args:
        data: Obsah souboru (JSON).
        kind_hint: Volitelný hint podtypu z cesty; prázdně = auto-detekce.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez Apple Cloud záznamů.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[AppleCloudRecord] = []

    def add_contact(item: dict[str, Any]) -> None:
        first = _to_str(item.get("firstName", item.get("givenName")))
        last = _to_str(item.get("lastName", item.get("surname")))
        name = " ".join(x for x in (first, last) if x).strip() or _to_str(
            item.get("name")
        )
        emails = _list_of_str(item.get("emailAddresses", item.get("emails")))
        phones = _list_of_str(item.get("phoneNumbers", item.get("phones")))
        records.append(
            AppleCloudRecord(
                kind="contact",
                name=name or None,
                email=emails[0] if emails else None,
                phone=phones[0] if phones else None,
                detail=", ".join(emails + phones)[:200] or None,
            )
        )

    def add_keychain(item: dict[str, Any]) -> None:
        label = _to_str(item.get("label", item.get("service")))
        account = _to_str(item.get("account"))
        ktype = _to_str(item.get("type")) or ""
        name = f"{label}:{account}" if (label and account) else (label or account)
        records.append(
            AppleCloudRecord(
                kind="keychain",
                name=name,
                detail=ktype[:60] or None,
                created_s=_to_epoch(item.get("created", item.get("modified"))),
            )
        )

    def add_mail(item: dict[str, Any]) -> None:
        subject = _to_str(item.get("subject"))
        sender = _first_str(
            item.get("from"), item.get("sender"), item.get("From")
        )
        recipients = _list_of_str(item.get("to", item.get("recipients")))
        body = _to_str(item.get("body", item.get("textBody")))
        records.append(
            AppleCloudRecord(
                kind="mail",
                name=subject,
                sender=sender,
                recipient=", ".join(recipients)[:200] or None,
                body=(body[:500] if body else None),
                created_s=_to_epoch(item.get("date", item.get("sentDate"))),
            )
        )

    def add_photo(item: dict[str, Any]) -> None:
        fname = _to_str(item.get("filename", item.get("name")))
        records.append(
            AppleCloudRecord(
                kind="photo",
                name=fname,
                size=_to_int(item.get("size")),
                latitude=_to_float(item.get("latitude")),
                longitude=_to_float(item.get("longitude")),
                created_s=_to_epoch(item.get("creationDate", item.get("date"))),
            )
        )

    def add_backup(item: dict[str, Any]) -> None:
        bname = _to_str(item.get("name", item.get("filename")))
        if not bname:
            return
        domain = _to_str(item.get("domain"))
        records.append(
            AppleCloudRecord(
                kind="backup",
                name=bname,
                size=_to_int(item.get("size")),
                path=_to_str(item.get("relativePath", item.get("path"))),
                detail=(domain[:60] if domain else None),
            )
        )

    handlers = {
        "contact": add_contact,
        "keychain": add_keychain,
        "mail": add_mail,
        "photo": add_photo,
        "backup": add_backup,
    }

    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("entries", "items", "contacts", "messages", "photos", "files"):
            val = payload.get(key)
            if isinstance(val, list):
                items.extend(x for x in val if isinstance(x, dict))
        # plochý objekt — jeden záznam
        if not items and any(
            k in payload
            for k in (
                "firstName",
                "label",
                "subject",
                "filename",
                "name",
            )
        ):
            items = [payload]
    elif isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]

    for item in items[:MAX_ITEMS_PER_FILE]:
        kind = (
            kind_hint
            if kind_hint in handlers
            else _detect_kind("", item)
        )
        handler = handlers.get(kind)
        if handler:
            handler(item)

    records = records[:MAX_ITEMS_PER_FILE]
    if not records:
        raise TypeError("Nenalezeny Apple Cloud záznamy")
    return records


def build_apple_cloud_artifacts(records: list[AppleCloudRecord]) -> list[Artifact]:
    """ČISTÁ funkce: z Apple Cloud záznamů vytvoří artifacty."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "apple_cloud", "kind": r.kind}

        if r.kind == "contact":
            title = f"Apple kontakt: {r.name or '(bez jména)'}"[:120]
            if r.email:
                details["email"] = r.email
            if r.phone:
                details["phone"] = r.phone
            artifacts.append(
                Artifact(
                    artifact_type="contact",
                    timestamp=None,
                    title=title,
                    details=details,
                    confidence=0.85 if (r.name and (r.email or r.phone)) else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )

        elif r.kind == "keychain":
            ts = None
            if r.created_s is not None:
                try:
                    ts = from_unix(r.created_s)
                except ValueError:
                    ts = None
            title = f"Apple keychain: {r.name or '(bez jména)'}"[:120]
            if r.detail:
                details["type"] = r.detail
            artifacts.append(
                Artifact(
                    artifact_type="credential",
                    timestamp=ts,
                    title=title,
                    details=details,
                    confidence=0.8 if r.name else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )

        elif r.kind == "mail":
            ts = None
            if r.created_s is not None:
                try:
                    ts = from_unix(r.created_s)
                except ValueError:
                    ts = None
            title = f"Apple e-mail: {r.name or '(bez předmětu)'}"[:120]
            if r.sender:
                details["sender"] = r.sender
            if r.recipient:
                details["recipient"] = r.recipient
            if r.body:
                details["body"] = r.body[:500]
            artifacts.append(
                Artifact(
                    artifact_type="email_message",
                    timestamp=ts,
                    title=title,
                    details=details,
                    confidence=0.85 if (r.name and r.sender) else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )

        elif r.kind == "photo":
            ts = None
            if r.created_s is not None:
                try:
                    ts = from_unix(r.created_s)
                except ValueError:
                    ts = None
            title = f"Apple fotka: {r.name or '(bez názvu)'}"[:120]
            if r.size is not None:
                details["size"] = r.size
            if r.latitude is not None and r.longitude is not None:
                details["latitude"] = r.latitude
                details["longitude"] = r.longitude
            artifacts.append(
                Artifact(
                    artifact_type="document_metadata",
                    timestamp=ts,
                    title=title,
                    details=details,
                    confidence=0.8 if r.name else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )

        elif r.kind == "backup":
            title = f"Apple backup: {r.name or '(bez názvu)'}"[:120]
            if r.size is not None:
                details["size"] = r.size
            if r.path:
                details["path"] = r.path[:200]
            artifacts.append(
                Artifact(
                    artifact_type="file_metadata",
                    timestamp=None,
                    title=title,
                    details=details,
                    confidence=0.8 if r.name else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )

    return artifacts


def extract_apple_cloud_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Apple Cloud JSON → artifacty (podtyp auto)."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("AppleCloud %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    # podtyp hint z cesty (detektor už marker ověřil)
    lower = str(path).lower()
    hint = ""
    for marker, kind in (
        ("contact", "contact"),
        ("keychain", "keychain"),
        ("mail", "mail"),
        ("photo", "photo"),
        ("backup", "backup"),
    ):
        if marker in lower:
            hint = kind
            break

    try:
        records = parse_apple_cloud(data, kind_hint=hint)
    except (ValueError, TypeError) as e:
        logger.debug("AppleCloud %s: %s", path.name, e)
        return []

    return build_apple_cloud_artifacts(records)


def is_apple_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Apple cloud exportu.

    Vyžaduje ``apple``/``icloud`` marker v názvu/cestě + ``.json`` příponu —
    generic ``contacts.json`` bez markery nepadne a TSV/CSV (např. iMessage
    ``[Apple_Request]-MessagesInICloud-1.csv``) se nekrade, protože Apple
    cloud exporty jsou vždy JSON.
    """
    lower = name.lower()
    if not any(m in lower for m in ("apple", "icloud")):
        return False
    if not lower.endswith(".json"):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
