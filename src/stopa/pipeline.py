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
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from stopa.artifacts.imessage_cloud import (
    PARSER_VERSION as IMESSAGE_CLOUD_VERSION,
)
from stopa.artifacts.imessage_cloud import extract_icloud_messages, is_icloud_messages_file
from stopa.artifacts.plist_extract import PARSER_VERSION as PLIST_VERSION
from stopa.artifacts.plist_extract import extract_plist_artifacts
from stopa.artifacts.registry_extract import PARSER_VERSION as REGISTRY_VERSION
from stopa.artifacts.registry_extract import extract_registry_artifacts
from stopa.artifacts.sqlite_extract import PARSER_VERSION as SQLITE_VERSION
from stopa.artifacts.sqlite_extract import extract_sqlite_artifacts
from stopa.artifacts.sqlite_recover import recover_deleted_rows
from stopa.artifacts.win_jumplist import PARSER_VERSION as JUMPLIST_VERSION
from stopa.artifacts.win_jumplist import extract_jump_list_artifacts, is_jump_list_file
from stopa.artifacts.win_lnk import PARSER_VERSION as LNK_VERSION
from stopa.artifacts.win_lnk import extract_lnk_artifacts
from stopa.artifacts.win_prefetch import PARSER_VERSION as PREFETCH_VERSION
from stopa.artifacts.win_prefetch import extract_prefetch_artifacts
from stopa.data.db import CaseDB
from stopa.data.ingest import WalkedFile, walk_source
from stopa.domain.bad_extension import extension_of, is_bad_extension
from stopa.domain.dedupe import Deduper
from stopa.domain.hashing import hash_bytes, hash_file
from stopa.domain.profiles import get_profile
from stopa.domain.signatures import detect_signature
from stopa.domain.timeline_anomaly import AnomalyContext, detect_anomalies
from stopa.models import Artifact, FileRecord, ProcessingProfile, ProcessResult

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


# signatura → (extraktor, verze_parseru) — E1: verze se eviduje v audit logu.
ARTIFACT_EXTRACTORS: dict[str, tuple[Callable[[Path], list], str]] = {
    "sqlite": (_extract_sqlite_all, SQLITE_VERSION),
    "registry_hive": (extract_registry_artifacts, REGISTRY_VERSION),
    "plist": (extract_plist_artifacts, PLIST_VERSION),
    # E6 Windows parsery vlna 1 — LNK + SuperFetch prefetch (MAM)
    "lnk": (extract_lnk_artifacts, LNK_VERSION),
    "win_prefetch": (extract_prefetch_artifacts, PREFETCH_VERSION),
}

# name-based fallback (AXIOM Hunter) — soubory bez spolehlivé magiky.
NAME_BASED_EXTRACTORS: dict[str, tuple[Callable[[Path], list], str]] = {
    "icloud_messages": (extract_icloud_messages, IMESSAGE_CLOUD_VERSION),
    # E6 Jump Lists — .customDestinations-ms kontejnery (magic je jen u32 version)
    "win_jumplist": (extract_jump_list_artifacts, JUMPLIST_VERSION),
}


def _name_based_match(name: str) -> tuple[Callable[[Path], list], str] | None:
    """Name-based fallback dispatch — AXIOM Hunter pattern.

    iCloud Messages export a Jump Lists nemají spolehlivou magic; detekce
    podle názvu souboru, jen když signatura nic nenašla (viz _extract_artifacts_for).
    """
    if is_icloud_messages_file(name):
        return NAME_BASED_EXTRACTORS["icloud_messages"]
    if is_jump_list_file(name):
        return NAME_BASED_EXTRACTORS["win_jumplist"]
    return None


def parser_versions() -> dict[str, str]:
    """Verze všech registrovaných parserů — pro audit log (reprodukovatelnost)."""
    return {sig: ver for sig, (_fn, ver) in ARTIFACT_EXTRACTORS.items()} | {
        name: ver for name, (_fn, ver) in NAME_BASED_EXTRACTORS.items()
    }


def _extract_artifacts_for(
    path: Path, signature_type: str | None
) -> tuple[list[Artifact], str | None]:
    """Artifact extraktoři pro jeden soubor — signatura PŘED name-based fallbackem.

    AXIOM Hunter pattern: iCloud Messages export (`MessagesInICloud.csv`) nemá
    spolehlivou magic (XLSX je generic OOXML, delimited text žádnou), proto se
    detekuje podle názvu souboru — jen když signatura nic nenašla.

    Vrací ``(artifacts, parser_version)`` — verze se eviduje na každém artifactu
    (E2 provenience / reprodukovatelnost). Bez extraktoru → ``([], None)``.
    """
    if signature_type in ARTIFACT_EXTRACTORS:
        fn, ver = ARTIFACT_EXTRACTORS[signature_type]
        return fn(path), ver
    name_match = _name_based_match(path.name)  # name-based fallback (AXIOM Hunter)
    if name_match is not None:
        fn, ver = name_match
        return fn(path), ver
    return [], None


