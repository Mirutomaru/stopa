"""P1-1 vlna 31 — E8/file_meta rodina: quality sada (parser ``file_meta``).

PDF /Info + OOXML docProps (core.xml/app.xml) + ID3v2 text frames + MP4/iTunes
atomy. Testované dokumentované kontrakty:
- Čas/tz: PDF ``D:`` datumy → ISO 8601 s offsetem (Z, ±hh'mm', bez offsetu =
  naive); OOXML W3CDTF pass-through as-is; ID3 TDRC priorita před TYER.
- Kódování/locale: česká diakritika roundtrip — PDF oktály/hex stringy
  (latin-1), ID3v2 UTF-16BE, OOXML core.xml UTF-8 (plná sada š/ř/č).
- Poškození: neuzavřený PDF string / invalidní hex → graceful; PK bez docProps
  a poškozené XML → ``{}``; prázdný ID3 frame → skip.
- Limity: docProps člen > 256 KiB se přeskočí, = 256 KiB projde (P1 security).
"""

from __future__ import annotations

import io
import struct
import zipfile

from stopa.domain.file_meta import _MAX_DOCPROPS_BYTES, extract_metadata

# ── buildery ────────────────────────────────────────────────────────


def _pdf(*kv: bytes) -> bytes:
    """PDF /Info skenovací payload — klíče za sebou (heuristický parser)."""
    return b"%PDF-1.4\n" + b"\n".join(kv)


def _zip_docprops(core_xml: str | None, app_xml: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        if core_xml is not None:
            zf.writestr("docProps/core.xml", core_xml)
        if app_xml is not None:
            zf.writestr("docProps/app.xml", app_xml)
    return buf.getvalue()


_CORE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/core"'
    ' xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"'
    ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    "<dc:title>{title}</dc:title><dc:creator>{author}</dc:creator>"
    "<cp:lastModifiedBy>{modified_by}</cp:lastModifiedBy>"
    '<dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>'
    "</cp:coreProperties>"
)

_APP = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
    "<Application>{app}</Application><Company>{company}</Company>"
    "<Pages>{pages}</Pages><Words>{words}</Words></Properties>"
)


def _id3_frame(fid: bytes, text: str, enc: int = 3) -> bytes:
    """STOPA parser layout — fid + fsize(=len body) + flags(2 B) + body."""
    body = bytes([enc]) + text.encode("utf-8" if enc == 3 else "utf-16-be")
    return fid + struct.pack(">I", len(body)) + b"\x00\x00" + body


def _id3(*frames: bytes) -> bytes:
    payload = b"".join(frames)
    size = len(payload)
    syncsafe = ((size >> 21) & 0x7F) | ((size >> 14) & 0x7F) << 7 | (
        (size >> 7) & 0x7F
    ) << 14 | (size & 0x7F) << 21
    return b"ID3\x03\x00\x00" + struct.pack(">I", syncsafe) + payload


def _mp4_box(btype: bytes, *children: bytes, fullbox: bool = False) -> bytes:
    body = (b"\x00\x00\x00\x00" if fullbox else b"") + b"".join(children)
    return struct.pack(">I", 8 + len(body)) + btype + body


def _mp4_text_atom(btype: bytes, text: str) -> bytes:
    encoded = text.encode("utf-8")  # byte length, ne string length (diakritika!)
    data = struct.pack(">I", 12 + len(encoded)) + b"data\x00\x00\x00\x00" + encoded
    return _mp4_box(btype, data)


# ── positive / locale ───────────────────────────────────────────────


# quality: positive
def test_pdf_info_full_extraction():
    """Všechna PDF /Info pole + datumy → ISO 8601."""
    meta = extract_metadata(
        _pdf(
            "/Title (Návrh smlouvy o dílo)".encode("latin-1"),  # PDF stringy = latin-1
            "/Author (Jan Novák)".encode("latin-1"),
            b"/Creator (STOPA writer)",
            b"/Producer (DocTech Pro 2.0)",
            b"/CreationDate (D:20260115103000+01'00')",
            b"/ModDate (D:20260220144500Z)",
        ),
        "smlouva.pdf",
    )
    assert meta["title"] == "Návrh smlouvy o dílo"
    assert meta["author"] == "Jan Novák"
    assert meta["creator"] == "STOPA writer"
    assert meta["producer"] == "DocTech Pro 2.0"
    assert meta["created"] == "2026-01-15T10:30:00+01:00"
    assert meta["modified"] == "2026-02-20T14:45:00+00:00"


# quality: positive locale
def test_ooxml_core_and_app_czech_full():
    """OOXML docProps — plná česká diakritika (š/ř) v core.xml + app statistiky."""
    data = _zip_docprops(
        _CORE.format(title="Návrh smlouvy", author="Matúš Svířek", modified_by="Jana Šedá", created="2026-03-01T09:00:00"),
        _APP.format(app="Microsoft Office Word 2024", company="Společnost s.r.o.", pages=12, words=3456),
    )
    meta = extract_metadata(data, "smlouva.docx")
    assert meta["title"] == "Návrh smlouvy"
    assert meta["author"] == "Matúš Svířek"  # dc:creator → author kontrakt
    assert meta["modified_by"] == "Jana Šedá"
    assert meta["created"] == "2026-03-01T09:00:00"  # W3CDTF as-is
    assert meta["application"] == "Microsoft Office Word 2024"
    assert meta["company"] == "Společnost s.r.o."
    assert meta["pages"] == "12"
    assert meta["words"] == "3456"


