"""ETAPA B vlna 12 — Microsoft Contacts parser (cloud export / warrant return).

AXIOM ekvivalent: ``CloudMicrosoftContactsArtifact``
(``Magnet.Artifacts.Cloud.Microsoft.Contacts.*``) — kontakty z Microsoft
365 / Outlook.com účtu.

Podporovaný formát: **JSON export kontaktů** (defenzivní parsing)::

    [{"displayName": "John Doe", "emailAddresses": ["john@example.com"],
      "phoneNumbers": ["+1555..."]}]

   nebo warrant return s alternativními klíči::

    {"value": [{"name": "Jane Roe", "email": "jane@corp.com",
                "mobilePhone": "+420..." }]}

Jeden kontakt = jeden artifact (``contact``, ``details.engine='ms_contacts'``,
``mimetype='ms:contact'``). Neznámá pole se ignoruje.

Detekce: **name-based** — Microsoft marker (``microsoft``/``outlook``) +
klíčová slova kontaktů; v dispatchi pre-pass na celé cestě PŘED basename
chainem (generic basenames ``contacts.json`` kolidují s Google Contacts WR).
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

MAX_CONTACTS_PER_FILE = 20_000


@dataclass
class MsContactRecord:
    """Jeden Microsoft kontakt."""

    display_name: str | None = None
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


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


def parse_ms_contacts(data: bytes) -> list[MsContactRecord]:
    """ČISTÝ parser — Microsoft contacts JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez kontaktů.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[MsContactRecord] = []

    def add(item: dict[str, Any]) -> None:
        name = _to_str(
            item.get("displayName", item.get("name", item.get("givenName")))
        )
        emails: list[str] = []
        for raw in _as_list(
            item.get("emailAddresses", item.get("emails", item.get("email")))
        ):
            if isinstance(raw, dict):
                addr = _to_str(raw.get("address", raw.get("email")))
            else:
                addr = _to_str(raw)
            if addr:
                emails.append(addr)
        phones: list[str] = []
        for raw in _as_list(
            item.get("phoneNumbers", item.get("phones", item.get("mobilePhone")))
        ):
            if isinstance(raw, dict):
                num = _to_str(raw.get("number", raw.get("phoneNumber")))
            else:
                num = _to_str(raw)
            if num:
                phones.append(num)
        if not name and not emails and not phones:
            return
        records.append(
            MsContactRecord(display_name=name, emails=emails, phones=phones)
        )

    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("value", "contacts", "items", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                items = [x for x in val if isinstance(x, dict)]
                break
        else:
            # jediný objekt s identitou
            if any(k in payload for k in ("displayName", "name", "emailAddresses")):
                add(payload)
    elif isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]

    for item in items[:MAX_CONTACTS_PER_FILE]:
        add(item)

    records = records[:MAX_CONTACTS_PER_FILE]
    if not records:
        raise TypeError("Nenalezeni Microsoft kontakty")
    return records


def build_ms_contact_artifacts(records: list[MsContactRecord]) -> list[Artifact]:
    """ČISTÁ funkce: z kontaktů vytvoří artifacty (contact)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {
            "engine": "ms_contacts",
            "mimetype": "ms:contact",
        }
        if r.emails:
            details["emails"] = r.emails
        if r.phones:
            details["phones"] = r.phones

        display = r.display_name or (r.emails[0] if r.emails else "?")
        title = f"Microsoft Contact: {display}"
        artifacts.append(
            Artifact(
                artifact_type="contact",
                timestamp=None,
                title=title[:120],
                details=details,
                confidence=0.7 if r.display_name else 0.5,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_ms_contact_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Microsoft contacts JSON → contact artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("MsContacts %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_ms_contacts(data)
    except (ValueError, TypeError) as e:
        logger.debug("MsContacts %s: %s", path.name, e)
        return []

    return build_ms_contact_artifacts(records)


def is_ms_contacts_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Microsoft contacts exportu.

    Vyžaduje Microsoft marker (``microsoft``/``outlook``) v názvu/cestě +
    klíčová slova kontaktů — generic ``contacts.json`` bez markery nepadne,
    aby se nekradl Google Contacts WR.
    """
    lower = name.lower()
    if not any(k in lower for k in ("microsoft", "outlook")):
        return False
    if not any(k in lower for k in ("contact",)):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
