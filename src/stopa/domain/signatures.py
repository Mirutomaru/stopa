"""Detekce reálného typu souboru podle magic bytes.

Ekvivalent FTK „File Signature Analysis“ / X-Ways type detection.
ČISTÁ funkce nad bajty — žádný IO, žádná síť → 100% offline testovatelné.

Heuristika je záměrně konzervativní: slabé signatury (např. MPEG frame sync)
se používají jen jako poslední možnost a vrací se s nižší jistotou.
"""

from __future__ import annotations

# (offset, magic, kanonický typ, rodina) — pořadí = priorita
SIGNATURES: list[tuple[int, bytes, str, str]] = [
    (0, b"\x89PNG\r\n\x1a\n", "png", "image"),
    (0, b"\xff\xd8\xff", "jpeg", "image"),
    (0, b"GIF87a", "gif", "image"),
    (0, b"GIF89a", "gif", "image"),
    (0, b"BM", "bmp", "image"),
    (0, b"\x4d\x4d\x00\x2a", "tiff", "image"),  # big-endian TIFF
    (0, b"\x49\x49\x2a\x00", "tiff", "image"),  # little-endian TIFF
    (0, b"%PDF-", "pdf", "document"),
    (0, b"PK\x03\x04", "zip", "archive"),  # zip/docx/xlsx/pptx/jar/apk — refine níže
    (0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole2", "compound"),  # doc/xls/ppt/mdb/msi
    (0, b"SQLite format 3\x00", "sqlite", "database"),
    (0, b"\x7fELF", "elf", "executable"),
    (0, b"\xfe\xed\xfa\xce", "macho64", "executable"),
    (0, b"\xca\xfe\xba\xbe", "macho32", "executable"),  # kolize s .class — akceptovatelné
    (0, b"7z\xbc\xaf\x27\x1c", "7zip", "archive"),
    (0, b"\x52\x61\x72\x21\x1a\x07", "rar", "archive"),
    (0, b"MZ", "pe", "executable"),  # DOS/PE — ověřeno PE hlavičkou níže
    (4, b"ftyp", "iso_bmff", "media"),  # MP4/MOV: 'ftyp' na offsetu 4
    (0, b"ID3", "mp3_id3", "audio"),
]

# RIFF kontejner — druhá kontrola na offsetu 8
_RIFF_SUBTYPES = {b"WEBP": ("webp", "image"), b"WAVE": ("wav", "audio"), b"AVI ": ("avi", "media")}


def _refine_zip(data: bytes) -> tuple[str, str] | None:
    """Zip → zjemnit na OOXML/APK podle obsahu (FTK expand compound files — lite)."""
    head = data[:65536]
    if b"[Content_Types].xml" in head or b"_rels/.rels" in head:
        for marker, typ in ((b"word/", "docx"), (b"xl/", "xlsx"), (b"ppt/", "pptx")):
            if marker in head:
                return typ, "document"
        return "ooxml", "document"
    if b"META-INF/ANDROID" in head or b"classes.dex" in head:
        return "apk", "package"
    return None


def _is_pe(data: bytes) -> bool:
    """MZ + PE\\0\\0 na e_lfanew offsetu (klasická FTK kontrola)."""
    if len(data) < 64:
        return False
    try:
        import struct

        e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    except struct.error:
        return False
    if e_lfanew + 4 > len(data):
        return False
    return data[e_lfanew : e_lfanew + 4] == b"PE\x00\x00"


def detect_signature(data: bytes) -> tuple[str, str] | None:
    """Vrátí (kanonický typ, rodina) nebo None pokud signatura neznámá.

    `data` stačí první ~64 KB souboru — všechny signatury jsou v hlavičce.
    """
    if not data:
        return None
    for offset, magic, typ, family in SIGNATURES:
        if data[offset : offset + len(magic)] == magic:
            if typ == "pe":
                if _is_pe(data):
                    return ("pe", "executable")
                continue  # MZ bez PE hlavičky — nejspíš starý DOS .COM/.EXE, zkusit dál
            if typ == "zip":
                refined = _refine_zip(data)
                if refined:
                    return refined
                return ("zip", "archive")
            return (typ, family)
    # RIFF podtypy (WEBP/WAV/AVI) — kontrola na offsetu 8
    if data[:4] == b"RIFF" and len(data) >= 12:
        sub = _RIFF_SUBTYPES.get(data[8:12])
        if sub:
            return sub
    # slabá signatura MPEG audio frame sync (jen jako poslední možnost)
    if data[:2] == b"\xff\xfb" or data[:2] == b"\xff\xf3":
        return ("mp3_frame", "audio")
    return None


def signature_family(typ: str | None) -> str | None:
    """Rodina typu (image/document/...) — pro filtry a reporty."""
    if typ is None:
        return None
    for _offset, _magic, t, family in SIGNATURES:
        if t == typ:
            return family
    return {  # typy vzniklé refine/subtypy
        "docx": "document",
        "xlsx": "document",
        "pptx": "document",
        "ooxml": "document",
        "apk": "package",
        "webp": "image",
        "wav": "audio",
        "avi": "media",
        "mp3_id3": "audio",
        "mp3_frame": "audio",
    }.get(typ)
