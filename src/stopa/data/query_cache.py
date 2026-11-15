"""F2.5 — Cache vrstva pro opakované operace nad case DB.

LRU eviction + TTL per query type, thread-safe (RLock), procesní instance
sdílená všemi CaseDB instancemi téhož souboru (web GUI: per-request
connection; CLI: jednorázový běh). Cache se tak projeví přesně tam, kde
dochází k opakování — re-render Entity Graph v GUI, opakované FTS dotazy
z Cmd+K historie, AI nl_search nad stejným případem.

Cacheované operace (op_type):
- ``fts``          — :meth:`CaseDB.search` (FTS5 + metadata filtry)
- ``entities``     — :meth:`CaseDB.list_entities` (entity resolution; vstup
                     pro merge-candidates a Entity Graph GUI)
- ``correlations`` — :meth:`CaseDB.list_correlations` (hrana grafu pro
                     Entity Graph GUI)

Invalidace je explicitní na mutačních bodech CaseDB facade (upsert_file,
artifact/entity/correlation upserty, delete_case) → O(1) přes reverzní
index po scope. TTL slouží jako bezpečnostní síť proti přehlédnutému
mutačnímu bodu (max stálost = TTL daného typu).

Scope = ``os.path.realpath`` case DB souboru — jednoznačná identita souboru
nezávisle na relativních/absolutních cestách a symlinkách; žádné
křížové kontaminace mezi případy.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import TypeVar, cast

# TTL per query type [s]; None = bez expirace (jen LRU eviction)
DEFAULT_TTLS: dict[str, float | None] = {
    "fts": 300.0,            # FTS dotazy — 5 min
    "entities": 600.0,       # entity resolution — 10 min
    "correlations": 600.0,   # graf (propojení) — 10 min
}

DEFAULT_MAXSIZE = 256

# unit separator — v op_type/scope/parametrech prakticky nevyskytuje se
_SEP = "\x1f"

T = TypeVar("T")


class QueryCache:
    """Thread-safe LRU cache s TTL per query type.

    Klíčová struktura: ``{op_type}{SEP}{scope}{SEP}{digest}``, kde digest je
    SHA-256 normalizovaných parametrů dotazu (query, source_id, limit, …).
    Hodnota nesmí být ``None`` (cacheovatelné výsledky jsou listy; prázdný
    výsledek ``[]`` se cacheuje — je legitimním opakovaným výsledkem).
    """

    def __init__(
        self,
        maxsize: int = DEFAULT_MAXSIZE,
        ttls: dict[str, float | None] | None = None,
    ) -> None:
        self.maxsize = maxsize
        self.ttls = {**DEFAULT_TTLS, **(ttls or {})}
        # key → (value, expires_at|None); pořadí = LRU (nejstarší vpředu)
        self._data: OrderedDict[str, tuple[object, float | None]] = OrderedDict()
        # scope → klíče (reverzní index pro O(1) invalidaci)
        self._by_scope: dict[str, set[str]] = {}
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0

    # ── klíče ────────────────────────────────────────────────
    @staticmethod
    def make_key(op_type: str, scope: str, *parts: object) -> str:
        """Digest parametrů dotazu (SHA-256 normalizovaného řetězce)."""
        raw = _SEP.join([op_type, scope] + [str(p) for p in parts])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def _full_key(cls, op_type: str, scope: str, *parts: object) -> str:
        return f"{op_type}{_SEP}{scope}{_SEP}{cls.make_key(op_type, scope, *parts)}"

    # ── interní (volat pod zamykáním) ────────────────────────
    def _remove_locked(self, key: str) -> None:
        self._data.pop(key, None)
        seg = key.split(_SEP, 2)
        if len(seg) == 3:
            sset = self._by_scope.get(seg[1])
            if sset is not None:
                sset.discard(key)
                if not sset:
                    del self._by_scope[seg[1]]

    def _evict_locked(self) -> None:
        while len(self._data) > self.maxsize:
            old_key = next(iter(self._data))  # nejstarší (LRU)
            self._remove_locked(old_key)

    # ── core API ─────────────────────────────────────────────
    def get(self, op_type: str, scope: str, *parts: object) -> T | None:
        """Vrací cacheovaný výsledek nebo ``None`` (miss / expirováno)."""
        key = self._full_key(op_type, scope, *parts)
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return None
            value, expires_at = entry
            if expires_at is not None and now >= expires_at:
                self._remove_locked(key)
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return cast("T", value)

    def set(self, op_type: str, scope: str, *parts: object, value: object = ...) -> None:
        """Uloží výsledek s TTL daného typu (LRU update/eviction)."""
        key = self._full_key(op_type, scope, *parts)
        ttl = self.ttls.get(op_type)
        expires_at = time.monotonic() + ttl if ttl is not None else None
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (value, expires_at)
            self._by_scope.setdefault(scope, set()).add(key)
            self._evict_locked()

    def get_or_set(
        self, op_type: str, scope: str, compute: Callable[[], T], *parts: object
    ) -> T:
        """Cacheovaný výsledek, jinak výpočet přes ``compute`` + uložení.

        Výjimka z ``compute`` se propaguje (nic se nenechává).
        """
        cached = self.get(op_type, scope, *parts)
        if cached is not None:
            return cached
        result = compute()
        self.set(op_type, scope, *parts, value=result)
        return result

    def invalidate(self, scope: str | None = None) -> int:
        """Odebere záznamy jednoho case souboru (scope); ``None`` = celý cache."""
        with self._lock:
            if scope is None:
                n = len(self._data)
                self._data.clear()
                self._by_scope.clear()
                return n
            keys = self._by_scope.pop(scope, set())
            for k in keys:
                self._data.pop(k, None)
            return len(keys)

    def stats(self) -> dict[str, object]:
        """Hit/miss statistika + aktuální velikost (diagnostika / AK hit ratio)."""
        with self._lock:
            total = self.hits + self.misses
            return {
                "hits": self.hits,
                "misses": self.misses,
                "size": len(self._data),
                "maxsize": self.maxsize,
                "hit_ratio": round(self.hits / total, 4) if total else None,
            }

    def reset_stats(self) -> None:
        """Reset počítadel hit/miss (záznamy zůstávají)."""
        with self._lock:
            self.hits = 0
            self.misses = 0


# Procesní instance sdílená všemi CaseDB instancemi téhož souboru.
PROCESS_CACHE = QueryCache()
