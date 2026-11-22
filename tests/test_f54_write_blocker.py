"""F5.4 — Write-blocker integration API.

Pokrývá: doménovou auto-detekci 3 vendorů, výpočet WB stavu z audit záznamů
(wb_* akce), konfigurovatelnou ingest bránu (ingest_gate), data vrstvu
(WriteBlockerRepository) a E2E — CLI `stopa wb status/attach/remove` + gate v
`stopa add` (exit kódy 0/2, settings.json require_write_blocker) a Web API
(GET write-blocker, POST attach/remove, ingest 409 při zapnuté bráně).

Celá suite běží offline na dočasných DB.
"""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from stopa.data.db import CaseDB
from stopa.domain.write_blocker import (
    ACTION_ATTACHED,
    ACTION_REMOVED,
    VENDORS,
    compute_state,
    detect_write_blocker,
    ingest_gate,
    known_vendor_ids,
    vendor_label,
)

# ── doména — auto-detekce 3 vendorů (AK F5.4) ────────────────────────────────


@pytest.mark.parametrize(
    ("text", "vendor_id"),
    [
        ("Tableau TBW-100", "tableau"),
        ("Tableau Technology write blocker", "tableau"),
        ("WiebeTech Ridgeline 2 USB3", "wiebtech"),
        ("Ridgeline Commando", "wiebtech"),
        ("Kroll Ontrack Metalink Pro", "kroll_ontrack"),
        ("Metalink Compact v4", "kroll_ontrack"),
    ],
)
def test_detect_all_three_vendors(text: str, vendor_id: str):
    m = detect_write_blocker(text)
    assert m is not None
    assert m.vendor_id == vendor_id


@pytest.mark.parametrize("text", [None, "", "   ", "/dev/sda", "Samsung SSD 870"])
def test_detect_unknown_device_returns_none(text: str | None):
    assert detect_write_blocker(text) is None


def test_detect_is_case_insensitive():
    m = detect_write_blocker("TABLEAU tbw-200")
    assert m is not None and m.vendor_id == "tableau"


def test_vendor_registry_shape():
    ids = known_vendor_ids()
    assert len(ids) == 3  # AK: auto-detekce 3 vendorů
    for v in VENDORS:
        assert v.label and v.patterns
    assert vendor_label("wiebtech") == "WiebeTech"
    assert vendor_label(None) is None
    assert vendor_label("unknown") is None


# ── doména — stav z audit záznamů + ingest brána ─────────────────────────────

def _rec(action: str, details: dict | None = None, ts: str = "t", actor=None) -> dict:
    return {"action": action, "details": details or {}, "ts": ts, "actor": actor}


def test_compute_state_empty_returns_none():
    assert compute_state([]) is None


def test_compute_state_attach_then_remove_then_reattach():
    recs = [
        _rec(ACTION_ATTACHED, {"vendor": "tableau", "device": "TBW-100"}, ts="t1"),
        _rec(ACTION_REMOVED, {"reason": "servis"}, ts="t2"),
        _rec(ACTION_ATTACHED, {"vendor": "wiebtech", "product": "Ridgeline 2"}, ts="t3"),
    ]
    st = compute_state(recs[:1])
    assert st is not None and st["attached"] is True and st["vendor"] == "tableau"
    st = compute_state(recs[:2])
    assert st is not None and st["attached"] is False and st["reason"] == "servis"
    st = compute_state(recs)
    assert st is not None and st["attached"] is True
    assert st["vendor"] == "wiebtech" and st["ts"] == "t3"


def test_ingest_gate_matrix():
    attached = {"attached": True, "vendor": "tableau"}
    removed = {"attached": False, "reason": None}
    # WB připojen → vždy allowed bez varování
    for require in (False, True):
        g = ingest_gate(attached, require)
        assert g.allowed is True and g.warning is None
    # chybí + gate OFF → měkké varování, ale allowed
    g = ingest_gate(None, False)
    assert g.allowed is True and g.warning
    # chybí + gate ON → hard blokování
    g = ingest_gate(None, True)
    assert g.allowed is False and "brána zapnutá" in (g.warning or "")
    # odebrán + gate ON → také blokuje
    g = ingest_gate(removed, True)
    assert g.allowed is False


# ── data — WriteBlockerRepository ────────────────────────────────────────────

@pytest.fixture()
def case_db(tmp_path: Path):
    db = CaseDB(tmp_path / "f54.db")
    from stopa.models import Case

    db.add_case(Case(name="f54"))
    yield db
    db.close()


