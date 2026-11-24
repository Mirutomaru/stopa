"""Web routes — soubory a artefakty (files hex/metadata/preview/export, artifacts provenance) (P1-4 vlna C: přesunuto bez změny chování).

Sdílený stav a helpery přicházejí přes ``ctx`` z ``create_app()``;
facade ``stopa.web.app`` volá ``register(app, ctx)`` pro kompatibilitu.
"""

import logging

log = logging.getLogger("stopa.web")


from urllib.parse import quote

from fastapi import HTTPException

from stopa.data.db import CaseDB

from ..app import ReviewStateIn, _hex_dump, _read_file_bytes


def register(app, ctx) -> None:
    """Registruje routy domény; ``ctx`` = sdílený stav create_app()."""
    base = ctx["base"]
    _publish_case = ctx["_publish_case"]
    open_db = ctx["open_db"]
    _require = ctx["_require"]
    _audit_actor = ctx["_audit_actor"]  # B3b — actor pro audit citlivých egress akcí

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
        _require("case.read", "list_files", case_id=case_id)
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

    # F4.3 — Peer-Review Workflow (stavový automat v domain/review.py) ──────────
    @app.get("/api/cases/{case_id}/artifacts")
    def list_artifacts(case_id: str, file_id: str | None = None, limit: int = 500) -> list[dict]:
        """Artefakty případu (volitelně filtr na soubor) včetně review_state."""
        _require("case.read", "list_artifacts", case_id=case_id)
        db = open_db(case_id)
        try:
            arts = db.list_artifacts(limit=limit) if file_id is None else [
                a for a in db.list_artifacts(limit=10_000) if a.file_id == file_id
            ]
            return [a.model_dump(mode="json") for a in arts]
        finally:
            db.close()

    # P3-2 — Artifact Version Comparison (path JSON diff dvou verzí téhož artefaktu)
    @app.get("/api/cases/{case_id}/artifacts/compare")
    def compare_artifact_versions(case_id: str, id_a: str = "", id_b: str = "") -> dict:
        """Srovnání dvou verzí artefaktu (path JSON diff + parser_version provenance).

        Zrcadlí CLI ``stopa compare-artifacts``. 404 pokud některá verze neexistuje;
        400 pro jiný artifact_key / neplatné details_json (semantické chyby domény).
        """
        _require("case.read", "artifact_compare", case_id=case_id)
        from stopa.data.artifact_compare_repository import ArtifactCompareRepository
        from stopa.domain.artifact_compare import compare_artifacts, comparison_to_dict

        db = open_db(case_id)
        try:
            repo = ArtifactCompareRepository(db.conn)
            try:
                rec_a = repo.get_record(id_a)
                rec_b = repo.get_record(id_b)
                missing = [i for i, r in ((id_a, rec_a), (id_b, rec_b)) if r is None]
                if missing:
                    raise HTTPException(404, f"artefakt neexistuje: {', '.join(missing)}")
                result = compare_artifacts(rec_a, rec_b)  # type: ignore[arg-type]
            except (ValueError, TypeError) as exc:
                raise HTTPException(400, str(exc)) from exc
        finally:
            db.close()
        return {"ids": {"a": id_a, "b": id_b}, **comparison_to_dict(result)}
    @app.get("/api/cases/{case_id}/artifacts/{artifact_id}/provenance")
    def artifact_provenance(case_id: str, artifact_id: str) -> dict:
        """P0-1 — řetězec provenience artefaktu (kroky + mezery + upozornění).

        404 = artefakt neexistuje. Kroky jsou chronologické a deterministické;
        ``gaps`` = tvrdé mezery (řetězec neúplný), ``warnings`` = měkké mezery
        (např. legacy hash bez timestampu).
        """
        _require("case.read", "artifact_provenance", case_id=case_id)
        from stopa.data.provenance_repository import ProvenanceRepository

        db = open_db(case_id)
        try:
            ctx = ProvenanceRepository(db.conn).get_artifact_context(artifact_id)
        finally:
            db.close()
        if ctx is None:
            raise HTTPException(404, f"Artefakt {artifact_id} neexistuje")
        from stopa.domain.provenance_chain import build_provenance, provenance_report

        return provenance_report(build_provenance(**ctx))
    @app.post("/api/cases/{case_id}/artifacts/{artifact_id}/review", status_code=201)
    def artifact_review(case_id: str, artifact_id: str, body: ReviewStateIn) -> dict:
        """Přechod review stavu (draft→reviewed→approved→court_ready).

        409 = neplatný přechod/přeskočení/kvorum; 404 = artefakt neexistuje.
        Každá akce = audit log + neměnný řádek v artifact_reviews (F4.3 AK).
        """
        from stopa.domain.review import ReviewError

        _require("case.review", case_id, case_id=case_id)
        db = open_db(case_id)
        try:
            try:
                info = db.artifact_repo.set_review_state(
                    artifact_id, body.state, body.reviewer, note=body.note
                )
            except ReviewError as e:
                raise HTTPException(409, str(e)) from e
            except ValueError as e:  # artefakt neexistuje (ReviewError je subclass)
                raise HTTPException(404, str(e)) from e
        finally:
            db.close()
        _publish_case(case_id, "review.state", **info)
        return info
    @app.get("/api/cases/{case_id}/artifacts/{artifact_id}/reviews")
    def artifact_reviews(case_id: str, artifact_id: str) -> dict:
        """Aktuální stav + kritičnost + neměnná historie review akcí."""
        _require("case.read", "artifact_reviews", case_id=case_id)
        db = open_db(case_id)
        try:
            art = db.get_artifact(artifact_id)
            if art is None:
                raise HTTPException(404, f"artefakt {artifact_id} nenalezen")
            return {
                "artifact_id": artifact_id,
                "review_state": art.review_state,
                "critical": db.artifact_repo.is_critical_artifact(artifact_id),
                "reviews": db.artifact_repo.list_artifact_reviews(artifact_id),
            }
        finally:
            db.close()
    @app.get("/api/cases/{case_id}/files/{file_id}")
    def get_file(case_id: str, file_id: str) -> dict:
        """Detail jednoho souboru + flagy (File Inspector)."""
        _require("case.read", "get_file", case_id=case_id)
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
        _require("case.read", "file_metadata", case_id=case_id)
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
        _require("case.read", "compare_metadata", case_id=case_id)
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
        _require("case.read", "marked_files", case_id=case_id)
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
        _require("case.read", "file_hex", case_id=case_id)
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
        _require("case.read", "file_preview", case_id=case_id)
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
        _require("case.read", "export_file", case_id=case_id)
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
            # B3b — audit citlivého egressu (stáhnutí raw obsahu důkazu);
            # actor = session uživatel, fallback case examiner (legacy BC).
            case = db.get_case(case_id)
            db.log_operation(
                "evidence_exported",
                actor=_audit_actor(case),
                details={"file_id": file_id, "name": name, "bytes": len(data)},
            )
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
