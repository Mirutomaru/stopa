"""F4.3 — Peer-Review Workflow: stavový automat + kritičnost + audit trail + report filtr.

Akcepční kritéria (ROADMAP V2 F4.3):
- Každý artefakt prochází stavy ``draft → reviewed → approved → court_ready``;
  přechod **vždy přesně o jeden krok** — přeskočení i zpětný přechod selže.
- Kritický artefakt (odkazuje na něj analytický nález) vyžaduje k schválení
  **minimálně dvou distinct examinátorů** — stejný člověk se nepočítá dvakrát.
- Každá review akce se zapisuje do audit logu (hash chaining + neměnná historie).
- Report obsahuje jen události od court-ready artefaktů, pokud workflow běží;
  bez aktivního workflow zůstává report kompletní (backward compat).
"""

from __future__ import annotations

import itertools
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stopa.data.db import CaseDB
from stopa.domain.evidence_model import Finding, Provenance
from stopa.domain.review import (
    MIN_CRITICAL_APPROVERS,
    STATES,
    ReviewError,
    can_transition,
    check_transition,
)
from stopa.models import Artifact, Case, EvidenceSource, FileRecord
from stopa.presentation.case_report import build_report_data

T0 = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


# ── Čistý stavový automat (bez DB — deterministický offline test) ────────────
class TestStateMachine:
    def test_valid_steps_forward(self):
        for cur, nxt in itertools.pairwise(STATES):
            assert can_transition(cur, nxt) is True
            check_transition(cur, nxt, is_critical=True, participants=["A", "B"])

    def test_final_state_has_no_target(self):
        assert can_transition("court_ready", "draft") is False

    def test_skip_rejected(self):
        with pytest.raises(ReviewError):
            check_transition("draft", "approved", is_critical=False, participants=["A"])
        with pytest.raises(ReviewError):
            check_transition("draft", "court_ready", is_critical=True, participants=["A", "B"])

    def test_backward_rejected(self):
        with pytest.raises(ReviewError):
            check_transition("approved", "reviewed", is_critical=False, participants=["A"])

    def test_same_state_rejected(self):
        with pytest.raises(ReviewError):
            check_transition("draft", "draft", is_critical=False, participants=["A"])

    def test_unknown_states_rejected(self):
        with pytest.raises(ReviewError):
            check_transition("foo", "reviewed", is_critical=False, participants=["A"])
        with pytest.raises(ReviewError):
            check_transition("draft", "bar", is_critical=False, participants=["A"])

    def test_min_critial_approvers_constant(self):
        assert MIN_CRITICAL_APPROVERS == 2

    def test_critical_two_distinct_ok(self):
        check_transition("reviewed", "approved", is_critical=True, participants=["A", "B"])

    def test_critical_same_person_twice_fails(self):
        """Stejný člověk se nedá počítat dvakrát — distinct kvorum."""
        with pytest.raises(ReviewError):
            check_transition("reviewed", "approved", is_critical=True, participants=["A", "A"])

    def test_non_critical_single_approver_ok(self):
        """Nekritický artefakt zvládne jeden člověk celý workflow."""
        for cur, nxt in itertools.pairwise(STATES):
            check_transition(cur, nxt, is_critical=False, participants=["A"])


# ── DB vrstva (CaseDB + ArtifactRepository) ───────────────────────────────────
def _seed(tmp_path: Path, critical: bool = False) -> tuple[str, str, CaseDB]:
    """Případ + zdroj + soubor + artefakt (+ nález u kritického). Vrací (case_id, art_id, db)."""
    db = CaseDB(tmp_path / "c.db")
    c = Case(name="T")
    db.add_case(c)
    cid = c.id
    s = EvidenceSource(case_id=cid, kind="file", path="/evidence")
    db.add_source(s)
    fid = db.upsert_file(
        FileRecord(source_id=s.id, rel_path="doc.txt", name="doc.txt", size_bytes=10)
    )
    art = Artifact(source_id=s.id, file_id=fid, artifact_type="browser_history", title="Art")
    db.upsert_artifact(art)
    arts = db.list_artifacts(limit=10)
    assert len(arts) == 1
    aid = arts[0].id
    if critical:
        db.add_finding(
            Finding(
                case_id=cid,
                kind="anomaly",
                provenance=[Provenance(parser_id="p", parser_version="1", file_id=fid)],
            )
        )
    return cid, aid, db