def test_repo_attach_latest_state_roundtrip(case_db: CaseDB):
    from stopa.data.write_blocker_repository import WriteBlockerRepository

    repo = WriteBlockerRepository(case_db.conn, case_db.audit_repo)
    assert repo.latest_state() is None  # žádné wb_* záznamy
    row_id = repo.attach(
        vendor="tableau", product="TBW-100", device="/dev/sdb2", notes="test"
    )
    assert row_id > 0
    st = repo.latest_state()
    assert st is not None and st["attached"] is True
    assert st["vendor"] == "tableau" and st["product"] == "TBW-100"
    assert st["device"] == "/dev/sdb2"
    hist = repo.history()
    assert len(hist) == 1
    assert hist[0]["action"] == ACTION_ATTACHED
    assert hist[0]["details"]["vendor"] == "tableau"


def test_repo_remove_semantics_and_history_order(case_db: CaseDB):
    from stopa.data.write_blocker_repository import WriteBlockerRepository

    repo = WriteBlockerRepository(case_db.conn, case_db.audit_repo)
    repo.attach(vendor="kroll_ontrack", device="Metalink Pro")
    repo.remove(reason="hotelní servis")
    st = repo.latest_state()
    assert st is not None and st["attached"] is False
    assert st["reason"] == "hotelní servis"
    hist = repo.history()
    assert [h["action"] for h in hist] == [ACTION_ATTACHED, ACTION_REMOVED]


# ── CLI E2E — stopa wb status/attach/remove + gate v add ─────────────────────

@pytest.fixture()
def cli_env(tmp_path: Path, monkeypatch):
    """Case DB f54.db pod STOPA_DB_DIR + malý textový zdroj ke zpracování."""
    db_dir = tmp_path / "dbdir"
    db_dir.mkdir()
    monkeypatch.setenv("STOPA_DB_DIR", str(db_dir))
    src_file = tmp_path / "note.txt"
    src_file.write_text("důkazní soubor\n", encoding="utf-8")
    return {"db_dir": db_dir, "src_file": src_file}


def _make_case(cli_env: dict) -> CaseDB:
    from stopa.models import Case

    db = CaseDB(cli_env["db_dir"] / "f54.db")
    # explicitní id = název DB souboru (CLI `_open_db` řeší case_id přes jméno souboru;
    # FK sources.case_id → cases.id musí sedět)
    db.add_case(Case(id="f54", name="f54"))
    return db


def test_cli_wb_status_exit_codes(cli_env: dict):
    from stopa.cli import cmd_wb_attach, cmd_wb_status

    _make_case(cli_env)  # vytvoří f54.db (zavřít pro čisté CLI otevření)
    # P0.4: settings chybí = forenzní profil → fail-closed výchozí (WB chybí → blokováno)
    rc = cmd_wb_status(Namespace(case_id="f54", json=True))
    assert rc == 2
    # legacy F5.4 konfigurace zůstává validní — explicitní False = laboratorní warn_only
    (cli_env["db_dir"] / "settings.json").write_text(
        json.dumps({"require_write_blocker": False}), encoding="utf-8"
    )
    rc = cmd_wb_status(Namespace(case_id="f54", json=True))
    assert rc == 0  # warn_only + WB chybí → allowed (měkké varování)
    # zapnout bránu přes settings.json
    (cli_env["db_dir"] / "settings.json").write_text(
        json.dumps({"require_write_blocker": True}), encoding="utf-8"
    )
    rc = cmd_wb_status(Namespace(case_id="f54", json=True))
    assert rc == 2  # gate ON + WB chybí → blokováno
    # připojení WB rozblokuje
    rc = cmd_wb_attach(
        Namespace(case_id="f54", device="Tableau TBW-100", vendor=None, product=None,
                  notes=None, json=True)
    )
    assert rc == 0
    rc = cmd_wb_status(Namespace(case_id="f54", json=True))
    assert rc == 0


def test_cli_wb_attach_auto_detection_and_audit_row(cli_env: dict):
    from stopa.cli import cmd_wb_attach

    db = _make_case(cli_env)
    # auto-detekce vendoru z device stringu (bez --vendor)
    rc = cmd_wb_attach(
        Namespace(case_id="f54", device="WiebeTech Ridgeline", vendor=None, product=None,
                  notes=None, json=True)
    )
    assert rc == 0
    rows = db.conn.execute(
        "SELECT details_json FROM audit_log WHERE action = 'wb_attached'"
    ).fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0]["details_json"])["vendor"] == "wiebtech"
    # neznámé zařízení bez explicitního vendoru → exit 2
    rc = cmd_wb_attach(
        Namespace(case_id="f54", device="/dev/sda", vendor=None, product=None,
                  notes=None, json=True)
    )
    assert rc == 2
    # explicitní --vendor zálohuje selhanou detekci
    rc = cmd_wb_attach(
        Namespace(case_id="f54", device="/dev/sda", vendor="kroll_ontrack", product=None,
                  notes=None, json=True)
    )
    assert rc == 0
    db.close()


