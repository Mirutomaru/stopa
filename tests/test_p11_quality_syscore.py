"""STOPA — P1-1 quality sada vlna 15 (chrome_preferences + plist + registry_hive + evtx + lnk).

Windows/Apple system core rodina. Kontrakty doložené per parser:

``chrome_preferences`` — Chrome Preferences JSON (profilový export):
- corrupted = BOM prefix → ValueError „Neplatné JSON" (json.loads odmítá \\ufeff),
  binární smetí → ValueError; extract na soubor graceful ``[]``;
  neobjektový kořen (JSON pole) → TypeError „Očekáván JSON objekt (Chrome Preferences)";
- tz = dokumentovaný snapshot kontrakt: všechny artifacty ``timestamp=None``;
- encoding/locale = UTF-8 vstup, česká diakritika v názvech extension/vyhledávačů
  verbatim; title truncation [:120];
- size = MAX_EXTENSIONS_PER_FILE=2000 (2001 extension → přesně 2000 záznamů).

``plist`` — Apple property list (binární bplist00 i XML, nativní ``plistlib``):
- negative = skalární kořen / prázdný dict → jen triage artifact
  (root_type „str"/„dict", top_level_keys [], žádné date artifacty);
- tz = passthrough datetime objektů: binární FMT_BINARY vyžaduje naive datetimes
  (plistlib epocha od 2001) → naive artefakt; XML ``<date>...Z</date>`` plistlib
  parsuje jako naive (Z se stripne — dokumentované chování); aware UTC na úrovni
  ``build_plist_artifacts`` passthrough +00:00;
- encoding/locale = binární roundtrip s českými klíči verbatim v triage
  top_level_keys; date artifact title ``{path} = {isoformat}`` s cestou klíče;
- size = MAX_DATE_ARTIFACTS=50 (60 datových polí → 50 artefaktů, date_fields=51 —
  break po inkrementaci), MAX_TOP_KEYS=30 (35 klíčů → 30 + truncated=True);
  list kořen → top_level_keys ``["[i]"]``.

``registry_hive`` — Windows registry hive (regipy, čisté build funkce nad subkeys):
- positive/boundary = priorita vzorců: RunOnce před Run (substring shoda,
  case-insensitive normalizace slash→backslash); MountedDevices → registry_usb_device;
- tz = passthrough subkey timestampu: aware UTC se zachová, None zůstává None;
- encoding = bytes hodnoty → utf-8 errors=replace (invalidní bajty → U+FFFD),
  str hodnoty verbatim; locale = česká diakritika v hodnotách verbatim;
- size = MAX_VALUE_LEN=200 (hodnota 250 znaků → přesně 200);
- negative = prázdný kontejner (bez values) skipnut, neznámá cesta bez artifactu.

``evtx`` — Windows Event Log (EVTX standard + ElfFile varianta):
- corrupted = <128 B → ValueError „EVTX soubor příliš krátký: N B (min 128)",
  cizí magic → ValueError „Neznámá EVTX magic"; extract graceful ``[]``;
- tz = FILETIME → aware UTC datetime (standard i ElfFile);
- locale = BinXML heuristika extrahuje nejdelší ASCII run ≥30 znaků verbatim —
  diakritický segment před ním se rozbíjí runy (dokumentované chování
  ``_extract_binxml_strings``); lichý byte v UTF-16LE payloadu → errors=replace,
  žádná výjimka; jen event_id bez provider/message → title „ID N", confidence 0.6;
- negative = validní magic + nula záznamů → 0 entries → ``[]`` artifactů;
  confidence 0.85 s message (fixture standard/ElfFile).

``lnk`` — MS-LNK shell link (hlavička 76 B + bloky):
- corrupted = <76 B → ValueError „LNK too short: N B (min 76)", cizí CLSID @4..20
  → ValueError „bad LNK CLSID"; extract graceful ``[]``;
- tz = FILETIME creation/access/write → aware UTC (passthrough do artifactu,
  details access_time/write_time jako ISO řetězce);
- locale = Name blok UTF-16LE s diakritikou verbatim (parsed + details.name),
  path stringy ANSI/CP1252;
- size = max_scan=4096 B od @76 při hledání prvního ANSI path — path za hranicí
  nenalezen (target_path None), pod hranicí nalezen verbatim.
"""

