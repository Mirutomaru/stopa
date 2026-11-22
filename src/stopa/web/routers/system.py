"""Web routes — systém (health/diagnostics/settings/parser-status/validation/write-blocker/plugins) (P1-4 vlna C: přesunuto bez změny chování).

Sdílený stav a helpery přicházejí přes ``ctx`` z ``create_app()``;
facade ``stopa.web.app`` volá ``register(app, ctx)`` pro kompatibilitu.
"""


import os

from fastapi import File, HTTPException, UploadFile

from stopa.data.db import CaseDB
from stopa.data.timesketch_client import TimesketchClient, TimesketchError, TimesketchUnavailable
from stopa.data.write_blocker_repository import WriteBlockerRepository
from stopa.domain.rbac import DEFAULT_ROLE, normalize_role, permissions_for
from stopa.domain.write_blocker import (  # F5.4/P0.4 — write-blocker API
    MODE_FAIL_CLOSED,
    VENDORS,
    detect_write_blocker,
    gate_with_mode,
    known_vendor_ids,
    resolve_gate_mode,
)

from ..app import SettingsIn, TimesketchPushIn, WBAttachIn, WBRemoveIn, log


def register(app, ctx) -> None:
    """Registruje routy domény; ``ctx`` = sdílený stav create_app()."""
    base = ctx["base"]
    _current_user = ctx["_current_user"]
    _multi_user_mode = ctx["_multi_user_mode"]
    open_db = ctx["open_db"]
    _load_settings = ctx["_load_settings"]
    _save_settings = ctx["_save_settings"]
    _require = ctx["_require"]

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "db_dir": str(base)}

    # ── cases ─────────────────────────────────────────────────
    @app.post("/api/cases/{case_id}/timesketch-push")
    def timesketch_push(case_id: str, body: TimesketchPushIn) -> dict:
        """Push datasetu případu do nového Timesketch sketchu (GUI — oblast Q ★★).

        Zrcadlí ``stopa timesketch-push`` CLI (stejná domain funkce):
        vytvoří sketch a nahraje l2tcsv timeline. Datasety: artifacts /
        timeline / correlations. STP-065: volitelné ``limit`` — pushne jen
        první N záznamů datasetu (None = vše; <1 → 422). Audit + integrity
        checkpoint. Timesketch nedostupná → 503; push selhal → 502 srozumitelnou
        zprávou.
        """
        from stopa.domain.export import (
            artifact_records,
            correlation_records,
            timeline_records,
        )
        from stopa.domain.timesketch_push import push_to_timesketch

        _require("analysis.run", "timesketch_push", case_id=case_id)
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
                    client, case.name if case else case_id, body.what, records,
                    limit=body.limit,
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
        _require("case.read", "timesketch_status", case_id=case_id)

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

        _require("analysis.run", "plaso_import", case_id=case_id)

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

    # ── Pluginy (F6.4) ────────────────────────────────────────
    @app.get("/api/cases/{case_id}/write-blocker")
    def wb_status(case_id: str) -> dict:
        """Aktuální WB stav + rozhodnutí ingest brány pro UI (P0.4: režim + třída ochrany)."""
        db = open_db(case_id)
        try:
            repo = WriteBlockerRepository(db.conn, db.audit_repo)
            state = repo.latest_state()
            # P0.4: status endpoint nemá kontext profilu → forenzní výchozí zobrazení;
            # explicitní settings (wb_gate_mode / require_write_blocker) mají prioritu.
            mode = resolve_gate_mode(_load_settings(), profile_name="forensic")
            check = gate_with_mode(state, mode)
            return {
                "state": state,
                "require_wb": mode == MODE_FAIL_CLOSED,  # F5.4 legacy (backward compat)
                "mode": mode,  # P0.4 — fail_closed / warn_only
                "protection_class": check.protection_class,  # P0.4 — třída ochrany
                "allowed": check.allowed,
                "warning": check.warning,
                "extra_warnings": list(check.extra_warnings),  # P0.4 — např. neznámé VID/PID
                # podporovaní vendori pro UI select (AK: 3 vendori)
                "vendors": [{"id": v.vendor_id, "label": v.label} for v in VENDORS],
                "history": repo.history(),
            }
        finally:
            db.close()
    @app.post("/api/cases/{case_id}/write-blocker/attach", status_code=201)
    def wb_attach(case_id: str, body: WBAttachIn) -> dict:
        """Zaznamenat připojení WB (auto-detekce vendoru z device stringu)."""
        _require("source.add", "wb_attach", case_id=case_id)
        db = open_db(case_id)
        try:
            repo = WriteBlockerRepository(db.conn, db.audit_repo)
            device = (body.device or "").strip()
            match = detect_write_blocker(device) if device else None
            vendor_id = body.vendor or (match.vendor_id if match else None)
            if not vendor_id:
                raise HTTPException(
                    400,
                    f"vendor nedetekován ({device!r}) — zadejte vendor z "
                    f"{', '.join(known_vendor_ids())}",
                )
            row_id = repo.attach(
                vendor=vendor_id,
                product=body.product,
                device=device or None,
                notes=body.notes,
            )
            return {
                "vendor": vendor_id,
                "detected_from_device": match is not None and bool(device),
                "audit_id": row_id,
            }
        finally:
            db.close()
    @app.post("/api/cases/{case_id}/write-blocker/remove")
    def wb_remove(case_id: str, body: WBRemoveIn) -> dict:
        """Zaznamenat odebrání WB."""
        _require("source.add", "wb_remove", case_id=case_id)
        db = open_db(case_id)
        try:
            row_id = WriteBlockerRepository(db.conn, db.audit_repo).remove(
                reason=body.reason
            )
            return {"audit_id": row_id}
        finally:
            db.close()

    # ── STP-050 — Validation Center (C3 registry + C6 report) ──
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

    # ── P0-4 — validation lab (per-parser status + test coverage) ────────────
    @app.get("/api/parser-status")
    def parser_status() -> dict:
        """P0-4 validation lab — per-parser validační status s pokrytím testy.

        Registry level (ne case): stav C3 registry + AST počítání testovacích
        funkcí v deklarovaných test souborech. Souhrn: count/validated/
        unvalidated/dataset_coverage_pct; detail = seznam parserů.
        """
        from stopa.data.parser_status_service import load_parser_status

        try:
            return load_parser_status()
        except Exception as e:  # doplňková vrstva — log + degradace
            log.warning("parser status selhal: %s", e)
            raise HTTPException(500, f"parser status selhal: {e}") from e

    # ── STP-052 — Audit Center (oblast O) ─────────────────────
    @app.get("/api/diagnostics")
    def diagnostics() -> dict:
        """Verze knihoven + dostupnost volitelných komponent (TSK/EWF/FDE).

        Poslední operace z audit_log všech případů (nejnovější 10) — GUI je
        zobrazí jako „poslední aktivity“; chyby = processing_completed s errors>0.
        """
        from stopa.data.diagnostics import collect_diagnostics
        from stopa.data.query_cache import PROCESS_CACHE

        out = collect_diagnostics()
        # F2.5 — stav query cache (hit ratio pro opakované operace)
        out["query_cache"] = PROCESS_CACHE.stats()
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
    @app.get("/api/settings")
    def get_settings() -> dict:
        """Uživatelská nastavení (defaulty + uložené přepsání)."""
        s = _load_settings()
        # F4.4 — multi-user: role session uživatele mačí přepínač v settings
        status, user = _current_user()
        role = user["role"] if status == "ok" else (s.get("role") or DEFAULT_ROLE)
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
            # F5.4 — write-blocker ingest gate (default OFF = backward compat)
            "require_write_blocker": bool(s.get("require_write_blocker", False)),
            # F4.4 — multi-user režim + identita session (SPA topbar / login gate)
            "multi_user_mode": _multi_user_mode(),
            "user": (
                {"username": user["username"], "role": user["role"]}
                if status == "ok"
                else None
            ),
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
        if body.require_write_blocker is not None:  # F5.4 — WB ingest gate
            s["require_write_blocker"] = bool(body.require_write_blocker)
        _save_settings(s)
        return get_settings()

    # ── F4.4 — Multi-tenant RBAC endpoints (orgs/teams/users/members/sso) ───────
