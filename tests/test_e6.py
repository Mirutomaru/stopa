"""E6 — Windows parsery vlna 1: MS-LNK, MS-PREFETCH (MAM), Jump Lists.

Binární fixture se generují přímo v testech (žádné externí soubory):
- LNK: 76 B hlavička + ANSI/UTF-16LE bloky podle flags [MS-LNK]
- PF: MAM header + LZXPRESS Huffman stream (identity komprese — každý byte
  jako 8-bit symbol; dekodér čte u16 LE páry, decode MSB-first → v páru jde
  druhý byte první)
- Jump List: kontejner version=2 + embedded LNK entry

E2E testy jdou přes `process_source` (forensic profil) a čtou artifacty z DB.
"""

from __future__ import annotations

import struct
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.artifacts.win_jumplist import (
    build_jump_list_artifacts,
    extract_jump_list_artifacts,
    is_jump_list_file,
    parse_jump_list,
)
from stopa.artifacts.win_lnk import build_lnk_artifacts, parse_lnk
from stopa.artifacts.win_prefetch import (
    MAM_MAGIC,
    build_prefetch_artifacts,
    extract_prefetch_artifacts,
    is_mam_prefetch,
    parse_prefetch,
    xpress_huffman_decompress,
)
from stopa.data.db import CaseDB
from stopa.domain.signatures import detect_signature
from stopa.models import Case, EvidenceSource
from stopa.pipeline import process_source

# ──────────────────────────────────────────────────────────────────────
# Fixture generátory
# ──────────────────────────────────────────────────────────────────────

LNK_CLSID = bytes.fromhex("0114020000000000c000000000000046")  # IShellLink LE


def _ft(dt: datetime) -> int:
    """aware datetime → FILETIME (100 ns od 1601)."""
    epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
    return int((dt - epoch).total_seconds() * 10_000_000)


def make_lnk(
    target: str | None = None,
    relative: str | None = None,
    name: str | None = None,
    working_dir: str | None = None,
    command_line: str | None = None,
    created: datetime | None = None,
) -> bytes:
    """Vygeneruje validní MS-LNK soubor (hlavička + bloky v kanonickém pořadí)."""
    flags = 0
    if target is not None:
        flags |= 0x0100  # HAS_LOCAL_BASE_PATH
    if relative is not None:
        flags |= 0x0002  # HAS_RELATIVE_PATH
    if name is not None:
        flags |= 0x0004  # HAS_NAME (UTF-16LE)
    if working_dir is not None:
        flags |= 0x0008  # HAS_WORKING_DIR
    if command_line is not None:
        flags |= 0x0010  # HAS_COMMAND_LINE

    created = created or datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    header = struct.pack("<I", 76)  # cbLinkHeaderSize @0
    header += LNK_CLSID  # @4..20
    header += struct.pack("<II", flags, 0x20)  # @20 flags, @24 file attributes
    header += struct.pack("<QQQ", _ft(created), _ft(created), _ft(created))  # @28..52
    header += struct.pack("<q", 123456)  # @52 qwFileSize
    header += b"\x00" * (76 - len(header))

    body = bytearray()
    if target is not None:
        body += target.encode("cp1252") + b"\x00"
    if relative is not None:
        body += relative.encode("cp1252") + b"\x00"
    if name is not None:
        body += name.encode("utf-16-le") + b"\x00\x00"
    if working_dir is not None:
        body += working_dir.encode("cp1252") + b"\x00"
    if command_line is not None:
        body += command_line.encode("cp1252") + b"\x00"
    return header + bytes(body)


