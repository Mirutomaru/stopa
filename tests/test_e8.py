"""E8 — File Inspector metadata (PDF/OOXML/ID3v2/MP4/EXIF + porovnání).

Domain testy = generované binární fixture (čistý Python, bez IO);
web E2E přes TestClient s reálnou case DB v tmp.
"""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ── fixture generátory (binární, deterministické) ────────────────────


def _ss(n: int) -> bytes:
    """ID3v2 syncsafe integer (7 bitů na byte)."""
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def make_pdf(
    title: str = "Forenzni dokument",
    author: str | None = "Miroslav Matus",
    creator: str | None = "STOPA",
    producer: str | None = "WeasyPrint 62",
) -> bytes:
    parts = [b"%PDF-1.7\n"]
    info = b"<< "
    if title is not None:
        info += f"/Title ({title}) ".encode()
    if author is not None:
        info += f"/Author ({author}) ".encode()
    if creator is not None:
        info += f"/Creator ({creator}) ".encode()
    if producer is not None:
        info += f"/Producer ({producer}) ".encode()
    info += b"/CreationDate (D:20260101120000+01'00') >>\n"
    parts.append(info)
    parts.append(b"trailer\n%%EOF")
    return b"".join(parts)


def make_pdf_hex_title() -> bytes:
    """PDF s hex stringem <...> místo literalu (…)."""
    title = "Hex titulek".encode("latin-1").hex().upper()
    return (
        b"%PDF-1.7\n"
        + f"<< /Title <{title}> >>\n".encode()
        + b"%%EOF"
    )


def make_docx(
    title: str = "Prace",
    creator: str = "Miroslav Matus",
    app: str = "Microsoft Office Word",
) -> bytes:
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:dcterms="http://purl.org/dc/terms/"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{title}</dc:title>"
        f"<dc:creator>{creator}</dc:creator>"
        "<cp:lastModifiedBy>Miroslav</cp:lastModifiedBy>"
        '<dcterms:created xsi:type="dcterms:W3CDTF">2026-01-01T10:00:00Z</dcterms:created>'
        "</cp:coreProperties>"
    )
    app_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        f"<Application>{app}</Application>"
        "<Company>Farnost</Company>"
        "<Pages>3</Pages>"
        "</Properties>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("docProps/core.xml", core)
        zf.writestr("docProps/app.xml", app_xml)
    return buf.getvalue()


def _id3_frame(fid: bytes, text: str, enc: int = 0) -> bytes:
    body = bytes([enc]) + text.encode({0: "latin-1", 3: "utf-8"}[enc])
    return fid + struct.pack(">I", len(body)) + b"\x00\x00" + body


def make_id3(frames: list[tuple[bytes, str, int]] = ...) -> bytes:
    if frames is ...:
        frames = [
            (b"TIT2", "Pisne", 0),
            (b"TPE1", "Umec", 0),
            (b"TALB", "Album", 0),
            (b"TRCK", "5/12", 0),
            (b"TDRC", "2024", 0),
        ]
    payload = b"".join(_id3_frame(f, t, e) for f, t, e in frames)
    return b"ID3\x04\x00\x00" + _ss(len(payload)) + payload


def make_id3_utf8() -> bytes:
    """UTF-8 frame (enc=3) + TDRC/TYER kolize — TDRC má prioritu."""
    frames = [
        (b"TIT2", "Česká píseň", 3),
        (b"TYER", "1999", 0),
        (b"TDRC", "2024", 0),
    ]
    payload = b"".join(_id3_frame(f, t, e) for f, t, e in frames)
    return b"ID3\x04\x00\x00" + _ss(len(payload)) + payload


