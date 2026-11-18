"""P1-4 vlna D — zlatý povrch modulu ``stopa.pipeline`` (před rozkladem do balíčku).

Kontrakt, který musí přežít rozklad god-file ``pipeline.py``:

1. **Vlastní definice** — všechna top-level def/class + konstanty definovaná
   v kódu pipeline (AST over ``src/stopa/pipeline.py`` nebo
   ``src/stopa/pipeline/*.py``) musí být byte-přesně stejná množina.
2. **Kompatibilitní povrch** — jména, která importují konzumenti
   (CLI komandy, web routery, benchmark engine, testy přes alias),
   musí zůstat dostupná jako atributy modulu ``stopa.pipeline``.
3. **Signatury entry pointů** — veřejné funkce sdílené CLI i web musí mít
   identické signatury (backward kompatibilita volání).

Deterministicky offline; snapshot: ``tests/golden/p14_pipeline_surface.json``.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

GOLDEN_PATH = Path(__file__).parent / "golden" / "p14_pipeline_surface.json"
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"


def _pipeline_files() -> list[Path]:
    """Současná podoba modulu: monolit nebo balíček s více moduly."""
    mono = SRC_ROOT / "stopa" / "pipeline.py"
    if mono.is_file():
        return [mono]
    pkg = SRC_ROOT / "stopa" / "pipeline"
    assert pkg.is_dir(), "chybí stopa/pipeline (monolit i balíček neexistují)"
    files = sorted(pkg.glob("*.py"))
    assert files, "balíček stopa/pipeline je prázdný"
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


@pytest.fixture(scope="module")
def golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text())


def test_own_definitions_match_golden(golden: dict) -> None:
    """Rozklad nesmí zmizet ani přejmenovat žádnou vlastní definici pipeline."""
    defs, consts = _own_names(_pipeline_files())
    assert defs == set(golden["own_defs"]), (
        f"vlastní def/class se liší od zlatého povrchu: "
        f"+{sorted(defs - set(golden['own_defs']))} / -{sorted(set(golden['own_defs']) - defs)}"
    )
    assert consts == set(golden["own_consts"]), (
        f"vlastní konstanty se liší od zlatého povrchu: "
        f"+{sorted(consts - set(golden['own_consts']))} / -{sorted(set(golden['own_consts']) - consts)}"
    )


def test_compat_names_importable() -> None:
    """Všechna jména používaná konzumenty musí zůstat importovatelná."""
    golden = json.loads(GOLDEN_PATH.read_text())
    from stopa import pipeline

    missing = [n for n in golden["compat_names"] if not hasattr(pipeline, n)]
    assert not missing, f"chybí kompatibilitní jména na stopa.pipeline: {missing}"


def test_entry_point_signatures_match_golden() -> None:
    """Veřejné entry pointy musí mít byte-přesně stejné signatury."""
    golden = json.loads(GOLDEN_PATH.read_text())
    from stopa import pipeline

    for name, expected in sorted(golden["signatures"].items()):
        fn = getattr(pipeline, name)
        actual = str(inspect.signature(fn))
        assert actual == expected, f"signatura {name} se změnila:\n  očekáváno: {expected}\n  aktuálně:   {actual}"
