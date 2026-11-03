"""ETAPA B vlna 4 — testy 6 nových portable-local parserů.

Parsery: ddg_cookies, allowlisted_websites, openoffice_base, parked_car_locations,
ios_voicemail, win_userassist. Čistá funkce + IO entrypoint; syntetické fixtures
plně offline (in-memory SQLite pro DB parsery, FakeHive pro UserAssist).
"""

from __future__ import annotations

import json
import sqlite3
import struct
import zipfile
from pathlib import Path

# ── ddg_cookies (Chromium cookies SQLite) ─────────────────────────────


def _make_ddg_cookies_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE cookies ("
        " host_key TEXT, name TEXT, value TEXT, path TEXT,"
        " expires_utc INTEGER, last_access_utc INTEGER,"
        " is_secure INTEGER, is_httponly INTEGER)"
    )
    # Chromium µs od 1601-01-01: 2024-01-15T10:30:00Z = unix 1705314600
    # → (unix + 11644473600) s od Windows epochy × 1e6 µs
    chrome_us = (1_705_314_600 + 11_644_473_600) * 1_000_000
    conn.execute(
        "INSERT INTO cookies VALUES (?,?,?,?,?,?,?,?)",
        (".example.com", "sessionid", "abc123", "/", chrome_us, chrome_us, 1, 0),
    )
    conn.execute(
        "INSERT INTO cookies VALUES (?,?,?,?,?,?,?,?)",
        (".tracker.org", "track", "xyz789", "/path", 0, chrome_us, 0, 1),
    )
    return conn


def test_ddg_cookies_detection():
    from stopa.artifacts.ddg_cookies import is_cookies_database

    assert is_cookies_database(_make_ddg_cookies_db()) is True


def test_ddg_cookies_not_detected_on_plain_db():
    from stopa.artifacts.ddg_cookies import is_cookies_database

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE cookies (id INTEGER, name TEXT)")  # chybí host_key/value
    assert is_cookies_database(conn) is False


def test_ddg_cookies_extract():
    from stopa.artifacts.ddg_cookies import extract_ddg_cookie_artifacts

    arts = extract_ddg_cookie_artifacts(_make_ddg_cookies_db())
    assert len(arts) == 2
    a0 = arts[0]
    assert a0.artifact_type == "browser_cookie"
    assert a0.details.get("host_key") == ".example.com"
    assert a0.details.get("name") == "sessionid"
    assert a0.timestamp is not None
    # 2024-01-15T10:30:00Z
    assert a0.timestamp.year == 2024 and a0.timestamp.month == 1


def test_ddg_cookies_empty_db():
    from stopa.artifacts.ddg_cookies import extract_ddg_cookie_artifacts

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT)")
    assert extract_ddg_cookie_artifacts(conn) == []


# ── allowlisted_websites (JSON) ───────────────────────────────────────


def test_allowlisted_detection():
    from stopa.artifacts.allowlisted_websites import is_allowlisted_websites_file

    assert is_allowlisted_websites_file("allowlisted_websites.json") is True
    assert is_allowlisted_websites_file("Allowlisted_Sites.json") is True
    assert is_allowlisted_websites_file("random.txt") is False


def test_allowlisted_extract(tmp_path: Path):
    from stopa.artifacts.allowlisted_websites import extract_allowlisted_websites_artifacts

    p = tmp_path / "allowlist.json"
    p.write_text(json.dumps(["example.com", "tracker.org", "sub.example.net"]), encoding="utf-8")
    arts = extract_allowlisted_websites_artifacts(p)
    assert len(arts) == 3
    a0 = arts[0]
    assert a0.artifact_type == "browser_setting"
    assert a0.details.get("domain") == "example.com"


def test_allowlisted_extract_object_form(tmp_path: Path):
    from stopa.artifacts.allowlisted_websites import extract_allowlisted_websites_artifacts

    p = tmp_path / "tracker_exceptions.json"
    # objekt s polem domén (DDG privacy config tvar)
    p.write_text(json.dumps({"exceptions": ["a.com", "b.org"]}), encoding="utf-8")
    arts = extract_allowlisted_websites_artifacts(p)
    assert len(arts) == 2


