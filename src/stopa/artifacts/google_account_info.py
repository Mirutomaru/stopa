"""ETAPA B vlna 2 — Google Account Info parser (lokální profil / Takeout).

AXIOM ekvivalent: ``GoogleAccountInfoArtifact``
(``Magnet.Artifacts.Cloud.Google.WarrantReturn.GoogleAccountInfoArtifact``).

Podporovaný formát: **JSON** s informacemi o účtu (``account_info.json``,
``profile.json`` z Google Takeout / warrant return)::

    {"name": "Jan Novák", "emailAddress": "jan@example.com",
     "phoneNumber": "+420123456789", ...}

Detekce: **name-based** (``account_info``, ``profile.json`` v kontextu Google)
+ content check (JSON objekt s klíči name/emailAddress/phoneNumber).

Artifact type: ``google_account`` — jeden účet = jeden artifact.
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


@dataclass
class GoogleAccountInfo:
    """Informace o Google účtu."""

    name: str = ""
    email: str = ""
    phone: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# známé klíče → normalizované pole (case-insensitive prefix matching)
_FIELD_MAP = {
    "name": ("name",),
    "email": ("emailaddress", "email"),
    "phone": ("phonenumber", "phone"),
}


def parse_account_info(data: bytes) -> GoogleAccountInfo | None:
    """ČISTÝ parser — Account Info JSON → info (prázdný → None).

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne objekt.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    if not isinstance(payload, dict):
        raise TypeError("Očekáván JSON objekt")

    # normalizace klíčů — lowercase bez mezer/podtržítek pro matching
    norm = {str(k).lower().replace("_", "").replace(" ", ""): v for k, v in payload.items()}

    info = GoogleAccountInfo()
    for target, keys in _FIELD_MAP.items():
        for key in keys:
            if key in norm and isinstance(norm[key], (str, int)):
                setattr(info, target, str(norm[key]).strip())
                break

    # zbývající pole do extra (bez interních klíčů)
    known = set()
    for keys in _FIELD_MAP.values():
        known.update(keys)
    info.extra = {k: v for k, v in norm.items() if k not in known and isinstance(v, (str, int))}

    # bez jakéhokoli identifikátoru to není account info
    if not (info.name or info.email or info.phone):
        return None

    return info


def is_account_info_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Google Account Info exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("account_info", "accountinfo")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        markers = (b"name", b"emailaddress", b"phonenumber")
        if not h.startswith(b"{"):
            return False
        if not any(m in h for m in markers):
            return False
    return True


def build_account_artifacts(info: GoogleAccountInfo) -> list[Artifact]:
    """ČISTÁ funkce: z account info vytvoří artifact (google_account)."""
    title = "Google account: " + (info.name or info.email or info.phone)[:100]

    details: dict[str, Any] = {
        "engine": "google_takeout",
        "name": info.name,
        "email": info.email,
        "phone": info.phone,
    }
    if info.extra:
        details["extra"] = info.extra

    return [
        Artifact(
            artifact_type="google_account",
            timestamp=None,  # account info nemá čas (snapshot profilu)
            title=title[:120],
            details=details,
            confidence=0.9 if (info.email or info.name) else 0.7,
            parser_version=PARSER_VERSION,
        )
    ]


def extract_account_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Google Account Info → google_account artifacty.

    Chyby (poškozený soubor, IO) → log + prázdný výsledek, nikdy ne výjimka.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("AccountInfo %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        info = parse_account_info(data)
    except (ValueError, TypeError) as e:
        logger.debug("AccountInfo %s: %s", path, e)
        return []

    if info is None:
        return []

    return build_account_artifacts(info)