def _mp4_box(t: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + t + payload


def _mp4_data(text: str | bytes) -> bytes:
    p = text.encode() if isinstance(text, str) else text
    # data box: header(8) + type indikátor(4) + payload
    return struct.pack(">I", len(p) + 12) + b"data" + struct.pack(">I", 0) + p


def make_mp4(title: str = "Video titul") -> bytes:
    nam = _mp4_box(b"\xa9nam", _mp4_data(title))
    art = _mp4_box(b"\xa9ART", _mp4_data("Reziser"))
    aart = _mp4_box(b"aart", _mp4_data("Herci"))
    trkn_payload = b"\x00\x00" + struct.pack(">H", 3) + struct.pack(">H", 12)
    trkn = _mp4_box(b"trkn", _mp4_data(trkn_payload))
    ilst = _mp4_box(b"ilst", nam + art + aart + trkn)
    meta = _mp4_box(b"meta", b"\x00\x00\x00\x00" + ilst)  # FullBox v+flags
    udta = _mp4_box(b"udta", meta)
    moov = _mp4_box(b"moov", udta)
    ftyp = _mp4_box(b"ftyp", b"isom" + struct.pack(">I", 512))
    return ftyp + moov


def make_jpeg_exif() -> bytes:
    """JPEG s EXIF (Make/Model) přes PIL — volitelná závislost [meta]."""
    pytest.importorskip("PIL")
    from PIL import Image

    img = Image.new("RGB", (8, 8), "red")
    exif = img.getexif()
    exif[0x010F] = "STOPA"  # Make
    exif[0x0110] = "Cam-1"  # Model
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


# ── domain testy — čistá funkce extract_metadata ─────────────────────


class TestPdfMeta:
    def test_info_fields_and_date(self):
        from stopa.domain.file_meta import extract_metadata

        meta = extract_metadata(make_pdf(), "doc.pdf")
        assert meta["title"] == "Forenzni dokument"
        assert meta["author"] == "Miroslav Matus"
        assert meta["creator"] == "STOPA"
        assert meta["producer"] == "WeasyPrint 62"
        # PDF date D:20260101120000+01'00' → ISO 8601
        assert meta["created"] == "2026-01-01T12:00:00+01:00"

    def test_hex_string(self):
        from stopa.domain.file_meta import extract_metadata

        meta = extract_metadata(make_pdf_hex_title(), "doc.pdf")
        assert meta["title"] == "Hex titulek"

    def test_corrupt_and_empty(self):
        from stopa.domain.file_meta import extract_metadata

        assert extract_metadata(b"%PDF-1.7\n", "x.pdf") == {}  # jen magic, bez /Info
        assert extract_metadata(b"", "x.pdf") == {}


class TestOoxmlMeta:
    def test_docx_core_and_app(self):
        from stopa.domain.file_meta import extract_metadata

        meta = extract_metadata(make_docx(), "prace.docx")
        assert meta["title"] == "Prace"
        assert meta["author"] == "Miroslav Matus"  # dc:creator → author
        assert meta["modified_by"] == "Miroslav"
        assert meta["created"] == "2026-01-01T10:00:00Z"
        assert meta["application"] == "Microsoft Office Word"
        assert meta["company"] == "Farnost"
        assert meta["pages"] == "3"

    def test_plain_zip_without_props(self):
        from stopa.domain.file_meta import extract_metadata

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "hello")
        assert extract_metadata(buf.getvalue(), "x.zip") == {}


class TestId3Meta:
    def test_latin1_frames(self):
        from stopa.domain.file_meta import extract_metadata

        meta = extract_metadata(make_id3(), "song.mp3")
        assert meta["title"] == "Pisne"
        assert meta["artist"] == "Umec"
        assert meta["album"] == "Album"
        assert meta["track"] == "5/12"
        assert meta["year"] == "2024"

    def test_utf8_and_tdrc_priority(self):
        from stopa.domain.file_meta import extract_metadata

        meta = extract_metadata(make_id3_utf8(), "song.mp3")
        assert meta["title"] == "Česká píseň"
        # TDRC (moderní) má prioritu před TYER (legacy) — setdefault
        assert meta["year"] == "2024"


class TestMp4Meta:
    def test_atoms_and_trkn(self):
        from stopa.domain.file_meta import extract_metadata

        meta = extract_metadata(make_mp4(), "video.mp4")
        assert meta["title"] == "Video titul"
        assert meta["artist"] == "Reziser"
        assert meta["performer"] == "Herci"
        # trkn binární: track 3/12
        assert meta["track"] == "3/12"

    def test_corrupt(self):
        from stopa.domain.file_meta import extract_metadata

        # ftyp magic, ale poškozený box layout → {} bez výjimky
        assert extract_metadata(b"\x00\x00\x00\x14ftypisom", "x.mp4") == {}


