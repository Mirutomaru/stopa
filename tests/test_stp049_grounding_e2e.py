"""STP-049 — AI Copilot grounding: E2E testy přes web endpoint.

Vrstva nad ``test_stp049_grounding.py`` (čistá domain logika): ověřuje, že
web endpoint ``POST /api/cases/{id}/ai/query`` ve všech třech režimech
(nl_search / summary / explain) vrací pole ``grounding`` s reportem
rozporů mezi odpovědí LLM a daty citovaných záznamů.

Offline: TestClient + monkeypatchovaný LmStudioClient (stejný vzor jako
E11 v ``test_e11.py``) — žádný reálný LM Studio, žádná síť.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

CASE_ID = "c-g"


@pytest.fixture()
def gnd_db(tmp_path: Path):
    """Case DB se 2 soubory (bez teček v ID — CITATION_RE je nepouští) + 2 artifacty."""
    from stopa.data.db import CaseDB
    from stopa.models import Artifact, FileRecord

    db = CaseDB(str(tmp_path / f"{CASE_ID}.db"))
    src_id = "src-g"
    now = "2026-01-01T00:00:00"  # deterministické (bez utcnow → DTZ003)
    db.conn.execute(
        "INSERT INTO cases (id, name, created_at) VALUES (?, 'GND', ?)", (CASE_ID, now)
    )
    db.conn.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES (?, ?, 'folder', '/tmp/gnd', ?)",
        (src_id, CASE_ID, now),
    )
    db.conn.commit()

    def mkfile(fid: str, name: str, size: int, mtime_iso: str) -> FileRecord:
        rec = FileRecord(
            id=fid, source_id=src_id, rel_path=name, name=name,
            size_bytes=size, mtime=mtime_iso,
            sha256=hashlib.sha256(name.encode()).hexdigest(), extension=name.rsplit(".", 1)[-1],
        )
        db.upsert_file(rec)
        return rec

    big = mkfile("file-big", "velky.jpg", 2 * 1024**2, "2026-03-10T12:00:00")
    small = mkfile("file-small", "maly.txt", 100, "2025-12-01T08:00:00")

    art1 = Artifact(
        id="art-g1", source_id=src_id, file_id=big.id, rel_path="velky.jpg",
        artifact_type="exif_photo", timestamp="2026-03-10T12:05:00",
        title="EXIF: fotograf JaneDoe", details={"author": "JaneDoe"}, confidence=0.9,
    )
    art2 = Artifact(
        id="art-g2", source_id=src_id, file_id=small.id, rel_path="maly.txt",
        artifact_type="document_metadata", timestamp=None, title="TXT autor: M.M.",
        details={"author": "M.M."}, confidence=0.6,
    )
    db.upsert_artifact(art1)
    db.upsert_artifact(art2)

    yield db
    db.close()


@pytest.fixture()
def gnd_client(gnd_db: object, tmp_path: Path):
    from stopa.web.app import create_app

    return TestClient(create_app(db_dir=tmp_path))


class _FakeAiClient:
    """Nahrazení LmStudioClient — `response` se vrací pro každý chat()."""

    response = "default"

    def __init__(self, *a, **k) -> None:
        pass

    def health(self) -> dict:
        return {"available": True, "model": "fake-model"}

    def chat(self, messages, max_tokens=None) -> str:
        return self.response


def _patch_ai(monkeypatch: pytest.MonkeyPatch, response: str) -> None:

    fake = type("Fake", (_FakeAiClient,), {"response": response})
    monkeypatch.setattr("stopa.web.routers.ai.LmStudioClient", fake)


def _query(client: TestClient, payload: dict) -> dict:
    r = client.post(f"/api/cases/{CASE_ID}/ai/query", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


class TestGroundingSummaryMode:
    def test_mismatch_date_detected(self, gnd_client, monkeypatch):
        """Odpověď tvrdí datum 2026-03-11, ale artifact má timestamp 2026-03-10."""
        _patch_ai(monkeypatch, "Případ obsahuje fotografii z 2026-03-11 [art:art-g1].")
        body = _query(gnd_client, {"mode": "summary"})

        assert "[art:" not in body["answer"]  # tokeny vyčištěné (E11 chování)
        g = body["grounding"]
        assert g is not None
        cats = {(f["category"], f["citation_id"]) for f in g["findings"]}
        assert ("mismatch_date", "art-g1") in cats
        finding = next(f for f in g["findings"] if f["category"] == "mismatch_date")
        assert finding["claim"] == "2026-03-11"
        assert finding["actual"] == "2026-03-10"
        assert "art-g1" not in g["verified"]  # rozporná citace není ověřená

    def test_correct_date_verified(self, gnd_client, monkeypatch):
        """Shodné datum → žádný rozpor, citace v verified."""
        _patch_ai(monkeypatch, "Fotografie z 2026-03-10 [art:art-g1].")
        body = _query(gnd_client, {"mode": "summary"})

        g = body["grounding"]
        assert g is not None
        assert g["findings"] == []
        assert "art-g1" in g["verified"]

    def test_no_citations_grounding_none(self, gnd_client, monkeypatch):
        """Bez validních citací → grounding=None (žádné co ověřovat)."""
        _patch_ai(monkeypatch, "Shrnutí bez jakýchkoli citací.")
        body = _query(gnd_client, {"mode": "summary"})

        assert body["citations"] == []
        assert body["grounding"] is None


class TestGroundingExplainMode:
    def test_mismatch_type_detected(self, gnd_client, monkeypatch):
        """Odpověď nazývá exif_photo jako sms_message → mismatch_type."""
        _patch_ai(monkeypatch, "Jde o sms_message z 2026-03-10 [art:art-g1].")
        body = _query(gnd_client, {"mode": "explain", "artifact_id": "art-g1"})

        g = body["grounding"]
        assert g is not None
        cats = {(f["category"], f["citation_id"]) for f in g["findings"]}
        assert ("mismatch_type", "art-g1") in cats
        finding = next(f for f in g["findings"] if f["category"] == "mismatch_type")
        assert finding["claim"].lower() == "sms_message"
        assert finding["actual"] == "exif_photo"

    def test_consistent_explain_verified(self, gnd_client, monkeypatch):
        """Správný typ + shodné datum → ověřená citace bez findings."""
        _patch_ai(monkeypatch, "Jde o exif_photo z 2026-03-10 [art:art-g1].")
        body = _query(gnd_client, {"mode": "explain", "artifact_id": "art-g1"})

        g = body["grounding"]
        assert g is not None
        assert g["findings"] == []
        assert "art-g1" in g["verified"]


class TestGroundingNlSearchMode:
    def test_mismatch_date_via_inline_token(self, gnd_client, monkeypatch):
        """LLM napíše inline citaci souboru + špatné datum → mismatch_date.

        Citace v nl_search = výsledky vyhledávání (file_id); grounding je
        aktivní jen pokud model do odpovědi napíše i inline token [art:<id>].
        """
        _patch_ai(monkeypatch, json.dumps(
            {"query": "size:>1MB",
             "explanation": "Velký soubor z 2026-03-11 [art:file-big]",
             "confidence": 0.9}
        ))
        body = _query(gnd_client, {"mode": "nl_search", "question": "co je velké?"})

        assert {c["rel_path"] for c in body["citations"]} == {"velky.jpg"}
        g = body["grounding"]
        assert g is not None
        cats = {(f["category"], f["citation_id"]) for f in g["findings"]}
        assert ("mismatch_date", "file-big") in cats

    def test_plain_json_no_inline_tokens(self, gnd_client, monkeypatch):
        """Běžný JSON bez inline tokenů → report bez findings (nic neattribuovat)."""
        _patch_ai(monkeypatch, json.dumps(
            {"query": "size:>1MB", "explanation": "Soubory větší než 1 MB", "confidence": 0.9}
        ))
        body = _query(gnd_client, {"mode": "nl_search", "question": "co je velké?"})

        g = body["grounding"]
        assert g is not None
        assert g["findings"] == []
        # všechny citace bez rozporu → verified
        assert set(g["verified"]) == {c["file_id"] for c in body["citations"]}


class TestGroundingResponseShape:
    def test_all_modes_carry_grounding_key(self, gnd_client, monkeypatch):
        """Kontrakt odpovědi: pole ``grounding`` existuje ve všech režimech."""
        _patch_ai(monkeypatch, "Fotografie z 2026-03-10 [art:art-g1].")
        for payload in ({"mode": "summary"},
                        {"mode": "explain", "artifact_id": "art-g1"}):
            body = _query(gnd_client, payload)
            assert "grounding" in body
            if body["grounding"] is not None:
                assert set(body["grounding"]) == {"verified", "findings"}
