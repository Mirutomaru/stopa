"""Web routes — reporty a integrace (report/compliance/daubert/audit/interop/export/timesketch/plaso) (P1-4 vlna C: přesunuto bez změny chování).

Sdílený stav a helpery přicházejí přes ``ctx`` z ``create_app()``;
facade ``stopa.web.app`` volá ``register(app, ctx)`` pro kompatibilitu.
"""



from urllib.parse import quote

from fastapi import HTTPException, Query
from fastapi.responses import FileResponse

from ..app import build_report_data_safe, log


def register(app, ctx) -> None:
    """Registruje routy domény; ``ctx`` = sdílený stav create_app()."""
    open_db = ctx["open_db"]
    _save_last_export = ctx["_save_last_export"]
    _save_last_export_bytes = ctx["_save_last_export_bytes"]
    _load_last_export = ctx["_load_last_export"]
    _load_settings = ctx["_load_settings"]
    _require = ctx["_require"]

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

        _require("analysis.run", "interop_export", case_id=case_id)
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

            # STP-067 — cache posledního exportu pro re-download z historie UI.
            _save_last_export(case_id, what, format, text)

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

    # ── STP-068 — ZIP bundle všech datasetů (oblast Q ★★) ───────────────
    @app.get("/api/cases/{case_id}/interop-export-bundle")
    def interop_export_bundle(case_id: str, limit: int | None = Query(default=None)):
        """Export všech 3 datasetů případu do jednoho deterministického ZIP (GUI — oblast Q ★★).

        Zrcadlí ``stopa export --bundle`` CLI (stejná domain funkce
        ``to_zip_bundle``): artifacts + timeline + correlations jako CSV
        soubory + manifest.json se SHA-256 kontrolními součty. Deterministický
        výstup pro C4: fixní pořadí souborů, fixní timestamps v ZIP, stabilní
        manifest. Volitelné ``limit`` — exportuje jen první N záznamů každého
        datasetu (None = vše; <1 → 422). Audit + integrity checkpoint.
        """
        from fastapi import Response

        from stopa.domain.export import (
            artifact_records,
            correlation_records,
            timeline_records,
            to_zip_bundle,
        )

        _require("analysis.run", "interop_export_bundle", case_id=case_id)
        if limit is not None and limit < 1:
            raise HTTPException(422, f"limit musí být ≥ 1 (dostalo se {limit})")

        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            if case is None:
                raise HTTPException(404, f"Případ '{case_id}' nenalezen")
            datasets = {
                "artifacts": artifact_records(db.list_artifacts()),
                "timeline": timeline_records(db.list_timeline_events()),
                "correlations": correlation_records(db.list_correlations(case_id)),
            }
            if limit is not None:
                datasets = {k: v[:limit] for k, v in datasets.items()}

            # STP-068 — deterministický timestamp z case.created_at (C4).
            data = to_zip_bundle(datasets, case_id, case.created_at.isoformat())

            # STP-068 — cache binárního bundle pro re-download z historie UI.
            _save_last_export_bytes(case_id, "bundle", "zip", data)

            ascii_name = f"{case_id}_interop-bundle.zip"
            db.log_operation(
                "interop_bundle_exported",
                actor=case.examiner if case else None,
                details={
                    "datasets": {k: len(v) for k, v in datasets.items()},
                    "limit": limit,
                    "bytes": len(data),
                },
            )
            # P0 Core C4: kontrolní bod po exportu.
            db.add_integrity_checkpoint("export")
            return Response(
                content=data,
                media_type="application/zip",
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

        _require("analysis.run", "l2tcsv_preview", case_id=case_id)
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

    # ── STP-066 — Export center: náhled CSV/JSON (UCO) před downloadem ──
    @app.get("/api/cases/{case_id}/export-preview")
    def export_preview(case_id: str, what: str = "artifacts", format: str = "csv", limit: int = 50) -> dict:
        """Náhled exportu v zvoleném formátu (GUI — oblast Q ★★).

        Generalizace l2tcsv-preview (STP-064) na všechny exportní formáty:
        ``l2tcsv`` / ``csv`` / ``uco`` (JSON-LD). Zrcadlí reálný export
        (stejné domain serializátory) — uživatel si ověří data před
        downloadem. Read-only: bez audit záznamu i integrity checkpointu.

        - ``l2tcsv`` — 17 sloupců log2timeline.pl (stejně jako l2tcsv-preview),
        - ``csv``    — nativní STOPA sloupce datasetu,
        - ``uco``    — první N objektů UCO JSON-LD dokumentu.

        Datasety: artifacts / timeline / correlations. Limit clamp 1..500.
        """
        import csv as _csv
        import io as _io
        import json as _json

        from stopa.domain.export import (
            ARTIFACT_COLUMNS,
            CORRELATION_COLUMNS,
            L2TCSV_COLUMNS,
            TIMELINE_COLUMNS,
            artifact_records,
            correlation_records,
            timeline_records,
            to_l2tcsv,
        )
        from stopa.domain.uco import to_uco_json

        _require("analysis.run", "export_preview", case_id=case_id)
        if what not in ("artifacts", "timeline", "correlations"):
            raise HTTPException(400, f"neplatný dataset: {what}")
        if format not in ("l2tcsv", "csv", "uco"):
            raise HTTPException(400, f"neplatný formát: {format}")
        limit = max(1, min(int(limit), 500))

        db = open_db(case_id)
        try:
            if what == "artifacts":
                records = artifact_records(db.list_artifacts())
            elif what == "timeline":
                records = timeline_records(db.list_timeline_events())
            else:  # correlations
                records = correlation_records(db.list_correlations(case_id))

            total = len(records)
            if format == "l2tcsv":
                text = to_l2tcsv(records, dataset=what)
                rows = list(_csv.reader(_io.StringIO(text)))
                header = rows[0] if rows else []
                body = rows[1 : limit + 1]
                return {
                    "case_id": case_id,
                    "dataset": what,
                    "format": format,
                    "columns": list(L2TCSV_COLUMNS),
                    "total_records": total,
                    "limit": limit,
                    "rows": [dict(zip(header, r)) for r in body],
                }

            if format == "csv":
                columns = {
                    "artifacts": ARTIFACT_COLUMNS,
                    "timeline": TIMELINE_COLUMNS,
                    "correlations": CORRELATION_COLUMNS,
                }[what]
                return {
                    "case_id": case_id,
                    "dataset": what,
                    "format": format,
                    "columns": list(columns),
                    "total_records": total,
                    "limit": limit,
                    "rows": [dict(r) for r in records[:limit]],
                }

            # uco — JSON-LD dokument; preview = první N objektů
            doc = _json.loads(to_uco_json(records, dataset=what))
            objects = doc.get("objects", [])[:limit]
            cols: list[str] = []
            for obj in objects:
                for key in obj:
                    if key not in cols:
                        cols.append(key)
            return {
                "case_id": case_id,
                "dataset": what,
                "format": format,
                "columns": cols,
                "total_records": total,
                "limit": limit,
                "rows": objects,
            }
        finally:
            db.close()

    # ── STP-067 — re-download posledního exportu z historie (oblast Q ★★) ──
    @app.get("/api/cases/{case_id}/last-export")
    def last_export(case_id: str, what: str = "artifacts", format: str = "csv"):
        """Re-download posledního exportu datasetu+formátu (GUI — oblast Q ★★).

        Vrací cache soubor uložený při posledním ``interop-export`` pro daný
        dataset a formát — uživatel si z historie v UI stáhne stejná data,
        která už jednou vyexportoval, bez nového exportu. Read-only: bez audit
        záznamu i integrity checkpointu (není nový export).

        STP-068: ``what=bundle&format=zip`` re-downloaduje poslední ZIP bundle
        všech datasetů (cache uložená při ``interop-export-bundle``).

        404 = pro daný dataset+formát ještě nebylo nic exportováno.
        """
        _require("analysis.run", "last_export", case_id=case_id)
        if what not in ("artifacts", "timeline", "correlations", "bundle"):
            raise HTTPException(400, f"neplatný dataset: {what}")
        # STP-068 — bundle se re-downloaduje jen jako zip; ostatní datasety
        # zip neznají (cache layout {what}.{format} je sdílený).
        if what == "bundle":
            valid_formats = ("zip",)
        else:
            valid_formats = ("csv", "json", "jsonl", "xml", "stix", "l2tcsv", "uco")
        if format not in valid_formats:
            raise HTTPException(400, f"neplatný formát: {format}")

        # case musí existovat (open_db → 404), cache nemusí
        db = open_db(case_id)
        db.close()

        path = _load_last_export(case_id, what, format)
        if path is None:
            raise HTTPException(
                404, f"pro {what}/{format} ještě nebylo nic exportováno"
            )

        media_type = {
            "csv": "text/csv",
            "json": "application/json",
            "uco": "application/json",
            "stix": "application/json",
            "jsonl": "application/x-ndjson",
            "xml": "application/xml",
            "l2tcsv": "text/plain",
            "zip": "application/zip",  # STP-068 — ZIP bundle
        }[format]
        # FileResponse s filename= sám nastaví Content-Disposition: attachment.
        return FileResponse(path, media_type=media_type, filename=f"{case_id}_{what}.{format}")

    # ── STP-069 — download posledního automatického ZIP bundle (opt-in) ──
    @app.get("/api/plugins")
    def plugins_list():
        """F6.4 — detekované pluginy: manifest + stav ověření + kapacity."""
        import stopa as _stopa_pkg
        from stopa.data.plugin_loader import discover_plugins

        settings = _load_settings()
        found = discover_plugins(settings=settings, stopa_version=_stopa_pkg.__version__)
        rows = sorted(found.values(), key=lambda x: x.name)
        out = [
            {
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "author": p.author,
                "min_stopa_version": p.min_stopa_version,
                "verified": p.verified,
                "capabilities": list(p.capabilities),
                "issues": list(p.issues),
                "path": str(p.path),
            }
            for p in rows
        ]
        return {"ok": True, "count": len(out), "plugins": out}

    # ── MITRE ATT&CK map (F6.3) ──────────────────────────────
    @app.get("/api/cases/{case_id}/attack-map")
    def attack_map(case_id: str, format: str = "json"):
        """F6.3 — heat-mapa taktik×technik; ``format=stix`` → intrusion-set bundle."""
        from fastapi import Response

        from stopa.domain.mitre_attack import build_attack_heatmap, to_stix_bundle_intrusion_set

        db = open_db(case_id)
        try:
            case = db.get_case(case_id)  # type: ignore[call-arg]
            if case is None:
                raise HTTPException(404, f"case nenalezen: {case_id}")
            arts = db.list_artifacts(limit=10_000)
            hm = build_attack_heatmap(arts)
        finally:
            db.close()

        if format == "stix":
            payload = to_stix_bundle_intrusion_set(case_id, case_name=getattr(case, "name", None), heatmap=hm)
            return Response(
                content=payload.encode("utf-8"),
                media_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="{case_id}_attack-map.stix.json"'
                },
            )
        return hm

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

    # ── F5.2 — SWGDE/ISO 27037 Compliance Report ────────────────
    @app.get("/api/cases/{case_id}/compliance-report")
    def compliance_report(case_id: str, format: str = "pdf"):
        """Podepsaný compliance report (PDF nebo JSON) pro externího auditora."""
        from fastapi import Response

        from stopa.presentation.compliance_report import generate_compliance_report

        db = open_db(case_id)
        try:
            out = generate_compliance_report(db, case_id)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        finally:
            db.close()
        filename = f"{case_id}_compliance.{format}"
        if format == "json":
            content = out["json_path"].read_text(encoding="utf-8").encode("utf-8")
            return Response(
                content=content,
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        if out.get("pdf_path") is None:
            raise HTTPException(500, "PDF compliance report selhal (weasyprint chybí)")
        return Response(
            content=out["pdf_path"].read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ── F5.5 — Daubert challenge preparedness pack (1-click JSON pro soud) ────
    @app.get("/api/cases/{case_id}/daubert-pack")
    def daubert_pack(case_id: str):
        """Daubert balík: peer-reviewed reference, validační testy, error rates."""
        from fastapi import Response

        from stopa.presentation.daubert import generate_daubert_pack

        db = open_db(case_id)
        try:
            out = generate_daubert_pack(db, case_id)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        finally:
            db.close()
        content = out["json_path"].read_text(encoding="utf-8").encode("utf-8")
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{case_id}_daubert.json"'
            },
        )

    # ── F5.4 — Write-blocker integration API (status + attach/remove) ──────────
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
    @app.get("/api/cases/{case_id}/audit")
    def audit_center(
        case_id: str, limit: int = 100, actor: str | None = Query(None)
    ) -> dict:
        """Audit Center — neměnná stopa + integrity v jednom reportu.

        F4.4: ``actor`` volitelně filtruje audit log per user (username).

        Agreguje (čistá čtení nad DB):
        - ``chain`` — výsledek ověření hash řetězce audit logu (C4),
        - ``entries`` — nejnovější záznamy audit trailu (limit, default 100),
        - ``checkpoints`` — Ed25519 kontrolní body + nezávislé ověření podpisů,
        - ``seals`` / ``seal_checks`` — F5.1 Merkle pečetě případu + jejich
          ověření (root shoda + Ed25519 podpis) pro soudní report.

        Selhání degraduje na 500 s logem (defenzivní obal).
        """
        db = open_db(case_id)
        try:
            report = db.verify_audit_chain()
            entries = db.list_audit_log(limit=max(1, min(int(limit), 1000)), actor=actor)
            checkpoints = db.list_integrity_checkpoints()
            checkpoint_checks = db.verify_integrity_checkpoints()
            seals = db.seal_repo.list_seals()
            seal_checks = db.seal_repo.verify_all()
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
                "seals": seals,
                "seal_checks": seal_checks,
            }
        except Exception as e:  # doplňková vrstva — log + degradace
            log.warning("audit center selhal pro %s: %s", case_id, e)
            raise HTTPException(500, f"audit report selhal: {e}") from e
        finally:
            db.close()

    # ── E11 — AI Forensic Assistant (LM Studio) ───────────────
