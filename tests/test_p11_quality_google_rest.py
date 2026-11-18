"""ETAPA B vlna 11 — Google Takeout zbytek rodiny (10 parserů), quality sady.

Doplňuje chybějící kategorie pro posledních 10 Google parserů, aby celá
Google rodina byla plně pokryta ve všech 8 kategoriích:

- ``google_account_change_history`` — corrupted, locale
- ``google_aggregated_activities`` — corrupted, locale
- ``google_chat_family`` — corrupted, locale
- ``google_export_summary`` — corrupted, locale
- ``google_identity_sessions`` — corrupted, locale
- ``google_linked_devices`` — corrupted, locale
- ``google_maps_activity`` — corrupted, locale
- ``google_2025_wr`` — negative, locale (+corrupted přes sdílený marker)
- ``google_mail_info`` — tz, encoding, locale, size
- ``google_photos`` — tz, encoding, locale, size

Kontrakty (ověřeno proti zdrojům vlny 1–6):
- Všech 10 parserů dekoduje přes ``json.loads(data.decode("utf-8",
  errors="replace"))`` → **BOM prefix → ValueError „Neplatné JSON"**
  (žádný z nich nečte utf-8-sig).
- Chybové prefixy: account meta rodina ``Neplatné JSON (<what>)``, ostatní
  holé ``Neplatné JSON: ...``; TypeError kontrakty per parser viz testy.
- Časy: mail_info ``internalDate`` = µs od epochy (>1e14 → /1e6), tolerantně
  i ms/s/ISO (naive ISO → UTC); photos/account_meta/2025_wr/identity
  ``_parse_iso_or_epoch``/``_to_epoch`` — ISO Z+offset, epoch s/ms
  (string ≥13 číslic → /1000); chat timestamp = webkit µs (>1e15 → /1e6).
- Limity: MAX_*_PER_FILE = 5_000 u všech; chat má globální strop zpráv na
  parse volání (break při dosáhnutí limitu).

# quality: corrupted encoding locale negative size tz
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from stopa.artifacts.google_2025_wr import parse_google_2025_wr
from stopa.artifacts.google_account_meta import (
    MAX_ENTRIES_PER_FILE as META_MAX,
)
from stopa.artifacts.google_account_meta import (
    parse_account_change_history,
    parse_export_summary,
    parse_linked_devices,
)
from stopa.artifacts.google_aggregated_activities import (
    parse_aggregated_activities,
    parse_identity_sessions,
)
from stopa.artifacts.google_chat_family import MAX_MESSAGES_PER_FILE as CHAT_MAX
from stopa.artifacts.google_chat_family import parse_chat_messages
from stopa.artifacts.google_mail_info import MAX_ENTRIES_PER_FILE as MAIL_MAX
from stopa.artifacts.google_mail_info import parse_mail_info
from stopa.artifacts.google_maps_activity import (
    MAX_OBJECTS_PER_FILE as MAPS_MAX,
)
from stopa.artifacts.google_maps_activity import parse_maps_activity
from stopa.artifacts.google_photos import MAX_ENTRIES_PER_FILE as PHOTOS_MAX
from stopa.artifacts.google_photos import parse_photos

_GARBAGE = b"\x01\x02\xff\xfebinarni smeti"
_BOM = b"\xef\xbb\xbf"

# 2024-01-15T10:30:00Z — kanonický referenční okamžik pro tz ekvivalence
TS_S = 1_705_314_600.0


def _js(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=True).encode("utf-8")


# ---------------------------------------------------------------------------
# corrupted
# ---------------------------------------------------------------------------


def test_account_change_history_corrupted() -> None:
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_account_change_history(_GARBAGE)
    with pytest.raises(ValueError, match="Neplatné JSON"):
        # oříznuté JSON
        parse_account_change_history(b'[{"eventType": ')


def test_linked_devices_corrupted_and_type_error() -> None:
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_linked_devices(_GARBAGE)
    # kořen bez wrapper klíče (events/devices/items/data) → TypeError
    with pytest.raises(TypeError, match="Očekáváno JSON pole"):
        parse_linked_devices(b"{}")
    # wrapper objekt s devices polem funguje
    recs = parse_linked_devices(_js({"devices": [{"name": "X"}]}))
    assert len(recs) == 1


def test_export_summary_corrupted_and_type_error() -> None:
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_export_summary(_GARBAGE)
    with pytest.raises(TypeError, match="Očekáván JSON objekt"):
        parse_export_summary(b"[1]")
    assert parse_export_summary(_js({"products": ["Gmail"]})) == {"products": ["Gmail"]}


def test_aggregated_activities_corrupted_and_type_error() -> None:
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_aggregated_activities(_GARBAGE)
    with pytest.raises(TypeError, match="Očekáváno JSON pole"):
        parse_aggregated_activities(b'{"a": 1}')


def test_identity_sessions_corrupted() -> None:
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_identity_sessions(_GARBAGE)
    with pytest.raises(TypeError, match="Očekáváno JSON pole"):
        parse_identity_sessions(b"{}")


def test_chat_family_corrupted_and_shapes() -> None:
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_chat_messages(_GARBAGE)
    # kořen musí být objekt s conversations polem
    with pytest.raises(TypeError, match="Očekáván JSON objekt s conversations"):
        parse_chat_messages(b"[]")
    assert parse_chat_messages(_js({"conversations": "ne-pole"})) == []


def test_maps_activity_corrupted_and_shapes() -> None:
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_maps_activity(_GARBAGE)
    with pytest.raises(TypeError, match="Očekáván JSON objekt s timelineObjects"):
        parse_maps_activity(b"[1]")
    # objekt bez timelineObjects → graceful []; ne-dict položky se skipují
    assert parse_maps_activity(_js({})) == []
    objs = parse_maps_activity(
        _js({"timelineObjects": [1, {"placeVisit": {"location": {}}}]})
    )
    assert len(objs) == 1


def test_2025_wr_corrupted() -> None:
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_google_2025_wr(_GARBAGE)
    with pytest.raises(ValueError, match="Neplatné JSON"):
        # oříznuté JSON
        parse_google_2025_wr(b'[{"deviceName": ')


# ---------------------------------------------------------------------------
# negative (platný JSON bez záznamů / špatný tvar kořene)
# ---------------------------------------------------------------------------


def test_2025_wr_negative_no_records() -> None:
    with pytest.raises(TypeError, match="Nenalezeny Google 2025 WR záznamy"):
        parse_google_2025_wr(_js({"foo": "bar"}))
    with pytest.raises(TypeError, match="Nenalezeny Google 2025 WR záznamy"):
        # pouze ne-dict položky → žádný záznam
        parse_google_2025_wr(b"[1, 2]")


def test_mail_info_negative_root_and_single_wrap() -> None:
    with pytest.raises(TypeError, match="Očekáváno JSON pole zpráv"):
        parse_mail_info(_js("text"))
    # jediný objekt s mail klíči → zabalí se do pole (1 záznam)
    recs = parse_mail_info(_js({"subject": "Ahoj", "internalDate": TS_S}))
    assert len(recs) == 1 and recs[0].subject == "Ahoj"


def test_photos_negative_root() -> None:
    with pytest.raises(TypeError, match="Očekáváno JSON pole fotek"):
        parse_photos(_js({}))


# ---------------------------------------------------------------------------
# locale (česká diakritika roundtrip)
# ---------------------------------------------------------------------------


def test_account_change_history_locale_roundtrip() -> None:
    evs = parse_account_change_history(
        _js(
            [
                {
                    "eventType": "PASSWORD_CHANGE",
                    "timestamp": "2024-01-15T10:30:00Z",
                    "deviceName": "Přenosná stanice Štěpán",
                    "location": "Hradec Králové",
                }
            ]
        )
    )
    assert evs[0].device_name == "Přenosná stanice Štěpán"
    assert evs[0].extra.get("location") == "Hradec Králové"


def test_linked_devices_locale_roundtrip() -> None:
    devs = parse_linked_devices(
        _js([{"name": "Špenátův telefon", "model": "Galaxy S24"}])
    )
    assert devs[0].name == "Špenátův telefon"


def test_export_summary_locale_roundtrip() -> None:
    summary = parse_export_summary(_js({"products": ["Fotografie", "Kalendář"]}))
    assert summary["products"] == ["Fotografie", "Kalendář"]


def test_aggregated_activities_locale_roundtrip() -> None:
    days = parse_aggregated_activities(
        _js([{"date": "2024-01-15", "activities": [{"type": "PŘECHOD_PEŠÍ", "count": 3}]}])
    )
    assert days[0].activities[0]["type"] == "PŘECHOD_PEŠÍ"


def test_identity_sessions_locale_roundtrip() -> None:
    sess = parse_identity_sessions(
        _js(
            [
                {
                    "deviceInfo": {"name": "Hráč Štěpán", "model": "M1"},
                    "location": "České Budějovice",
                    "sessionStartTimestamp": "2024-01-15T10:30:00Z",
                }
            ]
        )
    )
    assert sess[0].device_name == "Hráč Štěpán"
    assert sess[0].extra.get("location") == "České Budějovice"


def _chat_payload(texts: list[str]) -> bytes:
    return _js(
        {
            "conversations": [
                {
                    "conversation": {"conversation_id": {"id": "conv-1"}},
                    "events": [
                        {
                            "event_type": "CHAT_MESSAGE",
                            "sender_id": {"gaia_id": "user-1"},
                            "chat_message": {
                                "message_content": {
                                    "segment": [{"type": "TEXT", "text": t}]
                                }
                            },
                            "timestamp": str(int(TS_S * 1_000_000) + i),
                        }
                        for i, t in enumerate(texts)
                    ],
                }
            ]
        }
    )


def test_chat_family_locale_roundtrip() -> None:
    msgs = parse_chat_messages(_chat_payload(["Špenát žluťoučký, mák zelený"]))
    assert msgs[0].text == "Špenát žluťoučký, mák zelený"


def _maps_payload(n: int, name: str = "Kavárna U Švýcarů") -> bytes:
    objs = [
        {
            "placeVisit": {
                "location": {"latitudeE7": 501028934, "longitudeE7": 144363619},
                "place": {"name": name, "address": "Pražská 123, Praha"},
            }
        }
        for _ in range(n)
    ]
    return _js({"timelineObjects": objs})


def test_maps_activity_locale_roundtrip() -> None:
    objs = parse_maps_activity(_maps_payload(1))
    assert objs[0].place_name == "Kavárna U Švýcarů"
    assert objs[0].address == "Pražská 123, Praha"


def test_mail_info_locale_roundtrip() -> None:
    recs = parse_mail_info(
        _js(
            [
                {
                    "threadId": "t-1",
                    "subject": "Faktura za špeňkové práce",
                    "from": {"emailAddress": "jan.novak@example.cz"},
                    "to": [{"emailAddress": "mirka@example.cz"}],
                    "snippet": ("Štěpán poslal smlouvu. " * 20).strip(),
                    "internalDate": TS_S,
                }
            ]
        )
    )
    assert recs[0].subject == "Faktura za špeňkové práce"
    assert recs[0].sender == "jan.novak@example.cz"
    assert recs[0].recipients == ["mirka@example.cz"]


def test_photos_locale_roundtrip() -> None:
    recs = parse_photos(
        _js([{"filename": "fotka_u_mlyna.jpg", "description": "Štěpánova vila u rybníka"}])
    )
    assert recs[0].filename == "fotka_u_mlyna.jpg"
    assert recs[0].description == "Štěpánova vila u rybníka"


def test_2025_wr_locale_roundtrip() -> None:
    recs = parse_google_2025_wr(
        _js([{"deviceName": "Stanice Štěpán", "app": "Hra Špenát", "accessTime": TS_S}])
    )
    assert recs[0].kind == "access_log"
    assert "Štěpán" in (recs[0].name or "")
    assert "Špenát" in (recs[0].detail or "")


# ---------------------------------------------------------------------------
# tz (ekvivalence formátů času → stejný přesný UTC epoch)
# ---------------------------------------------------------------------------


def test_account_change_history_tz_iso_vs_epoch_ms() -> None:
    iso = parse_account_change_history(_js([{"timestamp": "2024-01-15T10:30:00Z"}]))[0]
    ms = parse_account_change_history(_js([{"timestamp": 1_705_314_600_000}]))[0]
    s_str = parse_account_change_history(
        _js([{"timestamp": "1705314600"}])
    )[0]
    assert iso.timestamp_s == TS_S
    assert ms.timestamp_s == TS_S  # int ms > 1e12 → /1000
    assert s_str.timestamp_s == TS_S  # string epoch s (10 číslic)


def test_linked_devices_tz_string_epoch_ms() -> None:
    iso = parse_linked_devices(_js([{"lastUsedTimestamp": "2024-01-15T10:30:00Z"}]))[0]
    ms_str = parse_linked_devices(
        _js([{"lastUsedTimestamp": "1705314600000"}])  # string, 13 číslic → /1000
    )[0]
    assert iso.last_used_s == TS_S
    assert ms_str.last_used_s == TS_S


def test_mail_info_tz_microsecond_iso_equivalence() -> None:
    def _ts(raw) -> float | None:
        return parse_mail_info(_js([{"internalDate": raw}]))[0].timestamp_s

    # µs od epochy (Takeout internalDate) == ms == s == ISO Z
    assert _ts(1_705_314_600_000_000) == TS_S  # >1e14 → /1e6
    assert _ts(1_705_314_600_000) == TS_S
    assert _ts(TS_S) == TS_S
    assert _ts("2024-01-15T10:30:00Z") == TS_S
    # naive ISO → interpretace jako UTC
    assert _ts("2024-01-15T10:30:00") == TS_S


def test_photos_tz_offset_and_epoch() -> None:
    # 2026-03-15T08:30:45+02:00 == 2026-03-15T06:30:45Z
    expected_ms = int(
        datetime(2026, 3, 15, 6, 30, 45, tzinfo=timezone.utc).timestamp() * 1000
    )

    def _ts(raw) -> float:
        v = parse_photos(_js([{"photoTakenTime": {"timestamp": raw}}]))[0].timestamp_s
        assert v is not None
        return v

    iso_offset = _ts("2026-03-15T08:30:45+02:00")
    iso_z = _ts("2026-03-15T06:30:45Z")
    ms_int = _ts(expected_ms)
    assert abs(iso_offset - expected_ms / 1000.0) < 0.001
    assert iso_z == pytest.approx(expected_ms / 1000.0, abs=0.001)
    assert ms_int == pytest.approx(expected_ms / 1000.0, abs=0.001)


def test_2025_wr_tz_ms_vs_iso() -> None:
    iso = parse_google_2025_wr(
        _js([{"deviceName": "X", "accessTime": "2024-01-15T10:30:00Z"}])
    )[0]
    ms = parse_google_2025_wr(_js([{"deviceName": "X", "accessTime": 1_705_314_600_000}]))[0]
    assert iso.created_s == TS_S
    assert ms.created_s == TS_S  # heuristika ≥1e12 → /1000


# ---------------------------------------------------------------------------
# encoding (BOM prefix — žádný z parserů nečte utf-8-sig)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (parse_mail_info, b'[{"subject": "x"}]'),
        (parse_photos, b'{"photos": [{"filename": "a.jpg"}]}'),
        (parse_account_change_history, b'[{"eventType": "X"}]'),
    ],
)
def test_bom_prefix_rejected(parser, payload: bytes) -> None:
    # čisté UTF-8 bez BOM projde (neprázdný výsledek), s BOM prefixem → ValueError
    assert parser(payload)
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parser(_BOM + payload)


# ---------------------------------------------------------------------------
# size / boundary (limity MAX_*_PER_FILE = 5000)
# ---------------------------------------------------------------------------


def test_mail_info_limit_and_snippet_truncation() -> None:
    big = [{"threadId": f"t{i}", "subject": f"s{i}"} for i in range(MAIL_MAX + 1)]
    recs = parse_mail_info(_js(big))
    assert len(recs) == MAIL_MAX

    long_body = ("Štěpán poslal smlouvu. " * 60).strip()
    assert len(long_body) > 500
    one = parse_mail_info(_js([{"snippet": long_body, "internalDate": TS_S}]))[0]
    assert len(one.snippet) == 500


def test_photos_limit_truncation() -> None:
    big = [{"filename": f"f{i}.jpg"} for i in range(PHOTOS_MAX + 1)]
    recs = parse_photos(_js(big))
    assert len(recs) == PHOTOS_MAX


def test_account_change_history_limit_truncation() -> None:
    big = [{"eventType": "X", "timestamp": str(TS_S)} for _ in range(META_MAX + 1)]
    evs = parse_account_change_history(_js(big))
    assert len(evs) == META_MAX


def test_chat_messages_global_cap() -> None:
    # globální strop zpráv na jedno parse volání (break při limitu)
    msgs = parse_chat_messages(_chat_payload([f"zpráva {i}" for i in range(CHAT_MAX + 1)]))
    assert len(msgs) == CHAT_MAX


def test_maps_objects_limit_truncation() -> None:
    objs = parse_maps_activity(_maps_payload(MAPS_MAX + 1))
    assert len(objs) == MAPS_MAX
