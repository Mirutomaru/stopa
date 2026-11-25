"""B11 — i18n katalog: schéma, proměnné (placeholders), pokrytí referencí.

Audit-first nálezy F-1..F-5 viz ``.stopa-dev/PLAN_BACKLOG_2026-11.md`` (sekce B11).
Test-only sada — žádná změna runtime kódu:

A. Schéma katalogu: flat dict[str, str], neprázdné klíče/hodnoty, formát klíčů
B. Placeholder konzistence cs↔en (shoda množiny ``{...}`` pro každý společný klíč)
C. Pokrytí forward: každý staticky referencovaný katalogový klíč existuje v obou katalozích
D. Pokrytí reverse: žádný mrtvý katalogový klíč (užit t() literálem nebo string literálem,
   např. hodnoty ``_SUBCOMMAND_EXAMPLES``)
E. Call-site parametry (AST): pro moduly s importem katalogového ``t()`` — kwargy volání
   odpovídají placeholderům klíče; klíč s placeholdery dostane na každém call-site všechny

Deterministická statická analýza zdrojů + JSON katalogů — offline, bez DB i sítě.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
SRC = BASE / "src" / "stopa"
CATALOG_DIR = SRC / "i18n"

KEY_RE = re.compile(r"^cli\.[A-Za-z0-9_.]+$")
PH_RE = re.compile(r"\{(\w+)\}")
T_CALL_RE = re.compile(r"""\bt\(\s*["']([^"']+)["']""")
BARE_KEY_RE = re.compile(r"""["'](cli(?:\.[A-Za-z0-9_.]+)+)["']""")


def _catalog(lang: str) -> dict[str, str]:
    return json.loads((CATALOG_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def _source_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _placeholders(value: str) -> set[str]:
    return set(PH_RE.findall(value))


def _referenced_keys() -> set[str]:
    """Katalogové klíče referencované v kódu (t() literály + string literály)."""
    refs = set()
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        refs.update(T_CALL_RE.findall(text))
        refs.update(BARE_KEY_RE.findall(text))
    return {k for k in refs if KEY_RE.match(k)}


def _catalog_t_modules() -> list[Path]:
    """Moduly importující ``t`` z katalogového stopa.i18n (ne domain/i18n)."""

    def _is_catalog_import(node: ast.ImportFrom) -> bool:
        parts = (node.module or "").split(".")
        if not parts or parts[-1] != "i18n" or "domain" in parts:
            return False
        return any(a.name == "t" for a in node.names)

    out = []
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        nodes = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        if any(_is_catalog_import(n) for n in nodes):
            out.append(path)
    return out


# --- A. Schéma katalogu -----------------------------------------------------


@pytest.mark.parametrize("lang", ["cs", "en"])
def test_catalog_is_flat_string_map(lang: str) -> None:
    """Katalog = plochá mapa klíč→řetězec, bez prázdných položek."""
    catalog = _catalog(lang)
    assert catalog, f"katalog {lang} je prázdný"
    for key, value in catalog.items():
        assert isinstance(key, str) and key.strip(), f"{lang}: neprázdný klíč — {key!r}"
        assert isinstance(value, str) and value.strip(), (
            f"{lang}: hodnota klíče {key} není neprázdný řetězec: {value!r}"
        )


@pytest.mark.parametrize("lang", ["cs", "en"])
def test_catalog_key_format(lang: str) -> None:
    """Formát klíčů: cli.h.NNN / cli.top.* / cli.mv.* / cli.opt.json.help atd."""
    bad = [k for k in _catalog(lang) if not KEY_RE.match(k)]
    assert not bad, f"{lang}: klíče mimo formát ^cli\\.[A-Za-z0-9_.]+$: {sorted(bad)}"


# --- B. Placeholder konzistence cs↔en ---------------------------------------


def test_placeholder_parity_cs_en() -> None:
    """Každý společný klíč má v obou jazycích stejnou množinu placeholderů."""
    cs, en = _catalog("cs"), _catalog("en")
    mismatches = {
        k: (sorted(_placeholders(cs[k])), sorted(_placeholders(en.get(k, ""))))
        for k in set(cs) & set(en)
        if _placeholders(cs[k]) != _placeholders(en.get(k, ""))
    }
    assert not mismatches, f"divergence placeholderů cs↔en: {mismatches}"


# --- C. Pokrytí forward ------------------------------------------------------


def test_referenced_keys_exist_in_both_catalogs() -> None:
    """Každý staticky referencovaný katalogový klíč existuje v cs i en."""
    refs = _referenced_keys()
    assert refs, "žádná katalogová reference nenalezena — scan selhal?"
    missing_cs = sorted(k for k in refs if k not in _catalog("cs"))
    missing_en = sorted(k for k in refs if k not in _catalog("en"))
    assert not missing_cs, f"referencované klíče chybějící v cs.json: {missing_cs}"
    assert not missing_en, f"referencované klíče chybějící v en.json: {missing_en}"


# --- D. Pokrytí reverse ------------------------------------------------------


def test_no_dead_catalog_keys() -> None:
    """Žádný katalogový klíč není mrtvý (užit t() literálem nebo string literálem)."""
    refs = _referenced_keys()
    dead = sorted(set(_catalog("cs")) - refs)
    assert not dead, f"mrtvé katalogové klíče (bez reference v kódu): {dead}"


# --- E. Call-site parametry (AST) --------------------------------------------


def test_call_site_params_match_placeholders() -> None:
    """Kwargy t("klíč", ...) odpovídají placeholderům; placeholdery jsou pokryty."""
    modules = _catalog_t_modules()
    assert modules, "čekaný import katalogového t() nenalezen — scan selhal?"
    cs = _catalog("cs")  # en parity zajišťuje test_placeholder_parity_cs_en

    problems: list[str] = []
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = str(path.relative_to(BASE))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id != "t" or not node.args:
                continue
            first = node.args[0]
            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                continue  # dynamický klíč — staticky neověřitelné
            key = first.value
            value = cs.get(key)
            if value is None:
                continue  # chybějící klíč řeší test C (čitelnější failure tam)
            ph = _placeholders(value)
            passed = {k.arg for k in node.keywords if k.arg}  # None = **double-star
            unknown = sorted(passed - ph)
            missing = sorted(ph - passed)
            if unknown:
                problems.append(f"{rel}:{node.lineno}: neznámé parametry pro {key}: {unknown}")
            if missing:
                problems.append(
                    f"{rel}:{node.lineno}: klíč {key} bez parametrů {missing}"
                    " → ve výstupu zůstane '{...}'"
                )
    assert not problems, "\n".join(problems)