def test_allowlisted_extract_invalid_json(tmp_path: Path):
    from stopa.artifacts.allowlisted_websites import extract_allowlisted_websites_artifacts

    p = tmp_path / "allowlist.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert extract_allowlisted_websites_artifacts(p) == []


def test_allowlisted_extract_missing(tmp_path: Path):
    from stopa.artifacts.allowlisted_websites import extract_allowlisted_websites_artifacts

    assert extract_allowlisted_websites_artifacts(tmp_path / "nope.json") == []


# ── openoffice_base (.odb = ZIP kontejner) ────────────────────────────


def _make_odb(path: Path, mimetype: str = "application/vnd.oasis.opendocument.base") -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", mimetype)
        zf.writestr(
            "content.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0">'
            "<office:body><office:database/></office:body></office:document-content>",
        )


def test_openoffice_detection():
    from stopa.artifacts.openoffice_base import is_openoffice_base_file

    assert is_openoffice_base_file("mydb.odb") is True
    assert is_openoffice_base_file("report.ODF") is False  # jen .odb
    assert is_openoffice_base_file("archive.zip") is False


def test_openoffice_extract(tmp_path: Path):
    from stopa.artifacts.openoffice_base import extract_openoffice_base_artifacts

    p = tmp_path / "mydb.odb"
    _make_odb(p)
    arts = extract_openoffice_base_artifacts(p)
    assert len(arts) == 1
    a0 = arts[0]
    assert a0.artifact_type == "document_metadata"
    assert a0.details.get("mimetype") == "application/vnd.oasis.opendocument.base"


def test_openoffice_extract_corrupt_zip(tmp_path: Path):
    from stopa.artifacts.openoffice_base import extract_openoffice_base_artifacts

    p = tmp_path / "bad.odb"
    p.write_bytes(b"not a zip file at all")
    assert extract_openoffice_base_artifacts(p) == []


def test_openoffice_extract_missing(tmp_path: Path):
    from stopa.artifacts.openoffice_base import extract_openoffice_base_artifacts

    assert extract_openoffice_base_artifacts(tmp_path / "nope.odb") == []


# ── parked_car_locations (iOS Local.sqlite ZRTVEHICLEEVENTMO) ─────────


def _make_parked_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE ZRTVEHICLEEVENTMO ("
        " _id INTEGER PRIMARY KEY, ZDATE REAL, ZLOCDATE REAL,"
        " ZLOCLATITUDE REAL, ZLOCLONGITUDE REAL, ZVEHICLEIDENTIFIER TEXT,"
        " ZNOTES TEXT)"
    )
    # CFAbsoluteTime: 2024-01-15T10:30:00Z = unix 1705314600 → CF = +978307200
    cf_ts = 1_705_314_600 - 978_307_200
    conn.execute(
        "INSERT INTO ZRTVEHICLEEVENTMO"
        " (ZDATE, ZLOCDATE, ZLOCLATITUDE, ZLOCLONGITUDE, ZVEHICLEIDENTIFIER, ZNOTES)"
        " VALUES (?,?,?,?,?,?)",
        (cf_ts, cf_ts, 50.0755, 14.4378, "VOZIDLO-123", "parking u úřadu"),
    )
    return conn


def test_parked_detection():
    from stopa.artifacts.parked_car_locations import is_parked_car_database

    assert is_parked_car_database(_make_parked_db()) is True


def test_parked_not_detected_plain():
    from stopa.artifacts.parked_car_locations import is_parked_car_database

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ZRTVEHICLEEVENTMO (_id INTEGER)")  # chybí souřadnice
    assert is_parked_car_database(conn) is False


def test_parked_extract():
    from stopa.artifacts.parked_car_locations import extract_parked_car_artifacts

    arts = extract_parked_car_artifacts(_make_parked_db())
    assert len(arts) == 1
    a0 = arts[0]
    assert a0.artifact_type == "location_data"
    lat = a0.details.get("latitude")
    lon = a0.details.get("longitude")
    assert abs(lat - 50.0755) < 1e-6
    assert abs(lon - 14.4378) < 1e-6


