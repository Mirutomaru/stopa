"""F4.2 — WebSockets: live progress ingestu / timeline events / AI akce.

Akcepční kritéria F4.2 (ROADMAP V2):
- ``GET /api/cases/{case_id}/ws`` — okamžité ``hello``, stream událostí
  (``ingest.progress`` / ``timeline.event`` / ``ai.action``), heartbeat;
- neznámý case → close code **4004**;
- nablokující publish: pomalý konzument ztrácí nejstarší události,
  místo aby blokoval produkující vlákno pipeline;
- graceful degradation — bez WS klientů vše funguje dál přes REST.

Přesnou latenci < 200 ms ověřuje E2E smoke na živém serveru (uvicorn +
WS klient); tady se testuje kontrakt a deterministické chování in-process.
"""
from __future__ import annotations

import contextlib
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from stopa.data.db import CaseDB
from stopa.domain.events import LiveEventBus, case_topic
from stopa.models import Case, EvidenceSource
from stopa.web.app import create_app


def _chrome_ts(unix_seconds: int) -> int:
    """Unix epoch → Chrome epoch (1601-01-01), mikrosekundy."""
    return (unix_seconds + 11_644_473_600) * 1_000_000


def _chrome_history_db(root: Path, name: str = "History") -> None:
    """Syntetická Chrome history DB s jedním známým timestampem (jako test_e3)."""
    import sqlite3

    p = root / name
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
    conn.execute(
        "CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER,"
        " visit_time INTEGER, from_visit INTEGER)"
    )
    # 2024-01-15T10:00:00Z = 1705312800 s
    conn.execute("INSERT INTO urls VALUES (1, 'https://example.com/a', 'Stránka A')")
    conn.execute(
        "INSERT INTO visits (url, visit_time) VALUES (1, ?)", (_chrome_ts(1_705_312_800),)
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def client(tmp_path: Path):
    app = create_app(db_dir=tmp_path, ws_heartbeat_s=0.3)
    with TestClient(app) as c:
        yield c


_log = logging.getLogger(__name__)


def _mk_case(client: TestClient, name: str = "WS case") -> str:
    r = client.post("/api/cases", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


class TestWsContract:
    def test_hello_is_first_message(self, client):
        cid = _mk_case(client)
        with client.websocket_connect(f"/api/cases/{cid}/ws") as ws:
            hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["case_id"] == cid
        assert "ts" in hello

    def test_unknown_case_closes_with_4004(self, client):
        with (
            client.websocket_connect("/api/cases/neexistuje-1/ws") as ws,
            pytest.raises(WebSocketDisconnect) as exc_info,
        ):
            ws.receive_json()
        assert exc_info.value.code == 4004

    def test_heartbeat_when_idle(self, client):
        cid = _mk_case(client)
        deadline = time.monotonic() + 5.0
        with client.websocket_connect(f"/api/cases/{cid}/ws") as ws:
            assert ws.receive_json()["type"] == "hello"
            got_heartbeat = False
            while time.monotonic() < deadline:
                ev = ws.receive_json()
                if ev["type"] == "heartbeat":
                    got_heartbeat = True
                    break
        assert got_heartbeat, "žádný heartbeat do 5 s (ws_heartbeat_s=0.3)"


class TestIngestFlowOverWs:
    def test_sync_ingest_streams_progress_and_timeline(
        self, client, tmp_path, monkeypatch
    ):
        """E2E přes WS: hello → ingest.progress(+done) + timeline.event.

        Fixture = syntetická Chrome History DB (deterministicky generuje
        artefakt s timestampem → timeline event; plain .txt artefakty nemá).
        Latence AK < 200 ms měříme jako **delivery** (server-side publish →
        přijetí klientem), ne včetně doby samotného ingestu.
        """
        import stopa.domain.events as evmod

        pub_ts: dict[str, float] = {}
        orig_publish = evmod.LiveEventBus.publish

        def _stamped(self, topic, event):
            if event.get("type") == "timeline.event" and "t_pub" not in pub_ts:
                pub_ts["t_pub"] = time.perf_counter()
            return orig_publish(self, topic, event)

        monkeypatch.setattr(evmod.LiveEventBus, "publish", _stamped)

        cid = _mk_case(client)
        src = tmp_path / "src"
        hist_dir = src / "profile"
        hist_dir.mkdir(parents=True)
        _chrome_history_db(hist_dir)

        events: list[dict] = []
        first_timeline_at: float | None = None
        with client.websocket_connect(f"/api/cases/{cid}/ws") as ws:
            assert ws.receive_json()["type"] == "hello"
            r = client.post(
                f"/api/cases/{cid}/sources",
                json={"path": str(src), "profile": "forensic"},
            )
            assert r.status_code == 201, r.text
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                ev = ws.receive_json()
                events.append(ev)
                if (
                    ev.get("type") == "timeline.event"
                    and first_timeline_at is None
                ):
                    first_timeline_at = time.perf_counter()
                if ev.get("type") == "ingest.progress" and ev.get("status") == "done":
                    break

        types = [e["type"] for e in events]
        assert "ingest.progress" in types, f"chybí ingest.progress: {types}"
        progress = [e for e in events if e["type"] == "ingest.progress"]
        last = progress[-1]
        assert last["status"] == "done"
        assert last["total"] > 0 and last["done"] >= last["total"], last

        # timeline.event — pipeline materializuje timeline pro artefakty (History → browser_history)
        assert first_timeline_at is not None, f"chybí timeline.event: {types}"

        # latence AK < 200 ms: publish (server) → přijetí WS klientem
        delivery = first_timeline_at - pub_ts["t_pub"]
        assert delivery < 0.2, f"delivery latence {delivery * 1000:.1f} ms ≥ 200 ms"

    def test_graceful_degradation_without_ws_clients(self, client, tmp_path):
        """Bez WS klientů vše funguje dál přes REST (graceful degradation)."""
        cid = _mk_case(client)
        src = tmp_path / "src"
        hist_dir = src / "profile"
        hist_dir.mkdir(parents=True)
        _chrome_history_db(hist_dir)

        r = client.post(
            f"/api/cases/{cid}/sources",
            json={"path": str(src), "profile": "forensic"},
        )
        assert r.status_code == 201, r.text
        # timeline přes REST — bez WS klientů vše projde normálně (graceful)
        tl = client.get(f"/api/cases/{cid}/timeline").json()
        rows = tl if isinstance(tl, list) else []
        assert len(rows) >= 1, "timeline prázdná po ingestu bez WS klientů"


class TestConcurrency:
    def test_100_concurrent_clients_receive_event(self, client, tmp_path):
        """AK: ~100 současných WS klientů — každý dostane událost (bus scale-out)."""
        cid = _mk_case(client)
        src = tmp_path / "src"
        hist_dir = src / "profile"
        hist_dir.mkdir(parents=True)
        _chrome_history_db(hist_dir)

        N = 100
        with contextlib.ExitStack() as stack:
            socks = [
                stack.enter_context(client.websocket_connect(f"/api/cases/{cid}/ws"))
                for _ in range(N)
            ]
            for ws in socks:
                assert ws.receive_json()["type"] == "hello"

            r = client.post(
                f"/api/cases/{cid}/sources",
                json={"path": str(src), "profile": "forensic"},
            )
            assert r.status_code == 201, r.text

            # každý klient musí vidět timeline.event (až do done progress)
            got = 0
            deadline = time.monotonic() + 30.0
            pending = list(range(N))
            while pending and time.monotonic() < deadline:
                for i in list(pending):
                    try:
                        ev = socks[i].receive_json()
                    except Exception as exc:  # noqa: BLE001 — close session při drain (defenzivní)
                        _log.debug("drain %d: %s", i, exc)
                        continue
                    if ev.get("type") == "timeline.event":
                        got += 1
                        pending.remove(i)
            assert got == N, f"jen {got}/{N} klientů dostalo timeline.event"


class TestDbHooks:
    """Hooky CaseDB.on_event — deterministické testy vrstvy dat."""

    @pytest.fixture()
    def db(self, tmp_path: Path) -> CaseDB:
        d = CaseDB(tmp_path / "case-x.db")
        d.add_case(Case(id="cx", name="Hook case"))
        d.add_source(
            EvidenceSource(
                id="s1", case_id="cx", path=str(tmp_path), kind="folder"
            )
        )
        return d

    def test_timeline_event_emitted_with_payload(self, db: CaseDB):
        captured: list[tuple[str, dict]] = []
        db.on_event = lambda etype, payload: captured.append((etype, payload))
        ts = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
        event_id = db.add_timeline_event(
            source_id="s1",
            ts_utc=ts,
            event_type="file",
            title="poznamky.txt",
            anomaly_flags=("night_activity",),
        )
        assert len(captured) == 1
        etype, payload = captured[0]
        assert etype == "timeline.event"
        assert payload["event_id"] == event_id
        assert payload["source_id"] == "s1"
        assert payload["ts_utc"] == ts.isoformat()
        assert payload["event_type"] == "file"
        assert payload["title"] == "poznamky.txt"
        assert payload["anomaly_flags"] == ["night_activity"]

    def test_ai_action_only_for_ai_prefix(self, db: CaseDB):
        captured: list[tuple[str, dict]] = []
        db.on_event = lambda etype, payload: captured.append((etype, payload))
        row_id = db.log_operation("ai_analyzed", actor="web")
        assert isinstance(row_id, int) and row_id > 0
        # ne-AI operace se do WS netlačí
        db.log_operation("interop_exported", actor="web")
        assert len(captured) == 1
        etype, payload = captured[0]
        assert etype == "ai.action"
        assert payload == {"action": "ai_analyzed", "actor": "web"}

    def test_hook_error_does_not_break_caller(self, db: CaseDB):
        """Hook nesmí rozbít kritickou cestu (defenzivní try/except)."""

        def boom(_etype: str, _payload: dict) -> None:
            raise RuntimeError("hook boom")

        db.on_event = boom
        ts = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
        event_id = db.add_timeline_event(source_id="s1", ts_utc=ts, event_type="file")
        assert isinstance(event_id, str) and event_id

    def test_no_hook_is_noop(self, db: CaseDB):
        """Bez nastaveného hooku se nic neděje (CLI režim)."""
        assert db.on_event is None
        ts = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
        event_id = db.add_timeline_event(source_id="s1", ts_utc=ts, event_type="file")
        assert isinstance(event_id, str) and event_id


class TestLiveEventBus:
    def test_publish_subscribe_roundtrip(self):
        bus = LiveEventBus(maxsize=8)
        topic = case_topic("c1")
        q = bus.subscribe(topic)
        n = bus.publish(topic, {"type": "x", "i": 1})
        assert n == 1
        ev = q.get_nowait()
        assert ev["type"] == "x"

    def test_publish_without_subscribers_is_noop(self):
        bus = LiveEventBus(maxsize=8)
        assert bus.publish(case_topic("c1"), {"type": "x"}) == 0

    def test_slow_consumer_drops_oldest_not_blocks(self):
        bus = LiveEventBus(maxsize=4)
        topic = case_topic("c2")
        q = bus.subscribe(topic)
        t0 = time.perf_counter()
        for i in range(10):  # bez blokujícího put by se tu viselo
            bus.publish(topic, {"type": "x", "i": i})
        assert time.perf_counter() - t0 < 2.0
        assert q.qsize() == 4
        assert bus.dropped_total == 6
        oldest = q.get_nowait()
        newest_i = -1
        for _ in range(3):
            newest_i = q.get_nowait()["i"]
        assert oldest["i"] == 6 and newest_i == 9

    def test_unsubscribe_is_idempotent(self):
        bus = LiveEventBus(maxsize=8)
        topic = case_topic("c3")
        q = bus.subscribe(topic)
        assert bus.subscriber_count == 1
        bus.unsubscribe(topic, q)
        assert bus.subscriber_count == 0
        bus.unsubscribe(topic, q)  # druhýkrát — bez chyby
        assert bus.subscriber_count == 0

    def test_topics_lists_only_active(self):
        bus = LiveEventBus(maxsize=8)
        topic = case_topic("c4")
        q = bus.subscribe(topic)
        assert bus.topics() == [topic]
        bus.unsubscribe(topic, q)
        assert bus.topics() == []
