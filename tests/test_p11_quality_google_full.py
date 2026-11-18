"""P1-1 vlna 10 — Google Takeout/cloud export rodina: quality sada (7 parserů).

google_account_info / google_calendar_events / google_keep_tasks /
google_voice_wr / google_location_history / google_login_history /
google_search_history — parsery s kompletní chybějící sadou kategorií.

Testované dokumentované kontrakty:
- Čas/tz: calendar+keep ISO 8601 (Z i offset +02:00) → epoch sekundy přesně
  v UTC (_to_epoch); voice timestampMsInEpoch ms → ts_s bez ztráty; location
  CSV epoch s/ms auto-detekce podle počtu číslic (13+ = ms, jinak ×1000),
  ISO a nečíselné tvary → None (graceful); login/search time.timestamp
  string epoch → int přesně; account_info = snapshot profilu bez času
  (artifact.timestamp is None).
- Kódování/locale: parser očekává UTF-8 — BOM prefix → ValueError „Neplatné
  JSON" (výjimka: location CSV čte utf-8-sig, tam BOM stripne); česká
  diakritika roundtrip v subject/title/text/SMS body/deviceID/location/query.
- Poškození: binární smetí/oříznuté JSON → ValueError „Neplatné JSON";
  location/login CSV bez povinných sloupců → ValueError; search ne-pole →
  TypeError „Očekáváno JSON pole záznamů".
- Limity/boundary: MAX_*_PER_FILE=5000 (5001 záznamů → truncation na limit),
  minimální vstupy (prázdné [], jeden záznam) = boundary; voice body[:500]
  truncace detailu.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from stopa.artifacts.google_account_info import build_account_artifacts, parse_account_info
from stopa.artifacts.google_calendar_events import (
    MAX_EVENTS_PER_FILE,
    parse_google_calendar_events,
)
from stopa.artifacts.google_keep_tasks import (
    MAX_ITEMS_PER_FILE as KEEP_MAX,
)
from stopa.artifacts.google_keep_tasks import (
    parse_google_keep_tasks,
)
from stopa.artifacts.google_location_history import (
    MAX_POINTS_PER_FILE,
    parse_location_history_csv,
    parse_location_history_json,
)
from stopa.artifacts.google_login_history import (
    MAX_ENTRIES_PER_FILE as LOGIN_MAX,
)
from stopa.artifacts.google_login_history import (
    parse_login_history_csv,
    parse_login_history_json,
)
from stopa.artifacts.google_search_history import (
    MAX_ENTRIES_PER_FILE as SEARCH_MAX,
)
from stopa.artifacts.google_search_history import (
    parse_google_search_history,
)
from stopa.artifacts.google_voice_wr import (
    MAX_ENTRIES_PER_FILE as VOICE_MAX,
)
from stopa.artifacts.google_voice_wr import (
    parse_google_voice,
)

_BOM = b"\xef\xbb\xbf"
_GARBAGE = b"\x01\x02\xff\xfebinarni smeti"


def _js(obj: object) -> bytes:
    return json.dumps(obj).encode("utf-8")


# ---------------------------------------------------------------------------
# google_account_info — corrupted / encoding / locale / size / tz
# ---------------------------------------------------------------------------


def test_acct_corrupted_inputs():
    # quality: corrupted
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_account_info(b'{"name": "Jan Nova", ')  # oříznuté JSON
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_account_info(_GARBAGE)


def test_acct_utf8_bom_rejected():
    # parser očekává čisté UTF-8 bez BOM
    # quality: encoding
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_account_info(_BOM + b'{"name": "Jan Nova"}')


def test_acct_czech_identity_roundtrip():
    # quality: locale
    info = parse_account_info(
        _js(
            {
                "name": "Jan Novák",
                "emailAddress": "jan.novak@post.cz",
                "phoneNumber": "+420 777 123 456",
                "city": "Praha, Česká republika",
            }
        )
    )
    assert info is not None
    assert info.name == "Jan Novák"
    assert info.email == "jan.novak@post.cz"
    assert info.phone == "+420 777 123 456"
    assert info.extra.get("city") == "Praha, Česká republika"


def test_acct_long_name_bounded_artifact():
    # neomezený input → omezený output (title ≤ 120 znaků)
    # quality: size
    info = parse_account_info(_js({"name": "X" * 250}))
    assert info is not None
    assert len(info.name) == 250  # parser zachovává celé jméno
    (artifact,) = build_account_artifacts(info)
    assert len(artifact.title) <= 120


def test_acct_snapshot_no_timestamp():
    # dokumentováno: snapshot profilu bez času
    # quality: tz
    info = parse_account_info(_js({"name": "Jan Novák"}))
    assert info is not None
    (artifact,) = build_account_artifacts(info)
    assert artifact.timestamp is None


# ---------------------------------------------------------------------------
# google_calendar_events — corrupted / encoding / locale / size+tz / boundary
# ---------------------------------------------------------------------------

_CAL_UTC_EPOCH = datetime(2024, 10, 3, 12, 0, tzinfo=timezone.utc).timestamp()


def test_cal_corrupted_inputs():
    # quality: corrupted
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_google_calendar_events(_GARBAGE)
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_google_calendar_events(b'[{"summary": "')  # oříznuté


def test_cal_utf8_bom_rejected():
    # quality: encoding
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_google_calendar_events(_BOM + b"[]")


def test_cal_czech_subject_roundtrip():
    # quality: locale
    recs = parse_google_calendar_events(
        _js(
            [
                {
                    "summary": "Setkání s dodavatelem — úvodní schůzka",
                    "start": {"dateTime": "2024-10-03T14:00:00+02:00"},
                    "location": "Praha, Česká republika",
                }
            ]
        )
    )
    assert len(recs) == 1
    assert recs[0].subject == "Setkání s dodavatelem — úvodní schůzka"


def test_cal_tz_offset_normalized_to_utc():
    # offset +02:00 i epoch passthrough → stejný UTC epoch
    # quality: tz
    recs = parse_google_calendar_events(
        _js(
            [
                {"summary": "a", "start": {"dateTime": "2024-10-03T14:00:00+02:00"}},
                {"subject": "b", "startDateTime": 1727956800, "endDateTime": 1727956800 + 3600},
            ]
        )
    )
    assert recs[0].start_s == _CAL_UTC_EPOCH
    assert recs[1].start_s == float(1727956800) == _CAL_UTC_EPOCH


def test_cal_limit_truncation_and_minimal():
    # 5001 událostí → truncation na MAX; minimální input
    # quality: boundary size
    big = [{"summary": f"e{i}"} for i in range(MAX_EVENTS_PER_FILE + 1)]
    recs = parse_google_calendar_events(_js(big))
    assert len(recs) == MAX_EVENTS_PER_FILE
    single = parse_google_calendar_events(_js([{"summary": "jediná"}]))
    assert len(single) == 1 and single[0].subject == "jediná"


# ---------------------------------------------------------------------------
# google_keep_tasks — corrupted / encoding / locale / size+tz / boundary
# ---------------------------------------------------------------------------


def test_keep_corrupted_inputs():
    # quality: corrupted
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_google_keep_tasks(_GARBAGE)
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_google_keep_tasks(b'[{"title": "')  # oříznuté


def test_keep_utf8_bom_rejected():
    # quality: encoding
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_google_keep_tasks(_BOM + b"[]")


def test_keep_czech_note_roundtrip():
    # quality: locale
    recs = parse_google_keep_tasks(
        _js(
            [
                {
                    "title": "Nákupní seznam",
                    "text": "Kopřivy, špenát, česnek",
                    "creationTime": "2024-10-03T14:00:00+02:00",
                }
            ]
        )
    )
    assert len(recs) == 1
    assert recs[0].title == "Nákupní seznam"
    assert recs[0].text == "Kopřivy, špenát, česnek"


def test_keep_tz_modified_utc():
    # modificationTime s offsetem i epoch → stejný UTC epoch
    # quality: tz
    recs = parse_google_keep_tasks(
        _js([{"title": "x", "modificationTime": "2024-10-03T14:00:00+02:00", "creationTime": 1727956800}])
    )
    assert recs[0].modified_s == _CAL_UTC_EPOCH
    assert recs[0].created_s == float(1727956800)


def test_keep_limit_truncation_and_minimal():
    # 5001 položek → truncation na MAX; minimální input
    # quality: boundary size
    big = [{"title": f"n{i}"} for i in range(KEEP_MAX + 1)]
    recs = parse_google_keep_tasks(_js(big))
    assert len(recs) == KEEP_MAX
    single = parse_google_keep_tasks(_js([{"title": "jediná"}]))
    assert len(single) == 1 and single[0].title == "jediná"


# ---------------------------------------------------------------------------
# google_voice_wr — corrupted / encoding / locale+size / boundary / tz
# ---------------------------------------------------------------------------


def test_voice_corrupted_inputs():
    # quality: corrupted
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_google_voice(_GARBAGE)
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_google_voice(b'[{"body": "')  # oříznuté


def test_voice_utf8_bom_rejected():
    # quality: encoding
    sms = _js([{"from": "+420", "body": "a", "timestampMsInEpoch": 1}])
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_google_voice(_BOM + sms)


def test_voice_czech_sms_roundtrip():
    # česká diakritika v SMS těle bez ztráty
    # quality: locale
    kind, recs = parse_google_voice(
        _js([{"from": "+420 777 123 456", "body": "Přijď večer na večeři!", "timestampMsInEpoch": 1725000000000}])
    )
    assert kind == "sms"
    assert recs[0].details["body"] == "Přijď večer na večeři!"


def test_voice_body_truncated_at_500():
    # detail body omezen na 500 znaků
    # quality: size
    long_body = ("Špenát " * 200).strip()
    assert len(long_body) > 500
    kind, recs = parse_google_voice(_js([{"from": "+420 777", "body": long_body}]))
    assert kind == "sms"
    assert len(recs[0].details["body"]) == 500
    assert recs[0].details["body"].startswith("Špenát")


def test_voice_limit_truncation_and_minimal():
    # 5001 SMS → truncation na MAX; minimální input
    # quality: boundary size
    big = [{"from": "+420", "body": f"x{i}", "timestampMsInEpoch": i} for i in range(VOICE_MAX + 1)]
    kind, recs = parse_google_voice(_js(big))
    assert kind == "sms"
    assert len(recs) == VOICE_MAX
    single_kind, single = parse_google_voice(_js([{"from": "+420", "body": "a"}]))
    assert single_kind == "sms" and len(single) == 1


def test_voice_epoch_ms_to_utc_seconds():
    # timestampMsInEpoch ms → epoch sekundy přesně (bez ztráty)
    # quality: tz
    dt = datetime(2024, 8, 30, 4, 0, tzinfo=timezone.utc)
    ms = int(dt.timestamp() * 1000)
    kind, recs = parse_google_voice(_js([{"from": "+420", "body": "ok", "timestampMsInEpoch": ms}]))
    assert kind == "sms"
    assert recs[0].timestamp_s is not None
    assert abs(recs[0].timestamp_s - dt.timestamp()) < 1e-6


# ---------------------------------------------------------------------------
# google_location_history — corrupted / encoding / locale / size+tz / boundary
# ---------------------------------------------------------------------------


def test_loc_corrupted_json_and_csv():
    # quality: corrupted
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_location_history_json(_GARBAGE)
    csv_no_cols = b"Time,Temperature\n1,2\n"
    with pytest.raises(ValueError, match="Chybí sloupce Latitude/Longitude"):
        parse_location_history_csv(csv_no_cols)


def test_loc_bom_contrast():
    # JSON očekává čisté UTF-8 (BOM → ValueError),
    # quality: encoding
    # CSV čte utf-8-sig (BOM stripnutý, parsuje se bez chyby)
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_location_history_json(_BOM + b"[]")
    csv = _BOM + b"Timestamp,Latitude,Longitude\n1625097600,48.85,2.35\n"
    pts = parse_location_history_csv(csv)
    assert len(pts) == 1


def test_loc_czech_device_roundtrip():
    # quality: locale
    pts = parse_location_history_json(
        _js([{"latitudeE7": 488500000, "longitudeE7": 235500000, "deviceID": "Přenosné zařízení"}])
    )
    assert len(pts) == 1
    assert pts[0].device_id == "Přenosné zařízení"


def test_loc_limit_truncation():
    # 5001 bodů → truncation na MAX_POINTS_PER_FILE
    # quality: size
    big = [{"latitudeE7": i, "longitudeE7": 0} for i in range(MAX_POINTS_PER_FILE + 1)]
    assert len(parse_location_history_json(_js(big))) == MAX_POINTS_PER_FILE


def test_loc_epoch_boundary_detection():
    # CSV epoch s (10 číslic) → ×1000, epoch ms (13 číslic)
    # quality: boundary
    # passthrough, ISO/nečíselné tvary → None (graceful); JSON nečíselné ts → None
    csv = (
        b"Timestamp,Latitude,Longitude\n"
        b"1625097600,48.85,2.35\n"
        b"1625097600123,48.86,2.36\n"
        b"2021-07-01T12:00:00Z,48.87,2.37\n"
    )
    pts = parse_location_history_csv(csv)
    assert [p.timestamp_ms for p in pts] == [1625097600_000, 1625097600_123, None]
    bad_ts = parse_location_history_json(_js([{"latitudeE7": 1, "longitudeE7": 1, "timestampMsSinceEpoch": "abc"}]))
    assert bad_ts[0].timestamp_ms is None


def test_loc_utc_epoch_exact():
    # epoch ms přesně bez ztráty (from_unix → aware UTC)
    # quality: tz
    dt = datetime(2021, 7, 1, 12, 0, tzinfo=timezone.utc)
    pts = parse_location_history_json(
        _js([{"latitudeE7": 488500000, "longitudeE7": 235500000, "timestampMsSinceEpoch": str(int(dt.timestamp() * 1000))}])
    )
    assert pts[0].timestamp_ms == int(dt.timestamp() * 1000)


# ---------------------------------------------------------------------------
# google_login_history — corrupted / encoding / locale / size+tz / boundary
# ---------------------------------------------------------------------------


def test_login_corrupted_json_and_csv():
    # quality: corrupted
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_login_history_json(_GARBAGE)
    csv_no_ip = b"Foo,Bar\n1,2\n"  # žádné z Time/Device/IP sloupců
    with pytest.raises(ValueError, match="Chybí sloupce Time/Device/IP"):
        parse_login_history_csv(csv_no_ip)


def test_login_utf8_bom_rejected():
    # quality: encoding
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_login_history_json(_BOM + b"[]")


def test_login_czech_device_location_roundtrip():
    # quality: locale
    recs = parse_login_history_json(
        _js(
            [
                {
                    "time": {"timestamp": "1625097600", "displayTime": "Jul 1, 2021, 8:00 AM"},
                    "deviceName": "Přenosné zařízení",
                    "ipAddress": "83.10.1.2",
                    "location": "Praha, Česká republika",
                }
            ]
        )
    )
    assert len(recs) == 1
    assert recs[0].device_name == "Přenosné zařízení"
    assert recs[0].location == "Praha, Česká republika"


def test_login_limit_truncation():
    # 5001 záznamů → truncation na MAX_ENTRIES_PER_FILE
    # quality: size
    big = [{"time": {"timestamp": str(i)}, "deviceName": f"d{i}"} for i in range(LOGIN_MAX + 1)]
    assert len(parse_login_history_json(_js(big))) == LOGIN_MAX


def test_login_boundary_minimal_inputs():
    # minimální záznam (pouze čas) a prázdné [] = graceful
    # quality: boundary
    single = parse_login_history_json(_js([{"time": {"timestamp": "1625097600"}}]))
    assert len(single) == 1 and single[0].timestamp_s == 1625097600
    assert parse_login_history_json(b"[]") == []


def test_login_epoch_utc_exact():
    # string epoch → int přesně (from_unix → aware UTC)
    # quality: tz
    dt = datetime(2021, 7, 1, 12, 0, tzinfo=timezone.utc)
    recs = parse_login_history_json(_js([{"time": {"timestamp": str(int(dt.timestamp()))}}]))
    assert recs[0].timestamp_s == int(dt.timestamp())


# ---------------------------------------------------------------------------
# google_search_history — corrupted / encoding / locale / size+tz / boundary
# ---------------------------------------------------------------------------


def test_search_corrupted_and_non_list():
    # quality: corrupted
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_google_search_history(_GARBAGE)
    with pytest.raises(TypeError, match="Očekáváno JSON pole záznamů"):
        parse_google_search_history(b'{"a": 1}')


def test_search_utf8_bom_rejected():
    # quality: encoding
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_google_search_history(_BOM + b"[]")


def test_search_czech_query_roundtrip():
    # quality: locale
    recs = parse_google_search_history(
        _js([{"key": "webSearch", "time": {"timestamp": "1625097600"}, "title": "české recepty na škvarky"}])
    )
    assert len(recs) == 1
    assert recs[0].query == "české recepty na škvarky"


def test_search_limit_truncation():
    # 5001 záznamů → truncation na MAX_ENTRIES_PER_FILE
    # quality: size
    big = [{"key": "webSearch", "time": {"timestamp": str(i)}, "title": f"q{i}"} for i in range(SEARCH_MAX + 1)]
    assert len(parse_google_search_history(_js(big))) == SEARCH_MAX


def test_search_boundary_minimal_inputs():
    # jeden záznam; ne-dict položky = graceful skip
    # quality: boundary
    single = parse_google_search_history(
        _js([{"key": "webSearch", "time": {"timestamp": "1625097600"}, "title": "houby"}])
    )
    assert len(single) == 1 and single[0].query == "houby"
    assert parse_google_search_history(b'["nejson"]') == []


def test_search_epoch_utc_exact():
    # string epoch → int přesně (from_unix → aware UTC)
    # quality: tz
    dt = datetime(2021, 7, 1, 12, 0, tzinfo=timezone.utc)
    recs = parse_google_search_history(
        _js([{"key": "webSearch", "time": {"timestamp": str(int(dt.timestamp()))}, "title": "x"}])
    )
    assert recs[0].timestamp == int(dt.timestamp())
