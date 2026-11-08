"""STP-063 — Plaso import GUI (l2tcsv upload, oblast Q ★★).

Web endpoint ``POST /api/cases/{case_id}/plaso-import`` zrcadlí CLI
(``stopa plaso-import``, stejná domain funkce ``import_l2tcsv``): evidence
source + artifacts (idempotentní upsert) + timeline events. Audit + integrity
checkpoint. Chybové cesty: 404 case neexistuje; 415 špatný typ souboru;
422 prázdný / nevalidní UTF-8.

Testy běží offline přes ``TestClient(create_app(db_dir=tmp_path))`` — žádná
externí služba, žádná síť.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture()
def client(tmp_path: Path):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    with TestClient(create_app(db_dir=tmp_path)) as c:
        yield c


def _make_case(client, name: str = "Plaso import test") -> dict:
    r = client.post("/api/cases", json={"name": name, "examiner": "Znalec"})
    assert r.status_code == 201, r.text
    return r.json()


def _l2t_text(rows: list[dict]) -> str:
    """Řádky → l2tcsv text přes skutečnou exportní cestu (plná shoda formátu)."""
    from stopa.domain.export import L2TCSV_COLUMNS, to_l2tcsv

    return to_l2tcsv(rows) if rows else ",".join(L2TCSV_COLUMNS) + "\n"


def _upload(client, case_id: str, text: str, filename: str = "x.l2t.csv"):
    """Multipart POST s jedním polem ``file``."""
    return client.post(
        f"/api/cases/{case_id}/plaso-import",
        files={"file": (filename, text.encode("utf-8"), "text/csv")},
    )


def _audit_actions(db_path: Path) -> list[str]:
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT action FROM audit_log ORDER BY id"
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def _checkpoint_reasons(db_path: Path) -> list[str]:
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT reason FROM integrity_checkpoints ORDER BY id"
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


class TestPlasoImportEndpoint:
    def test_unknown_case_404(self, client):
        text = _l2t_text([{"id": "e1", "timestamp_utc": "2026-10-30T12:00:00+00:00"}])
        r = _upload(client, "neexistuje", text)
        assert r.status_code == 404

    def test_wrong_extension_415(self, client):
        cid = _make_case(client)["id"]
        text = _l2t_text([{"id": "e1"}])
        r = _upload(client, cid, text, filename="x.txt")
        assert r.status_code == 415

    def test_empty_file_422(self, client):
        cid = _make_case(client)["id"]
        r = _upload(client, cid, "   \n  ")
        assert r.status_code == 422

    def test_invalid_utf8_422(self, client):
        cid = _make_case(client)["id"]
        # nevalidní UTF-8 bajty → decode selže → 422
        raw = b"\xff\xfe\x00bad"
        r = client.post(
            f"/api/cases/{cid}/plaso-import",
            files={"file": ("x.l2t.csv", raw, "text/csv")},
        )
        assert r.status_code == 422

    def test_success_imports_and_audits(self, client, tmp_path):
        cid = _make_case(client)["id"]
        rows = [
            {"id": "e1", "timestamp_utc": "2026-10-30T12:00:00+00:00",
             "artifact_type": "browser_history", "title": "https://x.cz"},
            {"id": "e2", "timestamp_utc": None,
             "artifact_type": "email", "title": "mail bez času"},
        ]
        text = _l2t_text(rows)
        r = _upload(client, cid, text)
        assert r.status_code == 200, r.text

        body = r.json()
        # summary klíče — shoda s domain import_l2tcsv return dictem
        for key in ("source_id", "events_total", "artifacts_imported",
                    "timeline_events", "skipped_no_time"):
            assert key in body, f"chybí klíč {key}"

        # 2 události; e1 má čas → timeline event, e2 bez času → jen artifact
        assert body["events_total"] == 2
        assert body["artifacts_imported"] == 2
        assert body["timeline_events"] == 1
        assert body["skipped_no_time"] == 1

        # audit záznam + integrity checkpoint se zapíší
        db_path = tmp_path / f"{cid}.db"
        assert "plaso_import" in _audit_actions(db_path)
        assert "plaso-import" in _checkpoint_reasons(db_path)

    def test_reimport_creates_new_source(self, client):
        """Re-import stejného souboru → nový evidence source (shoda s CLI STP-057).

        Kontrakt domain funkce ``import_l2tcsv``: každý import vytvoří vlastní
        source (náhodné ID), upsert deduplikuje jen uvnitř jednoho source.
        Web endpoint zrcadlí toto chování 1:1 s CLI.
        """
        cid = _make_case(client)["id"]
        rows = [
            {"id": "e1", "timestamp_utc": "2026-10-30T12:00:00+00:00",
             "artifact_type": "browser_history", "title": "https://x.cz"},
        ]
        text = _l2t_text(rows)

        r1 = _upload(client, cid, text)
        assert r1.status_code == 200, r1.text
        first_source = r1.json()["source_id"]

        r2 = _upload(client, cid, text)
        assert r2.status_code == 200, r2.text
        # nový source (shoda s CLI test_reimport_is_idempotent), ale import funguje
        assert r2.json()["source_id"] != first_source
        assert r2.json()["events_total"] == 1


class TestPlasoImportAuditDetails:
    def test_audit_details_carry_file_and_summary(self, client, tmp_path):
        cid = _make_case(client)["id"]
        rows = [
            {"id": "e1", "timestamp_utc": "2026-10-30T12:00:00+00:00",
             "artifact_type": "browser_history", "title": "https://x.cz"},
        ]
        r = _upload(client, cid, _l2t_text(rows), filename="case.l2t.csv")
        assert r.status_code == 200

        con = sqlite3.connect(tmp_path / f"{cid}.db")
        try:
            row = con.execute(
                "SELECT details_json FROM audit_log"
                " WHERE action='plaso_import' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            con.close()
        assert row is not None
        details = json.loads(row[0])
        # audit nese název souboru + summary počty (prohledatelnost)
        assert details["file"] == "case.l2t.csv"
        assert details["events_total"] == 1
