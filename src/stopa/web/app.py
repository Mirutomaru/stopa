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

import logging
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from stopa.data.db import CaseDB
from stopa.domain.times import to_local_iso
from stopa.models import Case, EvidenceSource
from stopa.pipeline import process_source

log = logging.getLogger("stopa.web")

STATIC_DIR = Path(__file__).parent / "static"


def _db_dir() -> Path:
    d = Path(os.environ.get("STOPA_DB_DIR", "cases"))
    d.mkdir(parents=True, exist_ok=True)
    return d


class CaseIn(BaseModel):
    name: str
    examiner: str | None = None
    notes: str | None = None


class SourceIn(BaseModel):
    path: str
    profile: str = "forensic"
    resume: bool = False  # E3 checkpointing — přeskočit soubory už v DB


def create_app(db_dir: Path | None = None) -> FastAPI:
    """App factory — `db_dir` pro testy (tmp), default z env STOPA_DB_DIR."""
    app = FastAPI(title="STOPA", version="0.1.0")
    base = db_dir or _db_dir()

    def open_db(case_id: str) -> CaseDB:
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
        # nová DB na nový soubor — case ID je v názvu souboru
        case = Case(name=body.name, examiner=body.examiner, notes=body.notes)
        db = CaseDB(base / f"{case.id}.db")
        try:
            db.add_case(case)
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
        root = Path(body.path).expanduser()
        if not root.exists():
            raise HTTPException(400, f"zdroj neexistuje: {root}")
        db = open_db(case_id)
        try:
            source = EvidenceSource(
                case_id=case_id,
                kind="folder" if root.is_dir() else "file",
                path=str(root),
            )
            db.add_source(source)
            result = process_source(db, source.id, root, body.profile, resume=body.resume)
            return {
                "source_id": source.id,
                **result.model_dump(),
            }
        finally:
            db.close()

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
    def search(case_id: str, q: str = "", limit: int = 100) -> list[dict]:
        if not q.strip():
            return []
        db = open_db(case_id)
        try:
            recs = db.search(q, limit=limit)
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

    # ── E4 Entity + Correlation Engine ────────────────────────────────
    @app.post("/api/cases/{case_id}/correlate")
    def correlate(case_id: str) -> dict:
        """Explicitní krok korelace (ROADMAP E4 bod 4) — re-run = clear + insert."""
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

    @app.post("/api/files/{file_id}/flag")
    def set_flag(file_id: str, flag: str = "evidence", on: bool = True) -> dict:
        """Přepne flag souboru — „Mark as Evidence“ / „Add to Report“."""
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
            return Response(
                content=data,
                media_type="application/octet-stream",
                headers={"Content-Disposition":
                         f'attachment; filename="{rec.name}"'},
            )
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

    # ── statická SPA ──────────────────────────────────────────
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


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
    else:
        p = root / rec.rel_path if not root.is_file() else root
        if not p.exists():
            raise HTTPException(404, f"soubor na disku neexistuje: {p}")
        data = p.read_bytes()

    end = len(data) if length is None else min(len(data), offset + length)
    return data[offset:end]


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
