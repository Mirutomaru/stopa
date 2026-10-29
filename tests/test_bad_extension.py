"""Testy FTK „Flag Bad Extensions“ — rozpor signatura × přípona."""

from __future__ import annotations

import pytest

from stopa.domain.bad_extension import extension_of, is_bad_extension


@pytest.mark.parametrize(
    ("sig", "name", "expected"),
    [
        # konzistentní → False
        ("png", "photo.png", False),
        ("jpeg", "img.JPG", False),  # velká přípona — normalizace
        ("pdf", "doc.pdf", False),
        ("zip", "archive.zip", False),
        ("docx", "report.docx", False),
        ("xlsx", "data.xlsx", False),
        ("ole2", "list.xls", False),  # OLE2 pokrývá doc/xls/ppt/mdb/msi
        ("sqlite", "app.db", False),
        ("pe", "loader.exe", False),
        ("elf", "lib.so", False),
        ("iso_bmff", "video.mp4", False),
        ("mp3_id3", "song.mp3", False),
        # rozporné → True (FTK flag)
        ("pe", "fake.jpg", True),  # executable maskovaný jako obrázek — klasika!
        ("png", "malware.exe", True),
        ("pdf", "invoice.docx", True),
        ("zip", "notes.txt", True),
        ("jpeg", "script.pdf", True),
    ],
)
def test_is_bad_extension(sig: str, name: str, expected: bool):
    assert is_bad_extension(sig, name) is expected


def test_unknown_signature_never_flagged():
    # bez signatury nemůžeme nic tvrdit → False (konzervativní FTK chování)
    assert is_bad_extension(None, "anything.xyz") is False


def test_missing_extension_not_flagged():
    # ELF binárky bez přípony jsou normální → False
    assert is_bad_extension("elf", "binary") is False
    assert is_bad_extension("png", ".hiddenfile") is False  # dot-file bez přípony


def test_type_without_defined_extensions_never_flagged():
    assert is_bad_extension("some_future_type", "x.whatever") is False


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("photo.png", "png"),
        ("IMG.JPG", "jpg"),  # normalizace na malá písmena
        ("archive.tar.gz", "gz"),  # poslední přípona
        ("noext", None),
        (".bashrc", None),  # dot-file bez přípony
        ("file.", None),  # tečka na konci — prázdná přípona
    ],
)
def test_extension_of(name: str, expected: str | None):
    assert extension_of(name) == expected
