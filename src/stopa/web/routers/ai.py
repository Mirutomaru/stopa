"""Web routes — AI asistent + hypotézy (ai status/query/run/orchestrator, hypotheses) (P1-4 vlna C: přesunuto bez změny chování).

Sdílený stav a helpery přicházejí přes ``ctx`` z ``create_app()``;
facade ``stopa.web.app`` volá ``register(app, ctx)`` pro kompatibilitu.
"""


from collections.abc import Callable, Iterator

from fastapi import HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from stopa.data.lmstudio_client import LmStudioClient, LmStudioUnavailable

from ..app import (
    AiAnalyzeIn,
    AiHypoGenerateIn,
    AiHypoStatusIn,
    AiQueryIn,
    AiRunIn,
    _ai_explain,
    _ai_nl_search,
    _ai_summary,
)


def register(app, ctx) -> None:
    """Registruje routy domény; ``ctx`` = sdílený stav create_app()."""
    open_db = ctx["open_db"]
    _last_export_path = ctx["_last_export_path"]
    _save_last_export = ctx["_save_last_export"]
    _save_last_export_bytes = ctx["_save_last_export_bytes"]
    _load_settings = ctx["_load_settings"]
    _require = ctx["_require"]

    @app.get("/api/ai/orchestrator-status")
    def ai_orchestrator_status() -> dict:
        """P1-2 — stav AI orchestrátoru (LM Studio dostupnost + registry rolí).

        Oddělené od E11 ``/api/ai/status`` (ten zůstává pro GUI kompatibilitu).
        """
        from stopa.data.lmstudio_client import LmStudioClient, settings_from_env
        from stopa.domain.ai_orchestrator import ROLE_IDS, build_role_registry

        roles = build_role_registry()
        return {
            "lmstudio": LmStudioClient(settings_from_env()).health(),
            "roles": [
                {"id": rid, "title": roles[rid].title, "max_tokens": roles[rid].max_tokens}
                for rid in ROLE_IDS
            ],
        }
    @app.post("/api/cases/{case_id}/ai/run")
    def ai_run(case_id: str, body: AiRunIn) -> dict:
        """P1-2 — spustí AI roli nad důkazy případu (audit → case audit_log).

        422 = neznámá role; 503 = LM Studio nedostupný po retrych;
        404 = artefakt nenalezen / prázdný case. ``validated=False`` = výstup
        nesplnil schema role (payload=None, QA signál).
        """
        _require("analysis.run", "ai_run", case_id=case_id)
        from stopa.data.ai_orchestrator_service import AiOrchestrationError, run_role_on_case
        from stopa.domain.ai_orchestrator import ROLE_IDS

        if body.role not in ROLE_IDS:
            raise HTTPException(422, f"neznámá AI role {body.role!r} (očekáván jeden z {ROLE_IDS})")
        db = open_db(case_id)
        try:
            call, used_ids = run_role_on_case(db, body.role, question=body.question,
                                              artifact_ids=body.artifact_ids)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
        except AiOrchestrationError as e:
            raise HTTPException(503, str(e)) from e
        finally:
            db.close()
        return {
            "role": call.role_id,
            "validated": call.payload is not None,
            "payload": call.payload,
            "text": call.text,
            "tokens_out": call.tokens_out,
            "attempts": call.attempts,
            "evidence": used_ids,
            # B8 — determinismus/grounding: citace + identita modelu
            "citations": list(call.citations),
            "unknown_citations": list(call.unknown_citations),
            "grounded": call.grounded,
            "model": call.model,
        }

    # ── P4-5 — AI agent stream (SSE) ─────────────────────────────────────
    @app.get("/api/cases/{case_id}/ai/run/stream")
    def ai_run_stream(case_id: str, question: str = Query(...)) -> Response:
        """P4-5 — streaming běh AI agenta (ReAct) nad případem.

        SSE události ``data: {json}`` v pořadí ``start`` → ``step``* →
        ``final`` (při chybě přesně jeden ``error``). Finální výsledek je
        identický s nestreamovacím během — stejná jádrová smyčka (AK P4-5).

        404 = případ neexistuje; 503 = LM Studio nedostupný. DB se zavírá až
        po skončení streamu (ne před ním).
        """
        _require("analysis.run", "ai_stream", case_id=case_id)
        import json as _json

        from stopa.intelligence.tool_agent import run_stream

        db = open_db(case_id)
        try:
            if db.get_case(case_id) is None:
                raise HTTPException(404, "případ neexistuje")
            client = LmStudioClient()
            health = client.health()
            if not health["available"]:
                raise HTTPException(503, "AI nedostupná — spusťte LM Studio (localhost:1234)")
            redact_pii = bool(_load_settings().get("ai_redact_pii", True))

            def _llm(messages: list[dict[str, str]], max_tokens: int) -> str:
                return client.chat(messages, max_tokens=max_tokens)

            def gen() -> Iterator[str]:
                try:
                    for ev in run_stream(_llm, db, case_id, question, redact_pii=redact_pii):
                        yield f"data: {_json.dumps(ev, ensure_ascii=False)}\n\n"
                finally:
                    db.close()  # P4-5: DB zavřená až po skončení streamu

            return StreamingResponse(gen(), media_type="text/event-stream")
        except Exception:
            db.close()
            raise
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
        _require("analysis.run", "ai_query", case_id=case_id)
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
        _require("analysis.run", "ai_analyze", case_id=case_id)
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
    # ── F3.5: Hypothesis Graph (AI graf hypotéz + ruční potvrzení/vyvrácení) ──
    @app.get("/api/cases/{case_id}/hypotheses")
    def hypotheses_list(case_id: str) -> dict:
        """Graf hypotéz případu: uzly + hrany + lineage k artefaktům."""
        from stopa.intelligence.hypothesis_graph import graph_payload

        _require("analysis.run", "hypotheses_list", case_id=case_id)
        db = open_db(case_id)
        try:
            if db.get_case(case_id) is None:
                raise HTTPException(404, "případ neexistuje")
            return graph_payload(db, case_id)
        finally:
            db.close()
    @app.post("/api/cases/{case_id}/hypotheses/generate", status_code=201)
    def hypotheses_generate(case_id: str, body: AiHypoGenerateIn) -> dict:
        """Sestaví a uloží graf hypotéz (AI nebo deterministický fallback)."""
        from stopa.intelligence.hypothesis_graph import (
            HypothesisGraphError,
            build_hypothesis_graph,
            graph_payload,
            store_graph,
        )

        _require("analysis.run", "hypotheses_generate", case_id=case_id)
        db = open_db(case_id)
        try:
            if db.get_case(case_id) is None:
                raise HTTPException(404, "případ neexistuje")
            llm_call: Callable[[str], str] | None = None
            source = "fallback"
            if body.use_ai:
                client = LmStudioClient()
                health = client.health()
                if not health["available"]:
                    raise HTTPException(503, "AI nedostupná — spusťte LM Studio (localhost:1234)")

                def _llm(prompt: str) -> str:
                    return client.chat([{"role": "user", "content": prompt}])

                llm_call = _llm
                source = "llm"
            try:
                nodes = build_hypothesis_graph(db, case_id, llm_call=llm_call)
            except HypothesisGraphError as exc:
                raise HTTPException(422, f"neplatný výstup LLM: {exc}") from exc
            ids = store_graph(db, case_id, nodes, source=source)
            return {"nodes": len(ids), "ids": ids, "graph": graph_payload(db, case_id)}
        finally:
            db.close()
    @app.post("/api/cases/{case_id}/hypotheses/{hyp_id}/status")
    def hypotheses_status(case_id: str, hyp_id: str, body: AiHypoStatusIn) -> dict:
        """Ruční potvrzení/vyvrácení hypotézy (AK F3.5)."""
        from stopa.data.hypothesis_repository import HYPOTHESIS_STATUSES

        _require("analysis.run", "hypotheses_status", case_id=case_id)
        if body.status not in HYPOTHESIS_STATUSES:
            raise HTTPException(400, f"neplatný stav (očekáváno pending|confirmed|refuted): {body.status}")
        db = open_db(case_id)
        try:
            node = db.get_hypothesis(hyp_id)
            if node is None or node["case_id"] != case_id:
                raise HTTPException(404, "hypotéza neexistuje")
            db.set_hypothesis_status(hyp_id, body.status)
            db.log_operation(
                "hypothesis_status_changed", actor="web", details={"id": hyp_id, "status": body.status}
            )
            return db.get_hypothesis(hyp_id) or {}
        finally:
            db.close()
    @app.get("/api/cases/{case_id}/hypotheses/export")
    def hypotheses_export(case_id: str, format: str = Query("json")) -> Response:
        """Export grafu hypotéz — PDF/JSON (AK F3.5)."""
        from stopa.intelligence.hypothesis_graph import export_graph_json, export_graph_pdf

        _require("analysis.run", "hypotheses_export", case_id=case_id)
        if format not in ("json", "pdf"):
            raise HTTPException(400, f"neznámý formát: {format}")
        db = open_db(case_id)
        try:
            if db.get_case(case_id) is None:
                raise HTTPException(404, "případ neexistuje")
            if format == "json":
                text = export_graph_json(db, case_id)
                _save_last_export(case_id, "hypotheses", "json", text)
                return Response(content=text, media_type="application/json")
            out = _last_export_path(case_id, "hypotheses", "pdf")
            try:
                export_graph_pdf(db, case_id, out)
            except RuntimeError as exc:
                raise HTTPException(501, str(exc)) from exc
            data = out.read_bytes()
            _save_last_export_bytes(case_id, "hypotheses", "pdf", data)
            return Response(content=data, media_type="application/pdf")
        finally:
            db.close()