def lzxp_identity_compress(payload: bytes) -> bytes:
    """LZXPRESS Huffman stream, kde každý byte = 8-bit symbol (identity tabulka).

    Tabulka `[0x88]*128 + [0x00]*128`: symboly 0-255 mají délku 8 (Kraft=1),
    match symboly 256-511 délku 0. Dekodér čte 32-bit okno přes `read16()`
    (u16 LE) a decode je MSB-first — uvnitř každého páru se dekóduje druhý
    byte první → payload se v párech zamění. Ověřeno roundtripem pro délky
    2..32 B i na reálných MAM souborech (regrese).
    """
    table = bytes([0x88] * 128 + [0x00] * 128)
    body = bytearray()
    for i in range(0, len(payload), 2):
        a = payload[i]
        b = payload[i + 1] if i + 1 < len(payload) else 0
        # u16 LE (a<<8)|b → byty na disku [b, a] = decode pořadí
        body += struct.pack("<H", (a << 8) | b)
    return table + bytes(body)


def make_pf(
    program: str = "TESTPROG.EXE",
    run_count: int = 7,
    volume_serial: int = 0x12345678,
    device_path: str = "\\\\VOLUME{abcd-efgh}",
    last_run: datetime | None = None,
) -> bytes:
    """Vygeneruje validní MAM .pf soubor (SCCA v31 payload, LZXPRESS identity)."""
    # Volume entry: dev_str_off@0, n_chars@4, created FILETIME@8, serial@16
    dev = device_path.encode("utf-16-le") + b"\x00\x00"
    vol_entry = (
        struct.pack("<II", 24, len(device_path))
        + struct.pack("<Q", _ft(last_run or datetime(2026, 5, 1, tzinfo=timezone.utc)))
        + struct.pack("<I", volume_serial)
        + b"\x00" * 4
        + dev
    )

    # File information blok (≥120 B): run_count@fi+116, last_run[8]@fi+44
    fi = bytearray(124)
    struct.pack_into("<II", fi, 0, 0, 3)  # metrics_off, n_metrics
    vol_off = 84 + len(fi)  # volume entry hned za file info v plain payloadu
    struct.pack_into("<II", fi, 24, vol_off, 1)  # vol_off, n_vols
    if last_run is not None:
        struct.pack_into("<Q", fi, 44, _ft(last_run))
    struct.pack_into("<I", fi, 116, run_count)

    name_slot = program.encode("utf-16-le") + b"\x00" * (60 - len(program.encode("utf-16-le")))
    plain = bytearray()
    plain += struct.pack("<I", 31)  # version @0
    plain += b"SCCA"  # @4
    plain += b"\x00" * 8  # @8..16
    plain += name_slot[:60]  # filename UTF-16LE fixed slot @16..76
    plain += b"\x00" * 8  # @76..84
    plain += fi  # file information @84
    plain += vol_entry

    return MAM_MAGIC + struct.pack("<I", len(plain)) + lzxp_identity_compress(bytes(plain))


def make_jump_list(entries: list[bytes]) -> bytes:
    """Jump List kontejner (version=2) s embedded LNK entry."""
    header = struct.pack("<II", 2, 0) + b"\x00" * 12  # 20 B container header
    return header + b"".join(entries)


# ──────────────────────────────────────────────────────────────────────
# LNK parser (7 testů)
# ──────────────────────────────────────────────────────────────────────


def test_lnk_parse_localbase_target():
    """LOCALBASE flag → ANSI target path se parsoje."""
    data = make_lnk(target="C:\\Windows\\system32\\dfrgui.exe")
    parsed = parse_lnk(data)
    assert parsed["target_path"] == "C:\\Windows\\system32\\dfrgui.exe"
    assert parsed["relative_path"] is None
    assert parsed["flags"] & 0x0100


def test_lnk_parse_name_utf16_diacritics():
    """Name je UTF-16LE s diakritikou — i ASCII poslední znak se dekóduje celý.

    Regrese: `_read_utf16_null` původně hledal `\x00\x00` na libovolném offsetu,
    takže ASCII poslední znak (high byte 0x00) + terminátor vytvořily falešný
    terminator o 1 byte dřív a string ztratil poslední znak.
    """
    data = make_lnk(target="C:\\app.exe", name="Počítačová stroj")
    parsed = parse_lnk(data)
    assert parsed["name"] == "Počítačová stroj"


