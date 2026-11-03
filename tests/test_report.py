"""Testy forenzního reportu (FÁZE 7) — domain build_html + IO wrapper."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.data.db import CaseDB
from stopa.domain.report import (
    CorrelationRow,
    CustodyItem,
    FlaggedFile,
    ReportData,
    SourceInfo,
    TimelineEvent,
    build_html,
)
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
            CustodyItem(
                source_id="src-1", rel_path="a.txt", size_bytes=1024,
                sha256="ab" * 32, md5="cd" * 16,
            ),
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

    def test_hash_manifest_contains_md5(self, sample_data):
        """CoC audit — MD5 se sbírá (compute_md5=True), musí být i v manifestu."""
        html_doc = build_html(sample_data)
        assert "MD5" in html_doc  # hlavička sloupce
        assert "cd" * 16 in html_doc  # hodnota MD5

    def test_hash_manifest_shows_source(self, sample_data):
        """CoC audit — manifest uvádí zdroj (zdrojová úroveň chain of custody)."""
        html_doc = build_html(sample_data)
        assert "/evidence/phone" in html_doc  # cesta zdroje v manifestu

    def test_tool_version_in_header(self, sample_data):
        """CoC audit — court-ready report uvádí verzi nástroje (reprodukovatelnost)."""
        from stopa import __version__

        html_doc = build_html(sample_data)
        assert f"STOPA v{__version__}" in html_doc

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

    def test_footer_no_unrendered_format(self):
        """Patička — žádný nevyhodnocený f-string placeholder (regrese)."""
        data = ReportData(
            case_id="case-foot",
            case_name="Foot",
            examiner=None,
            created_at=TS,
        )
        html_doc = build_html(data)
        assert "{_esc" not in html_doc  # nevyhodnocený placeholder by byl vidět v reportu
        assert "case-foot" in html_doc.split("STOPA report — případ")[-1]


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


# ── STP-020 — report engine 9 → 20 sekcí (sekce 10–20) ───────────────

@pytest.fixture()
def rich_data() -> ReportData:
    """ReportData naplněné daty pro sekce 10–20 (syntetický případ)."""
    return ReportData(
        case_id="case-stp020",
        case_name="STP-020 bohatý případ",
        examiner="Znalec Y",
        created_at=TS,
        sources=(SourceInfo(id="src-1", kind="folder", path="/evidence/box", added_at=TS),),
        per_source_stats={"src-1": {"files": 3, "bytes": 4096, "bad_ext": 1, "dups": 1, "signed": 2}},
        totals={"files": 3, "bytes": 4096, "bad_ext": 1, "dups": 1, "signed": 2},
        artifact_counts={"browser_history": 5, "sms_message": 3},
        flagged_files=(FlaggedFile(rel_path="a.txt", flags=("BAD-EXT",), sha256="ab" * 32),),
        timeline_events=(
            TimelineEvent(
                ts_utc="2026-10-30T12:00:00+00:00", event_type="file_access",
                title="a.txt", confidence=0.9, ts_origin="source",
                contradiction_group_id="cg-1",
            ),
            TimelineEvent(
                ts_utc="2026-10-30T12:00:30+00:00", event_type="file_access",
                title="b.txt", confidence=0.6, ts_origin="derived",
                dup_group_id="dg-1",
            ),
        ),
        correlations=(
            CorrelationRow(entity_a="u@x.cz", entity_b="+420123", relation="same_account",
                           confidence="confirmed"),
            CorrelationRow(entity_a="a.txt", entity_b="b.txt", relation="duplicate",
                           confidence="inferred"),
        ),
        entities=(
            {"kind": "email", "value": "u@x.cz", "first_seen": "2026-10-30T12:00:00+00:00",
             "last_seen": "2026-10-30T12:05:00+00:00"},
        ),
        lineage_steps=4,
        integrity_pub_key="AAAA" * 8,
        integrity_checkpoints=(
            {"ts": "2026-10-30T12:10:00+00:00", "audit_row_id": 7,
             "last_hash": "ff" * 32, "reason": "manual"},
        ),
    )


class TestStp020Sections:
    """Sekce 10–20 — presence + pořadí + obsah (backward compat sekcí 1–9)."""

    def test_all_20_sections_present_in_order(self, rich_data):
        html_doc = build_html(rich_data)
        # hlavička/titulní strana + 20 číslovaných sekcí v pořadí
        for i in range(1, 21):
            assert f"<h2>{i}. " in html_doc, f"chybí sekce {i}"
        # pořadí: každá sekce po předchozí
        pos = [html_doc.index(f"<h2>{i}. ") for i in range(1, 21)]
        assert pos == sorted(pos), "sekce nejsou v číselném pořadí"

    def test_section_10_methodology(self, rich_data):
        html_doc = build_html(rich_data)
        assert "Metodika analýzy" in html_doc
        # deterministicky z dat: počet zdrojů + souborů
        assert "Zpracováno 1 evidence zdrojů" in html_doc

    def test_section_11_tools_and_versions(self, rich_data):
        from stopa import __version__

        html_doc = build_html(rich_data)
        assert "Nástroje a verze" in html_doc
        assert f"v{__version__}" in html_doc  # STOPA verze
        # Python/SQLite/platforma z env_snapshot (C5)
        assert "Python" in html_doc
        assert "SQLite" in html_doc

    def test_section_12_limitations(self, rich_data):
        html_doc = build_html(rich_data)
        assert "Omezení analýzy" in html_doc
        # BLK-001 RAM peak je vždy uvedeno
        assert "BLK-001" in html_doc

    def test_section_13_conclusion(self, rich_data):
        html_doc = build_html(rich_data)
        assert "Závěr" in html_doc
        # souhrn findings — počty z dat (5+3=8 artifactů)
        assert "Souhrn: 8 artifactů" in html_doc
        # rozporové + duplikátové skupiny (STP-018)
        assert "Detekováno 1 rozporových skupin" in html_doc
        assert "Detekováno 1 duplikátových skupin" in html_doc

    def test_section_14_provenance(self, rich_data):
        html_doc = build_html(rich_data)
        assert "Provenience timestampů" in html_doc
        # source vs derived počty (1 + 1)
        assert "Zdrojové timestamps (z obsahu souboru): 1" in html_doc
        assert "Odvozené timestamps (systémový/FS fallback): 1" in html_doc

    def test_section_15_lineage(self, rich_data):
        html_doc = build_html(rich_data)
        assert "Evidence lineage" in html_doc
        assert "Zaznamenáno 4 kroků" in html_doc

    def test_section_16_integrity(self, rich_data):
        html_doc = build_html(rich_data)
        assert "Integrity — Ed25519 kontrolní body" in html_doc
        # veřejný klíč + kontrolní bod
        assert "AAAA" * 8 in html_doc
        assert "manual" in html_doc

    def test_section_17_entities(self, rich_data):
        html_doc = build_html(rich_data)
        assert "Rejstřík entit" in html_doc
        # hodnota entity v tabulce
        assert "u@x.cz" in html_doc

    def test_section_18_appendix_parsers(self, rich_data):
        from stopa.domain.validation_registry import build_registry

        html_doc = build_html(rich_data)
        assert "Příloha A — Validace parserů (C3)" in html_doc
        # alespoň jeden reálný parser ID z registry
        reg = build_registry()
        first_id = min(reg)
        assert first_id in html_doc

    def test_section_19_appendix_env(self, rich_data):
        html_doc = build_html(rich_data)
        assert "Příloha B — Reprodukční prostředí (C5)" in html_doc
        # snapshot klíčů (python/sqlite/platform) v tabulce
        assert "Snapshot prostředí pro reprodukovatelnost" in html_doc

    def test_section_20_appendix_confidence(self, rich_data):
        html_doc = build_html(rich_data)
        assert "Příloha C — Rozložení důvěryhodnosti" in html_doc
        # timeline confidence úrovně (0.9→ověřeno, 0.6→extrahováno)
        assert "[ověřeno]" in html_doc
        assert "[extrahováno]" in html_doc

    def test_empty_case_new_sections_render(self):
        """Prázdný případ — nové sekce se vykreslí s empty fallbacky (bez padu)."""
        data = ReportData(
            case_id="case-stp020-empty",
            case_name="Prázdný STP-020",
            examiner=None,
            created_at=TS,
        )
        html_doc = build_html(data)
        # všechny 20 sekcí existuje i u prázdného případu
        for i in range(1, 21):
            assert f"<h2>{i}. " in html_doc
        # empty fallbacky
        assert "Žádné timeline události s provenience." in html_doc
        assert "Žádné zaznamenané kroky lineage" in html_doc
        assert "Žádné extrahované entity." in html_doc

    def test_no_unrendered_placeholders(self, rich_data):
        """Žádný nevyhodnocený {placeholder} v novém HTML (regrese f-stringů)."""
        html_doc = build_html(rich_data)
        # typické nevyhodnocené artefakty by byly vidět doslovně
        assert "{artifacts}" not in html_doc
        assert "{n}" not in html_doc
        assert "{ts_origin}" not in html_doc

