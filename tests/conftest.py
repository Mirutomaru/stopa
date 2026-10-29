"""Společné fixture pro STOPA testy — syntetické soubory, žádná síť."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

# ── magic bytes fixtures (syntetické hlavičky) ────────────────

PNG_1x1 = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF_HEAD = b"GIF89a" + b"\x00" * 32
PDF_HEAD = b"%PDF-1.7\n" + b"\x00" * 32
ZIP_HEAD = b"PK\x03\x04" + b"\x00" * 64
DOCX_HEAD = (b"PK\x03\x04" + b"[Content_Types].xml" + b"\x00" * 16 + b"word/document.xml")
XLSX_HEAD = (b"PK\x03\x04" + b"[Content_Types].xml" + b"\x00" * 16 + b"xl/workbook.xml")
APK_HEAD = (b"PK\x03\x04" + b"META-INF/ANDROID" + b"\x00" * 16 + b"classes.dex")
OLE2_HEAD = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32
SQLITE_HEAD = b"SQLite format 3\x00" + b"\x00" * 32
ELF_HEAD = b"\x7fELF" + b"\x02\x01\x01" + b"\x00" * 32
PE_HEAD = b"MZ" + b"\x00" * 58 + struct.pack("<I", 64) + b"PE\x00\x00"  # e_lfanew=64 → PE na 64
SEVENZ_HEAD = b"7z\xbc\xaf\x27\x1c" + b"\x00" * 32
RAR_HEAD = b"Rar!\x1a\x07" + b"\x00" * 32
MP4_HEAD = b"\x00\x00\x00\x1c" + b"ftyp" + b"isom"  # box header + 'ftyp' na offsetu 4
WEBP_HEAD = b"RIFF" + struct.pack("<I", 64) + b"WEBP" + b"\x00" * 32
WAV_HEAD = b"RIFF" + struct.pack("<I", 64) + b"WAVE" + b"\x00" * 32


@pytest.fixture
def make_file(tmp_path: Path):
    """Vytvoří soubor se zadaným obsahem a vrátí cestu."""

    def _make(name: str, data: bytes) -> Path:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    return _make


@pytest.fixture
def evidence_tree(tmp_path: Path):
    """Syntetický evidence source — složka se soubory různých typů."""
    root = tmp_path / "evidence"
    (root / "docs").mkdir(parents=True)
    (root / "media").mkdir()

    files = {
        "readme.txt": b"hello world\n",
        "photo.png": PNG_1x1,
        "fake.jpg": PE_HEAD + b"\x00" * 32,  # PE executable s příponou .jpg → bad ext
        "docs/report.pdf": PDF_HEAD,
        "docs/presentation.pptx": XLSX_HEAD,  # xlsx signatura s .pptx → bad ext
        "media/clip.mp4": MP4_HEAD + b"\x00" * 32,
        "archive.zip": ZIP_HEAD,
        "app.apk": APK_HEAD,
        "db.sqlite": SQLITE_HEAD,
        "binary.elf": ELF_HEAD,
        "dup_a.bin": b"A" * 1024,
        "media/dup_b.bin": b"A" * 1024,  # duplikát dup_a.bin (stejné bajty)
    }
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root
