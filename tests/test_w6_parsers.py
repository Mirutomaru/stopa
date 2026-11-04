"""ETAPA B vlna 6 — syntetické offline testy (4 parsery / 4 AXIOM typy).

Pokrývá:
- ``google_photos`` — Google Photos metadata JSON (Takeout/warrant, photoTakenTime/geoData)
- ``google_mail_info`` — Gmail warrant return JSON (threadId/internalDate µs)
- ``google_bar`` — Chrome History DB tabulka ``search_terms`` (omnibox dotazy)
- ``attachment_extractor`` — MIME/RFC822 přílohy → email_attachment artifacty

Vše plně offline: syntetické fixtures, žádné sítě.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.artifacts.attachment_extractor import (
    AttachmentInfo,
    build_attachment_artifacts,
    extract_attachments_from_message,
    parse_attachments,
)
from stopa.artifacts.google_bar import (
    build_search_term_artifacts,
    extract_google_bar_artifacts,
    extract_search_terms,
    is_chrome_history_db,
)
from stopa.artifacts.google_mail_info import (
    MailInfoRecord,
    build_mail_info_artifacts,
    extract_mail_info_artifacts,
    is_mail_info_file,
    parse_mail_info,
)
from stopa.artifacts.google_photos import (
    PhotoRecord,
    build_photo_artifacts,
    extract_photos_artifacts,
    is_photos_file,
    parse_photos,
)
from stopa.domain.times import to_chrome_micros

# ── Google Photos ───────────────────────────────────────────────────────────


def _photos_json() -> bytes:
    return json.dumps(
        [
            {
                "filename": "IMG_001.jpg",
                "photoTakenTime": {"timestamp": "2024-01-15T10:30:00Z"},
                "geoData": {"latitudeE7": 500900000, "longitudeE7": 144200000},
                "description": "Víkend v horách",
                "mediaItemType": "PHOTO",
            },
            {
                "filename": "IMG_002.jpg",
                "photoTakenTime": {"timestamp": 1705314600000},  # epoch ms
            },
        ]
    ).encode()


def test_photos_parse_takeout_list():
    records = parse_photos(_photos_json())
    assert len(records) == 2
    r0 = records[0]
    assert r0.filename == "IMG_001.jpg"
    assert r0.description == "Víkend v horách"
    assert r0.media_type == "PHOTO"
    # ISO 8601 → epoch s (2024-01-15T10:30:00Z = 1705314600)
    assert r0.timestamp_s == pytest.approx(1_705_314_600.0, abs=1.0)
    # E7 → stupně (50.09 / 14.42 — Brno)
    assert r0.latitude == pytest.approx(50.09)
    assert r0.longitude == pytest.approx(14.42)


def test_photos_epoch_ms_timestamp():
    records = parse_photos(_photos_json())
    # druhý záznam: epoch ms → s
    assert records[1].timestamp_s == pytest.approx(1_705_314_600.0, abs=1.0)


def test_photos_single_object_wrapped():
    data = json.dumps(
        {"filename": "a.jpg", "photoTakenTime": {"timestamp": "2024-01-01T00:00:00Z"}}
    ).encode()
    records = parse_photos(data)
    assert len(records) == 1
    assert records[0].filename == "a.jpg"


def test_photos_invalid_json_raises():
    with pytest.raises(ValueError):
        parse_photos(b"{nejson")


def test_photos_not_list_raises():
    with pytest.raises(TypeError):
        parse_photos(json.dumps({"foo": "bar"}).encode())


def test_photos_build_artifacts():
    records = [
        PhotoRecord(
            filename="IMG_001.jpg",
            description="popis",
            media_type="PHOTO",
            timestamp_s=1_705_314_600.0,
            latitude=50.09,
            longitude=14.42,
        )
    ]
    arts = build_photo_artifacts(records)
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "google_photo"
    assert a.timestamp is not None and a.timestamp.year == 2024
    assert a.details["engine"] == "google_photos"
    assert a.details["filename"] == "IMG_001.jpg"
    assert a.details["latitude"] == pytest.approx(50.09)
    # filename + timestamp → confidence 0.8
    assert a.confidence == 0.8


def test_photos_no_ts_confidence_lower():
    arts = build_photo_artifacts([PhotoRecord(filename="x.jpg")])
    assert len(arts) == 1
    assert arts[0].timestamp is None
    assert arts[0].confidence == 0.6


def test_photos_is_file_detection():
    head = _photos_json()[:2048]
    assert is_photos_file("photos.json", head)
    assert is_photos_file("google_photos/photo.json", head)
    # binární fotka (bez JSON klíčů) → ne
    assert not is_photos_file("IMG_001.jpg")
    assert not is_photos_file("photos.bin", b"\x89PNG\r\n\x1a\n" + b"x" * 20)


def test_photos_extract_entrypoint(tmp_path: Path):
    p = tmp_path / "photos.json"
    p.write_bytes(_photos_json())
    arts = extract_photos_artifacts(p)
    assert len(arts) == 2
    assert all(a.artifact_type == "google_photo" for a in arts)


def test_photos_extract_missing_file(tmp_path: Path):
    assert extract_photos_artifacts(tmp_path / "chybi.json") == []


# ── Google Mail Message Information ─────────────────────────────────────────


def _mail_json() -> bytes:
    return json.dumps(
        [
            {
                "threadId": "abc123",
                "internalDate": "1705314600000000",  # µs od Unix epochy
                "from": {"emailAddress": "sender@example.com"},
                "to": [{"emailAddress": "rcpt@example.com"}],
                "subject": "Re: Schůzka",
                "snippet": "Text zprávy…",
            },
            {
                "threadId": "def456",
                "internalDate": 1705314600,  # epoch s (tolerantní)
                "from": "plain@example.com",
                "to": "a@x.cz",
                "cc": ["b@y.cz"],
            },
        ]
    ).encode()


def test_mail_parse_gmail_us():
    records = parse_mail_info(_mail_json())
    assert len(records) == 2
    r0 = records[0]
    assert r0.thread_id == "abc123"
    assert r0.subject == "Re: Schůzka"
    # µs → s (1705314600000000 µs = 1705314600 s)
    assert r0.timestamp_s == pytest.approx(1_705_314_600.0, abs=1.0)
    # objekt {"emailAddress": ...} → adresa
    assert r0.sender == "sender@example.com"
    assert r0.recipients == ["rcpt@example.com"]


def test_mail_plain_string_addrs_and_cc():
    records = parse_mail_info(_mail_json())
    r1 = records[1]
    # plain string from + to, cc připojeno bez duplicit
    assert r1.sender == "plain@example.com"
    assert r1.recipients == ["a@x.cz", "b@y.cz"]


def test_mail_single_object_wrapped():
    data = json.dumps({"threadId": "t1", "subject": "X"}).encode()
    records = parse_mail_info(data)
    assert len(records) == 1
    assert records[0].thread_id == "t1"


def test_mail_invalid_json_raises():
    with pytest.raises(ValueError):
        parse_mail_info(b"[{")


def test_mail_not_list_raises():
    with pytest.raises(TypeError):
        parse_mail_info(json.dumps({"foo": 1}).encode())


def test_mail_build_artifacts():
    records = [
        MailInfoRecord(
            thread_id="abc",
            subject="Předmět",
            sender="s@x.cz",
            recipients=["r@y.cz"],
            snippet="náhled",
            timestamp_s=1_705_314_600.0,
        )
    ]
    arts = build_mail_info_artifacts(records)
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "google_mail_info"
    assert a.timestamp is not None and a.timestamp.year == 2024
    assert a.details["engine"] == "google_mail_info"
    assert a.details["thread_id"] == "abc"
    assert a.details["from"] == "s@x.cz"
    assert a.details["to"] == ["r@y.cz"]
    # threadId + timestamp → confidence 0.8
    assert a.confidence == 0.8


def test_mail_no_ts_confidence_lower():
    arts = build_mail_info_artifacts([MailInfoRecord(thread_id="t")])
    assert len(arts) == 1
    assert arts[0].timestamp is None
    assert arts[0].confidence == 0.6


def test_mail_is_file_detection():
    head = _mail_json()[:2048]
    assert is_mail_info_file("gmail_messages.json", head)
    assert is_mail_info_file("mail_message_information.json", head)
    # jiný JSON bez mail klíčů → ne
    assert not is_mail_info_file("other.json", b'{"foo": 1}')


def test_mail_extract_entrypoint(tmp_path: Path):
    p = tmp_path / "gmail_messages.json"
    p.write_bytes(_mail_json())
    arts = extract_mail_info_artifacts(p)
    assert len(arts) == 2
    assert all(a.artifact_type == "google_mail_info" for a in arts)


def test_mail_extract_missing_file(tmp_path: Path):
    assert extract_mail_info_artifacts(tmp_path / "chybi.json") == []


# ── Google Bar (Chrome search_terms) ────────────────────────────────────────


def _make_chrome_db(with_search_terms: bool = True, with_columns: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
    conn.execute(
        "CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)"
    )
    if with_search_terms:
        cols = "term TEXT, time_last_used INTEGER"
        if with_columns:
            cols += ", weight REAL, source INTEGER"
        conn.execute(f"CREATE TABLE search_terms ({cols})")
    return conn


def test_bar_is_chrome_history_db():
    assert is_chrome_history_db(_make_chrome_db())
    # jen visits bez urls → ne Chrome history
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE visits (id INTEGER)")
    assert not is_chrome_history_db(c)


def test_bar_extract_search_terms():
    conn = _make_chrome_db()
    ts = to_chrome_micros(datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc))
    conn.execute(
        "INSERT INTO search_terms (term, time_last_used, weight, source) VALUES (?, ?, ?, ?)",
        ("počasí brno", ts, 2.5, 1),
    )
    conn.execute(
        "INSERT INTO search_terms (term, time_last_used, weight, source) VALUES (?, ?, ?, ?)",
        ("recept na koláč", ts - 3_600_000_000, 1.0, 2),
    )
    # duplicitní term (lowercase dedup) → vynechán
    conn.execute(
        "INSERT INTO search_terms (term, time_last_used, weight, source) VALUES (?, ?, ?, ?)",
        ("POČASÍ BRNO", ts + 1_000_000, 3.0, 1),
    )
    arts = extract_search_terms(conn)
    assert len(arts) == 2
    # dotaz řadí time_last_used DESC → novější "POČASÍ BRNO" vyhrává deduplikaci
    a0 = arts[0]
    assert a0.artifact_type == "browser_search"
    assert a0.title == "POČASÍ BRNO"
    assert a0.timestamp is not None and a0.timestamp.year == 2024
    assert a0.details["engine"] == "chrome/edge"
    assert a0.details["source"] == "search_terms"
    assert a0.confidence == 0.8


def test_bar_no_search_terms_table():
    conn = _make_chrome_db(with_search_terms=False)
    assert extract_search_terms(conn) == []


def test_bar_missing_required_columns():
    # tabulka bez time_last_used → ne search_terms
    conn = _make_chrome_db(with_columns=False)
    conn.execute("INSERT INTO search_terms (term, time_last_used) VALUES ('x', 1)")
    assert extract_search_terms(conn) == []


def test_bar_build_dedup_and_no_ts():
    rows = [
        {"term": "a", "time_last_used": None},
        {"term": "A", "time_last_used": to_chrome_micros(datetime(2024, 1, 1, tzinfo=timezone.utc))},
        {"term": "", "time_last_used": None},
    ]
    arts = build_search_term_artifacts(rows)
    # dedup: 'a' a 'A' → jeden; prázdný term vynechán
    assert len(arts) == 1
    assert arts[0].title == "a"
    # bez času → confidence 0.5
    assert arts[0].confidence == 0.5


def test_bar_extract_entrypoint(tmp_path: Path):
    db = tmp_path / "History"
    conn = _make_chrome_db()
    ts = to_chrome_micros(datetime(2024, 1, 15, tzinfo=timezone.utc))
    conn.execute("INSERT INTO urls (id, url, title) VALUES (1, 'https://x.cz', 'X')")
    conn.execute("INSERT INTO visits (id, url, visit_time) VALUES (1, 1, ?)", (ts,))
    conn.execute(
        "INSERT INTO search_terms (term, time_last_used, weight, source) VALUES (?, ?, 1.0, 1)",
        ("dotaz", ts),
    )
    conn.commit()
    db.write_bytes(b"")  # soubor musí existovat; entrypoint ho otevře read-only
    conn.close()
    # znovu vytvořit DB přímo do souboru (entrypoint otevírá path)
    conn2 = sqlite3.connect(db)
    conn2.row_factory = sqlite3.Row
    conn2.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
    conn2.execute(
        "CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)"
    )
    conn2.execute(
        "CREATE TABLE search_terms (term TEXT, time_last_used INTEGER, weight REAL, source INTEGER)"
    )
    conn2.execute("INSERT INTO urls (id, url, title) VALUES (1, 'https://x.cz', 'X')")
    conn2.execute("INSERT INTO visits (id, url, visit_time) VALUES (1, 1, ?)", (ts,))
    conn2.execute(
        "INSERT INTO search_terms (term, time_last_used, weight, source) VALUES (?, ?, 1.0, 1)",
        ("dotaz", ts),
    )
    conn2.commit()
    conn2.close()

    arts = extract_google_bar_artifacts(db)
    assert len(arts) == 1
    assert arts[0].artifact_type == "browser_search"


def test_bar_extract_missing_file(tmp_path: Path):
    assert extract_google_bar_artifacts(tmp_path / "chybi") == []


# ── Attachment Extractor (MIME/RFC822) ──────────────────────────────────────

_MIME_WITH_ATTACHMENT = b"""From: Sender <sender@example.com>
To: Rcpt <rcpt@example.com>
Subject: S priloou
Date: Mon, 15 Jan 2024 10:30:00 +0000
Message-ID: <msg-1@example.com>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="BOUND"

