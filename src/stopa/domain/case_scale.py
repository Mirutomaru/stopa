"""B10 — Klasifikace velikosti případu (strategie pro velké případy).

Čistá doménová vrstva bez I/O: prahy + doporučené údržbové postupy. Data vrstva
(``FilesFacadeMixin.case_scale()``) dodává cross-table statistiku; CLI ``case scale``
výsledek prezentuje a volitelně spustí FTS REBUILD (F-1/F-2 backlogu).

Příslušnost: doména = deterministická klasifikace ze statistik; disk I/O nikdy
ne sem. BC: nový modul — žádná změna existujících API.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── B10 prahy „velkého případu“ (stovky GB = tisíce souborů × GB) ────────────
LARGE_FILES_ROWS: int = 500_000        # metadata řádky v `files`
LARGE_TOTAL_BYTES: int = 100 * 2**30   # ingestovaný datový objem (100 GiB)
LARGE_ARTIFACTS_ROWS: int = 200_000    # extrahované artefakty

# Tier hranice jako podíl prahu: ≥ 1.0 → large, ≥ 0.1 → medium, jinak small.
_MEDIUM_RATIO: float = 0.1

TIER_SMALL = "small"
TIER_MEDIUM = "medium"
TIER_LARGE = "large"

# ── Doporučené údržbové postupy (CZ; CLI je vypíše, neinterpretuje) ──────────
PROC_FTS_REBUILD = (
    "Přestavět FTS5 indexy: stopa case scale <case_id> --rebuild-fts"
    "(idempotentní REBUILD files_fts + artifacts_fts)"
)
PROC_VACUUM = (
    "Po údržbě/ archivaci spustit VACUUM na case kontejneru"
    " (rekompakce volných stránek; ruční krok — mění DB soubor)"
)
PROC_WAL = (
    "Při ingestu velmi velkého zdroje zvážit PRAGMA journal_mode=WAL pro case DB"
    " (opt-in; výchozí DELETE mode drží portabilitu kontejneru bez -wal/-shm)"
)


@dataclass(frozen=True)
class CaseScaleProfile:
    """Výsledek klasifikace — tier + doporučené údržbové postupy.

    ``procedures`` je nula (small), jen FTS REBUILD (medium) nebo FTS REBUILD +
    VACUUM + WAL poznámka (large). Seznam roste s tierem; pořadí je stabilní
    (determinismus — testy porovnávají tuple byte-identicky).
    """

    tier: str
    files_rows: int
    total_bytes: int
    artifacts_rows: int
    procedures: tuple[str, ...]


def _max_ratio(files_rows: int, total_bytes: int, artifacts_rows: int) -> float:
    """Nejvyšší podíl prahu napříč všemi třemi metrikami (0.0 až ∞)."""
    ratios = (
        files_rows / LARGE_FILES_ROWS,
        total_bytes / LARGE_TOTAL_BYTES,
        artifacts_rows / LARGE_ARTIFACTS_ROWS,
    )
    return max(ratios)


def classify_case_size(
    files_rows: int,
    total_bytes: int,
    artifacts_rows: int,
) -> CaseScaleProfile:
    """Klasifikuje případ podle velikosti (čistá funkce — deterministická).

    tier=large pokud LOKÁLNĚ jakákoli metrika dosáhne LARGE_* prahu; medium
    pokud dosáhne 1/10 prahu; jinak small. Postupy rostou s tierem.

    Raises:
        ValueError: semantická chyba — záporná hodnota metriky (např. řádky < 0).
        TypeError: typová chyba — ne-celková hodnota metriky.
    """
    for name, value in (
        ("files_rows", files_rows),
        ("total_bytes", total_bytes),
        ("artifacts_rows", artifacts_rows),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} musí být int, dostal {type(value).__name__}")
        if value < 0:
            raise ValueError(f"{name} nesmí být záporné (dostalo {value})")

    ratio = _max_ratio(files_rows, total_bytes, artifacts_rows)
    if ratio >= 1.0:
        tier = TIER_LARGE
        procedures = (PROC_FTS_REBUILD, PROC_VACUUM, PROC_WAL)
    elif ratio >= _MEDIUM_RATIO:
        tier = TIER_MEDIUM
        procedures = (PROC_FTS_REBUILD,)
    else:
        tier = TIER_SMALL
        procedures = ()

    return CaseScaleProfile(
        tier=tier,
        files_rows=files_rows,
        total_bytes=total_bytes,
        artifacts_rows=artifacts_rows,
        procedures=procedures,
    )