from __future__ import annotations

import json
import plistlib
import struct
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from stopa.artifacts.chrome_preferences import (
    build_pref_artifacts,
    extract_chrome_pref_artifacts,
    parse_chrome_preferences,
)
from stopa.artifacts.plist_extract import build_plist_artifacts, extract_plist_artifacts
from stopa.artifacts.registry_extract import build_registry_artifacts
from stopa.artifacts.win_eventlog import (
    build_evtx_artifacts,
    extract_evtx_artifacts,
    parse_evtx_file,
)
from stopa.artifacts.win_lnk import build_lnk_artifacts, extract_lnk_artifacts, parse_lnk

# Reuse overěřených fixture generátorů ze stávajících sad (precedent: vlny 9/14).
from tests.test_e6 import LNK_CLSID, make_lnk
from tests.test_e7 import _ft, make_evtx_elf, make_evtx_standard

# Tato sada pokrývá chybějící kategorie (negative/corrupted/tz/encoding/locale/size)
# pro všech 5 parserů vlny 15 → category coverage 87.7 % → 91.3 %.
# quality: negative corrupted tz encoding locale size

UTC = timezone.utc


def _evtx_custom(message: str, odd_payload: bool = False) -> bytes:
    """Standard EVTX chunk s jedním záznamem a vlastním BinXML textem (UTF-16LE)."""
    hdr = bytearray(128)
    hdr[0:4] = b"EVTX"
    struct.pack_into("<I", hdr, 0x20, 128)
    data = bytes(hdr)

    ch = bytearray(128)
    ch[0:4] = b"CHUN"
    struct.pack_into("<I", ch, 0x28, 128)
    data += bytes(ch)

    payload = ("EventID\x004625\x00ProviderX\x00" + message).encode("utf-16-le")
    if odd_payload:
        payload += b"\x01"  # lichý byte → UTF-16LE decode errors=replace

    total = 40 + len(payload)
    rec = bytearray(total)
    struct.pack_into("<I", rec, 0x00, total)
    struct.pack_into("<H", rec, 0x04, 40)
    struct.pack_into("<H", rec, 0x06, 1)
    struct.pack_into("<Q", rec, 0x0C, _ft(2026, 10, 26, 15, 20, 19))
    rec[40:total] = payload
    return data + bytes(rec)


def _lnk_padded(pad_bytes: int, target: str) -> bytes:
    """LNK hlavička + null padding + ANSI path (hranice max_scan=4096)."""
    hdr = bytearray(76)
    struct.pack_into("<I", hdr, 0, 76)
    hdr[4:20] = LNK_CLSID
    struct.pack_into("<II", hdr, 20, 0x0100, 0x20)
    ft = _ft(2026, 5, 1)
    for off in (28, 36, 44):
        struct.pack_into("<Q", hdr, off, ft)
    struct.pack_into("<q", hdr, 52, 99)
    return bytes(hdr) + b"\x00" * pad_bytes + target.encode("cp1252") + b"\x00"


def _subkey(path: str, ts=None, values=()):
    """Fake registry subkey pro čisté build_registry_artifacts testy."""
    return SimpleNamespace(
        path=path,
        timestamp=ts,
        values=[SimpleNamespace(name=n, value=v) for n, v in values],
    )


# ── chrome_preferences ─────────────────────────────────────────────────────


