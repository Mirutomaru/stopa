"""Testy oprav z auditu (docs/AUDIT-2026-11.md).

P1#1 — path traversal case_id (regex validace)
P1#2 — rel_path traversal + Content-Disposition RFC 5987
P1#3 — ranged read (seek+read) místo read_bytes()
P2#4 — sqlite_formatter: wrapper importuje z domain (mrtvý kód pryč)
P2#5 — db.py bez lokálních datetime importů
P2#6/7 — README sekce E-fází + LICENSE
P2#9   — verze z jednoho zdroje (importlib.metadata)
"""

from __future__ import annotations

import builtins
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path: Path):
    import json as _json  # P0.4 — laboratorní WB režim pro tyto testy

    from stopa.web.app import create_app
    (tmp_path / "settings.json").write_text(
        _json.dumps({"wb_gate_mode": "warn_only"}), encoding="utf-8"
    )
    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c, tmp_path


def _make_case(client: TestClient, name: str = "Audit test") -> dict:
    r = client.post("/api/cases", json={"name": name, "examiner": "Znalec"})
    assert r.status_code == 201, r.text
    return r.json()


def _add_source(client: TestClient, cid: str, path: Path) -> dict:
    r = client.post(f"/api/cases/{cid}/sources", json={"path": str(path), "profile": "forensic"})
    assert r.status_code == 201, r.text
    return r.json()


class TestP1CaseIdTraversal:
    def test_dots_in_case_id_rejected_400(self, client):
        """case_id s tečkami (`x..y`) — regex musí odmítnout (400, ne 404/500).

        Starlette dekoduje %2F PŘED routingem → encoded slash dorazí jako
        multi-segment (generic 404 na úrovni routingu); tečky v JEDNOM segmentu
        ale do handleru projdou — a tam je regex chytne.
        """
        c, _ = client
        r = c.get("/api/cases/x..y")
        assert r.status_code == 400
        assert "neplatné ID" in r.json()["detail"]

    def test_encoded_dotdot_not_500(self, client):
        """%2E%2E%2Fsecret — routing ho odrefluje (generic 404), nikdy ne 500."""
        c, _ = client
        assert c.get("/api/cases/%2E%2E%2Fsecret").status_code in (400, 404)

    def test_dotdot_in_delete_rejected_400(self, client):
        """DELETE s traversal ID nesmí smazat cizí DB — validace před cestou."""
        c, _ = client
        r = c.delete("/api/cases/x..y")
        assert r.status_code == 400

    def test_valid_case_id_still_works(self, client):
        """Regres: legitimní ID (case-<hex>) regex nepropadne."""
        c, _ = client
        cid = _make_case(c)["id"]
        assert c.get(f"/api/cases/{cid}").status_code == 200


class TestP1RelPathTraversalAndHeaders:
    def test_rel_path_escape_returns_404(self, client):
        """rel_path s `..` unikne kořene zdroje → 404 (soubor existuje venku)."""
        c, tmp = client
        ev = tmp / "ev"
        ev.mkdir()
        (ev / "poznamky.txt").write_text("obsah", encoding="utf-8")
        cid = _make_case(c)["id"]
        _add_source(c, cid, ev)
        fid = c.get(f"/api/cases/{cid}/files").json()[0]["id"]

        # soubor venku z kořene zdroje + rel_path ho tam ukazuje
        (tmp / "venku.txt").write_text("cizí soubor", encoding="utf-8")
        con = sqlite3.connect(tmp / f"{cid}.db")
        con.execute("UPDATE files SET rel_path = '../venku.txt' WHERE id = ?", (fid,))
        con.commit()
        con.close()

        r = c.get(f"/api/cases/{cid}/files/{fid}/hex")
        assert r.status_code == 404
        assert "uniká kořene" in r.json()["detail"]

    def test_export_content_disposition_rfc5987(self, client):
        """Český název → filename*=UTF-8''… (percent-encoded) + ASCII fallback."""
        c, tmp = client
        ev = tmp / "ev"
        ev.mkdir()
        (ev / "přímé soubor.txt").write_text("obsah", encoding="utf-8")
        cid = _make_case(c)["id"]
        _add_source(c, cid, ev)
        fid = c.get(f"/api/cases/{cid}/files").json()[0]["id"]

        r = c.get(f"/api/cases/{cid}/files/{fid}/export")
        assert r.status_code == 200
        cd = r.headers["content-disposition"]
        # RFC 5987: UTF-8 percent-encoded název v filename* (ř = %C5%99)
        assert "filename*=UTF-8''" in cd
        assert "p%C5%99%C3%ADm%C3%A9%20soubor.txt" in cd
        # ASCII fallback bez ne-ASCII znaků
        ascii_part = cd.split(";")[1].strip()  # filename="…"
        inner = ascii_part.split('"')[1]
        assert all(ch.isascii() for ch in inner)

    def test_export_header_injection_quoted_name(self, client):
        """`"` v názvu nesmí uniknout do filename= (header injection)."""
        c, tmp = client
        ev = tmp / "ev"
        ev.mkdir()
        (ev / 'weird".txt').write_text("obsah", encoding="utf-8")
        cid = _make_case(c)["id"]
        _add_source(c, cid, ev)
        fid = c.get(f"/api/cases/{cid}/files").json()[0]["id"]

        r = c.get(f"/api/cases/{cid}/files/{fid}/export")
        assert r.status_code == 200
        cd = r.headers["content-disposition"]
        # raw uvozovka z názvu nahrazena podtržítkem ve fallbacku
        assert 'filename="weird_.txt"' in cd
        assert 'weird".txt' not in cd

    def test_export_crlf_control_chars_in_name(self, client):
        """ASCII control chars (\\r\\n) v názvu → '_' (CRLF injection pryč)."""
        c, tmp = client
        ev = tmp / "ev"
        ev.mkdir()
        (ev / "evil\r\nX-Injected: 1.txt").write_text("obsah", encoding="utf-8")
        cid = _make_case(c)["id"]
        _add_source(c, cid, ev)
        fid = c.get(f"/api/cases/{cid}/files").json()[0]["id"]

        r = c.get(f"/api/cases/{cid}/files/{fid}/export")
        assert r.status_code == 200
        cd = r.headers["content-disposition"]
        # fallback filename (ASCII) nesmí obsahovat control chars ani uvozovky
        ascii_part = cd.split(";")[1].strip()  # filename="…"
        inner = ascii_part.split('"')[1]
        for ch in "\r\n\"":
            assert ch not in inner, f"control char {ch!r} unikl do headeru: {cd!r}"


