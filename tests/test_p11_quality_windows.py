"""P1-1 vlna 9 — Windows forensics rodina: quality sada (5 parserů).

win_drivers (JSON z paměťového dumpu) / win_schedtask (Scheduled Task XML,
reálně UTF-16 LE s BOM) / win_jumplist + win_prefetch (binární JUMPLIST
kontejner + MAM .pf s LZXPRESS) / win_usn (NTFS USN Journal $UsnJrnl v2).

Testované dokumentované kontrakty:
- Čas: usn/prefetch/jumplist FILETIME → aware UTC bez ztráty; schedtask
  registration_date = ISO string pass-through i s offsetem (+02:00);
  win_drivers = snapshot paměti bez času (artifact.timestamp is None).
- Kódování/locale: česká diakritika roundtrip v JSON polích, XML textu,
  UTF-16LE MAM program name, LNK jménu a USN filename.
- Poškození: drivers BOM/binární smetí/oříznuté JSON → ValueError „Neplatné
  JSON", prázdné [] → TypeError "Nenalezeny driver záznamy"; schedtask
  nevalidní XML → ValueError, kořen ≠ Task bez task dětí → []; prefetch
  špatná magic / payload <84 B → None (graceful); jumplist smetí/krátký
  kontejner → []; usn <1024 B → ValueError „příliš krátký", poškozené
  záznamy = graceful break (entries []).
- Limity: drivers MAX_DRIVERS_PER_FILE=2000, schedtask MAX_TASKS_PER_FILE=50,
  jumplist MAX_ENTRIES_PER_LIST=50; usn 200 záznamů + neúplný závěrečný
  záznam (<60 B) = čistý konec.
"""

from __future__ import annotations

import json
import struct
from datetime import datetime, timedelta, timezone

from stopa.artifacts.win_drivers import (
    MAX_DRIVERS_PER_FILE,
    build_driver_artifacts,
    parse_win_drivers,
)
from stopa.artifacts.win_jumplist import MAX_ENTRIES_PER_LIST, parse_jump_list
from stopa.artifacts.win_prefetch import MAM_MAGIC, parse_prefetch
from stopa.artifacts.win_schedtask import (
    MAX_TASKS_PER_FILE,
    build_scheduled_task_artifacts,  # noqa: F401 — součást veřejného kontraktu sady
    parse_scheduled_task_xml,
)
from stopa.artifacts.win_usn import parse_usn_journal

# binární fixture buildery z bázisových sad (cross-test import = ustálený pattern)
from tests.test_e6 import lzxp_identity_compress, make_jump_list, make_lnk, make_pf
from tests.test_e7 import make_usn_journal

_FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)

_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def _ft(dt: datetime) -> int:
    """FILETIME ticky (100 ns od 1601-01-01 UTC), exact integer arithmetic."""
    delta = dt - _FILETIME_EPOCH
    return (
        delta.days * 86_400 * 10_000_000
        + delta.seconds * 10_000_000
        + delta.microseconds * 10
    )


def _task_xml(
    name: str | None = None,
    author="JAN\\Správce",
    date="2026-11-01T08:30:00",
) -> bytes:
    """Scheduled Task XML v reálném formátu — UTF-16 LE s BOM."""
    name_el = f"<Name>{name}</Name>\n" if name else ""
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        f'<Task version="1.2" xmlns="{_NS}">\n'
        "  <RegistrationInfo>\n"
        f"    <Date>{date}</Date>\n"
        f"    <Author>{author}</Author>\n"
        "  </RegistrationInfo>\n"
        f"{name_el}"
        "</Task>"
    ).encode("utf-16")


def _tasks_envelope(n: int) -> bytes:
    """Obálka s více tasky (zřídka, ale parser ji explicitně podporuje)."""
    inner = "".join(
        f'<Task version="1.2" xmlns="{_NS}">'
        "<RegistrationInfo><Author>u{}</Author></RegistrationInfo>"
        "</Task>".format(i)
        for i in range(n)
    )
    return f'<Tasks xmlns="{_NS}">{inner}</Tasks>'.encode()


def _drivers_payload() -> list[dict]:
    return [
        {
            "driverName": "ntoskrnl.exe",
            "baseAddress": "0xfffff8045b2c0000",
            "size": 16384,
            "signed": True,
            "description": "Windows NT Kernel",
        },
    ]


# ── win_drivers (JSON) ───────────────────────────────────────

# quality: encoding locale
def test_drivers_czech_diacritics_roundtrip():
    """Česká diakritika v JSON polích zůstává čitelná; int adresa → hex."""
    payload = [
        {
            "driverName": "účetní-driver.sys",
            "baseAddress": 0xFFFFF8045B2C0000,
            "size": 4096,
            "signed": False,
            "description": "Účetní driver pro tiskárnu",
            "companyName": "Společnost s.r.o.",
        }
    ]
    records = parse_win_drivers(json.dumps(payload).encode("utf-8"))
    assert len(records) == 1
    r = records[0]
    assert r.name == "účetní-driver.sys"
    assert r.description == "Účetní driver pro tiskárnu"
    assert r.extra["companyname"] == "Společnost s.r.o."
    assert r.base_address is not None
    assert "fffff8045b2c0000" in r.base_address.lower()


