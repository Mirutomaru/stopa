"""Testy detekce signatur (magic bytes) — FTK File Signature Analysis."""

from __future__ import annotations

import pytest

from stopa.domain.signatures import detect_signature, signature_family


@pytest.mark.parametrize(
    ("data", "expected_type"),
    [
        (b"\x89PNG\r\n\x1a\n" + b"x", "png"),
        (b"\xff\xd8\xff\xe0" + b"x", "jpeg"),
        (b"GIF87a" + b"x", "gif"),
        (b"GIF89a" + b"x", "gif"),
        (b"BM" + b"x" * 32, "bmp"),
        (b"\x4d\x4d\x00\x2a" + b"x", "tiff"),
        (b"%PDF-1.7\n%obj", "pdf"),
        (b"PK\x03\x04" + b"\x00" * 64, "zip"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"x", "ole2"),
        (b"SQLite format 3\x00" + b"x", "sqlite"),
        (b"regf" + b"\x00" * 20, "registry_hive"),
        (b"bplist00" + b"\x00" * 16, "plist"),
        (b"\x7fELF\x02\x01\x01" + b"x", "elf"),
        (b"7z\xbc\xaf\x27\x1c" + b"x", "7zip"),
        (b"Rar!\x1a\x07" + b"x", "rar"),
    ],
)
def test_known_signatures(data: bytes, expected_type: str):
    result = detect_signature(data)
    assert result is not None
    assert result[0] == expected_type


def test_ooxml_refinement_docx():
    data = b"PK\x03\x04" + b"[Content_Types].xml" + b"\x00" * 16 + b"word/document.xml"
    assert detect_signature(data) == ("docx", "document")


def test_ooxml_refinement_xlsx():
    data = b"PK\x03\x04" + b"[Content_Types].xml" + b"\x00" * 16 + b"xl/workbook.xml"
    assert detect_signature(data) == ("xlsx", "document")


def test_ooxml_refinement_pptx():
    data = b"PK\x03\x04" + b"[Content_Types].xml" + b"\x00" * 16 + b"ppt/presentation.xml"
    assert detect_signature(data) == ("pptx", "document")


def test_apk_detection():
    data = b"PK\x03\x04" + b"META-INF/ANDROID" + b"\x00" * 16 + b"classes.dex"
    assert detect_signature(data) == ("apk", "package")


def test_pe_with_valid_header():
    import struct

    data = b"MZ" + b"\x00" * 58 + struct.pack("<I", 64) + b"PE\x00\x00"
    assert detect_signature(data) == ("pe", "executable")


def test_mz_without_pe_header_not_flagged_as_pe():
    # MZ bez platné PE hlavičky → nejspíš DOS .COM — nenechat padnout, typ None nebo jiný
    data = b"MZ" + b"\x00" * 64
    result = detect_signature(data)
    assert result is None or result[0] != "pe"


def test_mp4_ftyp_at_offset_4():
    data = b"\x00\x00\x00\x1cftypisom" + b"\x00" * 32
    assert detect_signature(data) == ("iso_bmff", "media")


def test_riff_webp():
    import struct

    data = b"RIFF" + struct.pack("<I", 64) + b"WEBP" + b"\x00" * 32
    assert detect_signature(data) == ("webp", "image")


def test_riff_wav():
    import struct

    data = b"RIFF" + struct.pack("<I", 64) + b"WAVE" + b"\x00" * 32
    assert detect_signature(data) == ("wav", "audio")


def test_unknown_data_returns_none():
    assert detect_signature(b"\x00\x01\x02\x03random text here") is None


def test_empty_data_returns_none():
    assert detect_signature(b"") is None


def test_short_data_no_crash():
    # kratší data než magic — bez IndexError
    assert detect_signature(b"\x89P") is None


def test_xml_plist_detection():
    xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        b'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        b'<plist version="1.0"><dict></dict></plist>'
    )
    assert detect_signature(xml) == ("plist", "propertylist")


def test_family_lookup():
    assert signature_family("png") == "image"
    assert signature_family("pdf") == "document"
    assert signature_family("docx") == "document"  # refined typ
    assert signature_family("registry_hive") == "registry"
    assert signature_family("plist") == "propertylist"
    assert signature_family(None) is None
