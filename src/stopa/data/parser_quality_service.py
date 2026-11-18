"""P1-1 — Parser Quality Framework: data service (I/O vrstva).

Načítá testovací soubory deklarované v C3 registry a předává je čisté doméně
(``domain.parser_quality``). Sdílené testovací soubory se parsuji jen jednou
(cache) — stejný pattern jako P0-4 parser status. Nevyžaduje case DB.
"""

from __future__ import annotations

from pathlib import Path


def build_parser_quality_report(anchor: Path | None = None) -> dict:
    """Report quality pokrytí všech registrovaných parserů (deterministický).

    ``anchor`` = kořen projektu s adresářem ``tests/`` (default: auto-detekce,
    fallback CWD — viz P0-4 ``_repo_anchor``). Chybějící deklarovaný testovací
    soubor se tolerance jako prázdný text (OSError → ∅ markerů), ne výjimka.
    """
    from stopa.data.parser_status_service import _repo_anchor  # noqa: WPS437 — sdílený helper
    from stopa.domain.parser_quality import (
        build_quality_profile,
        parse_quality_markers,
        quality_report,
    )
    from stopa.domain.validation_registry import PARSER_VALIDATIONS

    root = anchor or _repo_anchor()
    cache: dict[str, frozenset[str]] = {}
    profiles = []
    for parser_id in sorted(PARSER_VALIDATIONS):
        rec = PARSER_VALIDATIONS[parser_id]
        markers_by_file: dict[str, frozenset[str]] = {}
        for rel in rec.test_files:
            if rel not in cache:
                try:
                    text = (root / rel).read_text(encoding="utf-8")
                except OSError:
                    text = ""
                cache[rel] = parse_quality_markers(text)
            markers_by_file[rel] = cache[rel]
        profiles.append(build_quality_profile(parser_id, markers_by_file))
    return quality_report(profiles)
