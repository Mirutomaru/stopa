"""P4-7 — Multi-node readiness: DB event bus + registry lease (offline, deterministicky).

W2: tabulka ``events`` v instance DB = cross-process bus; pořadí dáno monotónním
    ``id`` řádku (ne časem). AK jádro: dva procesy nad jednou DB → oba subscriberi
    dostanou stejnou sekvenci událostí deterministicky.
W3: čistá doménová funkce :func:`stopa.domain.case_registry.lease_status`
    ("fake clock" = fiktivní řady heartbeatů, bez wall-clocku) + repozitářové
    ``heartbeat()`` s atomickou globální generací; web poller auto-heartbeatuje
    a forwarduje cizí události do lokálního busu.

Jen stdlib + jádro STOPA (bez volitelných extras → běží i na minimálním profilu).
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sqlite3
import time
from pathlib import Path
from queue import Empty as QueueEmpty

import pytest

from stopa.data import event_repository
from stopa.data.case_registry_repository import heartbeat, list_entries
from stopa.data.cross_case_repository import apply_registry_lease_migration, open_instance
from stopa.domain.case_registry import LEASE_ALIVE, LEASE_EXPIRED, lease_status
from stopa.domain.event_bus import canonical_json, make_event, parse_event, validate_topic

N_EVENTS = 25


# ── W2 — doménové pomocníky event busu (čistá logika) ────────────────────────


def test_make_event_valid() -> None:
    ev = make_event("file.added", "case-1", ts="2026-01-01T00:00:00Z", size=42)
    assert ev["type"] == "file.added"
    assert ev["case_id"] == "case-1"
    assert ev["ts"] == "2026-01-01T00:00:00Z"
    assert ev["size"] == 42


def test_make_event_value_errors() -> None:
    with pytest.raises(ValueError):
        make_event("", "c", ts="2026-01-01T00:00:00Z")
    with pytest.raises(ValueError):
        make_event(5, "c", ts="2026-01-01T00:00:00Z")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        make_event("t", "c", ts="")
    with pytest.raises(ValueError):
        make_event("t", "c", ts="nehodnotny-cas")


def test_canonical_json_deterministic() -> None:
    a = {"b": 2, "a": [1, {"z": True, "y": None}]}
    b = {"a": [1, {"y": None, "z": True}], "b": 2}
    sa, sb = canonical_json(a), canonical_json(b)
    assert sa == sb  # pořadí klíčů nezáleží na vstupu
    assert json.loads(sa) == a


def test_parse_event_shapes() -> None:
    data = parse_event(canonical_json({"type": "file.added", "seq": 3}))
    assert data["seq"] == 3

    with pytest.raises(ValueError):  # neplatná JSON syntaxe → semantická chyba
        parse_event("xyz")
    with pytest.raises(TypeError):  # platné JSON, ale ne objekt (typová chyba)
        parse_event("[1, 2]")


def test_validate_topic() -> None:
    assert validate_topic("case:c-abc") == "case:c-abc"
    for bad in ("", "other:x"):
        with pytest.raises(ValueError):
            validate_topic(bad)
    with pytest.raises(ValueError):
        validate_topic(42)  # type: ignore[arg-type]


# ── W2 — repozitář (I/O nad instance DB) ─────────────────────────────────────


def test_publish_poll_roundtrip(tmp_path: Path) -> None:
    inst = open_instance(tmp_path)
    try:
        for i in range(1, 6):
            ev = make_event("file.added", "c1", ts=f"2026-01-01T00:00:{i % 60:02d}Z", seq=i)
            event_repository.publish_event(inst, "case:c1", ev)
        assert event_repository.max_event_id(inst) == 5

        got = event_repository.poll_events(inst)
        assert len(got) == 5
        # pořadí = monotónní id (deterministické napříč procesy)
        assert [e["event"]["seq"] for e in got] == [1, 2, 3, 4, 5]
        assert all(e["topic"] == "case:c1" for e in got)

        # inkrementální poll od posledního id → prázdný
        last = int(got[-1]["id"])
        assert event_repository.poll_events(inst, after_id=last) == []
    finally:
        inst.close()


def test_publish_event_bad_topic(tmp_path: Path) -> None:
    inst = open_instance(tmp_path)
    try:
        with pytest.raises(ValueError):
            event_repository.publish_event(
                inst, "jiné:téma", make_event("t", "c", ts="2026-01-01T00:00:00Z")
            )
    finally:
        inst.close()


def test_prune_old_events(tmp_path: Path) -> None:
    inst = open_instance(tmp_path)
    try:
        event_repository.publish_event(inst, "case:c1", make_event("t", "c1", ts="2026-01-01T00:00:00Z"))
        event_repository.publish_event(
            inst, "case:c1", make_event("t", "c1", ts="2026-11-22T00:00:00Z")
        )
        removed = event_repository.prune_old_events(inst, older_than_iso="2026-06-01T00:00:00Z")
        assert removed == 1
        rest = event_repository.poll_events(inst)
        assert len(rest) == 1 and rest[0]["topic"] == "case:c1"
    finally:
        inst.close()


# ── W2 AK — dva procesy nad jednou DB → deterministická distribuce ───────────


def _p47_worker(db_dir: str, out_q: multiprocessing.Queue) -> None:
    """Child proces: vlastní spojení, polluje events do doručení všech N."""
    from stopa.data import event_repository as erepo

    conn = open_instance(Path(db_dir))
    try:
        out_q.put(("ready", os.getpid()))
        seen: list[int] = []
        last_id = 0
        deadline = time.monotonic() + 30.0
        while len(seen) < N_EVENTS and time.monotonic() < deadline:
            for ev in erepo.poll_events(conn, after_id=last_id):
                last_id = int(ev["id"])
                seen.append(int(ev["event"]["seq"]))
            if len(seen) >= N_EVENTS:
                break
            time.sleep(0.05)
        out_q.put(("done", os.getpid(), seen))
    finally:
        conn.close()


def test_two_processes_deterministic_delivery(tmp_path: Path) -> None:
    """AK P4-7 W2: N událostí publikuje jeden proces; oba subscriberi (samostatné
    procesy nad stejnou instance DB, WAL) musí dostat tutéž sekvenci v pořadí."""
    parent = open_instance(tmp_path)
    q: multiprocessing.Queue = multiprocessing.Queue()
    procs = [
        multiprocessing.Process(target=_p47_worker, args=(str(tmp_path), q)) for _ in range(2)
    ]
    try:
        for p in procs:
            p.start()
        # oba child ready (svá spojení otevřená) → publikace začíná až po gate
        child_pids = set()
        for _ in range(2):
            tag, pid = q.get(timeout=30)
            assert tag == "ready" and isinstance(pid, int)
            assert pid != os.getpid(), "child běží v PID rodiče (fork selhal)"
            child_pids.add(pid)
        assert len(child_pids) == 2

        for i in range(1, N_EVENTS + 1):
            ev = make_event("file.added", "c1", ts=f"2026-01-01T00:00:{i % 60:02d}Z", seq=i)
            event_repository.publish_event(parent, "case:c1", ev)

        results: list[list[int]] = []
        for _ in range(2):
            tag, pid, seen = q.get(timeout=30)
            assert tag == "done" and isinstance(pid, int), f"child {pid} nedodělal"
            results.append(seen)
    finally:
        for p in procs:
            if p.is_alive():
                p.join(timeout=5)
            assert p.exitcode == 0, f"child exitcode={p.exitcode}"
        parent.close()

    expected = list(range(1, N_EVENTS + 1))
    assert results[0] == expected, "subscriber A nedostal kompletní sekvenci v pořadí"
    assert results[1] == expected, "subscriber B nedostal kompletní sekvenci v pořadí"


# ── W3 — lease: čistá doménová funkce s „fake clockem“ (fiktivní řady beatů) ─


def _entry(case_id: str, node_id: str | None, hb: int) -> dict:
    return {"case_id": case_id, "node_id": node_id, "last_heartbeat": hb}


def test_lease_status_alive() -> None:
    entries = [_entry("c1", "A", 10), _entry("c2", "B", 12)]
    out = lease_status(entries)
    assert out == {"c1": LEASE_ALIVE, "c2": LEASE_ALIVE}  # gap A = 2 < okno 8


def test_lease_status_expired_at_window_boundary() -> None:
    entries = [_entry("c1", "A", 4), _entry("c2", "B", 12)]
    out = lease_status(entries)
    assert out["c1"] == LEASE_EXPIRED  # gap A = 8 == okno → expirace (hranice)
    assert out["c2"] == LEASE_ALIVE


def test_lease_status_unknown_states() -> None:
    entries = [_entry("c1", None, 0), _entry("c2", "B", 5)]
    out = lease_status(entries)
    assert out["c1"] == "unknown"  # legacy řádek bez node_id

    zero_gen = [_entry("c1", "A", 0), _entry("c2", "B", 0)]
    assert set(lease_status(zero_gen).values()) == {"unknown"}  # claim bez beatu

    assert lease_status([]) == {}


def test_lease_status_custom_window() -> None:
    entries = [_entry("c1", "A", 9), _entry("c2", "B", 12)]
    assert lease_status(entries, window=3)["c1"] == LEASE_EXPIRED  # gap 3 ≥ 3
    assert lease_status(entries, window=4)["c1"] == LEASE_ALIVE  # gap 3 < 4


# ── W3 — repozitářový heartbeat (atomická globální generace) ─────────────────

_LEGACY_INSERT = (
    "INSERT INTO case_registry"
    " (case_id, name, tenant, created_at, status, stats_json, synced_at)"
    " VALUES (?, '', NULL, NULL, 'open', '{}', '2026-01-01T00:00:00Z')"
)


def _seed_registry(inst: sqlite3.Connection, case_ids: list[str]) -> None:
    for cid in case_ids:
        inst.execute(_LEGACY_INSERT, (cid,))
    inst.commit()


def test_heartbeat_global_generation(tmp_path: Path) -> None:
    inst = open_instance(tmp_path)
    try:
        _seed_registry(inst, ["c1", "c2"])
        assert heartbeat(inst, node_id="A") == 1
        assert heartbeat(inst, node_id="A") == 2  # globální seq roste dál

        rows = {r["case_id"]: r for r in list_entries(inst)}
        assert rows["c1"]["node_id"] == "A" and rows["c1"]["last_heartbeat"] == 2
        assert rows["c2"]["last_heartbeat"] == 2  # beat bez case_ids pokrývá vše

        gen = heartbeat(inst, node_id="B", case_ids=["c2"])
        assert gen == 3
        rows = {r["case_id"]: r for r in list_entries(inst)}
        assert (rows["c1"]["node_id"], rows["c1"]["last_heartbeat"]) == ("A", 2)
        assert (rows["c2"]["node_id"], rows["c2"]["last_heartbeat"]) == ("B", 3)
    finally:
        inst.close()


def test_lease_expiry_fake_clock_via_beats(tmp_path: Path) -> None:
    """AK P4-7 W3: uzel A zemře (přestane beatovat), B pokračuje → po LEASE_WINDOW
    cizích beatů je lease A expirovaný. Čas = fiktivní řada heartbeatů, ne wall-clock."""
    from stopa.domain.case_registry import LEASE_WINDOW

    inst = open_instance(tmp_path)
    try:
        _seed_registry(inst, ["c1", "c2"])
        assert heartbeat(inst, node_id="A") == 1  # A si claimne vše (gen 1)
        for expected in range(2, LEASE_WINDOW + 3):  # B beatuje jen svůj c2
            assert heartbeat(inst, node_id="B", case_ids=["c2"]) == expected

        rows = {r["case_id"]: r for r in list_entries(inst)}
        generation = max(r["last_heartbeat"] for r in rows.values())
        assert generation - rows["c1"]["last_heartbeat"] >= LEASE_WINDOW  # A zaostává

        out = lease_status(list(rows.values()))
        assert out["c1"] == LEASE_EXPIRED  # A zemřel → expirace
        assert out["c2"] == LEASE_ALIVE  # B žije
    finally:
        inst.close()


def test_heartbeat_empty_registry(tmp_path: Path) -> None:
    inst = open_instance(tmp_path)
    try:
        gen = heartbeat(inst, node_id="A")  # žádné řádky → rollback, aktuální max
        assert gen == 0
        row = inst.execute("SELECT COALESCE(MAX(last_heartbeat), 0) AS m FROM case_registry").fetchone()
        assert int(row["m"]) == 0  # generace se neposunula
    finally:
        inst.close()


def test_heartbeat_bad_node_id(tmp_path: Path) -> None:
    inst = open_instance(tmp_path)
    try:
        with pytest.raises(ValueError):
            heartbeat(inst, node_id="")
        with pytest.raises(ValueError):
            heartbeat(inst, node_id=5)  # type: ignore[arg-type]
    finally:
        inst.close()


def test_lease_migration_legacy_db(tmp_path: Path) -> None:
    """Stará instance DB bez lease sloupců → idempotentní ALTER doplní oba."""
    path = tmp_path / "stopa_instance.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """CREATE TABLE case_registry (
                case_id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
                examiner TEXT, tenant TEXT, created_at TEXT,
                status TEXT NOT NULL DEFAULT 'open', stats_json TEXT NOT NULL DEFAULT '{}',
                synced_at TEXT NOT NULL)"""
        )
        conn.commit()
        apply_registry_lease_migration(conn)  # 1. běh — doplní sloupce
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(case_registry)")}
        assert {"node_id", "last_heartbeat"} <= cols
        apply_registry_lease_migration(conn)  # 2. běh — no-op (idempotentní)
    finally:
        conn.close()


# ── W3/W4 — web poller: auto-heartbeat + cross-process forward do LocalBus ───


def test_web_poller_integration(tmp_path: Path) -> None:
    from stopa.domain.events import case_topic
    from stopa.web.app import create_app

    inst = open_instance(tmp_path)
    _seed_registry(inst, ["c1"])
    inst.close()

    app = create_app(db_dir=tmp_path, event_poll_interval_s=0.05)
    ctx_ = app.state.ctx  # P4-7 test hook
    stopper = ctx_["_stop_event_poller"]
    assert stopper is not None  # poller zapnutý

    bus_q = ctx_["_bus"].subscribe(case_topic("c1"))

    def _last_hb() -> int:
        c2 = open_instance(tmp_path)
        try:
            row = c2.execute(
                "SELECT COALESCE(MAX(last_heartbeat), 0) AS m FROM case_registry"
            ).fetchone()
            return int(row["m"])
        finally:
            c2.close()

    # poller bije heartbeat → generace v registru roste (deadlock-safe čekání)
    deadline = time.monotonic() + 5.0
    while _last_hb() == 0 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert _last_hb() > 0, "poller nebeatoval registry"

    # cross-process forward: cizí proces (tento test) publikuje do events →
    # poller musí událost doručit do lokálního busu přes queue subscribera.
    ext = make_event("file.added", "c1", ts="2026-11-22T00:00:00Z", _pid=-1, seq=99)
    inst2 = open_instance(tmp_path)
    event_repository.publish_event(inst2, case_topic("c1"), ext)
    inst2.close()

    forwarded: dict | None = None
    deadline = time.monotonic() + 5.0
    while forwarded is None and time.monotonic() < deadline:
        try:
            forwarded = bus_q.get(timeout=0.2)
        except QueueEmpty:
            pass
    assert forwarded is not None, "poller nedoručil cizí událost do lokálního busu"
    assert forwarded["seq"] == 99

    # clean stop: po set() už generace neroste (worker ukončen)
    gen_at_stop = _last_hb()
    stopper.set()
    time.sleep(0.3)
    assert _last_hb() == gen_at_stop, "po stopu poller pokračuje v heartbeatování"


def test_web_poller_disabled_by_default(tmp_path: Path) -> None:
    """Default ``event_poll_interval_s=None`` → žádný worker (deterministické unit testy)."""
    from stopa.web.app import create_app

    app = create_app(db_dir=tmp_path)  # default bez polling intervalu
    assert app.state.ctx["_stop_event_poller"] is None


# ── W3 — CLI: ``stopa registry --heartbeat NODE_ID`` (headless uzel) ──────────


def _cli_ns(heartbeat_id: str | None, *, sync=None, json_mode: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        heartbeat=heartbeat_id, sync=sync, tenant=None, user=None, json=json_mode
    )


def test_cli_heartbeat_plain(tmp_path: Path, monkeypatch, capsys) -> None:
    from stopa.cli.commands.registry import cmd_registry

    monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
    inst = open_instance(tmp_path)
    _seed_registry(inst, ["c1"])
    inst.close()

    assert cmd_registry(_cli_ns("node-x")) == 0
    out = capsys.readouterr().out
    assert "heartbeat: node=node-x | generation=1" in out

    assert cmd_registry(_cli_ns("node-y")) == 0
    assert "generation=2" in capsys.readouterr().out


def test_cli_heartbeat_json(tmp_path: Path, monkeypatch, capsys) -> None:
    from stopa.cli.commands.registry import cmd_registry

    monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
    inst = open_instance(tmp_path)
    _seed_registry(inst, ["c1"])
    inst.close()

    assert cmd_registry(_cli_ns("n1", json_mode=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    # H3 — všechny --json výstupy nesou verzi výstupního schématu (aditivní klíč)
    assert payload == {
        "node_id": "n1",
        "generation": 1,
        "stopa_output_schema": 1,
    }


def test_cli_heartbeat_conflicts_with_sync(tmp_path: Path, monkeypatch) -> None:
    from stopa.cli.commands.registry import cmd_registry

    monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
    with pytest.raises(SystemExit):  # ValueError → SystemExit (exit 1 soubor)
        cmd_registry(_cli_ns("n1", sync="c1"))


# ── W2 — open_instance: WAL + busy_timeout (multi-process bezpečí) ────────────


def test_open_instance_wal_and_busy_timeout(tmp_path: Path) -> None:
    inst = open_instance(tmp_path)
    try:
        mode = str(inst.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        assert mode == "wal"
        timeout = int(inst.execute("PRAGMA busy_timeout").fetchone()[0])
        assert timeout >= 5000
    finally:
        inst.close()
