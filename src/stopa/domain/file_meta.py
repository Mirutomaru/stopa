"""E8 — File metadata extraction (čistý Python, bez IO).

Podporované formáty:
- PDF ``/Info`` slovník (Title/Author/Creator/Producer/dates)
- OOXML docProps (docx/xlsx/pptx — core.xml + app.xml přes zipfile)
- ID3v2 audio tagy (TIT2/TPE1/TALB/TRCK/...)
- MP4/iTunes atomy (©nam/©ART/aart/©alb/trkn/...)
- EXIF přes PIL (volitelné extra ``[meta]`` — lazy import)

API:
    extract_metadata(data, name) -> dict[str, str]   # normalizovaná pole
    diff_metadata(meta_a, meta_b) -> list[dict]      # porovnání dvou souborů

Všechny parsery jsou defenzivní (try/except per formát) a vrací ``{}``
při neznámém/poškozeném obsahu — metadata jsou doplňkový důkaz, ne pipeline.
"""

from __future__ import annotations

import io
import logging
import re
import xml.etree.ElementTree as ET
import zipfile

logger = logging.getLogger(__name__)

# ── PDF /Info ────────────────────────────────────────────────────────

_PDF_KEYS: dict[bytes, str] = {
    b"/Title": "title",
    b"/Author": "author",
    b"/Creator": "creator",
    b"/Producer": "producer",
    b"/CreationDate": "created",
    b"/ModDate": "modified",
}

_PDF_DATE_RE = re.compile(
    r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?"
    r"(?:([+-])(\d{2})'?(\d{2})'?)?(Z)?"
)


def _pdf_parse_string(data: bytes, i: int) -> tuple[str | None, int]:
    """PDF string token na offsetu ``i`` — literal ``(…)`` s escapes/nestingem
    nebo hex ``<…>``. Vrací (text, konec)."""
    if data[i:i + 1] == b"(":
        depth = 1
        j = i + 1
        out = bytearray()
        while j < len(data) and depth > 0:
            c = data[j:j + 1]
            if c == b"\\" and j + 1 < len(data):
                n = data[j + 1:j + 2]
                if n in (b"(", b")", b"\\"):
                    out += n
                    j += 2
                    continue
                if n in (b"n", b"r", b"t"):
                    out += {b"n": b"\n", b"r": b"\r", b"t": b"\t"}[n]
                    j += 2
                    continue
                # oktalový escape — až 3 číslice
                k = j + 1
                while k < len(data) and data[k:k + 1].isdigit() and (k - j) <= 3:
                    k += 1
                if k > j + 1:
                    out.append(int(data[j + 1:k], 8))
                    j = k
                    continue
                j += 2
                continue
            if c == b"(":
                depth += 1
                out += c
            elif c == b")":
                depth -= 1
                if depth > 0:
                    out += c
            else:
                out += c
            j += 1
        return out.decode("latin-1", "replace"), j
    # hex string <…>
    end = data.find(b">", i)
    if end == -1:
        return None, len(data)
    hx = bytes(c for c in data[i + 1:end] if c not in b" \t\r\n")
    if len(hx) % 2:
        hx += b"0"
    try:
        return bytes.fromhex(hx.decode("ascii")).decode("latin-1", "replace"), end + 1
    except ValueError:
        return None, end + 1


def _clean_pdf_date(s: str) -> str:
    """PDF date ``D:20260101120000+01'00'`` → ISO 8601."""
    m = _PDF_DATE_RE.match(s.strip())
    if not m:
        return s
    y, mo, d, h, mi, sec = m.groups()[:6]
    sign, oh, omi, z = m.group(7), m.group(8), m.group(9), m.group(10)
    ts = f"{y}-{mo or '01'}-{d or '01'}T{h or '00'}:{mi or '00'}:{sec or '00'}"
    if z:
        return ts + "+00:00"
    if sign and oh:
        return ts + f"{sign}{oh}:{omi or '00'}"
    return ts


def _parse_pdf_info(data: bytes) -> dict[str, str]:
    """PDF /Info — sken klíčů s validním string tokenem (heuristika;
    /Info bývá indirect reference, proto první platná hodnota vyhrává)."""
    out: dict[str, str] = {}
    for key, field in _PDF_KEYS.items():
        idx = 0
        while True:
            i = data.find(key, idx)
            if i == -1:
                break
            j = i + len(key)
            while j < len(data) and data[j:j + 1] in b" \t\r\n":
                j += 1
            if j < len(data) and data[j:j + 1] in (b"(", b"<"):
                val, _ = _pdf_parse_string(data, j)
                if val:
                    v = val.strip()
                    if field in ("created", "modified"):
                        v = _clean_pdf_date(v)
                    if v:
                        out.setdefault(field, v)
                        break
            idx = i + len(key)
    return out