# quality: corrupted
def test_drivers_bom_junk_truncated_raise_invalid_json():
    """BOM / binární smetí / oříznuté JSON → ValueError „Neplatné JSON"."""
    good = json.dumps(_drivers_payload()).encode("utf-8")
    for bad in (b"\xef\xbb\xbf" + good, b"\x00\xff\xfe\xfd" * 16, good[:-5]):
        try:
            parse_win_drivers(bad)
            raise AssertionError(f"mělo zvednout ValueError pro {bad[:8]!r}")
        except ValueError as e:
            assert "Neplatné JSON" in str(e)


# quality: negative boundary
def test_drivers_empty_and_nameless_input():
    """Prázdné [] → TypeError; položky bez jména se přeskočí (→ [])."""
    try:
        parse_win_drivers(b"[]")
        raise AssertionError("mělo zvednout TypeError")
    except TypeError as e:
        assert "Nenalezeny driver záznamy" in str(e)
    assert parse_win_drivers(json.dumps([{"size": 42}]).encode()) == []


# quality: size
def test_drivers_max_2000_truncation():
    """MAX_DRIVERS_PER_FILE=2000 — přesně limit se parsuje, +5 nad = truncation."""
    payload = [
        {"driverName": f"drv{i}.sys", "size": i} for i in range(MAX_DRIVERS_PER_FILE)
    ]
    assert len(parse_win_drivers(json.dumps(payload).encode())) == MAX_DRIVERS_PER_FILE
    over = payload[: MAX_DRIVERS_PER_FILE + 5]
    assert len(parse_win_drivers(json.dumps(over).encode())) == MAX_DRIVERS_PER_FILE


# quality: tz
def test_drivers_memory_snapshot_without_time():
    """Snapshot paměti bez času → artifact.timestamp is None (dokumentovaný kontrakt)."""
    records = parse_win_drivers(json.dumps(_drivers_payload()).encode())
    arts = build_driver_artifacts(records)
    assert arts and all(a.timestamp is None for a in arts)


# ── win_schedtask (XML) ──────────────────────────────────────

# quality: encoding locale
def test_schedtask_utf16_bom_czech_roundtrip():
    """Reálný task XML = UTF-16 LE s BOM; česká diakritika v textu zůstává čitelná."""
    tasks = parse_scheduled_task_xml(_task_xml(name="Úklidové úlohy"))
    assert len(tasks) == 1
    t = tasks[0]
    assert t.name == "Úklidové úlohy"
    assert "Správce" in t.author


