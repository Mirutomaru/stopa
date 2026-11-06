"""STP-051 — File Preview (oblast G, File Intelligence).

Domain: čistá klasifikace preview nad bajty/názvem (offline).
Web E2E: TestClient + reálná case DB v tmp — PNG inline, text JSON, 415.
"""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stopa.domain.file_preview import (
    classify_preview,
    extract_text_preview,
    preview_media_type,
)

# ── binární fixture generátory (deterministické) ───────────────────────

def make_png() -> bytes:
    """Minimální 1×1 PNG (validní magic + IEND)."""
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(
            ">I", zlib.crc32(tag + data) & 0xFFFFFFFF
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw = zlib.compress(b"\x00\xff\x00\x00")
    idat = chunk(b"IDAT", raw)
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def make_jpeg() -> bytes:
    """JPEG magic (SOI + APP0 JFIF)."""
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 16


def make_mp3_id3() -> bytes:
    """MP3 s ID3v2 hlavičkou."""
    size = 4
    return b"ID3\x04\x00\x00" + bytes([(size >> 21) & 0x7F, (size >> 14) & 0x7F,
                                        (size >> 7) & 0x7F, size & 0x7F])


def make_mp4() -> bytes:
    """MP4 s ftyp boxem."""
    return struct.pack(">I", 20) + b"ftypisom" + b"\x00\x00\x02\x00" + b"isom"


def make_docx() -> bytes:
    """Minimální DOCX (ZIP s [Content_Types].xml)."""
    buf = Path("/tmp/_stp051.docx")
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("word/document.xml", "<document/>")
    data = buf.read_bytes()
    buf.unlink(missing_ok=True)
    return data


# ── domain: classify_preview ───────────────────────────────────────────

class TestClassifyPreview:
    def test_png(self):
        assert classify_preview(make_png(), "x.png") == "image"

    def test_jpeg(self):
        assert classify_preview(make_jpeg(), "foto.jpg") == "image"

    def test_mp3_id3v2(self):
        assert classify_preview(make_mp3_id3(), "hudba.mp3") == "audio"

    def test_mp4_ftyp(self):
        assert classify_preview(make_mp4(), "video.mp4") == "video"

    def test_text_by_content(self):
        assert classify_preview("ahoj světe\n".encode(), "pripominka.txt") == "text"

    def test_name_does_not_affect_classification(self):
        # .txt přípona netlačí text — rozhoduje obsah (kontrolní znaky → binárka)
        assert classify_preview(b"\x01\x02 plain-ish", "note.txt") is None

    def test_unknown_binary_none(self):
        assert classify_preview(b"\xde\xad\xbe\xef" * 8, "data.bin") is None

    def test_empty_bytes_none(self):
        assert classify_preview(b"", "prazdny.dat") is None


class TestExtractTextPreview:
    def test_short_text_not_truncated(self):
        text, truncated = extract_text_preview("krátký text".encode())
        assert text == "krátký text"
        assert truncated is False

    def test_long_text_truncated(self):
        data = ("x" * 20_000).encode()
        text, truncated = extract_text_preview(data)
        assert truncated is True
        assert len(text) == 4000

    def test_empty(self):
        text, truncated = extract_text_preview(b"")
        assert text == ""
        assert truncated is False


class TestPreviewMediaType:
    def test_image_png(self):
        assert preview_media_type("image", "x.png") == "image/png"

    def test_audio_mp3(self):
        assert preview_media_type("audio", "h.mp3") == "audio/mpeg"

    def test_video_mp4(self):
        assert preview_media_type("video", "v.mp4") == "video/mp4"


# ── web E2E ────────────────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path: Path):
    from stopa.web.app import create_app

    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def preview_evidence(tmp_path: Path) -> Path:
    ev = tmp_path / "ev"
    ev.mkdir()
    (ev / "foto.png").write_bytes(make_png())
    (ev / "pripominka.txt").write_bytes("Znalecká poznámka k souboru.\n".encode())
    (ev / "tajna.bin").write_bytes(b"\xde\xad\xbe\xef" * 32)
    return ev


def _make_case(client: TestClient, name: str = "STP-051 preview") -> dict:
    r = client.post("/api/cases", json={"name": name, "examiner": "Znalec"})
    assert r.status_code == 201, r.text
    return r.json()


class TestPreviewApi:
    def _ingest(self, client, evidence) -> tuple[str, dict]:
        cid = _make_case(client)["id"]
        client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
        files = {f["name"]: f for f in client.get(f"/api/cases/{cid}/files").json()}
        return cid, files

    def test_png_inline(self, client, preview_evidence):
        cid, files = self._ingest(client, preview_evidence)
        r = client.get(f"/api/cases/{cid}/files/{files['foto.png']['id']}/preview")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "image/png"
        assert r.content == make_png()

    def test_text_json(self, client, preview_evidence):
        cid, files = self._ingest(client, preview_evidence)
        r = client.get(f"/api/cases/{cid}/files/{files['pripominka.txt']['id']}/preview")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "Znalecká poznámka" in body["text"]
        assert body["truncated"] is False

    def test_unknown_binary_415(self, client, preview_evidence):
        cid, files = self._ingest(client, preview_evidence)
        r = client.get(f"/api/cases/{cid}/files/{files['tajna.bin']['id']}/preview")
        assert r.status_code == 415

    def test_missing_file_404(self, client):
        cid = _make_case(client)["id"]
        r = client.get(f"/api/cases/{cid}/files/neexistuje/preview")
        assert r.status_code == 404
