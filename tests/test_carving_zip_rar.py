"""B1 — inteligentní carving ZIP/OOXML/RAR (přesný rozsah archivu).

ZIP/OOXML: validace End Of Central Directory (EOCD) + offset Central Directory.
RAR5: chůze po blocích (vint HeaderSize/DataSize) až po End of archive (type 5).
RAR4: chůze po blocích (HeadSize/AddSize) až po ENDARC (type 0x72).

Čisté doménové testy — žádné IO, žádné TSK. Fixtures: reálné ZIP/DOCX přes
stdlib ``zipfile`` + syntetické RAR4/RAR5 dle specifikace rarlab.com/technote.htm
a 7-Zip kMarker (RAR5 marker 8 B, RAR4 marker 7 B).
"""

from __future__ import annotations

import io
import struct
import zipfile

from stopa.domain.carving import _estimate_size, carve

# ── fixture generátory ────────────────────────────────────────────────────


def make_zip(names: dict[str, bytes]) -> bytes:
    """Reálný ZIP přes stdlib (ZIP_DEFLATED)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in names.items():
            z.writestr(name, data)
    return buf.getvalue()


def _varint(v: int) -> bytes:
    """RAR5 vint: 7bitové skupiny, MSB = pokračování."""
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def make_rar5(file_data: bytes, name: bytes = b"a.txt") -> bytes:
    """Syntetický RAR5 dle technote + 7-Zip kMarker (8 B marker).

    Blok: CRC32(4)+HeaderSize(vint), pak tělo = HeaderType+Flags
    [+DataSize pokud flag 0x0002]+type-specific pole; data area za tělem.
    """
    sig = b"Rar!\x1a\x07\x01\x00"

    def block(htype: int, flags: int, body_extra: bytes = b"", data: bytes = b"") -> bytes:
        body = _varint(htype) + _varint(flags) + body_extra
        return b"\x00" * 4 + _varint(len(body)) + body + data

    arch = sig
    arch += block(1, 0)  # main archive header
    fh_body_extra = _varint(len(file_data)) + len(name).to_bytes(2, "little") + name
    arch += block(2, 0x0002, fh_body_extra, file_data)  # file header s data area
    arch += block(5, 0)  # end of archive (type 5)
    return arch


def make_rar4(file_data: bytes, name: bytes = b"a.txt") -> bytes:
    """Syntetický RAR4 dle technote (7 B marker).

    Blok: HEAD_CRC(2)+Type(1)+Flags(2)+HeadSize(2); AddSize/PackSize(4) jen
    pokud je flag 0x8000. HeadSize = hlavička od HEAD_CRC (bez dat); jméno
    souboru je implicitní za Method do konce HeadSize.
    """
    sig = b"Rar!\x1a\x07\x00"
    arch = sig + struct.pack("<HBHH", 0, 0x73, 0, 13) + b"\x00" * 6  # main header
    head_size = 26 + len(name)
    fh = (
        struct.pack("<HBHHI", 0, 0x74, 0x8000, head_size, len(file_data))
        + struct.pack(
            "<IBIIBB",
            len(file_data),  # UnpSize
            2,               # HostOS (Win32)
            0,               # FileTime
            0,               # FileCRC
            29,              # UnpVer
            0,               # Method (store)
        )
        + name
    )
    assert len(fh) == head_size
    arch += fh + file_data
    arch += struct.pack("<HBHH", 0, 0x72, 0, 7)  # ENDARC
    return arch


# ── ZIP / OOXML — EOCD validace ───────────────────────────────────────────


class TestZipExtent:
    def test_real_zip_presetny_rozsah(self):
        z = make_zip({"a.txt": b"hello zip world", "b.bin": bytes(range(64))})
        assert _estimate_size(z, 0, "zip") == len(z)

    def test_docx_ooxml_presetny_rozsah(self):
        d = make_zip(
            {
                "[Content_Types].xml": b"<Types/>",
                "_rels/.rels": b"<?xml version='1.0'?><Relationships/>",
                "word/document.xml": b"<w:document/>",
            }
        )
        assert _estimate_size(d, 0, "docx") == len(d)

    def test_xlsx_typ_sdieli_zip_strukturu(self):
        x = make_zip({"xl/workbook.xml": b"<workbook/>"})
        assert _estimate_size(x, 0, "xlsx") == len(x)

    def test_truncovany_zip_bez_eocd_none(self):
        z = make_zip({"a.txt": b"hello zip world"})
        trunc = z[: len(z) // 2]
        assert _estimate_size(trunc, 0, "zip") is None

    def test_carve_na_obrazu_presetny_extent(self):
        z = make_zip({"a.txt": b"hello zip world", "b.bin": bytes(range(64))})
        image = b"\x00" * 1024 + z + b"\xff" * 512
        res = [c for c in carve(image, min_size=32) if c.sig_type == "zip"]
        assert len(res) >= 1
        hit = next(c for c in res if c.offset == 1024)
        assert hit.size_estimate == len(z)


# ── RAR5 — chůze po blocích do End of archive ─────────────────────────────


class TestRar5Extent:
    def test_synteticky_rar5_presetny_rozsah(self):
        r = make_rar5(b"hello rar world test data")
        assert _estimate_size(r, 0, "rar") == len(r)

    def test_carve_na_obrazu_presetny_extent(self):
        r = make_rar5(b"hello rar world test data")
        image = b"\x00" * 256 + r + b"\xff" * 128
        res = [c for c in carve(image, min_size=32) if c.sig_type == "rar"]
        assert len(res) >= 1
        hit = next(c for c in res if c.offset == 256)
        assert hit.size_estimate == len(r)

    def test_truncovany_rar5_none(self):
        r = make_rar5(b"hello rar world test data")
        trunc = r[: len(r) // 2]
        assert _estimate_size(trunc, 0, "rar") is None


# ── RAR4 — chůze po blocích do ENDARC ─────────────────────────────────────


class TestRar4Extent:
    def test_synteticky_rar4_presetny_rozsah(self):
        r = make_rar4(b"hello rar world test data")
        assert _estimate_size(r, 0, "rar") == len(r)

    def test_carve_na_obrazu_presetny_extent(self):
        r = make_rar4(b"hello rar world test data")
        image = b"\x00" * 128 + r + b"\xff" * 96
        res = [c for c in carve(image, min_size=32) if c.sig_type == "rar"]
        assert len(res) >= 1
        hit = next(c for c in res if c.offset == 128)
        assert hit.size_estimate == len(r)

    def test_truncovany_rar4_none(self):
        r = make_rar4(b"hello rar world test data")
        trunc = r[: len(r) // 2]
        assert _estimate_size(trunc, 0, "rar") is None


# ── verze rozlišení (RAR5 marker 8 B vs RAR4 7 B) ─────────────────────────


class TestRarVersionDispatch:
    def test_rar5_marker_8b(self):
        r = make_rar5(b"data")
        assert r[:8] == b"Rar!\x1a\x07\x01\x00"

    def test_rar4_marker_7b(self):
        r = make_rar4(b"data")
        assert r[:7] == b"Rar!\x1a\x07\x00"