def test_lnk_parse_relative_path_only():
    """Jen RELPATH flag → relative_path, target_path None."""
    data = make_lnk(relative="..\\Programs\\app.exe")
    parsed = parse_lnk(data)
    assert parsed["relative_path"] == "..\\Programs\\app.exe"
    assert parsed["target_path"] is None


def test_lnk_parse_all_blocks():
    """Všechny bloky najednou — sekvenční čtení v kanonickém pořadí."""
    data = make_lnk(
        target="C:\\bin\\tool.exe",
        name="Nástroj",
        working_dir="C:\\bin",
        command_line='--flag "arg"',
    )
    parsed = parse_lnk(data)
    assert parsed["target_path"] == "C:\\bin\\tool.exe"
    assert parsed["name"] == "Nástroj"
    assert parsed["working_dir"] == "C:\\bin"
    assert parsed["command_line"] == '--flag "arg"'


def test_lnk_bad_clsid_raises():
    """Špatný CLSID @4 → ValueError (validace signatury)."""
    data = bytearray(make_lnk(target="C:\\x.exe"))
    data[4] = 0xFF
    with pytest.raises(ValueError, match="CLSID"):
        parse_lnk(bytes(data))


def test_lnk_too_short_raises():
    """Soubor kratší než hlavička (76 B) → ValueError."""
    with pytest.raises(ValueError, match="too short"):
        parse_lnk(b"\x4c\x00" * 10)


def test_lnk_artifacts_title_and_details():
    """build_lnk_artifacts — title obsahuje cíl, details kompletní."""
    created = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    parsed = parse_lnk(make_lnk(target="C:\\Windows\\notepad.exe", name="Notepad", created=created))
    arts = build_lnk_artifacts(parsed, rel_path="evidence/Recent/notepad.lnk")
    assert len(arts) == 1
    art = arts[0]
    assert art.artifact_type == "shell_link"
    assert "C:\\Windows\\notepad.exe" in art.title
    assert art.details["target_path"] == "C:\\Windows\\notepad.exe"
    assert art.details["name"] == "Notepad"
    assert art.details["rel_path"] == "evidence/Recent/notepad.lnk"
    assert art.timestamp is not None and art.timestamp.year == 2026


def test_lnk_signature_detection():
    """detect_signature na generovaném LNK → typ 'lnk' (rodina windows)."""
    data = make_lnk(target="C:\\x.exe")
    sig = detect_signature(data)
    assert sig is not None and sig[0] == "lnk" and sig[1] == "windows"


# ──────────────────────────────────────────────────────────────────────
# Prefetch parser (8 testů)
# ──────────────────────────────────────────────────────────────────────


def test_pf_is_mam_magic():
    """is_mam_prefetch — MAM magic ano, ostatní ne."""
    assert is_mam_prefetch(make_pf())
    assert not is_mam_prefetch(b"JFET\x01\x02\x03")
    assert not is_mam_prefetch(b"MAM\x05xxxx")


def test_pf_lzxp_identity_roundtrip():
    """LZXPRESS dekomprese identity streamu — regrese EOF fixu.

    Dekodér čte 32-bit okno (init = 4 byty); u krátkých streamů se celý payload
    vejde do okna a stará podmínka `bs.pos < len` ukončila blok před dekodováním.
    """
    for n in (4, 8, 32, 64, 128, 256):
        payload = bytes(range(n))
        stream = lzxp_identity_compress(payload)
        out = xpress_huffman_decompress(stream, n)
        assert out == payload, f"roundtrip selhal pro n={n}"


