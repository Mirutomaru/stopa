"""ETAPA B vlna 4 — OpenOffice/LibreOffice Base (.odb) parser (ZIP kontejner).

AXIOM ekvivalent: ``OpenOfficeBaseArtifact`` (Magnet.Artifacts.dll) — metadata
databázového dokumentu OpenDocument Base. Zdroj: soubor ``*.odb``, který je
ZIP archívem (OpenDocument kontejner) obsahujícím ``mimetype``,
``META-INF/manifest.xml`` a ``content.xml`` s DC metadaty.

Formát: ZIP → ``mimetype`` = ``application/vnd.oasis.opendocument.base``;
metadata z ``content.xml`` (namespace dc: title, creator, date). Čistá funkce
``build_openoffice_base_artifacts()`` nad metadata dictem; IO entrypoint
``extract_openoffice_base_artifacts(path)`` s defenzivním try/except.

Artifact type: ``document_metadata`` (AXIOM OpenOfficeBase).
"""

from __future__ import annotations

import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

# OpenDocument Base mimetype (přesný řetězec v ZIP kontejneru)
_ODF_BASE_MIMETYPE = "application/vnd.oasis.opendocument.base"

# DC metadata namespace (Dublin Core — standardní pro ODF)
_DC_NS = "{http://purl.org/dc/elements/1.1/}"


def is_openoffice_base_file(name: str) -> bool:
    """Name-based detekce — OpenOffice/LibreOffice Base databáze (.odb)."""
    return name.lower().endswith(".odb")


def _parse_odf_date(raw: str | None) -> datetime | None:
    """Defenzivní parsování ODF data (ISO 8601) → aware UTC datetime."""
    if not raw:
        return None
    try:
        # ISO 8601 — zkus fromisoformat, případně ruční fallback pro 'Z'
        s = raw.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        logger.debug("OpenOfficeBase date parse failed: %r", raw)
        return None


def _read_metadata(zf: zipfile.ZipFile) -> dict[str, Any]:
    """Extrahuje DC metadata z content.xml (title/creator/date)."""
    meta: dict[str, Any] = {}
    try:
        with zf.open("content.xml") as fh:
            tree = ET.parse(fh)
    except (KeyError, ET.ParseError, OSError):
        return meta

    root = tree.getroot()
    for tag in ("title", "creator", "date"):
        el = root.find(f".//{_DC_NS}{tag}")
        if el is not None and el.text:
            meta[tag] = el.text.strip()
    return meta


def build_openoffice_base_artifacts(meta: dict[str, Any]) -> list[Artifact]:
    """ČISTÁ funkce: metadata dict → document_metadata artifact."""
    title = meta.get("title") or "(bez názvu)"
    creator = meta.get("creator", "")
    created = _parse_odf_date(meta.get("date"))

    details: dict[str, Any] = {
        "engine": "openoffice_base",
        "format": "opendocument.base (ZIP)",
        "mimetype": _ODF_BASE_MIMETYPE,
    }
    if creator:
        details["creator"] = creator

    return [
        Artifact(
            artifact_type="document_metadata",
            timestamp=created,
            title=f"OpenOffice Base: {title[:120]}",
            details=details,
            confidence=0.75,
            parser_version=PARSER_VERSION,
        )
    ]


def extract_openoffice_base_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — .odb (ZIP/ODF Base) → document_metadata artifact."""
    try:
        with zipfile.ZipFile(path) as zf:
            # ODF kontejner musí mít 'mimetype' jako první položku
            names = set(zf.namelist())
            if "content.xml" not in names and "META-INF/manifest.xml" not in names:
                logger.debug("OpenOfficeBase %s: not an ODF container", path)
                return []

            # Potvrzení, že jde o Base (ne Writer/Calc) — přesný mimetype
            is_base = False
            try:
                with zf.open("mimetype") as fh:
                    mt = fh.read(256).decode("utf-8", errors="replace").strip()
                is_base = mt == _ODF_BASE_MIMETYPE
            except (KeyError, OSError):
                pass  # mimetype chybí — spolehneme se na .odb extenzi

            meta = _read_metadata(zf)
            if not is_base and not meta:
                logger.debug("OpenOfficeBase %s: no base marker + no metadata", path)
                return []

            arts = build_openoffice_base_artifacts(meta)
            # Přidat poznámku, zda šlo o potvrzený Base nebo jen .odb kontejner
            if not is_base:
                arts[0].details["note"] = "ODF container (mimetype != base)"
            return arts
    except zipfile.BadZipFile as exc:
        logger.warning("OpenOfficeBase bad zip %s: %s", path, exc)
        return []
    except Exception as exc:  # noqa: BLE001 — defenzivní IO, ne výjimka nahoru
        logger.error("Chyba při parsingu OpenOffice Base %s: %s", path, exc)
        return []