class TestDbLayer:
    def test_critical_detection(self, tmp_path: Path):
        _, crit_id, db = _seed(tmp_path / "a", critical=True)
        assert db.artifact_repo.is_critical_artifact(crit_id) is True

        # druhý případ bez nálezu → nekritický
        _cid2, plain_id, db2 = _seed(tmp_path / "b", critical=False)
        assert db2.artifact_repo.is_critical_artifact(plain_id) is False
        db.close()
        db2.close()

    def test_full_workflow_three_examiners(self, tmp_path: Path):
        """A→B→C — kritický artefakt projde celým workflow se 3 distinct lidmi."""
        _cid, aid, db = _seed(tmp_path, critical=True)
        for i, (reviewer, state) in enumerate(
            [("A", "reviewed"), ("B", "approved"), ("C", "court_ready")]
        ):
            info = db.artifact_repo.set_review_state(aid, state, reviewer, note=f"step{i}")
            assert info["review_state"] == state
            assert info["previous_state"] == STATES[i]

        row = db.conn.execute(
            "SELECT review_state FROM artifacts WHERE id = ?", (aid,)
        ).fetchone()
        assert row["review_state"] == "court_ready"

        # neměnná historie — 3 řádky v pořadí, s distinct examinátory
        history = db.artifact_repo.list_artifact_reviews(aid)
        assert [(r["reviewer"], r["new_state"]) for r in history] == [
            ("A", "reviewed"),
            ("B", "approved"),
            ("C", "court_ready"),
        ]

        # audit log — každá akce zapsaná s aktorem (hash chaining v AuditRepository)
        audits = [e for e in db.list_audit_log(limit=500) if e["action"] == "artifact.review"]
        assert len(audits) == 3
        assert {a["actor"] for a in audits} == {"A", "B", "C"}
        db.close()

    def test_single_examiner_blocked_on_critical(self, tmp_path: Path):
        """Kritický + jen A → zůstane na 'reviewed', schválení selže."""
        _cid, aid, db = _seed(tmp_path, critical=True)
        db.artifact_repo.set_review_state(aid, "reviewed", "A")
        with pytest.raises(ReviewError):
            db.artifact_repo.set_review_state(aid, "approved", "A")
        # DB nedotčená přechodem (stále reviewed, jen 1 review řádek)
        row = db.conn.execute(
            "SELECT review_state FROM artifacts WHERE id = ?", (aid,)
        ).fetchone()
        assert row["review_state"] == "reviewed"
        assert len(db.artifact_repo.list_artifact_reviews(aid)) == 1
        db.close()

    def test_non_critical_solo_full_path(self, tmp_path: Path):
        """Nekritický artefakt zvládne jeden člověk až do court_ready."""
        _cid, aid, db = _seed(tmp_path, critical=False)
        for state in ("reviewed", "approved", "court_ready"):
            db.artifact_repo.set_review_state(aid, state, "A")
        row = db.conn.execute(
            "SELECT review_state FROM artifacts WHERE id = ?", (aid,)
        ).fetchone()
        assert row["review_state"] == "court_ready"
        db.close()

    def test_skip_transition_db_unchanged(self, tmp_path: Path):
        _cid, aid, db = _seed(tmp_path, critical=False)
        with pytest.raises(ReviewError):
            db.artifact_repo.set_review_state(aid, "approved", "A")  # přeskočí reviewed
        row = db.conn.execute(
            "SELECT review_state FROM artifacts WHERE id = ?", (aid,)
        ).fetchone()
        assert row["review_state"] == "draft"
        assert db.artifact_repo.list_artifact_reviews(aid) == []
        db.close()

    def test_unknown_artifact_value_error(self, tmp_path: Path):
        _cid, _aid, db = _seed(tmp_path)
        with pytest.raises(ValueError):
            db.artifact_repo.set_review_state("art_neexistuje", "reviewed", "A")
        db.close()

    def test_reviewer_required(self, tmp_path: Path):
        _cid, aid, db = _seed(tmp_path)
        with pytest.raises(ReviewError):
            db.artifact_repo.set_review_state(aid, "reviewed", "   ")
        db.close()


