"""STP-021 — Performance: stream parsing velkých E01 + web Processing Monitor.

Dvě vrstvy:
1. Stream (``stream_to_raw``): byte-for-byte shoda s ``read_container``,
   progress callback s rostoucím done a správným total, neznámý typ → EwfError.
2. Web monitor: sync POST /sources (default — backward compat, stejná pole)
   + async ingest (background=true → 201 okamžitě, poll /processing až done).

Fixture kontejnerů sdílené z test_ewf_container.py (_create_e01/_create_aff4).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from test_ewf_container import _CHUNK, _create_aff4, _create_e01, requires_ewf

from stopa.data.ewf_container import EwfError, read_container, stream_to_raw

# ── 1) stream_to_raw — chunked extrakce bez akumulace celého obrazu ───────


@requires_ewf
def test_stream_e01_roundtrip(tmp_path):
    """E01 → stream_to_raw == read_container (byte-for-byte, přes 2 chunky)."""
    pattern = bytes((i * 7 + 3) & 0xFF for i in range(2 * _CHUNK + 4096))
    e01 = _create_e01(tmp_path / "img", pattern)

    dest = tmp_path / "out.img"
    written = stream_to_raw(e01, "e01", dest)

    assert written == len(pattern)
    assert dest.read_bytes() == pattern
    # konzistence s původním API (backward compat)
    assert dest.read_bytes() == read_container(e01, "e01")


@requires_ewf
def test_stream_aff4_roundtrip(tmp_path):
    """AFF4 → stream_to_raw == read_container (byte-for-byte)."""
    pattern = bytes((i * 13 + 5) & 0xFF for i in range(2 * _CHUNK + 8192))
    aff = tmp_path / "img.aff"
    _create_aff4(aff, pattern)

    dest = tmp_path / "out.img"
    written = stream_to_raw(aff, "aff4", dest)

    assert written == len(pattern)
    assert dest.read_bytes() == pattern
    assert dest.read_bytes() == read_container(aff, "aff4")


@requires_ewf
def test_stream_progress_callback(tmp_path):
    """Progress callback: done roste monotónně, finální (done, total) == velikost."""
    pattern = bytes((i * 3 + 1) & 0xFF for i in range(2 * _CHUNK + 4096))
    e01 = _create_e01(tmp_path / "img", pattern)

    calls: list[tuple[int, int]] = []
    stream_to_raw(e01, "e01", tmp_path / "out.img", progress=lambda d, t: calls.append((d, t)))

    assert calls, "progress nebyl volán"
    # done monotónně rostoucí, nikdy > total
    for i in range(1, len(calls)):
        assert calls[i][0] >= calls[i - 1][0]
        assert calls[i][0] <= calls[i][1]
    # finální stav = celá velikost obrazu
    assert calls[-1] == (len(pattern), len(pattern))


@requires_ewf
def test_stream_unknown_type_raises(tmp_path):
    """Neznámý typ kontejneru → EwfError (ne TypeError)."""
    p = tmp_path / "x.E01"
    p.write_bytes(b"EVF\t\r\n\xff\x00")
    with pytest.raises(EwfError, match="Neznámý"):
        stream_to_raw(p, "dd", tmp_path / "out.img")


# ── 2) web Processing Monitor — sync (backward compat) + async ingest ─────


@pytest.fixture()
def client(tmp_path: Path):
    import json as _json  # P0.4 — laboratorní WB režim pro tyto testy

    from stopa.web.app import create_app
    (tmp_path / "settings.json").write_text(
        _json.dumps({"wb_gate_mode": "warn_only"}), encoding="utf-8"
    )
    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def evidence(tmp_path: Path) -> Path:
    """Důkazová složka — 3 soubory (1 duplicitní obsah)."""
    ev = tmp_path / "ev"
    ev.mkdir()
    for i in range(3):
        (ev / f"soubor{i}.txt").write_text(f"obsah {i}", encoding="utf-8")
    return ev


def _make_case(client: TestClient, name: str = "STP-021 test") -> dict:
    r = client.post("/api/cases", json={"name": name, "examiner": "Znalec"})
    assert r.status_code == 201, r.text
    return r.json()


def test_sync_ingest_backward_compat(client, evidence):
    """Default sync POST /sources — stejná pole jako před STP-021 (+ job_id)."""
    case = _make_case(client)
    cid = case["id"]

    r = client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence), "profile": "forensic"})
    assert r.status_code == 201, r.text
    body = r.json()

    # backward compat pole — testy před STP-021 čtou právě tato
    assert body["files_total"] >= 3
    assert "artifacts_extracted" in body
    assert "errors" in body
    # nová pole monitoru (nepovinná pro staré klienty)
    assert body["job_id"]
    assert body["source_id"]

    # job se do registru zapsal a skončil done
    st = client.get(f"/api/cases/{cid}/processing").json()
    assert st["active"] is None  # sync už dokončený
    assert len(st["recent"]) == 1
    assert st["recent"][0]["status"] == "done"
    assert st["recent"][0]["result"]["files_total"] >= 3


def test_async_ingest_background(client, evidence):
    """background=true → 201 okamžitě (source_id=None), poll /processing až done."""
    case = _make_case(client)
    cid = case["id"]

    r = client.post(
        f"/api/cases/{cid}/sources",
        json={"path": str(evidence), "profile": "forensic", "background": True},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    # async odpověď — request nečekal na ingest
    assert body["source_id"] is None
    assert body["job_id"]
    assert body["status"] == "running"

    # poll monitoru dokud job nedokončí (timeout 30 s)
    deadline = time.time() + 30
    final = None
    while time.time() < deadline:
        st = client.get(f"/api/cases/{cid}/processing").json()
        job = st["active"] or (st["recent"][0] if st["recent"] else None)
        if job and job["status"] in ("done", "error"):
            final = job
            break
        time.sleep(0.05)

    assert final is not None, "job nedokončil do timeoutu"
    assert final["status"] == "done", f"chyba ingestu: {final.get('error')}"
    assert final["source_id"], "background thread nezapsal source do DB"
    assert final["result"]["files_total"] >= 3

    # po dokončení active=None, job v recent
    st = client.get(f"/api/cases/{cid}/processing").json()
    assert st["active"] is None
    assert st["recent"][0]["status"] == "done"


def test_processing_endpoint_empty(client):
    """Bez běhů → active=None, recent=[] (GUI polluje bezpečně)."""
    case = _make_case(client)
    st = client.get(f"/api/cases/{case['id']}/processing").json()
    assert st == {"active": None, "recent": []}
