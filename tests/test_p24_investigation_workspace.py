"""P2-4 Investigation Workspace — domain unit tests + repository integrace (Wave 1).

Pokrytí návrhu (docs/P2_DESIGNS.md §P2-4):
- poznámky ukotvené na artefakt / entity / timeline event (validace + existence),
- úkoly se stavovým automatem open → in_progress → done,
- revize hypotéz jako append-only hash chain — tamper detekce bez LLM.

Offline a deterministické: čistá doménová vrstva bez I/O; repozitář na dočasné DB.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from stopa.data.db import SCHEMA_VERSION, CaseDB
from stopa.data.investigation_repository import InvestigationRepository
from stopa.domain.investigation_workspace import (
    GENESIS_HASH,
    compute_revision_hash,
    next_revision,
    revision_payload,
    validate_note,
    validate_task,
    verify_revisions,
)

CASE_ID = "p24-case"


# ── fixture: case DB s minimálními referencemi ───────────────────────────────


@pytest.fixture()
def db(tmp_path: Path):
    d = CaseDB(tmp_path / f"{CASE_ID}.db")
    now = "2026-11-18T12:00:00+00:00"
    c = d.conn
    c.execute("INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)", (CASE_ID, "P2-4", now))
    c.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES ('s1', ?, 'file', '/tmp/p24', ?)",
        (CASE_ID, now),
    )
    c.execute(
        "INSERT INTO artifacts (id, source_id, artifact_type, title)"
        " VALUES ('art-1', 's1', 'browser_history', 'history')"
    )
    c.execute(
        "INSERT INTO entities (id, case_id, kind, value_normalized)"
        " VALUES ('ent-1', ?, 'email', 'x@y.cz')",
        (CASE_ID,),
    )
    c.execute(
        "INSERT INTO timeline_events (id, source_id, event_type, ts_utc)"
        " VALUES ('evt-1', 's1', 'browser_history', '2026-01-05T10:00:00+00:00')"
    )
    c.execute(
        "INSERT INTO hypotheses (id, case_id, claim, created_at, updated_at)"
        " VALUES ('hyp-1', ?, 'Uživatel byl online v 10:00', ?, ?)",
        (CASE_ID, now, now),
    )
    c.commit()
    yield d
    d.close()


@pytest.fixture()
def repo(db) -> InvestigationRepository:
    return InvestigationRepository(db.conn)


# ── domain: validace poznámek ────────────────────────────────────────────────


class TestNoteValidation:
    def test_valid_normalizes(self):
        assert validate_note("artifact", "  a1 ", "text") == ("artifact", "a1", "text")

    def test_kind_not_str_typeerror(self):
        with pytest.raises(TypeError, match="ref_kind"):
            validate_note(42, "x", "y")  # type: ignore[arg-type]

    def test_unknown_kind_valueerror(self):
        with pytest.raises(ValueError, match="neplatný druh ukotvení"):
            validate_note("file", "x", "y")

    def test_empty_ref_id_valueerror(self):
        with pytest.raises(ValueError, match="prázdné ID"):
            validate_note("artifact", "   ", "y")

    def test_empty_text_valueerror(self):
        with pytest.raises(ValueError, match="bez textu"):
            validate_note("artifact", "a1", "")


# ── domain: validace úkolů ───────────────────────────────────────────────────


class TestTaskValidation:
    def test_defaults_open(self):
        assert validate_task("review") == ("review", "open", None, None)

    def test_bad_status_valueerror(self):
        with pytest.raises(ValueError, match="neplatný stav"):
            validate_task("t", status="closed")

    def test_due_iso_parsed(self):
        _, _, _, parsed = validate_task("t", due="2026-12-31T23:59:59")
        assert isinstance(parsed, datetime) and parsed.year == 2026

    def test_due_not_iso_valueerror(self):
        with pytest.raises(ValueError, match="neplatné datum"):
            validate_task("t", due="v pátek")

    def test_assignee_type_error(self):
        with pytest.raises(TypeError, match="assignee"):
            validate_task("t", assignee=5)  # type: ignore[arg-type]


# ── domain: hash chain revizí hypotéz ────────────────────────────────────────


def _build_chain(n: int, hypothesis_id: str = "hyp-1") -> list[dict]:
    rows: list[dict] = []
    for i in range(n):
        rows.append(next_revision(hypothesis_id, f"claim {i}", author="znalec", existing=rows))
    return rows


class TestRevisionChain:
    def test_first_revision_is_genesis(self):
        r0 = next_revision("hyp-1", "claim 0", author="znalec")
        assert r0["seq"] == 1 and r0["prev_hash"] == GENESIS_HASH
        expected = compute_revision_hash(GENESIS_HASH, revision_payload("claim 0", "znalec"))
        assert r0["hash"] == expected

    def test_chain_links_and_seq(self):
        rows = _build_chain(3)
        for i in range(1, len(rows)):
            assert rows[i]["prev_hash"] == rows[i - 1]["hash"]
        assert [r["seq"] for r in rows] == [1, 2, 3]

    def test_verify_clean_returns_none(self):
        assert verify_revisions(_build_chain(4)) is None

    def test_tampered_content_detected_at_index(self):
        rows = _build_chain(3)
        tampered = json.loads(rows[1]["content_json"])
        tampered["claim"] = "upraveno"
        rows[1] = {**rows[1], "content_json": json.dumps(tampered)}
        assert verify_revisions(rows) == 1

    def test_missing_first_revision_detected(self):
        rows = _build_chain(3)[1:]
        # první zbývající revize už neukončuje GENESIS → porušení na indexu 0
        assert verify_revisions(rows) == 0

    def test_hash_deterministic_and_author_sensitive(self):
        a = compute_revision_hash("GENESIS", revision_payload("c", None))
        b = compute_revision_hash("GENESIS", revision_payload("c", None))
        c_ = compute_revision_hash("GENESIS", revision_payload("c", "znalec"))
        assert a == b and a != c_

    def test_empty_claim_valueerror(self):
        with pytest.raises(ValueError, match="bez obsahu"):
            next_revision("hyp-1", "   ")


# ── repository: poznámky ─────────────────────────────────────────────────────


class TestRepositoryNotes:
    def test_schema_version_is_23(self, db):
        assert SCHEMA_VERSION == 23 and db.schema_version() == SCHEMA_VERSION

    def test_note_on_artifact_roundtrip(self, repo):
        note_id = repo.add_note(CASE_ID, "artifact", "art-1", "poznamka na artefakt", "znalec")
        assert note_id >= 1
        notes = repo.list_notes(CASE_ID)
        assert len(notes) == 1 and notes[0]["ref_kind"] == "artifact"
        assert notes[0]["text"] == "poznamka na artefakt"

    def test_all_ref_kinds_accepted(self, repo):
        for kind, ref in (("entity", "ent-1"), ("timeline_event", "evt-1")):
            assert repo.add_note(CASE_ID, kind, ref, f"note {kind}") >= 1
        assert len(repo.list_notes(CASE_ID)) == 2

    def test_missing_ref_valueerror(self, repo):
        with pytest.raises(ValueError, match="neexistuje"):
            repo.add_note(CASE_ID, "artifact", "nope", "t")

    def test_bad_kind_propagates_domain_error(self, repo):
        with pytest.raises(ValueError, match="neplatný druh ukotvení"):
            repo.add_note(CASE_ID, "file", "x", "t")


# ── repository: úkoly ────────────────────────────────────────────────────────


class TestRepositoryTasks:
    def test_lifecycle_open_to_done(self, repo):
        task_id = repo.add_task(CASE_ID, "ověřit hash")
        assert repo.get_task(CASE_ID, task_id)["status"] == "open"
        updated = repo.set_task_status(CASE_ID, task_id, "in_progress")
        assert updated["status"] == "in_progress"
        done = repo.set_task_status(CASE_ID, task_id, "done")
        assert done["status"] == "done" and len(repo.list_tasks(CASE_ID)) == 1

    def test_invalid_status_valueerror(self, repo):
        task_id = repo.add_task(CASE_ID, "t")
        with pytest.raises(ValueError, match="neplatný stav"):
            repo.set_task_status(CASE_ID, task_id, "closed")

    def test_unknown_task_id_valueerror(self, repo):
        with pytest.raises(ValueError, match="neexistuje"):
            repo.set_task_status(CASE_ID, 999, "done")

    def test_due_stored_iso(self, repo):
        task_id = repo.add_task(CASE_ID, "t", due="2026-12-31T23:59:59")
        assert repo.get_task(CASE_ID, task_id)["due"] == "2026-12-31T23:59:59"


# ── repository: revize hypotéz (append-only chain v DB) ──────────────────────


class TestHypoRevisions:
    def test_append_only_chain_in_db(self, repo):
        for i in range(3):
            row = repo.add_hypo_revision(CASE_ID, "hyp-1", f"claim {i}", author="znalec")
            assert row["seq"] == i + 1
        rows = repo.list_hypo_revisions(CASE_ID, "hyp-1")
        assert [r["seq"] for r in rows] == [1, 2, 3]
        assert rows[0]["prev_hash"] == GENESIS_HASH
        assert verify_revisions(rows) is None

    def test_tampered_middle_row_detected(self, db, repo):
        for i in range(3):
            repo.add_hypo_revision(CASE_ID, "hyp-1", f"claim {i}")
        # znalý tamper: změna obsahu starší revize bez přepočtu hashu
        db.conn.execute(
            "UPDATE hypothesis_revisions SET content_json = ? WHERE seq = 2 AND case_id = ?",
            (json.dumps({"claim": "tamper", "author": None}), CASE_ID),
        )
        assert verify_revisions(repo.list_hypo_revisions(CASE_ID, "hyp-1")) == 1

    def test_missing_hypothesis_valueerror(self, repo):
        with pytest.raises(ValueError, match="neexistuje"):
            repo.add_hypo_revision(CASE_ID, "nope", "claim")

    def test_empty_claim_valueerror(self, repo):
        with pytest.raises(ValueError, match="bez obsahu"):
            repo.add_hypo_revision(CASE_ID, "hyp-1", "   ")
