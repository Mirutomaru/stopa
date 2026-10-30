"""Testy FÁZE 5 — disk images: image_types + carving (čisté funkce, offline).

TSK IO vrstva se testuje defenzivně v test_tsk.py; zde jen logika nad bajty.
"""

from __future__ import annotations

from stopa.domain.carving import carve, carve_by_family
from stopa.domain.image_types import detect_image_type, is_container

# ── image_types: kontejnery s vlastní magic hlavičkou ────────────────

def test_e01_detection():
    data = b"EWF" + b"\x00" * 64
    assert detect_image_type(data) == ("e01", "Expert Witness Format (EWF/E01)")


def test_aff4_detection():
    data = b"AFF4" + b"\x00" * 64
    typ, _desc = detect_image_type(data)
    assert typ == "aff4"
    assert is_container(typ) is True


def test_is_container():
    assert is_container("e01") is True
    assert is_container("aff4") is True
    assert is_container("dd") is False
    assert is_container(None) is False


# ── image_types: RAW obrazy — podkladový file system ────────────────

def test_ntfs_raw():
    # OEM "NTFS    " na offsetu 3 (8 znaků + 4 mezery)
    data = b"\x00\x00\x00" + b"NTFS    " + b"\x00" * 64
    typ, desc = detect_image_type(data)
    assert typ == "dd"
    assert "ntfs" in desc


def test_fat_raw():
    # FAT boot sector: jump instr. EB na offsetu 0 + AA55 na konci sektoru
    data = bytearray(512)
    data[0] = 0xEB
    data[510] = 0x55
    data[511] = 0xAA
    typ, desc = detect_image_type(bytes(data))
    assert typ == "dd"
    assert "fat" in desc


def test_ext_raw():
    # ext2/3/4 superblock: s_magic=0xEF53 na abs. offsetu 1080 (little-endian)
    data = bytearray(1096)
    data[1080] = 0x53
    data[1081] = 0xEF
    typ, desc = detect_image_type(bytes(data))
    assert typ == "dd"
    assert "ext" in desc


def test_hfsplus_raw():
    # HFS+ volume header: signature 'H+' (0x48 0x2B) na offsetu 1024
    data = bytearray(1096)
    data[1024] = 0x48
    data[1025] = 0x2B
    typ, desc = detect_image_type(bytes(data))
    assert typ == "dd"
    assert "hfsplus" in desc


def test_mbr_raw():
    # MBR/partition table: AA55 na konci sektoru 0, bez FS hlavičky
    data = bytearray(512)
    data[0] = 0x00  # ne EB/E9 → není FAT boot sector
    data[510] = 0x55
    data[511] = 0xAA
    typ, desc = detect_image_type(bytes(data))
    assert typ == "dd"
    assert "mbr" in desc


def test_unknown_raw():
    # žádné známé signatury → None
    data = b"\x00" * 2048
    assert detect_image_type(data) is None


def test_empty_buffer():
    assert detect_image_type(b"") is None


# ── carving: PNG s IEND koncovým markerem ───────────────────────────

def _png_with_iend(payload_len: int = 100) -> bytes:
    """Syntetický PNG: hlavička + payload + IEND chunk (posledních 8 bajtů)."""
    head = b"\x89PNG\r\n\x1a\n"
    body = b"\x00" * payload_len
    iend = b"IEND\xae\x42\x60\x82"
    return head + body + iend


def test_carve_png_finds_offset_and_size():
    data = _png_with_iend(payload_len=100)
    results = carve(data, min_size=16)
    pngs = [c for c in results if c.sig_type == "png"]
    assert len(pngs) >= 1
    p = pngs[0]
    assert p.offset == 0
    # odhadovaná velikost = celá délka bufferu (IEND je na konci)
    assert p.size_estimate == len(data)


def test_carve_png_embedded_offset():
    # PNG zakopaný uprostřed bufferu → offset > 0
    prefix = b"\xde\xad\xbe\xef" * 16  # 64 B šumu (bez magic hlaviček)
    png = _png_with_iend(payload_len=80)
    data = prefix + png
    results = carve(data, min_size=16)
    pngs = [c for c in results if c.sig_type == "png"]
    assert len(pngs) >= 1
    assert pngs[0].offset == len(prefix)


# ── carving: JPEG s EOI markerem ─────────────────────────────────────

def _jpeg_with_eoi(payload_len: int = 120) -> bytes:
    head = b"\xff\xd8\xff\xe0"
    body = b"\x00" * payload_len
    eoi = b"\xff\xd9"
    return head + body + eoi


def test_carve_jpeg_finds_offset_and_size():
    data = _jpeg_with_eoi(payload_len=120)
    results = carve(data, min_size=16)
    jpegs = [c for c in results if c.sig_type == "jpeg"]
    assert len(jpegs) >= 1
    assert jpegs[0].offset == 0
    assert jpegs[0].size_estimate == len(data)


# ── carving: PDF s %%EOF markerem ───────────────────────────────────

def _pdf_with_eof(payload_len: int = 90) -> bytes:
    head = b"%PDF-1.7\n"
    body = b"\x00" * payload_len
    eof = b"%%EOF"
    return head + body + eof


def test_carve_pdf_finds_offset_and_size():
    data = _pdf_with_eof(payload_len=90)
    results = carve(data, min_size=16)
    pdfs = [c for c in results if c.sig_type == "pdf"]
    assert len(pdfs) >= 1
    assert pdfs[0].offset == 0
    assert pdfs[0].size_estimate == len(data)


# ── carving: více souborů v jednom bufferu, seřazení podle offsetu ───

def test_carve_multiple_sorted_by_offset():
    png = _png_with_iend(payload_len=50)
    pdf = _pdf_with_eof(payload_len=50)
    data = b"\x11" * 32 + png + b"\x22" * 32 + pdf
    results = carve(data, min_size=16)
    offsets = [c.offset for c in results]
    assert offsets == sorted(offsets), "výstup musí být seřazený podle offsetu"
    types = {c.sig_type for c in results}
    assert "png" in types and "pdf" in types


# ── carving: min_size filtrování ─────────────────────────────────────

def test_carve_min_size_filters_small():
    # PNG s velmi krátkým payloadem → malý odhad; vysoké min_size ho vyfiltruje
    data = _png_with_iend(payload_len=4)  # celkem ~20 B
    results_low = carve(data, min_size=16)
    assert any(c.sig_type == "png" for c in results_low)
    results_high = carve(data, min_size=10_000)
    assert not any(c.sig_type == "png" and c.size_estimate is not None for c in results_high)


# ── carving: prázdný buffer a rodinový filtr ────────────────────────

def test_carve_empty():
    assert carve(b"", min_size=16) == []


def test_carve_by_family_image():
    data = _png_with_iend(payload_len=80) + b"\x33" * 40 + _jpeg_with_eoi(payload_len=80)
    images = carve_by_family(data, "image", min_size=16)
    assert len(images) >= 2
    assert all(c.family == "image" for c in images)


def test_carve_no_match_returns_empty():
    # čistý šum bez žádné magic hlavičky
    data = b"\x07\x08\x09" * 100
    results = carve(data, min_size=16)
    assert results == []
