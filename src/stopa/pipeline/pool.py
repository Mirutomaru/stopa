"""Paralelní zpracování souborů — pool worker procesy/vlákna.

P1-4 vlna D: vyčleněno z monolitu ``pipeline.py``; moduly stavu
_POOL_PROFILE/_POOL_SETS je zde (global statement v _pool_init).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from stopa.data.ingest import WalkedFile
from stopa.domain.bad_extension import extension_of, is_bad_extension
from stopa.domain.hashing import hash_bytes, hash_file
from stopa.domain.signatures import detect_signature
from stopa.models import Artifact, FileRecord, ProcessingProfile

from .dispatch import _extract_artifacts_for
from .extractors import _read_head


@dataclass
class _FileWork:
    """E3 paralelizace: výsledek worker vlákna pro jeden soubor (bez DB).

    DB writes + dedupe zůstávají v hlavním vlákně — pořadí zpracování určuje
    originál vs. duplikát (FTK hide duplicates), takže musí být deterministické.
    """

    rec: FileRecord
    artifacts: list[Artifact] = field(default_factory=list)
    parser_version: str | None = None
    error: str | None = None  # hashing OSError — soubor se upsertuje bez hashů


_POOL_PROFILE: ProcessingProfile | None = None


_POOL_SETS: dict[str, set[str]] = {}


def _pool_init(profile: ProcessingProfile, normalized_sets: dict[str, set[str]]) -> None:
    """Initializer ProcessPoolExecutor — nastaví sdílený stav worker procesu."""
    global _POOL_PROFILE, _POOL_SETS
    _POOL_PROFILE = profile
    _POOL_SETS = normalized_sets


def _process_file_task(wf: WalkedFile, abs_path_str: str, source_id: str) -> _FileWork:
    """Task pro ProcessPoolExecutor — čte profile/sets z globálů worker procesu.

    Top-level funkce (picklovatelná po referenci); `abs_path` je string, aby se
    v child procesu nemuselo řešit picklování Path přes procesy.
    """
    assert _POOL_PROFILE is not None  # nastaveno _pool_init (initializer)
    return _process_file_worker(wf, Path(abs_path_str), source_id, _POOL_PROFILE, _POOL_SETS)


def _process_file_worker(
    wf: WalkedFile,
    abs_path: Path,
    source_id: str,
    profile: ProcessingProfile,
    normalized_sets: dict[str, set[str]],
) -> _FileWork:
    """Hashing + signatura + bad ext + hash sets + artifact extraktoři (bez DB).

    Drahé operace (disk IO + CPU hashing + parsery) běží v worker vláknech;
    ``hashlib`` i ``sqlite3`` uvolňují GIL, takže se vláknům reálně překrývají.
    """
    rec = FileRecord(
        source_id=source_id,
        rel_path=wf.rel_path,
        name=wf.name,
        size_bytes=wf.size_bytes,
        mtime=wf.mtime,
        ctime=wf.ctime,
        atime=wf.atime,
    )

    # ── hashing podle profilu ────────────────────────────
    algs: list[str] = []
    if profile.compute_md5:
        algs.append("md5")
    if profile.compute_sha1:
        algs.append("sha1")
    if profile.compute_sha256:
        algs.append("sha256")
    if profile.compute_sha512:  # STP-022 — SHA-512 (forensic profil)
        algs.append("sha512")
    hash_error: str | None = None
    try:
        if algs and wf.size_bytes > 0:
            digests = hash_file(abs_path, algs)
            rec.md5 = digests.get("md5")
            rec.sha256 = digests.get("sha256")
            rec.sha512 = digests.get("sha512")
        elif algs:  # prázdný soubor — platné prázdné digesty
            digests = hash_bytes(b"", algs)
            rec.md5 = digests.get("md5")
            rec.sha256 = digests.get("sha256")
            rec.sha512 = digests.get("sha512")
    except OSError as e:
        # hashing selhal (IO) — soubor se upsertuje bez hashů, ale signatura +
        # artifacts se zkouší dál (původní sekvenční chování — IO chyba nemusí
        # znemožnit čtení hlavičky / parsery).
        hash_error = f"{wf.rel_path}: {e}"

    # ── signatura (magic bytes) ──────────────────────────
    if profile.signature_analysis and wf.size_bytes > 0:
        sig = detect_signature(_read_head(abs_path))
        if sig is not None:
            rec.signature_type, _family = sig

    # ── bad extension (FTK Flag Bad Extensions) ─────────
    rec.extension = extension_of(wf.name)
    if profile.flag_bad_extensions and rec.signature_type is not None:
        rec.bad_extension = is_bad_extension(rec.signature_type, wf.name)

    # ── known-bad hash sets (FTK) — MD5 i SHA-256 sety ───
    if profile.match_hash_sets and normalized_sets:
        for digest in (rec.sha256, rec.md5):
            if digest is None:
                continue
            for name, hashes in normalized_sets.items():
                if digest.lower() in hashes:
                    rec.hash_set_hit = name
                    break
            if rec.hash_set_hit:
                break

    # ── artifact extraktoři (AXIOM-style) — signatura → extraktor (+ name fallback) ──
    arts: list[Artifact] = []
    parser_ver: str | None = None
    if profile.extract_artifacts:
        arts, parser_ver = _extract_artifacts_for(
            abs_path, rec.signature_type, crypto_scan=profile.crypto_scan
        )

    return _FileWork(
        rec=rec, artifacts=arts, parser_version=parser_ver, error=hash_error
    )
