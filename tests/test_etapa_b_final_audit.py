"""ETAPA B — ZÁVĚREČNÝ AUDIT (STP-037).

Deterministické invarianty celé ETAPY B po vlnách 1–15:
- coverage matice ↔ AXIOM RE reference: bijekce 232 typů (oběma směry)
- SUPPORTED = 200 typů, každý s parserem + testováním
- DEPRECATED = 32 base-class rozhraní (multi, ne extraktory)
- C3 registry: 77 verzovaných parserů, test_files existují, verze neprázdné
- pipeline dispatch ↔ C3 registry sync (name-based extraktory mají záznamy)

Spouští se offline — jen čtení CSV/JSON + importy.
"""

from __future__ import annotations

import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

RE_JSON = os.path.join(
    os.path.dirname(__file__), "..", "docs", "re-axiom", "axiom-artifact-extractors.json"
)
MATRIX_CSV = os.path.join(os.path.dirname(__file__), "..", "STOPA_COVERAGE_MATRIX.csv")


def _load_matrix() -> list[dict]:
    with open(MATRIX_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_re_suffixes() -> set[str]:
    with open(RE_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return {d["type"].rsplit(".", 1)[-1] for d in data}


class TestMatrixIntegrity:
    """Struktura coverage matice."""

    def test_total_rows_232(self):
        rows = _load_matrix()
        assert len(rows) == 232, f"očekáváno 232 řádků, je {len(rows)}"

    def test_no_duplicate_types(self):
        names = [r["artifact_type"] for r in _load_matrix()]
        dups = {n for n in names if names.count(n) > 1}
        assert not dups, f"duplicitní typy: {sorted(dups)}"

    def test_bijection_with_axiom_re(self):
        """Matice ↔ AXIOM RE reference: stejná množina 232 typů oběma směry."""
        matrix_names = {r["artifact_type"] for r in _load_matrix()}
        re_suffixes = _load_re_suffixes()
        assert len(re_suffixes) == 232, f"RE reference má {len(re_suffixes)} unikátních typů"
        assert matrix_names == re_suffixes, (
            "rozdíl matice vs RE: jen v matici "
            f"{sorted(matrix_names - re_suffixes)}, jen v RE {sorted(re_suffixes - matrix_names)}"
        )

    def test_only_known_statuses(self):
        from collections import Counter

        statuses = Counter(r["stav_implementace"] for r in _load_matrix())
        assert set(statuses) == {"SUPPORTED", "DEPRECATED"}, f"neznámé stavy: {statuses}"


class TestEtapaBFinalState:
    """Finální stav ETAPY B po vlnách 1–15."""

    def test_supported_count_200(self):
        rows = _load_matrix()
        supported = [r for r in rows if r["stav_implementace"] == "SUPPORTED"]
        assert len(supported) == 200, f"očekáváno 200 SUPPORTED, je {len(supported)}"

    def test_supported_all_have_parser_and_tests(self):
        """Každý SUPPORTED typ má přiřazen parser i testování."""
        for r in _load_matrix():
            if r["stav_implementace"] != "SUPPORTED":
                continue
            assert r["parser_stopa"].strip(), f"{r['artifact_type']}: chybí parser_stopa"
            assert (
                r["stav_testovani"].strip() == "testováno"
            ), f"{r['artifact_type']}: stav_testovani = {r['stav_testovani']!r}"

    def test_deprecated_are_base_classes(self):
        """DEPRECATED = 32 base-class rozhraní (multi, ne extraktory)."""
        dep = [r for r in _load_matrix() if r["stav_implementace"] == "DEPRECATED"]
        assert len(dep) == 32, f"očekáváno 32 DEPRECATED, je {len(dep)}"
        for r in dep:
            assert r["platforma"] == "multi", f"{r['artifact_type']}: platforma = {r['platforma']}"
            assert (
                "rozhraní" in r["zdroj_dat"] or "základní třída" in r["zdroj_dat"]
            ), f"{r['artifact_type']}: zdroj_dat = {r['zdroj_dat']!r}"

    def test_no_unsupported_left(self):
        """Po vlně 15 nezbývá žádný NOT_SUPPORTED typ (celá ETAPA B dokončena)."""
        statuses = {r["stav_implementace"] for r in _load_matrix()}
        assert "NOT_SUPPORTED" not in statuses, f"zbývají: {statuses}"


class TestC3RegistryFinalState:
    """C3 registry po vlně 15."""

    def test_registry_count_81(self):
        from stopa.domain.validation_registry import build_registry

        reg = build_registry()
        assert len(reg) == 81, f"očekáváno 81 parserů (vlna 15 + K2 crypto + vlna 31 file_meta + STP-080 syslog + STP-081 access_log), je {len(reg)}"

    def test_all_test_files_exist(self):
        """Každý registry záznam odkazuje na existující test soubory."""
        from stopa.domain.validation_registry import build_registry

        reg = build_registry()
        missing = [
            (pid, tf) for pid, v in reg.items() for tf in v.test_files if not os.path.exists(tf)
        ]
        assert not missing, f"chybějící test soubory: {missing}"

    def test_all_versions_nonempty(self):
        from stopa.domain.validation_registry import build_registry

        reg = build_registry()
        bad = [pid for pid, v in reg.items() if not v.version]
        assert not bad, f"prázdné verze: {bad}"


class TestPipelineRegistrySync:
    """Pipeline dispatch ↔ C3 registry (name-based extraktory)."""

    def test_name_based_extractors_have_registry_records(self):
        from stopa.domain.validation_registry import build_registry
        from stopa.pipeline import NAME_BASED_EXTRACTORS

        reg = build_registry()
        missing = [k for k in NAME_BASED_EXTRACTORS if k not in reg]
        assert not missing, f"name-based extraktory bez C3 záznamu: {missing}"

    def test_signature_extractors_have_registry_records(self):
        from stopa.domain.validation_registry import build_registry
        from stopa.pipeline import ARTIFACT_EXTRACTORS

        reg = build_registry()
        missing = [k for k in ARTIFACT_EXTRACTORS if k not in reg]
        assert not missing, f"signatura extraktory bez C3 záznamu: {missing}"
