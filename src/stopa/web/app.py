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
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from stopa.data.db import CaseDB
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
            result = process_source(db, source.id, root, body.profile)
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
        limit: int = 500,
    ) -> list[dict]:
        db = open_db(case_id)
        try:
            recs = db.list_files(
                bad_extensions_only=bad_ext,
                duplicates_only=dups,
                signature_family=family,
                limit=limit,
            )
            return [r.model_dump(mode="json") for r in recs]
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
        case_id: str, type: str | None = None, limit: int = 500
    ) -> list[dict]:
        db = open_db(case_id)
        try:
            arts = db.list_artifacts(artifact_type=type, limit=limit)
            return [a.model_dump(mode="json") for a in arts]
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


app = create_app()
