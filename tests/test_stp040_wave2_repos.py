"""ETAPA C vlna 2 (STP-040) — rozdělení monolitu ``db.py`` na doménová repozitáře.

Ověřuje, že extrakce ``ArtifactRepository`` / ``EntityRepository`` je
**behaviorálně ekvivalentní** původnímu monolitu:

- facade ``CaseDB`` drží pět repozitářů a sdílí s nimi jednu SQLite connection;
- volání přes facade (``upsert_artifact``, ``add_finding``, ``log_lineage``,
  ``record_operation``, ``add_timeline_event``, ``upsert_entities``,
  ``add_correlation``, …) skutečně projde příslušným repozitářem — data jsou
  čitelná zpět i přímo z repo na stejném spojení;
- repozitáře lze konstruovat nezávisle (tenká SQLite vrstva);
- klíčové behaviorální invarianty monolitu zůstávají: idempotentní upsert
  artifactu podle ``(source_id, artifact_type, rel_path)``, výměna artifactů
  souboru při re-ingestu, append-only lineage + dohledání řetězce.

Žádné nové business logiky — jen struktura + wiring.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from stopa.data.artifact_repository import ArtifactRepository
from stopa.data.db import CaseDB
from stopa.data.entity_repository import EntityRepository
from stopa.domain.evidence_model import Finding, Provenance
from stopa.models import Artifact, Case, EvidenceSource, FileRecord

CASE_ID = "case-w2"


@pytest.fixture
def case_db(tmp_path: Path) -> CaseDB:
    db = CaseDB(tmp_path / "wave2.db")
    # FK na cases — většina delegovaných metod vyžaduje existující případ.
    db.add_case(Case(id=CASE_ID, name="Vlna 2"))
    return db


def _artifact(art_type: str = "browser_history", rel_path: str | None = None) -> Artifact:
    return Artifact(
        artifact_type=art_type,
        title="test artifact",
        timestamp=datetime(2026, 1, 5, tzinfo=UTC),
        rel_path=rel_path,
        details={"url": "https://example.com"},
    )


@pytest.fixture
def src(case_db: CaseDB) -> EvidenceSource:
    """Důkazní zdroj pro artifacty (upsert_artifact vyžaduje source_id)."""
    s = EvidenceSource(case_id=CASE_ID, kind="folder", path="/tmp/evid")
    case_db.add_source(s)
    return s


def _finding(case_id: str = CASE_ID) -> Finding:
    return Finding(
        case_id=case_id,
        kind="anomaly",
        provenance=[Provenance(parser_id="test-parser", parser_version="1.0")],
        details_json={"note": "vlna 2"},
    )


# ── wiring: facade drží repozitáře na sdílené connection ────────────────
class TestWiring:
    def test_repos_present(self, case_db: CaseDB):
        assert isinstance(case_db.artifact_repo, ArtifactRepository)
        assert isinstance(case_db.entity_repo, EntityRepository)

    def test_shared_connection(self, case_db: CaseDB):
        """Všechna repozitáře sdílí jednu connection (jeden transactional kontext)."""
        assert case_db.artifact_repo.conn is case_db.conn
        assert case_db.entity_repo.conn is case_db.conn


# ── delegace přes facade → data čitelná zpět i přímo z repo ───────────────
class TestArtifactDelegation:
    def test_upsert_artifact_routes_to_artifact_repo(self, case_db: CaseDB, src: EvidenceSource):
        art = _artifact()
        art.source_id = src.id
        case_db.upsert_artifact(art)
        # facade čtení
        got = case_db.list_artifacts()
        assert len(got) == 1 and got[0].id == art.id
        # přímé čtení z repo (stejná data, stejné spojení)
        direct = ArtifactRepository(case_db.conn).get_artifact(art.id)
        assert direct is not None and direct.artifact_type == "browser_history"

    def test_upsert_artifact_idempotent_by_key(self, case_db: CaseDB):
        """Re-ingest se stejným (source_id, artifact_type, rel_path) → 1 řádek."""
        src = EvidenceSource(case_id=CASE_ID, kind="folder", path="/tmp/evid")
        case_db.add_source(src)
        a1 = _artifact(rel_path="a.html")
        a1.source_id = src.id
        case_db.upsert_artifact(a1)
        a2 = _artifact(rel_path="a.html")  # stejný klíč, jiná instance
        a2.source_id = src.id
        case_db.upsert_artifact(a2)
        arts = case_db.list_artifacts()
        assert len(arts) == 1
        assert arts[0].id != a1.id  # DELETE+INSERT → nový ID (chování monolitu)

    def test_replace_artifacts_for_file(self, case_db: CaseDB, src: EvidenceSource):
        rec = case_db.upsert_file(
            FileRecord(source_id=src.id, rel_path="x.db", name="x.db", size_bytes=10)
        )
        old = _artifact(rel_path="x.db")
        old.file_id = rec
        old.source_id = src.id
        case_db.upsert_artifact(old)
        new = _artifact(art_type="sqlite_database", rel_path="x.db")
        new.file_id = rec
        new.source_id = src.id
        n = case_db.replace_artifacts_for_file(rec, [new])
        assert n == 1
        arts = case_db.list_artifacts()
        assert len(arts) == 1 and arts[0].artifact_type == "sqlite_database"

    def test_add_finding_routes_to_artifact_repo(self, case_db: CaseDB):
        f = _finding()
        fid = case_db.add_finding(f)
        # facade čtení
        got = case_db.get_finding(fid)
        assert got is not None and got.kind == "anomaly"
        # přímé čtení z repo (stejná data)
        direct = ArtifactRepository(case_db.conn).get_finding(fid)
        assert direct is not None and direct.details_json == {"note": "vlna 2"}

    def test_log_lineage_routes_to_artifact_repo(self, case_db: CaseDB):
        ev_id = case_db.log_lineage(
            "extract", input_refs=["file:1"], output_refs=[f"artifact:{CASE_ID}"]
        )
        assert isinstance(ev_id, str) and ev_id.startswith("lin")
        # facade čtení
        events = case_db.list_lineage()
        assert len(events) == 1 and events[0].op_type == "extract"
        # přímé čtení z repo (stejná data)
        direct = ArtifactRepository(case_db.conn).list_lineage()
        assert [e.id for e in direct] == [ev_id]

    def test_get_lineage_chain(self, case_db: CaseDB):
        """Dohledání řetězce: zdroj → extract → ref (vzor build_chain)."""
        case_db.log_lineage("extract", input_refs=["file:1"], output_refs=["art:x"])
        chain = case_db.get_lineage_chain("art:x")
        assert len(chain) == 1 and "art:x" in chain[0].output_refs

    def test_record_operation_routes_to_artifact_repo(self, case_db: CaseDB):
        op_id = case_db.record_operation(
            "extract", stopa_version="test", parser_versions={"p": "1.0"}
        )
        assert isinstance(op_id, str) and op_id.startswith("op")
        # facade čtení
        ops = case_db.list_operations()
        assert len(ops) == 1 and ops[0].op_type == "extract"
        # přímé čtení z repo (stejná data)
        direct = ArtifactRepository(case_db.conn).get_operation(op_id)
        assert direct is not None and direct.parser_versions == {"p": "1.0"}

    def test_timeline_event_routes_to_artifact_repo(self, case_db: CaseDB):
        src = EvidenceSource(case_id=CASE_ID, kind="folder", path="/tmp/evid")
        case_db.add_source(src)
        ev_id = case_db.add_timeline_event(
            source_id=src.id,
            ts_utc=datetime(2026, 1, 5, tzinfo=UTC),
            event_type="browser_visit",
            title="example.com",
        )
        assert isinstance(ev_id, str) and ev_id.startswith("tl")
        # facade čtení
        events = case_db.list_timeline_events()
        assert len(events) == 1 and events[0]["event_type"] == "browser_visit"
        # přímé čtení z repo (stejná data)
        direct = ArtifactRepository(case_db.conn).list_timeline_events()
        assert [e["id"] for e in direct] == [ev_id]


# ── delegace entity/correlations → EntityRepository ───────────────────────
class TestEntityDelegation:
    def test_upsert_entities_routes_to_entity_repo(self, case_db: CaseDB):
        rows = [
            ("email", "a@b.c", "A <a@b.c>", "2026-01-05T00:00:00+00:00", None),
            ("phone", "+420123", "123 456 789", None, "2026-01-06T00:00:00+00:00"),
        ]
        n = case_db.upsert_entities(CASE_ID, rows)
        assert n == 2
        # facade čtení
        ents = case_db.list_entities(CASE_ID)
        assert len(ents) == 2 and {e["kind"] for e in ents} == {"email", "phone"}
        # přímé čtení z repo (stejná data)
        direct = EntityRepository(case_db.conn).list_entities(CASE_ID)
        assert len(direct) == 2
        assert {e["value"] for e in direct} == {"a@b.c", "+420123"}

    def test_upsert_entities_idempotent(self, case_db: CaseDB):
        """Re-run s touž hodnotou → agregace first/last_seen, ne duplicita."""
        rows = [("email", "a@b.c", None, "2026-01-05T00:00:00+00:00", "2026-01-05T00:00:00+00:00")]
        case_db.upsert_entities(CASE_ID, rows)
        case_db.upsert_entities(
            CASE_ID, [("email", "a@b.c", None, "2026-01-04T00:00:00+00:00", "2026-01-07T00:00:00+00:00")]
        )
        ents = case_db.list_entities(CASE_ID)
        assert len(ents) == 1
        assert ents[0]["first_seen"] == "2026-01-04T00:00:00+00:00"
        assert ents[0]["last_seen"] == "2026-01-07T00:00:00+00:00"

    def test_correlations_route_to_entity_repo(self, case_db: CaseDB):
        cid = case_db.add_correlation(
            CASE_ID, "a@b.c", "+420123", "same_contact", "confirmed", [{"type": "co_occurrence"}]
        )
        assert isinstance(cid, int) and cid > 0
        # facade čtení
        cors = case_db.list_correlations(CASE_ID)
        assert len(cors) == 1 and cors[0]["relation"] == "same_contact"
        # přímé čtení z repo (stejná data)
        direct = EntityRepository(case_db.conn).list_correlations(CASE_ID)
        assert [c["id"] for c in direct] == [cid]

    def test_clear_correlations(self, case_db: CaseDB):
        case_db.add_correlation(CASE_ID, "a", "b", "hash_match", "possible", [])
        n = case_db.clear_correlations(CASE_ID)
        assert n == 1 and case_db.list_correlations(CASE_ID) == []


# ── repozitáře jako nezávislé tenké vrstvy (stejné spojení) ───────────────
class TestIndependentRepos:
    def test_artifact_repo_standalone(self, case_db: CaseDB, src: EvidenceSource):
        repo = ArtifactRepository(case_db.conn)
        art = _artifact()
        art.source_id = src.id
        repo.upsert_artifact(art)
        assert repo.get_artifact(art.id).title == "test artifact"

    def test_entity_repo_standalone(self, case_db: CaseDB):
        repo = EntityRepository(case_db.conn)
        n = repo.upsert_entities(CASE_ID, [("hash", "ab12cd34", None, None, None)])
        assert n == 1 and len(repo.list_entities(CASE_ID)) == 1


# ── sanity: connection je sqlite3.Connection (typová kontrola) ────────────
def test_conn_type(case_db: CaseDB):
    assert isinstance(case_db.conn, sqlite3.Connection)
