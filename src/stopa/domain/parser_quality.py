"""P1-1 — Parser Quality Framework (jádro): quality kategorie a pokrytí.

Čistá logika bez I/O: vstupem je zdrojový text testovacích souborů (čte data
vrstva) a záznamy C3 registry. Konvence quality markeru — řádek v testovacím
souboru::

    # quality: positive negative tz encoding

deklaruje, které ze 8 standardních kategorií (ROADMAP_2_1.md P1-1:
pozitivní/negativní/hraniční/poškozené vstupy, časové pásmo/kódování/locale,
limitní velikosti) soubor pokrývá. Pokrytí parseru = unie markerů všech
deklarovaných testovacích souborů; chybějící kategorie = viditelný dluh
(gate ``stopa parser-quality``).

Sémantika chyb: typový nesoulad → ``TypeError``, semantická chyba → ``ValueError``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

#: 8 standardních quality kategorií (kanonické pořadí = pořadí ve reportu).
QUALITY_CATEGORIES: tuple[str, ...] = (
    "positive",
    "negative",
    "boundary",
    "corrupted",
    "tz",
    "encoding",
    "locale",
    "size",
)

_MARKER_RE = re.compile(r"^\s*#\s*quality\s*:\s*([A-Za-z][A-Za-z0-9 _-]*)\s*$")


def parse_quality_markers(source: str | None) -> frozenset[str]:
    """Extrahuje deklarovné quality kategorie ze zdrojového textu testů.

    Více řádků ``# quality:`` je povoleno (unie). Neznámé jméno kategorie →
    ``ValueError`` (fail-fast — překlep v markru se netají). Prázdný/None vstup
    → prázdná množina (žádná I/O zde, text dodává data vrstva).
    """
    if source is None:
        return frozenset()
    if not isinstance(source, str):
        raise TypeError(f"source musí být str, got {type(source).__name__}")
    found: set[str] = set()
    for line in source.splitlines():
        m = _MARKER_RE.match(line)
        if not m:
            continue
        for name in m.group(1).split():
            if name not in QUALITY_CATEGORIES:
                raise ValueError(f"neznámá quality kategorie {name!r} (řádek: {line.strip()!r})")
            found.add(name)
    return frozenset(found)


@dataclass(frozen=True)
class QualityProfile:
    """Quality profil jednoho parseru (deterministické, JSON-připravené pole)."""

    parser_id: str
    covered: tuple[str, ...]  # v pořadí QUALITY_CATEGORIES
    missing: tuple[str, ...]
    test_files: int = 0

    @property
    def complete(self) -> bool:
        return not self.missing and self.test_files > 0


def build_quality_profile(
    parser_id: str, markers_by_file: Mapping[str, frozenset[str]]
) -> QualityProfile:
    """Profil pokrytí jednoho parseru z per-file množin markerů.

    Unie všech deklarovaných testovacích souborů; soubor bez markerů = běžný
    test (žádný quality claim). Prázdné ``markers_by_file`` → nulové pokrytí
    (viditelný dluh, ne chyba).
    """
    if not isinstance(parser_id, str) or not parser_id:
        raise TypeError("parser_id musí být neprázdný str")
    union: set[str] = set()
    for markers in markers_by_file.values():
        union |= set(markers)
    covered = tuple(c for c in QUALITY_CATEGORIES if c in union)
    missing = tuple(c for c in QUALITY_CATEGORIES if c not in union)
    return QualityProfile(
        parser_id=parser_id, covered=covered, missing=missing, test_files=len(markers_by_file)
    )


def quality_report(profiles: Iterable[QualityProfile]) -> dict:
    """JSON-serializovatelný kontrakt reportu (CLI + budoucí Web/Assurance Center).

    Deterministický: parsery seřazené podle parser_id; ``coverage_pct`` = podíl
    plně pokrytých parserů na 1. desetinné místo. Prázdný vstup → ``ValueError``.
    """
    rows = list(profiles)
    if not rows:
        raise ValueError("prázdná množina profilů")
    for p in rows:
        if not isinstance(p, QualityProfile):
            raise TypeError(f"očekáván QualityProfile, got {type(p).__name__}")
    ordered = sorted(rows, key=lambda p: p.parser_id)
    complete_count = sum(1 for p in ordered if p.complete)
    return {
        "count": len(ordered),
        "quality_complete": complete_count,
        "coverage_pct": round(100.0 * complete_count / len(ordered), 1),
        "categories": list(QUALITY_CATEGORIES),
        "parsers": [
            {
                "parser_id": p.parser_id,
                "covered": list(p.covered),
                "missing": list(p.missing),
                "test_files": p.test_files,
            }
            for p in ordered
        ],
    }