def test_chrome_pref_positive_extensions_search_sync():
    """Extension + default search provider + sync sekce → artifacty s detaily."""
    payload = {
        "extensions": {"settings": {
            "abc.cde": {"manifest": {"name": "Nastroj"}, "state": 1, "location": 0},
        }},
        "default_search_provider_data": {"template_url_data": {
            "short_name": "Seftelka",
            "search_url": "https://hledani.sef.cz/?q=%s",
        }},
        "sync": {"preferred": True, "passthrough": False},
    }
    records = parse_chrome_preferences(json.dumps(payload).encode())
    arts = build_pref_artifacts(records)

    ext_arts = [a for a in arts if a.artifact_type == "browser_extension"]
    set_arts = [a for a in arts if a.artifact_type == "browser_setting"]
    assert len(ext_arts) == 1
    title = ext_arts[0].title
    assert title is not None and "Nastroj" in title
    assert ext_arts[0].confidence == pytest.approx(0.85)

    search = [a for a in set_arts if a.details.get("setting") == "default_search_provider"]
    assert len(search) == 1
    assert search[0].details["search_url"] == "https://hledani.sef.cz/?q=%s"

    sync = [a for a in set_arts if a.details.get("setting") == "sync"]
    assert len(sync) == 1
    assert sync[0].details["preferred"] is True


def test_chrome_pref_locale_diacritics_verbatim():
    """Česká diakritika v názvech extension/vyhledávače verbatim (UTF-8 vstup)."""
    payload = {
        "extensions": {"settings": {
            "x.y": {"manifest": {"name": "Příliš žluťoučký kůň"}},
        }},
        "default_search_provider_data": {"template_url_data": {
            "short_name": "Šéfův vyhledávač",
        }},
    }
    records = parse_chrome_preferences(json.dumps(payload, ensure_ascii=False).encode())
    names = [r.name for r in records]
    assert "Příliš žluťoučký kůň" in names
    assert "Šéfův vyhledávač" in names

    arts = build_pref_artifacts(records)
    titles = " | ".join(a.title or "" for a in arts)
    assert "Příliš žluťoučký kůň" in titles
    assert "Šéfův vyhledávač" in titles


def test_chrome_pref_corrupted_bom_raises_value_error():
    """BOM prefix → ValueError (json.loads odmítá \\ufeff — dokumentované)."""
    payload = json.dumps({"extensions": {}}).encode()
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_chrome_preferences(b"\xef\xbb\xbf" + payload)


def test_chrome_pref_corrupt_binary_graceful_extract(tmp_path):
    """Binární smetí → ValueError v parseru; extract na soubor graceful []."""
    with pytest.raises(ValueError, match="Neplatné JSON"):
        parse_chrome_preferences(b"\x00\xff\xfebinarni-smeti" * 5)

    p = tmp_path / "prefs.json"
    p.write_bytes(b"\x00\xff\xfebinarni-smeti")
    assert extract_chrome_pref_artifacts(p) == []


def test_chrome_pref_non_object_root_type_error():
    """Platné JSON, ale ne objekt (pole) → TypeError s přesnou zprávou."""
    with pytest.raises(TypeError, match="Očekáván JSON objekt"):
        parse_chrome_preferences(b"[1, 2, 3]")


def test_chrome_pref_size_extension_cap_2000():
    """MAX_EXTENSIONS_PER_FILE=2000 — 2001 extension → přesně 2000 záznamů."""
    exts = {f"ext{i:04d}": {"manifest": {"name": f"E{i}"}} for i in range(2001)}
    records = parse_chrome_preferences(json.dumps({"extensions": {"settings": exts}}).encode())
    assert len(records) == 2000

    arts = build_pref_artifacts(records)
    assert len(arts) == 2000


def test_chrome_pref_tz_snapshot_none_and_title_truncation():
    """Snapshot kontrakt: timestamp=None vždy; title truncation [:120]."""
    records = parse_chrome_preferences(json.dumps({
        "extensions": {"settings": {"a.b": {"manifest": {"name": "D" * 200}}}},
    }).encode())
    arts = build_pref_artifacts(records)
    assert len(arts) == 1
    art = arts[0]
    assert art.timestamp is None
    title = art.title
    assert title is not None and len(title) == 120


# ── plist ───────────────────────────────────────────────────────────────────


