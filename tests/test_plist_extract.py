"""Testy Apple property list extraktoru — FÁZE 4b.

ČISTÉ funkce testujeme nad Python objekty (žádné IO). IO wrapper testujeme na
reálných binárních i XML plists vygenerovaných plistlibem.
"""

from __future__ import annotations

import plistlib
from datetime import UTC, datetime
from pathlib import Path

from stopa.artifacts.plist_extract import build_plist_artifacts

TS = datetime(2024, 3, 15, 12, 34, 56, tzinfo=UTC)


class TestBuildPlistArtifacts:
    def test_datetime_field_becomes_date_artifact(self):
        data = {"LastOpened": TS, "Name": "Test"}
        arts = build_plist_artifacts(data)
        # 1 date artifact + 1 triage
        assert len(arts) == 2
        date_arts = [a for a in arts if a.artifact_type == "plist_date"]
        assert len(date_arts) == 1
        assert date_arts[0].timestamp == TS
        assert "LastOpened" in date_arts[0].details["key_path"]

    def test_nested_datetime_found(self):
        data = {"Outer": {"Inner": {"When": TS}}}
        arts = build_plist_artifacts(data)
        date_arts = [a for a in arts if a.artifact_type == "plist_date"]
        assert len(date_arts) == 1
        # cesta obsahuje plnou hierarchii
        assert "Outer/Inner/When" in date_arts[0].details["key_path"]

    def test_list_datetime_indexed(self):
        data = {"Events": [TS, TS]}
        arts = build_plist_artifacts(data)
        date_arts = [a for a in arts if a.artifact_type == "plist_date"]
        assert len(date_arts) == 2

    def test_non_datetime_no_date_artifacts(self):
        data = {"Name": "Test", "Count": 42, "Flag": True}
        arts = build_plist_artifacts(data)
        date_arts = [a for a in arts if a.artifact_type == "plist_date"]
        assert date_arts == []

    def test_triage_always_present(self):
        data = {"A": 1, "B": 2}
        arts = build_plist_artifacts(data)
        triage = [a for a in arts if a.artifact_type == "property_list"]
        assert len(triage) == 1
        assert set(triage[0].details["top_level_keys"]) <= {"A", "B"}

    def test_triage_root_type(self):
        data = {"A": 1}
        arts = build_plist_artifacts(data)
        triage = next(a for a in arts if a.artifact_type == "property_list")
        assert triage.details["root_type"] == "dict"

    def test_empty_dict(self):
        arts = build_plist_artifacts({})
        # jen triage, žádné date
        assert len(arts) == 1
        assert arts[0].artifact_type == "property_list"


class TestExtractPlistArtifactsIO:
    # Apple plists ukládají časy jako sekundy od 2001 epochu — bez timezone (naive).
    # plistlib.dump(FMT_BINARY) tz-aware neumí serializovat → fixture používá naive.
    NAIVE_TS = datetime(2024, 3, 15, 12, 34, 56)

    def _write_binary_plist(self, tmp_path: Path, data: dict) -> Path:
        p = tmp_path / "test.plist"
        with open(p, "wb") as f:
            plistlib.dump(data, f, fmt=plistlib.FMT_BINARY)
        return p

    def _write_xml_plist(self, tmp_path: Path, data: dict) -> Path:
        p = tmp_path / "test.xml.plist"
        with open(p, "wb") as f:
            plistlib.dump(data, f, fmt=plistlib.FMT_XML)
        return p

    def test_binary_plist_with_date(self, tmp_path: Path):
        from stopa.artifacts.plist_extract import extract_plist_artifacts

        p = self._write_binary_plist(tmp_path, {"LastOpened": self.NAIVE_TS, "Name": "Test"})
        arts = extract_plist_artifacts(p)
        date_arts = [a for a in arts if a.artifact_type == "plist_date"]
        assert len(date_arts) == 1
        # round-trip: plistlib vrací naive datetime (sekundy od 2001 epochu)
        assert date_arts[0].timestamp is not None
        assert date_arts[0].timestamp.year == 2024

    def test_xml_plist_with_date(self, tmp_path: Path):
        from stopa.artifacts.plist_extract import extract_plist_artifacts

        p = self._write_xml_plist(tmp_path, {"When": self.NAIVE_TS})
        arts = extract_plist_artifacts(p)
        date_arts = [a for a in arts if a.artifact_type == "plist_date"]
        assert len(date_arts) == 1

    def test_corrupt_plist_returns_empty(self, tmp_path: Path):
        from stopa.artifacts.plist_extract import extract_plist_artifacts

        p = tmp_path / "corrupt.plist"
        # bplist00 magic ale jinak neplatný obsah
        p.write_bytes(b"bplist00" + b"\xff\xfe\xfd\xfc")
        assert extract_plist_artifacts(p) == []

    def test_missing_file_returns_empty(self, tmp_path: Path):
        from stopa.artifacts.plist_extract import extract_plist_artifacts

        assert extract_plist_artifacts(tmp_path / "chybi.plist") == []


class TestSignatureIntegration:
    """Signatura → extraktor dispatch (pipeline ARTIFACT_EXTRACTORS)."""

    def test_dispatch_map_has_new_types(self):
        from stopa.pipeline import ARTIFACT_EXTRACTORS

        assert "sqlite" in ARTIFACT_EXTRACTORS
        assert "registry_hive" in ARTIFACT_EXTRACTORS
        assert "plist" in ARTIFACT_EXTRACTORS

    def test_dispatch_map_extractors_are_callable(self):
        from stopa.pipeline import ARTIFACT_EXTRACTORS

        for sig, (fn, _ver) in ARTIFACT_EXTRACTORS.items():
            assert callable(fn), f"extraktor pro {sig} není callable"

    def test_dispatch_map_has_parser_versions(self):
        """E1: každý extraktor má verzi parseru (reprodukovatelnost)."""
        from stopa.pipeline import ARTIFACT_EXTRACTORS, parser_versions

        for sig, (_fn, ver) in ARTIFACT_EXTRACTORS.items():
            assert isinstance(ver, str) and ver, f"extraktor {sig} nemá verzi"
        versions = parser_versions()
        assert "sqlite" in versions
        assert "registry_hive" in versions
        assert "plist" in versions
