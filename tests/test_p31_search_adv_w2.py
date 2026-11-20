"""P3-1 Advanced Search — datová vrstva + CLI + Web (Wave 2).

Pokrytí návrhu (docs/P3_DESIGNS.md §P3-1, prezentace):
- ``SearchRepository.search_advanced`` — FTS5 bazová cesta + strukturované filtry
  (kind/size/mtime/source/entity) + relace BFS přes graph_edges;
- CLI ``stopa search <case> [dotaz] [--kind --entity --size-min/--size-max
  --mtime-from/--mtime-to --rel-depth]`` — bez flagů byte-identické chování (AK1);
- Web ``GET /api/cases/{id}/search/advanced`` — aditivní endpoint.

Offline a deterministické: syntetická case DB (3 soubory, 2 artefakty, graf
art_f1 → entity → art_f2), přímé volání cmd funkcí přes build_parser() a
FastAPI TestClient bez spuštění serveru.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path

import pytest

CASE_ID = "p31-srch"
ENTITY = "email:joe@example.com"


@pytest.fixture()
def dbdir(tmp_path: Path, monkeypatch):
    """Syntetická case DB pro P3-1 W2.

    Soubory (FTS index přes názvy):
    - praha.jpg 2 MB 2026-03-10 JPEG  → artefakt art_f1 (seed dotazu "praha")
    - maly.txt  500 B 2026-04-01 None → artefakt art_f2
    - velky.pdf 7 MB 2025-11-15 PDF   → bez artefaktu

    Graf: art_f1 --derived_from--> ENTITY --about--> art_f2.
    """
    from stopa.data.db import CaseDB
    from stopa.models import FileRecord, new_id

    d = tmp_path / "dbdir"
    d.mkdir()
    monkeypatch.setenv("STOPA_DB_DIR", str(d))
    db = CaseDB(d / f"{CASE_ID}.db")
    src_id = "src-p31"
    now = "2026-01-01T00:00:00"
    c = db.conn
    c.execute("INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
              (CASE_ID, "P3-1 W2", now))
    c.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES (?, ?, 'folder', '/tmp/p31w2', ?)",
        (src_id, CASE_ID, now),
    )

    def mkfile(name: str, size: int, mtime_iso: str, sig: str | None) -> FileRecord:
        rec = FileRecord(
            id=new_id("f"), source_id=src_id, rel_path=name, name=name,
            size_bytes=size, mtime=mtime_iso,
            sha256=hashlib.sha256(name.encode()).hexdigest(), signature_type=sig,
        )
        db.upsert_file(rec)
        return rec

    f1 = mkfile("praha.jpg", 2 * 1024**2, "2026-03-10T12:00:00", "JPEG")
    f2 = mkfile("maly.txt", 500, "2026-04-01T09:00:00", None)
    f3 = mkfile("velky.pdf", 7 * 1024**2, "2025-11-15T18:00:00", "PDF")

    art_f1, art_f2 = new_id("art"), new_id("art")
    for aid, fid in ((art_f1, f1.id), (art_f2, f2.id)):
        c.execute(
            "INSERT INTO artifacts (id, source_id, file_id, rel_path, artifact_type,"
            " details_json) VALUES (?, ?, ?, ?, 'test_artifact', '{}')",
            (aid, src_id, fid, None),
        )

    from stopa.data.graph_repository import GraphRepository

    graph = GraphRepository(c)  # kanonická cesta (upsert + created_at + validace)
    graph.upsert_edge(
        CASE_ID, src_type="artifact", src_id=art_f1, dst_type="entity",
        dst_id=ENTITY, relation="derived_from", reason="test fixture",
    )
    graph.upsert_edge(
        CASE_ID, src_type="entity", src_id=ENTITY, dst_type="artifact",
        dst_id=art_f2, relation="about", reason="test fixture",
    )
    c.commit()
    yield {"db": db, "f1": f1, "f2": f2, "f3": f3, "art_f1": art_f1, "art_f2": art_f2}
    db.close()


# ── datová vrstva: SearchRepository ────────────────────────────────────────


class TestSearchRepository:
    def test_ak1_plain_query_identical_to_e9(self, dbdir):
        """Bez strukturovaných filtrů = delegace do E9 cesty (stejné ID i pořadí)."""
        from stopa.data.search_repository import SearchRepository
        from stopa.domain.search_adv import AdvancedSearchQuery

        db = dbdir["db"]
        adv = SearchRepository(db.conn).search_advanced(AdvancedSearchQuery(text="praha"))
        e9 = db.search("praha")
        assert [r.rel_path for r in adv.results] == [r.rel_path for r in e9]
        assert [r.rel_path for r in adv.results] == ["praha.jpg"]

    def test_structured_filters_narrow(self, dbdir):
        from stopa.data.search_repository import SearchRepository
        from stopa.domain.search_adv import AdvancedSearchQuery, FilterSpec

        repo = SearchRepository(dbdir["db"].conn)

        big = repo.search_advanced(AdvancedSearchQuery(
            filters=FilterSpec(size_min=1024**2)))
        assert {r.rel_path for r in big.results} == {"praha.jpg", "velky.pdf"}

        window = repo.search_advanced(AdvancedSearchQuery(
            text="praha", filters=FilterSpec.from_iso(mtime_from="2026-03", mtime_to="2026-04")))
        assert [r.rel_path for r in window.results] == ["praha.jpg"]

        pdf = repo.search_advanced(AdvancedSearchQuery(filters=FilterSpec(kind="PDF")))
        assert {r.rel_path for r in pdf.results} == {"velky.pdf"}

    def test_empty_result_is_not_error(self, dbdir):
        from stopa.data.search_repository import SearchRepository
        from stopa.domain.search_adv import AdvancedSearchQuery, FilterSpec

        res = SearchRepository(dbdir["db"].conn).search_advanced(
            AdvancedSearchQuery(filters=FilterSpec(size_max=100)))
        assert res.results == ()  # prázdné, ne výjimka

    def test_deterministic_repeated_runs(self, dbdir):
        import copy

        from stopa.data.search_repository import SearchRepository
        from stopa.domain.search_adv import AdvancedSearchQuery, FilterSpec, RelationSpec

        q = AdvancedSearchQuery(
            text="praha",
            filters=FilterSpec.from_iso(mtime_from="2026-01"),
            relations=RelationSpec(depth=3),
        )
        repo = SearchRepository(dbdir["db"].conn)
        first = json.dumps(_result_json(repo.search_advanced(copy.deepcopy(q))), sort_keys=True)
        second = json.dumps(_result_json(repo.search_advanced(copy.deepcopy(q))), sort_keys=True)
        assert first == second

    def test_limit_applied_after_filter(self, dbdir):
        from stopa.data.search_repository import SearchRepository
        from stopa.domain.search_adv import AdvancedSearchQuery, FilterSpec

        res = SearchRepository(dbdir["db"].conn).search_advanced(AdvancedSearchQuery(
            filters=FilterSpec(size_min=1024**2), limit=1))
        # pořadí bez textu = mtime DESC → praha.jpg (2026-03) před velky.pdf (2025-11)
        assert [r.rel_path for r in res.results] == ["praha.jpg"]

    def test_entity_filter_via_graph(self, dbdir):
        from stopa.data.search_repository import SearchRepository
        from stopa.domain.search_adv import AdvancedSearchQuery, FilterSpec

        res = SearchRepository(dbdir["db"].conn).search_advanced(AdvancedSearchQuery(
            filters=FilterSpec(entity=ENTITY)))
        # soubory s artefaktem přímo spojeným entitou; velky.pdf (bez artefaktu) ven
        assert {r.rel_path for r in res.results} == {"praha.jpg", "maly.txt"}

    def test_relations_depth1_only_entity(self, dbdir):
        from stopa.data.search_repository import SearchRepository
        from stopa.domain.search_adv import AdvancedSearchQuery, RelationSpec

        res = SearchRepository(dbdir["db"].conn).search_advanced(AdvancedSearchQuery(
            text="praha", relations=RelationSpec(depth=1)))
        assert [r.rel_path for r in res.results] == ["praha.jpg"]
        assert res.related_files == ()  # hloubka 1: jen entity, žádný další soubor
        nodes = {(n["type"], n["id"]) for n in res.related_nodes}
        assert ("entity", ENTITY) in nodes

    def test_relations_depth2_reaches_second_file(self, dbdir):
        from stopa.data.search_repository import SearchRepository
        from stopa.domain.search_adv import AdvancedSearchQuery, RelationSpec

        res = SearchRepository(dbdir["db"].conn).search_advanced(AdvancedSearchQuery(
            text="praha", relations=RelationSpec(depth=2)))
        # dosažený artefakt art_f2 → jeho soubor maly.txt; zásah praha.jpg neopakujeme
        assert [r.rel_path for r in res.related_files] == ["maly.txt"]
        depths = {n["id"]: n["depth"] for n in res.related_nodes}
        assert depths.get(ENTITY) == 1

    def test_scope_artifacts_not_implemented_yet(self, dbdir):
        import pytest as _pt

        from stopa.data.search_repository import SearchRepository
        from stopa.domain.search_adv import AdvancedSearchQuery

        with _pt.raises(NotImplementedError):
            SearchRepository(dbdir["db"].conn).search_advanced(
                AdvancedSearchQuery(text="x", scope="artifacts"))


def _result_json(res) -> dict:
    """Deterministický JSON tvar výsledku (pro determinismus testů)."""
    return {
        "results": [r.rel_path for r in res.results],
        "related_files": [r.rel_path for r in res.related_files],
        "related_nodes": list(res.related_nodes),
    }


# ── CLI: stopa search s pokročilými flagy ───────────────────────────────────


def _cli(argv: list[str]) -> tuple[int, str]:
    """Spuští skrze build_parser() (ověřuje registraci flagů) a chytá stdout."""
    from stopa.cli import build_parser

    ns = build_parser().parse_args(argv)
    buf = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        rc = ns.func(ns)
    return int(rc if isinstance(rc, int) else 0), buf.getvalue()


class TestCliSearchAdvanced:
    def test_no_flags_legacy_output(self, dbdir):
        """Bez pokročilých flagů → původní formát (AK1 na CLI úrovni)."""
        rc, out = _cli(["search", CASE_ID, "praha"])
        assert rc == 0
        lines = [l for l in out.splitlines() if l.strip()]
        assert any("praha.jpg" in l and "[JPEG]" in l for l in lines)
        assert any(l.startswith("CELKEM: 1 soubor") for l in lines)

    def test_rel_depth_adds_relations_section(self, dbdir):
        """--rel-depth přidá sekci VZTAHY; výsledková část zůstává identická."""
        rc_plain, plain = _cli(["search", CASE_ID, "praha"])
        rc_adv, adv = _cli(["search", CASE_ID, "praha", "--rel-depth", "2"])
        assert (rc_plain, rc_adv) == (0, 0)

        # výsledková sekce (řádky PŘED hlavičkou VZTAHY) identická v obou výstupech
        def results_section(text: str) -> list[str]:
            out = []
            for l in text.splitlines():
                if "VZTAHY" in l or "CELKEM" in l:
                    break
                out.append(l.strip())
            return [l for l in out if l]

        assert results_section(plain) == results_section(adv)
        assert "VZTAHY (hloubka 2)" in adv
        assert "maly.txt" in adv  # související soubor z dosaženého artefaktu
        assert ENTITY in adv  # entita v seznamu uzlů grafu

    def test_flags_narrow_results(self, dbdir):
        # metadata-only dotaz: query je povinný poziční → prázdný string
        rc, out = _cli(["search", CASE_ID, "", "--size-min", str(1024**2)])
        assert rc == 0
        assert "praha.jpg" in out and "velky.pdf" in out
        assert "maly.txt" not in out

    def test_json_additive_keys(self, dbdir):
        rc, out = _cli(["search", CASE_ID, "praha", "--rel-depth", "2", "--json"])
        assert rc == 0
        body = json.loads(out)
        # aditivní klíče nad původním kontraktem (case_id/query/results/total)
        for key in ("case_id", "query", "results", "total", "filters", "related"):
            assert key in body
        assert body["total"] == 1 and body["results"][0]["rel_path"] == "praha.jpg"
        rel = body["related"]
        assert [f["rel_path"] for f in rel["files"]] == ["maly.txt"]
        assert any(n.get("type") == "entity" for n in rel["nodes"])

    def test_invalid_filter_exit2_stderr(self, dbdir):
        """Semantická chyba filtru → exit 2 + zpráva na stderr (ne traceback)."""
        from stopa.cli import build_parser

        ns = build_parser().parse_args(["search", CASE_ID, "", "--mtime-from", "garbage"])
        err, out = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = ns.func(ns)
        assert rc == 2 and "Neplatný filtr" in err.getvalue()


# ── Web: GET /api/cases/{id}/search/advanced ───────────────────────────────


@pytest.fixture()
def client(dbdir):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    return TestClient(create_app())


class TestWebSearchAdvanced:
    def test_full_payload_with_relations(self, client):
        r = client.get(f"/api/cases/{CASE_ID}/search/advanced",
                       params={"q": "praha", "rel_depth": 2})
        assert r.status_code == 200
        body = r.json()
        assert body["case_id"] == CASE_ID and body["total"] == 1
        assert [f["rel_path"] for f in body["results"]] == ["praha.jpg"]
        assert [f["rel_path"] for f in body["related"]["files"]] == ["maly.txt"]
        nodes = {(n["type"], n["id"]) for n in body["related"]["nodes"]}
        assert ("entity", ENTITY) in nodes

    def test_filters_only_no_relations(self, client):
        r = client.get(f"/api/cases/{CASE_ID}/search/advanced",
                       params={"size_min": 1024**2})
        assert r.status_code == 200
        body = r.json()
        assert {f["rel_path"] for f in body["results"]} == {"praha.jpg", "velky.pdf"}
        assert body["related"]["files"] == [] and body["related"]["nodes"] == []

    def test_invalid_filter_400(self, client):
        r = client.get(f"/api/cases/{CASE_ID}/search/advanced",
                       params={"mtime_from": "garbage"})
        assert r.status_code == 400 and "neplatný filtr" in r.json()["detail"]

    def test_unknown_case_404(self, client):
        r = client.get("/api/cases/nope/search/advanced", params={"q": "x"})
        assert r.status_code == 404
