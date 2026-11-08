"""STOPA web GUI — FastAPI nad `analyze()` pipeline + statická SPA.

Design:
- **jeden endpoint = jedna DB operace** (per-request CaseDB open/close —
  SQLite je thread-safe při sekvenčním přístupu, uvicorn single worker)
- **vanilla JS SPA** bez build kroku (index.html + app.js + style.css) —
  forenzní nástroj by neměl potřebovat Node toolchain
- pipeline sdílí s CLI stejnou `process_source()` — web není paralelní implementace

Spuštění: ``stopa serve [--port 8473]`` nebo ``uvicorn stopa.web.app:app``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from stopa import __version__
from stopa.data.db import CaseDB
from stopa.data.lmstudio_client import LmStudioClient, LmStudioUnavailable
from stopa.data.timesketch_client import (
    TimesketchClient,
    TimesketchError,
    TimesketchUnavailable,
)
from stopa.domain.ai_assistant import (
    build_explain_prompt,
    build_nl_search_prompt,
    build_summary_prompt,
    extract_citations,
    parse_confidence,
    parse_nl_search,
)
from stopa.domain.rbac import (
    DEFAULT_ROLE,
    PERMISSIONS,
    ROLE_LABELS,
    ROLES,
    RBACDenied,
    normalize_role,
    permissions_for,
    require_permission,
)
from stopa.domain.times import to_local_iso
from stopa.models import Case, EvidenceSource
from stopa.pipeline import process_source

log = logging.getLogger("stopa.web")

STATIC_DIR = Path(__file__).parent / "static"


def _db_dir() -> Path:
    d = Path(os.environ.get("STOPA_DB_DIR", "cases"))
    d.mkdir(parents=True, exist_ok=True)
    return d


# audit P1 — case_id z URL jde přímo do cesty; bez sanitace uniká `../secret.db`
# mimo STOPA_DB_DIR (path traversal). Legitní ID = `case-<hex>` → strict regex.
_CASE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_case_id(case_id: str) -> None:
    """Odmítne case_id, které by mohly uniknout DB adresáře (path traversal)."""
    if not _CASE_ID_RE.match(case_id):
        raise HTTPException(400, f"neplatné ID případu: {case_id!r}")


class CaseIn(BaseModel):
    name: str
    examiner: str | None = None
    notes: str | None = None


class SourceIn(BaseModel):
    path: str
    profile: str = "forensic"
    resume: bool = False  # E3 checkpointing — přeskočit soubory už v DB
    background: bool = False  # STP-021 — async ingest (default sync = backward compat)


class AiQueryIn(BaseModel):
    """E11 — dotaz na AI asistenta (režim + parametry)."""

    mode: str  # nl_search | summary | explain
    question: str = ""  # nl_search: přirozená řeč; explain: volitelný kontext
    artifact_id: str | None = None  # explain: který artifact vysvětlit


class AiAnalyzeIn(BaseModel):
    """P0 Intelligence I1 — analytický úkol pro AI orchestraci.

    ``agent`` je volitelné (None = auto-routing podle dotazu).
    """

    question: str
    agent: str | None = None  # case_analyst|timeline_analyst|artifact_analyst|media_analyst|report_analyst


class TimesketchPushIn(BaseModel):
    """STP-059 — push datasetu případu do Timesketch sketchu."""

    what: str = "timeline"  # artifacts | timeline | correlations


class SettingsIn(BaseModel):
    """E12 — uživatelská nastavení (jen zadaná pole se uloží)."""

    timezone_name: str | None = None
    ai_url: str | None = None
    role: str | None = None  # examiner | analyst | admin
    bind_address: str | None = None
    ai_redact_pii: bool | None = None  # STP-019 — maskovat PII v LLM promptech


class CaseUpdateIn(BaseModel):
    """E12 — aktualizace metadat případu (jen zadaná pole)."""

    name: str | None = None
    examiner: str | None = None
    notes: str | None = None
    timezone_name: str | None = None


def create_app(db_dir: Path | None = None) -> FastAPI:
    """App factory — `db_dir` pro testy (tmp), default z env STOPA_DB_DIR."""
    app = FastAPI(title="STOPA", version=__version__)
    base = db_dir or _db_dir()
    app.state.db_dir = base  # pro testy (TestClient)

    # STP-021 — Processing Monitor: registry běhů ingestu (in-memory, per-app).
    # Job = {id, case_id, source_id, status, done, total, error, result}.
    # Sync POST /sources (default) se do registru taky zapisuje → GUI vidí i
    # právě probíhající synchronní ingest přes poll endpoint.
    _jobs: dict[str, dict] = {}
    _jobs_lock = threading.Lock()

    def _job_update(job_id: str, **fields) -> None:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].update(fields)

    def open_db(case_id: str) -> CaseDB:
        validate_case_id(case_id)
        path = base / f"{case_id}.db"
        if not path.exists():
            raise HTTPException(404, f"případ {case_id} nenalezen")
        return CaseDB(path)

    # ── health ────────────────────────────────────────────────
    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "db_dir": str(base)}

    # ── cases ─────────────────────────────────────────────────
    @app.get("/api/cases")
    def list_cases() -> list[dict]:
        out = []
        for path in sorted(base.glob("case-*.db")):
            db = CaseDB(path)
            try:
                case = db.get_case(path.stem)
                if case is None:
                    continue
                stats = db.stats()
                art = db.artifact_stats()
                out.append(
                    {
                        "id": case.id,
                        "name": case.name,
                        "examiner": case.examiner,
                        "created_at": case.created_at.isoformat(),
                        "files": stats["files"],
                        "bytes": stats["bytes"],
                        "bad_ext": stats["bad_ext"],
                        "dups": stats["dups"],
                        "artifacts": art.get("total", 0),
                    }
                )
            finally:
                db.close()
        return out

    @app.post("/api/cases", status_code=201)
    def create_case(body: CaseIn) -> dict:
        _require("case.create", "create_case")
        # nová DB na nový soubor — case ID je v názvu souboru
        case = Case(name=body.name, examiner=body.examiner, notes=body.notes)
        db = CaseDB(base / f"{case.id}.db")
        try:
            db.add_case(case)
            # P0 Core C4: Ed25519 klíčový pár případu (graceful degradation bez cryptography).
            try:
                db.ensure_integrity_key()
            except RuntimeError:  # chybí balík cryptography — checkpointy degradují
                pass
        finally:
            db.close()
        return {"id": case.id, "name": case.name}

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str) -> dict:
        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            if case is None:
                raise HTTPException(404, "případ neexistuje")
            return {
                "id": case.id,
                "name": case.name,
                "examiner": case.examiner,
                "notes": case.notes,
                "created_at": case.created_at.isoformat(),
                "sources": [
                    {"id": s.id, "kind": s.kind, "path": s.path,
                     "added_at": s.added_at.isoformat()}
                    for s in db.list_sources(case_id)
                ],
                "stats": db.stats(),
                "artifact_stats": db.artifact_stats(),
            }
        finally:
            db.close()

    # ── sources / ingest ──────────────────────────────────────
    @app.post("/api/cases/{case_id}/sources", status_code=201)
    def add_source(case_id: str, body: SourceIn) -> dict:
        _require("source.add", "add_source")
        root = Path(body.path).expanduser()
        if not root.exists():
            raise HTTPException(400, f"zdroj neexistuje: {root}")
        db = open_db(case_id)

        # STP-021 — Processing Monitor: registrovat běh (sync i async).
        job_id = uuid.uuid4().hex[:12]
        with _jobs_lock:
            _jobs[job_id] = {
                "id": job_id,
                "case_id": case_id,
                "source_id": None,
                "status": "running",
                "done": 0,
                "total": 0,
                "error": None,
                "result": None,
            }

        def _progress(done: int, total: int) -> None:
            _job_update(job_id, done=done, total=total)

        if body.background:
            # STP-021 — async ingest: background thread se VLASTNÍ DB spojením
            # (per-thread sqlite3.connect; hlavní request vrací 201 okamžitě).
            db.close()

            def _run() -> None:
                tdb = CaseDB(base / f"{case_id}.db")
                try:
                    source = EvidenceSource(
                        case_id=case_id,
                        kind="folder" if root.is_dir() else "file",
                        path=str(root),
                    )
                    tdb.add_source(source)
                    _job_update(job_id, source_id=source.id)
                    result = process_source(
                        tdb, source.id, root, body.profile,
                        progress=_progress, resume=body.resume,
                    )
                    _job_update(job_id, status="done", result=result.model_dump())
                except Exception as exc:  # defenzivně — thread nesmí umlčet chybu
                    log.exception("background ingest %s selhal", job_id)
                    _job_update(job_id, status="error", error=str(exc))
                finally:
                    tdb.close()

            threading.Thread(target=_run, name=f"stopa-ingest-{job_id}", daemon=True).start()
            return {"source_id": None, "job_id": job_id, "status": "running"}

        # sync ingest (default — backward compat): request čeká na dokončení
        try:
            source = EvidenceSource(
                case_id=case_id,
                kind="folder" if root.is_dir() else "file",
                path=str(root),
            )
            db.add_source(source)
            _job_update(job_id, source_id=source.id)
            result = process_source(db, source.id, root, body.profile, progress=_progress, resume=body.resume)
            _job_update(job_id, status="done", result=result.model_dump())
            return {
                "source_id": source.id,
                "job_id": job_id,
                **result.model_dump(),
            }
        except Exception:
            _job_update(job_id, status="error")
            raise
        finally:
            db.close()

    # ── STP-021 — Processing Monitor (živý progress ingestu) ───────────────
    @app.get("/api/cases/{case_id}/processing")
    def processing_status(case_id: str) -> dict:
        """STP-021 — stav běhů ingestu pro případ (live progress).

        `active` = právě probíhající job (GUI polluje tento endpoint během
        async ingestu); `recent` = poslední 10 běhů (nejnovější první).
        """
        with _jobs_lock:
            mine = [dict(j) for j in _jobs.values() if j["case_id"] == case_id]
        active = next((j for j in reversed(mine) if j["status"] == "running"), None)
        return {"active": active, "recent": list(reversed(mine[-10:]))}

    # ── files / search / timeline ─────────────────────────────
    @app.get("/api/cases/{case_id}/files")
    def list_files(
        case_id: str,
        bad_ext: bool = False,
        dups: bool = False,
        family: str | None = None,
        source: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        db = open_db(case_id)
        try:
            recs = db.list_files(
                source_id=source,
                bad_extensions_only=bad_ext,
                duplicates_only=dups,
                signature_family=family,
                limit=limit,
                offset=offset,
            )
            return [r.model_dump(mode="json") for r in recs]
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/families")
    def families(case_id: str) -> list[str]:
        """DISTINCT detekované signatury — pro filtr v File System gridu."""
        db = open_db(case_id)
        try:
            rows = db.conn.execute(
                "SELECT DISTINCT signature_type FROM files"
                " WHERE signature_type IS NOT NULL AND signature_type != ''"
                " ORDER BY 1"
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/search")
    def search(
        case_id: str,
        q: str = "",
        hash: str | None = Query(None),  # E9 — exact hash lookup (SHA-256/MD5)
        limit: int = 100,
    ) -> list[dict]:
        """E9 Search rozšíření: FTS + metadata filtry v `q` nebo exact `?hash=`.

        - `q` — kombinace FTS termínů a filtrů (``size:>1MB``, ``mtime:A..B``,
          ``ext:jpg``, ``in-artifact:X``)
        - `hash` — hex SHA-256/MD5 → exact lookup přes index (priorita před `q`)
        """
        db = open_db(case_id)
        try:
            if hash and hash.strip():
                recs = db.search_by_hash(hash, limit=limit)
            elif q.strip():
                from stopa.domain.search_filters import SearchFilterError

                try:
                    recs = db.search(q, limit=limit)
                except SearchFilterError as exc:
                    raise HTTPException(400, f"neplatný filtr: {exc}") from exc
            else:
                return []
            return [r.model_dump(mode="json") for r in recs]
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/timeline")
    def timeline(
        case_id: str,
        type: str | None = Query(None),
        source: str | None = Query(None),
        from_ts: datetime | None = Query(None),
        to_ts: datetime | None = Query(None),
        anomalies_only: bool = Query(False),
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        """Timeline (E2) — chronologické události s UTC i lokálním časem.

        Primárně čte materializovanou ``timeline_events``; prázdná (starý case
        bez re-ingestu) → fallback na ``artifacts``. Lokální čas počítáme přes
        case ``timezone_name`` (default Europe/Prague). Backward-kompatibilní:
        staré GUI konzumuje ``timestamp`` / ``artifact_type`` / ``title``.
        """
        db = open_db(case_id)
        try:
            tz_name = "Europe/Prague"
            case = db.get_case(case_id)
            if case is not None and case.timezone_name:
                tz_name = case.timezone_name

            events = db.list_timeline_events(
                source_id=source,
                event_type=type,
                from_ts=from_ts,
                to_ts=to_ts,
                anomalies_only=anomalies_only,
                limit=limit,
                offset=offset,
            )
            if events:
                out = []
                for e in events:
                    # lokální čas pro zobrazení (UTC zůstává kanonický)
                    local_iso = to_local_iso(
                        datetime.fromisoformat(e["ts_utc"])
                        if e["ts_utc"] else None,
                        tz_name,
                    )
                    row = {**e, "ts_local": local_iso}
                    # backward-kompatibilní aliasy pro staré GUI (artifact_type/timestamp)
                    row["artifact_type"] = e.get("event_type")
                    row["timestamp"] = e.get("ts_utc")
                    out.append(row)
                return out

            # fallback: starý case bez materializované timeline → artifacts
            arts = db.list_artifacts(
                source_id=source,
                artifact_type=type,
                from_ts=from_ts,
                to_ts=to_ts,
                anomalies_only=anomalies_only,
                limit=limit,
                offset=offset,
            )
            out = []
            for a in arts:
                d = a.model_dump(mode="json")
                local_iso = to_local_iso(a.timestamp, tz_name) if a.timestamp else None
                # backward-kompatibilní pole pro staré GUI (timestamp/artifact_type/title)
                d["ts_utc"] = d.get("timestamp")
                d["ts_local"] = local_iso
                d["anomaly_flags"] = list(a.anomaly_flags or ())
                out.append(d)
            return out
        finally:
            db.close()

    # ── STP-018 Timeline Intelligence 2.0 ─────────────────────────────
    @app.post("/api/cases/{case_id}/timeline/intel")
    def timeline_intel(case_id: str, window_seconds: float = Query(60.0)) -> dict:
        """STP-018 — explicitní spuštění Timeline Intelligence 2.0 post-passu.

        Rozpory (souběžná aktivita subjektu) + duplikáty napříč zdroji nad
        materializovanou timeline. Idempotentní, deterministický výsledek.
        """
        _require("analysis.run", "timeline_intel")
        from stopa.pipeline import run_timeline_intel

        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            summary = run_timeline_intel(db, window_seconds=window_seconds)
            db.log_operation(
                "timeline_intel_run",
                actor=case.examiner if case else None,
                details={**summary, "window_seconds": window_seconds},
            )
            return summary
        finally:
            db.close()

    # ── E4 Entity + Correlation Engine ────────────────────────────────
    @app.post("/api/cases/{case_id}/correlate")
    def correlate(case_id: str) -> dict:
        """Explicitní krok korelace (ROADMAP E4 bod 4) — re-run = clear + insert."""
        _require("analysis.run", "correlate")
        from stopa.domain.correlation import run_correlation

        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            summary = run_correlation(db, case_id)
            db.log_operation(
                "correlation_run",
                actor=case.examiner if case else None,
                details={
                    "entities": summary["entities"],
                    "correlations_total": summary["correlations_total"],
                    "by_relation": summary["by_relation"],
                    "merge_candidates": len(summary.get("merge_candidates", [])),
                },
            )
            return summary
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/correlations")
    def list_correlations(case_id: str) -> list[dict]:
        """Propojení entit s evidence listy (dohledatelnost každého nálezu)."""
        db = open_db(case_id)
        try:
            return db.list_correlations(case_id)
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/entities")
    def list_entities(case_id: str) -> list[dict]:
        """Kanonické entity extrahované z artifactů (E4)."""
        db = open_db(case_id)
        try:
            return db.list_entities(case_id)
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/entities/merge-candidates")
    def merge_candidates(case_id: str) -> list[dict]:
        """P0 I3 — detekce duplicitních entit s důvody (heuristické páry)."""
        from stopa.domain.entity_resolution import find_merge_candidates

        db = open_db(case_id)
        try:
            return [
                {"kind": m.kind, "value_a": m.value_a, "value_b": m.value_b, "reason": m.reason}
                for m in find_merge_candidates(db.list_entities(case_id))
            ]
        finally:
            db.close()

    # ── partition map (GUI File System & Carving — vizuální mapa) ────────────
    @app.get("/api/cases/{case_id}/partition-map")
    def partition_map(case_id: str) -> list[dict]:
        """Partition mapy všech diskových obrazů v případu."""
        db = open_db(case_id)
        try:
            arts = db.list_artifacts(artifact_type="disk_image")
            out: list[dict] = []
            for a in arts:
                d = a.details or {}
                pm = d.get("partition_map") or []
                if not pm and d.get("partitions"):
                    # starší artifact bez strukturované mapy — jen textový popis
                    pm = [{"desc": d["partitions"], "fstype": None,
                           "offset_sectors": 0, "size_sectors": 0}]
                out.append({
                    "source_id": a.source_id,
                    "image_name": a.rel_path,
                    "description": d.get("description"),
                    "files_total": d.get("files_total", 0),
                    "partitions": pm,
                })
            return out
        finally:
            db.close()

    # ── file inspector (GUI pravý panel) ───────────────────────
    @app.get("/api/cases/{case_id}/files/{file_id}")
    def get_file(case_id: str, file_id: str) -> dict:
        """Detail jednoho souboru + flagy (File Inspector)."""
        db = open_db(case_id)
        try:
            rec = db.get_file(file_id)
            if rec is None or rec.source_id not in {s.id for s in db.list_sources(case_id)}:
                raise HTTPException(404, f"soubor {file_id} nenalezen")
            source = db.get_source(rec.source_id)
            return {
                **rec.model_dump(mode="json"),
                "flags": list(db.get_file_flags(file_id)),
                "source_path": source.path if source else None,
                "in_image": bool(rec.meta_addr),  # soubor v diskovém obrazu (TSK)
            }
        finally:
            db.close()

    # ── E8 — souborová metadata (PDF/OOXML/ID3/MP4/EXIF) ───────────────
    META_MAX_BYTES = 32 * 1024 * 1024  # metadata bývají na začátku; strop pro velké soubory

    @app.get("/api/cases/{case_id}/files/{file_id}/metadata")
    def file_metadata(case_id: str, file_id: str) -> dict:
        """Metadata z obsahu souboru (čistý Python + volitelné EXIF)."""
        from stopa.domain.file_meta import extract_metadata

        db = open_db(case_id)
        try:
            rec = db.get_file(file_id)
            if rec is None or rec.source_id not in {s.id for s in db.list_sources(case_id)}:
                raise HTTPException(404, f"soubor {file_id} nenalezen")
            data = _read_file_bytes(db, rec, offset=0, length=META_MAX_BYTES)
            meta = extract_metadata(data, rec.name or "")
            return {"file_id": file_id, "name": rec.name, "metadata": meta}
        finally:
            db.close()

    @app.post("/api/cases/{case_id}/files/compare-metadata")
    def compare_metadata(case_id: str, a: str, b: str) -> dict:
        """Porovnání metadat dvou souborů (řádky field/a/b/match)."""
        from stopa.domain.file_meta import diff_metadata, extract_metadata

        db = open_db(case_id)
        try:
            ra = db.get_file(a)
            rb = db.get_file(b)
            srcs = {s.id for s in db.list_sources(case_id)}
            if ra is None or rb is None or ra.source_id not in srcs or rb.source_id not in srcs:
                raise HTTPException(404, "soubor nenalezen")
            ma = extract_metadata(_read_file_bytes(db, ra, 0, META_MAX_BYTES), ra.name or "")
            mb = extract_metadata(_read_file_bytes(db, rb, 0, META_MAX_BYTES), rb.name or "")
            return {
                "a": {"file_id": a, "name": ra.name},
                "b": {"file_id": b, "name": rb.name},
                "diff": diff_metadata(ma, mb),
            }
        finally:
            db.close()

    @app.post("/api/files/{file_id}/flag")
    def set_flag(file_id: str, flag: str = "evidence", on: bool = True) -> dict:
        """Přepne flag souboru — „Mark as Evidence“ / „Add to Report“."""
        _require("file.flag", "set_flag")
        if flag not in ("evidence", "report"):
            raise HTTPException(400, f"neznámý flag: {flag}")
        # flag je globální (file_id je unikátní napříč case DB) — najdi správnou DB
        for path in sorted(base.glob("case-*.db")):
            db = CaseDB(path)
            try:
                if db.get_file(file_id) is None:
                    continue
                db.set_file_flag(file_id, flag, on)
                return {"file_id": file_id, "flag": flag, "on": on,
                        "flags": list(db.get_file_flags(file_id))}
            finally:
                db.close()
        raise HTTPException(404, f"soubor {file_id} nenalezen")

    @app.get("/api/cases/{case_id}/marked")
    def marked(case_id: str, flag: str | None = None) -> list[dict]:
        """Označené soubory (Evidence / Report modul)."""
        db = open_db(case_id)
        try:
            out = []
            for rec, flags in db.list_marked():
                if flag and flag not in flags:
                    continue
                out.append({**rec.model_dump(mode="json"), "flags": list(flags)})
            return out
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/files/{file_id}/hex")
    def file_hex(case_id: str, file_id: str, offset: int = 0, length: int = 256) -> dict:
        """Hex dump úryvku souboru (File Inspector — hex grid)."""
        db = open_db(case_id)
        try:
            rec = db.get_file(file_id)
            if rec is None:
                raise HTTPException(404, f"soubor {file_id} nenalezen")
            data = _read_file_bytes(db, rec, offset=offset, length=length)
            return {"file_id": file_id, "offset": offset, "length": len(data),
                    "hex": _hex_dump(data)}
        finally:
            db.close()

    # ── STP-051 — File Preview (oblast G) ───────────────────────────────
    PREVIEW_HEAD_BYTES = 64 * 1024      # hlavička pro klasifikaci
    PREVIEW_MAX_MEDIA_BYTES = 20 * 1024 * 1024   # strop inline media (RAM peak)
    PREVIEW_TEXT_SAMPLE_BYTES = 256 * 1024       # vzorka pro textový preview

    @app.get("/api/cases/{case_id}/files/{file_id}/preview")
    def file_preview(case_id: str, file_id: str):
        """Preview souboru v UI — inline media (image/audio/video) nebo JSON text.

        Klasifikace přes `domain.file_preview` (čistá logika). Neznámý/nelze
        zobrazit → 415; příliš velký media → 413.
        """
        from fastapi import Response

        from stopa.domain.file_preview import (
            classify_preview,
            extract_text_preview,
            preview_media_type,
        )

        db = open_db(case_id)
        try:
            rec = db.get_file(file_id)
            if rec is None:
                raise HTTPException(404, f"soubor {file_id} nenalezen")
            head = _read_file_bytes(db, rec, offset=0, length=PREVIEW_HEAD_BYTES)
            kind = classify_preview(head, rec.name or "")
            if kind is None:
                raise HTTPException(415, "preview není pro tento formát k dispozici")

            if kind == "text":
                sample = _read_file_bytes(db, rec, offset=0, length=PREVIEW_TEXT_SAMPLE_BYTES)
                text, truncated = extract_text_preview(sample)
                return {"kind": "text", "name": rec.name, "truncated": truncated, "text": text}

            # image / audio / video — inline bytes s MIME
            if (rec.size_bytes or 0) > PREVIEW_MAX_MEDIA_BYTES:
                raise HTTPException(413, "soubor je příliš velký pro preview")
            mime = preview_media_type(rec.signature_type, rec.name or "") or "application/octet-stream"
            data = _read_file_bytes(db, rec, offset=0, length=None)
            return Response(content=data, media_type=mime)
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/files/{file_id}/export")
    def export_file(case_id: str, file_id: str):
        """Stáhnout obsah souboru (Export File)."""
        from fastapi import Response

        db = open_db(case_id)
        try:
            rec = db.get_file(file_id)
            if rec is None:
                raise HTTPException(404, f"soubor {file_id} nenalezen")
            data = _read_file_bytes(db, rec, offset=0, length=None)
            # audit P1 — RFC 5987 quoting: nequoted `"` v názvu = header injection;
            # filename* nese UTF-8 (české názvy), fallback filename je ASCII-safe.
            # isprintable() vyfiltruje i control chars (\r\n) → CRLF injection pryč.
            name = rec.name or "soubor"
            ascii_name = "".join(c if c.isascii() and c.isprintable() and c not in '"\\' else "_" for c in name)
            return Response(
                content=data,
                media_type="application/octet-stream",
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="{ascii_name}"; '
                        f"filename*=UTF-8''{quote(name)}"
                    )
                },
            )
        finally:
            db.close()

    # ── STP-058 — interop exporty (l2tcsv / UCO / CSV / JSON / ...) ───────
    @app.get("/api/cases/{case_id}/interop-export")
    def interop_export(
        case_id: str, what: str = "artifacts", format: str = "csv"
    ):
        """Export dat případu do interop formátů (GUI — oblast Q ★★).

        Zrcadlí ``stopa export`` CLI (stejná domain funkce), ale vrací
        soubor jako HTTP Response s Content-Disposition. Formáty:
        csv / json / jsonl / xml / stix / l2tcsv / uco. Datasety:
        artifacts / timeline / correlations. Audit + integrity checkpoint.
        """
        from fastapi import Response

        from stopa.domain.export import (
            ARTIFACT_COLUMNS,
            CORRELATION_COLUMNS,
            TIMELINE_COLUMNS,
            artifact_records,
            correlation_records,
            timeline_records,
            to_csv,
            to_json,
            to_jsonl,
            to_l2tcsv,
            to_stix_bundle,
            to_xml,
        )

        _require("analysis.run", "interop_export")
        if what not in ("artifacts", "timeline", "correlations"):
            raise HTTPException(400, f"neplatný dataset: {what}")
        valid_formats = ("csv", "json", "jsonl", "xml", "stix", "l2tcsv", "uco")
        if format not in valid_formats:
            raise HTTPException(400, f"neplatný formát: {format}")

        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            if what == "artifacts":
                records = artifact_records(db.list_artifacts())
                columns = ARTIFACT_COLUMNS
            elif what == "timeline":
                records = timeline_records(db.list_timeline_events())
                columns = TIMELINE_COLUMNS
            else:  # correlations
                records = correlation_records(db.list_correlations(case_id))
                columns = CORRELATION_COLUMNS

            if format == "csv":
                text = to_csv(records, columns)
            elif format == "jsonl":
                text = to_jsonl(records)
            elif format == "xml":
                text = to_xml(records, dataset=what)
            elif format == "stix":
                text = to_stix_bundle(records, dataset=what)
            elif format == "l2tcsv":
                text = to_l2tcsv(records, dataset=what)
            elif format == "uco":
                from stopa.domain.uco import to_uco_json

                text = to_uco_json(records, dataset=what)
            else:  # json (default)
                text = to_json(records)

            media_type = {
                "csv": "text/csv",
                "json": "application/json",
                "uco": "application/json",
                "stix": "application/json",
                "jsonl": "application/x-ndjson",
                "xml": "application/xml",
                "l2tcsv": "text/plain",
            }[format]

            # audit P1 — RFC 5987 quoting (stejný vzor jako export_file)
            ascii_name = f"{case_id}_{what}.{format}"
            db.log_operation(
                "interop_exported",
                actor=case.examiner if case else None,
                details={"what": what, "format": format, "records": len(records)},
            )
            # P0 Core C4: kontrolní bod po exportu.
            db.add_integrity_checkpoint("export")
            return Response(
                content=text.encode("utf-8"),
                media_type=media_type,
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="{ascii_name}"; '
                        f"filename*=UTF-8''{quote(ascii_name)}"
                    )
                },
            )
        finally:
            db.close()

    # ── STP-064 — L2T CSV preview (oblast Q ★★) ───────────────
    @app.get("/api/cases/{case_id}/l2tcsv-preview")
    def l2tcsv_preview(case_id: str, what: str = "artifacts", limit: int = 50) -> dict:
        """Náhled l2tcsv exportu (GUI — oblast Q ★★).

        Zrcadlí ``stopa export --format l2tcsv`` / interop-export endpoint
        (stejná domain funkce ``to_l2tcsv``): vrátí první N řádků toho, co se
        reálně vyexportuje — uživatel si ověří data před downloadem/pushem.
        Read-only: bez audit záznamu i integrity checkpointu (není export).

        Datasety: artifacts / timeline / correlations. Limit clamp 1..500.
        """
        import csv as _csv
        import io as _io

        from stopa.domain.export import (
            L2TCSV_COLUMNS,
            artifact_records,
            correlation_records,
            timeline_records,
            to_l2tcsv,
        )

        _require("analysis.run", "l2tcsv_preview")
        if what not in ("artifacts", "timeline", "correlations"):
            raise HTTPException(400, f"neplatný dataset: {what}")
        limit = max(1, min(int(limit), 500))

        db = open_db(case_id)
        try:
            if what == "artifacts":
                records = artifact_records(db.list_artifacts())
            elif what == "timeline":
                records = timeline_records(db.list_timeline_events())
            else:  # correlations
                records = correlation_records(db.list_correlations(case_id))

            text = to_l2tcsv(records, dataset=what)
            rows = list(_csv.reader(_io.StringIO(text)))
            header = rows[0] if rows else []
            body = rows[1 : limit + 1]
            return {
                "case_id": case_id,
                "dataset": what,
                "columns": list(L2TCSV_COLUMNS),
                "total_records": len(records),
                "limit": limit,
                "rows": [dict(zip(header, r)) for r in body],
            }
        finally:
            db.close()

    # ── STP-059 — Timesketch push (oblast Q, interop) ───────────────
    @app.post("/api/cases/{case_id}/timesketch-push")
    def timesketch_push(case_id: str, body: TimesketchPushIn) -> dict:
        """Push datasetu případu do nového Timesketch sketchu (GUI — oblast Q ★★).

        Zrcadlí ``stopa timesketch-push`` CLI (stejná domain funkce):
        vytvoří sketch a nahraje l2tcsv timeline. Datasety: artifacts /
        timeline / correlations. Audit + integrity checkpoint.
        Timesketch nedostupná → 503; push selhal → 502 srozumitelnou zprávou.
        """
        from stopa.domain.export import (
            artifact_records,
            correlation_records,
            timeline_records,
        )
        from stopa.domain.timesketch_push import push_to_timesketch

        _require("analysis.run", "timesketch_push")
        if body.what not in ("artifacts", "timeline", "correlations"):
            raise HTTPException(400, f"neplatný dataset: {body.what}")

        client = TimesketchClient()
        health = client.health()
        if not health["available"]:
            raise HTTPException(
                503, "Timesketch nedostupná — spusťte ji (STOPA_TIMESKETCH_URL)"
            )

        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            if body.what == "artifacts":
                records = artifact_records(db.list_artifacts())
            elif body.what == "timeline":
                records = timeline_records(db.list_timeline_events())
            else:  # correlations
                records = correlation_records(db.list_correlations(case_id))

            try:
                summary = push_to_timesketch(
                    client, case.name if case else case_id, body.what, records
                )
            except TimesketchUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
            except (TimesketchError, ValueError) as exc:
                raise HTTPException(502, f"Timesketch push selhal: {exc}") from exc

            db.log_operation(
                "timesketch_pushed",
                actor=case.examiner if case else None,
                details={**summary, "what": body.what},
            )
            # P0 Core C4: kontrolní bod po pushi.
            db.add_integrity_checkpoint("timesketch-push")
            return summary
        finally:
            db.close()

    # ── STP-061 — Timesketch timeline status (live polling, oblast Q ★★) ───
    @app.get("/api/cases/{case_id}/timesketch-status")
    def timesketch_status(case_id: str):
        """Live stav indexace naposledy pushnuté timeline (oblast Q ★★).

        Read-only endpoint pro UI polling: najde poslední audit záznam
        ``timesketch_pushed`` (sketch_id + timeline_id) a dotáže Timesketch
        ``GET /api/v1/sketches/{sid}/timelines/{tid}/`` → stav indexace
        (``new``/``processing``/``ready``/``fail``).

        Chybové cesty: 404 — case neexistuje nebo ještě žádný push;
        503 — Timesketch nedostupná; 502 — dotaz selhal (HTTP != 200 /
        ne-JSON). Read-only → RBAC ``case.read`` (všechny role), bez auditu.
        """
        _require("case.read", "timesketch_status")

        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            if case is None:
                raise HTTPException(404, f"case neexistuje: {case_id}")

            # poslední push — audit log je nejnovější první
            last_push: dict | None = None
            for entry in db.list_audit_log(limit=200):
                if entry.get("action") == "timesketch_pushed":
                    last_push = entry
                    break
            details = (last_push or {}).get("details") or {}
            sketch_id = details.get("sketch_id")
            timeline_id = details.get("timeline_id")
            if not isinstance(sketch_id, int) or not isinstance(timeline_id, int):
                raise HTTPException(
                    404, "zatím žádný Timesketch push v audit logu"
                )

            client = TimesketchClient()
            health = client.health()
            if not health["available"]:
                raise HTTPException(
                    503, "Timesketch nedostupná — spusťte ji (STOPA_TIMESKETCH_URL)"
                )
            try:
                st = client.timeline_status(sketch_id, timeline_id)
            except TimesketchUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
            except TimesketchError as exc:
                raise HTTPException(502, f"Timesketch status selhal: {exc}") from exc

            return {
                "sketch_id": sketch_id,
                "timeline_id": timeline_id,
                "status": st["status"],
                "updated_at": st["updated_at"],
            }
        finally:
            db.close()

    # ── STP-063 — Plaso import (l2tcsv upload, oblast Q ★★) ────────────────
    @app.post("/api/cases/{case_id}/plaso-import")
    async def plaso_import(case_id: str, file: UploadFile = File(...)) -> dict:
        """Import l2tcsv souboru do případu (GUI — oblast Q ★★).

        Zrcadlí ``stopa plaso-import`` CLI (stejná domain funkce): evidence
        source + artifacts (idempotentní upsert) + timeline events. Audit +
        integrity checkpoint. Chybové cesty: 404 case neexistuje; 415 špatný
        typ souboru; 422 prázdný soubor / nevalidní UTF-8.
        """
        from stopa.domain.plaso_import import import_l2tcsv

        _require("analysis.run", "plaso_import")

        filename = file.filename or ""
        if not filename.endswith((".csv", ".l2t.csv")):
            raise HTTPException(415, "očekáván l2tcsv soubor (.csv)")

        raw = await file.read()
        if not raw.strip():
            raise HTTPException(422, "soubor je prázdný")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(422, f"soubor není validní UTF-8: {exc}") from exc

        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            summary = import_l2tcsv(db, case_id, text, source_path=filename)
            db.log_operation(
                "plaso_import",
                actor=case.examiner if case else None,
                details={**summary, "file": filename},
            )
            # P0 Core C4: kontrolní bod po importu.
            db.add_integrity_checkpoint("plaso-import")
            return summary
        finally:
            db.close()

    # ── report (FÁZE 7) ───────────────────────────────────────
    @app.get("/api/cases/{case_id}/report")
    def report(case_id: str, format: str = "html"):
        from fastapi import Response

        from stopa.presentation.case_report import build_html

        db = open_db(case_id)
        try:
            data = build_report_data_safe(db, case_id)
        finally:
            db.close()
        html_doc = build_html(data)
        filename = f"{case_id}_report.{format}"
        if format == "pdf":
            import io

            from weasyprint import HTML  # type: ignore[import-untyped]

            buf = io.BytesIO()
            try:
                HTML(string=html_doc).write_pdf(buf)
            except Exception as e:
                raise HTTPException(500, f"PDF report selhal: {e}") from e
            return Response(
                content=buf.getvalue(),
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        return Response(
            content=html_doc.encode("utf-8"),
            media_type="text/html",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ── STP-050 — Validation Center (C3 registry + C6 report) ──
    @app.get("/api/cases/{case_id}/validation")
    def validation_report(case_id: str) -> dict:
        """Validační report případu — coverage parserů, statusy, per-artifact řádky.

        Čistá agregace nad DB (C6 ``build_validation_report``); selhání registry
        degraduje na 500 s logem (defenzivní obal).
        """
        from stopa.data.validation_report import build_validation_report

        db = open_db(case_id)
        try:
            return build_validation_report(db, case_id)
        except Exception as e:  # doplňková vrstva — log + degradace
            log.warning("validation report selhal pro %s: %s", case_id, e)
            raise HTTPException(500, f"validační report selhal: {e}") from e
        finally:
            db.close()

    @app.get("/api/validation/registry")
    def validation_registry() -> dict:
        """Parser Validation Registry (C3) — řádky s identitou a validací parserů.

        Synchronizace registry × pipeline; nesoulad → 500 s logem (defenzivní obal).
        """
        from stopa.domain.validation_registry import build_registry, registry_report

        try:
            rows = registry_report(build_registry())
        except Exception as e:  # doplňková vrstva — log + degradace
            log.warning("parser validation registry selhal: %s", e)
            raise HTTPException(500, f"parser registry selhal: {e}") from e
        return {"count": len(rows), "parsers": rows}

    # ── STP-052 — Audit Center (oblast O) ─────────────────────
    @app.get("/api/cases/{case_id}/audit")
    def audit_center(case_id: str, limit: int = 100) -> dict:
        """Audit Center — neměnná stopa + integrity v jednom reportu.

        Agreguje (čistá čtení nad DB):
        - ``chain`` — výsledek ověření hash řetězce audit logu (C4),
        - ``entries`` — nejnovější záznamy audit trailu (limit, default 100),
        - ``checkpoints`` — Ed25519 kontrolní body + nezávislé ověření podpisů.

        Selhání degraduje na 500 s logem (defenzivní obal).
        """
        db = open_db(case_id)
        try:
            report = db.verify_audit_chain()
            entries = db.list_audit_log(limit=max(1, min(int(limit), 1000)))
            checkpoints = db.list_integrity_checkpoints()
            checkpoint_checks = db.verify_integrity_checkpoints()
            return {
                "chain": {
                    "ok": report.ok,
                    "rows_checked": report.rows_checked,
                    "broken_at_id": report.broken_at_id,
                    "reason": report.reason,
                },
                "total_entries": len(entries),
                "entries": entries,
                "public_key": db.integrity_public_key(),
                "checkpoints": checkpoints,
                "checkpoint_checks": checkpoint_checks,
            }
        except Exception as e:  # doplňková vrstva — log + degradace
            log.warning("audit center selhal pro %s: %s", case_id, e)
            raise HTTPException(500, f"audit report selhal: {e}") from e
        finally:
            db.close()

    # ── E11 — AI Forensic Assistant (LM Studio) ───────────────
    @app.get("/api/ai/status")
    def ai_status() -> dict:
        """Dostupnost LM Studio — GUI ukáže „AI nedostupná“ bez chyb."""
        return LmStudioClient().health()

    @app.post("/api/cases/{case_id}/ai/query")
    def ai_query(case_id: str, body: AiQueryIn) -> dict:
        """Jeden dotaz na AI asistenta (3 režimy).

        - ``nl_search`` → vrácen i použitý STOPA FTS query + citace souborů
        - ``summary``   → shrnutí případu s citacemi artifactů
        - ``explain``   → vysvětlení jednoho artifactu (artifact_id)

        Citace = validované ID (soubory/artifacty existují v DB); GUI je
        vykreslí jako klikací odkazy na File Inspector.
        """
        if body.mode not in ("nl_search", "summary", "explain"):
            raise HTTPException(400, f"neznámý režim: {body.mode}")
        _require("analysis.run", "ai_query")
        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            if case is None:
                raise HTTPException(404, "případ neexistuje")

            client = LmStudioClient()
            health = client.health()
            if not health["available"]:
                raise HTTPException(503, "AI nedostupná — spusťte LM Studio (localhost:1234)")

            # STP-019 — PII redaktor (settings toggle, default ON) + auditní model name
            redact_pii = bool(_load_settings().get("ai_redact_pii", True))
            model_name = str(health.get("model") or None)
            try:
                if body.mode == "nl_search":
                    return _ai_nl_search(
                        db, case_id, case.name, body.question, client,
                        redact_pii=redact_pii, model=model_name,
                    )
                if body.mode == "summary":
                    return _ai_summary(
                        db, case_id, case.name, client,
                        redact_pii=redact_pii, model=model_name,
                    )
                return _ai_explain(
                    db, case_id, body.artifact_id, client,
                    redact_pii=redact_pii, model=model_name,
                )
            except LmStudioUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
        finally:
            db.close()

    # ── P0 Intelligence I1 — AI orchestrace (multi-agent) ───────────────
    @app.post("/api/cases/{case_id}/ai/analyze")
    def ai_analyze(case_id: str, body: AiAnalyzeIn) -> dict:
        """Analytický úkol přes AI orchestraci (5 agentů).

        Explicitní ``agent`` má přednost; jinak auto-routing podle dotazu.
        Výstup = validovaný JSON modelu vybraného agenta + auditní metadata
        (citace, délka promptu, doba inference). Fail-closed: nevalidní
        odpověď LLM → 502 s úryvkem (auditovatelné).
        """
        from stopa.intelligence import (
            OrchestrationError,
            audit_ai_query,
            build_case_context,
            orchestrate,
            prompt_hash,
            retrieve,
        )

        if not body.question.strip():
            raise HTTPException(400, "chybí otázka")
        _require("analysis.run", "ai_analyze")
        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            if case is None:
                raise HTTPException(404, "případ neexistuje")

            client = LmStudioClient()
            health = client.health()
            if not health["available"]:
                raise HTTPException(503, "AI nedostupná — spusťte LM Studio (localhost:1234)")

            context = build_case_context(db, case_id)
            # P0 Intelligence I2 — Forensic RAG: retrieval napříč vrstvami
            rag = retrieve(body.question, db=db, case_id=case_id)
            # STP-019 — PII redaktor (settings toggle, default ON)
            redact_pii = bool(_load_settings().get("ai_redact_pii", True))
            try:
                result = orchestrate(
                    client.chat,
                    context,
                    body.question,
                    agent_id=body.agent,
                    rag=rag,
                    redact_pii=redact_pii,
                )
            except LmStudioUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
            except OrchestrationError as exc:
                raise HTTPException(502, f"AI orchestrace selhala: {exc}") from exc

            # audit AI dotazu (evidence modelu + promptu) — analysis_operations
            from stopa.intelligence.ai_orchestrator import build_prompt, route_agent

            profile = route_agent(body.question, body.agent)
            ph = prompt_hash(
                build_prompt(profile, context, body.question, rag=rag, redact_pii=redact_pii)
            )
            audit_ai_query(
                db,
                case_id=case_id,
                question=body.question,
                model=str(health.get("model") or None),
                prompt_sha256=ph,
                citations=result.citations,
                agent=result.agent_id,
            )

            db.log_operation(
                "ai_analyzed",
                actor="web",
                details={
                    "agent": result.agent_id,
                    "question": body.question[:200],
                    "citations": result.citations,
                    "duration_ms": round(result.duration_ms, 1),
                },
            )
            return {
                "agent": result.agent_id,
                "output": result.output.model_dump(mode="json"),
                "citations": result.citations,
                "rag": {
                    "case": len(rag.case_chunks),
                    "technical": len(rag.technical_chunks),
                    "knowledge": len(rag.knowledge_chunks),
                },
                "prompt_chars": result.prompt_chars,
                "duration_ms": round(result.duration_ms, 1),
            }
        finally:
            db.close()

    # ── E12 — System Diagnostics ──────────────────────────────
    @app.get("/api/diagnostics")
    def diagnostics() -> dict:
        """Verze knihoven + dostupnost volitelných komponent (TSK/EWF/FDE).

        Poslední operace z audit_log všech případů (nejnovější 10) — GUI je
        zobrazí jako „poslední aktivity“; chyby = processing_completed s errors>0.
        """
        from stopa.data.diagnostics import collect_diagnostics

        out = collect_diagnostics()
        recent: list[dict] = []
        for path in sorted(base.glob("case-*.db")):
            db = CaseDB(path)
            try:
                for row in db.list_audit_log(limit=10):
                    row["case_id"] = path.stem
                    recent.append(row)
            finally:
                db.close()
        recent.sort(key=lambda r: r.get("ts") or "", reverse=True)
        out["recent_operations"] = recent[:25]
        return out

    # ── E12 — Settings (persistence do settings.json v db_dir) ──
    def _settings_path() -> Path:
        return base / "settings.json"

    def _load_settings() -> dict:
        p = _settings_path()
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            log.warning("settings.json je poškozený — použiju defaulty")
            return {}

    def _save_settings(data: dict) -> None:
        _settings_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── STP-053 — RBAC enforcement (permission matrix z domain/rbac.py) ──
    def _current_role() -> str:
        """Aktuální role; bez uložené hodnoty → default (examiner)."""
        return _load_settings().get("role") or DEFAULT_ROLE

    def _require(permission: str, context: str = "") -> None:
        """Validuje oprávnění aktuální role; chybí → HTTP 403."""
        try:
            require_permission(_current_role(), permission, context=context)
        except RBACDenied as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.get("/api/settings")
    def get_settings() -> dict:
        """Uživatelská nastavení (defaulty + uložené přepsání)."""
        s = _load_settings()
        role = s.get("role") or DEFAULT_ROLE
        return {
            "timezone_name": s.get("timezone_name", "Europe/Prague"),
            "ai_url": s.get("ai_url") or os.environ.get(
                "STOPA_LMSTUDIO_URL", "http://localhost:1234/v1"
            ),
            "role": role,
            # STP-053 — oprávnění aktuální role (permission matrix)
            "permissions": permissions_for(role),
            "bind_address": s.get("bind_address", "127.0.0.1"),
            # STP-019 — PII redaktor je default ON (fail-safe: maskovat)
            "ai_redact_pii": bool(s.get("ai_redact_pii", True)),
        }

    @app.get("/api/roles")
    def get_roles() -> dict:
        """STP-056 — matice rolí pro UI přepínač role (Settings + topbar).

        Vrací role v pořadí od nejnižší po nejvyšší privilegie, labely a
        oprávnění každé role (z permission matrix — jediný zdroj pravdy).
        Čistě čtení; žádné oprávnění nevyžaduje.
        """
        return {
            "default": DEFAULT_ROLE,
            "roles": [
                {"id": r, "label": ROLE_LABELS[r], "permissions": permissions_for(r)}
                for r in ROLES
            ],
            # všechna oprávnění v matici (pro UI legendu) — deterministicky seřazené
            "all_permissions": sorted(PERMISSIONS),
        }

    @app.put("/api/settings")
    def put_settings(body: SettingsIn) -> dict:
        """Uloží nastavení (jen zadaná pole). Bind address platí po restartu."""
        _require("settings.write", "put_settings")
        if body.role is not None and normalize_role(body.role) is None:
            raise HTTPException(400, f"neznámá role: {body.role!r} (povoleno: analyst/examiner/admin)")
        s = _load_settings()
        if body.timezone_name is not None:
            s["timezone_name"] = body.timezone_name
        if body.ai_url is not None:
            s["ai_url"] = body.ai_url
        if body.role is not None:
            s["role"] = body.role
        if body.bind_address is not None:
            s["bind_address"] = body.bind_address
        if body.ai_redact_pii is not None:
            s["ai_redact_pii"] = bool(body.ai_redact_pii)
        _save_settings(s)
        return get_settings()

    # ── E12 — Cases CRUD (update/delete nad existujícím GET/POST) ──
    @app.patch("/api/cases/{case_id}")
    def update_case(case_id: str, body: CaseUpdateIn) -> dict:
        """Aktualizace metadat případu (name/examiner/notes/timezone)."""
        _require("case.update", "update_case")
        db = open_db(case_id)
        try:
            ok = db.update_case(
                case_id,
                name=body.name,
                examiner=body.examiner,
                notes=body.notes,
                timezone_name=body.timezone_name,
            )
            if not ok:
                raise HTTPException(404, "případ neexistuje")
            db.log_operation("case_updated", details={"case_id": case_id})
            return get_case(case_id)
        finally:
            db.close()

    @app.delete("/api/cases/{case_id}")
    def delete_case(case_id: str) -> dict:
        """Smaže případ i zdroje (kaskáda na files/artifacts/timeline)."""
        _require("case.delete", "delete_case")
        validate_case_id(case_id)
        path = base / f"{case_id}.db"
        db = CaseDB(path) if path.exists() else None
        try:
            if db is None or db.get_case(case_id) is None:
                raise HTTPException(404, "případ neexistuje")
            db.log_operation("case_deleted", details={"case_id": case_id})
            db.delete_case(case_id)
        finally:
            if db is not None:
                db.close()
        return {"deleted": case_id}

    # ── statická SPA ──────────────────────────────────────────
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


def _ground_answer_safe(
    text: str, cited_ids: list[str], artifacts_by_id: dict[str, dict]
) -> dict | None:
    """STP-049 — grounding odpovědi LLM proti citovaným záznamům (defenzivní obal).

    Vrací report ``to_dict()`` nebo ``None`` (žádné citace / interní chyba).
    Grounding je doplňková vrstva — nesmí rozbít hlavní odpověď, proto se
    jakákoli výjimka loguje a degraduje na ``None``.
    """
    if not cited_ids:
        return None
    try:
        from stopa.domain.ai_grounding import ground_answer

        report = ground_answer(text, list(cited_ids), artifacts_by_id)
    except Exception:  # doplňková vrstva, log + degradace
        log.exception("AI grounding selhalo (odpověď se vrací bez reportu)")
        return None
    return report.to_dict()


def _ai_nl_search(
    db: CaseDB, case_id: str, case_name: str, question: str, client: LmStudioClient, *, redact_pii: bool = True, model: str | None = None
) -> dict:
    """Režim ``nl_search`` — přirozená řeč → STOPA FTS query + výsledky.

    Citace = soubory, které dotaz vrátil (GUI je propojí na File Inspector).
    STP-019: PII v promptu se maskuje podle ``redact_pii``; audit do analysis_operations.
    """
    from stopa.domain.search_filters import SearchFilterError
    from stopa.intelligence.rag import audit_ai_query, prompt_hash

    if not question.strip():
        raise HTTPException(400, "chybí otázka")
    messages = build_nl_search_prompt(question, case_name, redact_pii=redact_pii)
    text = client.chat(messages)
    query, explanation, confidence = parse_nl_search(text)
    if not query:
        raise HTTPException(502, f"AI nevrátila validní query (odpověď: {text[:160]!r})")

    try:
        records = db.search(query, limit=50)
    except SearchFilterError as exc:
        raise HTTPException(400, f"AI vygenerovala neplatný dotaz „{query}“: {exc}") from exc

    citations = [
        {"file_id": r.id, "rel_path": r.rel_path, "name": r.name} for r in records[:20]
    ]
    # STP-049 — grounding: tvrzení v odpovědi vs mtime citovaných souborů
    file_by_id = {
        r.id: {"id": r.id, "timestamp": r.mtime.isoformat() if r.mtime else None}
        for r in records
    }
    grounding = _ground_answer_safe(text, [c["file_id"] for c in citations], file_by_id)
    # STP-019 — audit AI volání (model + hash skutečně odeslaného promptu)
    audit_ai_query(
        db,
        case_id=case_id,
        question=question,
        model=model or "unknown",
        prompt_sha256=prompt_hash(messages),
        citations=[c["file_id"] for c in citations],
        agent="e11:nl_search",
    )
    return {
        "mode": "nl_search",
        "answer": explanation or f"Vyhledáno: {query}",
        "query": query,
        "confidence": confidence,
        "citations": citations,
        "files": [r.model_dump(mode="json") for r in records],
        "grounding": grounding,
    }


def _ai_summary(
    db: CaseDB, case_id: str, case_name: str, client: LmStudioClient, *, redact_pii: bool = True, model: str | None = None
) -> dict:
    """Režim ``summary`` — shrnutí případu s citacemi artifactů ze vzorku.

    STP-019: PII v promptu se maskuje podle ``redact_pii``; audit do analysis_operations.
    """
    from stopa.intelligence.rag import audit_ai_query, prompt_hash

    stats = db.stats()
    art_stats = db.artifact_stats()
    sample = [a.model_dump(mode="json") for a in db.list_artifacts(limit=15)]

    messages = build_summary_prompt(case_name, stats, art_stats, sample, redact_pii=redact_pii)
    text = client.chat(messages)
    valid_ids = {a["id"] for a in sample}
    answer, cited = extract_citations(text, valid_ids)
    by_id = {a["id"]: a for a in sample}
    citations = [
        {"artifact_id": aid, "title": by_id[aid].get("title"), "rel_path": by_id[aid].get("rel_path")}
        for aid in cited
    ]
    # STP-049 — grounding: tvrzení v odpovědi vs data citovaných artifactů
    grounding = _ground_answer_safe(text, list(cited), by_id)
    # STP-019 — audit AI volání (model + hash skutečně odeslaného promptu)
    audit_ai_query(
        db,
        case_id=case_id,
        question=f"summary: {case_name}",
        model=model or "unknown",
        prompt_sha256=prompt_hash(messages),
        citations=list(cited),
        agent="e11:summary",
    )
    return {
        "mode": "summary",
        "answer": answer or text.strip(),
        "confidence": parse_confidence(text),
        "citations": citations,
        "grounding": grounding,
    }


def _ai_explain(
    db: CaseDB, case_id: str, artifact_id: str | None, client: LmStudioClient, *, redact_pii: bool = True, model: str | None = None
) -> dict:
    """Režim ``explain`` — vysvětlení jednoho artifactu + citace na něj.

    STP-019: PII v promptu se maskuje podle ``redact_pii``; audit do analysis_operations.
    """
    from stopa.intelligence.rag import audit_ai_query, prompt_hash

    if not artifact_id:
        raise HTTPException(400, "chybí artifact_id")
    art = db.get_artifact(artifact_id)
    if art is None:
        raise HTTPException(404, f"artifact {artifact_id} nenalezen")

    payload = art.model_dump(mode="json")
    messages = build_explain_prompt(payload, redact_pii=redact_pii)
    text = client.chat(messages)
    answer, cited = extract_citations(text, {art.id})
    # STP-049 — grounding: tvrzení v odpovědi vs data citovaného artifactu
    grounding = _ground_answer_safe(text, list(cited), {art.id: payload})
    # STP-019 — audit AI volání (model + hash skutečně odeslaného promptu)
    audit_ai_query(
        db,
        case_id=case_id,
        question=f"explain: {artifact_id}",
        model=model or "unknown",
        prompt_sha256=prompt_hash(messages),
        citations=list(cited),
        agent="e11:explain",
    )
    return {
        "mode": "explain",
        "answer": answer or text.strip(),
        "confidence": parse_confidence(text),
        "citations": (
            [{"artifact_id": art.id, "title": art.title, "rel_path": art.rel_path}]
            if cited
            else []
        ),
        "grounding": grounding,
    }


def build_report_data_safe(db: CaseDB, case_id: str):
    """build_report_data s HTTPException místo ValueError (404)."""
    from stopa.presentation.case_report import build_report_data

    try:
        return build_report_data(db, case_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


def _read_file_bytes(db: CaseDB, rec, offset: int = 0, length: int | None = None) -> bytes:
    """Obsah souboru — z disku (folder/file zdroj) nebo TSK icat (diskový obraz).

    ``length=None`` → celý obsah; jinak úryvek [offset : offset+length].
    """
    from pathlib import Path as _P

    source = db.get_source(rec.source_id)
    if source is None:
        raise HTTPException(404, "zdroj souboru neexistuje")
    root = _P(source.path).expanduser()

    if rec.meta_addr:
        # soubor v diskovém obrazu → TSK icat (partice z partition mapy)
        from stopa.data.tsk import Partition, TskError, extract_file

        parts: list[Partition] = []
        for a in db.list_artifacts(source_id=rec.source_id, artifact_type="disk_image"):
            pm = (a.details or {}).get("partition_map") or []
            for p in pm:
                if p.get("fstype"):
                    parts.append(
                        Partition(
                            index=p["index"],
                            offset_sectors=p["offset_sectors"],
                            size_sectors=p["size_sectors"],
                            desc=p["desc"],
                            fstype=p["fstype"],
                        )
                    )
        data: bytes | None = None
        for part in ([None] if not parts else parts):
            try:
                data = extract_file(root, rec.meta_addr, partition=part)
                break
            except TskError:
                continue  # jiná partice / obraz bez TSK — zkus další
        if data is None:
            raise HTTPException(502, "TSK icat se nedaří přečíst soubor z obrazu")
        end = len(data) if length is None else min(len(data), offset + length)
        return data[offset:end]

    # diskový zdroj — audit P1: rel_path s `..` (symlink ve zdroji) unikne kořene
    p = root / rec.rel_path if not root.is_file() else root
    try:
        resolved = p.resolve(strict=True)
    except OSError:
        raise HTTPException(404, f"soubor na disku neexistuje: {p}") from None
    root_resolved = root.resolve()
    if resolved != root_resolved and not str(resolved).startswith(str(root_resolved) + os.sep):
        # soubor je mimo kořen zdroje (.. nebo symlink ven) → 404, ne 500
        raise HTTPException(404, f"soubor uniká kořene zdroje: {rec.rel_path}")

    # audit P1 — RAM peak: ranged read (seek + read) místo read_bytes() celého souboru
    with open(p, "rb") as fh:
        if offset:
            fh.seek(offset)
        data = fh.read(length) if length is not None else fh.read()
    return data


def _hex_dump(data: bytes) -> list[str]:
    """Hex dump řádky (16 B/řádek): ``0000  48 53 ... |HS...|``."""
    lines: list[str] = []
    for i in range(0, len(data), 16):
        chunk = data[i : i + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:04x}  {hexpart:<47}  |{asc}|")
    return lines


app = create_app()