# ── OOXML docProps (docx/xlsx/pptx) ─────────────────────────────────

_OOXML_CORE_FIELDS = {
    "title": "title",
    "creator": "author",
    "lastModifiedBy": "modified_by",
    "created": "created",
    "modified": "modified",
}

_OOXML_APP_FIELDS = {
    "Application": "application",
    "Company": "company",
    "Pages": "pages",
    "Words": "words",
    "Characters": "characters",
    "Slides": "slides",
    "Lines": "lines",
    "Paragraphs": "paragraphs",
}


def _parse_ooxml(data: bytes) -> dict[str, str]:
    """OOXML docProps — core.xml (Dublin Core) + app.xml přes zipfile."""
    out: dict[str, str] = {}
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return out
    names = set(zf.namelist())

    if "docProps/core.xml" in names:
        try:
            root = ET.fromstring(zf.read("docProps/core.xml"))
        except (ET.ParseError, OSError):
            root = None
        if root is not None:
            for local, field in _OOXML_CORE_FIELDS.items():
                for el in root.iter():
                    if el.tag.split("}")[-1] == local and (el.text or "").strip():
                        out.setdefault(field, el.text.strip())
                        break

    if "docProps/app.xml" in names:
        try:
            root = ET.fromstring(zf.read("docProps/app.xml"))
        except (ET.ParseError, OSError):
            root = None
        if root is not None:
            for el in root.iter():
                field = _OOXML_APP_FIELDS.get(el.tag.split("}")[-1])
                if field and (el.text or "").strip():
                    out.setdefault(field, el.text.strip())
    return out


# ── ID3v2 audio tagy ────────────────────────────────────────────────

_ID3_TEXT_TAGS: dict[bytes, str] = {
    b"TIT2": "title",
    b"TPE1": "artist",
    b"TALB": "album",
    b"TRCK": "track",
    b"TDRC": "year",
    b"TYER": "year",  # ID3v2.2/2.3 legacy — TDRC má prioritu (setdefault)
    b"TCON": "genre",
    b"TBPM": "bpm",
}

_ID3_ENCODINGS = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}


def _syncsafe(b: bytes) -> int:
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def _parse_id3v2(data: bytes) -> dict[str, str]:
    """ID3v2.3/2.4 text frames (TIT2/TPE1/...). TDRC má prioritu před TYER."""
    out: dict[str, str] = {}
    if data[:3] != b"ID3":
        return out
    size = _syncsafe(data[6:10])
    end = min(10 + size, len(data))
    frames: list[tuple[bytes, bytes]] = []  # (fid, body)
    pos = 10
    while pos + 10 <= end:
        fid = data[pos:pos + 4]
        if not re.fullmatch(rb"[A-Z0-9]{4}", fid):
            break
        fsize = int.from_bytes(data[pos + 4:pos + 8], "big")
        frames.append((fid, data[pos + 10:pos + 10 + fsize]))
        pos += 10 + fsize

    def apply(fid: bytes, body: bytes) -> None:
        field = _ID3_TEXT_TAGS.get(fid)
        if not (field and body):
            return
        enc = _ID3_ENCODINGS.get(body[0])
        if not enc:
            return
        try:
            s = body[1:].decode(enc, "replace").strip("\x00").strip()
        except UnicodeDecodeError:
            return
        if s:
            out.setdefault(field, s)

    # TDRC (moderní ID3v2.4) aplikovat PŘED TYER (legacy 2.2/2.3) — setdefault
    for fid, body in frames:
        if fid == b"TDRC":
            apply(fid, body)
    for fid, body in frames:
        if fid != b"TDRC":
            apply(fid, body)
    return out


# ── MP4/iTunes atomy ────────────────────────────────────────────────

_MP4_TEXT_ATOMS: dict[bytes, str] = {
    b"\xa9nam": "title",
    b"\xa9ART": "artist",
    b"aart": "performer",
    b"\xa9alb": "album",
    b"\xa9day": "year",
    b"\xa9gen": "genre",
}