# ── Web API (FastAPI TestClient) ─────────────────────────────────────────────
@pytest.fixture()
def client(tmp_path: Path):
    from stopa.web.app import create_app

    app = create_app(db_dir=tmp_path, ws_heartbeat_s=0.3)
    with TestClient(app) as c:
        yield c


def _seed_web_case(tmp_path: Path, cid: str = "c1", critical: bool = True) -> str:
    """Seed přímo do case DB souboru, který očekává web vrstva ({cid}.db)."""
    db = CaseDB(tmp_path / f"{cid}.db")
    c = Case(id=cid, name="T")
    db.add_case(c)
    s = EvidenceSource(case_id=cid, kind="file", path="/evidence")
    db.add_source(s)
    fid = db.upsert_file(
        FileRecord(source_id=s.id, rel_path="doc.txt", name="doc.txt", size_bytes=10)
    )
    art = Artifact(source_id=s.id, file_id=fid, artifact_type="browser_history", title="Art")
    db.upsert_artifact(art)
    aid = db.list_artifacts(limit=10)[0].id
    if critical:
        db.add_finding(
            Finding(
                case_id=cid,
                kind="anomaly",
                provenance=[Provenance(parser_id="p", parser_version="1", file_id=fid)],
            )
        )
    return aid


class TestWebApi:
    def test_full_review_flow(self, client: TestClient, tmp_path: Path):
        aid = _seed_web_case(tmp_path)

        # GET artifacts — review_state draft
        r = client.get("/api/cases/c1/artifacts")
        assert r.status_code == 200
        arts = r.json()
        assert len(arts) == 1 and arts[0]["review_state"] == "draft"

        # postupné přechody A→B→C (kritický artefakt — kvorum na schválení)
        for reviewer, state in [("A", "reviewed"), ("B", "approved"), ("C", "court_ready")]:
            r = client.post(
                f"/api/cases/c1/artifacts/{aid}/review",
                json={"state": state, "reviewer": reviewer, "note": "ok"},
            )
            assert r.status_code == 201, r.text
            assert r.json()["review_state"] == state

        # historie + kritičnost
        r = client.get(f"/api/cases/c1/artifacts/{aid}/reviews")
        assert r.status_code == 200
        body = r.json()
        assert body["critical"] is True
        assert body["review_state"] == "court_ready"
        assert [x["reviewer"] for x in body["reviews"]] == ["A", "B", "C"]

    def test_skip_transition_409(self, client: TestClient, tmp_path: Path):
        aid = _seed_web_case(tmp_path)
        r = client.post(
            f"/api/cases/c1/artifacts/{aid}/review",
            json={"state": "approved", "reviewer": "A"},
        )
        assert r.status_code == 409

    def test_single_examiner_quorum_409(self, client: TestClient, tmp_path: Path):
        aid = _seed_web_case(tmp_path, critical=True)
        assert (
            client.post(
                f"/api/cases/c1/artifacts/{aid}/review",
                json={"state": "reviewed", "reviewer": "A"},
            ).status_code
            == 201
        )
        r = client.post(
            f"/api/cases/c1/artifacts/{aid}/review",
            json={"state": "approved", "reviewer": "A"},
        )
        assert r.status_code == 409

    def test_unknown_artifact_404(self, client: TestClient, tmp_path: Path):
        _seed_web_case(tmp_path)
        r = client.post(
            "/api/cases/c1/artifacts/art_neexistuje/review",
            json={"state": "reviewed", "reviewer": "A"},
        )
        assert r.status_code == 404

    def test_reviewer_required_422(self, client: TestClient, tmp_path: Path):
        aid = _seed_web_case(tmp_path)
        r = client.post(
            f"/api/cases/c1/artifacts/{aid}/review",
            json={"state": "reviewed", "reviewer": ""},
        )
        assert r.status_code == 422

    def test_live_ws_review_state_event(self, client: TestClient, tmp_path: Path):
        """F4.2×F4.3 — review přechod letí live přes WS (typ review.state)."""
        aid = _seed_web_case(tmp_path)
        with client.websocket_connect("/api/cases/c1/ws") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello"

            def post_review():
                # vlastní TestClient na stejnou app instanci → sdílený LiveEventBus
                c2 = TestClient(client.app)
                with c2:
                    r = c2.post(
                        f"/api/cases/c1/artifacts/{aid}/review",
                        json={"state": "reviewed", "reviewer": "A"},
                    )
                    assert r.status_code == 201, r.text

            t = threading.Thread(target=post_review)
            t.start()
            ev = ws.receive_json()
            t.join(timeout=15)

        assert ev["type"] == "review.state"
        assert ev["artifact_id"] == aid
        assert ev["review_state"] == "reviewed"