def test_plist_positive_binary_roundtrip_dates_and_keys(tmp_path):
    """Binární bplist00 roundtrip: naive datetimes + české klíče verbatim."""
    dt = datetime(2026, 5, 1, 12, 30)  # FMT_BINARY vyžaduje naive (epocha 2001)
    pl = {"created": dt, "české_hodnota": "Příliš žluťoučký", "nested": {"hloubka": [dt]}}
    p = tmp_path / "test.plist"
    p.write_bytes(plistlib.dumps(pl, fmt=plistlib.FMT_BINARY))

    arts = extract_plist_artifacts(p)
    date_arts = [a for a in arts if a.artifact_type == "plist_date"]
    triage = next(a for a in arts if a.artifact_type == "property_list")

    assert len(date_arts) == 2
    first = date_arts[0]
    ts = first.timestamp
    assert ts is not None and ts.tzinfo is None  # naive passthrough (FMT_BINARY)
    title = first.title
    assert title is not None and "created" in title

    keys = triage.details["top_level_keys"]
    assert "české_hodnota" in keys
    assert triage.details["truncated"] is False


def test_plist_tz_xml_z_date_naive_documented(tmp_path):
    """XML <date>...Z</date> → plistlib parsuje jako naive (Z se stripne)."""
    xml_doc = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"'
        ' "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
        "<plist version=\"1.0\"><dict>"
        "<key>created</key><date>2026-05-01T12:30:00Z</date>"
        "</dict></plist>"
    )
    p = tmp_path / "test.xml.plist"
    p.write_bytes(xml_doc.encode("utf-8"))

    date_arts = [a for a in extract_plist_artifacts(p) if a.artifact_type == "plist_date"]
    assert len(date_arts) == 1
    ts = date_arts[0].timestamp
    assert ts is not None and ts.tzinfo is None
    assert ts.isoformat() == "2026-05-01T12:30:00"


def test_plist_tz_aware_utc_unit_level():
    """Aware UTC datetime na úrovni build funkce → passthrough +00:00."""
    arts = build_plist_artifacts({"d": datetime(2026, 5, 1, 12, 30, tzinfo=UTC)})
    date_arts = [a for a in arts if a.artifact_type == "plist_date"]
    assert len(date_arts) == 1
    ts = date_arts[0].timestamp
    assert ts is not None and ts.tzinfo is not None
    assert ts.isoformat() == "2026-05-01T12:30:00+00:00"


def test_plist_negative_scalar_root():
    """Skalární kořen → jen triage artifact (root_type str, žádné klíče)."""
    arts = build_plist_artifacts("skalar")
    assert len(arts) == 1
    art = arts[0]
    assert art.artifact_type == "property_list"
    assert art.timestamp is None
    assert art.details["root_type"] == "str"
    assert art.details["top_level_keys"] == []


def test_plist_negative_empty_dict():
    """Prázdný dict → triage bez date artefaktů a bez klíčů."""
    arts = build_plist_artifacts({})
    assert len(arts) == 1
    triage = arts[0]
    assert triage.artifact_type == "property_list"
    assert triage.details["top_level_keys"] == []
    assert triage.details["date_fields"] == 0


def test_plist_size_date_artifact_cap_50():
    """MAX_DATE_ARTIFACTS=50 — 60 polí → 50 artefaktů, date_fields=51 (break po inkrementaci)."""
    many = {"d": [datetime(2026, 1, 1 + i % 28, tzinfo=UTC) for i in range(60)]}
    arts = build_plist_artifacts(many)
    date_arts = [a for a in arts if a.artifact_type == "plist_date"]
    triage = next(a for a in arts if a.artifact_type == "property_list")

    assert len(date_arts) == 50
    assert triage.details["date_fields"] == 51


