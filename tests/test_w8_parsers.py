"""ETAPA B vlna 8 — syntetické offline testy (4 parsery / 16 AXIOM typů).

Pokrývá:
- ``chrome_preferences`` — Chrome Preferences JSON (extensions/search/sync)
- ``cloud_drive_files`` — Cloud Drive soubory (Google/OneDrive/Apple, verze)
- ``google_voice_wr`` — Google Voice warrant return (4 subtypy, auto-detekce)
- ``win_drivers`` — Windows drivers z paměťového dumpu

Vše plně offline: syntetické fixtures, žádné sítě.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.artifacts.chrome_preferences import (
    PARSER_VERSION as CHROME_PREFS_VERSION,
)
from stopa.artifacts.chrome_preferences import (
    build_pref_artifacts,
    extract_chrome_pref_artifacts,
    is_chrome_preferences_file,
    parse_chrome_preferences,
)
from stopa.artifacts.cloud_drive_files import PARSER_VERSION as CLOUD_DRIVE_FILES_VERSION
from stopa.artifacts.cloud_drive_files import (
    build_cloud_file_artifacts,
    extract_cloud_drive_artifacts,
    is_cloud_drive_file,
    parse_cloud_drive_files,
)
from stopa.artifacts.google_voice_wr import PARSER_VERSION as GOOGLE_VOICE_WR_VERSION
from stopa.artifacts.google_voice_wr import (
    build_voice_artifacts,
    extract_google_voice_artifacts,
    is_google_voice_file,
    parse_google_voice,
)
from stopa.artifacts.win_drivers import PARSER_VERSION as WIN_DRIVERS_VERSION
from stopa.artifacts.win_drivers import (
    build_driver_artifacts,
    extract_win_driver_artifacts,
    is_win_drivers_file,
    parse_win_drivers,
)


def _write(tmp_path: Path, name: str, payload) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload))
    return p


# ── Chrome Preferences ──────────────────────────────────────────────────────


def _prefs_payload() -> dict:
    return {
        "account_info": [{"email": "user@gmail.com", "gaia": {"name": "Uživatel"}}],
        "default_search_provider_data": {
            "default_search_provider_info": {
                "name": "Google",
                "search_url": "https://www.google.com/search?q={searchTerms}",
            }
        },
        "extensions": {
            "settings": {
                "nmmicjeknamkfloonkhhcjmomklfhlci": {
                    "location": 1,
                    "state": 1,
                    "was_installed_by_default": False,
                    "manifest": {"name": "AdBlock", "version": "4.0"},
                    "path": "nmmicjeknamkfloonkhhcjmomklfhlci",
                }
            }
        },
        "sync": {"data_type_enabled": {1: True, 2: True}},
    }


def test_prefs_parse_extensions():
    records = parse_chrome_preferences(json.dumps(_prefs_payload()).encode())
    exts = [r for r in records if r.kind == "extension"]
    assert len(exts) == 1
    assert exts[0].name == "AdBlock"
    assert exts[0].details.get("version") == "4.0"


def test_prefs_parse_search_and_sync():
    records = parse_chrome_preferences(json.dumps(_prefs_payload()).encode())
    kinds = {r.kind for r in records}
    assert "search_engine" in kinds or any(
        "search" in str(r.details) for r in records if r.kind != "extension"
    )
    # sync nastavení se musí objevit jako setting
    settings = [r for r in records if r.kind not in ("extension",)]
    assert len(settings) >= 1


def test_prefs_invalid_json():
    with pytest.raises(ValueError):
        parse_chrome_preferences(b"{nejson")


def test_prefs_empty_payload():
    assert parse_chrome_preferences(b"{}") == []


def test_prefs_detector_name_and_content():
    head = json.dumps(_prefs_payload()).encode()[:2048]
    assert is_chrome_preferences_file("Preferences", head)
    assert not is_chrome_preferences_file("random.txt", head)
    # bez klíčových markerů v obsahu → False
    assert not is_chrome_preferences_file("Preferences", b'{"foo": 1}')


def test_prefs_build_artifacts_types():
    records = parse_chrome_preferences(json.dumps(_prefs_payload()).encode())
    arts = build_pref_artifacts(records)
    types = {a.artifact_type for a in arts}
    assert "browser_extension" in types
    assert all(a.parser_version == CHROME_PREFS_VERSION for a in arts)
    # snapshot konfigurace — bez času
    assert all(a.timestamp is None for a in arts)


def test_prefs_entrypoint(tmp_path: Path):
    p = _write(tmp_path, "Preferences", _prefs_payload())
    arts = extract_chrome_pref_artifacts(p)
    assert len(arts) >= 2
    assert any(a.artifact_type == "browser_extension" for a in arts)


def test_prefs_entrypoint_missing_file(tmp_path: Path):
    assert extract_chrome_pref_artifacts(tmp_path / "chybi.json") == []


# ── Cloud Drive files ───────────────────────────────────────────────────────


def _drive_payload() -> list[dict]:
    return [
        {
            "id": "abc123",
            "name": "report.pdf",
            "sizeBytes": "1024",
            "md5Checksum": "d41d8cd98f00b204e9800998ecf8427e",
            "mimeType": "application/pdf",
            "createdTime": "2026-01-15T10:30:00Z",
            "modifiedTime": "2026-02-20T14:00:00Z",
        },
        {
            "id": "def456",
            "name": "photo.jpg",
            "sizeBytes": "2048",
            "mimeType": "image/jpeg",
            "createdTime": 1739000000,
            "modifiedTime": 1739100000,
        },
    ]


def test_drive_parse_google():
    records = parse_cloud_drive_files(json.dumps(_drive_payload()).encode(), name="Files.json")
    assert len(records) == 2
    r0 = records[0]
    assert r0.name == "report.pdf"
    assert r0.size_bytes == 1024
    assert r0.checksum == "d41d8cd98f00b204e9800998ecf8427e"
    # ISO čas → epoch s (2026-02-20T14:00Z)
    assert r0.modified_s is not None
    back = datetime.fromtimestamp(r0.modified_s, tz=timezone.utc)
    assert (back.year, back.month, back.day) == (2026, 2, 20)


def test_drive_parse_epoch_timestamps():
    records = parse_cloud_drive_files(json.dumps(_drive_payload()).encode(), name="Files.json")
    r1 = records[1]
    assert r1.created_s is not None and abs(r1.created_s - 1739000000) < 2


def test_drive_provider_detection():
    payload = json.dumps(_drive_payload()).encode()
    # google drive — sizeBytes marker
    recs = parse_cloud_drive_files(payload, name="Files.json")
    assert all(r.provider == "google_drive" for r in recs)
    # onedrive — lastModifiedDateTime marker + název
    od = json.dumps(
        [{"name": "a.docx", "size": 10, "lastModifiedDateTime": "2026-01-01T00:00:00Z"}]
    ).encode()
    recs_od = parse_cloud_drive_files(od, name="OneDrive.json")
    assert all(r.provider == "onedrive" for r in recs_od)


def test_drive_invalid_json():
    with pytest.raises(ValueError):
        parse_cloud_drive_files(b"[nejson", name="Files.json")


def test_drive_detector_name_and_content():
    head = json.dumps(_drive_payload()).encode()[:2048]
    assert is_cloud_drive_file("Drive/Files.json", head)
    assert not is_cloud_drive_file("random.txt", head)
    # kolize s drive_activity (vlna 5) — ten má vlastní detektor
    assert not is_cloud_drive_file("drive_activity.json", head)


def test_drive_build_artifacts():
    records = parse_cloud_drive_files(json.dumps(_drive_payload()).encode(), name="Files.json")
    arts = build_cloud_file_artifacts(records)
    assert len(arts) == 2
    assert all(a.artifact_type == "cloud_file" for a in arts)
    assert all(a.parser_version == CLOUD_DRIVE_FILES_VERSION for a in arts)


def test_drive_entrypoint(tmp_path: Path):
    p = _write(tmp_path, "Files.json", _drive_payload())
    # entrypoint dostane jen basename — provider z markerů v obsahu
    arts = extract_cloud_drive_artifacts(p)
    assert len(arts) == 2
    assert any("report.pdf" in a.title for a in arts)


# ── Google Voice WR ─────────────────────────────────────────────────────────


def _voice_sms_payload() -> list[dict]:
    return [
        {
            "id": "msg1",
            "from": "+420777123456",
            "to": "+420604987654",
            "body": "Ahoj, kde jsi?",
            "direction": "inbound",
            "timestampMsInEpoch": 1739000000000,
        },
        {
            "id": "msg2",
            "from": "+420604987654",
            "to": "+420777123456",
            "body": "U domu.",
            "direction": "outbound",
            "timestampMsInEpoch": 1739000100000,
        },
    ]


def _voice_voicemail_payload() -> list[dict]:
    return [
        {
            "id": "vm1",
            "fromNumber": "+420777555666",
            "durationSeconds": 42,
            "transcript": "Volal jsem ohledně faktury.",
            "timestampMsInEpoch": 1739000200000,
        }
    ]


def _voice_contact_payload() -> list[dict]:
    return [
        {"name": "Jan Novák", "phoneNumber": "+420601112223", "emailAddress": "jan@example.cz"},
        {"name": "Petr Svoboda", "phoneNumber": "+420604445556"},
    ]


def _voice_subscriber_payload() -> dict:
    return {
        "subscriberNumber": "+420604987654",
        "carrierName": "O2 Czech Republic",
        "planType": "Voice Unlimited",
        "accountStatus": "active",
    }


def test_voice_parse_sms():
    kind, records = parse_google_voice(json.dumps(_voice_sms_payload()).encode())
    assert kind == "sms"
    assert len(records) == 2
    r0 = records[0]
    assert "+420777123456" in r0.details.get("from", "")
    assert r0.timestamp_s is not None and abs(r0.timestamp_s - 1739000000) < 2


def test_voice_parse_voicemail():
    kind, records = parse_google_voice(json.dumps(_voice_voicemail_payload()).encode())
    assert kind == "voicemail"
    assert len(records) == 1
    assert records[0].details.get("duration_seconds") == 42
    assert "faktury" in records[0].details.get("transcript", "")


def test_voice_parse_contact():
    kind, records = parse_google_voice(json.dumps(_voice_contact_payload()).encode())
    assert kind == "contact"
    assert len(records) == 2
    assert any(r.name == "Jan Novák" for r in records)


def test_voice_parse_subscriber():
    kind, records = parse_google_voice(json.dumps(_voice_subscriber_payload()).encode())
    assert kind == "subscriber"
    assert len(records) == 1
    assert "+420604987654" in records[0].details.get("subscribernumber", "")


def test_voice_unknown_kind():
    kind, records = parse_google_voice(json.dumps({"foo": [1, 2, 3]}).encode())
    assert kind is None
    assert records == []


def test_voice_invalid_json():
    with pytest.raises(ValueError):
        parse_google_voice(b"{nejson")


def test_voice_detector_name_and_content():
    head = json.dumps(_voice_sms_payload()).encode()[:2048]
    assert is_google_voice_file("Voice/Texts.json", head)
    assert not is_google_voice_file("random.txt", head)
    # kolize s ios_voicemail (.db) a samsung recording
    assert not is_google_voice_file("voicemail.db", head)


def test_voice_build_artifacts_types():
    kind, records = parse_google_voice(json.dumps(_voice_sms_payload()).encode())
    arts = build_voice_artifacts(kind, records)
    assert all(a.artifact_type == "sms_message" for a in arts)
    assert all(a.parser_version == GOOGLE_VOICE_WR_VERSION for a in arts)

    kind2, recs2 = parse_google_voice(json.dumps(_voice_voicemail_payload()).encode())
    arts2 = build_voice_artifacts(kind2, recs2)
    assert all(a.artifact_type == "voicemail" for a in arts2)


def test_voice_entrypoint(tmp_path: Path):
    p = _write(tmp_path, "Texts.json", _voice_sms_payload())
    arts = extract_google_voice_artifacts(p)
    assert len(arts) == 2
    assert all(a.artifact_type == "sms_message" for a in arts)


# ── Windows Drivers ─────────────────────────────────────────────────────────


def _drivers_payload() -> list[dict]:
    return [
        {
            "driverName": "ntoskrnl.exe",
            "baseAddress": "0xfffff8045b2c0000",
            "size": 16384,
            "signed": True,
            "description": "Windows NT Kernel",
        },
        {
            "driverName": "suspicious.sys",
            "baseAddress": "fffff8045c000000",
            "size": 4096,
            "signed": False,
        },
    ]


def test_drivers_parse():
    records = parse_win_drivers(json.dumps(_drivers_payload()).encode())
    assert len(records) == 2
    r0 = records[0]
    assert r0.name == "ntoskrnl.exe"
    assert r0.base_address is not None and r0.base_address.lower().startswith("0x")
    assert r0.size_bytes == 16384
    assert r0.signed is True


def test_drivers_parse_unsigned():
    records = parse_win_drivers(json.dumps(_drivers_payload()).encode())
    r1 = records[1]
    assert r1.signed is False


def test_drivers_invalid_json():
    with pytest.raises(ValueError):
        parse_win_drivers(b"{nejson")


def test_drivers_detector_name_and_content():
    head = json.dumps(_drivers_payload()).encode()[:2048]
    assert is_win_drivers_file("drivers.json", head)
    assert not is_win_drivers_file("random.txt", head)
    # bez markerů baseAddress/driverName → False
    assert not is_win_drivers_file("drivers.json", b'{"foo": 1}')


def test_drivers_build_artifacts_anomaly():
    records = parse_win_drivers(json.dumps(_drivers_payload()).encode())
    arts = build_driver_artifacts(records)
    assert len(arts) == 2
    assert all(a.artifact_type == "win_driver" for a in arts)
    # nesignovaný driver → anomaly flag
    unsigned = [a for a in arts if "suspicious" in a.title]
    assert len(unsigned) == 1
    assert "unsigned_driver" in (unsigned[0].anomaly_flags or [])
    signed = [a for a in arts if "ntoskrnl" in a.title]
    assert not (signed[0].anomaly_flags or [])


def test_drivers_entrypoint(tmp_path: Path):
    p = _write(tmp_path, "drivers.json", _drivers_payload())
    arts = extract_win_driver_artifacts(p)
    assert len(arts) == 2
    assert all(a.parser_version == WIN_DRIVERS_VERSION for a in arts)


# ── Registry + pipeline dispatch (vlna 8) ───────────────────────────────────


def test_registry_contains_wave8_parsers():
    from stopa.domain.validation_registry import build_registry

    reg = build_registry()
    for pid in ("chrome_preferences", "cloud_drive_files", "google_voice_wr", "win_drivers"):
        assert pid in reg, f"chybí {pid} v C3 registry"
        assert reg[pid].version == "1.0"


def test_pipeline_dispatch_wave8():
    from stopa.pipeline import _name_based_match

    # Takeout layout — klíčové slovo v rodičovské složce (retry na celé cestě)
    m = _name_based_match("Drive/Files.json")
    assert m is not None and m[1] == CLOUD_DRIVE_FILES_VERSION
    m2 = _name_based_match("Voice/Texts.json")
    assert m2 is not None and m2[1] == GOOGLE_VOICE_WR_VERSION
    # basename s klíčovým slovem
    m3 = _name_based_match("Preferences")
    assert m3 is not None and m3[1] == CHROME_PREFS_VERSION
    m4 = _name_based_match("drivers.json")
    assert m4 is not None and m4[1] == WIN_DRIVERS_VERSION
    # cizí soubor → None
    assert _name_based_match("random.txt") is None
