"""E10 — Reporting rozšíření: timeline+korelace v reportu, confidence štítky,
``stopa export`` CLI (CSV/JSON), i18n cs/en.

Domain testy = čistá logika (i18n lookup, confidence mapping, CSV/JSON
serializace — bez IO); DB/CLI testy = syntetická case DB + ``cli.main()``.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

TS = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


# ── i18n — čistá logika (bez IO) ────────────────────────────────


class TestI18n:
    def test_normalize_lang_aliases_and_fallback(self):
        from stopa.domain.i18n import normalize_lang

        assert normalize_lang(None) == "cs"  # výchozí
        assert normalize_lang("EN") == "en"  # case-insensitive
        assert normalize_lang("czech") == "cs"
        assert normalize_lang("english") == "en"
        assert normalize_lang("fr") == "cs"  # neznámý → fallback cs

    def test_t_returns_both_languages(self):
        from stopa.domain.i18n import t

        assert t("sec_timeline", "cs").startswith("Timeline — chronologické")
        assert t("sec_timeline", "en").startswith("Timeline — chronological")
        # neznámý klíč → klíč sám (chyba viditelná při testování)
        assert t("neexistujici_klic", "cs") == "neexistujici_klic"

    def test_t_fmt_interpolation(self):
        from stopa.domain.i18n import t_fmt

        cs = t_fmt("total_line", "cs", files="2", bytes="3 kB", signed=1, bad_ext=0, dups=0)
        assert "CELKEM: 2 souborů" in cs
        en = t_fmt("total_line", "en", files="2", bytes="3 kB", signed=1, bad_ext=0, dups=0)
        assert "TOTAL: 2 files" in en


# ── confidence štítky — čistá logika (bez IO) ────────────────────


class TestConfidenceLabels:
    def test_thresholds(self):
        from stopa.domain.report import confidence_label

        assert confidence_label(0.95) == "conf_verified"  # ≥ 0.8 → ověřeno
        assert confidence_label(0.8) == "conf_verified"  # hranice inclusive
        assert confidence_label(0.7) == "conf_extracted"  # 0.5–0.8 → extrahováno
        assert confidence_label(0.5) == "conf_extracted"  # hranice inclusive
        assert confidence_label(0.49) == "conf_hypothesis"  # < 0.5 → hypotéza
        assert confidence_label(None) == "conf_hypothesis"  # bez skóre → nejslabší

    def test_correlation_confidence_mapping(self):
        from stopa.domain.report import _correlation_confidence_label

        assert _correlation_confidence_label("verified") == "conf_verified"
        assert _correlation_confidence_label("inferred") == "conf_inferred"
        # neznámá hodnota → zobrazení tak, jak je (žádný pad)
        assert _correlation_confidence_label("custom") == "custom"


# ── export — čistá serializace (bez IO) ──────────────────────────


class TestExportSerialization:
    def test_artifact_records_stable_columns(self):
        from stopa.domain.export import ARTIFACT_COLUMNS, artifact_records
        from stopa.models import Artifact

        art = Artifact(
            source_id="src-1", file_id="file-1", rel_path="doc.pdf",
            artifact_type="browser_history", timestamp=TS, title="https://x.cz",
            confidence=0.9, parser_version="t-1.0", extracted_at=TS,
            anomaly_flags=("future_date",), details={"k": "v"},
        )
        recs = artifact_records([art])
        assert len(recs) == 1
        # stabilní sloupce — každý klíč existuje (pořadí = CSV header)
        for col in ARTIFACT_COLUMNS:
            assert col in recs[0]
        assert recs[0]["confidence"] == 0.9
        assert recs[0]["anomaly_flags"] == "future_date"
        assert json.loads(recs[0]["details_json"]) == {"k": "v"}

    def test_csv_escaping_and_none_handling(self):
        from stopa.domain.export import to_csv

        records = [
            {"id": 1, "title": 'Hodnota s "úvodzovkami" a, čárkou', "note": None},
            {"id": 2, "title": "normální", "note": "x"},
        ]
        text = to_csv(records, ("id", "title", "note"))
        rows = list(csv.reader(io.StringIO(text)))
        assert rows[0] == ["id", "title", "note"]  # header
        assert len(rows) == 3
        # csv.writer správně uvozkuje hodnotu s čárkou/úvodzovkami
        assert rows[1][1] == 'Hodnota s "úvodzovkami" a, čárkou'
        # None → prázdné pole (ne řetězec "None")
        assert rows[1][2] == ""

    def test_json_roundtrip_czech(self):
        from stopa.domain.export import to_json

        records = [{"id": 1, "title": "Příliš žluťoučký kůň", "confidence": 0.5}]
        text = to_json(records)
        parsed = json.loads(text)
        assert parsed[0]["title"] == "Příliš žluťoučký kůň"  # ensure_ascii=False


# ── report HTML — timeline + korelace + i18n (bez IO) ────────────


def _data_with_timeline_and_corr() -> object:
    from stopa.domain.report import CorrelationRow, ReportData, TimelineEvent

    return ReportData(
        case_id="case-e10",
        case_name="E10 test",
        examiner=None,
        created_at=TS,
        timeline_events=(
            TimelineEvent(
                ts_utc="2026-10-30T12:00:00+00:00",
                event_type="browser_history",
                title="https://x.cz",
                rel_path="doc.pdf",
                confidence=0.9,
                anomaly_flags=("future_date",),
            ),
        ),
        correlations=(
            CorrelationRow(
                entity_a="user:jan.novak",
                entity_b="host:PC-OFFICE",
                relation="temporal_overlap",
                confidence="inferred",
                evidence=({"rel_path": "doc.pdf", "detail": "SHA-256 cdcd… (2048 B)"},),
            ),
        ),
    )


class TestReportSections:
    def test_timeline_section_cs_with_local_time(self):
        from stopa.domain.report import build_html

        html_doc = build_html(_data_with_timeline_and_corr())  # výchozí cs
        assert "Timeline — chronologické události" in html_doc
        # UTC sloupec + lokální čas (Europe/Prague v říjnu = UTC+1 → 13:00)
        assert "2026-10-30 12:00:00" in html_doc  # UTC
        assert "2026-10-30 13:00:00" in html_doc  # lokální (UTC+1)
        assert "Čas (lokální Europe/Prague)" in html_doc
        # confidence štítek + hodnota + anomaly flag
        assert "[ověřeno] 0.90" in html_doc
        assert "future_date" in html_doc

    def test_correlations_section_with_evidence(self):
        from stopa.domain.report import build_html

        html_doc = build_html(_data_with_timeline_and_corr())
        assert "Propojení entity (korelace)" in html_doc
        assert "user:jan.novak" in html_doc and "host:PC-OFFICE" in html_doc
        assert "temporal_overlap" in html_doc
        # confidence korelace (string verified/inferred) → štítek [odvozeno]
        assert "[odvozeno]" in html_doc
        # evidence odkaz — detail + rel_path dohledatelné v reportu
        assert "SHA-256 cdcd… (2048 B)" in html_doc
        assert "(doc.pdf)" in html_doc

    def test_empty_sections_render_placeholders(self):
        from stopa.domain.report import ReportData, build_html

        html_doc = build_html(ReportData(case_id="c", case_name="x", examiner=None, created_at=TS))
        assert "Žádné timeline události" in html_doc
        assert "Žádná propojení" in html_doc

    def test_english_report_switches_all_keys(self):
        from stopa.domain.report import build_html

        html_doc = build_html(_data_with_timeline_and_corr(), lang="en")
        assert "<html lang='en'>" in html_doc
        assert "Timeline — chronological events" in html_doc
        assert "Entity correlations" in html_doc
        assert "[verified] 0.90" in html_doc  # confidence štítek EN
        assert "[inferred]" in html_doc  # korelační confidence EN
        assert "Local time (Europe/Prague)" in html_doc
        # čeština v EN reportu neuteče (hlavičky sekcí)
        assert "chronologické události" not in html_doc


# ── IO wrapper + CLI — reálná case DB ────────────────────────────


@pytest.fixture()
def e10_case(tmp_path: Path, monkeypatch) -> tuple[object, str]:
    """Case DB (soubor pojmenovaný `<case_id>.db`, jako `stopa case new`) s
    artifactem (confidence), timeline eventem a korelací."""
    from stopa import cli
    from stopa.data.db import CaseDB
    from stopa.models import Artifact, EvidenceSource, FileRecord

    monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
    assert cli.main(["case", "new", "E10 IO"]) == 0
    case_id = next(iter(list(tmp_path.glob("*.db")))).stem
    db = CaseDB(tmp_path / f"{case_id}.db")
    src = EvidenceSource(case_id=case_id, kind="folder", path="/evidence/box")
    db.add_source(src)
    f1 = FileRecord(
        source_id=src.id, rel_path="doc.pdf", name="doc.pdf", size_bytes=2048,
        sha256="cd" * 32, signature_type="pdf", extension="pdf",
    )
    db.upsert_file(f1)
    art = Artifact(
        source_id=src.id, file_id=f1.id, rel_path="doc.pdf",
        artifact_type="browser_history", timestamp=TS, title="https://x.cz",
        confidence=0.9, parser_version="t-1.0", extracted_at=TS,
    )
    db.replace_artifacts_for_file(f1.id, [art])
    db.add_timeline_event(
        source_id=src.id, artifact_id=art.id, file_id=f1.id, rel_path="doc.pdf",
        event_type="browser_history", ts_utc=TS, title="https://x.cz",
        confidence=0.9, parser_version="t-1.0", extracted_at=TS,
    )
    db.add_correlation(
        case_id, "user:jan.novak", "host:PC-OFFICE", "temporal_overlap", "inferred",
        [{"rel_path": "doc.pdf", "detail": "SHA-256 cdcd… (2048 B)"}],
    )
    return db, case_id


class TestIoAndCli:
    def test_build_report_data_populates_new_sections(self, e10_case):
        from stopa.presentation.case_report import build_report_data

        db, case_id = e10_case
        data = build_report_data(db, case_id)
        assert len(data.timeline_events) == 1
        assert data.timeline_events[0].confidence == 0.9
        assert len(data.correlations) == 1
        assert data.correlations[0].relation == "temporal_overlap"
        assert data.timezone_name  # TZ pro lokální čas je nastavená

    def test_generate_html_report_lang_param(self, e10_case, tmp_path):
        from stopa.presentation.case_report import generate_html_report

        db, case_id = e10_case
        cs = generate_html_report(db, case_id, tmp_path / "cs.html").read_text(encoding="utf-8")
        en = generate_html_report(
            db, case_id, tmp_path / "en.html", lang="en"
        ).read_text(encoding="utf-8")
        assert "<html lang='cs'>" in cs and "[ověřeno] 0.90" in cs
        assert "<html lang='en'>" in en and "[verified] 0.90" in en

    def test_cli_export_artifacts_csv_file(self, e10_case, tmp_path):
        from stopa import cli

        db, case_id = e10_case
        db.close()
        out = tmp_path / "art.csv"
        assert cli.main(["export", case_id, "--what", "artifacts",
                         "--format", "csv", "--out", str(out)]) == 0
        rows = list(csv.reader(io.StringIO(out.read_text(encoding="utf-8"))))
        assert rows[0][0] == "id" and "artifact_type" in rows[0]  # header
        assert len(rows) == 2  # 1 artifact
        assert "browser_history" in rows[1]

    def test_cli_export_correlations_json_stdout(self, e10_case, tmp_path, capsys):
        from stopa import cli

        db, case_id = e10_case
        db.close()
        assert cli.main(["export", case_id, "--what", "correlations",
                         "--format", "json"]) == 0
        captured = capsys.readouterr().out
        parsed = json.loads(captured)
        assert len(parsed) == 1
        assert parsed[0]["relation"] == "temporal_overlap"
        ev = json.loads(parsed[0]["evidence_json"])
        assert ev[0]["rel_path"] == "doc.pdf"

    def test_cli_export_timeline_csv_limit(self, e10_case, tmp_path):
        from stopa import cli

        db, case_id = e10_case
        db.close()
        out = tmp_path / "tl.csv"
        assert cli.main(["export", case_id, "--what", "timeline",
                         "--format", "csv", "--limit", "5", "--out", str(out)]) == 0
        rows = list(csv.reader(io.StringIO(out.read_text(encoding="utf-8"))))
        assert "ts_utc" in rows[0] and "event_type" in rows[0]
        assert len(rows) == 2  # header + 1 událost