def _parse_mp4(data: bytes) -> dict[str, str]:
    """MP4/iTunes atomy — walk moov/udta/meta/ilst + text tagy a trkn."""
    out: dict[str, str] = {}

    def _data_payload(inner: int, box_end: int) -> bytes | None:
        """Obsah ``data`` sub-boxu (za u32 type indikátorem)."""
        d = inner
        while d + 8 <= box_end:
            dsz = int.from_bytes(data[d:d + 4], "big")
            if dsz < 16 or d + dsz > box_end:
                break
            if data[d + 4:d + 8] == b"data":
                return data[d + 12:d + dsz]
            d += dsz
        return None

    def walk(off: int, end: int, depth: int) -> None:
        if depth > 8 or off >= end:
            return
        pos = off
        while pos + 8 <= end:
            size = int.from_bytes(data[pos:pos + 4], "big")
            btype = data[pos + 4:pos + 8]
            hdr = 8
            if size == 1 and pos + 16 <= end:
                size = int.from_bytes(data[pos + 8:pos + 16], "big")
                hdr = 16
            elif size == 0:
                size = end - pos
            if size < hdr or pos + size > end:
                break
            body_start = pos + hdr
            box_end = pos + size
            # meta je FullBox — za headerem ještě version+flags (4 B)
            inner = body_start + 4 if btype == b"meta" else body_start
            if btype in (b"moov", b"udta", b"ilst", b"meta"):
                walk(inner, box_end, depth + 1)
            elif btype in _MP4_TEXT_ATOMS:
                payload = _data_payload(inner, box_end)
                if payload is not None:
                    s = payload.decode("utf-8", "replace").strip("\x00").strip()
                    if s:
                        out.setdefault(_MP4_TEXT_ATOMS[btype], s)
            elif btype == b"trkn":
                # binární: u16 reserved, u16 track, u16 total
                payload = _data_payload(inner, box_end)
                if payload is not None and len(payload) >= 4:
                    track = int.from_bytes(payload[2:4], "big")
                    total = int.from_bytes(payload[4:6], "big") if len(payload) >= 6 else 0
                    out.setdefault("track", str(track) + (f"/{total}" if total else ""))
            pos += size

    walk(0, len(data), 0)
    return out


# ── EXIF přes PIL (volitelné extra [meta]) ─────────────────────────

_EXIF_FIELDS = {
    "Make": "camera_make",
    "Model": "camera_model",
    "DateTimeOriginal": "created",
    "Artist": "artist",
    "Copyright": "copyright",
}


def _parse_exif(data: bytes) -> dict[str, str]:
    """EXIF přes PIL — lazy import (volitelné extra ``[meta]``)."""
    try:
        from PIL import Image  # lazy — volitelná závislost
        from PIL.ExifTags import TAGS
    except ImportError:
        logger.debug("file_meta EXIF — chybí Pillow (extra [meta])")
        return {}
    try:
        img = Image.open(io.BytesIO(data))
        exif = img.getexif()
    except Exception:  # noqa: BLE001 — cizí binární formáty, PIL háže vše
        return {}
    out: dict[str, str] = {}
    for tag_id, value in exif.items():
        field = _EXIF_FIELDS.get(TAGS.get(tag_id, ""))
        if not field or value is None:
            continue
        s = str(value).strip()
        if s and s.lower() != "none":
            out.setdefault(field, s)
    return out


# ── dispatch + porovnání ────────────────────────────────────────────

_IMAGE_EXTS = frozenset({"jpg", "jpeg", "png", "tif", "tiff", "heic", "webp"})


def extract_metadata(data: bytes, name: str) -> dict[str, str]:
    """Extrahovat metadata z obsahu souboru (čistá funkce, bez IO).

    Dispatch podle magic bytes + přípony; neznámý formát → ``{}``.
    """
    if not data:
        return {}
    head = data[:16]
    try:
        if head.startswith(b"%PDF"):
            return _parse_pdf_info(data)
        if head[:4] == b"PK\x03\x04":
            out = _parse_ooxml(data)
            if out:
                return out
        if head[:3] == b"ID3":
            return _parse_id3v2(data)
        if len(head) >= 8 and head[4:8] == b"ftyp":
            return _parse_mp4(data)
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext in _IMAGE_EXTS:
            return _parse_exif(data)
    except Exception:
        logger.debug("file_meta: extrakce selhala pro %s", name, exc_info=True)
    return {}


def diff_metadata(meta_a: dict[str, str], meta_b: dict[str, str]) -> list[dict]:
    """Porovnání metadat dvou souborů — řádky ``{field, a, b, match}``.

    Pole seřazená abecedně; chybějící hodnota = ``None`` (mismatch).
    """
    fields = sorted(set(meta_a) | set(meta_b))
    return [
        {
            "field": f,
            "a": meta_a.get(f),
            "b": meta_b.get(f),
            "match": meta_a.get(f) == meta_b.get(f),
        }
        for f in fields
    ]
