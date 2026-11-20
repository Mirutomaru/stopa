"""Web routes — analýzy (search/timeline/analytics/correlate/entities/evidence-graph) (P1-4 vlna C: přesunuto bez změny chování).

Sdílený stav a helpery přicházejí přes ``ctx`` z ``create_app()``;
facade ``stopa.web.app`` volá ``register(app, ctx)`` pro kompatibilitu.
"""


from datetime import datetime

from fastapi import HTTPException, Query

from stopa.domain.times import to_local_iso


def register(app, ctx) -> None:
    """Registruje routy domény; ``ctx`` = sdílený stav create_app()."""
    open_db = ctx["open_db"]
    _require = ctx["_require"]

    @app.get("/api/cases/{case_id}/evidence-graph")
    def evidence_graph(case_id: str) -> dict:
        """P1-3 — unifikovaný Evidence Graph (uzly + hrany s důvodem a polaritou).

        Spojí korelace entit, hypotézy s důkazy pro/proti, timeline události
        (subjekty + rozporné skupiny), findings a ruční/AI hrany z ``graph_edges``.
        Explicitní hrana se stejným klíčem má přednost před odvozenou.
        """
        from stopa.data.graph_repository import GraphRepository

        db = open_db(case_id)
        try:
            repo = GraphRepository(db.conn)
            correlations = db.list_correlations(case_id)
            hypotheses = db.hypothesis_repo.list_by_case(case_id)
            events = db.list_timeline_events()
            manual_rows = repo.list_edges(case_id)
            findings = [
                {
                    "id": f.id,
                    "kind": f.kind,
                    "details_json": dict(f.details_json or {}),
                    "provenance_json": [p.model_dump(mode="json") for p in (f.provenance or [])],
                }
                for f in db.list_findings(case_id)
            ]
            # Provenance odkazuje kanonicky na FileRecord.id → teprve přes mapu na artefakt
            file_to_artifacts = {a.file_id: a.id for a in db.list_artifacts() if a.file_id}
        finally:
            db.close()

        from stopa.domain.evidence_graph import EvidenceGraph, build_evidence_graph

        manual = EvidenceGraph()
        for row in manual_rows:  # explicitní hrany mají přednost
            manual.add_edge(
                src_type=row["src_type"], src_id=row["src_id"],
                dst_type=row["dst_type"], dst_id=row["dst_id"],
                relation=row["relation"], polarity=row.get("polarity") or "neutral",
                confidence=float(row.get("confidence") or 0.5), reason=row["reason"],
                origin="manual",
            )
        graph = build_evidence_graph(
            base=manual, correlations=correlations, hypotheses=hypotheses,
            findings=findings, events=events, file_to_artifacts=file_to_artifacts,
        )
        return graph.to_dict()
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

    # ── P3-1 Advanced Search ────────────────────────────────────────────
    @app.get("/api/cases/{case_id}/search/advanced")
    def search_advanced(
        case_id: str,
        q: str = "",
        kind: str | None = Query(None),
        entity: str | None = Query(None),
        size_min: int | None = Query(None),
        size_max: int | None = Query(None),
        mtime_from: str | None = Query(None),
        mtime_to: str | None = Query(None),
        rel_depth: int | None = Query(None, ge=1, le=3),
        limit: int = 100,
    ) -> dict:
        """P3-1 — Advanced Search: FTS5 + strukturované filtry + graf vztahů.

        Bez parametrů ekvivalentní ``/search``; ``rel_depth`` přidá procházení
        ``graph_edges`` (hloubka 1..3) z artefaktů výsledků. Neznámý případ →
        404, semantická chyba filtru → 400.
        """
        from stopa.data.search_repository import SearchRepository
        from stopa.domain.search_adv import AdvancedSearchQuery, FilterSpec, RelationSpec

        db = open_db(case_id)
        try:
            spec = FilterSpec.from_iso(
                kind=kind,
                size_min=size_min,
                size_max=size_max,
                mtime_from=mtime_from,
                mtime_to=mtime_to,
                entity=entity,
            )
            relations = RelationSpec(depth=rel_depth) if rel_depth else None
            query = AdvancedSearchQuery(
                text=q or None, scope="files", filters=spec, relations=relations, limit=limit
            )
            result = SearchRepository(db.conn).search_advanced(query)
            return {
                "case_id": case_id,
                "query": q,
                "results": [r.model_dump(mode="json") for r in result.results],
                "total": len(result.results),
                "related": {
                    "files": [r.model_dump(mode="json") for r in result.related_files],
                    "nodes": list(result.related_nodes),
                },
            }
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, f"neplatný filtr: {exc}") from exc
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

    # ── F2.2 DuckDB OLAP analytics ────────────────────────────────────
    @app.get("/api/cases/{case_id}/analytics")
    def analytics(
        case_id: str,
        from_ts: datetime | None = Query(None),
        to_ts: datetime | None = Query(None),
        type: str | None = Query(None),
        limit: int = 200,
    ) -> dict:
        """F2.2 — DuckDB OLAP agregace nad timeline (histogram, top typy, okno).

        Bez nainstalovaného duckdb ([analytics] extra) → HTTP 503 s hláškou;
        standardní timeline/search zůstává v SQLite (backward-kompatibilní).
        """
        from stopa.data.analytics import AnalyticsError, AnalyticsStore, duckdb_available

        if not duckdb_available():
            raise HTTPException(
                status_code=503,
                detail="DuckDB není nainstalováno — pip install 'stopa[analytics]'",
            )
        db = open_db(case_id)
        try:
            db_path = str(db.path)
        finally:
            db.close()
        try:
            store = AnalyticsStore(db_path)
            payload: dict[str, object] = {
                "case_id": case_id,
                "status": store.status(),
                "top_event_types": store.top_event_types(limit=20),
                "entity_summary": store.entity_summary(),
            }
            if from_ts is not None and to_ts is not None:
                events = store.timeline_range(
                    from_ts.isoformat(),
                    to_ts.isoformat(),
                    event_type=type,
                    limit=limit,
                )
                payload["timeline_window"] = {
                    "from": from_ts.isoformat(),
                    "to": to_ts.isoformat(),
                    "events": events,
                    "count": len(events),
                }
            return payload  # type: ignore[return-value]
        except AnalyticsError as exc:
            raise HTTPException(status_code=502, detail=f"Analytics chyba: {exc}") from exc

    # ── STP-018 Timeline Intelligence 2.0 ─────────────────────────────
    @app.post("/api/cases/{case_id}/timeline/intel")
    def timeline_intel(case_id: str, window_seconds: float = Query(60.0)) -> dict:
        """STP-018 — explicitní spuštění Timeline Intelligence 2.0 post-passu.

        Rozpory (souběžná aktivita subjektu) + duplikáty napříč zdroji nad
        materializovanou timeline. Idempotentní, deterministický výsledek.
        """
        _require("analysis.run", "timeline_intel", case_id=case_id)
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

    # ── P2-3 Advanced Timeline Intelligence ────────────────────────
    @app.get("/api/cases/{case_id}/timeline/advanced-intel")
    def timeline_advanced_intel(case_id: str) -> dict:
        """P2-3 — pokročilá timeline intelligence (IQR gapy/outliery, cross-source korelace, nejistota).

        Počítá on-the-fly nad materializovanou ``timeline_events`` + E4 correlations
        (cache tabulka je v designu volitelná → Wave 2 bez DDL). Výstup je
        deterministický (stejné vstupy = stejný JSON); confidence korelací z
        nejvyššího ranku E4 propojení entity. Neznámý případ → 404,
        semantická chyba → 400.
        """
        from stopa.domain.timeline_adv import analyze_timeline_adv, entity_confidence_map

        db = open_db(case_id)   # neznámý případ → HTTPException(404) z ctx["open_db"]
        try:
            events = db.list_timeline_events()
            conf_map = entity_confidence_map(db.list_correlations(case_id))
            result = analyze_timeline_adv(events, entity_confidence=conf_map)
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            db.close()
        return {
            "case_id": case_id,
            "events_analyzed": len(events),
            **result.to_dict(),
        }

    # ── E4 Entity + Correlation Engine ────────────────────────────────
    @app.post("/api/cases/{case_id}/correlate")
    def correlate(case_id: str) -> dict:
        """Explicitní krok korelace (ROADMAP E4 bod 4) — re-run = clear + insert."""
        _require("analysis.run", "correlate", case_id=case_id)
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
