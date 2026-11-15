"""F2.5 — Cache vrstva: LRU + TTL per query type, invalidace na mutačních bodech.

AK F2.5: opakovaná FTS query < 50 ms; hit ratio ≥ 70 % na repeat workloadu
(re-render Entity Graph v GUI + opakované hledání z historie).

Unit testy = čistý QueryCache (bez IO); wiring testy = CaseDB facade se
spy na repozitární vrstvě (důkaz, že cache hit obchází SQL).
"""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

# ── fixtures ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_process_cache():
    """Deterministický stav procesního cache (PROCESS_CACHE je sdílený)."""
    from stopa.data.query_cache import PROCESS_CACHE

    PROCESS_CACHE.invalidate(None)
    PROCESS_CACHE.reset_stats()
    yield
    PROCESS_CACHE.invalidate(None)


def _mk_file_rec(src_id: str, name: str, size: int = 2048):
    """FileRecord pro syntetickou ingest (FTS obsah = název souboru)."""
    from stopa.models import FileRecord, new_id

    return FileRecord(
        id=new_id("f"),
        source_id=src_id,
        rel_path=name,
        name=name,
        size_bytes=size,
        mtime=datetime(2026, 1, 1),  # deterministické (bez utcnow → DTZ003)
        sha256=hashlib.sha256(name.encode()).hexdigest(),
        extension=name.rsplit(".", 1)[-1] if "." in name else "",
    )


def _seed_case(db, case_id: str, src_id: str) -> None:
    """Vloží case + source (raw SQL — cache netýče jen o dotazy)."""
    now = "2026-01-01T00:00:00"
    db.conn.execute(
        "INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
        (case_id, case_id.upper(), now),
    )
    db.conn.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES (?, ?, 'folder', '/tmp/f25-seed', ?)",
        (src_id, case_id, now),
    )
    db.conn.commit()


@pytest.fixture()
def case_db(tmp_path: Path):
    """Syntetická case DB se 3 soubory (FTS termín 'report')."""
    from stopa.data.db import CaseDB

    db = CaseDB(str(tmp_path / "case-f25.db"))
    src_id = "src-f25"
    _seed_case(db, "c1", src_id)
    for i in range(3):
        db.upsert_file(_mk_file_rec(src_id, f"report_{i:04d}.txt"))
    db.commit()
    yield db
    db.close()


@pytest.fixture()
def big_db(tmp_path: Path):
    """Větší case DB (2500 souborů, FTS termín 'report') pro AK časování."""
    from stopa.data.db import CaseDB

    db = CaseDB(str(tmp_path / "case-f25-big.db"))
    src_id = "src-f25big"
    _seed_case(db, "c1", src_id)
    for i in range(2500):
        db.upsert_file(_mk_file_rec(src_id, f"report_{i:05d}.txt"))
    db.commit()
    yield db
    db.close()


def _spy_repo_search(db) -> list[int]:
    """Obalí ``db.file_repo.search`` počítadlem volání; vrací počítadlo."""
    orig = db.file_repo.search
    calls = [0]

    def spy(*a, **kw):
        calls[0] += 1
        return orig(*a, **kw)

    db.file_repo.search = spy
    return calls


# ── unit: QueryCache core API ───────────────────────────────


class TestQueryCacheCore:
    def test_set_get_roundtrip_and_empty_list_cached(self):
        from stopa.data.query_cache import QueryCache

        c = QueryCache()
        assert c.get("fts", "s1","x") is None  # miss
        c.set("fts", "s1", "x", value=[])
        assert c.get("fts", "s1","x") == []    # prázdný výsledek je legitimní záznam

    def test_params_are_part_of_key(self):
        from stopa.data.query_cache import QueryCache

        c = QueryCache()
        c.set("fts", "s1", "a", None, 100, value=[1])
        assert c.get("fts", "s1", "a", None, 100) == [1]
        assert c.get("fts", "s1", "a", None, 50) is None    # jiný limit → miss
        assert c.get("fts", "s2", "a", None, 100) is None   # jiný scope → miss

    def test_get_or_set_computes_once(self):
        from stopa.data.query_cache import QueryCache

        c = QueryCache()
        n = [0]

        def compute():
            n[0] += 1
            return ["v"]

        assert c.get_or_set("fts", "s", compute,"x") == ["v"]
        assert c.get_or_set("fts", "s", compute,"x") == ["v"]
        assert n[0] == 1  # druhý volání z cache

    def test_get_or_set_exception_not_cached(self):
        from stopa.data.query_cache import QueryCache

        c = QueryCache()
        state = {"fail": True}

        def compute():
            if state["fail"]:
                raise ValueError("boom")
            return ["ok"]

        with pytest.raises(ValueError):
            c.get_or_set("fts", "s", compute,"x")
        state["fail"] = False
        assert c.get_or_set("fts", "s", compute,"x") == ["ok"]  # po chybě se počítá znovu


# ── unit: LRU eviction ──────────────────────────────────────


