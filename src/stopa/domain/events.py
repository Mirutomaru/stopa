"""F4.2 — LiveEventBus: in-process pub/sub pro real-time události (WebSocket).

Design (single-process model STOPA, bez Redis):
- **topic** = ``case:{case_id}`` — každý klient se přihlásí k tématu svého případu;
- **publish** je nablokující: pomalý konzument nedrží pipeline (omezená fronta,
  při přetečení se události počítají do ``dropped``);
- thread-safe (publikují worker vlákna ingestu/pipeline, čte async WS handler);
- graceful degradation = bez přihlášeného klienta se nic neděje (REST polluje dál).

Událost je plain dict: ``{"type": str, "case_id": str | None, "ts": iso8601, ...}``.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field


@dataclass
class LiveEventBus:
    """Pub/sub buse s omezenými frontami per-subscriber (F4.2).

    :param maxsize: kapacita fronty jednoho subscribera; pomalý klient
        ztrácí nejstarší události (počet v ``dropped``) místo toho, aby
        blokoval produkující vlákno.
    """

    maxsize: int = 256
    _subs: dict[str, list[queue.Queue]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    dropped_total: int = 0
    published_total: int = 0

    def subscribe(self, topic: str) -> queue.Queue:
        """Nová fronta pro téma; vrací ji (volající si ji drží a čte)."""
        q: queue.Queue = queue.Queue(maxsize=self.maxsize)
        with self._lock:
            self._subs.setdefault(topic, []).append(q)
        return q

    def unsubscribe(self, topic: str, q: queue.Queue) -> None:
        """Odhlásí frontu (idempotentní; volá se v finally WS handleru)."""
        with self._lock:
            subs = self._subs.get(topic)
            if subs and q in subs:
                subs.remove(q)
            if subs is not None and not subs:
                del self._subs[topic]

    def publish(self, topic: str, event: dict) -> int:
        """Rozdá událost všem subscriberům tématu; vrací jejich počet.

        Nablokující (``put_nowait`` + drop nejstaršího u plné fronty).
        """
        with self._lock:
            subs = list(self._subs.get(topic, ()))
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                # pomalý konzument — vyhodit nejstarší, vložit novou
                try:
                    q.get_nowait()
                    self.dropped_total += 1
                    q.put_nowait(event)
                except (queue.Empty, queue.Full):
                    self.dropped_total += 1
        self.published_total += len(subs) if subs else 0
        return len(subs)

    @property
    def subscriber_count(self) -> int:
        """Počet aktivních front napříč všemi tématy (diagnostika/testy)."""
        with self._lock:
            return sum(len(v) for v in self._subs.values())

    def topics(self) -> list[str]:
        with self._lock:
            return [t for t, subs in self._subs.items() if subs]


def case_topic(case_id: str) -> str:
    """Kanonický název tématu pro případ."""
    return f"case:{case_id}"
