"""Jádro pipeline — process_source() a veřejné utility.

P1-4 vlna D: vyčleněno z monolitu ``pipeline.py``; sdílený entrypoint
CLI i web GUI (jeden kódový průchod).
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import tempfile
import threading  # F2.4 — stop_event pro graceful shutdown (CLI napojuje SIGINT/SIGTERM)
import time
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timezone
from multiprocessing import get_context as _mp_get_context
from pathlib import Path

import stopa as _stopa_pkg  # __version__ (single-source z pyproject)
from stopa.data.db import CaseDB
from stopa.data.ingest import WalkedFile, walk_source
from stopa.domain.dedupe import Deduper
from stopa.domain.entities import extract_entities
from stopa.domain.hashing import hash_file
from stopa.domain.lineage import config_hash
from stopa.domain.profiles import get_profile
from stopa.domain.reproducibility import (
    AnalysisOperation,
    ReplayResult,
    compare_outputs,
    verify_inputs,
)
from stopa.domain.timeline_anomaly import AnomalyContext, detect_anomalies
from stopa.domain.timeline_intel import analyze_timeline
from stopa.domain.work_queue import CapacityBudget, InProcessWorkQueue, WorkQueue  # P2-1
from stopa.models import ProcessResult

from .pool import (
    _FileWork,
    _pool_init,
    _process_file_task,
    _process_file_worker,
)
from .registry import (
    ARTIFACT_EXTRACTORS,
    NAME_BASED_EXTRACTORS,
)

log = logging.getLogger("stopa.pipeline")

def parser_versions() -> dict[str, str]:
    """Verze všech registrovaných parserů — pro audit log (reprodukovatelnost)."""
    return {sig: ver for sig, (_fn, ver) in ARTIFACT_EXTRACTORS.items()} | {
        name: ver for name, (_fn, ver) in NAME_BASED_EXTRACTORS.items()
    }


def summarize_outputs(result: ProcessResult) -> dict:
    """Deterministický souhrn výsledku pro porovnání při replay (P0 Core C5).

    Obsahuje jen stabilní počty — ne ID ani časy, aby stejný vstup na stejném
    prostředí vždy dal stejný souhrn (determinismus porovnání).
    """
    return {
        "files_total": result.files_total,
        "bytes_total": result.bytes_total,
        "hashed_md5": result.hashed_md5,
        "hashed_sha256": result.hashed_sha256,
        "signatures_detected": result.signatures_detected,
        "bad_extensions": result.bad_extensions,
        "duplicates": result.duplicates,
        "hash_set_hits": result.hash_set_hits,
        "artifacts_extracted": result.artifacts_extracted,
        "errors": len(result.errors),
    }


def _resume_meta_matches(row_meta: dict, wf: WalkedFile) -> bool:
    """P0.1 Fast resume — metadata identity mezi běhy (size + mtime UTC).

    Metadata nejsou důkazem integrity obsahu (viz ``strict``); slouží k levnému
    vyřazení zjevně neměněných souborů. Neznámá/legacy hodnota (NULL) = nelze
    ověřit → soubor se znovu zpracuje (bezpečná strana).
    """
    if row_meta["size"] != wf.size_bytes:
        return False
    stored_mtime = row_meta["mtime"]  # ISO TEXT nebo NULL
    if stored_mtime is None or wf.mtime is None:
        return False
    try:
        stored = datetime.fromisoformat(stored_mtime)
    except ValueError:
        return False
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=timezone.utc)
    return stored == wf.mtime


def _sha256_stream(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str | None:
    """P0.1 Strict resume — streaming SHA-256 (peak RAM = jeden chunk).

    Vrací ``None`` při read chybě (soubor zmizel mezi běhy → volající ho
    re-processuje; bezpečná strana, protože hashing v normální pipeline
    workeru stejně proběhne).
    """
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def process_source(
    db: CaseDB,
    source_id: str,
    root: Path,
    profile_name: str = "forensic",
    hash_sets: dict[str, set[str]] | None = None,
    progress: Callable[[int, int], None] | None = None,
    resume: bool = False,
    resume_mode: str | None = None,  # P0.1 — "fast" (výchozí) / "strict"; viz docstring
    max_workers: int | None = None,
    pool: str = "auto",
    commit_every: int = 256,
    stop_event: threading.Event | None = None,
    max_inflight: int | None = None,
    pinned_parser_version: str | None = None,
    work_queue: WorkQueue | None = None,
    disk_budget_bytes: int | None = None,
) -> ProcessResult:
    """Zpracuje jeden evidence source daným processing profilem.

    `hash_sets` — {název_setu: množina_hashů} (FTK known-bad sets; malá hex).
    `progress` — callback (soubory_hotovo, souborů_celkem) po každém souboru.
    `resume` — E3 checkpointing: přeskočí soubory už v DB pro tento zdroj
        (předchozí běh byl dokončený); doplní jen nové soubory a timeline se
        nečistí. Default False = plný re-ingest (idempotentní upsert).
    `resume_mode` — P0.1 Safe resume: jak ověřit identitu souborů už v DB při
        ``resume=True``. "fast" (výchozí) = existence + size_bytes + mtime (UTC);
        "strict" = obsah SHA-256 (metadata nejsou důkazem integrity obsahu).
        Změněné/smazané soubory se neticho přeskočí: dojdou na re-processing a
        auditní událost ``source_modified_during_resume`` zachová původní hodnoty.
    `max_workers` — E3 paralelizace: počet worker procesů/vláken pro hashing/parsing;
        None = auto (min(8, cpu_count)). DB writes + dedupe zůstávají v hlavním
        vlákně → deterministický výsledek nezávislý na počtu workerů.
    `pool` — F2.4 typ poolu: "auto" (default) = procesy pro workers > 1 (GIL u
        Python parserů; Rust core GIL stejně uvolňuje), "threads" = původní E3
        režim, "processes" = vynutit procesy i pro workers == 1.
    `commit_every` — F2.4 checkpointing: db.commit() každých N souborů; po kill
        uprostřed běhu jsou zpracované soubory v DB a `resume=True` doplní zbytek
        (bez ztráty dat). 0 = commit až na konci (původní chování).
    `stop_event` — F2.4 graceful shutdown: threading.Event; když se nastaví,
        okno se nedoplňuje novými úlohami, in-flight úlohy dojedou a stav se
        committuje. CLI napojuje SIGINT/SIGTERM sem (result.interrupted = True).
    `max_inflight` — F2.4 backpressure: max počtu současně odeslaných (in-flight)
        úloh; None = auto (max(8, 4*workers)). Omezuje RAM i napředběh walku.
    `pinned_parser_version` — F5.3 reparse: prokládaná verze parserové sady;
        všechny extrahované artefakty dostanou tuto provenience místo aktuální
        registry (chování parserů se nemění → deterministický souhrn je stejný).
    `work_queue` — P2-1 abstrakce fronty úkolů (WorkQueue kontrakt); None = in-process
        InProcessWorkQueue (aktuální stav F2.4, omezená na `window`). Broker backend
        se napojí pod stejným rozhraním bez změny ostatní pipeline logiky; DB writes +
        dedupe zůstávají v hlavním procesu a konzumace je FIFO → determinismus.
        Kontrakt: kapacita fronty (maxsize) musí být ≥ `window` nebo neomezená —
        refill burst plní okno bez mezizastavení na konzumaci, takže menší omezená
        fronta by v put() blokovala (backpressure bez aktivního konzumenta).
    `disk_budget_bytes` — P2-1 kapacitní řízení: max celková velikost in-flight souborů
        (CapacityBudget); None/0 = bez limitu (původní chování). Soubor větší než celý
        rozpočet projde vždy, když nic jiného není in-flight (fail-open pro jeden velký).
    """
    profile = get_profile(profile_name)
    result = ProcessResult(source_id=source_id, profile=profile.name)
    _t0 = time.monotonic()  # P0 Core C5: čas zpracování operace (reproducibility)

    # E1 Evidence Manager: neměnná stopa operací (provenience — SWGDE-style)
    db.log_operation(
        "processing_started",
        details={"source_id": source_id, "profile": profile_name},
    )

    walked = walk_source(root)
    total = len(walked)

    # ── P0.1 Safe resume — ověření identity souborů mezi běhy ───────────────
    # Staré --resume věřil jen rel_path v DB: nahrazený/zmenšený/smazaný soubor
    # prošel ticho jako „již zpracován“. Teď se ověřuje:
    #   fast (výchozí) — existence + size_bytes + mtime (UTC); levný metadata check.
    #   strict         — obsah SHA-256 (metadata nejsou důkazem integrity obsahu).
    #   force          = resume=False (kompletní re-ingest, idempotentní upsert).
    # Změněné soubory se NEpřeskočí: dojdou na re-processing a auditní událost
    # source_modified_during_resume zachová původní hodnoty (hash/historii).
    if resume_mode is not None and resume_mode not in ("fast", "strict"):
        raise ValueError(f"resume_mode: očekávám 'fast' nebo 'strict', dostal jsem {resume_mode!r}")

    if resume:
        mode = resume_mode or "fast"
        rows = db.conn.execute(
            "SELECT rel_path, size_bytes, mtime, sha256 FROM files WHERE source_id = ?",
            (source_id,),
        ).fetchall()
        existing_meta = {
            r["rel_path"]: {
                "size": r["size_bytes"],
                "mtime": r["mtime"],
                "sha256": r["sha256"],
            }
            for r in rows
        }
        single_file_source = root.is_file()
        resolved_root = Path(root).resolve()

        def _resume_abs(rel_path: str) -> Path:
            return resolved_root if single_file_source else resolved_root / rel_path

        changes: list[dict] = []
        to_process: list[WalkedFile] = []
        for wf in walked:
            row_meta = existing_meta.get(wf.rel_path)
            if row_meta is None:
                to_process.append(wf)  # nový soubor — zpracovat
                continue
            if mode == "strict":
                stored_sha = row_meta["sha256"]
                current_sha = _sha256_stream(_resume_abs(wf.rel_path))
                same_content = (
                    stored_sha is not None
                    and current_sha is not None
                    and stored_sha == current_sha
                )
            else:  # fast — jen metadata (size + mtime UTC)
                same_content = _resume_meta_matches(row_meta, wf)
            if same_content:
                continue  # ověřeno → přeskočit
            to_process.append(wf)  # změněno → re-processing (upsert drží kanonické ID)
            changes.append(
                {
                    "rel_path": wf.rel_path,
                    "kind": "modified",
                    "old_size": row_meta["size"],
                    "new_size": wf.size_bytes,
                    "old_mtime": row_meta["mtime"],
                    "new_mtime": wf.mtime.isoformat() if wf.mtime else None,
                    "old_sha256": row_meta["sha256"],
                }
            )
        # smazané soubory — v DB, ale už ve zdroji ne (walk vidí jen co existuje)
        walked_paths = {wf.rel_path for wf in walked}
        for rel_path in sorted(set(existing_meta) - walked_paths):
            row_meta = existing_meta[rel_path]
            changes.append(
                {
                    "rel_path": rel_path,
                    "kind": "deleted",
                    "old_size": row_meta["size"],
                    "old_mtime": row_meta["mtime"],
                    "old_sha256": row_meta["sha256"],
                }
            )
        if changes:
            truncated = len(changes) > 100
            db.log_operation(
                "source_modified_during_resume",
                details={
                    "mode": mode,
                    "modified_count": sum(1 for c in changes if c["kind"] == "modified"),
                    "deleted_count": sum(1 for c in changes if c["kind"] == "deleted"),
                    "changes": changes[:100],
                    **({"truncated": True} if truncated else {}),
                },
            )
            result.modified_during_resume = len(changes)
    else:
        to_process = list(walked)

    skipped = total - len(to_process)  # E3 resume — hotové z předchozího běhu
    result.skipped = skipped  # P0.1 — explicitní counter pro volající (API/CLI/web)
    if progress is not None:
        progress(skipped, total)

    # dedupe napříč celým případem — seed z DB (jiné zdroje / předchozí běhy)
    # oba hashy: SHA-256 profily i MD5-only (FTK eDiscovery); STP-022: +SHA-512
    deduper = Deduper()
    existing = db.conn.execute("SELECT sha256, md5, sha512, rel_path FROM files").fetchall()
    deduper.seed(
        [(r["sha256"], r["rel_path"]) for r in existing]
        + [(r["md5"], r["rel_path"]) for r in existing]
        + [(r["sha512"], r["rel_path"]) for r in existing]
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

    # E3/F2.4 paralelizace: drahé operace (hashing + signatura + parsery) běží v
    # worker procesech/vláknech; DB writes + dedupe zůstávají v hlavním vlákně a
    # konzumují se v pořadí procházky → deterministický originál vs. duplikát
    # (FTK hide duplicates). F2.4: omezené okno in-flight úloh = backpressure mezi
    # producerem (walk) a consumerem (parse); periodický commit = checkpoint pro
    # graceful shutdown — po kill bez ztráty dat (zpracované soubory jsou v DB,
    # nezpracované doplní resume=True).
    n = len(to_process)
    if max_workers is None:
        workers = min(8, os.cpu_count() or 4) if n > 1 else 1
    else:
        workers = max(1, max_workers)

    pool_mode = "auto" if pool not in ("threads", "processes") else pool
    use_processes = (pool_mode == "processes") or (pool_mode == "auto" and workers > 1)
    window = max_inflight if max_inflight is not None else max(8, workers * 4)

    def _abs(wf: WalkedFile) -> Path:
        return root_resolved / wf.rel_path if not root.is_file() else root_resolved

    def _apply_work(work: _FileWork, wf: WalkedFile, i: int) -> None:
        """DB writes + dedupe pro jeden soubor — hlavní vlákno, pořadí procházky."""
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
            # SHA-256 profily i MD5-only (eDiscovery); STP-022: +SHA-512
            for digest in (rec.sha256, rec.md5, rec.sha512):
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
                # F5.3 reparse — prokládaná verze parserové sady (provenience)
                if pinned_parser_version is not None:
                    a.parser_version = pinned_parser_version
            db.replace_artifacts_for_file(file_id, arts)
            result.artifacts_extracted += len(arts)
            # P0 Core C2: Evidence Lineage — output_refs kroku extract (ID artefaktů)
            result.extracted_artifact_ids.extend(a.id for a in arts)

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
                # STP-018 — normalizované entity subjektu (pro detekci rozporů);
                # čistá logika bez IO, defenzivně (chyba extrakce ≠ pád pipeline).
                try:
                    subject_values = tuple(sorted({e.value for e in extract_entities(a)}))
                except Exception:  # noqa: BLE001 — analytický bonus, ne kritická cesta
                    log.debug("subject extraction failed for artifact %s", a.id)
                    subject_values = ()
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
                    ts_origin=getattr(a, "ts_origin", None) or "source",
                    subject_values=subject_values,
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

    with contextlib.ExitStack() as stack:
        if use_processes and workers > 1:
            # F2.4 — spawn context: children nedědí zámky rodiče (CLI běží s Rich
            # Progress pozadím vlákna → fork by mohl v child procesu deadlocknout).
            executor = stack.enter_context(
                ProcessPoolExecutor(
                    max_workers=workers,
                    mp_context=_mp_get_context("spawn"),
                    initializer=_pool_init,
                    initargs=(profile, normalized_sets),
                )
            )

            def _submit_one(wf_: WalkedFile) -> Future[_FileWork]:
                return executor.submit(  # type: ignore[union-attr]
                    _process_file_task, wf_, str(_abs(wf_)), source_id
                )
        else:
            executor = stack.enter_context(ThreadPoolExecutor(max_workers=max(1, workers)))

            def _submit_one(wf_: WalkedFile) -> Future[_FileWork]:
                return executor.submit(  # type: ignore[union-attr]
                    _process_file_worker, wf_, _abs(wf_), source_id, profile, normalized_sets
                )

        # P2-1 — abstrakce fronty úkolů: default in-process InProcessWorkQueue
        # (= aktuální stav F2.4, omezená na `window`); broker backend se napojuje
        # přes parametr `work_queue` pod stejným WorkQueue kontraktem. Konzumace je
        # FIFO (take_batch) → deterministický originál vs. duplikát; DB writes + dedupe
        # zůstávají v hlavním procesu. CapacityBudget = disk budget in-flight souborů.
        queue: WorkQueue = (
            work_queue if work_queue is not None else InProcessWorkQueue(maxsize=window)
        )
        budget = CapacityBudget(
            max_workers=max(1, workers), disk_budget_bytes=disk_budget_bytes
        )
        it = iter(to_process)
        next_wf: WalkedFile | None = next(it, None)
        stopped = False

        for i in range(n):
            # F2.4 backpressure — doplnit okno na max `window` in-flight úloh;
            # walk (producer) se tak nemůže běhat neomezeně napřed před parsem.
            # P2-1: omezení přes WorkQueue.pending + CapacityBudget disk budget.
            while not stopped and next_wf is not None and queue.pending < window:
                if stop_event is not None and stop_event.is_set():
                    stopped = True  # nová submit už ne; in-flight úlohy dojedou (graceful)
                    break
                wf_ = next_wf
                size = max(0, wf_.size_bytes)
                # P2-1 kapacitní řízení — disk budget in-flight souborů: plný rozpočet →
                # nechat konzumační fázi uvolnit místo (jeden soubor větší než celý
                # rozpočet projde vždy, když nic jiného není in-flight).
                if budget.inflight_bytes > 0 and not budget.can_admit(size):
                    break
                budget.admit(size)
                queue.put((_submit_one(wf_), wf_))
                next_wf = next(it, None)

            # P2-1 konzumace — FIFO take_batch; stop+drained → [] (graceful shutdown).
            if stopped and queue.pending == 0:
                batch: list[tuple[Future[_FileWork], WalkedFile]] = []
            else:
                batch = queue.take_batch(1)

            if not batch:
                break  # vše odesláno+zkonzumováno (nebo stop bez in-flight úloh)

            fut, wf = batch[0]
            work = fut.result()  # konzumace v pořadí procházky → deterministické dedupe
            _apply_work(work, wf, i)
            budget.release(max(0, wf.size_bytes))  # P2-1 — kapacita uvolněna po DB write
            if commit_every > 0 and (i + 1) % commit_every == 0:
                db.commit()  # F2.4 checkpoint — stav přežije kill uprostřed běhu

    result.interrupted = stopped

    db.commit()  # F2.4 finální checkpoint (periodické commity už proběhly průběžně)
    # P0.4/P1 — Source manifest: deterministický snapshot souborového stavu zdroje
    # (rel_path/size/mtime/SHA-256 → kanonická forma → SHA-256). Změna oproti
    # uloženému manifestu = auditní událost se starou hodnotou (historie v chain);
    # fast-skip resume s nezměněnými řádky reprodukuje stejný digest → bez šumu.
    try:
        mrows = db.conn.execute(
            "SELECT rel_path, size_bytes, mtime, sha256 FROM files WHERE source_id = ?",
            (source_id,),
        ).fetchall()
        mres = db.case_repo.update_source_manifest(source_id, [dict(r) for r in mrows])
        if mres["status"] != "unchanged":
            db.log_operation(
                "source_manifest_created"
                if mres["status"] == "created"
                else "source_manifest_changed",
                details={"source_id": source_id, **mres},
            )
    except Exception as exc:  # noqa: BLE001 — defenzivní, manifest nepřeruší ingest (data už commitnuta)
        db.log_operation(
            "source_manifest_error", details={"source_id": source_id, "error": str(exc)}
        )
    # E1 Evidence Manager: uzavření běhu — souhrny + verze parserů (reprodukovatelnost).
    # F2.4: přerušený běh se eviduje jako processing_interrupted (checkpoint uložen,
    # pokračování přes resume=True bez ztráty dat).
    db.log_operation(
        "processing_completed" if not result.interrupted else "processing_interrupted",
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
    # P0 Core C2: Evidence Lineage — krok extrakce (zdroj → artefakty).
    # Input = zdroj + zpracované soubory; output = ID extrahovaných artefaktů.
    if result.artifacts_extracted or result.files_total:
        db.log_lineage(
            "extract",
            case_id=_case_id_for_source(db, source_id),
            tool_version=_stopa_pkg.__version__,
            config_hash=config_hash({"profile": profile_name}),
            input_refs=(source_id,),
            output_refs=tuple(result.extracted_artifact_ids),
            details={
                "files_total": result.files_total,
                "artifacts_extracted": result.artifacts_extracted,
                "parser_versions": parser_versions(),
            },
        )
    # P0 Core C5: Reproducibility Engine — záznam operace pro opakování + porovnání.
    # Vstupní soubory se SHA-256 (z DB po upsertu) → replay ověří, že se zpracovává totéž.
    input_files = [
        {"rel_path": r["rel_path"], "sha256": r["sha256"]}
        for r in db.conn.execute(
            "SELECT rel_path, sha256 FROM files WHERE source_id = ? ORDER BY rel_path",
            (source_id,),
        ).fetchall()
    ]
    # F5.3 reparse — snapshot mapy verzí odrazí, co se skutečně použilo:
    # registry + prokládaná verze (přítomná jen u re-parse běhu).
    if pinned_parser_version is not None:
        _recorded_versions = {**parser_versions(), "pinned": pinned_parser_version}
        _op_params = {"profile": profile_name, "pinned_parser_version": pinned_parser_version}
    else:
        _recorded_versions = parser_versions()
        _op_params = {"profile": profile_name}
    db.record_operation(
        "extract",
        case_id=_case_id_for_source(db, source_id),
        source_id=source_id,
        input_files=input_files,
        parser_versions=_recorded_versions,
        stopa_version=_stopa_pkg.__version__,
        config_hash=config_hash({"profile": profile_name}),
        params=_op_params,
        outputs=summarize_outputs(result),
        duration_ms=int((time.monotonic() - _t0) * 1000),
    )
    # STP-069 — Plánované/periodické exporty: opt-in automatický ZIP bundle po
    # úspěšném dokončení processingu. Fail-safe: chyba auto-exportu nikdy nepadne
    # hlavní flow (log + pokračování). Deterministický výstup (C4) přes to_zip_bundle.
    # F2.4: přerušený (částečný) běh nespouští plánovaný export — doplní resume.
    if not result.interrupted:
        _maybe_auto_export(db, source_id)
    return result


def _maybe_auto_export(db: CaseDB, source_id: str) -> None:
    """STP-069 — vygeneruje auto-bundle, pokud je u případu zapnutý (opt-in).

    Volá se na konci ``process_source()`` po úspěšném dokončení. Celé tělo je
    obalené v try/except — selhání auto-exportu se pouze zloguje a nikdy nepadne
    hlavní ingest/analysis flow (fail-safe, default off).
    """
    case_id = _case_id_for_source(db, source_id)
    if not case_id:
        return
    try:
        case = db.get_case(case_id)
        if case is None or not case.auto_export_enabled:
            return
        from stopa.domain.export import build_auto_bundle

        data, out_path = build_auto_bundle(db, case_id)
        # atomický zápis (tmp → rename), aby UI nikdy nevidělo poloviční soubor
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_suffix(".zip.tmp")
        tmp_path.write_bytes(data)
        tmp_path.replace(out_path)
        db.set_last_auto_export(case_id, str(out_path))
        db.log_operation(
            "auto_bundle_exported",
            actor=case.examiner,
            details={
                "source_id": source_id,
                "path": str(out_path),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
        )
    except Exception as exc:  # noqa: BLE001 — fail-safe, nikdy nepadne flow
        logging.getLogger(__name__).warning(
            "STP-069 auto-export selhal (case=%s): %s", case_id, exc
        )


def run_timeline_intel(
    db: CaseDB, window_seconds: float = 60.0
) -> dict[str, int]:
    """STP-018 Timeline Intelligence 2.0 — post-pass nad celou case DB.

    Běží po zpracování zdrojů (CLI ``add`` / web process) nebo explicitně
    (``stopa timeline --intel``). Čistá logika z ``domain/timeline_intel.py``:
    rozpory (souběžná aktivita subjektu) + duplikáty napříč zdroji. Výsledek se
    materializuje do ``timeline_events`` (group ID + kanonické flagy) —
    idempotentní, deterministický, bez dotyku původních artifactů.

    Vrací souhrn pro logování/UI: počet událostí, rozporových skupin a duplikátů.
    """
    db.clear_timeline_intel_groups()
    events = db.list_timeline_events()
    result = analyze_timeline(events, window_seconds=window_seconds)
    updated = db.set_timeline_intel_groups(
        result.event_contradiction_groups, result.event_dup_groups
    )
    log.info(
        "timeline intel: %d událostí → %d rozporových skupin, %d dup. skupin (%d řádků upraveno)",
        len(events),
        len(result.contradictions),
        len(result.dup_groups),
        updated,
    )
    return {
        "events": len(events),
        "contradiction_groups": len(result.contradictions),
        "dup_groups": len(result.dup_groups),
        "updated_rows": updated,
    }


def _case_id_for_source(db: CaseDB, source_id: str) -> str | None:
    """Case ID zdroje pro lineage (None pokud zdroj neexistuje — defenzivní)."""
    src = db.get_source(source_id)
    return src.case_id if src else None


def replay_extract(
    op: AnalysisOperation, root: Path, workdir: Path | None = None
) -> ReplayResult:
    """Opakuje zaznamenanou extrakci a porovná výsledek s původním (P0 Core C5).

    1. ověří vstupní soubory (SHA-256 na disku vs. záznam operace),
    2. spustí ``process_source`` do ČISTÉ dočasné DB (původní případ se nedotkne —
       „nikdy neměň originální důkazní data"),
    3. porovná deterministický souhrn výstupů s původním záznamem.

    ``workdir`` — kde leží dočasná DB (default: systémový tmp). Volání zavře
    dočasnou DB; soubor zůstává pro inspekcí (volající ho smaže, pokud chce).
    """
    from stopa.data.db import CaseDB as _CaseDB  # lokální — bez cyklu při importu
    from stopa.models import Case, EvidenceSource

    t0 = time.monotonic()
    profile_name = op.params_json.get("profile", "forensic")

    # 1) vstupní ověření — aktuální hashe na disku (jen soubory ze záznamu)
    current_hashes: dict[str, str | None] = {}
    for f in op.input_files:
        p = root / f["rel_path"] if not root.is_file() else root
        try:
            digests = hash_file(p, ["sha256"])
            current_hashes[f["rel_path"]] = digests.get("sha256")
        except OSError:
            current_hashes[f["rel_path"]] = None  # soubor zmizel / nečitelný
    inputs_ok, input_diffs = verify_inputs(list(op.input_files), current_hashes)

    # 2) čistá dočasná DB — původní případ se nedotkne (append-only evidence)
    tmp_db_path = Path(workdir or tempfile.gettempdir()) / f"stopa-replay-{op.id}.db"
    replay_db = _CaseDB(tmp_db_path)
    try:
        case = Case(name=f"replay {op.op_type} {op.id}")
        replay_db.add_case(case)
        src = EvidenceSource(
            case_id=case.id, kind="folder", path=str(root), size_bytes=None
        )
        replay_db.add_source(src)
        result = process_source(replay_db, src.id, root, profile_name=profile_name)
    finally:
        replay_db.close()

    # 3) porovnání výstupů — deterministický souhrn vs. původní záznam
    report = compare_outputs(op.outputs_json, summarize_outputs(result))
    return ReplayResult(
        op_id=op.id,
        inputs_identical=inputs_ok,
        input_diffs=input_diffs,
        outputs_identical=report.identical,
        output_diffs=report.diffs,
        duration_ms=int((time.monotonic() - t0) * 1000),
    )


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
