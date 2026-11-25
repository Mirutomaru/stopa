"""B12 — Práh přechodu FTS5 → dedikovaný search engine.

Čistá doménová vrstva bez I/O: výkonnostní prahy search workloadu + tierová
klasifikace s doporučenými postupy. Data vrstva (``FilesFacadeMixin.
search_workload()``) dodává read-only statistiku; CLI ``case scale`` rozšíří
report o sekci ``search`` a postupy prezentuje (F-1..F-5 backlogu).

Prahová kritéria (viz PLAN_BACKLOG B12):
- objem indexovaných řádků (files/artifacts) — bm25 + REBUILD náklady;
- složené dotazy — ``graph_edges`` hranice O(A·E) stěny relací BFS v Pythonu;
- faceting/agregace a jazyková analýza (diakritika/stemming) jsou funkční
  triggery, které tier doplní o postupy na vyhodnocení rozšiřující cesty.

Příslušnost: doména = deterministická klasifikace ze statistik; disk I/O nikdy
ne sem. BC: nový modul — žádná změna existujících API.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── B12 prahy search workloadu ───────────────────────────────────────────────
SEARCH_FILES_ROWS: int = 500_000    # indexované řádky files_fts (konzistentní s B10)
SEARCH_ARTIFACTS_ROWS: int = 200_000  # řádky artifacts_fts — details_json tokenizuje nejvíce
GRAPH_EDGES_ROWS: int = 50_000     # F-2 stěna: _expand_relations načte vše + BFS per hit (O(A·E))

# Tier hranice jako podíl prahu: ≥ 1.0 → engine_candidate, ≥ 0.1 → fts_watch.
_WATCH_RATIO: float = 0.1

TIER_FTS_OK = "fts_ok"
TIER_FTS_WATCH = "fts_watch"
TIER_ENGINE_CANDIDATE = "engine_candidate"

# ── Doporučené postupy (CZ; CLI je vypíše, neinterpretuje) ───────────────────
PROC_SEARCH_REBUILD = (
    "Před/po ingestu přestavět FTS5 indexy: stopa case scale <case_id> --rebuild-fts"
    " (idempotentní REBUILD files_fts + artifacts_fts)"
)
PROC_REL_BATCHING = (
    "Relační dotazy (--rel-depth): dávkovat zásahy — expanze relací je O(A·E) v Pythonu"
    " (_expand_relations načte celé graph_edges per dotaz a BFS per hit artifact)"
)
PROC_ENGINE_EVAL = (
    "Vyhodnotit B12 rozšiřující cestu: koloceovaný search engine v case diru"
    " (sidecar index rekonstruovatelný ze zdrojových tabulek; FTS5 zůstává defaultem)"
)


@dataclass(frozen=True)
class SearchWorkloadProfile:
    """Výsledek klasifikace search workloadu — tier + doporučené postupy.

    ``procedures`` je nula (fts_ok), jen REBUILD plán (fts_watch) nebo REBUILD +
    dávkování relací + vyhodnocení engine (engine_candidate). Seznam roste s
    tierem; pořadí je stabilní (determinismus — testy porovnávají tuple
    byte-identicky).
    """

    tier: str
    files_rows: int
    artifacts_rows: int
    graph_edges_rows: int
    procedures: tuple[str, ...]


def _max_ratio(files_rows: int, artifacts_rows: int, graph_edges_rows: int) -> float:
    """Nejvyšší podíl prahu napříč všemi třemi metrikami (0.0 až ∞)."""
    ratios = (
        files_rows / SEARCH_FILES_ROWS,
        artifacts_rows / SEARCH_ARTIFACTS_ROWS,
        graph_edges_rows / GRAPH_EDGES_ROWS,
    )
    return max(ratios)


def classify_search_workload(
    files_rows: int,
    artifacts_rows: int,
    graph_edges_rows: int,
) -> SearchWorkloadProfile:
    """Klasifikuje search workload podle objemu indexů a relační stěny.

    tier=engine_candidate pokud LOKÁLNĚ jakákoli metrika dosáhne prahu; fts_watch
    pokud dosáhne 1/10 prahu; jinak fts_ok. Postupy rostou s tierem.

    Raises:
        ValueError: semantická chyba — záporná hodnota metriky (např. řádky < 0).
        TypeError: typová chyba — ne-celková hodnota metriky (bool explicitně odmítnut).
    """
    for name, value in (
        ("files_rows", files_rows),
        ("artifacts_rows", artifacts_rows),
        ("graph_edges_rows", graph_edges_rows),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} musí být int, dostal {type(value).__name__}")
        if value < 0:
            raise ValueError(f"{name} nesmí být záporné (dostalo {value})")

    ratio = _max_ratio(files_rows, artifacts_rows, graph_edges_rows)
    if ratio >= 1.0:
        tier = TIER_ENGINE_CANDIDATE
        procedures = (PROC_SEARCH_REBUILD, PROC_REL_BATCHING, PROC_ENGINE_EVAL)
    elif ratio >= _WATCH_RATIO:
        tier = TIER_FTS_WATCH
        procedures = (PROC_SEARCH_REBUILD,)
    else:
        tier = TIER_FTS_OK
        procedures = ()

    return SearchWorkloadProfile(
        tier=tier,
        files_rows=files_rows,
        artifacts_rows=artifacts_rows,
        graph_edges_rows=graph_edges_rows,
        procedures=procedures,
    )


__all__ = [
    "GRAPH_EDGES_ROWS",
    "PROC_ENGINE_EVAL",
    "PROC_REL_BATCHING",
    "PROC_SEARCH_REBUILD",
    "SEARCH_ARTIFACTS_ROWS",
    "SEARCH_FILES_ROWS",
    "TIER_ENGINE_CANDIDATE",
    "TIER_FTS_OK",
    "TIER_FTS_WATCH",
    "SearchWorkloadProfile",
    "classify_search_workload",
]
