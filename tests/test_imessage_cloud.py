"""Testy iCloud Messages extraktoru — cloud varianta iMessage (warrant return).

Offline: delimited text (TSV/CSV) + sloupcové mapování + časová konverze.
XLSX přes openpyxl (volitelné extra `[xlsx]`) — importorskip, když není nainstalovaný.
E2E: name-based fallback v pipeline (`process_source`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.artifacts.imessage_cloud import (
    _find_column,
    _normalize_header,
    _parse_timestamp,
    extract_icloud_messages,
    is_icloud_messages_file,
)

# ── detekce podle názvu ───────────────────────────────────────────

class TestNameDetection:
    def test_detects_lowercase(self):
        assert is_icloud_messages_file("MessagesInICloud.csv")

    def test_detects_case_insensitive(self):
        assert is_icloud_messages_file("messagesinicloud.csv")
        assert is_icloud_messages_file("MESSAGESINICLOUD.XLSX")

    def test_detects_in_path_basename(self):
        # detekce pracuje s názvem, ne celou cestou — ale marker v názvu stačí
        assert is_icloud_messages_file("[Apple_Request]-MessagesInICloud-1.csv")

    def test_rejects_unrelated(self):
        assert not is_icloud_messages_file("chat.db")
        assert not is_icloud_messages_file("messages.txt")  # bez "inicloud"


# ── normalizace hlaviček + mapování sloupců ───────────────────────

class TestHeaderMapping:
    def test_normalize_strips_case_and_nonalnum(self):
        assert _normalize_header("IsFromMe") == "isfromme"
        assert _normalize_header("Message ID") == "messageid"
        assert _normalize_header("Date Sent") == "datesent"

    def test_find_column_exact(self):
        headers = ["MessageID", "Text", "Date", "IsFromMe"]
        assert _find_column(headers, ("text",)) == 1
        assert _find_column(headers, ("date",)) == 2
        assert _find_column(headers, ("isfromme",)) == 3

    def test_find_column_substring_fallback(self):
        headers = ["MessageID", "BodyText", "DateSent"]
        # 'text' není přesná shoda → substring v 'bodytext'
        assert _find_column(headers, ("text",)) == 1
        # 'date' substring v 'datesent'
        assert _find_column(headers, ("date",)) == 2

    def test_find_column_missing(self):
        headers = ["Foo", "Bar"]
        assert _find_column(headers, ("text",)) is None


# ── časová konverze ───────────────────────────────────────────────

class TestTimestampParsing:
    def test_iso_space_format(self):
        ts = _parse_timestamp("2024-03-15 12:34:56")
        assert ts == datetime(2024, 3, 15, 12, 34, 56, tzinfo=timezone.utc)

    def test_iso_t_format(self):
        ts = _parse_timestamp("2024-03-15T12:34:56")
        assert ts == datetime(2024, 3, 15, 12, 34, 56, tzinfo=timezone.utc)

    def test_iso_with_micros(self):
        ts = _parse_timestamp("2024-03-15T12:34:56.789")
        assert ts == datetime(2024, 3, 15, 12, 34, 56, 789000, tzinfo=timezone.utc)

    def test_epoch_seconds(self):
        # unix 1710506096 = 2024-03-15T12:34:56Z
        ts = _parse_timestamp("1710506096")
        assert ts == datetime(2024, 3, 15, 12, 34, 56, tzinfo=timezone.utc)

    def test_epoch_millis(self):
        ts = _parse_timestamp("1710506096000")
        assert ts == datetime(2024, 3, 15, 12, 34, 56, tzinfo=timezone.utc)

    def test_datetime_object_naive_assumed_utc(self):
        dt = datetime(2024, 3, 15, 12, 34, 56)  # naivní (openpyxl vrací bez tz)
        ts = _parse_timestamp(dt)
        assert ts == datetime(2024, 3, 15, 12, 34, 56, tzinfo=timezone.utc)

    def test_empty_and_none(self):
        assert _parse_timestamp(None) is None
        assert _parse_timestamp("") is None
        assert _parse_timestamp("   ") is None

    def test_unrecognized_returns_none(self):
        assert _parse_timestamp("not a date") is None


# ── delimited text extrakce (TSV/CSV) ─────────────────────────────

def _write_tsv(path: Path, header: str, rows: list[list[str]]) -> Path:
    lines = [header] + ["\t".join(r) for r in rows]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


class TestDelimitedText:
    def test_extracts_messages_tsv(self, tmp_path):
        p = _write_tsv(
            tmp_path / "MessagesInICloud.csv",
            "MessageID\tText\tDate\tIsFromMe\tHandle",
            [
                ["1", "Ahoj, kde jsi?", "2024-03-15 12:34:56", "TRUE", "+420****3456"],
                ["2", "U obchodu", "2024-03-15 12:40:00", "FALSE", "+420****3456"],
            ],
        )
        arts = extract_icloud_messages(p)
        assert len(arts) == 2
        assert all(a.artifact_type == "imessage" for a in arts)
        assert all(a.details["engine"] == "icloud_messages" for a in arts)

    def test_timestamps_and_details(self, tmp_path):
        p = _write_tsv(
            tmp_path / "MessagesInICloud.csv",
            "MessageID\tText\tDate\tIsFromMe\tHandle",
            [["1", "Ahoj", "2024-03-15 12:34:56", "TRUE", "+420****3456"]],
        )
        arts = extract_icloud_messages(p)
        assert arts[0].timestamp == datetime(2024, 3, 15, 12, 34, 56, tzinfo=timezone.utc)
        assert arts[0].title == "Ahoj"
        assert arts[0].details["handle"] == "+420****3456"
        assert arts[0].details["direction"] == "TRUE"

    def test_comma_delimited(self, tmp_path):
        p = tmp_path / "MessagesInICloud.csv"
        p.write_text(
            "MessageID,Text,Date\n1,Ahoj,2024-03-15 12:34:56\n", encoding="utf-8"
        )
        arts = extract_icloud_messages(p)
        assert len(arts) == 1
        assert arts[0].title == "Ahoj"

    def test_metadata_rows_above_header(self, tmp_path):
        """Apple export má nad hlavičkou metadata — detekce najde správný řádek."""
        p = tmp_path / "MessagesInICloud.csv"
        content = (
            "Export generated by Apple\n"
            "Request ID: 12345\n"
            "\n"
            "MessageID\tText\tDate\tIsFromMe\n"
            "1\tAhoj\t2024-03-15 12:34:56\tTRUE\n"
        )
        p.write_text(content, encoding="utf-8")
        arts = extract_icloud_messages(p)
        assert len(arts) == 1
        assert arts[0].title == "Ahoj"

    def test_empty_rows_skipped(self, tmp_path):
        p = _write_tsv(
            tmp_path / "MessagesInICloud.csv",
            "MessageID\tText\tDate",
            [["1", "Ahoj", "2024-03-15 12:34:56"], ["", "", ""], ["2", "Bye", "2024-03-15 13:00:00"]],
        )
        arts = extract_icloud_messages(p)
        assert len(arts) == 2

    def test_empty_text_placeholder(self, tmp_path):
        p = _write_tsv(
            tmp_path / "MessagesInICloud.csv",
            "MessageID\tText\tDate",
            [["1", "", "2024-03-15 12:34:56"]],
        )
        arts = extract_icloud_messages(p)
        assert len(arts) == 1
        assert arts[0].title == "(prázdná zpráva)"

    def test_no_header_returns_empty(self, tmp_path):
        p = tmp_path / "MessagesInICloud.csv"
        p.write_text("random\ndata\nno known columns here\n", encoding="utf-8")
        assert extract_icloud_messages(p) == []

    def test_missing_file_returns_empty(self, tmp_path):
        assert extract_icloud_messages(tmp_path / "chybi.csv") == []


# ── XLSX varianta (openpyxl — volitelné extra [xlsx]) ─────────────

class TestXlsx:
    @pytest.fixture()
    def xlsx_file(self, tmp_path):
        pytest.importorskip("openpyxl")
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        # metadata řádky nad hlavičkou (Apple export)
        ws.append(["Export generated by Apple"])
        ws.append(["Request ID: 12345"])
        ws.append([])
        ws.append(["MessageID", "Text", "Date", "IsFromMe", "Handle"])
        ws.append([1, "Ahoj, kde jsi?", datetime(2024, 3, 15, 12, 34, 56), True, "+420****3456"])
        ws.append([2, "U obchodu", datetime(2024, 3, 15, 12, 40, 0), False, "+420****3456"])
        p = tmp_path / "MessagesInICloud.csv"  # xlsx s příponou .csv (reálný případ)
        wb.save(p)
        return p

    def test_extracts_from_xlsx(self, xlsx_file):
        arts = extract_icloud_messages(xlsx_file)
        assert len(arts) == 2
        assert all(a.artifact_type == "imessage" for a in arts)
        assert all(a.details["engine"] == "icloud_messages" for a in arts)

    def test_xlsx_timestamps(self, xlsx_file):
        arts = extract_icloud_messages(xlsx_file)
        ts = sorted(a.timestamp for a in arts if a.timestamp)
        assert ts[0] == datetime(2024, 3, 15, 12, 34, 56, tzinfo=timezone.utc)

    def test_xlsx_details(self, xlsx_file):
        arts = extract_icloud_messages(xlsx_file)
        assert all(a.details["handle"] == "+420****3456" for a in arts)


# ── E2E: name-based fallback v pipeline ───────────────────────────

class TestPipelineFallback:
    def test_process_source_extracts_icloud(self, tmp_path):
        from stopa.data.db import CaseDB
        from stopa.models import Case, EvidenceSource
        from stopa.pipeline import process_source

        db = CaseDB(tmp_path / "case.db")
        db.add_case(Case(id="case-icloud", name="iCloud test"))
        root = tmp_path / "warrant"
        root.mkdir()
        _write_tsv(
            root / "[Apple_Request]-MessagesInICloud-1.csv",
            "MessageID\tText\tDate\tIsFromMe\tHandle",
            [["1", "Ahoj z cloudu", "2024-03-15 12:34:56", "TRUE", "+420****3456"]],
        )
        src = EvidenceSource(case_id="case-icloud", kind="folder", path=str(root))
        db.add_source(src)

        result = process_source(db, src.id, root, "forensic")
        assert result.artifacts_extracted == 1

        arts = db.list_artifacts(src.id)
        assert len(arts) == 1
        assert arts[0].artifact_type == "imessage"
        assert arts[0].details["engine"] == "icloud_messages"
        assert arts[0].title == "Ahoj z cloudu"

    def test_regular_file_not_affected(self, tmp_path):
        """Soubor bez iCloud markeru v názvu → žádný artifact (fallback nespálí vše)."""
        from stopa.data.db import CaseDB
        from stopa.models import Case, EvidenceSource
        from stopa.pipeline import process_source

        db = CaseDB(tmp_path / "case.db")
        db.add_case(Case(id="case-plain", name="Plain test"))
        root = tmp_path / "src"
        root.mkdir()
        (root / "notes.txt").write_text("jen text bez signatury\n", encoding="utf-8")
        src = EvidenceSource(case_id="case-plain", kind="folder", path=str(root))
        db.add_source(src)

        result = process_source(db, src.id, root, "forensic")
        assert result.artifacts_extracted == 0
