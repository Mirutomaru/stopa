"""ETAPA B vlna 7 — Google Chrome Autofill / Contact Info Warrant Return parser.

AXIOM ekvivalenty: ``GoogleChromeAutofillWarrantReturnArtifact`` +
``GoogleChromeContactInfoWarrantReturnArtifact`` +
``CloudGoogleChromeAutofillArtifact``.

Podporovaný formát: **Chrome Autofill / Contact Info warrant return JSON** —
pole záznamů vyplňovaných formulářů (adresy, karty, kontakty)::

    [{"name": "Jan Novák", "email": "jan@example.com",
      "phoneNumber": "+420123456789",
      "addressLine1": "Hlavní 1", "city": "Brno", "countryCode": "CZ"}, ...]

   Chrome Autofill exportuje kontakty/adresy jako ploché pole objektů.
   Jeden záznam = jeden artifact (``autofill_entry``). Neznámá pole se
   ignorují; prázdné záznamy (bez jména i e-mailu) se vynechávají.

Detekce: **name-based** (``autofill``, ``contact_info``, ``chrome_autofill``)
+ content check (JSON s autofill klíči).

Artifact type: ``autofill_entry`` — jeden záznam = jeden artifact.
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

MAX_ENTRIES_PER_FILE = 5_000


@dataclass
class AutofillRecord:
    """Jeden záznam Chrome Autofill / Contact Info."""

    name: str = ""
    email: str = ""
    phone: str = ""
    address_line1: str = ""
    city: str = ""
    country_code: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _s(value: Any) -> str:
    """Tolerantní string extrakce (string / pole stringů)."""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, list):
        for item in value:
            s = _s(item)
            if s:
                return s
        return ""
    return str(value).strip()


def parse_chrome_autofill(data: bytes) -> list[AutofillRecord]:
    """ČISTÝ parser — Chrome Autofill / Contact Info JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne pole/objekt se záznamy.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    if isinstance(payload, dict):
        for key in ("autofill", "contacts", "items", "records"):
            v = payload.get(key)
            if isinstance(v, list):
                payload = v
                break
        else:
            # jediný objekt s autofill klíči → zabal do pole
            if any(k in payload for k in ("name", "email", "phoneNumber")):
                payload = [payload]
    if not isinstance(payload, list):
        raise TypeError("Očekáváno JSON pole autofill záznamů")

    records: list[AutofillRecord] = []
    for item in payload[:MAX_ENTRIES_PER_FILE]:
        if not isinstance(item, dict):
            continue

        name = _s(item.get("name", item.get("fullName")))
        email = _s(item.get("email", item.get("emailAddress")))
        phone = _s(
            item.get("phoneNumber", item.get("phone", item.get("mobileNumber")))
        )
        address_line1 = _s(
            item.get("addressLine1", item.get("street", item.get("address")))
        )
        city = _s(item.get("city"))
        country_code = _s(item.get("countryCode", item.get("country")))

        # prázdný záznam (bez jména i e-mailu) — vynechat
        if not name and not email:
            continue

        extra: dict[str, Any] = {}
        for key in ("organizationName", "jobTitle", "postalCode"):
            v = _s(item.get(key))
            if v:
                extra[key] = v

        records.append(
            AutofillRecord(
                name=name,
                email=email,
                phone=phone,
                address_line1=address_line1,
                city=city,
                country_code=country_code,
                extra=extra,
            )
        )
    return records


def is_chrome_autofill_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Chrome Autofill / Contact Info exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("autofill", "contact_info", "contactinfo", "chrome_contact")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"[", b"{")):
            return False
        joined = head[:2048].lower()
        markers = (b"phonenumber", b"addressline1", b"email")
        if not any(k in joined for k in markers):
            return False
    return True


def build_autofill_artifacts(records: list[AutofillRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (autofill_entry)."""
    artifacts: list[Artifact] = []
    for r in records:
        label = r.name or r.email[:50] or "autofill"
        title = f"Chrome Autofill: {label}"

        details: dict[str, Any] = {"engine": "chrome_autofill"}
        if r.name:
            details["name"] = r.name
        if r.email:
            details["email"] = r.email
        if r.phone:
            details["phone"] = r.phone
        if r.address_line1:
            details["address"] = r.address_line1
        if r.city:
            details["city"] = r.city
        if r.country_code:
            details["country"] = r.country_code
        if r.extra:
            details.update(r.extra)

        artifacts.append(
            Artifact(
                artifact_type="autofill_entry",
                timestamp=None,  # snapshot autofill bez času
                title=title[:120],
                details=details,
                confidence=0.8 if (r.name and r.email) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_chrome_autofill_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Chrome Autofill JSON → autofill_entry artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("ChromeAutofill %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_chrome_autofill(data)
    except (ValueError, TypeError) as e:
        logger.debug("ChromeAutofill %s: %s", path, e)
        return []

    return build_autofill_artifacts(records)
