"""STOPA — unifikovaná forenzní workbench.

Moduly:
- models        : Pydantic v2 boundary modely (Case, EvidenceSource, FileRecord, ProcessingProfile)
- domain/       : ČISTÁ logika — bez sítě, bez UI, 100% offline testovatelná
    signatures      : detekce reálného typu podle magic bytes (FTK file signature analysis)
    bad_extension   : FTK „Flag Bad Extensions“ — rozpor mezi signaturou a příponou
    dedupe          : FTK „Advanced De-duplication Analysis“ — duplikáty podle hash
    hashing         : chunked MD5/SHA-1/SHA-256 s progress callbackem
    profiles        : vestavěné FTK-style processing profily (Forensic/eDiscovery/Quick)
- data/         : SQLite case DB + ingest (jediná vrstva dotýkající se disku)
- pipeline.py   : jediný analyze() entrypoint sdílený CLI i web GUI
- presentation/ : verziované JSON exporty + textové formátory
- cli.py        : argparse subpříkazy
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """Deterministicky čitelné ID s prefixem (forenzní stopa v logech)."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class Case(BaseModel):
    """Forenzní případ — ekvivalent AXIOM case file / FTK case."""

    id: str = Field(default_factory=lambda: new_id("case"))
    name: str
    created_at: datetime = Field(default_factory=_utcnow)
    examiner: str | None = None
    notes: str | None = None
    # E2 Timeline Engine: lokální časové pásmo pro zobrazení timeline (default Praha).
    timezone_name: str = "Europe/Prague"


class EvidenceSource(BaseModel):
    """Zdroj důkazů — složka, soubor nebo raw obraz (AXIOM evidence source)."""

    id: str = Field(default_factory=lambda: new_id("src"))
    case_id: str
    kind: Literal["folder", "file"]
    path: str
    size_bytes: int | None = None
    added_at: datetime = Field(default_factory=_utcnow)


class FileRecord(BaseModel):
    """Jeden soubor v případu — FTK-style záznam s hashi, signaturou a deduplikací."""

    id: str = Field(default_factory=lambda: new_id("file"))
    source_id: str
    rel_path: str  # cesta relativní ke kořeni zdroje (forward slashes)
    name: str
    size_bytes: int
    mtime: datetime | None = None
    ctime: datetime | None = None
    atime: datetime | None = None
    sha256: str | None = None
    md5: str | None = None
    signature_type: str | None = None  # kanonický typ z magic bytes (None = neznámá)
    extension: str | None = None
    bad_extension: bool = False  # FTK Flag Bad Extensions
    is_duplicate_of: str | None = None  # FTK Advanced De-duplication
    hash_set_hit: str | None = None  # název known-bad hash setu, pokud hash sedí (FTK)
    meta_addr: str | None = None  # TSK metadata adresa (icat) — pro soubory v diskovém obrazu


class ProcessingProfile(BaseModel):
    """FTK-style processing options — co se při ingestu počítá."""

    name: str
    compute_md5: bool = True
    compute_sha1: bool = False
    compute_sha256: bool = True
    signature_analysis: bool = True  # magic bytes → reálný typ
    flag_bad_extensions: bool = True  # rozpor signatura × přípona
    deduplicate: bool = True  # duplikáty podle hash
    match_hash_sets: bool = True  # porovnání s known-bad hash sety
    extract_artifacts: bool = True  # AXIOM-style artifact extraktoři (SQLite, …)


class Artifact(BaseModel):
    """Extrahovaný forenzní artefakt — AXIOM-style záznam (browser history, chat, call log…)."""

    id: str = Field(default_factory=lambda: new_id("art"))
    source_id: str | None = None  # pipeline doplní po extrakci (extraktor nezná kontext)
    file_id: str | None = None  # FileRecord.id, pokud artifact pochází ze souboru
    rel_path: str | None = None  # denormalizováno pro zobrazení v timeline
    artifact_type: str  # např. "browser_history", "chat_message", "sqlite_database"
    timestamp: datetime | None = None
    title: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    # E2 Timeline Engine — provenience + důvěryhodnost (reprodukovatelnost analýzy):
    confidence: float | None = None  # 0.0–1.0 — jak moc lze timestampu/resultu věřit
    parser_version: str | None = None  # verze extraktoru, který artifact vygeneroval
    extracted_at: datetime | None = None  # kdy byl artifact extrahován (UTC) — odliší se od event time
    anomaly_flags: list[str] = Field(default_factory=list)  # E2: detekované nesrovnalosti (kanonické flagy)


class ProcessResult(BaseModel):
    """Výsledek zpracování jednoho zdroje (FTK processing summary)."""

    source_id: str
    profile: str
    files_total: int = 0
    bytes_total: int = 0
    hashed_md5: int = 0
    hashed_sha256: int = 0
    signatures_detected: int = 0
    bad_extensions: int = 0
    duplicates: int = 0
    hash_set_hits: int = 0
    artifacts_extracted: int = 0
    errors: list[str] = Field(default_factory=list)