def test_cli_add_gate_blocks_ingest(cli_env: dict):
    from stopa.cli import cmd_add, cmd_wb_attach

    _make_case(cli_env)
    (cli_env["db_dir"] / "settings.json").write_text(
        json.dumps({"require_write_blocker": True}), encoding="utf-8"
    )
    args = Namespace(
        case_id="f54", profile="quick", paths=[str(cli_env["src_file"])],
        hash_set=None, workers=1, pool="threads",
    )
    rc = cmd_add(args)  # gate ON + WB chybí → blokováno (žádný ingest)
    assert rc == 2
    db = CaseDB(cli_env["db_dir"] / "f54.db")
    assert not db.list_sources("f54")  # zdroj se nepřidal
    db.close()
    rc = cmd_wb_attach(
        Namespace(case_id="f54", device="Metalink Pro", vendor=None, product=None,
                  notes=None, json=True)
    )
    assert rc == 0
    rc = cmd_add(args)  # WB připojen → ingest proběhne
    assert rc == 0


# ── Web E2E — GET/POST write-blocker + ingest 409 ────────────────────────────

@pytest.fixture()
def client(tmp_path: Path):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    return TestClient(create_app(db_dir=tmp_path))


def _create_case(client) -> str:
    r = client.post("/api/cases", json={"name": "F54"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_web_wb_endpoints(client):
    cid = _create_case(client)
    r = client.get(f"/api/cases/{cid}/write-blocker")
    assert r.status_code == 200
    body = r.json()
    # P0.4: settings chybí = forenzní profil → fail-closed výchozí (WB chybí → blokováno)
    assert body["state"] is None and body["allowed"] is False and body["require_wb"] is True
    assert body["mode"] == "fail_closed" and body["protection_class"] == "unknown"
    assert len(body["vendors"]) == 3

    # attach — auto-detekce z device stringu
    r = client.post(
        f"/api/cases/{cid}/write-blocker/attach",
        json={"device": "Kroll Ontrack Metalink Pro"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["vendor"] == "kroll_ontrack"
    assert r.json()["detected_from_device"] is True

    body = client.get(f"/api/cases/{cid}/write-blocker").json()
    assert body["state"]["attached"] is True
    assert body["state"]["vendor"] == "kroll_ontrack"
    assert len(body["history"]) == 1

    # neznámé zařízení bez vendoru → 400
    r = client.post(f"/api/cases/{cid}/write-blocker/attach", json={"device": "/dev/sda"})
    assert r.status_code == 400

    # remove → stav attached=False
    r = client.post(
        f"/api/cases/{cid}/write-blocker/remove", json={"reason": "servis"}
    )
    assert r.status_code == 200, r.text
    body = client.get(f"/api/cases/{cid}/write-blocker").json()
    # P0.4: odebráný WB = neověřený zdroj → fail-closed blokuje ingest
    assert body["state"]["attached"] is False and body["allowed"] is False
    assert body["protection_class"] == "unknown"


def test_web_ingest_409_when_gate_on(client, tmp_path: Path):
    cid = _create_case(client)
    src = tmp_path / "src.txt"
    src.write_text("obsah\n", encoding="utf-8")

    # default (gate OFF) → ingest proběhne i bez WB
    r = client.post(
        f"/api/cases/{cid}/sources", json={"path": str(src), "profile": "quick"}
    )
    assert r.status_code == 201, r.text

    # zapnout bránu + odebrat WB (nebo nový případ) → 409
    cid2 = _create_case(client)
    src2 = tmp_path / "src2.txt"
    src2.write_text("obsah\n", encoding="utf-8")
    r = client.put("/api/settings", json={"require_write_blocker": True})
    assert r.status_code == 200 and r.json()["require_write_blocker"] is True
    try:
        r = client.post(
            f"/api/cases/{cid2}/sources", json={"path": str(src2), "profile": "quick"}
        )
        assert r.status_code == 409
        # připojení WB rozblokuje ingest
        r = client.post(
            f"/api/cases/{cid2}/write-blocker/attach", json={"device": "Tableau TBW-100"}
        )
        assert r.status_code == 201, r.text
        r = client.post(
            f"/api/cases/{cid2}/sources", json={"path": str(src2), "profile": "quick"}
        )
        assert r.status_code == 201, r.text
    finally:
        # zpět na default pro ostatní testy (settings.json je per db_dir)
        client.put("/api/settings", json={"require_write_blocker": False})