def test_plist_size_top_keys_truncation_30():
    """MAX_TOP_KEYS=30 — 35 klíčů → 30 + truncated=True; list kořen → [i] indexy."""
    many_keys = {f"key{i:02d}": i for i in range(35)}
    triage = next(a for a in build_plist_artifacts(many_keys) if a.artifact_type == "property_list")
    assert len(triage.details["top_level_keys"]) == 30
    assert triage.details["truncated"] is True

    list_triage = next(a for a in build_plist_artifacts([1, 2, 3]) if a.artifact_type == "property_list")
    assert list_triage.details["top_level_keys"] == ["[0]", "[1]", "[2]"]


# ── registry_hive ───────────────────────────────────────────────────────────


def test_registry_positive_patterns_runonce_priority():
    """Priorita vzorců: RunOnce před Run (substring shoda), MountedDevices → USB."""
    subs = [
        _subkey(r"Software\Microsoft\Windows\CurrentVersion\RunOnce", None, [("setup.exe", r"C:\temp\setup.exe")]),
        _subkey(r"Software\Microsoft\Windows\CurrentVersion\Run", None, [("updator", "C:\\upd\\u.exe")]),
        _subkey(r"HKLM\SYSTEM\MountedDevices", None, [("\\\\?\\USB#VID_1234#", "\\\\Device\\HarddiskVolume2")]),
    ]
    arts = build_registry_artifacts(subs)

    run_once = [a for a in arts if "RunOnce" in a.details.get("key_path", "")]
    plain_run = [a for a in arts if a.details.get("key_path", "").endswith(r"\Run")]
    usb = [a for a in arts if a.artifact_type == "registry_usb_device"]

    assert len(run_once) == 1
    ro_title = run_once[0].title
    assert ro_title is not None and "Jednorázový start (RunOnce)" in ro_title
    assert run_once[0].details["values"]["setup.exe"] == r"C:\temp\setup.exe"

    assert len(plain_run) == 1
    pr_title = plain_run[0].title
    assert pr_title is not None and "Spouštěno při startu (Run)" in pr_title

    assert len(usb) == 1
    usb_title = usb[0].title
    assert usb_title is not None and "Připojené USB/removable média" in usb_title


def test_registry_slash_path_normalization():
    """Forward-slash cesty se normalizují na backslash pro shodu vzorců."""
    subs = [_subkey("Software/Microsoft/Windows/CurrentVersion/Run", None, [("x", "y")])]
    arts = build_registry_artifacts(subs)
    assert len(arts) == 1
    title = arts[0].title
    assert title is not None and "Spouštěno při startu (Run)" in title


def test_registry_tz_timestamp_passthrough_aware_and_none():
    """Passthrough subkey timestampu: aware UTC se zachová, None zůstává None."""
    aware = datetime(2026, 4, 1, 8, 30, tzinfo=UTC)
    arts = build_registry_artifacts([
        _subkey(r"Software\Microsoft\Windows\CurrentVersion\Run", aware, [("a", "b")]),
        _subkey(r"Software\Microsoft\Windows\CurrentVersion\RunOnce", None, [("c", "d")]),
    ])
    by_path = {a.details["key_path"]: a for a in arts}
    assert len(by_path) == 2

    aware_art = [a for a in arts if a.timestamp is not None]
    assert len(aware_art) == 1
    assert aware_art[0].timestamp == aware

    none_arts = [a for a in arts if a.timestamp is None]
    assert len(none_arts) == 1


def test_registry_encoding_bytes_invalid_utf8_replacement():
    """Bytes hodnoty → utf-8 errors=replace: invalidní bajty → U+FFFD, zbytek verbatim."""
    arts = build_registry_artifacts([
        _subkey(r"Software\Microsoft\Windows\CurrentVersion\Run", None, [("bin", b"\xff\xfebinarni-utf8")]),
    ])
    assert len(arts) == 1
    val = arts[0].details["values"]["bin"]
    assert val.startswith("\ufffd\ufffd")
    assert val.endswith("binarni-utf8")


