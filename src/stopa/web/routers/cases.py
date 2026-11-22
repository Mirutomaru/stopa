"""Web routes — case CRUD, zdroje a live kanál (cases/sources/processing/ws/auto-export) (P1-4 vlna C: přesunuto bez změny chování).

Sdílený stav a helpery přicházejí přes ``ctx`` z ``create_app()``;
facade ``stopa.web.app`` volá ``register(app, ctx)`` pro kompatibilitu.
"""


import asyncio
import queue
import re
import threading
import uuid
from pathlib import Path

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from stopa.data.db import CaseDB
from stopa.data.write_blocker_repository import WriteBlockerRepository
from stopa.domain.events import case_topic
from stopa.domain.rbac import normalize_role
from stopa.domain.write_blocker import (  # F5.4/P0.4 — write-blocker API
    ACTION_CHECK,
    ACTION_MODE_EXCEPTION,
    MODE_WARN_ONLY,
    gate_with_mode,
    resolve_gate_mode,
)
from stopa.models import Case, EvidenceSource
from stopa.pipeline import process_source

from ..app import CaseIn, CaseUpdateIn, SourceIn, log, validate_case_id


def register(app, ctx) -> None:
    """Registruje routy domény; ``ctx`` = sdílený stav create_app()."""
    base = ctx["base"]
    _jobs = ctx["_jobs"]
    _jobs_lock = ctx["_jobs_lock"]
    _bus = ctx["_bus"]
    _ws_heartbeat_s = ctx["_ws_heartbeat_s"]
    _now_iso = ctx["_now_iso"]
    _attach_live_events = ctx["_attach_live_events"]
    _job_update = ctx["_job_update"]
    _user_repo = ctx["_user_repo"]
    _current_user = ctx["_current_user"]
    open_db = ctx["open_db"]
    _load_last_export = ctx["_load_last_export"]
    _load_settings = ctx["_load_settings"]
    _require = ctx["_require"]

    @app.get("/api/cases")
    def list_cases() -> list[dict]:
        _require("case.read")  # legacy: settings role; multi-user bez tokenu → 401 fail-closed
        # F4.4 — multi-user: uživatel vidí jen případy, ve kterých je člen (admin = vše).
        visible: set[str] | None = None
        status, user = _current_user()
        if status == "ok" and normalize_role(user["role"]) != "admin":
            repo = _user_repo()
            try:
                visible = set(repo.member_case_ids(user["id"]))  # fail-closed filtr
            finally:
                repo.conn.close()
        out = []
        for path in sorted(base.glob("case-*.db")):
            if visible is not None and path.stem not in visible:
                continue
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
                        # STP-069 — stav auto-exportu pro UI checkbox
                        "auto_export_enabled": bool(case.auto_export_enabled),
                        # STP-070 — interval plánovače pro UI input (None = nenastaveno)
                        "auto_export_interval_minutes": case.auto_export_interval_minutes,
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
        # P2-2 — centrální registr případů: automatický sync při vzniku případu (defenzivní)
        from stopa.data.case_registry_repository import auto_sync

        auto_sync(base, case.id)
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
                # STP-069 — opt-in automatický export + cesta k poslednímu bundle.
                "auto_export_enabled": bool(case.auto_export_enabled),
                "last_auto_export_path": case.last_auto_export_path,
                # STP-070 — periodický plánovač auto-bundle (interval + čas spuštění).
                "auto_export_interval_minutes": case.auto_export_interval_minutes,
                "last_auto_export_at": (
                    case.last_auto_export_at.isoformat() if case.last_auto_export_at else None
                ),
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
        _require("source.add", "add_source", case_id=case_id)
        root = Path(body.path).expanduser()
        if not root.exists():
            raise HTTPException(400, f"zdroj neexistuje: {root}")
        db = open_db(case_id)

        # F5.4/P0.4 — write-blocker gate (režim z resolve_gate_mode: explicitní
        # settings > legacy bool require_write_blocker > profilový výchozí;
        # forensic → fail-closed). 409 = brána blokuje ingest bez potvrzené
        # ochrany proti zápisu. P0.4: každá kontrola se audituje (wb_check),
        # laboratorní warn_only navíc jako explicitní výjimka (wb_mode_exception).
        _wb_repo = WriteBlockerRepository(db.conn, db.audit_repo)
        _wb_mode = resolve_gate_mode(_load_settings(), profile_name=body.profile or "forensic")
        _wb_check = gate_with_mode(
            _wb_repo.latest_state(), _wb_mode, connection="web"
        )
        db.log_operation(
            ACTION_CHECK,
            details={
                "allowed": _wb_check.allowed,
                "protection_class": _wb_check.protection_class,
                "mode": _wb_mode,
                "device_id": _wb_check.device_id,
                "connection": _wb_check.connection,
                "extra_warnings": list(_wb_check.extra_warnings),
            },
        )
        if _wb_mode == MODE_WARN_ONLY:
            db.log_operation(
                ACTION_MODE_EXCEPTION, details={"mode": _wb_mode}
            )
        if not _wb_check.allowed:
            raise HTTPException(409, _wb_check.warning or "write-blocker gate")

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
                _attach_live_events(tdb, case_id)  # F4.2 — live události i z bg ingestu
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
                        resume_mode=body.resume_mode,  # P0.1 — fast (výchozí) / strict
                        pool="threads",  # F2.4 — web běží s pozadím vlákny (uvicorn);
                        # per-request spawn procesů by byl zbytečný + fork riziko
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
            # F2.4 — web běží s pozadím vlákny (uvicorn); per-request spawn procesů
            # by byl zbytečný + fork riziko → explicitně threads (původní E3 režim)
            result = process_source(
                db, source.id, root, body.profile, progress=_progress, resume=body.resume,
                resume_mode=body.resume_mode, pool="threads",
            )
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

    # ── F4.2 — WebSocket real-time updates (live progress/timeline/AI) ─────
    @app.websocket("/api/cases/{case_id}/ws")
    async def case_events_ws(websocket: WebSocket, case_id: str) -> None:
        """F4.2 — live události případu přes WebSocket.

        Kontrakt:
        - při připojení okamžitě ``{"type": "hello", ...}`` (marker pro
          klienty = úspěšné (re)spojení);
        - pak stream událostí ``ingest.progress`` / ``timeline.event`` /
          ``ai.action`` (typ v poli ``type``, čas v ``ts`` ISO-8601 UTC);
        - **heartbeat** ``{"type": "heartbeat"}`` každé ``ws_heartbeat_s``
          při neaktivitě (AK F4.2; default 15 s, parametr factory pro testy);
        - **reconnection** je na klientu (exponenciální backoff + fallback
          na REST polling — graceful degradation: bez WS vše funguje dál);
        - neznámý případ → close code 4004.

        Latence AK < 200 ms: publish je nablokující put_nowait do fronty,
        handler čte přes ``asyncio.to_thread`` (worker vlákna nepočeká).
        """
        if not re.fullmatch(r"[A-Za-z0-9._-]+", case_id or ""):
            await websocket.close(code=4000)
            return
        if not (base / f"{case_id}.db").exists():
            await websocket.accept()
            await websocket.close(code=4004, reason="případ nenalezen")
            return

        topic = case_topic(case_id)
        q: queue.Queue = _bus.subscribe(topic)
        try:
            await websocket.accept()
            await websocket.send_json({"type": "hello", "case_id": case_id, "ts": _now_iso()})
            while True:
                # get s timeoutem v worker vláknu — nepadá event loop;
                # při datu se vrátí okamžitě (latence = put_nowait + scheduling).
                try:
                    event = await asyncio.to_thread(q.get, True, _ws_heartbeat_s)
                except queue.Empty:
                    await websocket.send_json({"type": "heartbeat", "ts": _now_iso()})
                else:
                    await websocket.send_json(event)
        except WebSocketDisconnect:
            pass  # normální konec (reconnection na klientu)
        finally:
            _bus.unsubscribe(topic, q)

    # ── files / search / timeline ─────────────────────────────
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
    @app.get("/api/cases/{case_id}/auto-export")
    def auto_export_download(case_id: str):
        """Re-download posledního automatického ZIP bundle (STP-069).

        Auto-bundle generuje pipeline hook po dokončení processingu, pokud je u
        případu zapnutý ``auto_export_enabled``. Cesta je persistovaná v case DB
        (``last_auto_export_path``); fallback = trvalá cache layout
        ``{db_dir}/exports/{case_id}/auto-bundle.zip``. Read-only: bez auditu.

        404 = auto-export ještě nikdy nebyl vygenerován.
        """
        _require("analysis.run", "auto_export_download", case_id=case_id)
        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            if case is None:
                raise HTTPException(404, f"Případ '{case_id}' nenalezen")
        finally:
            db.close()

        path: Path | None = None
        persisted = getattr(case, "last_auto_export_path", None)
        if persisted and Path(persisted).is_file():
            path = Path(persisted)
        else:
            path = _load_last_export(case_id, "auto-bundle", "zip")
        if path is None:
            raise HTTPException(404, "automatický export ještě nebyl vygenerován")

        return FileResponse(
            path, media_type="application/zip", filename=f"{case_id}_auto-bundle.zip"
        )

    # ── STP-059 — Timesketch push (oblast Q, interop) ───────────────
    @app.patch("/api/cases/{case_id}")
    def update_case(case_id: str, body: CaseUpdateIn) -> dict:
        """Aktualizace metadat případu (name/examiner/notes/timezone/auto-export)."""
        _require("case.update", "update_case", case_id=case_id)
        db = open_db(case_id)
        try:
            ok = db.update_case(
                case_id,
                name=body.name,
                examiner=body.examiner,
                notes=body.notes,
                timezone_name=body.timezone_name,
                auto_export_enabled=body.auto_export_enabled,  # STP-069
            )
            if not ok:
                raise HTTPException(404, "případ neexistuje")
            # STP-070 — interval periodického auto-bundle. Pole chybí v requestu =
            # bez změny; explicitní null / prázdný string = vymazat; číslo = nastavit.
            if "auto_export_interval_minutes" in body.model_fields_set:
                from stopa.domain.export_schedule import parse_interval_minutes

                try:
                    minutes = parse_interval_minutes(body.auto_export_interval_minutes)
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
                ok_int = db.set_auto_export_interval(case_id, minutes)
                if not ok_int:
                    raise HTTPException(404, "případ neexistuje")
            db.log_operation("case_updated", details={"case_id": case_id})
            return get_case(case_id)
        finally:
            db.close()
    @app.delete("/api/cases/{case_id}")
    def delete_case(case_id: str) -> dict:
        """Smaže případ i zdroje (kaskáda na files/artifacts/timeline)."""
        _require("case.delete", "delete_case", case_id=case_id)
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
        # F2.2 — materiálový DuckDB stav je odvozený artefakt; po smazání zmizí.
        try:
            from stopa.data.analytics import drop_case_analytics

            drop_case_analytics(path)
        except Exception as exc:
            log.warning("DuckDB cleanup selhal pro case %s: %s", case_id, exc)
        # F4.4 — instance DB: smazat řádek case → FK CASCADE odstraní i členství
        repo = _user_repo()
        try:
            repo.conn.execute("DELETE FROM cases WHERE id=?", (case_id,))
            repo.conn.commit()
        finally:
            repo.conn.close()
        # P2-2 — centrální registr případů: odebrat záznam při smazání případu (defenzivní)
        from stopa.data.case_registry_repository import auto_remove

        auto_remove(base, case_id)
        return {"deleted": case_id}
