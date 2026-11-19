"""P2-1 Distribuované zpracování — abstrakce fronty úkolů (čistá doména).

Design (docs/P2_DESIGNS.md, P2-1):
- ``WorkQueue(Protocol)`` — kontrakt mezi producentem (walk zdrojů) a workerem.
  In-process implementace = aktuální stav F2.4 (default); volitelný broker
  backend jako extra ``[dist]`` nese vlastní transport, ale stejný kontrakt.
- Determinismus: DB writes zůstávají v hlavním procesu (pattern F2.4) — fronta
  jen přenáší práci; pořadí konzumace je FIFO → stejný výsledek jako single-machine.

Kapacitní řízení = max workerů + disk budget (``CapacityBudget``) + checkpointing E3
(commit_every v pipeline). Disk budget omezuje součet velikostí in-flight souborů,
tím pádem i RAM a napředběh walku před parsem.

Čistá doména: bez I/O, sítě ani procesů — jen threading pro thread-safe stav
(in-process backend běží v hlavním procesu, workerové jsou vlákna/procesy).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")


class QueueStopped(Exception):
    """Fail-closed: ``put()`` po ``stop()`` — producent už nemůže přidávat práci."""


@runtime_checkable
class WorkQueue(Protocol[T]):
    """Kontrakt fronty úkolů (P2-1).

    Producent volá ``put(item)``; worker volá ``take_batch()`` a bere batche.
    Pořadí konzumace je FIFO — determinismus originál vs. duplikát v pipeline
    závisí na tom, že se práce konzumuje v pořadí procházky zdroje.

    Semantika:
    - ``put`` blokuje, když je fronta plná (backpressure mezi walk a parsem).
    - ``stop()`` = graceful shutdown: nová ``put`` selže s :class:`QueueStopped`,
      in-flight položky se ještě konzumují; fronta je drainovaná, když
      ``pending == 0 and stopped``.
    - ``take_batch(max_items, timeout)`` čeká na první položku (timeout=None =
      neomezeně), poté sbírá až do max_items bez dalšího čekání — deterministický
      výsledek nezávislý na načasování workerů.
    """

    def put(self, item: T) -> None:
        """Přidat práci; blokuje při plné frontě (backpressure)."""
        ...

    def take_batch(self, max_items: int = 1, timeout: float | None = None) -> list[T]:
        """Vzít batch až do ``max_items`` položek; [] jen pokud stop a prázdná."""
        ...

    @property
    def pending(self) -> int:
        """Počet čekajících položek (pro backpressure/kapacitní přehled)."""
        ...

    @property
    def stopped(self) -> bool:
        """Byla fronta zastavená (graceful shutdown)."""
        ...

    def stop(self) -> None:
        """Zastavit přijímání nové práce; in-flight se dotáhne."""
        ...


@dataclass
class InProcessWorkQueue(Generic[T]):
    """In-process implementace :class:`WorkQueue` — default (aktuální stav F2.4).

    Thread-safe omezená FIFO fronta: ``maxsize`` = backpressure okno
    (0 = neomezená, ale kapacitu pak drží disk budget / max workerů). Vše běží
    v hlavním procesu — žádný transport, žádný broker.
    """

    maxsize: int = 0
    _items: deque[Any] = field(default_factory=deque, init=False)
    _cv: threading.Condition = field(default_factory=threading.Condition, init=False)
    _stopped: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.maxsize < 0:
            raise ValueError(f"maxsize musí být ne-negativní, dostal {self.maxsize}")

    # ── WorkQueue[T] ───────────────────────────────────────

    @property
    def stopped(self) -> bool:
        with self._cv:
            return self._stopped

    @property
    def pending(self) -> int:
        with self._cv:
            return len(self._items)

    def put(self, item: T) -> None:
        with self._cv:
            if self._stopped:
                raise QueueStopped("put po stop() — fronta už nepřijímá práci")
            while self.maxsize and len(self._items) >= self.maxsize:
                self._cv.wait()  # backpressure — čeká, dokud worker neuvolní místo
            self._items.append(item)
            self._cv.notify_all()

    def take_batch(self, max_items: int = 1, timeout: float | None = None) -> list[T]:
        if max_items < 1:
            raise ValueError(f"max_items musí být ≥ 1, dostal {max_items}")
        deadline: float | None = None if timeout is None else time.monotonic() + timeout
        with self._cv:
            # čekání na PRVN položku (stop+prázdná → [] bez ztráty)
            while not self._items and not self._stopped:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return []
                self._cv.wait(remaining)
            if not self._items:  # stop (nebo timeout) a nic nedorazilo — graceful []
                return []
            batch: list[T] = [self._items.popleft()]
            # doplnění do max_items — bez dalšího čekání (determinismus nezávislý na načasování)
            while len(batch) < max_items and self._items:
                batch.append(self._items.popleft())  # type: ignore[arg-type]
            # uvolnění místa v omezené frontě → probudit producent blokovaný backpressurem
            self._cv.notify_all()
        return batch

    def stop(self) -> None:
        with self._cv:
            self._stopped = True
            self._cv.notify_all()  # probudit čekající take_batch (vrátí [])

    # ── pomocné ────────────────────────────────────────────

    def drained(self) -> bool:
        """Graceful shutdown hotový: stop + vše zkonzumováno."""
        with self._cv:
            return self._stopped and not self._items


@dataclass
class CapacityBudget:
    """Kapacitní řízení (P2-1): max workerů + disk budget in-flight souborů.

    ``disk_budget_bytes`` = max součet velikostí souborů, které jsou zároveň
    in flight (odeslané workerům, ale ještě nezkonzumované do DB). None/0 =
    bez limitu (původní chování F2.4 — jen backpressure okno fronty).

    Deterministické a fail-closed: ``admit()`` s překročeným rozpočtem vrací
    False (producent čeká), ne hází výjimku — backpressure, ne chyba běhu.
    """

    max_workers: int = 1
    disk_budget_bytes: int | None = None
    _inflight_bytes: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.max_workers < 1:
            raise ValueError(f"max_workers musí být ≥ 1, dostal {self.max_workers}")
        if self.disk_budget_bytes is not None and self.disk_budget_bytes < 0:
            raise ValueError(
                f"disk_budget_bytes musí být ne-negativní, dostal {self.disk_budget_bytes}"
            )

    @property
    def inflight_bytes(self) -> int:
        return self._inflight_bytes

    def can_admit(self, size_bytes: int) -> bool:
        """Přijme rozpočet další soubor o ``size_bytes`` (bez mutace stavu)."""
        if self.disk_budget_bytes is None or self.disk_budget_bytes == 0:
            return True
        return self._inflight_bytes + size_bytes <= self.disk_budget_bytes

    def admit(self, size_bytes: int) -> bool:
        """Započítat soubor do in-flight rozpočtu; False = přes budget (čekat)."""
        if size_bytes < 0:
            raise ValueError(f"size_bytes musí být ne-negativní, dostal {size_bytes}")
        if not self.can_admit(size_bytes):
            return False
        self._inflight_bytes += size_bytes
        return True

    def release(self, size_bytes: int) -> None:
        """Uvolnit rozpočet po zkonzumování souboru do DB."""
        if size_bytes < 0:
            raise ValueError(f"size_bytes musí být ne-negativní, dostal {size_bytes}")
        self._inflight_bytes = max(0, self._inflight_bytes - size_bytes)
