"""E8 — file metadata pipeline wrapper (PDF + OOXML docProps).

STP-075 / vlna 31 (design §7 pilot vlna 2): zaregistrová E8 doménovou
utilitu ``stopa.domain.file_meta.extract_metadata`` do artifact pipeline.
Dispatch je name-based (AXIOM Hunter pattern — stejné jako icloud_messages/
win_jumplist), protože pro extrakční stupeň pipeline nepotřebujeme vlastní
magic: obsahový dispatch (%PDF / PK / ID3 / ftyp) běží v doméně.

Artifact typ: ``document_metadata`` (stejná rodina jako openoffice_base).
Details = normalizovaná metadata pole + ``name``; klíč ``engine`` značí
provenience extrakce pro timeline zobrazení.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from stopa.domain.file_meta import extract_metadata
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

#: Strop čtených bajtů — metadata sedí na začátku souboru; PDF /Info skenuje
#: celou načtenou plochu (shoda s E8 web endpointem).
META_MAX_BYTES: int = 32 * 1024 * 1024

#: Name-based dispatch — přípony s obsahovým dispatchem v doméně.
_FILE_META_EXTS = frozenset({".pdf", ".docx", ".xlsx", ".pptx"})


def is_file_meta_file(name: str) -> bool:
    """Name detektor pro pipeline dispatch (AXIOM Hunter pattern)."""
    lower = name.lower()
    return any(lower.endswith(ext) for ext in _FILE_META_EXTS)


def build_file_meta_artifacts(meta: dict[str, str], filename: str) -> list[Artifact]:
    """Čistá funkce — normalizovaná metadata → document_metadata artifact.

    Prázdná metadata (neznámý/poškozený obsah) → ``[]`` (žádný artifact).
    Timestamp = pole ``created`` při parsabilním ISO tvaru, jinak ``None``
    (defenzivní — EXIF dává např. "2026:03:15 14:30:00").
    """
    if not meta:
        return []

    created: datetime | None = None
    raw_created = meta.get("created")
    if raw_created:
        try:
            created = datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
        except ValueError:
            created = None  # neparsabilní tvar — metadata zůstanou v details

    details: dict[str, str] = {"engine": "file_meta", "name": filename} | meta
    title_doc = str(meta.get("title") or filename)
    return [
        Artifact(
            artifact_type="document_metadata",
            timestamp=created,
            title=f"Document: {title_doc[:120]}",
            details=details,
            confidence=0.75,
            parser_version=PARSER_VERSION,
        )
    ]


def extract_file_meta_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — PDF/OOXML → document_metadata artifact."""
    try:
        with path.open("rb") as fh:
            data = fh.read(META_MAX_BYTES + 1)
        if len(data) > META_MAX_BYTES:
            logger.debug("file_meta %s: soubor přes strop, trunc na 32 MiB", path)
            data = data[:META_MAX_BYTES]
    except OSError as exc:
        logger.error("file_meta %s: chyba čtení: %s", path, exc)
        return []

    meta = extract_metadata(data, path.name)
    return build_file_meta_artifacts(meta, path.name)
