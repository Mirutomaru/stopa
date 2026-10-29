"""FTK „Advanced De-duplication Analysis“ — detekce duplicit podle hash.

ČISTÁ logika: dostane sekvenci (hash, rel_path) v pořadí zpracování,
vrátí mapu index → index prvního výskytu stejného hash. První výskyt je
„originál“, pozdější jsou duplikáty (FTK chování: hide duplicates).
"""

from __future__ import annotations


def find_duplicates(hashes: list[str | None]) -> dict[int, int]:
    """Vrátí {pozice: pozice_prvního_výskytu} pro všechny duplicitní záznamy.

    `hashes` — hash (nebo None pokud se nepočítal) v pořadí zpracování souborů.
    Záznamy s None se mezi sebou neporovnávají (bez hash = bez důkazu).
    """
    first_seen: dict[str, int] = {}
    dups: dict[int, int] = {}
    for i, h in enumerate(hashes):
        if h is None:
            continue
        if h in first_seen:
            dups[i] = first_seen[h]
        else:
            first_seen[h] = i
    return dups


def dedupe_stats(dups: dict[int, int], sizes: list[int]) -> tuple[int, int]:
    """(počet duplicit, ušetřené bajty) — pro FTK-style processing summary."""
    saved = sum(sizes[i] for i in dups if i < len(sizes))
    return len(dups), saved


class Deduper:
    """Inkrementální deduplikátor napříč celým případem (FTK hide duplicates).

    Použití v pipeline:
      1. `seed()` — existující hash z DB (jiné zdroje / předchozí běhy)
      2. pro každý nový soubor `check_and_register(hash, rel_path)` →
         vrátí rel_path originálu pokud je to duplikát, jinak None a zaregistruje.

    První výskyt hashu v celém případu = originál; pozdější = duplikáty.
    """

    def __init__(self) -> None:
        self._first_seen: dict[str, str] = {}

    def seed(self, existing: list[tuple[str | None, str]]) -> None:
        """Naloží existující (hash, rel_path) páry — hash=None se ignoruje."""
        for h, path in existing:
            if h is not None and h not in self._first_seen:
                self._first_seen[h] = path

    def check_and_register(self, digest: str | None, rel_path: str) -> str | None:
        """Vrátí originál pokud je `digest` už v případu; jinak zaregistruje a vrátí None."""
        if digest is None:
            return None
        original = self._first_seen.get(digest)
        if original is not None and original != rel_path:
            return original
        if digest not in self._first_seen:
            self._first_seen[digest] = rel_path
        return None

    @property
    def known_hashes(self) -> int:
        return len(self._first_seen)