class TestLruEviction:
    def test_evicts_least_recently_used(self):
        from stopa.data.query_cache import QueryCache

        c = QueryCache(maxsize=2)
        c.set("fts", "s", "a", value=[1])
        c.set("fts", "s", "b", value=[2])
        assert c.get("fts", "s","a") == [1]  # 'a' novější → LRU je 'b'
        c.set("fts", "s", "c", value=[3])  # evikuje 'b'
        assert c.get("fts", "s","a") == [1]
        assert c.get("fts", "s","b") is None
        assert c.get("fts", "s","c") == [3]

    def test_eviction_across_op_types_and_scopes(self):
        from stopa.data.query_cache import QueryCache

        c = QueryCache(maxsize=2)
        c.set("fts", "scope-a", "x", value=[1])
        c.set("entities", "scope-b", "c", value=[2])
        c.set("correlations", "scope-c", "d", value=[3])  # evikuje nejstarší
        assert c.get("fts", "scope-a","x") is None
        assert c.get("entities", "scope-b","c") == [2]
        assert c.get("correlations", "scope-c","d") == [3]


# ── unit: TTL per query type ────────────────────────────────


class TestTtlPerType:
    def test_expiry_per_type(self):
        from stopa.data.query_cache import QueryCache

        c = QueryCache(ttls={"fts": 0.1, "entities": None})
        c.set("fts", "s", "x", value=[1])
        c.set("entities", "s", "c", value=[2])
        assert c.get("fts", "s","x") == [1]
        time.sleep(0.15)
        assert c.get("fts", "s","x") is None              # fts: TTL 0,1 s vypršel
        assert c.get("entities", "s","c") == [2]    # entities: bez TTL

    def test_set_refreshes_ttl(self):
        from stopa.data.query_cache import QueryCache

        c = QueryCache(ttls={"fts": 0.3})
        c.set("fts", "s", "x", value=[1])
        time.sleep(0.2)
        c.set("fts", "s", "x", value=[2])  # refresh → nový TTL od tohoto okamžiku
        time.sleep(0.2)                      # celkem 0,4 s, ale jen 0,2 s od posledního set
        assert c.get("fts", "s","x") == [2]


# ── unit: invalidace + statistika ───────────────────────────


class TestInvalidationAndStats:
    def test_invalidate_scope_only(self):
        from stopa.data.query_cache import QueryCache

        c = QueryCache()
        c.set("fts", "scope-a", "q", value=[1])
        c.set("entities", "scope-b", "c", value=[2])
        assert c.invalidate("scope-a") == 1
        assert c.get("fts", "scope-a","q") is None
        assert c.get("entities", "scope-b","c") == [2]  # jiný scope netknut

    def test_invalidate_all(self):
        from stopa.data.query_cache import QueryCache

        c = QueryCache()
        c.set("fts", "a", "q", value=[1])
        c.set("correlations", "b", "x", value=[2])
        assert c.invalidate(None) == 2
        assert c.stats()["size"] == 0

    def test_stats_and_reset(self):
        from stopa.data.query_cache import QueryCache

        c = QueryCache()
        c.set("fts", "s", "q", value=[])
        c.get("fts", "s","q")   # hit
        c.get("fts", "s","y")   # miss
        st = c.stats()
        assert (st["hits"], st["misses"]) == (1, 1)
        assert st["hit_ratio"] == 0.5
        c.reset_stats()
        assert c.stats()["hit_ratio"] is None


# ── unit: thread safety ─────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_get_or_set(self):
        from stopa.data.query_cache import QueryCache

        c = QueryCache(maxsize=32)
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                for i in range(50):
                    q = f"q{i % 8}"
                    v = c.get_or_set("fts", "shared", lambda q=q: [q], q)
                    assert isinstance(v, list) and v == [q]
            except BaseException as e:  # noqa: BLE001 — test sbírá všechny výjimky
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not errors, f"chyby z vláken: {errors}"
        st = c.stats()
        # každé get_or_set provedlo přesně jeden get → počítadla součtově sedí
        assert st["hits"] + st["misses"] == 8 * 50
        assert 1 <= st["size"] <= 8


# ── wiring: CaseDB facade (AK F2.5) ─────────────────────────


