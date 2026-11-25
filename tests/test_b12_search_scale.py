"""B12 — Práh přechodu FTS5 → dedikovaný search engine (prahy + klasifikace).

A. Čistá doména ``classify_search_workload`` — prahy/tier/postupy/semantika chyb
   (objem indexů files/artifacts + O(A·E) stěna relační expanze přes graph_edges).
B. Data vrstva ``search_workload()`` — read-only statistika ze zdrojových tabulek.
C. CLI ``case scale`` E2E — aditivní sekce ``search`` v JSON i lidském výstupu.

Offline a deterministické; konvence chyb: typová = TypeError (bool odmítnut),
semantická = ValueError (záporná hodnota). Viz PLAN_BACKLOG B12 (F-1..F-5).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from stopa.data.db import CaseDB
from stopa.domain.search_scale import (
    GRAPH_EDGES_ROWS,
    PROC_ENGINE_EVAL,
    PROC_REL_BATCHING,
    PROC_SEARCH_REBUILD,
    SEARCH_ARTIFACTS_ROWS,
    SEARCH_FILES_ROWS,
    TIER_ENGINE_CANDIDATE,
    TIER_FTS_OK,
    TIER_FTS_WATCH,
    classify_search_workload,
)
from stopa.models import Artifact, Case, EvidenceSource, FileRecord

CASE_ID = "case-b12"


# ── A. Čistá doména — prahy a klasifikace ───────────────────────────────────────


class TestClassifySearchWorkload:
    def test_empty_workload_is_fts_ok(self):
        profile = classify_search_workload(0, 0, 0)
        assert profile.tier == TIER_FTS_OK
        assert profile.procedures == ()

    def test_just_below_watch_ratio_is_fts_ok(self):
        # pod 1/10 prahu u každé metriky zvlášť → fts_ok
        files = int(SEARCH_FILES_ROWS * 0.1) - 1
        arts = int(SEARCH_ARTIFACTS_ROWS * 0.1) - 1
        edges = int(GRAPH_EDGES_ROWS * 0.1) - 1
        for f, a, e in ((files, 0, 0), (0, arts, 0), (0, 0, edges)):
            assert classify_search_workload(f, a, e).tier == TIER_FTS_OK

    @pytest.mark.parametrize(
        ("f", "a", "e"),
        [
            (int(SEARCH_FILES_ROWS * 0.1), 0, 0),
            (0, int(SEARCH_ARTIFACTS_ROWS * 0.1), 0),
            (0, 0, int(GRAPH_EDGES_ROWS * 0.1)),
        ],
    )
    def test_watch_ratio_boundary(self, f: int, a: int, e: int):
        profile = classify_search_workload(f, a, e)
        assert profile.tier == TIER_FTS_WATCH
        assert profile.procedures == (PROC_SEARCH_REBUILD,)

    @pytest.mark.parametrize(
        ("f", "a", "e"),
        [
            (SEARCH_FILES_ROWS, 0, 0),
            (0, SEARCH_ARTIFACTS_ROWS, 0),
            (0, 0, GRAPH_EDGES_ROWS),
            (SEARCH_FILES_ROWS + 1, SEARCH_ARTIFACTS_ROWS + 1, GRAPH_EDGES_ROWS + 1),
        ],
    )
    def test_threshold_boundary_is_engine_candidate(self, f: int, a: int, e: int):
        profile = classify_search_workload(f, a, e)
        assert profile.tier == TIER_ENGINE_CANDIDATE
        # postupový tuple roste s tierem; pořadí je stabilní (determinismus)
        assert profile.procedures == (PROC_SEARCH_REBUILD, PROC_REL_BATCHING, PROC_ENGINE_EVAL)

    def test_single_metric_drives_tier(self):
        # jedna metrika nad prahem stačí — ostatní mohou být nulové (F-2: i jen graf)
        assert classify_search_workload(0, 0, GRAPH_EDGES_ROWS).tier == TIER_ENGINE_CANDIDATE
        assert classify_search_workload(SEARCH_FILES_ROWS * 2, 0, 0).tier == TIER_ENGINE_CANDIDATE

    def test_profile_carries_input_metrics(self):
        profile = classify_search_workload(17, 3, 5)
        assert (profile.files_rows, profile.artifacts_rows, profile.graph_edges_rows) == (17, 3, 5)

    @pytest.mark.parametrize("bad", [1.5, None, "42"])
    def test_type_error_for_non_int(self, bad):
        with pytest.raises(TypeError):
            classify_search_workload(bad, 0, 0)

    def test_bool_rejected_as_int(self):
        # bool je instance int — typová kontrola ho explicitně odmítá (B6 konvence)
        with pytest.raises(TypeError):
            classify_search_workload(True, 0, 0)

    @pytest.mark.parametrize("pos", [0, 1, 2])
    def test_value_error_for_negative_metrics(self, pos: int):
        args = [0, 0, 0]
        args[pos] = -1
        with pytest.raises(ValueError):
            classify_search_workload(*args)


# ── B. Data vrstva — read-only statistika + klasifikace ───────────────────────────


def _seeded_db(tmp_path: Path, edges: int = 3) -> CaseDB:
    """Case DB se třemi soubory, jedním artefaktem a N hranami graph_edges."""
    db = CaseDB(tmp_path / f"{CASE_ID}.db")
    db.add_case(Case(id=CASE_ID, name="B12 test"))
    src = EvidenceSource(case_id=CASE_ID, kind="folder", path="/evidence")
    db.add_source(src)
    for i in range(3):
        rec = FileRecord(
            source_id=src.id,
            rel_path=f"docs/file_{i}.txt",
            name=f"file_{i}.txt",
            size_bytes=1024 * (i + 1),
        )
        db.upsert_file(rec)
    art = Artifact(artifact_type="test_artifact", title="needle marker", source_id=src.id)
    db.upsert_artifact(art)
    if edges:
        # velká sada hran v jedné transakci (upsert_edge commituje per řádek — pomalé)
        rows = [
            (CASE_ID, "artifact", f"art-{i}", "entity", f"ent-{i}", "mentions",
             "neutral", "b12 fixture", 0.5)
            for i in range(edges)
        ]
        db.conn.executemany(
            "INSERT INTO graph_edges (case_id, src_type, src_id, dst_type, dst_id,"
            " relation, polarity, reason, confidence, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '2026-11-25T00:00:00Z')"
            " ON CONFLICT (case_id, src_type, src_id, dst_type, dst_id, relation) DO NOTHING",
            rows,
        )
        db.conn.commit()
    return db


class TestSearchWorkloadDb:
    def test_workload_reports_exact_counts(self, tmp_path: Path):
        db = _seeded_db(tmp_path)
        try:
            report = db.search_workload()
        finally:
            db.close()
        assert report["files_rows"] == 3
        assert report["artifacts_rows"] == 1
        assert report["graph_edges_rows"] == 3
        assert report["tier"] == TIER_FTS_OK
        assert report["procedures"] == []

    def test_workload_is_read_only(self, tmp_path: Path):
        """Statistika bez zápisu — opakovaný volání identická, žádné nové řádky."""
        db = _seeded_db(tmp_path)
        try:
            before = dict(db.search_workload())
            audit_before = int(
                db.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
            )
            after = dict(db.search_workload())
            assert after == before  # deterministická, bez vedlejších efektů
            audit_after = int(
                db.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
            )
            assert audit_after == audit_before
        finally:
            db.close()

    def test_workload_tier_escalates_with_graph_edges(self, tmp_path: Path):
        """F-2 stěna — jen objem graph_edges zvedne tier na engine_candidate."""
        db = _seeded_db(tmp_path, edges=GRAPH_EDGES_ROWS)
        try:
            report = db.search_workload()
        finally:
            db.close()
        assert report["graph_edges_rows"] == GRAPH_EDGES_ROWS
        assert report["tier"] == TIER_ENGINE_CANDIDATE
        assert PROC_REL_BATCHING in report["procedures"]  # dávkování relačních dotazů
        assert PROC_ENGINE_EVAL in report["procedures"]


# ── C. CLI `case scale` E2E — aditivní sekce search ───────────────────────────────


class TestCliCaseScaleSearch:
    def test_scale_json_has_search_section(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ):
        from stopa.cli.commands.case import cmd_case_scale

        db = _seeded_db(tmp_path)
        db.close()
        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))

        args = argparse.Namespace(case_id=CASE_ID, json=True, rebuild_fts=False)
        rc = cmd_case_scale(args)
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        # B10 sekce zůstává (BC), B12 přidá aditivní "search"
        assert payload["files_rows"] == 3
        search = payload["search"]
        assert search["files_rows"] == 3
        assert search["artifacts_rows"] == 1
        assert search["graph_edges_rows"] == 3
        assert search["tier"] == TIER_FTS_OK
        assert search["procedures"] == []

    def test_scale_human_prints_search_tier(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ):
        from stopa.cli.commands.case import cmd_case_scale

        db = _seeded_db(tmp_path)
        db.close()
        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))

        args = argparse.Namespace(case_id=CASE_ID, json=False, rebuild_fts=False)
        rc = cmd_case_scale(args)
        out = capsys.readouterr().out
        assert rc == 0
        assert f"search workload:   tier={TIER_FTS_OK}" in out
        # u fts_ok nejsou žádné search postupy → žádná sekce postupů
        assert "Search workload — doporučené postupy:" not in out