def test_pf_parse_full_fixture():
    """Kompletní MAM fixture — program, verze, run_count, časy, volume."""
    last_run = datetime(2026, 10, 26, 15, 20, 19, tzinfo=timezone.utc)
    data = make_pf(program="APPACTIONS.EXE", run_count=42, volume_serial=0x6E6F5F6B, last_run=last_run)
    parsed = parse_prefetch(data)
    assert parsed is not None
    assert parsed["program"] == "APPACTIONS.EXE"
    assert parsed["version"] == 31
    assert parsed["run_count"] == 42
    assert len(parsed["last_run_times"]) == 1
    assert parsed["last_run_times"][0].startswith("2026-10-26T15:20:19")
    assert parsed["volume_serial"] == 0x6E6F5F6B
    assert parsed["device_path"] is not None and "VOLUME" in parsed["device_path"]


def test_pf_bad_magic_returns_none():
    """Ne-MAM magic → parse_prefetch vrátí None (ne výjimku)."""
    assert parse_prefetch(b"JFET\x01\x02\x03\x04") is None
    assert parse_prefetch(b"MAM") is None  # příliš krátké


def test_pf_missing_scca_signature():
    """Dekomprimuje se, ale chybí 'SCCA' @4 → None."""
    plain = bytearray(200)
    struct.pack_into("<I", plain, 0, 31)
    # SCCA signature záměrně nenapsána (zůstávají nuly)
    data = MAM_MAGIC + struct.pack("<I", len(plain)) + lzxp_identity_compress(bytes(plain))
    assert parse_prefetch(data) is None


def test_pf_artifacts_title_and_details():
    """build_prefetch_artifacts — title s programem a run_count, details kompletní."""
    last_run = datetime(2026, 10, 26, 15, 20, 19, tzinfo=timezone.utc)
    parsed = parse_prefetch(make_pf(run_count=9, volume_serial=0xABCDEF01, last_run=last_run))
    assert parsed is not None
    arts = build_prefetch_artifacts(Path("C:/PF/TESTPROG-1.pf"), parsed)
    assert len(arts) == 1
    art = arts[0]
    assert art.artifact_type == "win_prefetch"
    assert "TESTPROG.EXE" in art.title
    assert "run_count=9" in art.title
    assert art.details["volume_serial"] == "0xABCDEF01"
    assert art.timestamp is not None and art.timestamp.year == 2026


def test_pf_signature_detection():
    """detect_signature na MAM souboru → typ 'win_prefetch'."""
    sig = detect_signature(make_pf())
    assert sig is not None and sig[0] == "win_prefetch" and sig[1] == "windows"


def test_pf_extract_from_file(tmp_path: Path):
    """extract_prefetch_artifacts — IO wrapper nad souborem ve fs."""
    p = tmp_path / "TESTPROG-1.pf"
    p.write_bytes(make_pf(run_count=3))
    arts = extract_prefetch_artifacts(p)
    assert len(arts) == 1
    assert arts[0].artifact_type == "win_prefetch"


# ──────────────────────────────────────────────────────────────────────
# Jump Lists parser (4 testy)
# ──────────────────────────────────────────────────────────────────────


def test_jl_parse_container_with_entries():
    """Kontejner se 2 embedded LNK → parse_jump_list vrátí obě entry s cíli."""
    e1 = make_lnk(target="C:\\Users\\gamer\\Documents\\prace.docx")
    e2 = make_lnk(relative="..\\Downloads\\img.png", name="Obrázek")
    data = make_jump_list([e1, e2])
    entries = parse_jump_list(data)
    assert len(entries) == 2
    assert entries[0]["target_path"] == "C:\\Users\\gamer\\Documents\\prace.docx"
    assert entries[1]["relative_path"] == "..\\Downloads\\img.png"
    assert entries[1]["name"] == "Obrázek"


def test_jl_is_jump_list_file_name_based():
    """Name-based detektor — .customDestinations-ms ano, ostatní ne."""
    assert is_jump_list_file("16f2f0042ddbe0e8.customDestinations-ms")
    assert is_jump_list_file("ABC.CUSTOMDESTINATIONS-MS")  # case-insensitive
    assert not is_jump_list_file("foo.lnk")
    assert not is_jump_list_file("customdestinations.txt")