# quality: corrupted negative
def test_schedtask_invalid_xml_raises_and_non_task_graceful():
    """Nevalidní XML → ValueError; kořen ≠ Task bez task dětí → []."""
    full = _task_xml()
    for bad in (b"\x01\x02" + "binární smetí".encode(), full[: len(full) // 2]):
        try:
            parse_scheduled_task_xml(bad)
            raise AssertionError("mělo zvednout ValueError")
        except ValueError as e:
            assert "Neplatné Scheduled Task XML" in str(e)
    other = b'<?xml version="1.0"?><WLANProfile xmlns="x"><name>w</name></WLANProfile>'
    assert parse_scheduled_task_xml(other) == []


# quality: size boundary
def test_schedtask_max_50_tasks_and_empty_task_skipped():
    """Obálka s 60 tasky → MAX_TASKS_PER_FILE=50; task bez obsahu = skip."""
    assert len(parse_scheduled_task_xml(_tasks_envelope(60))) == MAX_TASKS_PER_FILE
    empty = (
        f'<?xml version="1.0"?><Task version="1.2" xmlns="{_NS}">'
        "<RegistrationInfo></RegistrationInfo></Task>"
    ).encode()
    assert parse_scheduled_task_xml(empty) == []


# quality: tz
def test_schedtask_date_offset_string_passthrough():
    """registration_date = ISO string pass-through i s offsetem (bez přepisu)."""
    t = parse_scheduled_task_xml(_task_xml(date="2026-11-01T08:30:00+02:00"))[0]
    assert t.registration_date == "2026-11-01T08:30:00+02:00"
    parsed = datetime.fromisoformat(t.registration_date)
    assert parsed.utcoffset() == timedelta(hours=2)


# ── win_prefetch + win_jumplist (binární) ───────────────────

# quality: encoding locale tz
def test_prefetch_czech_program_name_and_utc_run_times():
    """MAM program name UTF-16LE s diakritikou roundtrip; FILETIME → ISO UTC."""
    last_run = datetime(2026, 3, 15, 8, 30, 45, tzinfo=timezone(timedelta(hours=2)))
    parsed = parse_prefetch(make_pf(program="ÚČETNÍ.EXE", last_run=last_run))
    assert parsed is not None
    assert parsed["program"] == "ÚČETNÍ.EXE"
    # absolutní čas se normalizuje do UTC bez ztráty (08:30+02 → 06:30Z)
    assert parsed["last_run_times"][0] == "2026-03-15T06:30:45+00:00"


# quality: corrupted negative
def test_prefetch_corrupted_returns_none():
    """Špatná magic / příliš krátké → None (graceful, ne výjimka)."""
    assert parse_prefetch(b"JFET\x01\x02\x03\x04") is None
    assert parse_prefetch(b"MAM") is None  # <8 B


# quality: boundary size
def test_prefetch_min_payload_size_none():
    """Dekompresuje se, ale payload <84 B → None (dokumentovaný limit)."""
    plain = bytearray(20)
    struct.pack_into("<I", plain, 0, 31)
    data = MAM_MAGIC + struct.pack("<I", len(plain)) + lzxp_identity_compress(bytes(plain))
    assert parse_prefetch(data) is None


# quality: encoding locale
def test_jumplist_czech_lnk_roundtrip():
    """Embedded LNK s českým jménem a cestou zůstává čitelný."""
    jl = make_jump_list([make_lnk(target="C:\\Doklady\\faktura.pdf", name="Faktura únor")])
    entries = parse_jump_list(jl)
    assert len(entries) == 1
    e = entries[0]
    assert e["name"] == "Faktura únor"
    assert e["target_path"] == "C:\\Doklady\\faktura.pdf"


# quality: tz
def test_jumplist_creation_time_aware_utc_passthrough():
    """LNK creation FILETIME → aware UTC datetime bez ztráty."""
    created = datetime(2026, 2, 3, 14, 5, 0, tzinfo=timezone.utc)
    entries = parse_jump_list(make_jump_list([make_lnk(target="C:\\x.exe", created=created)]))
    assert len(entries) == 1
    assert entries[0]["creation_time"] == created


# quality: corrupted negative
def test_jumplist_corrupted_graceful_empty():
    """Smetí / krátký kontejner → [] (graceful, ne výjimka)."""
    assert parse_jump_list(b"\x01\x02\x03") == []  # <20 B
    assert parse_jump_list(b"random text bez LNK entry\n" * 5) == []


# quality: size
def test_jumplist_max_50_entries_truncation():
    """MAX_ENTRIES_PER_LIST=50 — 60 embedded LNK → přesně 50."""
    jl = make_jump_list([make_lnk(target=f"C:\\apps\\a{i}.exe") for i in range(60)])
    assert len(parse_jump_list(jl)) == MAX_ENTRIES_PER_LIST


# ── win_usn (NTFS USN Journal) ───────────────────────────────

# quality: encoding locale
def test_usn_czech_filename_roundtrip():
    """UTF-16LE filename s diakritikou zůstává čitelný."""
    data = make_usn_journal(
        [
            (513, _ft(datetime(2026, 4, 2, 9, 15, 30, tzinfo=timezone.utc)), 0x1, "přepočet.log"),
            (514, _ft(datetime(2026, 4, 2, 9, 16, 0, tzinfo=timezone.utc)), 0x4, "C:\\Data\\smaženi.dat"),
        ]
    )
    parsed = parse_usn_journal(data)
    assert [e.filename for e in parsed.entries] == ["přepočet.log", "C:\\Data\\smaženi.dat"]


# quality: tz
def test_usn_filetime_aware_utc():
    """FILETIME → aware UTC datetime (record timestamp i header creation_time)."""
    ts = datetime(2026, 4, 2, 9, 15, 30, tzinfo=timezone.utc)
    parsed = parse_usn_journal(make_usn_journal([(513, _ft(ts), 0x1, "a.log")]))
    assert parsed.entries[0].timestamp == ts
    assert parsed.creation_time is not None and parsed.creation_time.tzinfo is not None


# quality: corrupted negative boundary
def test_usn_too_short_raises_and_bad_record_graceful():
    """<1024 B → ValueError; poškozený záznam (major=99) = graceful break."""
    try:
        parse_usn_journal(b"short journal")
        raise AssertionError("mělo zvednout ValueError")
    except ValueError as e:
        assert "příliš krátký" in str(e)
    hdr = make_usn_journal([])  # validní prázdná hlavička v2 (1024 B)
    bad_rec = struct.pack("<HHI", 99, 0, 64) + b"\x00" * 58  # celkem 64 B
    assert parse_usn_journal(hdr + bad_rec).entries == []


# quality: size boundary
def test_usn_stress_200_records_and_incomplete_trailing():
    """200 záznamů = všechny se parsují; neúplný závěr (<60 B) = čistý konec."""
    base = datetime(2026, 4, 2, 9, tzinfo=timezone.utc)
    recs = [
        (513 + i, _ft(base + timedelta(seconds=i)), 0x1, f"file_{i:03d}.dat")
        for i in range(200)
    ]
    parsed = parse_usn_journal(make_usn_journal(recs))
    assert len(parsed.entries) == 200
    truncated_tail = make_usn_journal([(513, _ft(base), 0x1, "a.log")]) + b"\x02\x00" * 8
    assert len(parse_usn_journal(truncated_tail).entries) == 1