# ── Report filtr (court-ready only při aktivním workflow) ─────────────────────
def _seed_two_artifacts(tmp_path: Path, cid: str = "c1") -> tuple[str, str]:
    """Dva artefakty + timeline události pro oba; první je kritický."""
    db = CaseDB(tmp_path / f"{cid}.db")
    c = Case(id=cid, name="T")
    db.add_case(c)
    s = EvidenceSource(case_id=cid, kind="file", path="/evidence")
    db.add_source(s)
    aids: list[str] = []
    for i, (rel, crit) in enumerate([("a.txt", True), ("b.txt", False)]):
        fid = db.upsert_file(
            FileRecord(source_id=s.id, rel_path=rel, name=f"{i}.txt", size_bytes=i + 1)
        )
        art = Artifact(
            source_id=s.id, file_id=fid, artifact_type="browser_history", title=f"Art{i}", rel_path=rel
        )
        db.upsert_artifact(art)
        aid = next(a for a in db.list_artifacts(limit=20) if a.file_id == fid).id
        aids.append(aid)
        if crit:
            db.add_finding(
                Finding(
                    case_id=cid,
                    kind="anomaly",
                    provenance=[Provenance(parser_id="p", parser_version="1", file_id=fid)],
                )
            )
        db.add_timeline_event(
            source_id=s.id, ts_utc=T0, event_type="browser_history",
            artifact_id=aid, title=f"EV-{i}", rel_path=rel,
        )
    # timeline inserty nesou vlastní commit (v produkci ho dělá pipeline ve špartě)
    db.conn.commit()
    db.close()
    return aids[0], aids[1]


class TestReportFilter:
    def test_workflow_inactive_all_events(self, tmp_path: Path):
        """Bez review akcí report obsahuje vše (backward compat)."""
        _a, _b = _seed_two_artifacts(tmp_path)
        db = CaseDB(tmp_path / "c1.db")
        data = build_report_data(db, "c1")
        titles = {e.title for e in data.timeline_events}
        assert titles == {"EV-0", "EV-1"}
        db.close()

    def test_workflow_active_only_court_ready(self, tmp_path: Path):
        """Workflow běží → report jen události od court-ready artefaktů."""
        a, _b = _seed_two_artifacts(tmp_path)
        db = CaseDB(tmp_path / "c1.db")
        # kritický (a) projde celým workflow s 3 distinct examinátory
        for reviewer, state in [("A", "reviewed"), ("B", "approved"), ("C", "court_ready")]:
            db.artifact_repo.set_review_state(a, state, reviewer)
        # nekritický (b) zůstane draft → jeho událost vynechá report

        data = build_report_data(db, "c1")
        titles = {e.title for e in data.timeline_events}
        assert titles == {"EV-0"}
        db.close()
