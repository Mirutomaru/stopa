"""P1-4 vlna E — zlatý povrch modulu ``stopa.domain.validation_registry``.

Kontrakt, který musí přežít rozklad god-file ``validation_registry.py``
(1242 ř., z toho 1161 ř. deklarativní rejstřík ``PARSER_VALIDATIONS``):

1. **Vlastní definice** — top-level def/class + konstanty (AST over monolitu
   nebo balíčku) byte-přesně stejná množina; jediný povolený přírůstek je
   interní assembly jméno ``_PART`` v datových modulech.
2. **Kompatibilitní povrch** — jména importovaná konzumenty (CLI parser-status,
   report engine, testy w4–w14/p04/etapa-b) zůstávají dostupná na modulu.
3. **Signatury entry pointů** — ``build_registry`` / ``registry_report`` bez
   změny signatury.
4. **Datový kontrakt** — pořadí 78 parserů (insertion order) i obsah každého
   záznamu (formats/limitations/reference_dataset/test_files/expected_results)
   byte-přesně dle snapshotu; verze se v monolitu/balíčku rovná ``""``
   (doplňuje je až ``build_registry()``).

Deterministicky offline; snapshot: ``tests/golden/p14_validation_registry_surface.json``.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

GOLDEN_PATH = Path(__file__).parent / "golden" / "p14_validation_registry_surface.json"
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"


def _vr_files() -> list[Path]:
    """Současná podoba modulu: monolit nebo balíček s více moduly."""
    mono = SRC_ROOT / "stopa" / "domain" / "validation_registry.py"
    if mono.is_file():
        return [mono]
    pkg = SRC_ROOT / "stopa" / "domain" / "validation_registry"
    assert pkg.is_dir(), "chybí validation_registry (monolit i balíček neexistují)"
    files = sorted(pkg.glob("*.py"))
    assert files, "balíček validation_registry je prázdný"
    return files


def _own_names(files: list[Path]) -> tuple[set[str], set[str]]:
    defs: set[str] = set()
    consts: set[str] = set()
    for f in files:
        tree = ast.parse(f.read_text(), filename=str(f))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defs.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and not t.id.startswith("__"):
                        consts.add(t.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                consts.add(node.target.id)
    return defs, consts


def test_own_definitions_match_golden() -> None:
    """Rozklad nesmí zmizet ani přejmenovat žádnou vlastní definici modulu."""
    golden = json.loads(GOLDEN_PATH.read_text())
    defs, consts = _own_names(_vr_files())
    assert defs == set(golden["own_defs"]), (
        f"vlastní def/class se liší od zlatého povrchu: "
        f"+{sorted(defs - set(golden['own_defs']))} / -{sorted(set(golden['own_defs']) - defs)}"
    )
    allowed_extra = {"_PART"}  # interní assembly jméno datových modulů (balíček)
    assert consts <= set(golden["own_consts"]) | allowed_extra, (
        f"neznámé vlastní konstanty: {sorted(consts - set(golden['own_consts']) - allowed_extra)}"
    )
    missing = set(golden["own_consts"]) - consts
    assert not missing, f"chybí vlastní konstanty: {sorted(missing)}"


def test_compat_names_importable() -> None:
    """Všechna jména používaná konzumenty musí zůstat importovatelná."""
    golden = json.loads(GOLDEN_PATH.read_text())
    from stopa.domain import validation_registry

    missing = [n for n in golden["compat_names"] if not hasattr(validation_registry, n)]
    assert not missing, f"chybí kompatibilitní jména: {missing}"


def test_entry_point_signatures_match_golden() -> None:
    """Veřejné entry pointy musí mít byte-přesně stejné signatury."""
    golden = json.loads(GOLDEN_PATH.read_text())
    from stopa.domain import validation_registry

    for name, expected in sorted(golden["signatures"].items()):
        fn = getattr(validation_registry, name)
        actual = str(inspect.signature(fn))
        assert actual == expected, (
            f"signatura {name} se změnila:\n  očekáváno: {expected}\n  aktuálně:   {actual}"
        )


def test_parser_order_matches_golden() -> None:
    """Insertion order 78 parserů musí zůstat byte-přesný (chování build_registry)."""
    golden = json.loads(GOLDEN_PATH.read_text())
    from stopa.domain.validation_registry import PARSER_VALIDATIONS

    actual = list(PARSER_VALIDATIONS.keys())
    assert len(actual) == len(golden["parser_order"]), (
        f"počet parserů: {len(actual)} != {len(golden['parser_order'])}"
    )
    diff = [(i, a, b) for i, (a, b) in enumerate(zip(actual, golden["parser_order"])) if a != b]
    assert not diff, f"pořadí parserů se liší od prvního rozdílu: {diff[:5]}"


def _as_stored(value):
    """Z JSON záznamu obnoví původní typ: list → tuple, str/None zůstává."""
    return tuple(value) if isinstance(value, list) else value


def test_data_content_matches_golden() -> None:
    """Obsah každého záznamu musí být byte-přesný (verze == '' před build_registry)."""
    golden = json.loads(GOLDEN_PATH.read_text())
    from stopa.domain.validation_registry import PARSER_VALIDATIONS, ParserValidation

    for pid, expected in golden["data"].items():
        assert pid in PARSER_VALIDATIONS, f"chybí záznam parseru {pid!r}"
        actual = PARSER_VALIDATIONS[pid]
        rebuilt = ParserValidation(
            parser_id=pid,
            version=expected["version"],
            formats=_as_stored(expected["formats"]),
            limitations=_as_stored(expected["limitations"]),
            reference_dataset=expected["reference_dataset"],
            test_files=tuple(expected["test_files"]),
            expected_results=dict(expected["expected_results"]),
        )
        assert actual == rebuilt, (
            f"záznam {pid!r} se liší od zlatého datového kontraktu:\n"
            f"  očekáváno: {rebuilt}\n  aktuálně:   {actual}"
        )
