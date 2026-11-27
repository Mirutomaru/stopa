"""P0-4 validation lab — per-parser validační status (čistá logika).

Doplňuje C3 registry (`validation_registry.build_registry()`) o metriky
pokrytí testy a explicitní validační status pro každý parser. I/O (čtení
testovacích souborů) je injektováno callbackem ``file_loader`` z data/CLI vrstvy,
aby doména zůstala bez I/O (viz `data/parser_status_service.py`).

Pravidlo statusu:
    validated   ⟺ alespoň jeden deklarovaný test soubor existuje a obsahuje ≥ 1
                  testovací funkci.
    unvalidated ⟺ žádné test_files, všechny chybí, nebo jen prázdné soubory.

STP-074 (design §6 krok 8 / §7) — aditivní stav:
    differentially_validated ⟺ validated + pincovaný reference dataset
                  (§6 kroky 7–8 proběhly nezávislou cestou). Implikuje
                  ``validated``; bez datasetu zůstává ``validated``. Report klíč
                  ``validated`` počítá oba stavy (aditivita), nový klíč
                  ``differentially_validated`` je explicitní seznam ID.

``direct_tests`` = počet testovacích funkcí, jejichž název TĚLO odkazuje na
parser_id (spolehlivá přímá atribuce); ``total_tests`` = celkový počet testů v
deklarovaných souborech (sdílené soubory se počítají pro každý parser — kontext).
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

VALIDATED = "validated"
UNVALIDATED = "unvalidated"
# STP-074 (design §6 krok 8, §7): validated parser s pincovaným reference datasetem
# prošel diferenciálním testováním nezávislou cestou — aditivní stav (implikuje
# VALIDATED), bez přepisování hodnotového sémantika existujících reportů.
DIFFERENTIALLY_VALIDATED = "differentially_validated"

if TYPE_CHECKING:  # jen pro anotace — runtime import by byl zbytečný (čistota vrstev)
    from stopa.domain.validation_registry import ParserValidation


@dataclass(frozen=True)
class ParserStatusRecord:
    """Per-parser validační záznam (P0-4)."""

    parser_id: str
    version: str
    formats_count: int
    limitations_count: int
    test_files: tuple[str, ...]
    total_tests: int
    direct_tests: int
    reference_dataset: str | None
    validation_status: str  # validated / unvalidated / differentially_validated (STP-074)
    last_validated_ts: str | None = None  # ISO UTC; metadata z fs (viz docstring)


def _test_functions(source: str) -> list[tuple[str, str]]:
    """(název, rozepsaný zdroj) pro všechny testovací funkce; SyntaxError → []."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            try:
                un = ast.unparse(node)
            except Exception:  # noqa: BLE001 — py<3.9 fallback — jen název
                un = node.name
            out.append((node.name, un))
    return out


def _counts(functions: list[tuple[str, str]], parser_id: str) -> tuple[int, int]:
    direct = sum(1 for name, src in functions if parser_id in name or parser_id in src)
    return (len(functions), direct)


def parse_test_counts(source: str, parser_id: str) -> tuple[int, int]:
    """Čistá funkce nad zdrojem: ``(total_tests, direct_tests)``.

    SyntaxError → ``(0, 0)`` (soubor se počítá jako "nenačten" volajícím).
    """
    return _counts(_test_functions(source), parser_id)


def build_parser_status(
    registry: Mapping[str, ParserValidation],
    file_loader: Callable[[str], str | None],
    stamp_loader: Callable[[str], str | None] | None = None,
) -> list[ParserStatusRecord]:
    """Agregace per-parser statusu nad C3 registry.

    ``file_loader(rel_path)`` → zdrojový kód testovacího souboru nebo ``None``
    (chybí/nečitelný). Sdílené testovací soubory se parší jen jednou (cache).

    ``stamp_loader(rel_path)`` → ISO UTC timestamp posledního dotčení souboru
    (metadata pro ``last_validated_ts``) nebo ``None``; volitelně — bez něj je
    pole None. Doména zůstává čistá: oba callbacky přichází z data vrstvy.
    """
    cache: dict[str, list[tuple[str, str]] | None] = {}

    def functions_for(rel_path: str) -> list[tuple[str, str]] | None:
        if rel_path not in cache:  # hit i miss — loader se volá max jednou na soubor
            src = file_loader(rel_path)
            cache[rel_path] = _test_functions(src) if src is not None else None
        return cache[rel_path]

    out: list[ParserStatusRecord] = []
    for pid in sorted(registry):
        p = registry[pid]  # ParserValidation (C3)
        total = 0
        direct = 0
        stamps: list[str] = []
        files_found = False
        for rel in p.test_files:
            funcs = functions_for(rel)
            if funcs is None:
                continue
            files_found = True
            t, d = _counts(funcs, pid)
            total += t
            direct += d
            if stamp_loader is not None:
                st = stamp_loader(rel)
                if st:
                    stamps.append(st)
        base_status = VALIDATED if (files_found and total > 0) else UNVALIDATED
        last_ts = max(stamps) if (base_status == VALIDATED and stamps) else None
        # STP-074 (§6 krok 8): validated + pincovaný reference dataset → aditivní stav.
        status = (
            DIFFERENTIALLY_VALIDATED
            if base_status == VALIDATED and p.reference_dataset is not None
            else base_status
        )
        out.append(
            ParserStatusRecord(
                parser_id=pid,
                version=p.version,
                formats_count=len(p.formats),
                limitations_count=len(p.limitations),
                test_files=tuple(p.test_files),
                total_tests=total,
                direct_tests=direct,
                reference_dataset=p.reference_dataset,
                validation_status=status,
                last_validated_ts=last_ts,
            )
        )
    return out


def parser_status_report(records: list[ParserStatusRecord]) -> dict:
    """JSON-serializovatelný report + souhrn (CLI ``parser-status`` / Web).

    STP-074: klíč ``validated`` je aditivní — počítá i stavy s vyšší důvěryhodností
    (``differentially_validated``); nový explicitní klíč ``differentially_validated``
    obsahuje jejich ID. Kompatibilita starých reportů: stávající klíče nemění význam
    směrem dolů (validovaný parser zůstává v ``validated``).
    """
    if not records:
        return {
            "count": 0,
            "validated": 0,
            "unvalidated_count": 0,
            "unvalidated": [],
            "differentially_validated": [],
            "dataset_coverage_pct": 0.0,
            "parsers": [],
        }
    validated = sum(
        1 for r in records if r.validation_status in (VALIDATED, DIFFERENTIALLY_VALIDATED)
    )
    unvalidated = sorted(r.parser_id for r in records if r.validation_status == UNVALIDATED)
    diff_validated = sorted(
        r.parser_id for r in records if r.validation_status == DIFFERENTIALLY_VALIDATED
    )
    with_dataset = sum(1 for r in records if r.reference_dataset)
    return {
        "count": len(records),
        "validated": validated,
        "unvalidated_count": len(unvalidated),
        "unvalidated": unvalidated,
        "differentially_validated": diff_validated,  # STP-074 — aditivní klíč
        "dataset_coverage_pct": round(100.0 * with_dataset / len(records), 1),
        "parsers": [asdict(r) for r in records],
    }