# quality: encoding locale
def test_pdf_czech_latin1_roundtrip_octal_and_hex():
    """PDF stringy — oktálové escapes (latin-1 á/ý) a hex <…> roundtrip."""
    # \341 = 0xE1 á, \365 = 0xFD ý (latin-1); hex = ASCII "Jan Nov"
    data = _pdf(
        b"/Title (Smlouva \\341\\375n)",  # \341 á, \375 ý (latin-1)
        b"/Author <4A616E204E6F76>",
    )
    meta = extract_metadata(data, "a.pdf")
    assert meta["title"] == "Smlouva áýn"
    assert meta["author"] == "Jan Nov"


# ── corrupted / negative ────────────────────────────────────────────


# quality: corrupted
def test_pdf_unterminated_string_and_bad_hex_graceful():
    """Neuzavřený PDF string = partial bez výjimky; invalidní hex → pole chybí."""
    meta = extract_metadata(b"%PDF-1.4\n/Title (abc", "x.pdf")
    assert meta.get("title") == "abc"  # graceful partial, ne crash

    meta2 = extract_metadata(_pdf(b"/Author <ZZ>"), "y.pdf")
    assert "author" not in meta2


# quality: corrupted negative
def test_zip_without_docprops_and_bad_xml():
    """PK bez docProps → ``{}``; poškozené core.xml XML → ``{}`` (bounded parse)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("hello.txt", "world")  # běžný zip, žádné docProps
    assert extract_metadata(buf.getvalue(), "x.docx") == {}

    broken = _zip_docprops("<cp:coreProperties><dc:title>neuzavřeno")
    assert extract_metadata(broken, "y.docx") == {}


# quality: negative
def test_unknown_formats_and_empty():
    """Prázdný obsah a neznámé formáty → ``{}`` (metadata = doplňkový důkaz)."""
    assert extract_metadata(b"", "empty.bin") == {}
    assert extract_metadata(b"RIFF\x01\x02\x03\x04WAVE", "a.wav") == {}
    assert extract_metadata(b"plain text bez magic", "p.txt") == {}


# ── boundary / tz / size ────────────────────────────────────────────


# quality: boundary
def test_pdf_date_minimal_forms():
    """Datum s minimálními složkami — rok jen, rok+měsíc, offset bez minut."""
    assert (
        extract_metadata(_pdf(b"/CreationDate (D:2026)"), "a.pdf")["created"]
        == "2026-01-01T00:00:00"
    )
    assert (
        extract_metadata(_pdf(b"/ModDate (D:202605)"), "b.pdf")["modified"]
        == "2026-05-01T00:00:00"
    )
    assert (
        extract_metadata(_pdf(b"/CreationDate (D:202605150930+01'30')"), "c.pdf")["created"]
        == "2026-05-15T09:30:00+01:30"
    )


# quality: tz
def test_pdf_date_offsets_z_and_negative():
    """Z → +00:00, záporný offset -hh'mm' → -hh:mm; bez offsetu = naive."""
    assert (
        extract_metadata(_pdf(b"/CreationDate (D:19990101)"), "a.pdf")["created"]
        == "1999-01-01T00:00:00"  # naive — offset není v zdroji
    )
    assert (
        extract_metadata(_pdf(b"/ModDate (D:20260515093000-05'30')"), "b.pdf")["modified"]
        == "2026-05-15T09:30:00-05:30"
    )


# quality: size boundary
def test_docprops_member_limit_256kib():
    """P1 security — docProps člen > 256 KiB se přeskočí, = limit projde."""
    base_core = _CORE.format(title="t", author="a", modified_by="m", created="c")
    # přesně na hranici: <!-- + N×x + --> = 7 B overhead → N = limit − len − 7
    pad_ok = "<!--" + "x" * (_MAX_DOCPROPS_BYTES - len(base_core) - 7) + "-->"
    core_ok = base_core + pad_ok
    assert len(core_ok) == _MAX_DOCPROPS_BYTES  # sanity: přesně na limitu
    assert extract_metadata(_zip_docprops(core_ok), "ok.docx")["author"] == "a"

    core_big = base_core + pad_ok + "x"
    assert len(core_big) == _MAX_DOCPROPS_BYTES + 1  # sanity: přesně o 1 B nad limitem
    meta = extract_metadata(_zip_docprops(core_big), "big.docx")
    assert "author" not in meta  # člen přeskákán → metadata chybí


# ── ID3v2 / MP4 (encoding) ──────────────────────────────────────────


# quality: encoding positive
def test_id3v2_utf16be_czech_and_tdrc_priority():
    """ID3v2 UTF-16BE česká diakritika; TDRC má prioritu před TYER."""
    data = _id3(
        _id3_frame(b"TIT2", "Písně pro děti", enc=2),  # utf-16-be
        _id3_frame(b"TDRC", "2024"),
        _id3_frame(b"TYER", "2001"),
    )
    meta = extract_metadata(data, "album.mp3")
    assert meta["title"] == "Písně pro děti"
    assert meta["year"] == "2024"  # TDRC vyhrálo nad TYER


# quality: encoding positive
def test_mp4_text_atoms_utf8():
    """MP4/iTunes — moov/udta/meta/ilst textové atomy (utf-8)."""
    # dispatch vyžaduje standardní ftyp header na začátku souboru
    ftyp = struct.pack(">I", 16) + b"ftypM4A \x00\x00\x00\x00"
    data = ftyp + _mp4_box(
        b"moov",
        _mp4_box(
            b"udta",
            _mp4_box(
                b"meta",
                _mp4_box(
                    b"ilst",
                    _mp4_text_atom(b"\xa9nam", "Královéhradecká symfonie"),
                    _mp4_text_atom(b"aart", "Sbor Matúš"),
                ),
                fullbox=True,  # meta je FullBox (version+flags)
            ),
        ),
    )
    meta = extract_metadata(data, "a.m4a")
    assert meta["title"] == "Královéhradecká symfonie"
    assert meta["performer"] == "Sbor Matúš"
