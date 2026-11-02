"""P0 Core C3 — Parser Validation Registry: synchronizace s pipeline, report."""

from __future__ import annotations

import dataclasses

import pytest

from stopa.domain.validation_registry import (
    PARSER_VALIDATIONS,
    ParserValidation,
    RegistryError,
    build_registry,
    registry_report,
)


class TestBuildRegistry:
    def test_all_pipeline_extractors_have_records(self):
        """Každý extraktor v pipeline má záznam v registry (a naopak)."""
        from stopa.pipeline import parser_versions

        reg = build_registry()
        assert set(reg) == set(parser_versions())
        # registry obsahuje přesně deklarované záznamy (1:1 s PARSER_VALIDATIONS)
        assert len(reg) == len(PARSER_VALIDATIONS)

    def test_versions_synced_with_pipeline(self):
        """Verze v registry se shodují s pipeline (zdroj pravdy)."""
        from stopa.pipeline import parser_versions

        reg = build_registry()
        for pid, ver in parser_versions().items():
            assert reg[pid].version == ver, f"verze {pid} nesouhlasí"

    def test_explicit_versions_override(self):
        """build_registry(versions=...) — bez lazy importu pipeline."""
        versions = {pid: "9.9" for pid in PARSER_VALIDATIONS}
        reg = build_registry(versions)
        assert all(pv.version == "9.9" for pv in reg.values())

    def test_missing_pipeline_extractor_raises(self):
        """Záznam v registry bez extraktoru v pipeline → RegistryError."""
        with pytest.raises(RegistryError, match="nemá odpovídající extraktor"):
            build_registry({pid: "1.0" for pid in PARSER_VALIDATIONS if pid != "lnk"})

    def test_missing_registry_record_raises(self):
        """Extraktor v pipeline bez záznamu v registry → RegistryError."""
        versions = {pid: "1.0" for pid in PARSER_VALIDATIONS}  # všechny deklarované extraktory
        saved = PARSER_VALIDATIONS.pop("win_usn")  # schoveme záznam (zbývá o jeden méně)
        try:
            with pytest.raises(RegistryError, match="nemá záznam v registry"):
                build_registry(versions)
        finally:
            PARSER_VALIDATIONS["win_usn"] = saved

    def test_version_mismatch_raises(self):
        """Rozdílná verze pipeline vs. deklarace → RegistryError."""
        versions = {pid: "1.0" for pid in PARSER_VALIDATIONS}
        # deklarujeme jinou verzi pro jeden parser
        saved = PARSER_VALIDATIONS.pop("sqlite")
        try:
            PARSER_VALIDATIONS["sqlite"] = ParserValidation(
                parser_id="sqlite", version="2.0", formats=("x",)
            )
            with pytest.raises(RegistryError, match="nesouhlasí|verze parseru"):
                build_registry(versions)
        finally:
            PARSER_VALIDATIONS["sqlite"] = saved


class TestParserValidationModel:
    def test_frozen(self):
        pv = ParserValidation(parser_id="x", version="1", formats=("f",))
        with pytest.raises(dataclasses.FrozenInstanceError):
            pv.version = "2"  # type: ignore[misc]

    def test_defaults(self):
        pv = ParserValidation(parser_id="x", version="1", formats=("f",))
        assert pv.limitations == () and pv.reference_dataset is None
        assert pv.expected_results == {}


class TestRegistryReport:
    def test_report_rows_sorted_and_complete(self):
        rows = registry_report()
        ids = [r["parser_id"] for r in rows]
        assert ids == sorted(ids)
        # report obsahuje přesně deklarované záznamy (1:1 s PARSER_VALIDATIONS)
        assert len(rows) == len(PARSER_VALIDATIONS)
        for row in rows:
            assert row["version"]  # verze doplněna z pipeline
            assert isinstance(row["formats"], list) and row["formats"]

    def test_report_with_explicit_registry(self):
        reg = build_registry({pid: "1.0" for pid in PARSER_VALIDATIONS})
        rows = registry_report(reg)
        assert all(r["version"] == "1.0" for r in rows)