def test_jl_artifacts_per_entry():
    """build_jump_list_artifacts — jeden artifact na entry, GUID v details."""
    entries = parse_jump_list(
        make_jump_list([make_lnk(target="C:\\a.exe"), make_lnk(target="C:\\b.exe")])
    )
    arts = build_jump_list_artifacts(Path("deadbeef.customDestinations-ms"), entries)
    assert len(arts) == 2
    for i, art in enumerate(arts):
        assert art.artifact_type == "win_jumplist"
        assert art.details["jump_list_guid"] == "deadbeef"
        assert art.details["entry_index"] == i
    assert "C:\\a.exe" in arts[0].title


def test_jl_empty_container_no_entries(tmp_path: Path):
    """Kontejner bez embedded LNK → prázdný seznam (ne výjimka)."""
    data = make_jump_list([])  # jen 20 B header
    assert parse_jump_list(data) == []
    p = tmp_path / "empty.customDestinations-ms"
    p.write_bytes(data)
    assert extract_jump_list_artifacts(p) == []


# ──────────────────────────────────────────────────────────────────────
# E2E pipeline (3 testy) — process_source → DB artifacts
# ──────────────────────────────────────────────────────────────────────

CASE_ID = "case-e6"


@pytest.fixture
def case_db(tmp_path: Path) -> CaseDB:
    db = CaseDB(tmp_path / "case.db")
    db.add_case(Case(id=CASE_ID, name="E6 test"))
    return db


def _add_source(db: CaseDB, root: Path) -> EvidenceSource:
    src = EvidenceSource(case_id=CASE_ID, kind="folder", path=str(root))
    db.add_source(src)
    return src


def test_e2e_lnk_pipeline(tmp_path: Path, case_db: CaseDB):
    """LNK soubor v evidence stromu → shell_link artifact v DB."""
    (tmp_path / "Recent").mkdir()
    (tmp_path / "Recent" / "notepad.lnk").write_bytes(
        make_lnk(target="C:\\Windows\\notepad.exe", name="Notepad")
    )
    src = _add_source(case_db, tmp_path)
    process_source(case_db, src.id, tmp_path, "forensic")

    arts = case_db.list_artifacts(source_id=src.id, artifact_type="shell_link")
    assert len(arts) == 1
    assert arts[0].details["target_path"] == "C:\\Windows\\notepad.exe"
    assert arts[0].file_id is not None


def test_e2e_prefetch_pipeline(tmp_path: Path, case_db: CaseDB):
    """MAM .pf v evidence stromu → win_prefetch artifact v DB."""
    (tmp_path / "PF").mkdir()
    (tmp_path / "PF" / "TESTPROG-1.pf").write_bytes(make_pf(run_count=5))
    src = _add_source(case_db, tmp_path)
    process_source(case_db, src.id, tmp_path, "forensic")

    arts = case_db.list_artifacts(source_id=src.id, artifact_type="win_prefetch")
    assert len(arts) == 1
    assert "TESTPROG.EXE" in arts[0].title
    assert arts[0].details["run_count"] == 5


def test_e2e_jumplist_pipeline(tmp_path: Path, case_db: CaseDB):
    """Jump List (.customDestinations-ms) → win_jumplist artifacty v DB.

    Name-based dispatch — kontejner nemá spolehlivou magic, detekce podle názvu.
    """
    (tmp_path / "CustomDestinations").mkdir()
    jl = make_jump_list([make_lnk(target="C:\\Users\\gamer\\doc.docx")])
    (tmp_path / "CustomDestinations" / "cafebabble.customDestinations-ms").write_bytes(jl)
    src = _add_source(case_db, tmp_path)
    process_source(case_db, src.id, tmp_path, "forensic")

    arts = case_db.list_artifacts(source_id=src.id, artifact_type="win_jumplist")
    assert len(arts) == 1
    assert arts[0].details["jump_list_guid"] == "cafebabble"
    assert arts[0].details["target_path"] == "C:\\Users\\gamer\\doc.docx"
