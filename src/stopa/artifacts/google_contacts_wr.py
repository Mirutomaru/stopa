"""ETAPA B vlna 7 — Google Contacts Warrant Return parser.

AXIOM ekvivalenty: ``GoogleContactsWarrantReturnArtifact`` +
``CloudGoogleContactsArtifact``.

Podporovaný formát: **Google Contacts Takeout / warrant return JSON** — pole
kontaktů::

    [{"name": ["Jan Novák"], "givenName": ["Jan"], "familyName": ["Novák"],
      "emails": [{"label": ["home"], "value": "jan@example.com"}],
      "phoneNumbers": [{"label": ["mobile"], "value": "+420123456789"}]}, ...]

   Takeout formát používá **pole stringů** pro jména (``name: ["Jan Novák"]``)
   a objekty s ``label``/``value`` pro e-maily/telefony. People API varianta
   (objekty s ``displayName``/``value``) je podporována tolerantně. Jeden
   kontakt = jeden artifact (``contact``).

Detekce: **name-based** (``contacts``, ``google_contacts``) + content check
(JSON s ``givenName``/``emails``/``phoneNumbers`` klíči).

Artifact type: ``contact`` — jeden kontakt = jeden artifact.
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

MAX_CONTACTS_PER_FILE = 10_000


@dataclass
class ContactRecord:
    """Jeden záznam Google Contacts."""

    display_name: str = ""
    given_name: str = ""
    family_name: str = ""
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


def _first_str(value: Any) -> str:
    """První string z pole/objektu/hodnoty — tolerantní extrakce."""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, list):
        for item in value:
            s = _first_str(item)
            if s:
                return s
        return ""
    if isinstance(value, dict):
        # People API objekt — zkus známé klíče
        for key in ("displayName", "value", "formattedValue"):
            s = _first_str(value.get(key))
            if s:
                return s
        return ""
    return str(value).strip()


def _extract_labeled_list(items: Any) -> list[str]:
    """Extrahuje hodnoty z pole label/value objektů (Takeout contacts)."""
    out: list[str] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if isinstance(item, dict):
            v = _first_str(item.get("value"))
            if v and v not in out:
                out.append(v)
        elif isinstance(item, str) and item.strip() and item.strip() not in out:
            out.append(item.strip())
    return out


def parse_contacts_wr(data: bytes) -> list[ContactRecord]:
    """ČISTÝ parser — Google Contacts JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne pole/objekt s kontakty.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    if isinstance(payload, dict):
        for key in ("contacts", "people", "items", "records"):
            v = payload.get(key)
            if isinstance(v, list):
                payload = v
                break
        else:
            # jediný objekt s contact klíči → zabal do pole
            if any(k in payload for k in ("givenName", "emails", "phoneNumbers")):
                payload = [payload]
    if not isinstance(payload, list):
        raise TypeError("Očekáváno JSON pole kontaktů")

    records: list[ContactRecord] = []
    for item in payload[:MAX_CONTACTS_PER_FILE]:
        if not isinstance(item, dict):
            continue

        display_name = _first_str(
            item.get("name", item.get("displayName", item.get("resourceName")))
        )
        given_name = _first_str(item.get("givenName"))
        family_name = _first_str(item.get("familyName"))

        # People API fallback — names[0].displayName
        if not display_name:
            names = item.get("names")
            if isinstance(names, list) and names:
                display_name = _first_str(names[0])

        emails = _extract_labeled_list(item.get("emails", item.get("emailAddresses")))
        phones = _extract_labeled_list(
            item.get("phoneNumbers", item.get("phones"))
        )

        extra: dict[str, Any] = {}
        for key in ("organizationName", "jobTitle"):
            v = _first_str(item.get(key))
            if v:
                extra[key] = v

        records.append(
            ContactRecord(
                display_name=display_name or given_name or (emails[0] if emails else ""),
                given_name=given_name,
                family_name=family_name,
                emails=emails,
                phones=phones,
                extra=extra,
            )
        )
    return records


def is_contacts_wr_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Google Contacts exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("contact", "google_contact")):
        return False
    # vyhnout se kolizi s lokálními contacts DB (SQLite) a Samsung contacts2
    if lower.endswith((".db", ".sqlite", ".sqlite3")) or "contacts2" in lower:
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"[", b"{")):
            return False
        joined = head[:2048].lower()
        markers = (b"givename", b"emails", b"phonenumber")
        if not any(k in joined for k in markers):
            return False
    return True


def build_contact_artifacts(records: list[ContactRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (contact)."""
    artifacts: list[Artifact] = []
    for r in records:
        label = r.display_name or "kontakt"
        title = f"Google Contact: {label}"

        details: dict[str, Any] = {"engine": "google_contacts_wr"}
        if r.given_name:
            details["given_name"] = r.given_name
        if r.family_name:
            details["family_name"] = r.family_name
        if r.emails:
            details["emails"] = r.emails[:10]
        if r.phones:
            details["phones"] = r.phones[:10]
        if r.extra:
            details.update(r.extra)

        artifacts.append(
            Artifact(
                artifact_type="contact",
                timestamp=None,  # snapshot kontaktů bez času
                title=title[:120],
                details=details,
                confidence=0.8 if (r.display_name and (r.emails or r.phones)) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_contacts_wr_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Google Contacts JSON → contact artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("ContactsWR %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_contacts_wr(data)
    except (ValueError, TypeError) as e:
        logger.debug("ContactsWR %s: %s", path, e)
        return []

    return build_contact_artifacts(records)
