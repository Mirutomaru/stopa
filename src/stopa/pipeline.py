"""STOPA pipeline — jediný analyze() entrypoint sdílený CLI i web GUI.

Postup (FTK-style processing):
1. walk zdroje → WalkedFile záznamy
2. pro každý soubor: hashy podle profilu + signatura (magic bytes)
3. bad extension check, dedupe napříč případem, known-bad hash sets
4. upsert do case DB + ProcessResult summary

Jeden kódový průchod pro CLI i web — jedna cesta k debugování.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from stopa.artifacts.plist_extract import extract_plist_artifacts
from stopa.artifacts.registry_extract import extract_registry_artifacts
from stopa.artifacts.sqlite_extract import extract_sqlite_artifacts
from stopa.artifacts.sqlite_recover import recover_deleted_rows
from stopa.data.db import CaseDB
from stopa.data.ingest import walk_source
from stopa.domain.bad_extension import extension_of, is_bad_extension
from stopa.domain.dedupe import Deduper
from stopa.domain.hashing import hash_bytes, hash_file
from stopa.domain.profiles import get_profile
from stopa.domain.signatures import detect_signature
from stopa.models import Artifact, FileRecord, ProcessResult

log = logging.getLogger("stopa.pipeline")

SIGNATURE_HEAD_BYTES = 65536  # stačí pro všechny signatury v hlavičce


def _extract_sqlite_all(path: Path) -> list[Artifact]:
    """SQLite — aktivní řádky (schema matchery) + carving smazaných (.db + .wal).

    Obě cesty jsou nezávislé; jedna selže → log + prázdný výsledek, druhá běží dál.
    """
    arts = extract_sqlite_artifacts(path)
    try:
        arts.extend(recover_deleted_rows(path))
    except Exception as e:  # noqa: BLE001 — carving je bonus, nesmí potopit extrakci
        log.warning("SQLite recover %s: %s", path, e)
    return arts


# signatura → extraktor (AXIOM-style artifact engine). Nový typ = nový řádek.
ARTIFACT_EXTRACTORS: dict[str, Callable[[Path], list]] = {
    "sqlite": _extract_sqlite_all,
    "registry_hive": extract_registry_artifacts,
    "plist": extract_plist_artifacts,
}


def _read_head(path: Path) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read(SIGNATURE_HEAD_BYTES)
    except OSError as e:
        log.warning("signatura — nelze číst %s: %s", path, e)
        return b""


def process_source(
    db: CaseDB,
    source_id: str,
    root: Path,
    profile_name: str = "forensic",
    hash_sets: dict[str, set[str]] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ProcessResult:
    """Zpracuje jeden evidence source daným processing profilem.

    `hash_sets` — {název_setu: množina_hashů} (FTK known-bad sets; malá hex).
    `progress` — callback (soubory_hotovo, souborů_celkem) po každém souboru.
    """
    profile = get_profile(profile_name)
    result = ProcessResult(source_id=source_id, profile=profile.name)

    walked = walk_source(root)
    total = len(walked)
    if progress is not None:
        progress(0, total)

    # dedupe napříč celým případem — seed z DB (jiné zdroje / předchozí běhy)
    # oba hashy: SHA-256 profily i MD5-only (FTK eDiscovery)
    deduper = Deduper()
    existing = db.conn.execute("SELECT sha256, md5, rel_path FROM files").fetchall()
    deduper.seed(
        [(r["sha256"], r["rel_path"]) for r in existing]
        + [(r["md5"], r["rel_path"]) for r in existing]
    )

    # hash sets — normalizace na malá hex pro rychlé porovnání
    normalized_sets: dict[str, set[str]] = {}
    if profile.match_hash_sets and hash_sets:
        for name, hashes in hash_sets.items():
            normalized_sets[name] = {h.lower() for h in hashes}

    root_resolved = root.resolve()

    for i, wf in enumerate(walked):
        abs_path = root_resolved / wf.rel_path if not root.is_file() else root_resolved
        rec = FileRecord(
            source_id=source_id,
            rel_path=wf.rel_path,
            name=wf.name,
            size_bytes=wf.size_bytes,
            mtime=wf.mtime,
            ctime=wf.ctime,
            atime=wf.atime,
        )
        result.files_total += 1
        result.bytes_total += wf.size_bytes

        # ── hashing podle profilu ────────────────────────────
        algs: list[str] = []
        if profile.compute_md5:
            algs.append("md5")
        if profile.compute_sha1:
            algs.append("sha1")
        if profile.compute_sha256:
            algs.append("sha256")
        try:
            if algs and wf.size_bytes > 0:
                digests = hash_file(abs_path, algs)
                rec.md5 = digests.get("md5")
                rec.sha256 = digests.get("sha256")
                result.hashed_md5 += int(rec.md5 is not None)
                result.hashed_sha256 += int(rec.sha256 is not None)
            elif algs:  # prázdný soubor — platné prázdné digesty
                digests = hash_bytes(b"", algs)
                rec.md5 = digests.get("md5")
                rec.sha256 = digests.get("sha256")
                result.hashed_md5 += int(rec.md5 is not None)
                result.hashed_sha256 += int(rec.sha256 is not None)
        except OSError as e:
            result.errors.append(f"{wf.rel_path}: {e}")

        # ── signatura (magic bytes) ──────────────────────────
        if profile.signature_analysis and wf.size_bytes > 0:
            sig = detect_signature(_read_head(abs_path))
            if sig is not None:
                rec.signature_type, _family = sig
                result.signatures_detected += 1

        # ── bad extension (FTK Flag Bad Extensions) ─────────
        rec.extension = extension_of(wf.name)
        if profile.flag_bad_extensions and rec.signature_type is not None:
            rec.bad_extension = is_bad_extension(rec.signature_type, wf.name)
            result.bad_extensions += int(rec.bad_extension)

        # ── dedupe napříč případem (FTK Advanced De-duplication) ──
        if profile.deduplicate:
            for digest in (rec.sha256, rec.md5):  # SHA-256 profily i MD5-only (eDiscovery)
                original = deduper.check_and_register(digest, wf.rel_path)
                if original is not None:
                    rec.is_duplicate_of = original
                    result.duplicates += 1
                    break

        # ── known-bad hash sets (FTK) — MD5 i SHA-256 sety ───
        if profile.match_hash_sets and normalized_sets:
            for digest in (rec.sha256, rec.md5):
                if digest is None:
                    continue
                for name, hashes in normalized_sets.items():
                    if digest.lower() in hashes:
                        rec.hash_set_hit = name
                        result.hash_set_hits += 1
                        break
                if rec.hash_set_hit:
                    break

        db.upsert_file(rec)  # nejdřív soubor — FK pro artifacts níže

        # ── artifact extraktoři (AXIOM-style) — signatura → extraktor ──
        if profile.extract_artifacts and rec.signature_type in ARTIFACT_EXTRACTORS:
            arts = ARTIFACT_EXTRACTORS[rec.signature_type](abs_path)
            for a in arts:
                a.source_id = source_id
                a.file_id = rec.id
                a.rel_path = wf.rel_path
            db.replace_artifacts_for_file(rec.id, arts)
            result.artifacts_extracted += len(arts)

        if progress is not None and ((i + 1) % 10 == 0 or i + 1 == total):
            progress(i + 1, total)

    db.commit()
    return result


def load_hash_sets(paths: list[Path]) -> dict[str, set[str]]:
    """Načte known-bad hash sety z textových souborů (FTK-style).

    Formát: jeden hash na řádek (# komentář), SHA-256 nebo MD5 — detekce podle délky.
    Název setu = jméno souboru bez přípony.
    """
    sets: dict[str, set[str]] = {}
    for p in paths:
        name = p.stem
        hashes: set[str] = set()
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip().lower()
                if not line or line.startswith("#"):
                    continue
                if len(line) in (32, 40, 64):  # md5 / sha1 / sha256 hex
                    hashes.add(line)
        sets[name] = hashes
    return sets