--BOUND
Content-Type: text/plain; charset=utf-8

Telo zpravy.
--BOUND
Content-Type: application/pdf; name="faktura.pdf"
Content-Disposition: attachment; filename="faktura.pdf"
Content-Length: 1234

BASE64PAYLOAD
--BOUND--
"""


def test_attachment_parse_with_attachment():
    date, atts = parse_attachments(_MIME_WITH_ATTACHMENT)
    assert len(atts) == 1
    a = atts[0]
    assert a.filename == "faktura.pdf"
    assert a.content_type == "application/pdf"
    assert a.disposition == "attachment"
    # Content-Length hlavička → velikost bez dekodování payloadu
    assert a.size_bytes == 1234
    assert a.message_id == "<msg-1@example.com>"
    # datum rodičovské zprávy (přílohy ho dědí)
    assert date is not None and date.year == 2024


def test_attachment_parse_no_attachments():
    raw = b"From: a@x.cz\nTo: b@y.cz\nSubject: X\nDate: Mon, 15 Jan 2024 10:30:00 +0000\n\nTelo."
    date, atts = parse_attachments(raw)
    assert atts == []
    assert date is not None


def test_attachment_parse_corrupted():
    # prázdný vstup → (None, []) bez výjimky
    assert parse_attachments(b"") == (None, [])


def test_attachment_inline_disposition():
    raw = b"""From: a@x.cz
