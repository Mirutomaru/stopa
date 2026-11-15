"""F3.5 — Hypothesis Graph (AI generuje graf hypotéz, člověk potvrzuje/vyvrací).

AK F3.5 (ROADMAP V2, Fáze 3):
- **Graf v UI** → payload uzly + hrany + lineage; web endpointy E2E (TestClient);
- **Lineage k artifactům** → citace (ID artefaktů) se rozřeší na existující
  artefakty (fail-soft: neexistující vyřadí);
- **Export PDF/JSON** → JSON round-trip; PDF přes WeasyPrint (graceful RuntimeError).

Uzel = claim + confidence (0.1–0.9 CHECK) + status pending/confirmed/refuted
+ support/against (ID artefaktů). Strom podhypotéz přes ``parent_id``.
LLM je injektovatelná (``llm_call(prompt) -> str``, JSON výstup); deterministický
fallback = detekované triage profily F3.2 (bez LLM).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from stopa.intelligence.hypothesis_graph import (
    EVIDENCE_CAP_PER_SIDE,
    MAX_CONFIDENCE,
    MAX_NODES,
    MIN_CONFIDENCE,
    HypothesisGraphError,
    build_hypothesis_graph,
    export_graph_json,
    graph_payload,
    store_graph,
)

CASE_ID = "case-f35"
SRC_ID = "src-f35"


# ── stavba case DB (pattern F3.2/F3.4) ───────────────────────────────


def _fresh_db(root: Path, name: str | None = None):
    from stopa.data.db import CaseDB

    db = CaseDB(str(root / f"{name or 'f35_hypo'}.db"))
    now = "2026-01-01T00:00:00"
    db.conn.execute("INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)", (CASE_ID, CASE_ID.upper(), now))
    db.conn.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES (?, ?, 'folder', '/tmp/f35-seed', ?)",
        (SRC_ID, CASE_ID, now),
    )
    db.conn.commit()
    return db


def _art(db, artifact_type: str, title: str, rel_path: str | None = None) -> str:
    from stopa.models import Artifact

    a = Artifact(
        source_id=SRC_ID,
        artifact_type=artifact_type,
        timestamp=datetime(2026, 1, 5),
        title=title,
        details={},
        rel_path=rel_path,
    )
    db.upsert_artifact(a)
    return a.id


def _file(db, name: str) -> None:
    from stopa.models import FileRecord, new_id

    rec = FileRecord(
        id=new_id("f"),
        source_id=SRC_ID,
        rel_path=name,
        name=name.rsplit("/", 1)[-1],
        size_bytes=2048,
        mtime=datetime(2026, 1, 1),
        sha256=hashlib.sha256(name.encode()).hexdigest(),
        extension=name.rsplit(".", 1)[-1] if "." in name else "",
    )
    db.upsert_file(rec)


def seed_ransomware(db):
    """Syntetické RANSOMWARE pozitivum (2 signály, skóre ≥ threshold F3.2)."""
    ids = [_art(db, "antiforensics/timestomping", "bulk-touch 42 souborů")]
    _file(db, "docs/quarterly.locked")
    db.conn.commit()  # upsert_file necommituje (na rozdíl od upsert_artifact)
    return ids


# ── fallback (bez LLM) z triage F3.2 ────────────────────────────────


def test_ak_fallback_graph_from_triage_detection(tmp_path):
    db = _fresh_db(tmp_path, "f35_fb1")
    seed_ransomware(db)
    nodes = build_hypothesis_graph(db, CASE_ID)
    assert len(nodes) >= 1
    for n in nodes:
        assert n.claim.strip()
        assert MIN_CONFIDENCE <= n.confidence <= MAX_CONFIDENCE
        assert n.status == "pending"
    # claim = hypotéza z template RANSOMWARE profilu
    assert any("RANSOMWARE" in n.claim for n in nodes)
    db.close()


def test_fallback_deterministic_no_llm(tmp_path):
    """Bez LLM = deterministický výsledek (dvakrát totéž)."""
    db = _fresh_db(tmp_path, "f35_fb2")
    seed_ransomware(db)
    a = build_hypothesis_graph(db, CASE_ID)
    b = build_hypothesis_graph(db, CASE_ID)
    assert [n.claim for n in a] == [n.claim for n in b]
    assert [n.confidence for n in a] == [n.confidence for n in b]
    db.close()


def test_empty_case_fallback_empty(tmp_path):
    """Případ bez signálů → prázdný graf (žádný profil nedetekován)."""
    db = _fresh_db(tmp_path, "f35_fb3")
    assert build_hypothesis_graph(db, CASE_ID) == []
    db.close()


# ── ukládání + strom podhypotéz ─────────────────────────────────────


def test_store_and_read_roundtrip(tmp_path):
    db = _fresh_db(tmp_path, "f35_crud")
    seed_ransomware(db)
    nodes = build_hypothesis_graph(db, CASE_ID)
    ids = store_graph(db, CASE_ID, nodes, source="fallback")
    assert len(ids) == len(nodes)
    rows = db.list_hypotheses(CASE_ID)
    assert len(rows) == len(nodes)
    for row in rows:
        assert row["case_id"] == CASE_ID
        assert row["status"] == "pending"
        assert isinstance(row["support"], list)
        assert isinstance(row["against"], list)
    got = db.get_hypothesis(ids[0])
    assert got is not None and got["claim"] == nodes[0].claim
    db.close()


def test_ak_manual_confirm_refute(tmp_path):
    """Ruční potvrzení/vyvrácení — přechody stavů (AK F3.5)."""
    db = _fresh_db(tmp_path, "f35_status")
    hid = db.add_hypothesis(CASE_ID, "Útočitel pracoval z VPN", confidence=0.7)
    assert db.set_hypothesis_status(hid, "confirmed") is True
    row = db.get_hypothesis(hid)
    assert row is not None and row["status"] == "confirmed"
    assert db.set_hypothesis_status(hid, "refuted") is True
    row = db.get_hypothesis(hid)
    assert row is not None and row["status"] == "refuted"
    # zpět na pending = „znovu zvážit“
    assert db.set_hypothesis_status(hid, "pending") is True
    with pytest.raises(ValueError):
        db.set_hypothesis_status(hid, "open")
    # neexistující uzel → False (ne výjimka)
    assert db.set_hypothesis_status("hyp-xyz", "confirmed") is False
    db.close()


def test_confidence_check_constraint(tmp_path):
    """Confidence je interval interpretace: CHECK 0.1–0.9."""
    db = _fresh_db(tmp_path, "f35_conf")
    with pytest.raises(sqlite3.IntegrityError):
        db.add_hypothesis(CASE_ID, "příliš jistá", confidence=0.95)
    with pytest.raises(sqlite3.IntegrityError):
        db.add_hypothesis(CASE_ID, "příliš nejistá", confidence=0.05)
    hi = db.add_hypothesis(CASE_ID, "horní hrana", confidence=MAX_CONFIDENCE)
    lo = db.add_hypothesis(CASE_ID, "dolní hrana", confidence=MIN_CONFIDENCE)
    assert db.get_hypothesis(hi)["confidence"] == 0.9
    assert db.get_hypothesis(lo)["confidence"] == 0.1
    with pytest.raises(ValueError):
        db.add_hypothesis(CASE_ID, "   ")  # prázdný claim
    db.close()


def test_parent_tree_edges(tmp_path):
    """Strom podhypotéz: parent_id → hrana type=parent v payloadu."""
    db = _fresh_db(tmp_path, "f35_tree")
    parent = db.add_hypothesis(CASE_ID, "Data odcizena", confidence=0.6)
    child = db.add_hypothesis(CASE_ID, "Odcizení přes USB", confidence=0.4, parent_id=parent)
    payload = graph_payload(db, CASE_ID)
    assert {"source": child, "target": parent, "type": "parent"} in payload["edges"]
    # pořadí vkladu zachováno (rodice před dítětem v list)
    rows = db.list_hypotheses(CASE_ID)
    assert [r["id"] for r in rows] == [parent, child]
    assert rows[1]["parent_id"] == parent
    db.close()


# ── LLM cesta (injektovatelná) ──────────────────────────────────────


def test_llm_json_parsing_and_grounding(tmp_path):
    """LLM JSON: grounding citace (neexistující vyřadí) + clamp confidence."""
    db = _fresh_db(tmp_path, "f35_llm1")
    good_art = _art(db, "network/ioc", "IoC c2_beaconing", rel_path="f35/llm1.bin")
    llm_out = json.dumps(
        [
            {
                "claim": "C2 komunikace na 30 s intervalu",
                "support": [good_art, "art-neexistuje"],
                "against": [],
                "confidence": 1.5,  # clamp → 0.9
            },
            {"claim": "Jiná hypotéza", "support": [], "against": [], "confidence": -3},  # clamp → 0.1
            {"claim": "Třetí", "support": [], "against": [], "confidence": "abc"},  # → default 0.5
        ]
    )
    nodes = build_hypothesis_graph(db, CASE_ID, llm_call=lambda prompt: llm_out)
    assert len(nodes) == 3
    assert nodes[0].support == [good_art]  # neexistující art-neexistuje vyřazen
    assert nodes[0].confidence == MAX_CONFIDENCE
    assert nodes[1].confidence == MIN_CONFIDENCE
    assert nodes[2].confidence == 0.5
    db.close()


def test_llm_parent_index_mapping(tmp_path):
    """Parent = index v JSON poli; přeskočený prvek nesmí posunout mapping."""
    db = _fresh_db(tmp_path, "f35_llm2")
    llm_out = json.dumps(
        [
            {"claim": "A — kořen", "support": [], "against": []},
            {"claim": "B — pod A", "parent": 0, "support": [], "against": []},
            {"claim": ""},  # prázdný claim → vyřazen (pozice 2)
            {"claim": "D — pod B", "parent": 1, "support": [], "against": []},
        ]
    )
    nodes = build_hypothesis_graph(db, CASE_ID, llm_call=lambda prompt: llm_out)
    assert [n.claim for n in nodes] == ["A — kořen", "B — pod A", "D — pod B"]
    ids = store_graph(db, CASE_ID, nodes, source="llm")
    a_id, b_id, d_id = ids
    a_row = db.get_hypothesis(a_id)
    b_row = db.get_hypothesis(b_id)
    d_row = db.get_hypothesis(d_id)
    assert a_row is not None and b_row is not None and d_row is not None
    assert a_row["parent_id"] is None
    assert b_row["parent_id"] == a_id  # parent=0 → A
    assert d_row["parent_id"] == b_id  # parent=1 → B (i když pozice 2 vyřazena)
    db.close()


def test_llm_invalid_output_raises(tmp_path):
    """Fail-closed: neplatný JSON výstup LLM → HypothesisGraphError."""
    db = _fresh_db(tmp_path, "f35_llm3")

    with pytest.raises(HypothesisGraphError, match="JSON"):
        build_hypothesis_graph(db, CASE_ID, llm_call=lambda prompt: "to není json {")

    with pytest.raises(HypothesisGraphError, match="pole"):
        build_hypothesis_graph(db, CASE_ID, llm_call=lambda prompt: '{"claim": "x"}')
    db.close()


def test_max_nodes_cap(tmp_path):
    """AI nesmí explodovat: max MAX_NODES uzlů."""
    db = _fresh_db(tmp_path, "f35_cap")
    many = json.dumps([{"claim": f"Hypotéza {i}", "support": [], "against": []} for i in range(25)])
    nodes = build_hypothesis_graph(db, CASE_ID, llm_call=lambda prompt: many)
    assert len(nodes) == MAX_NODES
    ids = store_graph(db, CASE_ID, nodes)
    assert len(ids) == MAX_NODES
    db.close()


def test_evidence_cap_per_side(tmp_path):
    """Důkazy na stranu omezeny EVIDENCE_CAP_PER_SIDE."""
    db = _fresh_db(tmp_path, "f35_ev")
    arts = [_art(db, "network/ioc", f"ioc-{i}", rel_path=f"f35/ev{i}.bin") for i in range(30)]
    llm_out = json.dumps([{"claim": "Hromadné IoC", "support": arts, "against": []}])
    nodes = build_hypothesis_graph(db, CASE_ID, llm_call=lambda prompt: llm_out)
    assert len(nodes[0].support) == EVIDENCE_CAP_PER_SIDE
    db.close()


# ── lineage + export (AK F3.5) ──────────────────────────────────────


def test_ak_lineage_resolves_citations(tmp_path):
    """Lineage: citace se rozřeší na existující artefakty; hrany support/against."""
    db = _fresh_db(tmp_path, "f35_lin")
    sup_art = _art(db, "antiforensics/timestomping", "bulk-touch", rel_path="f35/l1.bin")
    agn_art = _art(db, "network/ioc", "C2 IoC", rel_path="f35/l2.bin")
    hid = db.add_hypothesis(CASE_ID, "Timestomp maskuje exfiltrace", support=[sup_art], against=[agn_art])
    payload = graph_payload(db, CASE_ID)
    assert len(payload["nodes"]) == 1
    lin = payload["lineage"][hid]
    assert [a["id"] for a in lin["support"]] == [sup_art]
    assert lin["support"][0]["artifact_type"] == "antiforensics/timestomping"
    assert lin["support"][0]["title"] == "bulk-touch"
    assert [a["id"] for a in lin["against"]] == [agn_art]
    # hrany na obě strany důkazů
    assert {"source": hid, "target": sup_art, "type": "support"} in payload["edges"]
    assert {"source": hid, "target": agn_art, "type": "against"} in payload["edges"]
    db.close()


def test_lineage_failsoft_missing_citation(tmp_path):
    """Neexistující citace se vyřadí (fail-soft), ne spadne graf."""
    db = _fresh_db(tmp_path, "f35_lins")
    hid = db.add_hypothesis(CASE_ID, "Citace bez podkladu", support=["art-nebylo-tam"])
    payload = graph_payload(db, CASE_ID)
    assert payload["lineage"][hid]["support"] == []
    db.close()


def test_ak_export_json_roundtrip(tmp_path):
    """Export JSON: validní JSON s uzly/hranami/lineage (AK F3.5)."""
    db = _fresh_db(tmp_path, "f35_expj")
    seed_ransomware(db)
    nodes = build_hypothesis_graph(db, CASE_ID)
    store_graph(db, CASE_ID, nodes, source="fallback")
    text = export_graph_json(db, CASE_ID)
    data = json.loads(text)  # validní JSON
    assert set(data.keys()) == {"case_id", "nodes", "edges", "lineage"}
    assert data["case_id"] == CASE_ID
    assert len(data["nodes"]) == len(nodes)
    for n in data["nodes"]:
        assert {"id", "claim", "confidence", "status", "support", "against", "parent_id"} <= set(n.keys())
    db.close()


def test_export_pdf_weasyprint_or_degradation(tmp_path):
    """Export PDF: WeasyPrint → %PDF; bez balíku → RuntimeError (graceful)."""
    import importlib.util

    db = _fresh_db(tmp_path, "f35_expp")
    seed_ransomware(db)
    nodes = build_hypothesis_graph(db, CASE_ID)
    store_graph(db, CASE_ID, nodes, source="fallback")
    out = tmp_path / "graph.pdf"
    if importlib.util.find_spec("weasyprint"):
        from stopa.intelligence.hypothesis_graph import export_graph_pdf

        export_graph_pdf(db, CASE_ID, out)
        assert out.read_bytes()[:4] == b"%PDF"
    else:  # pragma: no cover — závisí na instalaci venvu
        from stopa.intelligence.hypothesis_graph import export_graph_pdf

        with pytest.raises(RuntimeError, match="WeasyPrint"):
            export_graph_pdf(db, CASE_ID, out)
    db.close()


def test_store_graph_audit_log(tmp_path):
    """Generování grafu se loguje do audit (traceability)."""
    db = _fresh_db(tmp_path, "f35_aud")
    seed_ransomware(db)
    nodes = build_hypothesis_graph(db, CASE_ID)
    store_graph(db, CASE_ID, nodes, source="llm")
    rows = db.conn.execute(
        "SELECT action, details_json FROM audit_log WHERE action = 'hypothesis_graph_generated'"
    ).fetchall()
    assert len(rows) == 1
    details = json.loads(rows[0][1])
    assert details["source"] == "llm"
    assert details["nodes"] == len(nodes)
    db.close()


# ── web API E2E (Graf v UI — AK F3.5) ───────────────────────────────


@pytest.fixture()
def client(tmp_path: Path):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    # case DB přímo pod db_dir appky (open_db = {db_dir}/{case_id}.db)
    db = _fresh_db(tmp_path, CASE_ID)
    seed_ransomware(db)
    db.close()

    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c


def test_web_graph_lifecycle(client):
    """E2E: generate → list → confirm/refute → export JSON."""
    # prázdný graf na začátku
    r = client.get(f"/api/cases/{CASE_ID}/hypotheses")
    assert r.status_code == 200
    assert r.json()["nodes"] == []

    # generování (deterministický fallback — bez LLM)
    r = client.post(
        f"/api/cases/{CASE_ID}/hypotheses/generate", json={"use_ai": False}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["nodes"] >= 1
    hid = body["ids"][0]

    # ruční potvrzení (AK F3.5)
    r = client.post(f"/api/cases/{CASE_ID}/hypotheses/{hid}/status", json={"status": "confirmed"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed"

    # vyvrácení
    r = client.post(f"/api/cases/{CASE_ID}/hypotheses/{hid}/status", json={"status": "refuted"})
    assert r.json()["status"] == "refuted"

    # neplatný stav → 400
    r = client.post(f"/api/cases/{CASE_ID}/hypotheses/{hid}/status", json={"status": "open"})
    assert r.status_code == 400

    # export JSON
    r = client.get(f"/api/cases/{CASE_ID}/hypotheses/export?format=json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    data = json.loads(r.text)
    assert len(data["nodes"]) >= 1

    # neplatný formát → 400
    assert client.get(f"/api/cases/{CASE_ID}/hypotheses/export?format=csv").status_code == 400


def test_web_generate_ai_unavailable_503(client, monkeypatch):
    """use_ai=True bez LM Studio → 503 (jasná diagnóza pro uživatele)."""
    import stopa.web.app as app_mod

    class _FakeClient:
        def health(self) -> dict:
            return {"available": False, "model": None}

    monkeypatch.setattr(app_mod, "LmStudioClient", _FakeClient)
    r = client.post(f"/api/cases/{CASE_ID}/hypotheses/generate", json={"use_ai": True})
    assert r.status_code == 503
    assert "LM Studio" in r.json()["detail"]


def test_web_404_unknown_case(client):
    r = client.get("/api/cases/case-neexistuje/hypotheses")
    assert r.status_code == 404