def test_registry_locale_czech_values_verbatim():
    """Česká diakritika v hodnotách verbatim (cesty klíčů jsou anglické vzorce)."""
    subs = [
        _subkey(r"Software\Microsoft\Windows\CurrentVersion\Run", None, [("czech", "Příliš žluťoučký text")]),
        _subkey(r"HKCU\Control Panel\User Name", None, [("default", "Šéf")]),
    ]
    arts = build_registry_artifacts(subs)
    czech = [a for a in arts if a.details.get("values", {}).get("czech")]
    assert len(czech) == 1
    assert czech[0].details["values"]["czech"] == "Příliš žluťoučký text"

    user_info = [a for a in arts if a.artifact_type == "registry_user_info"]
    assert len(user_info) == 1


def test_registry_size_value_truncation_200():
    """MAX_VALUE_LEN=200 — hodnota 250 znaků → přesně 200."""
    arts = build_registry_artifacts([
        _subkey(r"Software\Microsoft\Windows\CurrentVersion\Run", None, [("dlouha", "x" * 250)]),
    ])
    assert len(arts) == 1
    val = arts[0].details["values"]["dlouha"]
    assert len(val) == 200


def test_registry_negative_empty_container_and_unknown_path():
    """Prázdný kontejner (bez values) skipnut; neznámá cesta → žádný artifact."""
    subs = [
        _subkey(r"Software\EmptyContainer", None, []),
        _subkey(r"Software\Random\Unrelated\Path", None, [("x", "y")]),
    ]
    assert build_registry_artifacts(subs) == []


# ── evtx ────────────────────────────────────────────────────────────────────


def test_evtx_positive_standard_entries_aware_utc():
    """Standard EVTX: FILETIME → aware UTC, event_id postupné, conf 0.85 s message."""
    parsed = parse_evtx_file(make_evtx_standard(2))
    assert len(parsed.entries) == 2

    e1, e2 = parsed.entries
    ts = e1.timestamp
    assert ts is not None and ts.tzinfo is not None
    assert ts.isoformat() == "2026-10-26T15:20:19+00:00"
    assert (e1.event_id, e2.event_id) == (4624, 4625)

    arts = build_evtx_artifacts(parsed)
    assert len(arts) == 2
    title = arts[0].title
    assert title is not None and "Microsoft-Windows-Kernel-General ID 4624" in title
    assert all(a.confidence == pytest.approx(0.85) for a in arts)


def test_evtx_positive_elf_variant():
    """ElfFile varianta: entries + aware UTC timestampy."""
    parsed = parse_evtx_file(make_evtx_elf(2))
    assert len(parsed.entries) == 2
    assert (parsed.entries[0].event_id, parsed.entries[1].event_id) == (7040, 7041)
    for e in parsed.entries:
        ts = e.timestamp
        assert ts is not None and ts.tzinfo is not None


def test_evtx_negative_zero_events():
    """Validní magic + nula záznamů → 0 entries → [] artifactů."""
    parsed = parse_evtx_file(make_evtx_standard(0))
    assert parsed.entries == []
    assert build_evtx_artifacts(parsed) == []


def test_evtx_corrupted_too_short():
    """<128 B → ValueError s přesnou zprávou (min 128)."""
    data = make_evtx_standard(1)[:100]
    with pytest.raises(ValueError, match="EVTX soubor příliš krátký: 100 B \\(min 128\\)"):
        parse_evtx_file(data)


def test_evtx_corrupted_bad_magic_and_extract_graceful(tmp_path):
    """Cizí magic → ValueError; extract na soubor graceful []."""
    bad = b"XXXX" + b"\x00" * 200
    with pytest.raises(ValueError, match="Neznámá EVTX magic"):
        parse_evtx_file(bad)

    p = tmp_path / "c.evtx"
    p.write_bytes(bad)
    assert extract_evtx_artifacts(p) == []


def test_evtx_locale_mixed_message_verbatim_ascii_run():
    """Diakritický prefix rozbije ASCII runy; nejdelší run ≥30 B se zachová verbatim."""
    ascii_run = "Uzivatel spustil sluzbu ucetne a probihla dlouha kontrola systemu bez chyb"
    parsed = parse_evtx_file(_evtx_custom("Příliš žluťoučký kůň: " + ascii_run))
    assert len(parsed.entries) == 1

    entry = parsed.entries[0]
    # run začíná na ":" (za diakritickým ň) a sahá do konce payloadu
    assert entry.message == ": " + ascii_run


