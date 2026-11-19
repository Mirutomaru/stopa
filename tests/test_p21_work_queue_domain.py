"""P2-1 Wave 1 — doména work_queue: InProcessWorkQueue + CapacityBudget.

Čistá doménová sada (bez pipeline/DB): FIFO pořadí, batch take, backpressure,
graceful stop s dotáhnutím in-flight, kapacitní rozpočet (max workerů + disk budget).
"""

from __future__ import annotations

import threading
import time

import pytest

from stopa.domain.work_queue import (
    CapacityBudget,
    InProcessWorkQueue,
    QueueStopped,
    WorkQueue,
)


class TestInProcessWorkQueueBasics:
    """Základní semantika: FIFO, batche, počítadlo, protokol."""

    def test_fifo_order_single_takes(self):
        q = InProcessWorkQueue[str]()
        for i in range(5):
            q.put(f"s{i}")
        assert [q.take_batch(1)[0] for _ in range(5)] == ["s0", "s1", "s2", "s3", "s4"]

    def test_take_batch_up_to_max_items(self):
        q = InProcessWorkQueue[int]()
        for i in range(7):
            q.put(i)
        first = q.take_batch(3)
        assert first == [0, 1, 2]
        second = q.take_batch(5)  # zbývá jen 4 — batch kratší než max_items
        assert second == [3, 4, 5, 6]

    def test_pending_and_drained(self):
        q: InProcessWorkQueue[int] = InProcessWorkQueue()
        assert q.stopped is False
        for i in range(3):
            q.put(i)
        assert q.pending == 3
        assert not q.drained()  # ještě nemožná — nestopovaná fronta není drainovaná
        q.stop()
        assert q.take_batch(10) == [0, 1, 2]
        assert q.pending == 0
        assert q.drained()

    def test_protocol_conformance(self):
        # runtime_checkable Protocol — stačí přítomnost metod
        assert isinstance(InProcessWorkQueue[int](), WorkQueue)

    def test_negative_maxsize_rejected(self):
        with pytest.raises(ValueError, match="maxsize"):
            InProcessWorkQueue(maxsize=-1)

    def test_take_batch_zero_rejected(self):
        q: InProcessWorkQueue[int] = InProcessWorkQueue()
        q.put(1)
        with pytest.raises(ValueError, match="max_items"):
            q.take_batch(0)

    def test_empty_queue_timeout_zero_returns_immediately(self):
        q: InProcessWorkQueue[int] = InProcessWorkQueue()
        t0 = time.monotonic()
        assert q.take_batch(1, timeout=0.05) == []
        assert time.monotonic() - t0 < 2.0  # žádné visení

    def test_empty_queue_wait_then_producer(self):
        """Worker čeká na první položku; producent ji dodá → vrácena."""
        q: InProcessWorkQueue[str] = InProcessWorkQueue()
        result: list[list[str]] = []
        done = threading.Event()

        def worker() -> None:
            result.append(q.take_batch(1))
            done.set()

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        time.sleep(0.05)  # worker je už v čekacím take_batch
        q.put("x")
        assert done.wait(timeout=2.0)
        t.join(timeout=1.0)
        assert result == [["x"]]


class TestInProcessWorkQueueBackpressure:
    """Omezená fronta = backpressure mezi producentem a workerem."""

    def test_put_blocks_when_full(self):
        q = InProcessWorkQueue[int](maxsize=1)
        q.put(0)
        blocked = threading.Event()
        put_done = threading.Event()

        def producer() -> None:
            blocked.set()  # producent se chystá na (blokující) put
            q.put(1)
            put_done.set()

        t = threading.Thread(target=producer, daemon=True)
        t.start()
        assert blocked.wait(timeout=2.0)
        time.sleep(0.05)  # producer je už uvnitř blokujícího put()
        assert not put_done.is_set(), "put do plné fronty musí blokovat (backpressure)"
        q.take_batch(1)  # worker uvolní místo
        assert put_done.wait(timeout=2.0), "po uvolnění místa se put musí dokončit"
        t.join(timeout=1.0)
        assert q.take_batch(1)[0] == 1

    def test_unbounded_queue_never_blocks(self):
        q: InProcessWorkQueue[int] = InProcessWorkQueue(maxsize=0)
        for i in range(500):
            q.put(i)
        assert q.pending == 500


class TestInProcessWorkQueueStop:
    """Graceful shutdown: stop → nová put selže, in-flight se dotáhne."""

    def test_put_after_stop_raises(self):
        q: InProcessWorkQueue[int] = InProcessWorkQueue()
        q.stop()
        with pytest.raises(QueueStopped):
            q.put(1)

    def test_take_batch_returns_empty_when_stopped_and_drained(self):
        q: InProcessWorkQueue[int] = InProcessWorkQueue()
        result: list[list[int]] = []
        done = threading.Event()

        def worker() -> None:
            # čeká neomezeně; stop+prázdná fronta → [] bez visení
            result.append(q.take_batch(1))
            done.set()

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        time.sleep(0.05)  # worker čeká na první položku
        q.stop()
        assert done.wait(timeout=2.0), "stop musí probudit čekající take_batch"
        t.join(timeout=1.0)
        assert result == [[]]

    def test_stop_drains_inflight_items(self):
        """Stop nezahazuje už odeslanou práci — in-flight se dotáhne."""
        q = InProcessWorkQueue[int](maxsize=4)
        for i in range(3):
            q.put(i)
        q.stop()
        assert q.take_batch(10) == [0, 1, 2]
        assert q.drained()


class TestCapacityBudget:
    """Kapacitní řízení: max workerů + disk budget in-flight souborů."""

    def test_unlimited_budget_admits_everything(self):
        b = CapacityBudget(max_workers=4)
        for size in (0, 1, 10**9, 2 * 10**9):
            assert b.can_admit(size)
            assert b.admit(size)
        assert b.inflight_bytes == sum([0, 1, 10**9, 2 * 10**9])

    def test_limited_budget_blocks_overrun(self):
        b = CapacityBudget(max_workers=2, disk_budget_bytes=100)
        assert b.admit(60) is True
        assert b.can_admit(50) is False  # 60+50 > 100
        assert b.admit(50) is False      # přes rozpočet — bez mutace stavu
        assert b.inflight_bytes == 60    # admit=False mění nic
        assert b.can_admit(40) is True
        assert b.admit(40) is True
        assert b.inflight_bytes == 100

    def test_release_frees_budget(self):
        b = CapacityBudget(disk_budget_bytes=100)
        assert b.admit(80)
        assert not b.can_admit(30)
        b.release(80)
        assert b.inflight_bytes == 0
        assert b.can_admit(90)

    def test_release_clamps_at_zero(self):
        """Převybitné release nesmí dát rozpočet do minusu (defenzivní)."""
        b = CapacityBudget(disk_budget_bytes=100)
        b.admit(50)
        b.release(90)
        assert b.inflight_bytes == 0

    def test_zero_budget_means_unlimited(self):
        """disk_budget_bytes=0 = vypnutý limit (původní chování F2.4)."""
        b = CapacityBudget(disk_budget_bytes=0)
        assert b.admit(10**9) is True

    def test_invalid_values_fail_closed(self):
        with pytest.raises(ValueError, match="max_workers"):
            CapacityBudget(max_workers=0)
        with pytest.raises(ValueError, match="disk_budget"):
            CapacityBudget(disk_budget_bytes=-1)
        b = CapacityBudget()
        with pytest.raises(ValueError, match="size_bytes"):
            b.admit(-5)
        with pytest.raises(ValueError, match="size_bytes"):
            b.release(-1)
