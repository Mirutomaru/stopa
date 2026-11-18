"""STOPA — Parser Validation Registry (P0 Core, C3).

Deklarativní registry všech parserů: identifikátor, verze, podporované formáty,
známá omezení a referenční datasety. Zdroj pravdy pro verze je pipeline
(``ARTIFACT_EXTRACTORS`` / ``NAME_BASED_EXTRACTORS``) — registry se s ním
synchronizuje v ``build_registry()`` (každý extraktor má záznam a naopak,
verze se shodují).

Čistá logika bez I/O; verze pipeline se načítají lazy (domain → pipeline je
směr jen u konvenční funkce, ne při importu modulu).
"""

from __future__ import annotations

from dataclasses import replace

from . import _axiom_local, _chrome_cloud, _cloud_export, _core, _extras, _google_takeout, _sns
from ._types import ParserValidation, RegistryError

# P1-4 vlna E — rejstřík složen z datových modulů (pořadí = pořadí monolitu)
PARSER_VALIDATIONS: dict[str, ParserValidation] = {
    **_core._PART,
    **_axiom_local._PART,
    **_google_takeout._PART,
    **_chrome_cloud._PART,
    **_sns._PART,
    **_cloud_export._PART,
    **_extras._PART,
}


def build_registry(versions: dict[str, str] | None = None) -> dict[str, ParserValidation]:
    """Synchronizuje registry s pipeline a vrací kompletní registry.

    ``versions`` — verze parserů (výchozí: lazy import z ``stopa.pipeline``).
    Ověření: každý extraktor v pipeline má záznam v registry a naopak;
    verze se shodují. Nesoulad → :class:`RegistryError`.
    """
    if versions is None:  # lazy — domain bez tvrdé závislosti na pipeline při importu
        from stopa.pipeline import parser_versions

        versions = parser_versions()

    out: dict[str, ParserValidation] = {}
    for pid, pv in PARSER_VALIDATIONS.items():
        if pid not in versions:
            raise RegistryError(f"registry {pid!r} nemá odpovídající extraktor v pipeline")
        out[pid] = pv if pv.version else replace(pv, version=versions[pid])

    for pid, ver in versions.items():
        if pid not in PARSER_VALIDATIONS:
            raise RegistryError(f"pipeline extraktor {pid!r} nemá záznam v registry")
        elif out[pid].version != ver:
            raise RegistryError(
                f"verze parseru {pid!r}: pipeline={ver!r}, registry={out[pid].version!r}"
            )
    return out


def registry_report(registry: dict[str, ParserValidation] | None = None) -> list[dict]:
    """Shrnutí registry pro CLI/GUI — řádky s identitou a validací parserů."""
    if registry is None:
        registry = build_registry()
    return [
        {
            "parser_id": pv.parser_id,
            "version": pv.version,
            "formats": list(pv.formats),
            "limitations": list(pv.limitations),
            "reference_dataset": pv.reference_dataset,
            "test_files": list(pv.test_files),
        }
        for pv in sorted(registry.values(), key=lambda p: p.parser_id)
    ]

__all__ = [
    "PARSER_VALIDATIONS",
    "ParserValidation",
    "RegistryError",
    "build_registry",
    "registry_report",
]