def test_parked_extract_empty():
    from stopa.artifacts.parked_car_locations import extract_parked_car_artifacts

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE ZRTVEHICLEEVENTMO (ZLOCATION TEXT, ZLATITUDE REAL,"
        " ZLONGITUDE REAL, ZCREATIONDATE REAL)"
    )
    assert extract_parked_car_artifacts(conn) == []


# ── ios_voicemail (voicemail.db) ──────────────────────────────────────


def _make_voicemail_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE voicemail ("
        " id INTEGER PRIMARY KEY, date INTEGER, sender TEXT,"
        " callback_num TEXT, duration INTEGER, trashed_date REAL)"
    )
    # unix epoch s: 2024-01-15T10:30:00Z = 1705314600
    conn.execute(
        "INSERT INTO voicemail (date, sender, callback_num, duration, trashed_date)"
        " VALUES (?,?,?,?,?)",
        (1_705_314_600, "+420 123 456 789", "+420 123 456 789", 42, 0),
    )
    return conn


def test_voicemail_detection():
    from stopa.artifacts.ios_voicemail import is_ios_voicemail_database

    assert is_ios_voicemail_database(_make_voicemail_db()) is True


def test_voicemail_not_detected_plain():
    from stopa.artifacts.ios_voicemail import is_ios_voicemail_database

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE voicemail (id INTEGER, note TEXT)")  # chybí date/sender
    assert is_ios_voicemail_database(conn) is False


def test_voicemail_extract():
    from stopa.artifacts.ios_voicemail import extract_ios_voicemail_artifacts

    arts = extract_ios_voicemail_artifacts(_make_voicemail_db())
    assert len(arts) == 1
    a0 = arts[0]
    assert a0.artifact_type == "voicemail"
    assert "+420 123 456 789" in a0.title
    assert a0.details.get("duration_s") == 42
    assert a0.timestamp is not None and a0.timestamp.year == 2024


def test_voicemail_extract_empty():
    from stopa.artifacts.ios_voicemail import extract_ios_voicemail_artifacts

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE voicemail (date INTEGER, sender TEXT)")
    assert extract_ios_voicemail_artifacts(conn) == []


# ── win_userassist (NTUSER.DAT registry — FakeHive pattern) ───────────


class FakeValue:
    def __init__(self, name: str, value):
        self.name = name
        self.value = value


class FakeKey:
    def __init__(self, path: str, values=None):
        self.path = path
        self.values = values or []


class FakeHive:
    def __init__(self, keys: list[FakeKey]):
        self._keys = keys

    def recurse_subkeys(self):
        return iter(self._keys)


def _ua_binary(run_count: int, focus_ms: int, last_run_ft: int) -> bytes:
    """UserAssist binárka: run count u32@0, focus ms u32@4, FILETIME q64@8."""
    return struct.pack("<IIQ", run_count, focus_ms, last_run_ft)


# FILETIME pro 2024-01-15T10:30:00Z = unix 1705314600 → (unix + 11644473600)*10^7
_UA_FT = (1_705_314_600 + 11_644_473_600) * 10_000_000

UA_KEYS = [
    FakeKey(
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist"
        r"\{CEBFF5CD-B328-4C2E-8545-051131C10450}",
        values=[FakeValue("6d6f7a696c6c61", _ua_binary(5, 120_000, _UA_FT))],
    ),
    FakeKey(
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist"
        r"\{F4E57C4B-2433-4AEF-A1AD-8AAEB6B89AC7}",
        values=[FakeValue("646f63756d656e74", _ua_binary(2, 30_000, _UA_FT))],
    ),
]


def test_userassist_rot13():
    from stopa.artifacts.win_userassist import _rot13_decode

    # ROT13 je involuce: decode(decode(x)) == x; hex "6d" = 'm' → ROT13 'z'
    assert _rot13_decode("6d") == "z"


