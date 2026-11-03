"""STP-018 Timeline Intelligence 2.0 — rozpory, duplikáty napříč zdroji, provenience.

Pokrytí:
- čistá logika ``domain/timeline_intel.py`` (bez IO):
  - find_contradictions: souběžná aktivita subjektu (okno, typ/soubor, tranzitivní uzavření)
  - find_cross_source_duplicates: stejný obsah z více zdrojů + provenance
  - classify_precision / provenance_summary: source vs derived + přesnost
  - analyze_timeline: per-event mapy pro DB materializaci
- DB vrstva: add/list roundtrip (ts_origin, subject_values), set/clear intel skupin
  (idempotence, merge flagů, E2 flagy nedotčené)
- migrace staré case DB (schéma ≤ v11 → sloupce STP-018 + zachování dat)
- pipeline post-pass ``run_timeline_intel``: souhrn + materializace + idempotence
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.data.db import SCHEMA_VERSION, CaseDB
from stopa.domain.timeline_intel import (
    DEFAULT_CONTRADICTION_WINDOW_SECONDS,
    FLAG_CONCURRENT_ACTIVITY,
    FLAG_CROSS_SOURCE_DUP,
    PRECISION_FILE_METADATA,
    PRECISION_MICROSECOND,
    PRECISION_MILLISECOND,
    PRECISION_SECOND,
    PRECISION_UNKNOWN,
    TS_ORIGIN_DERIVED,
    analyze_timeline,
    classify_precision,
    find_contradictions,
    find_cross_source_duplicates,
    normalize_title,
    provenance_summary,
)
from stopa.models import Case, EvidenceSource

# ── fixtures / helpers ─────────────────────────────────────────


def _ev(
    eid: str,
    ts: str,
    etype: str = "browser_history",
    title: str | None = None,
    source_id: str = "s1",
    rel_path: str = "/a.db",
    subjects: tuple[str, ...] = (),
    origin: str = "source",
) -> dict:
    """Syntetický timeline řádek ve tvaru výstupu ``db.list_timeline_events()``."""
    return {
        "id": eid,
        "ts_utc": ts,
        "event_type": etype,
        "title": title,
        "source_id": source_id,
        "rel_path": rel_path,
        "subject_values": list(subjects),
        "ts_origin": origin,
    }


@pytest.fixture
def db(tmp_path: Path) -> CaseDB:
    d = CaseDB(tmp_path / "case.db")
    yield d
    d.close()


# ── 1. Rozpory (concurrent_activity) — čistá logika ───────────


class TestFindContradictions:
    def test_same_subject_different_type_in_window(self):
        """Stejný subjekt, odlišný typ události v okně → rozpor."""
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00", etype="browser_history", subjects=("tel:+420123456789",)),
            _ev("e2", "2024-01-15T10:00:30+00:00", etype="chat_message", subjects=("tel:+420123456789",)),
        ]
        groups = find_contradictions(events)
        assert len(groups) == 1
        g = groups[0]
        assert [e["id"] for e in g.events] == ["e1", "e2"]
        assert g.subject == "tel:+420123456789"
        assert g.group_id.startswith("tci-")

    def test_same_subject_different_file_in_window(self):
        """Stejný subjekt, stejný typ, ale odlišný soubor → rozpor."""
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00", rel_path="/a.db", subjects=("host:pc-x",)),
            _ev("e2", "2024-01-15T10:00:45+00:00", rel_path="/b.db", subjects=("host:pc-x",)),
        ]
        groups = find_contradictions(events)
        assert len(groups) == 1

    def test_same_type_same_file_is_legit(self):
        """Stejný typ ze stejného souboru v okně → legitimní opakovaná aktivita."""
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00", subjects=("email:a@b.cz",)),
            _ev("e2", "2024-01-15T10:00:20+00:00", subjects=("email:a@b.cz",)),
        ]
        assert find_contradictions(events) == ()

    def test_outside_window_no_contradiction(self):
        """Δt > okno (60 s) → bez rozporu."""
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00", etype="browser_history", subjects=("tel:+420111",)),
            _ev("e2", "2024-01-15T10:01:30+00:00", etype="chat_message", subjects=("tel:+420111",)),
        ]
        assert find_contradictions(events) == ()

    def test_custom_window(self):
        """Vlastní okno 120 s zachytí Δt=90 s."""
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00", etype="browser_history", subjects=("tel:+420222",)),
            _ev("e2", "2024-01-15T10:01:30+00:00", etype="chat_message", subjects=("tel:+420222",)),
        ]
        assert find_contradictions(events) == ()
        groups = find_contradictions(events, window_seconds=120.0)
        assert len(groups) == 1

    def test_transitive_closure(self):
        """A–B (typ) a B–C (soubor) → jedna skupina tří událostí."""
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00", etype="browser_history", rel_path="/a.db", subjects=("tel:+420333",)),
            _ev("e2", "2024-01-15T10:00:10+00:00", etype="chat_message", rel_path="/a.db", subjects=("tel:+420333", "host:pc-y")),
            _ev("e3", "2024-01-15T10:00:20+00:00", etype="chat_message", rel_path="/b.db", subjects=("host:pc-y",)),
        ]
        groups = find_contradictions(events)
        assert len(groups) == 1
        assert [e["id"] for e in groups[0].events] == ["e1", "e2", "e3"]

    def test_no_subjects_no_contradiction(self):
        """Události bez subjektů se porovnávat nedají."""
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00", etype="a"),
            _ev("e2", "2024-01-15T10:00:05+00:00", etype="b"),
        ]
        assert find_contradictions(events) == ()

    def test_empty_and_single(self):
        assert find_contradictions([]) == ()
        assert find_contradictions([_ev("e1", "2024-01-15T10:00:00+00:00")]) == ()

    def test_deterministic_group_id_and_order(self):
        """Stejné vstupní události → stejné group ID i pořadí (reprodukovatelnost)."""
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00", etype="a", subjects=("tel:+420444",)),
            _ev("e2", "2024-01-15T10:00:10+00:00", etype="b", subjects=("tel:+420444",)),
            _ev("e3", "2024-01-15T10:00:20+00:00", etype="c", subjects=("tel:+420444",)),
        ]
        g1 = find_contradictions(events)
        g2 = find_contradictions(list(reversed(events)))  # jiný pořadový vstup, stejná množina
        assert len(g1) == 1 and len(g2) == 1
        assert g1[0].group_id == g2[0].group_id

    def test_default_window_constant(self):
        assert DEFAULT_CONTRADICTION_WINDOW_SECONDS == 60.0


# ── 2. Duplikáty napříč zdroji — čistá logika ──────────────────


class TestCrossSourceDuplicates:
    def test_same_content_two_sources(self):
        """Stejný typ+title z dvou různých souborů → duplikát s provenance."""
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00", title="Stránka A", source_id="s1", rel_path="/a.db"),
            _ev("e2", "2024-01-15T10:05:00+00:00", title="Stránka A", source_id="s2", rel_path="/b.db"),
        ]
        groups = find_cross_source_duplicates(events)
        assert len(groups) == 1
        g = groups[0]
        assert [e["id"] for e in g.events] == ["e1", "e2"]
        assert g.group_id.startswith("dup-")

    def test_same_content_two_files_one_source(self):
        """Stejný obsah z dvou souborů téhož zdroje → také duplikát (různé rel_path)."""
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00", title="Zpráva X", source_id="s1", rel_path="/a.db"),
            _ev("e2", "2024-01-15T10:06:00+00:00", title="Zpráva X", source_id="s1", rel_path="/b.db"),
        ]
        assert len(find_cross_source_duplicates(events)) == 1

    def test_same_file_repeat_is_legit(self):
        """Opakovaná návštěva stejné URL ve stejném souboru → neoznačuje se."""
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00", title="https://example.com"),
            _ev("e2", "2024-01-15T11:30:00+00:00", title="https://example.com"),
        ]
        assert find_cross_source_duplicates(events) == ()

    def test_different_titles_no_dup(self):
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00", title="A", source_id="s1", rel_path="/a.db"),
            _ev("e2", "2024-01-15T10:00:00+00:00", title="B", source_id="s2", rel_path="/b.db"),
        ]
        assert find_cross_source_duplicates(events) == ()

    def test_title_normalization(self):
        """Rozdílné mezery/písmena → stejný normalizovaný obsah."""
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00", title="Hello   World", source_id="s1", rel_path="/a.db"),
            _ev("e2", "2024-01-15T10:00:00+00:00", title="hello world", source_id="s2", rel_path="/b.db"),
        ]
        groups = find_cross_source_duplicates(events)
        assert len(groups) == 1
        assert groups[0].title_norm == "hello world"

    def test_empty_title_skipped(self):
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00", title=None, source_id="s1", rel_path="/a.db"),
            _ev("e2", "2024-01-15T10:00:00+00:00", title="", source_id="s2", rel_path="/b.db"),
        ]
        assert find_cross_source_duplicates(events) == ()

    def test_deterministic_group_id(self):
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00", title="Dup", source_id="s1", rel_path="/a.db"),
            _ev("e2", "2024-01-15T10:00:00+00:00", title="Dup", source_id="s2", rel_path="/b.db"),
        ]
        g1 = find_cross_source_duplicates(events)
        g2 = find_cross_source_duplicates(list(reversed(events)))
        assert g1[0].group_id == g2[0].group_id

    def test_normalize_title_helper(self):
        assert normalize_title("  A   B ") == "a b"
        assert normalize_title(None) == ""
        assert normalize_title("") == ""


# ── 3. Provenience timestampů — čistá logika ───────────────────


class TestProvenance:
    def test_classify_precision_source(self):
        base = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        assert classify_precision(base) == PRECISION_SECOND
        assert classify_precision(base.replace(microsecond=500_000)) == PRECISION_MILLISECOND
        assert classify_precision(base.replace(microsecond=123_456)) == PRECISION_MICROSECOND

    def test_classify_precision_derived(self):
        base = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        assert classify_precision(base, TS_ORIGIN_DERIVED) == PRECISION_FILE_METADATA
        # derived má vždy přesnost souborového systému — µs komponenta se nebere v úvahu
        assert classify_precision(base.replace(microsecond=123_456), TS_ORIGIN_DERIVED) == PRECISION_FILE_METADATA

    def test_classify_precision_none(self):
        assert classify_precision(None) == PRECISION_UNKNOWN

    def test_provenance_summary_counts(self):
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00"),  # source, second
            _ev("e2", "2024-01-15T10:00:00.500000+00:00"),  # source, millisecond
            _ev("e3", "2024-01-15T10:00:00.123456+00:00"),  # source, microsecond
            _ev("e4", "2024-01-15T10:00:00+00:00", origin="derived"),  # derived → file_metadata
        ]
        s = provenance_summary(events)
        assert s["total"] == 4
        assert s["origin_source"] == 3
        assert s["origin_derived"] == 1
        assert s["precision_second"] == 1
        assert s["precision_millisecond"] == 1
        assert s["precision_microsecond"] == 1
        assert s["precision_file_metadata"] == 1
        assert s["precision_unknown"] == 0

    def test_provenance_summary_empty(self):
        s = provenance_summary([])
        assert s["total"] == 0


# ── 4. analyze_timeline — per-event mapy ───────────────────────


class TestAnalyzeTimeline:
    def test_combined_scenario_maps(self):
        """Rozpor + duplikát najednou; event může být v obou skupinách."""
        # stejný typ+title z dvou souborů → duplikát; stejný subjekt + odlišný soubor v okně → rozpor
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00", etype="browser_history", title="Stránka A",
                source_id="s1", rel_path="/a.db", subjects=("tel:+420555",)),
            _ev("e2", "2024-01-15T10:00:30+00:00", etype="browser_history", title="Stránka A",
                source_id="s2", rel_path="/b.db", subjects=("tel:+420555",)),
        ]
        result = analyze_timeline(events)
        assert len(result.contradictions) == 1
        assert len(result.dup_groups) == 1
        # obě události jsou v rozporu I v duplikátu
        assert set(result.event_contradiction_groups) == {"e1", "e2"}
        assert set(result.event_dup_groups) == {"e1", "e2"}
        assert result.event_contradiction_groups["e1"] == result.contradictions[0].group_id
        assert result.event_dup_groups["e1"] == result.dup_groups[0].group_id

    def test_clean_timeline_empty_result(self):
        events = [
            _ev("e1", "2024-01-15T10:00:00+00:00"),
            _ev("e2", "2024-01-15T12:00:00+00:00", title="Jiné"),
        ]
        result = analyze_timeline(events)
        assert result.contradictions == ()
        assert result.dup_groups == ()
        assert result.event_contradiction_groups == {}
        assert result.event_dup_groups == {}


# ── 5. DB vrstva — roundtrip + skupiny ─────────────────────────


class TestTimelineIntelDB:
    def _case_and_source(self, db: CaseDB) -> tuple[str, str]:
        c = Case(name="TL intel test")
        db.add_case(c)
        s = EvidenceSource(case_id=c.id, kind="folder", path="/tmp/ev")
        db.add_source(s)
        return c.id, s.id

    def test_add_list_roundtrip_stp018_fields(self, db: CaseDB):
        """ts_origin + subject_values projdou add → list."""
        _, sid = self._case_and_source(db)
        ts = datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        eid = db.add_timeline_event(
            source_id=sid,
            ts_utc=ts,
            event_type="chat_message",
            title="Zpráva",
            ts_origin="derived",
            subject_values=("tel:+420123456789", "host:pc-z"),
        )
        rows = db.list_timeline_events(source_id=sid)
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == eid
        assert row["ts_origin"] == "derived"
        assert row["subject_values"] == ["tel:+420123456789", "host:pc-z"]
        assert row["contradiction_group_id"] is None
        assert row["dup_group_id"] is None

    def test_add_default_ts_origin_source(self, db: CaseDB):
        """Bez explicitního ts_origin → default 'source' (staré parsery se nemění)."""
        _, sid = self._case_and_source(db)
        ts = datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        db.add_timeline_event(source_id=sid, ts_utc=ts, event_type="x", title="t")
        row = db.list_timeline_events()[0]
        assert row["ts_origin"] == "source"
        assert row["subject_values"] == []

    def test_set_groups_merges_flags_and_is_idempotent(self, db: CaseDB):
        """set_timeline_intel_groups: group ID + merge flagů; re-run = stejný výsledek."""
        _, sid = self._case_and_source(db)
        ts = datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        e1 = db.add_timeline_event(source_id=sid, ts_utc=ts, event_type="a", title="t")
        e2 = db.add_timeline_event(
            source_id=sid, ts_utc=ts.replace(second=30), event_type="b", title="t"
        )

        n1 = db.set_timeline_intel_groups({e1: "g-c1", e2: "g-c1"}, {e1: "g-d1"})
        assert n1 == 3  # 2 rozporové + 1 duplikátní UPDATE

        rows = {r["id"]: r for r in db.list_timeline_events()}
        assert rows[e1]["contradiction_group_id"] == "g-c1"
        assert rows[e2]["contradiction_group_id"] == "g-c1"
        assert rows[e1]["dup_group_id"] == "g-d1"
        assert rows[e2]["dup_group_id"] is None
        # kanonické flagy se merge do anomaly_flags
        assert FLAG_CONCURRENT_ACTIVITY in rows[e1]["anomaly_flags"]
        assert FLAG_CROSS_SOURCE_DUP in rows[e1]["anomaly_flags"]
        assert FLAG_CONCURRENT_ACTIVITY in rows[e2]["anomaly_flags"]

        # idempotence: stejný re-run → žádné duplicitní flagy, stejné ID
        n2 = db.set_timeline_intel_groups({e1: "g-c1", e2: "g-c1"}, {e1: "g-d1"})
        assert n2 == 3
        rows = {r["id"]: r for r in db.list_timeline_events()}
        assert rows[e1]["anomaly_flags"].count(FLAG_CONCURRENT_ACTIVITY) == 1
        assert rows[e1]["anomaly_flags"].count(FLAG_CROSS_SOURCE_DUP) == 1

    def test_clear_keeps_e2_flags(self, db: CaseDB):
        """clear_timeline_intel_groups odstraní jen STP-018 flagy; E2 zůstávají."""
        _, sid = self._case_and_source(db)
        ts = datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        e1 = db.add_timeline_event(
            source_id=sid, ts_utc=ts, event_type="a", title="t", anomaly_flags=("duplicate",)
        )
        db.set_timeline_intel_groups({e1: "g-c1"}, {})

        db.clear_timeline_intel_groups()
        row = {r["id"]: r for r in db.list_timeline_events()}[e1]
        assert row["contradiction_group_id"] is None
        assert row["dup_group_id"] is None
        # E2 flag zůstal, STP-018 flag odešel
        assert "duplicate" in row["anomaly_flags"]
        assert FLAG_CONCURRENT_ACTIVITY not in row["anomaly_flags"]


# ── 6. Migrace staré case DB (schéma ≤ v11) ────────────────────


class TestMigrationStp018:
    def test_old_db_gets_stp018_columns_and_keeps_data(self, tmp_path: Path):
        """Stará DB bez STP-018 sloupců se po open migruje; data zůstávají."""
        p = tmp_path / "old.db"
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE cases (id TEXT PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE sources (id TEXT PRIMARY KEY, case_id TEXT)")
        # starý tvar timeline_events (schéma v11 — bez STP-018 sloupců)
        conn.execute(
            "CREATE TABLE timeline_events ("
            " id TEXT PRIMARY KEY,"
            " source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,"
            " artifact_id TEXT, file_id TEXT, rel_path TEXT,"
            " event_type TEXT NOT NULL, ts_utc TEXT NOT NULL, title TEXT,"
            " confidence REAL, parser_version TEXT, extracted_at TEXT, anomaly_flags TEXT)"
        )
        conn.execute("INSERT INTO sources VALUES ('src-old', 'case-1')")
        conn.execute(
            "INSERT INTO timeline_events (id, source_id, event_type, ts_utc, title)"
            " VALUES ('tl-old1', 'src-old', 'browser_history',"
            " '2024-01-15T10:00:00+00:00', 'Stará událost')"
        )
        conn.commit()
        conn.close()

        d = CaseDB(p)
        try:
            assert d.schema_version() == SCHEMA_VERSION
            cols = {r["name"] for r in d.conn.execute("PRAGMA table_info(timeline_events)").fetchall()}
            for col in ("ts_origin", "subject_values_json", "contradiction_group_id", "dup_group_id"):
                assert col in cols, f"chybí sloupec {col}"

            # data zachována + defaulty
            rows = d.list_timeline_events()
            assert len(rows) == 1
            row = rows[0]
            assert row["id"] == "tl-old1"
            assert row["title"] == "Stará událost"
            assert row["ts_origin"] == "source"  # staré timestampy jsou vždy z obsahu
            assert row["subject_values"] == []
            assert row["contradiction_group_id"] is None
            assert row["dup_group_id"] is None
        finally:
            d.close()


# ── 7. Pipeline post-pass run_timeline_intel ───────────────────


class TestRunTimelineIntel:
    def _case_and_sources(self, db: CaseDB) -> tuple[str, str, str]:
        c = Case(name="TL intel pipeline")
        db.add_case(c)
        s1 = EvidenceSource(case_id=c.id, kind="folder", path="/tmp/ev1")
        s2 = EvidenceSource(case_id=c.id, kind="folder", path="/tmp/ev2")
        db.add_source(s1)
        db.add_source(s2)
        return c.id, s1.id, s2.id

    def test_postpass_materializes_and_is_idempotent(self, db: CaseDB):
        """Post-pass nad celou case DB: souhrn + materializace; re-run = stejný výsledek."""
        from stopa.pipeline import run_timeline_intel

        _, s1, s2 = self._case_and_sources(db)
        ts = datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        # rozpor: stejný subjekt + odlišný soubor v okně; duplikát: stejný typ+title z dvou souborů
        db.add_timeline_event(
            source_id=s1, ts_utc=ts, event_type="browser_history", title="Stránka A",
            rel_path="/a.db", subject_values=("tel:+420777",),
        )
        db.add_timeline_event(
            source_id=s2, ts_utc=ts.replace(second=30), event_type="browser_history", title="Stránka A",
            rel_path="/b.db", subject_values=("tel:+420777",),
        )

        summary = run_timeline_intel(db)
        assert summary["events"] == 2
        assert summary["contradiction_groups"] == 1
        assert summary["dup_groups"] == 1  # stejný obsah z dvou souborů
        assert summary["updated_rows"] == 4  # 2× rozpor + 2× duplikát

        rows = db.list_timeline_events()
        assert all(r["contradiction_group_id"] for r in rows)
        assert all(r["dup_group_id"] for r in rows)
        gids_c = {r["contradiction_group_id"] for r in rows}
        gids_d = {r["dup_group_id"] for r in rows}
        assert len(gids_c) == 1 and len(gids_d) == 1

        # idempotence: re-run → stejná group ID, žádné duplicitní flagy
        summary2 = run_timeline_intel(db)
        assert summary2 == summary
        rows2 = db.list_timeline_events()
        for r in rows2:
            assert r["anomaly_flags"].count(FLAG_CONCURRENT_ACTIVITY) == 1
            assert r["anomaly_flags"].count(FLAG_CROSS_SOURCE_DUP) == 1

    def test_postpass_empty_db(self, db: CaseDB):
        """Prázdná timeline → nulový souhrn, bez chyb."""
        from stopa.pipeline import run_timeline_intel

        self._case_and_sources(db)
        summary = run_timeline_intel(db)
        assert summary == {
            "events": 0,
            "contradiction_groups": 0,
            "dup_groups": 0,
            "updated_rows": 0,
        }