def test_evtx_locale_odd_byte_and_event_id_only_confidence():
    """Lichý byte v UTF-16LE → errors=replace bez výjimky; jen event_id → conf 0.6."""
    ok = parse_evtx_file(_evtx_custom("dlouha zprava nad tricet znaku pro test behu", odd_payload=True))
    assert len(ok.entries) == 1

    minimal = parse_evtx_file(_evtx_custom("kratka zprava"))
    entry = minimal.entries[0]
    assert entry.event_id == 4625
    assert entry.message == "" and entry.provider == ""

    arts = build_evtx_artifacts(minimal)
    assert len(arts) == 1
    title = arts[0].title
    assert title is not None and "ID 4625" in title
    assert arts[0].confidence == pytest.approx(0.6)


# ── lnk ─────────────────────────────────────────────────────────────────────


def test_lnk_positive_roundtrip_aware_utc_title():
    """MS-LNK roundtrip: creation FILETIME → aware UTC; title LNK → target."""
    created = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    data = make_lnk(target=r"C:\Program Files\App\app.exe", name="Cil", created=created)
    parsed = parse_lnk(data)

    ct = parsed["creation_time"]
    assert ct is not None and ct.tzinfo is not None
    assert ct == created
    assert parsed["target_path"] == r"C:\Program Files\App\app.exe"

    arts = build_lnk_artifacts(parsed, rel_path="Desktop/app.lnk")
    assert len(arts) == 1
    art = arts[0]
    title = art.title
    assert title is not None and "LNK → C:\\Program Files\\App\\app.exe" in title
    ts = art.timestamp
    assert ts is not None and ts.isoformat() == "2026-05-01T12:00:00+00:00"
    # access/write FILETIMEs → ISO řetězce v detailech
    assert art.details["access_time"] == "2026-05-01T12:00:00+00:00"
    assert art.details["rel_path"] == "Desktop/app.lnk"


def test_lnk_locale_name_diacritics_utf16_verbatim():
    """Name blok UTF-16LE s diakritikou verbatim (parsed + details.name)."""
    name = "Příliš žluťoučký cíl"
    data = make_lnk(target=r"C:\App\run.exe", name=name)
    parsed = parse_lnk(data)
    assert parsed["name"] == name

    art = build_lnk_artifacts(parsed)[0]
    assert art.details["name"] == name


def test_lnk_corrupted_too_short():
    """<76 B → ValueError s přesnou zprávou (min 76)."""
    data = make_lnk(target=r"C:\App\run.exe")[:40]
    with pytest.raises(ValueError, match="LNK too short: 40 B \\(min 76\\)"):
        parse_lnk(data)


def test_lnk_corrupted_bad_clsids_and_extract_graceful(tmp_path):
    """Cizí CLSID @4..20 → ValueError bad LNK CLSID; extract graceful []."""
    data = bytearray(make_lnk(target=r"C:\App\run.exe"))
    data[4:20] = b"\xde\xad\xbe\xef" * 4
    with pytest.raises(ValueError, match="bad LNK CLSID"):
        parse_lnk(bytes(data))

    p = tmp_path / "c.lnk"
    p.write_bytes(make_lnk(target=r"C:\App\run.exe")[:40])
    assert extract_lnk_artifacts(p) == []


def test_lnk_size_max_scan_boundary_4096():
    """max_scan=4096 B od @76 — path za hranicí nenalezen, pod hranicí verbatim."""
    beyond = parse_lnk(_lnk_padded(4900, r"C:\Hidden\App.exe"))
    assert beyond["target_path"] is None

    within = parse_lnk(_lnk_padded(100, r"C:\Visible\App.exe"))
    assert within["target_path"] == r"C:\Visible\App.exe"
