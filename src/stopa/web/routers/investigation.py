"""P2-4 — Investigation Workspace API.

Routy nad případem: poznámky ukotvené na reference (``/inv/notes``), úkoly s
stavovým automatem (``/inv/tasks``) a revize hypotéz jako append-only hash
chain (``/inv/hypo-revisions``). Logika žije v ``domain/investigation_workspace``
a I/O v ``data/investigation_repository``; tady je jen API hrana.

Konvence: 404 = neznámý případ (z ``ctx["open_db"]``); 400 = semantická chyba
domény/repotitáře (ValueError/TypeError); 201 = vytvořen záznam.
"""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field

from stopa.data.investigation_repository import InvestigationRepository


class NoteIn(BaseModel):
    ref_kind: str = Field(..., description="artifact | entity | timeline_event")
    ref_id: str
    text: str
    author: str | None = None


class TaskIn(BaseModel):
    title: str
    assignee: str | None = None
    due: str | None = Field(None, description="ISO datetime (volitelné)")


class TaskStatusIn(BaseModel):
    status: str


class HypoRevisionIn(BaseModel):
    hypothesis_id: str
    claim: str
    author: str | None = None


def _repo(db) -> InvestigationRepository:
    return InvestigationRepository(db.conn)


def register(app, ctx) -> None:
    """Přidá P2-4 routy do aplikace (volá se z ``create_app``)."""
    open_db = ctx["open_db"]

    @app.get("/api/cases/{case_id}/inv/notes")
    def inv_notes_list(case_id: str):
        db = open_db(case_id)
        try:
            return _repo(db).list_notes(case_id)
        finally:
            db.close()

    @app.post("/api/cases/{case_id}/inv/notes", status_code=201)
    def inv_note_add(case_id: str, body: NoteIn):
        db = open_db(case_id)
        try:
            note_id = _repo(db).add_note(
                case_id, body.ref_kind, body.ref_id, body.text, author=body.author
            )  # ValueError/TypeError → 400 níže
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            db.close()
        return {"id": note_id}

    @app.get("/api/cases/{case_id}/inv/tasks")
    def inv_tasks_list(case_id: str):
        db = open_db(case_id)
        try:
            return _repo(db).list_tasks(case_id)
        finally:
            db.close()

    @app.post("/api/cases/{case_id}/inv/tasks", status_code=201)
    def inv_task_add(case_id: str, body: TaskIn):
        db = open_db(case_id)
        try:
            task_id = _repo(db).add_task(
                case_id, body.title, assignee=body.assignee, due=body.due
            )  # ValueError/TypeError → 400 níže
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            db.close()
        return {"id": task_id}

    @app.patch("/api/cases/{case_id}/inv/tasks/{task_id}")
    def inv_task_set_status(case_id: str, task_id: int, body: TaskStatusIn):
        db = open_db(case_id)
        try:
            return _repo(db).set_task_status(case_id, task_id, body.status)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/inv/hypo-revisions")
    def inv_hypo_revisions_list(case_id: str, hypothesis: str | None = None):
        from stopa.domain.investigation_workspace import verify_revisions

        db = open_db(case_id)
        try:
            rows = _repo(db).list_hypo_revisions(case_id, hypothesis)
        finally:
            db.close()
        return {"revisions": rows, "chain_ok": verify_revisions(rows) is None}

    @app.post("/api/cases/{case_id}/inv/hypo-revisions", status_code=201)
    def inv_hypo_revision_add(case_id: str, body: HypoRevisionIn):
        db = open_db(case_id)
        try:
            return _repo(db).add_hypo_revision(
                case_id, body.hypothesis_id, body.claim, author=body.author
            )  # ValueError/TypeError → 400 níže
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            db.close()