class TestP1RangedRead:
    def test_ranged_read_uses_seek_and_length(self, client, monkeypatch):
        """Disková větev musí volat seek(offset) + read(length), ne read() celého souboru."""
        c, tmp = client
        ev = tmp / "ev"
        ev.mkdir()
        (ev / "poznamky.txt").write_bytes(b"A" * 1024)
        cid = _make_case(c)["id"]
        _add_source(c, cid, ev)

        from stopa.web import app as webapp

        calls: list[tuple] = []

        class FakeFH:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def seek(self, off: int):
                calls.append(("seek", off))

            def read(self, n=None):
                calls.append(("read", n))
                return b"ABCD"

        monkeypatch.setattr(builtins, "open", lambda *a, **k: FakeFH())
        rec = SimpleNamespace(source_id=1, meta_addr=None, rel_path="poznamky.txt", name="x")

        class StubDB:
            def get_source(self, sid):
                return SimpleNamespace(path=str(ev))

        data = webapp._read_file_bytes(StubDB(), rec, offset=10, length=4)
        assert data == b"ABCD"
        assert ("seek", 10) in calls
        assert ("read", 4) in calls

    def test_hex_slice_matches_source(self, client):
        """Regres: hex endpoint vrací přesný úryvek [offset : offset+length]."""
        c, tmp = client
        ev = tmp / "ev"
        ev.mkdir()
        payload = bytes(range(256)) * 4  # 1 KiB deterministických dat
        (ev / "data.bin").write_bytes(payload)
        cid = _make_case(c)["id"]
        _add_source(c, cid, ev)
        fid = c.get(f"/api/cases/{cid}/files").json()[0]["id"]

        r = c.get(f"/api/cases/{cid}/files/{fid}/hex", params={"offset": 16, "length": 32})
        assert r.status_code == 200
        body = r.json()
        # hex řádky → zpět na bajty a porovnat se slice payloadu
        got = bytearray()
        for line in body["hex"]:
            got += bytes(int(x, 16) for x in line.split("|")[0].split()[1:])
        assert bytes(got) == payload[16:48]


class TestP2Quality:
    def test_wrapper_uses_domain_row_to_artifact(self):
        """P2#4 — mrtvý kód pryč: wrapper sdílí funkci s domain."""
        import stopa.artifacts.sqlite_recover as wrapper
        import stopa.domain.sqlite_formatter as domain_fmt

        assert wrapper.row_to_artifact is domain_fmt.row_to_artifact

    def test_db_no_local_datetime_imports(self):
        """P2#5 — jediný (top-level) datetime import v db.py."""
        src = (ROOT / "src" / "stopa" / "data" / "db.py").read_text(encoding="utf-8")
        assert src.count("from datetime import") == 1

    def test_version_single_source(self, client):
        """P2#9 — app.version == stopa.__version__ a žádný hardcodovaný literal v app.py."""
        from stopa import __version__
        from stopa.web.app import create_app

        _, tmp = client
        assert create_app(db_dir=tmp).version == __version__
        src = (ROOT / "src" / "stopa" / "web" / "app.py").read_text(encoding="utf-8")
        assert '"0.1.0"' not in src and "'0.1.0'" not in src

    def test_license_exists(self):
        """P2#7 — LICENSE (MIT) v kořeni repo."""
        lic = (ROOT / "LICENSE").read_text(encoding="utf-8")
        assert lic.startswith("MIT License")

    def test_readme_covers_e_phases(self):
        """P2#6 — README popisuje E-fáze i AI asistenta, plán je aktuální."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for token in ("E1", "E6", "E7", "E11", "E12", "AI Forensic Assistant"):
            assert token in readme, f"README chybí {token}"
        # plán: FÁZE 2 (web GUI) už není „zbývá“ bez zaškrtnutí
        plan = readme.split("## Plán")[1]
        assert "✅ Web GUI" in plan