class TestExifMeta:
    def test_pil_exif(self):
        from stopa.domain.file_meta import extract_metadata

        meta = extract_metadata(make_jpeg_exif(), "foto.jpg")
        assert meta["camera_make"] == "STOPA"
        assert meta["camera_model"] == "Cam-1"


class TestDispatchAndDiff:
    def test_unknown_format_and_empty(self):
        from stopa.domain.file_meta import extract_metadata

        assert extract_metadata(b"\x00\x01\x02\x03", "data.bin") == {}
        assert extract_metadata(b"", "nic.txt") == {}

    def test_diff_match_mismatch_missing(self):
        from stopa.domain.file_meta import diff_metadata

        a = {"title": "X", "author": "A"}
        b = {"title": "Y", "album": "B"}
        rows = {r["field"]: r for r in diff_metadata(a, b)}
        assert set(rows) == {"title", "author", "album"}  # union, seřazené
        assert rows["title"]["match"] is False
        assert rows["title"]["a"] == "X" and rows["title"]["b"] == "Y"
        assert rows["author"]["match"] is False  # chybí v b → None ≠ "A"
        assert rows["album"]["match"] is False
        # identické hodnoty → match
        same = {r for r in diff_metadata(a, a) if not r["match"]}
        assert same == set()


# ── web E2E — metadata endpoint + porovnání ──────────────────────────


@pytest.fixture()
def client(tmp_path: Path):
    from stopa.web.app import create_app

    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def meta_evidence(tmp_path: Path) -> Path:
    """Důkazová složka — PDF + DOCX (oba s metadata, rozdílné title)."""
    ev = tmp_path / "ev"
    ev.mkdir()
    (ev / "prava.pdf").write_bytes(make_pdf(title="Prava"))
    (ev / "prace.docx").write_bytes(make_docx(title="Prace"))
    return ev


def _make_case(client: TestClient, name: str = "E8 meta") -> dict:
    r = client.post("/api/cases", json={"name": name, "examiner": "Znalec"})
    assert r.status_code == 201, r.text
    return r.json()


class TestMetadataApi:
    def _ingest(self, client, evidence) -> tuple[str, dict]:
        cid = _make_case(client)["id"]
        client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
        files = {f["name"]: f for f in client.get(f"/api/cases/{cid}/files").json()}
        return cid, files

    def test_file_metadata_pdf(self, client, meta_evidence):
        cid, files = self._ingest(client, meta_evidence)
        r = client.get(f"/api/cases/{cid}/files/{files['prava.pdf']['id']}/metadata")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "prava.pdf"
        assert body["metadata"]["title"] == "Prava"
        assert body["metadata"]["author"] == "Miroslav Matus"

    def test_file_metadata_docx(self, client, meta_evidence):
        cid, files = self._ingest(client, meta_evidence)
        r = client.get(f"/api/cases/{cid}/files/{files['prace.docx']['id']}/metadata")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["metadata"]["title"] == "Prace"
        assert body["metadata"]["application"] == "Microsoft Office Word"

    def test_metadata_404(self, client):
        cid = _make_case(client)["id"]
        assert (
            client.get(f"/api/cases/{cid}/files/file-neexistuje/metadata").status_code
            == 404
        )

    def test_compare_metadata_endpoint(self, client, meta_evidence):
        cid, files = self._ingest(client, meta_evidence)
        a_id = files["prava.pdf"]["id"]
        b_id = files["prace.docx"]["id"]
        r = client.post(
            f"/api/cases/{cid}/files/compare-metadata", params={"a": a_id, "b": b_id}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["a"]["name"] == "prava.pdf"
        assert body["b"]["name"] == "prace.docx"
        rows = {row["field"]: row for row in body["diff"]}
        # title se liší → mismatch s oběma hodnotami
        assert rows["title"]["match"] is False
        assert rows["title"]["a"] == "Prava"
        assert rows["title"]["b"] == "Prace"
        # pole jen v jednom souboru → chybějící strana None (mismatch)
        assert rows["application"]["a"] is None
        assert rows["application"]["match"] is False
