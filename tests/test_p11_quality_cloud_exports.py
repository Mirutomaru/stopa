"""P1-1 quality vlna 12 — cloud export rodina (5 parserů).

Dokončení zbývajících kategorií u cloud export parserů:
box_cloud / dropbox_mega / cloud_drive_files / icloud_messages +
{corrupted, encoding, locale, size, tz}, cloud_generic + {locale, negative}.

Kontrakty doložené ze zdrojů (src/stopa/artifacts/*.py):
- JSON rodina (box/dropbox/drive/generic) dekoduje přes utf-8 s
  errors="replace" → BOM prefix / binární smetí / oříznuté JSON →
  ValueError "Neplatné JSON: ..."; platné JSON bez záznamů → TypeError.
- Časová ekvivalence: epoch s == epoch ms (>=1e12 → /1000) == ISO Z ==
  ISO offset +02:00; naive ISO string se interpretuje jako UTC.
- icloud_messages = file-based extractor (CSV/xlsx): chyby → log + []
  (nikdy výjimka nahoru), hlavička se detekuje v prvních
  MAX_HEADER_SCAN_ROWS=15 řádcích, BOM je stripnut (utf-8-sig).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stopa.artifacts.box_cloud import parse_box_cloud
from stopa.artifacts.cloud_drive_files import parse_cloud_drive_files
from stopa.artifacts.cloud_generic import parse_cloud_generic
from stopa.artifacts.dropbox_mega import parse_dropbox_mega
from stopa.artifacts.imessage_cloud import extract_icloud_messages

# quality: corrupted encoding locale negative size tz

TS_S = 1_750_000_000
TS_MS = TS_S * 1000
_DT = datetime.fromtimestamp(TS_S, tz=timezone.utc)
ISO_Z = _DT.isoformat()
ISO_OFFSET = _DT.astimezone(timezone(timedelta(hours=2))).isoformat()
NAIVE_UTC = _DT.strftime("%Y-%m-%dT%H:%M:%S")  # naive → interpretace jako UTC
TSV_TS = _DT.strftime("%Y-%m-%d %H:%M:%S")


def _js(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------------------
# box_cloud — corrupted / encoding / locale / size / tz
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [b"\xef\xbb\xbf" + b'[]', b"\x00\x01\xff\xfe{binarni-smeti", b'{"name": '],
    ids=["bom_prefix", "binary_garbage", "truncated"],
)
def test_box_corrupted(payload: bytes) -> None:
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_box_cloud(payload)


def test_box_encoding_diacritics_roundtrip() -> None:
    payload = _js(
        [
            {"name": "Přehled faktur 2026.pdf", "type": "file", "size": 1234},
            {
                "type": "comment",
                "message": "Štěpán poslal smlouvu pro Janu",
                "created_by": {"name": "Jan Novák"},
            },
        ]
    )
    records = parse_box_cloud(payload)
    assert records[0].name == "Přehled faktur 2026.pdf"
    assert records[0].size == 1234
    comment = records[1]
    assert comment.kind == "comment"
    assert comment.message == "Štěpán poslal smlouvu pro Janu"
    assert comment.author == "Jan Novák"


def test_box_locale_czech_event() -> None:
    payload = _js(
        [
            {
                "event_type": "soubor.nahrání",
                "record_name": "Diplomová práce — finální verze.docx",
                "actor": {"name": "Marek Dvořák"},
                "created_at": ISO_Z,
            }
        ]
    )
    (rec,) = parse_box_cloud(payload)
    assert rec.kind == "event"
    assert rec.name == "Diplomová práce — finální verze.docx"
    assert rec.author == "Marek Dvořák"
    assert rec.action == "soubor.nahrání"


def test_box_size_truncation_5001_to_5000() -> None:
    payload = _js([{"name": f"soubor-{i}.txt", "type": "file"} for i in range(5001)])
    records = parse_box_cloud(payload)
    assert len(records) == 5000
    assert records[0].name == "soubor-0.txt"
    assert records[-1].name == "soubor-4999.txt"


@pytest.mark.parametrize(
    "ts",
    [TS_S, TS_MS, ISO_Z, ISO_OFFSET, NAIVE_UTC],
    ids=["epoch_s", "epoch_ms", "iso_z", "iso_offset+02:00", "naive_utc"],
)
def test_box_tz_epoch_formats_equivalence(ts: object) -> None:
    payload = _js(
        [{"event_type": "file.upload", "record_name": "x.pdf", "created_at": ts}]
    )
    (rec,) = parse_box_cloud(payload)
    assert rec.created_s == float(TS_S)


# ---------------------------------------------------------------------------
# dropbox_mega — corrupted / encoding / locale / size / tz
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [b"\xef\xbb\xbf" + b'[]', b"\x00\x01\xff\xfe{binarni-smeti"],
    ids=["bom_prefix", "binary_garbage"],
)
def test_dropbox_corrupted(payload: bytes) -> None:
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_dropbox_mega(payload)


def test_dropbox_encoding_diacritics_roundtrip() -> None:
    payload = _js(
        [
            {
                "name": "Dokument s diakritikou.pdf",
                "path_lower": "smlouvy/2026/dohlednost-česká.pdf",
                "bytes": 42,
            }
        ]
    )
    (rec,) = parse_dropbox_mega(payload)
    assert rec.name == "Dokument s diakritikou.pdf"
    assert rec.path == "smlouvy/2026/dohlednost-česká.pdf"
    assert rec.size == 42


def test_dropbox_locale_czech_name_folder() -> None:
    payload = _js([{"name": "Faktury za leden", "is_dir": True}])
    (rec,) = parse_dropbox_mega(payload)
    assert rec.kind == "folder"
    assert rec.name == "Faktury za leden"
    assert rec.size is None


def test_dropbox_size_truncation_5001_to_5000() -> None:
    payload = _js([{"name": f"soubor-{i}.txt"} for i in range(5001)])
    records = parse_dropbox_mega(payload)
    assert len(records) == 5000
    assert records[0].name == "soubor-0.txt"
    assert records[-1].name == "soubor-4999.txt"


@pytest.mark.parametrize(
    "ts",
    [TS_S, TS_MS, ISO_Z, ISO_OFFSET, NAIVE_UTC],
    ids=["epoch_s", "epoch_ms", "iso_z", "iso_offset+02:00", "naive_utc"],
)
def test_dropbox_tz_modified_formats_equivalence(ts: object) -> None:
    payload = _js([{"name": "f.pdf", "server_modified": ts}])
    (rec,) = parse_dropbox_mega(payload)
    assert rec.modified_s == float(TS_S)


# ---------------------------------------------------------------------------
# cloud_drive_files — corrupted / encoding / locale / size / tz
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [b"\xef\xbb\xbf" + b'[]', b"\x00\x01\xff\xfe{binarni-smeti", b'{"name": '],
    ids=["bom_prefix", "binary_garbage", "truncated"],
)
def test_cloudfiles_corrupted(payload: bytes) -> None:
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_cloud_drive_files(payload)


def test_cloudfiles_encoding_diacritics_roundtrip() -> None:
    payload = _js(
        [
            {
                "name": "Přehled faktur Q4.xlsx",
                "sizeBytes": 98765,
                "md5Checksum": "abc123def456",
            }
        ]
    )
    (rec,) = parse_cloud_drive_files(payload)
    assert rec.name == "Přehled faktur Q4.xlsx"
    assert rec.size_bytes == 98765
    assert rec.checksum == "abc123def456"


def test_cloudfiles_locale_czech_name_owner() -> None:
    payload = _js(
        [
            {
                "name": "Návrh smlouvy pro páně Dvořáka.docx",
                "owners": [{"emailAddress": "uživatel@příklad.cz"}],
            }
        ]
    )
    (rec,) = parse_cloud_drive_files(payload)
    assert rec.name == "Návrh smlouvy pro páně Dvořáka.docx"
    assert rec.owner == "uživatel@příklad.cz"


def test_cloudfiles_size_truncation_5001_to_5000() -> None:
    payload = _js([{"name": f"soubor-{i}.txt"} for i in range(5001)])
    records = parse_cloud_drive_files(payload)
    assert len(records) == 5000
    assert records[0].name == "soubor-0.txt"
    assert records[-1].name == "soubor-4999.txt"


@pytest.mark.parametrize(
    "ts",
    [TS_S, TS_MS, ISO_Z, ISO_OFFSET, NAIVE_UTC],
    ids=["epoch_s", "epoch_ms", "iso_z", "iso_offset+02:00", "naive_utc"],
)
def test_cloudfiles_tz_createdtime_formats_equivalence(ts: object) -> None:
    payload = _js([{"name": "x.pdf", "createdTime": ts, "modifiedTime": ts}])
    (rec,) = parse_cloud_drive_files(payload)
    assert rec.created_s == float(TS_S)
    assert rec.modified_s == float(TS_S)


# ---------------------------------------------------------------------------
# icloud_messages — corrupted / encoding / locale / size / tz (file-based)
# ---------------------------------------------------------------------------


def _write_tsv(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_icloud_corrupted_binary_garbage_graceful(tmp_path: Path) -> None:
    p = tmp_path / "export.csv"
    p.write_bytes(b"\x00\x01\xff\xfePK?binarni-smeti\n")  # bez xlsx magicu PK\x03\x04
    assert extract_icloud_messages(p) == []


def test_icloud_encoding_bom_and_diacritics(tmp_path: Path) -> None:
    rows = ["text\ttimestamp", "Ahoj světe, Štěpáne.\t" + TSV_TS]
    with_bom = _write_tsv(tmp_path / "bom.csv", ["\ufeff"] + [rows[0]] + rows[1:])
    plain = _write_tsv(tmp_path / "plain.csv", rows)
    arts_bom = extract_icloud_messages(with_bom)
    arts_plain = extract_icloud_messages(plain)
    assert len(arts_bom) == 1 and len(arts_plain) == 1
    assert arts_bom[0].title == "Ahoj světe, Štěpáne."
    assert arts_bom[0].title == arts_plain[0].title


def test_icloud_locale_czech_roundtrip(tmp_path: Path) -> None:
    p = _write_tsv(
        tmp_path / "cz.csv",
        ["text\thandle\ttimestamp", "Dobrý den, pane Dvořáku!\t+420123456789\t" + TSV_TS],
    )
    (art,) = extract_icloud_messages(p)
    assert art.title == "Dobrý den, pane Dvořáku!"
    assert art.details["handle"] == "+420123456789"


def test_icloud_size_header_beyond_scan_window(tmp_path: Path) -> None:
    body = ["text\ttimestamp", "obsah zprávy\t" + TSV_TS]
    meta = [f"# export metadata řádek {i}" for i in range(15)]
    deep = _write_tsv(tmp_path / "deep.csv", meta + body)  # hlavička na indexu 15
    shallow = _write_tsv(tmp_path / "shallow.csv", body)  # hlavička na indexu 0
    assert extract_icloud_messages(deep) == []
    assert len(extract_icloud_messages(shallow)) == 1


def test_icloud_tz_timestamp_formats_equivalence(tmp_path: Path) -> None:
    p = _write_tsv(
        tmp_path / "ts.csv",
        [
            "text\ttimestamp",
            "a\t" + TSV_TS,  # ISO naive → UTC
            "b\t" + str(TS_S),  # epoch sekundy (text)
            "c\t" + str(TS_MS),  # epoch milisekundy (text)
        ],
    )
    arts = extract_icloud_messages(p)
    assert [a.timestamp for a in arts] == [_DT, _DT, _DT]


# ---------------------------------------------------------------------------
# cloud_generic — locale / negative
# ---------------------------------------------------------------------------


def test_generic_locale_timeline_czech() -> None:
    detail = "Přihlášení z neznámé stanice v Praze — " * 10
    payload = _js(
        [
            {
                "event": "přihlášení",
                "actor": "uživatel@příklad.cz",
                "details": detail,
                "time": ISO_Z,
            }
        ]
    )
    (rec,) = parse_cloud_generic(payload)
    assert rec.kind == "timeline"
    assert rec.name == "přihlášení"
    assert rec.actor == "uživatel@příklad.cz"
    assert len(rec.detail or "") == 200  # truncation [:200] s diakritikou
    assert (rec.detail or "").startswith("Přihlášení z neznámé stanice")


@pytest.mark.parametrize(
    "payload",
    [b'[{"foo": 1}]', b"{}"],
    ids=["unrecognized_item", "empty_object"],
)
def test_generic_negative_no_records(payload: bytes) -> None:
    with pytest.raises(TypeError, match="Nenalezeny generic cloud záznamy"):
        parse_cloud_generic(payload)
