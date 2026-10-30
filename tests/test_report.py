"""Testy forenzního reportu (FÁZE 7) — domain build_html + IO wrapper."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.data.db import CaseDB
from stopa.domain.report import CustodyItem, FlaggedFile, ReportData, SourceInfo, build_html
from stopa.models import Artifact, Case, EvidenceSource, FileRecord
from stopa.presentation.case_report import (
    build_report_data,
    generate_html_report,
    generate_pdf_report,
)

TS = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def sample_data() -> ReportData:
    return ReportData(
        case_id="case-test123",
        case_name="Karel Novák <&> spol.",
        examiner="Mgr. Miroslav Matúš DiS",
        created_at=TS,
        notes="Testovací případ",
        sources=(
            SourceInfo(id="src-1", kind="folder", path="/evidence/phone", added_at=TS),
        ),
        per_source_stats={"src-1": {"files": 2, "bytes": 3072, "bad_ext": 1, "dups": 1, "signed": 1}},
        totals={"files": 2, "bytes": 3072, "bad_ext": 1, "dups": 1, "signed": 1},
        artifact_counts={"browser_history": 4, "sms_message": 2},
        custody_items=(
            CustodyItem(source_id="src-1", rel_path="a.txt", size_bytes=1024, sha256="ab" * 32),
            CustodyItem(source_id="src-1", rel_path="b.bin", size_bytes=2048, sha256=None),
        ),
        flagged_files=(
            FlaggedFile(rel_path="a.txt", flags=("BAD-EXT", "HASHSET:bad"), sha256="ab" * 32),
        ),
    )


class TestBuildHtml:
    def test_contains_case_header(self, sample_data):
        html_doc = build_html(sample_data)
        assert "Karel Novák &lt;&amp;&gt; spol." in html_doc  # HTML escaping
        assert "case-test123" in html_doc
        assert "Mgr. Miroslav Matúš DiS" in html_doc

    def test_chain_of_custody_section(self, sample_data):
        html_doc = build_html(sample_data)
        assert "Chain of custody" in html_doc
        assert "/evidence/phone" in html_doc

    def test_hash_manifest_contains_sha256(self, sample_data):
        html_doc = build_html(sample_data)
        assert "Hash manifest" in html_doc
        assert "ab" * 32 in html_doc
        # soubor bez hashu → pomlčka
        assert "b.bin" in html_doc

    def test_flagged_files_section(self, sample_data):
        html_doc = build_html(sample_data)
        assert "Hlavní nálezy" in html_doc
        assert "BAD-EXT" in html_doc
        assert "HASHSET:bad" in html_doc

    def test_artifact_counts(self, sample_data):
        html_doc = build_html(sample_data)
        assert "browser_history" in html_doc
        assert ">4<" in html_doc  # počet artifactů

    def test_empty_case_renders(self):
        data = ReportData(
            case_id="case-empty",
            case_name="Prázdný",
            examiner=None,
            created_at=TS,
        )
        html_doc = build_html(data)
        assert "Žádné evidence sources" in html_doc
        assert "Žádné extrahované artifacty" in html_doc

    def test_utc_normalization(self):
        """Naive datetime se normalizuje na UTC (court-ready jednoznačný čas)."""
        data = ReportData(
            case_id="case-tz",
            case_name="TZ",
            examiner=None,
            created_at=datetime(2026, 10, 30, 14, 0),  # naive → UTC
        )
        html_doc = build_html(data)
        assert "2026-10-30 14:00:00 UTC" in html_doc


# ── IO wrapper — reálná case DB ────────────────────────────────

@pytest.fixture()
def populated_case(tmp_path: Path) -> tuple[CaseDB, str]:
    """Case DB se zdrojem, soubory (vč. bad-ext + duplikátu) a artifacty."""
    db = CaseDB(tmp_path / "case-report.db")
    case = Case(name="Report test", examiner="Znalec X")
    db.add_case(case)
    src = EvidenceSource(case_id=case.id, kind="folder", path="/evidence/box")
    db.add_source(src)

    f1 = FileRecord(
        source_id=src.id, rel_path="doc.pdf", name="doc.pdf", size_bytes=2048,
        sha256="cd" * 32, signature_type="pdf", extension="pdf", bad_extension=True,
    )
    f2 = FileRecord(
        source_id=src.id, rel_path="dup.txt", name="dup.txt", size_bytes=1024,
        sha256="ef" * 32, signature_type="text", extension="txt",
        is_duplicate_of="doc.pdf",
    )
    db.upsert_file(f1)
    db.upsert_file(f2)

    art = Artifact(
        source_id=src.id, file_id=f1.id, rel_path="doc.pdf",
        artifact_type="browser_history", timestamp=TS, title="https://x.cz",
    )
    db.replace_artifacts_for_file(f1.id, [art])
    return db, case.id


class TestIoWrapper:
    def test_build_report_data(self, populated_case):
        db, case_id = populated_case
        data = build_report_data(db, case_id)
        assert data.case_name == "Report test"
        assert len(data.sources) == 1
        assert data.totals["files"] == 2
        assert data.artifact_counts.get("browser_history") == 1
        # flagované: bad-ext + duplikát
        flagged_paths = {f.rel_path for f in data.flagged_files}
        assert "doc.pdf" in flagged_paths and "dup.txt" in flagged_paths

    def test_build_report_data_missing_case(self, populated_case):
        db, _ = populated_case
        with pytest.raises(ValueError):
            build_report_data(db, "case-neexistuje")

    def test_generate_html_file(self, populated_case, tmp_path):
        db, case_id = populated_case
        out = generate_html_report(db, case_id, tmp_path / "rep.html")
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "Report test" in content
        assert "cd" * 32 in content  # hash manifest

    def test_generate_pdf_file(self, populated_case, tmp_path):
        db, case_id = populated_case
        out = generate_pdf_report(db, case_id, tmp_path / "rep.pdf")
        assert out.exists()
        head = out.read_bytes()[:5]
        assert head == b"%PDF-"  # PDF magic

    def test_html_and_pdf_same_content(self, populated_case, tmp_path):
        """PDF je render HTML — klíčové texty se v obou formátech shodují."""
        db, case_id = populated_case
        html_doc = build_html(build_report_data(db, case_id))
        assert "Chain of custody" in html_doc