To: b@y.cz
Subject: X
Date: Mon, 15 Jan 2024 10:30:00 +0000
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="B"

--B
Content-Type: text/html; name="obr.png"
Content-Disposition: inline; filename="obr.png"

DATA
--B--
"""
    _, atts = parse_attachments(raw)
    assert len(atts) == 1
    # inline s filename → příloha, ale disposition "inline"
    assert atts[0].disposition == "inline"
    assert atts[0].filename == "obr.png"


def test_attachment_build_artifacts():
    from datetime import timezone as tz

    date = datetime(2024, 1, 15, 10, 30, tzinfo=tz.utc)
    arts = build_attachment_artifacts(
        [AttachmentInfo(filename="faktura.pdf", content_type="application/pdf", size_bytes=1234)],
        date,
    )
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "email_attachment"
    assert a.title == "faktura.pdf"
    assert a.timestamp is not None and a.timestamp.year == 2024
    assert a.details["engine"] == "mime"
    assert a.details["filename"] == "faktura.pdf"
    assert a.details["size_bytes"] == 1234
    # s datem → confidence 0.8
    assert a.confidence == 0.8


def test_attachment_build_without_date():
    arts = build_attachment_artifacts([AttachmentInfo(filename="x.txt")])
    assert len(arts) == 1
    assert arts[0].timestamp is None
    assert arts[0].confidence == 0.6


def test_attachment_extract_from_message_entrypoint():
    arts = extract_attachments_from_message(_MIME_WITH_ATTACHMENT)
    assert len(arts) == 1
    assert arts[0].artifact_type == "email_attachment"
    assert arts[0].title == "faktura.pdf"


# ── Pipeline integrace (name-based dispatch + C3 registry) ─────────────────


def test_pipeline_name_based_photos():
    from stopa.pipeline import NAME_BASED_EXTRACTORS, _name_based_match

    m = _name_based_match("photos.json")
    assert m is not None
    fn, ver = m
    assert fn is NAME_BASED_EXTRACTORS["google_photos"][0]
    assert ver == "1.0"


def test_pipeline_name_based_mail_info():
    from stopa.pipeline import NAME_BASED_EXTRACTORS, _name_based_match

    m = _name_based_match("gmail_messages.json")
    assert m is not None
    fn, ver = m
    assert fn is NAME_BASED_EXTRACTORS["google_mail_info"][0]
    assert ver == "1.0"


def test_registry_contains_wave6_parsers():
    from stopa.domain.validation_registry import build_registry

    reg = build_registry()
    # vlna 6: google_photos + google_mail_info (explicitní C3 záznamy)
    assert "google_photos" in reg
    assert "google_mail_info" in reg
    assert reg["google_photos"].version == "1.0"
    assert reg["google_mail_info"].version == "1.0"
