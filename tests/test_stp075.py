"""STP-075 — file_meta reference dataset + pipeline registrace (vlna 31, pilot vlna 2, design §7).

Pokrývá celý celek end-to-end:

* **Referenční dataset** ``tests/reference_datasets/filemeta/`` — čtyři
  dokumentové fixtury (PDF + OOXML rodina docx/xlsx/pptx) s SHA-256 pinem per
  fixture v manifestu (guard testy, byte-stability rebuildu);
* **vrstva diffref, referenční čtení** — adaptér se dvěma nezávislými cestami
  nad stejným souborem (STOPA extraktor vs. ručně psané parsery PDF /Info +
  OOXML docProps), fail-fast pin, parity syntetických PDF tokenu;
* **pipeline registrace** — name-based dispatch (AXIOM Hunter pattern) za
  icloud/jumplist/usn, před klíčovými slovy; ``parser_versions()``;
* **CLI auto-režim** ``stopa differential file_meta --raw F --manifest M``;
* **aditivní stav** ``differentially_validated`` — reálný C3 registry.

Deterministicky offline; fixtury se commítují.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from stopa.artifacts.file_meta import (
    PARSER_VERSION,
    build_file_meta_artifacts,
    extract_file_meta_artifacts,
    is_file_meta_file,
)
from stopa.cli.commands.differential import cmd_differential
from stopa.diffref.meta_ref import (
    _ref_clean_pdf_date,
    _ref_ooxml_info,
    _ref_pdf_info,
    load_meta_manifest,
    read_reference_entries,
    run_stopa_filemeta,
)
from stopa.domain.differential import build_report, normalize_dataset
from stopa.domain.parser_status import DIFFERENTIALLY_VALIDATED

DS = Path(__file__).parent / "reference_datasets" / "filemeta"
MANIFEST = DS / "manifest.json"
FIXTURE_NAMES = ("sample.pdf", "sample.docx", "sample.xlsx", "sample.pptx")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _pin(name: str) -> str:
    for fx in _manifest()["fixtures"]:  # type: ignore[union-attr]
        if isinstance(fx, dict) and fx.get("file") == name:
            return str(fx["sha256"])
    raise AssertionError(f"fixture {name!r} není v manifestu")


def _join_spec() -> dict[str, tuple[str, ...]]:
    raw = _manifest()["join_keys"]
    assert isinstance(raw, dict)
    return {k: tuple(v) for k, v in raw.items()}  # type: ignore[union-attr]


# ---------------------------------------------------------------- fixture guard


class TestFixtureGuard:
    """Determinismus reference datasetu — pin per fixture + byte-stability rebuildu."""

    def test_fixtures_sha256_pinned_to_manifest(self) -> None:
        for name in FIXTURE_NAMES:
            assert _sha256(DS / name) == _pin(name), f"drift fixtury {name}"

    def test_build_fixture_rebuilds_identical_bytes(self, tmp_path: Path) -> None:
        # Rebuild do jiného adresáře = byte-identické fixtury (ZIP STORED + fixní
        # date_time; PDF ručně skládané bajty — žádná závislost na zlib/sqlite).
        proc = subprocess.run(
            [sys.executable, str(DS / "build_fixture.py"), str(tmp_path)],
            capture_output=True, text=True, check=False, cwd=str(DS),
        )
        assert proc.returncode == 0, f"rebuild selhal: {proc.stderr[:300]}"
        for name in FIXTURE_NAMES:
            assert _sha256(tmp_path / name) == _pin(name), f"drift rebuildu {name}"
        rebuilt = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        original = _manifest()
        assert rebuilt["fixtures"] == original["fixtures"]


# ---------------------------------------------------------------- manifest smlouva


class TestMetaManifestSchema:
    """Manifest file_meta datasetu = smlouva referenční cesty."""

    def test_schema_fields_present(self) -> None:
        m = _manifest()
        assert m["version"] == 1
        assert m["parser_id"] == "file_meta"
        assert isinstance(m["reference_tool"], str) and m["reference_tool"]
        jk = m["join_keys"]
        assert jk == {"document_metadata": ["name"]}
        fixtures = m["fixtures"]
        assert isinstance(fixtures, list) and len(fixtures) == 4
        declared = {fx["file"]: fx["variant"] for fx in fixtures}  # type: ignore[index]
        assert declared == {
            "sample.pdf": "pdf",
            "sample.docx": "ooxml",
            "sample.xlsx": "ooxml",
            "sample.pptx": "ooxml",
        }

    def test_load_manifest_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="chybi.json"):
            load_meta_manifest(tmp_path / "chybi.json")

    def test_load_manifest_non_object_json(self, tmp_path: Path) -> None:
        p = tmp_path / "m.json"
        p.write_text("[1, 2]", encoding="utf-8")
        with pytest.raises(TypeError, match="očekáván JSON objekt"):
            load_meta_manifest(p)

    def test_load_manifest_bad_version(self, tmp_path: Path) -> None:
        m = _manifest()
        m["version"] = 2
        p = tmp_path / "m.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        with pytest.raises(ValueError, match="nepodporovaná verze"):
            load_meta_manifest(p)

    def test_load_manifest_unknown_variant(self, tmp_path: Path) -> None:
        m = _manifest()
        m["fixtures"][0]["variant"] = "evtx"  # type: ignore[index]
        p = tmp_path / "m.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        with pytest.raises(ValueError, match="neznámá reference varianta"):
            load_meta_manifest(p)

    def test_load_manifest_bad_sha_length(self, tmp_path: Path) -> None:
        m = _manifest()
        m["fixtures"][1]["sha256"] = "abc"  # type: ignore[index]
        p = tmp_path / "m.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        with pytest.raises(ValueError, match="64-znakový hex"):
            load_meta_manifest(p)


# ---------------------------------------------------------------- reference parsery

class TestRefPdfParser:
    """Nezávislý PDF /Info parser — magic, escapes, datová normalizace."""

    def test_requires_pdf_magic(self) -> None:
        from stopa.diffref.meta_ref import _ref_pdf

        with pytest.raises(ValueError, match="%PDF"):
            _ref_pdf(b"NOT-PDF-CONTENT")

    def test_sample_pdf_full_info(self) -> None:
        info = _ref_pdf_info((DS / "sample.pdf").read_bytes())
        assert info["title"] == "Annual Report (Q4) - final version 2"  # escaped parens
        assert info["author"] == "Jane A. Doe"  # oktalový escape \101 = 'A'
        assert info["creator"] == "STOPA Pilot Generator"
        assert info["producer"] == "diffref-wave2/1.0"
        assert info["created"] == "2026-03-15T14:30:00+02:00"  # D:…+02'00' → ISO
        assert info["modified"] == "2026-04-01T09:00:00+00:00"  # D:…Z → +00:00

    def test_hex_string_token(self) -> None:
        pdf = b"%PDF-1.5\n3 0 obj\n<< /Title <48656c6c6f20576f726c64> >>\nendobj\n%%EOF\n"
        assert _ref_pdf_info(pdf)["title"] == "Hello World"

    def test_clean_pdf_date_variants(self) -> None:
        assert _ref_clean_pdf_date("D:20260101") == "2026-01-01T00:00:00"
        assert _ref_clean_pdf_date("D:20260101Z") == "2026-01-01T00:00:00+00:00"
        assert _ref_clean_pdf_date("D:20260315143000+02'00'") == "2026-03-15T14:30:00+02:00"
        # neparsabilní / cizí tvary zůstávají nezměněny (defenzivní kontrakt)
        assert _ref_clean_pdf_date("garbage") == "garbage"
        assert _ref_clean_pdf_date("D:") == "D:"


class TestRefOoxmlParser:
    """Nezávislý OOXML docProps parser — magic, core.xml mapa, app.xml statistiky."""

    def test_requires_zip_magic(self) -> None:
        from stopa.diffref.meta_ref import _ref_ooxml

        with pytest.raises(ValueError, match="PK zip"):
            _ref_ooxml(b"NOT-ZIP-CONTENT")

    def test_sample_docx_full_core_and_app(self) -> None:
        info = _ref_ooxml_info((DS / "sample.docx").read_bytes())
        assert info["title"] == "Quarterly Planning Document"
        assert info["author"] == "Miroslav Matúš"  # dc:creator → author (kontrakt)
        assert info["modified_by"] == "Jana Nováková"
        assert info["created"] == "2026-05-10T08:00:00Z"
        assert info["modified"] == "2026-06-01T17:45:30Z"
        assert info["application"] == "Microsoft Office Word"
        assert info["company"] == "Komunikátor s.r.o."
        assert info["pages"] == "12"

    def test_sample_xlsx_reduced_field_set(self) -> None:
        info = _ref_ooxml_info((DS / "sample.xlsx").read_bytes())
        # redukovaná množina — chybějící pole se NENÍ doplněna (union ≡ None)
        assert "modified_by" not in info and "modified" not in info
        assert "pages" not in info and "words" not in info
        assert info["title"] == "Budget Overview FY26"
        assert info["author"] == "Petr Svířek"
        assert info["characters"] == "89204"

    def test_sample_pptx_slides_and_offset_dates(self) -> None:
        info = _ref_ooxml_info((DS / "sample.pptx").read_bytes())
        assert info["slides"] == "24"
        assert info["created"] == "2026-07-04T09:00:00+02:00"  # bez normalizace (kontrakt)


# ---------------------------------------------------------------- parity obou cest

class TestBothSidesIdentity:
    """Dvě nezávislé cesty nad stejnými bajty = identické normalizované záznamy."""

    @pytest.mark.parametrize("name", FIXTURE_NAMES)
    def test_normalized_records_identical(self, name: str) -> None:
        spec = _join_spec()
        stopa = normalize_dataset(run_stopa_filemeta(DS / name), join_keys=spec)
        ref = normalize_dataset(read_reference_entries(DS / name, load_meta_manifest(MANIFEST)), join_keys=spec)
        assert len(stopa) == 1 and len(ref) == 1
        a, b = stopa[0], ref[0]
        assert a.type == b.type == "document_metadata"
        assert a.ts_epoch is None and b.ts_epoch is None
        assert dict(a.fields) == dict(b.fields), f"pole se liší: {dict(a.fields)} vs {dict(b.fields)}"

    @pytest.mark.parametrize("name", FIXTURE_NAMES)
    def test_build_report_zero_diffs(self, name: str) -> None:
        spec = _join_spec()
        stopa = normalize_dataset(run_stopa_filemeta(DS / name), join_keys=spec)
        ref = normalize_dataset(read_reference_entries(DS / name, load_meta_manifest(MANIFEST)), join_keys=spec)
        report = build_report(parser="file_meta", stopa_records=stopa, ref_records=ref, join_keys=spec)
        assert len(report.differences) == 0
        assert report.identical_pct == 100.0

    @pytest.mark.parametrize("name", FIXTURE_NAMES)
    def test_reference_entries_match_golden(self, name: str) -> None:
        # golden = referenční cesta přes sdílenou normalizační vrstvu (design §3)
        spec = _join_spec()
        records = normalize_dataset(
            read_reference_entries(DS / name, load_meta_manifest(MANIFEST)), join_keys=spec
        )
        payload = [
            {"type": r.type, "ts_epoch": r.ts_epoch, "fields": dict(r.fields)} for r in records
        ]
        ext = name.rsplit(".", 1)[-1]
        golden = json.loads((DS / f"expected_sample_{ext}.json").read_text(encoding="utf-8"))
        assert payload == golden

    def test_synthetic_pdf_token_parity(self) -> None:
        # syntetické PDF tvary — doménová utilita vs. referenční parser (parita na bajtech)
        from stopa.domain.file_meta import extract_metadata

        cases = [
            b"%PDF-1.4\n<< /Title <48656c> /Author (A\\(B\\) C \\101) >>\n%%EOF\n",
            b"%PDF-1.5\n<< /CreationDate (D:20260101T123045Z) /Producer <DEAD> >>\n%%EOF\n",
        ]
        for data in cases:
            domain = extract_metadata(data, "synthetic.pdf")
            ref = _ref_pdf_info(data)
            assert domain == ref, f"parita selhala pro {data[:40]!r}: {domain} vs {ref}"


# ---------------------------------------------------------------- pipeline registrace

class TestPipelineRegistration:
    """Name-based dispatch — AXIOM Hunter pattern za icloud/jumplist/usn."""

    def test_is_file_meta_file_extensions(self) -> None:
        assert is_file_meta_file("report.pdf")
        assert is_file_meta_file("REPORT.PDF")  # case-insensitive
        assert is_file_meta_file("/full/path/to/doc.docx")  # celá cesta (retry dispatch)
        assert not is_file_meta_file("notes.txt")
        assert not is_file_meta_file("archive.zip")

    def test_name_based_match_routes_documents(self) -> None:
        from stopa.pipeline.matching import _name_based_match
        from stopa.pipeline.registry import NAME_BASED_EXTRACTORS

        for name in ("report.pdf", "plan.docx", "budget.XLSX", "deck.pptx"):
            assert _name_based_match(name) == NAME_BASED_EXTRACTORS["file_meta"], name

    def test_icloud_priority_over_document_extension(self) -> None:
        # MessagesInICloud.xlsx — icloud detektor (substring marker) si drží prioritu
        from stopa.pipeline.matching import _name_based_match
        from stopa.pipeline.registry import NAME_BASED_EXTRACTORS

        assert _name_based_match("MessagesInICloud.xlsx") == NAME_BASED_EXTRACTORS["icloud_messages"]

    def test_document_extension_beats_keyword_detectors(self) -> None:
        # netstat klíčové slovo v názvu dokumentu — extenzní detektor vyhrává
        from stopa.pipeline.matching import _name_based_match
        from stopa.pipeline.registry import NAME_BASED_EXTRACTORS

        assert _name_based_match("netstat_report.docx") == NAME_BASED_EXTRACTORS["file_meta"]

    def test_registry_version_and_parser_versions(self) -> None:
        from stopa.pipeline.core import parser_versions
        from stopa.pipeline.registry import NAME_BASED_EXTRACTORS

        fn, ver = NAME_BASED_EXTRACTORS["file_meta"]
        assert ver == PARSER_VERSION == "1.0"
        assert callable(fn)
        versions = parser_versions()
        assert versions.get("file_meta") == "1.0"


class TestBuildArtifacts:
    """Čistá funkce — normalizovaná metadata → document_metadata artifact."""

    def test_empty_meta_no_artifact(self) -> None:
        assert build_file_meta_artifacts({}, "x.pdf") == []

    def test_iso_created_parsed_to_timestamp(self) -> None:
        (artifact,) = build_file_meta_artifacts(
            {"title": "T", "created": "2026-03-15T14:30:00+02:00"}, "x.pdf"
        )
        assert artifact.artifact_type == "document_metadata"
        assert artifact.timestamp is not None and isinstance(artifact.timestamp, datetime)

    def test_unparsable_created_timestamp_none(self) -> None:
        # EXIF tvar "2026:03:15 14:30:00" není ISO → defenzivně None (pole zůstává v details)
        (artifact,) = build_file_meta_artifacts(
            {"title": "T", "created": "2026:03:15 14:30:00"}, "x.jpg"
        )
        assert artifact.timestamp is None

    def test_details_contract(self) -> None:
        (artifact,) = build_file_meta_artifacts({"title": "T", "author": "A"}, "doc.pdf")
        assert artifact.details["engine"] == "file_meta"  # provenience extrakce
        assert artifact.details["name"] == "doc.pdf"
        assert artifact.details["title"] == "T" and artifact.details["author"] == "A"
        assert artifact.parser_version == PARSER_VERSION

    def test_extract_file_meta_artifacts_on_fixture(self) -> None:
        (artifact,) = extract_file_meta_artifacts(DS / "sample.pdf")
        assert artifact.artifact_type == "document_metadata"
        assert artifact.details["author"] == "Jane A. Doe"


# ---------------------------------------------------------------- CLI auto-režim

def _ns(name: str = "sample.pdf", **overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "parser": "file_meta",
        "input": None,
        "ref": None,
        "raw": str(DS / name),
        "manifest": str(MANIFEST),
        "tool": None,
        "join_key": [],
        "adjudications": None,
        "run_id": None,
        "format": "text",
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestCliAutoModeFileMeta:
    """``stopa differential file_meta --raw F --manifest M`` (§7 pilot vlna 2)."""

    @pytest.mark.parametrize("name", FIXTURE_NAMES)
    def test_auto_mode_success(self, name: str, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_differential(_ns(name=name))
        assert rc == 0
        out = capsys.readouterr().out
        assert "parser=file_meta" in out
        assert "identické: 100.0 %" in out
        assert "Rozdíly: žádné" in out

    def test_auto_mode_json_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_differential(_ns(format="json"))
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["parser"] == "file_meta"
        assert payload["identical_pct"] == 100.0
        assert payload["differences"] == []
        # reference_tool bez --tool = identita z manifestu (design §10.2)
        assert str(payload["reference_tool"]).startswith("diffref-meta-stdlib/1.0")

    def test_hash_pin_mismatch_exit2(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        broken = tmp_path / "sample.docx"
        shutil.copyfile(DS / "sample.docx", broken)
        with open(broken, "ab") as f:
            f.write(b"\n")
        rc = cmd_differential(_ns(name="sample.docx", raw=str(broken)))
        assert rc == 2
        assert "hash fixtury se neshoduje s pinem" in capsys.readouterr().err

    def test_missing_raw_file_exit2(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_differential(_ns(raw=str(tmp_path / "nenalezen.pdf")))
        assert rc == 2
        assert "soubor nenalezen" in capsys.readouterr().err


# ---------------------------------------------------------------- aditivní stav

class TestDifferentiallyValidatedFileMeta:
    """Reálný C3 registry — file_meta se pincovaným datasetem = promoted."""

    def test_real_registry_file_meta_promoted(self) -> None:
        from stopa.data.parser_status_service import load_parser_status

        report = load_parser_status()
        by_id = {p["parser_id"]: p for p in report["parsers"]}
        assert by_id["file_meta"]["validation_status"] == DIFFERENTIALLY_VALIDATED
        # pilot vlny 1+2: všechny tři promované parsery v explicitním klíči
        assert set(report["differentially_validated"]) == {
            p["parser_id"] for p in report["parsers"]
            if p["validation_status"] == DIFFERENTIALLY_VALIDATED
        } >= {"sqlite", "net_connections", "file_meta"}