def test_userassist_filetime():
    from stopa.artifacts.win_userassist import _filetime_to_dt

    dt = _filetime_to_dt(_UA_FT)
    assert dt is not None
    assert dt.year == 2024 and dt.month == 1 and dt.day == 15


def test_userassist_parse_invalid_binary():
    from stopa.artifacts.win_userassist import _parse_userassist_value

    assert _parse_userassist_value(b"short") is None
    assert _parse_userassist_value(None) is None
    parsed = _parse_userassist_value(_ua_binary(3, 90_000, _UA_FT))
    assert parsed["run_count"] == 3 and parsed["focus_time_ms"] == 90_000


def test_userassist_build_artifacts():
    from stopa.artifacts.win_userassist import (
        PARSER_VERSION,
        UserAssistEntry,
        build_userassist_artifacts,
    )

    arts = build_userassist_artifacts(
        [UserAssistEntry(hash_hex="6d", decoded_hash="z", kind="program", run_count=5)]
    )
    assert len(arts) == 1
    a0 = arts[0]
    assert a0.artifact_type == "app_execution"
    assert a0.parser_version == PARSER_VERSION
    assert a0.details.get("kind") == "program"
    assert a0.details.get("run_count") == 5


def test_userassist_extract(monkeypatch):
    from stopa.artifacts.win_userassist import extract_userassist_artifacts

    monkeypatch.setattr(
        "regipy.registry.RegistryHive", lambda **kw: FakeHive(UA_KEYS)
    )
    arts = extract_userassist_artifacts("/fake/NTUSER.DAT")
    assert len(arts) == 2
    kinds = {a.details.get("kind") for a in arts}
    assert kinds == {"program", "document"}


def test_userassist_extract_no_keys(monkeypatch):
    from stopa.artifacts.win_userassist import extract_userassist_artifacts

    other = [FakeKey(r"Software\Microsoft\Windows\CurrentVersion\Run")]
    monkeypatch.setattr("regipy.registry.RegistryHive", lambda **kw: FakeHive(other))
    assert extract_userassist_artifacts("/fake/NTUSER.DAT") == []


def test_userassist_extract_missing(monkeypatch):
    from stopa.artifacts.win_userassist import extract_userassist_artifacts

    def _raise(**_kw):
        raise FileNotFoundError("no hive")

    monkeypatch.setattr("regipy.registry.RegistryHive", _raise)
    assert extract_userassist_artifacts("/fake/nope.dat") == []


def test_userassist_extract_hive_error(monkeypatch):
    from stopa.artifacts.win_userassist import extract_userassist_artifacts

    def _raise(**_kw):
        raise ValueError("corrupt hive")

    monkeypatch.setattr("regipy.registry.RegistryHive", _raise)
    assert extract_userassist_artifacts("/fake/bad.dat") == []


# ── pipeline dispatch integrace (vlna 4) ──────────────────────────────


def test_pipeline_name_based_allowlisted():
    from stopa.pipeline import NAME_BASED_EXTRACTORS, _name_based_match

    m = _name_based_match("allowlisted_websites.json")
    assert m is not None and m[0] == NAME_BASED_EXTRACTORS["allowlisted_websites"][0]


def test_pipeline_name_based_openoffice():
    from stopa.pipeline import NAME_BASED_EXTRACTORS, _name_based_match

    m = _name_based_match("mydb.odb")
    assert m is not None and m[0] == NAME_BASED_EXTRACTORS["openoffice_base"][0]


def test_pipeline_registry_includes_userassist():
    from stopa.pipeline import parser_versions

    # UserAssist běží v registry chainu (sdílená regf magic) — verze registry_hive
    assert "registry_hive" in parser_versions()


def test_c3_registry_w4_entries():
    from stopa.domain.validation_registry import build_registry

    reg = build_registry()
    assert reg["allowlisted_websites"].version == "1.0"
    assert reg["openoffice_base"].version == "1.0"
    # sqlite + registry_hive sdílené záznamy obsahují vlna 4 formáty
    assert any("DuckDuckGo cookies" in f for f in reg["sqlite"].formats)
    assert any("UserAssist MRU" in f for f in reg["registry_hive"].formats)