class TestFacadeWiring:
    def test_repeated_fts_query_under_50ms(self, big_db):
        """AK F2.5 — opakovaná FTS query < 50 ms; cache hit obchází SQL."""
        db = big_db
        calls = _spy_repo_search(db)
        q = "report"

        first = db.search(q, None, 3000)
        assert len(first) > 1000   # sanity: termín matched velké množství souborů
        assert calls[0] == 1          # první dotaz = přesně jedno SQL volání

        worst = 0.0
        for _ in range(25):
            t0 = time.perf_counter()
            res = db.search(q, None, 3000)
            worst = max(worst, time.perf_counter() - t0)
            assert len(res) == len(first)
        assert calls[0] == 1          # opakování z cache — žádný nový SQL dotaz
        assert worst < 0.05           # AK: opakovaná FTS query < 50 ms

    def test_hit_ratio_ge_70_percent_on_repeat_workload(self, case_db):
        """AK F2.5 — hit ratio ≥ 70 % na reálném repeat workloadu (GUI)."""
        from stopa.data.query_cache import PROCESS_CACHE

        db = case_db
        PROCESS_CACHE.reset_stats()
        # GUI session: opakované hledání q1 + re-render Entity Graph (entities+correlations)
        seq = ["q1", "q1", "e", "c", "q1", "q1", "e", "c",
               "q1", "q2", "q1", "q1", "e", "c", "q1"]

        for kind in seq:
            if kind == "e":
                db.list_entities("c1")
            elif kind == "c":
                db.list_correlations("c1")
            else:
                db.search(kind)  # 'q1' / 'q2' — FTS termíny (bez shod → [], cacheuje se)

        st = PROCESS_CACHE.stats()
        assert st["hits"] + st["misses"] == len(seq)   # každý op = přesně jeden get
        assert st["misses"] == 4                       # první q1, e, c, q2
        assert st["hit_ratio"] is not None and st["hit_ratio"] >= 0.7

    def test_invalidation_on_file_upsert(self, case_db):
        """upsert_file → FTS cache neplatné; výsledek se počítá znovu."""
        db = case_db
        calls = _spy_repo_search(db)
        q = "report"

        first = db.search(q)
        assert len(first) == 3
        db.search(q)                    # hit — bez nového SQL
        assert calls[0] == 1

        db.upsert_file(_mk_file_rec("src-f25", "report_new.txt"))  # mutace → invalidace
        second = db.search(q)           # recompute — nový soubor v výsledku
        assert calls[0] == 2
        assert len(second) == 4

    def test_invalidation_on_entity_and_correlation_upsert(self, case_db):
        """upsert_entities / add_correlation → příslušné cache neplatné."""
        db = case_db
        e_calls = [0]
        c_calls = [0]
        orig_e = db.entity_repo.list_entities
        orig_c = db.entity_repo.list_correlations

        def espy(*a, **kw):
            e_calls[0] += 1
            return orig_e(*a, **kw)

        def cspy(*a, **kw):
            c_calls[0] += 1
            return orig_c(*a, **kw)

        db.entity_repo.list_entities = espy
        db.entity_repo.list_correlations = cspy

        assert db.list_entities("c1") == []
        assert db.list_entities("c1") == []   # hit
        assert e_calls[0] == 1

        db.upsert_entities(
            "c1", [("email", "user@example.com", "User@Example.COM", None, None)]
        )
        ents = db.list_entities("c1")         # recompute — nová entity přítomná
        assert e_calls[0] == 2
        assert any(e["value"] == "user@example.com" for e in ents)

        assert db.list_correlations("c1") == []
        assert db.list_correlations("c1") == []   # hit
        assert c_calls[0] == 1
        db.add_correlation(
            "c1", "tel:+4201", "email:user@example.com", "same_contact", "possible", []
        )
        corr = db.list_correlations("c1")    # recompute — nové propojení přítomné
        assert c_calls[0] == 2
        assert len(corr) == 1

    def test_empty_query_returns_empty_without_cache(self, case_db):
        """Prázdná query → [] bez výpočtu i bez cache záznamu."""
        from stopa.data.query_cache import PROCESS_CACHE

        db = case_db
        calls = _spy_repo_search(db)
        assert db.search("   ") == []
        assert calls[0] == 0
        before = PROCESS_CACHE.stats()["size"]
        db.search("")
        assert PROCESS_CACHE.stats()["size"] == before


# ── wiring: izolace mezi případy (scope = case DB soubor) ───


class TestCrossCaseIsolation:
    def test_invalidation_of_one_case_does_not_touch_other(self, tmp_path):
        """Dva case DB soubory: invalidace jednoho nedotkne druhý."""
        from stopa.data.db import CaseDB

        db1 = CaseDB(str(tmp_path / "case-a.db"))
        db2 = CaseDB(str(tmp_path / "case-b.db"))
        _seed_case(db1, "c1", "src-a")
        _seed_case(db2, "c1", "src-b")
        calls1 = _spy_repo_search(db1)
        calls2 = _spy_repo_search(db2)

        q = "report"
        db1.search(q)
        db2.search(q)   # jiný scope → i při stejné query své vlastní miss+set
        assert calls1[0] == 1 and calls2[0] == 1

        db1.upsert_file(_mk_file_rec("src-a", "report_extra.txt"))  # invaliduje jen A
        db1.search(q)   # recompute v A
        db2.search(q)   # B stále z cache
        assert calls1[0] == 2 and calls2[0] == 1

        db1.close()
        db2.close()


# ── web: diagnostika odhaluje stav cache ────────────────────


class TestWebDiagnostics:
    def test_diagnostics_query_cache_section(self, tmp_path):
        from fastapi.testclient import TestClient

        from stopa.web.app import create_app

        app = create_app(tmp_path)
        with TestClient(app) as client:
            r = client.get("/api/diagnostics")
            assert r.status_code == 200
            qc = r.json()["query_cache"]
            assert set(qc) >= {"hits", "misses", "size", "maxsize", "hit_ratio"}
