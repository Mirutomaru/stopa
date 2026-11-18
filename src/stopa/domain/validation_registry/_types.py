"""Typy validačního rejstříku parserů (P1-4 vlna E — rozklad validation_registry.py).

``ParserValidation`` — validační záznam jednoho parseru (C3 zadání §4.2);
``RegistryError`` — nesoulad registry a pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParserValidation:
    """Validační záznam jednoho parseru (C3 zadání §4.2)."""

    parser_id: str  # např. "win_prefetch" — klíč v pipeline extraktorech
    version: str  # synchronizováno s pipeline (ověřeno build_registry)
    formats: tuple[str, ...]  # podporované formáty/varianty
    limitations: tuple[str, ...] = ()  # známá omezení parseru
    reference_dataset: str | None = None  # cesta do tests/reference_datasets/
    expected_results: dict = field(default_factory=dict)  # očekáv. počty na datasetu
    test_files: tuple[str, ...] = ()  # testové soubory pokrývající parser


class RegistryError(Exception):
    """Nesoulad registry a pipeline (chybějící záznam / rozdílná verze)."""