def _read_head(path: Path) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read(SIGNATURE_HEAD_BYTES)
    except OSError as e:
        log.warning("signatura — nelze číst %s: %s", path, e)
        return b""


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
    hash_error: str | None = None
    try:
        if algs and wf.size_bytes > 0:
            digests = hash_file(abs_path, algs)
            rec.md5 = digests.get("md5")
            rec.sha256 = digests.get("sha256")
        elif algs:  # prázdný soubor — platné prázdné digesty
            digests = hash_bytes(b"", algs)
            rec.md5 = digests.get("md5")
            rec.sha256 = digests.get("sha256")
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
        arts, parser_ver = _extract_artifacts_for(abs_path, rec.signature_type)

    return _FileWork(
        rec=rec, artifacts=arts, parser_version=parser_ver, error=hash_error
    )


def process_source(
    db: CaseDB,
    source_id: str,
    root: Path,
    profile_name: str = "forensic",
    hash_sets: dict[str, set[str]] | None = None,
    progress: Callable[[int, int], None] | None = None,
    resume: bool = False,
    max_workers: int | None = None,
) -> ProcessResult:
    """Zpracuje jeden evidence source daným processing profilem.

    `hash_sets` — {název_setu: množina_hashů} (FTK known-bad sets; malá hex).
    `progress` — callback (soubory_hotovo, souborů_celkem) po každém souboru.
    `resume` — E3 checkpointing: přeskočí soubory už v DB pro tento zdroj
        (předchozí běh byl dokončený); doplní jen nové soubory a timeline se
        nečistí. Default False = plný re-ingest (idempotentní upsert).
    `max_workers` — E3 paralelizace: počet worker vláken pro hashing/parsing;
        None = auto (min(8, cpu_count)). DB writes + dedupe zůstávají v hlavním
        vlákně → deterministický výsledek nezávislý na počtu vláken.
    """
    profile = get_profile(profile_name)
    result = ProcessResult(source_id=source_id, profile=profile.name)

    # E1 Evidence Manager: neměnná stopa operací (provenience — SWGDE-style)
    db.log_operation(
        "processing_started",
        details={"source_id": source_id, "profile": profile_name},
    )

    walked = walk_source(root)
    total = len(walked)

    # E3 checkpointing (resume): soubory už v DB pro tento zdroj se přeskočí —
    # předchozí běh je dokončený, neděláme hashing/parsing znovu. Timeline se
    # nečistí (události z prvního běhu jsou platné), doplníme jen nové soubory.
    if resume:
        existing_paths = {
            r["rel_path"]
            for r in db.conn.execute(
                "SELECT rel_path FROM files WHERE source_id = ?", (source_id,)
            ).fetchall()
        }
        to_process = [wf for wf in walked if wf.rel_path not in existing_paths]
    else:
        to_process = list(walked)

    skipped = total - len(to_process)  # E3 resume — hotové z předchozího běhu
    if progress is not None:
        progress(skipped, total)

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

    # E2 Timeline Engine — kontext pro detekci nesrovnalostí.
    # Operační okno (min/max) se seeduje ze stavu DB a průběžně rozšiřuje;
    # seen_timestamps naplňuje duplikát detekci během běhu.
    now_utc = datetime.now(timezone.utc)
    win = db.timeline_window(source_id=source_id)
    anomaly_ctx = AnomalyContext(
        window_start=win.get("window_start"),
        window_end=win.get("window_end"),
    )
    # re-ingest stejného zdroje → čisté timeline (idempotence, žádné duplicitní události).
    # E3 resume: nečistíme — události z předchozího běhu jsou platné, doplníme jen nové.
    if not resume:
        db.clear_timeline_events(source_id=source_id)

    # E3 paralelizace: drahé operace (hashing + signatura + parsery) běží v
    # worker vláknech; DB writes + dedupe zůstávají v hlavním vlákně v pořadí
    # procházky → deterministický originál vs. duplikát (FTK hide duplicates).
    n = len(to_process)
    if max_workers is None:
        workers = min(8, os.cpu_count() or 4) if n > 1 else 1
    else:
        workers = max(1, max_workers)

    def _abs(wf: WalkedFile) -> Path:
        return root_resolved / wf.rel_path if not root.is_file() else root_resolved

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _process_file_worker, wf, _abs(wf), source_id, profile, normalized_sets
            )
            for wf in to_process
        ]
        # konzumace v pořadí procházky — DB writes + dedupe deterministické
        for i, (wf, fut) in enumerate(zip(to_process, futures)):
            work = fut.result()
            rec = work.rec

            result.files_total += 1
            result.bytes_total += wf.size_bytes
            if work.error is not None:
                result.errors.append(work.error)
            else:
                result.hashed_md5 += int(rec.md5 is not None)
                result.hashed_sha256 += int(rec.sha256 is not None)

            # signatura — worker ji detekoval; počítáme jen pokud je nastavena
            if rec.signature_type is not None:
                result.signatures_detected += 1
            if rec.bad_extension:
                result.bad_extensions += 1

            # ── dedupe napříč případem (FTK Advanced De-duplication) ──
            # hlavní vlákno, pořadí procházky → deterministický originál
            if profile.deduplicate:
                for digest in (rec.sha256, rec.md5):  # SHA-256 profily i MD5-only (eDiscovery)
                    original = deduper.check_and_register(digest, wf.rel_path)
                    if original is not None:
                        rec.is_duplicate_of = original
                        result.duplicates += 1
                        break

            # ── known-bad hash sets — worker jen nastaví flag, tady počítáme ──
            if rec.hash_set_hit:
                result.hash_set_hits += 1

            # kanonický file id — při re-ingestu se drží původní řádek (FK stability)
            file_id = db.upsert_file(rec)  # nejdřív soubor — FK pro artifacts níže

            # ── artifact extraktoři — worker je už extrahoval, tady jen DB + timeline ──
            if profile.extract_artifacts:
                arts = work.artifacts
                parser_ver = work.parser_version
                for a in arts:
                    a.source_id = source_id
                    a.file_id = file_id
                    a.rel_path = wf.rel_path
                    # E2 Timeline Engine — provenience (reprodukovatelnost analýzy):
                    # kdy byl artifact extrahován + jakou verzí parseru.
                    if a.extracted_at is None:
                        a.extracted_at = now_utc
                    if a.parser_version is None and parser_ver is not None:
                        a.parser_version = parser_ver
                db.replace_artifacts_for_file(file_id, arts)
                result.artifacts_extracted += len(arts)

                # E2 Timeline Engine — materializace timeline + detekce nesrovnalostí.
                for a in arts:
                    if a.timestamp is None:
                        continue  # bez času události → není timeline event
                    flags = detect_anomalies(
                        a.artifact_type,
                        a.timestamp,
                        title=a.title,
                        rel_path=wf.rel_path,
                        file_mtime=rec.mtime,
                        file_ctime=rec.ctime,
                        ctx=anomaly_ctx,
                    )
                    if flags:
                        a.anomaly_flags = tuple(flags)
                    db.add_timeline_event(
                        source_id=source_id,
                        artifact_id=a.id,
                        file_id=file_id,
                        rel_path=wf.rel_path,
                        event_type=a.artifact_type,
                        ts_utc=a.timestamp,
                        title=a.title,
                        confidence=a.confidence,
                        parser_version=a.parser_version,
                        extracted_at=a.extracted_at,
                        anomaly_flags=tuple(flags),
                    )
                    # průběžné doplnění kontextu — duplikát detekce + rozšiřování okna
                    key = f"{a.artifact_type}|{a.title or ''}|{wf.rel_path}"
                    anomaly_ctx.seen_timestamps.append((a.timestamp, key))
                    if (anomaly_ctx.window_start is None
                            or a.timestamp < anomaly_ctx.window_start):
                        anomaly_ctx.window_start = a.timestamp
                    if (anomaly_ctx.window_end is None
                            or a.timestamp > anomaly_ctx.window_end):
                        anomaly_ctx.window_end = a.timestamp

            if progress is not None and ((i + 1) % 10 == 0 or i + 1 == n):
                progress(skipped + i + 1, total)

    db.commit()
    # E1 Evidence Manager: uzavření běhu — souhrny + verze parserů (reprodukovatelnost)
    db.log_operation(
        "processing_completed",
        details={
            "source_id": source_id,
            "files_total": result.files_total,
            "bytes_total": result.bytes_total,
            "signatures_detected": result.signatures_detected,
            "bad_extensions": result.bad_extensions,
            "duplicates": result.duplicates,
            "hash_set_hits": result.hash_set_hits,
            "artifacts_extracted": result.artifacts_extracted,
            "errors": len(result.errors),
            "parser_versions": parser_versions(),
        },
    )
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
