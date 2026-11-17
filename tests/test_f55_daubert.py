"""F5.5 — Daubert challenge preparedness pack.

Pokrývá: referenční knihovnu (AK min. 20 referencí, well-formed citace), mapování
parser ID → rodiny algoritmů pro všech registrovaných parserů, vyhodnocení 4
Daubert faktorů (testovatelnost / peer-review / chybovost / obecné přijetí) s
poctivou error-rate politikou, determinismus kanonického JSON + digest a E2E —
presentation vrstva (podepsaný JSON balík + audit ``daubert_pack_generated``),
CLI `stopa daubert` (JSON i human režim, --out) a Web endpoint
GET /api/cases/{id}/daubert-pack.

Celá suite běží offline na dočasných DB.
"""

from __future__ import annotations

import json
import re
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

from stopa.data.db import CaseDB
from stopa.domain.compliance_report import canonical_json, report_digest, verify_report
from stopa.domain.daubert import (
    CORE_ALGORITHMS,
    DAUBERT_FACTORS,
    FAMILY_REFS,
    MIN_REFERENCES_AK,
    REFERENCES,
    build_daubert_pack,
    family_for_parser,
    refs_for_parser,
)

ALLOWED_REF_TYPES = {"peer_reviewed", "standard", "book", "whitepaper", "vendor_doc"}


def _pack(parsers: list[dict] | None = None, **kw: Any) -> dict:
    """Pomocný builder s fixním deterministickým vstupem."""
    defaults = {
        "case_id": "c1",
        "case_name": "C1",
        "generated_at": "2026-11-17T12:00:00+00:00",
        "stopa_version": "9.9.9",
    }
    defaults.update(kw)
    return build_daubert_pack(parsers=parsers or [], **defaults)


def _parser_record(
    pid: str, artifacts: int = 5, test_files: tuple[str, ...] = (), ref_ds=None
) -> dict:
    return {
        "parser_id": pid,
        "version": "1.0",
        "artifacts": artifacts,
        "test_files": test_files,
        "reference_dataset": ref_ds,
        "limitations": ("omezení X",),
    }


# ── doména — referenční knihovna (AK: min. 20 referencí) ─────────────────────


def test_ak_min_20_references():
    assert len(REFERENCES) >= MIN_REFERENCES_AK == 20
    payload = _pack()
    assert payload["references_total"] == len(REFERENCES)
    assert len(payload["reference_library"]) == payload["references_total"]
    # AK invariant — pod limitem builder hází (bezpečnost proti úbytku knihovny)
    with pytest.raises(ValueError, match="AK limit"):
        import stopa.domain.daubert as d

        orig = d.MIN_REFERENCES_AK
        d.MIN_REFERENCES_AK = len(REFERENCES) + 1
        try:
            _pack()
        finally:
            d.MIN_REFERENCES_AK = orig


def test_reference_library_wellformed():
    for ref in REFERENCES.values():
        assert ref.ref_id and re.fullmatch(r"[a-z0-9_]+", ref.ref_id)
        assert ref.authors.strip(), f"chybějí autoři: {ref.ref_id}"
        assert ref.title.strip(), f"chybí titulek: {ref.ref_id}"
        assert ref.venue.strip(), f"chybí venue: {ref.ref_id}"
        assert 1950 <= ref.year <= 2030, f"netypický rok: {ref.ref_id}={ref.year}"
        assert ref.ref_type in ALLOWED_REF_TYPES, f"neznámý typ: {ref.ref_id}"
    # peer-review existuje (faktor 2 není prázdná disciplína)
    assert sum(1 for r in REFERENCES.values() if r.ref_type == "peer_reviewed") >= 5


def test_family_mapping_covers_all_registry_parsers():
    from stopa.domain.validation_registry import build_registry

    registry = build_registry()
    known_families = set(FAMILY_REFS) | {"generic"}
    for pid in registry:
        fam = family_for_parser(pid)
        assert fam in known_families, f"parser {pid} → neznámá rodina {fam}"
        refs = refs_for_parser(pid)
        for r in refs:  # jen platné reference z knihovny, bez duplicit
            assert r.ref_id in REFERENCES
        assert len({r.ref_id for r in refs}) == len(refs)


# ── doména — core algoritmy + Daubert faktory ────────────────────────────────


def test_core_algorithms_structure():
    payload = _pack()
    cores = {c["name"]: c for c in payload["core_algorithms"]}
    assert len(cores) == len(CORE_ALGORITHMS) == 3
    for name, entry in cores.items():
        assert entry["role"] and entry["references"], name
        factors = entry["factors"]
        assert set(factors) == {"testability", "peer_review", "error_rate", "general_acceptance"}
        assert factors["testability"]["tested_in_lab"] is True  # CORE_TEST_FILES
    sha256 = cores["SHA-256"]
    assert any(r["ref_id"] == "fips_180_4" for r in sha256["references"])
    cdc = next(
        e for e in payload["core_algorithms"] if "CDC" in e["name"]
    )
    assert "deterministický" in (cdc["factors"]["error_rate"]["documented_value"] or "")


def test_factor_evaluation_per_parser():
    parsers = [
        _parser_record(
            "sqlite", 10, test_files=("tests/test_sqlite_extract.py",), ref_ds="ds/sqlite"
        ),
        _parser_record("some_future_parser"),
    ]
    payload = _pack(parsers=parsers)
    by_id = {p["parser_id"]: p for p in payload["case_parsers"]}

    sql = by_id["sqlite"]
    assert sql["family"] == "web_browsers"
    f = sql["factors"]
    assert f["testability"]["tested_in_lab"] is True
    assert f["peer_review"]["count"] >= 1
    assert f["error_rate"]["documented_value"] is None  # poctivost: žádná vyfabrikovaná hodnota
    assert "referenčním datasetu" in f["error_rate"]["basis"]

    unk = by_id["some_future_parser"]
    assert unk["family"] == "generic" and unk["references"] == []
    uf = unk["factors"]
    assert uf["testability"]["tested_in_lab"] is False
    assert uf["peer_review"]["count"] == 0
    assert "veřejná kvantifikace chybí" in uf["error_rate"]["basis"]


def test_error_rate_honesty():
    payload = _pack(
        parsers=[
            _parser_record("evtx"),
            _parser_record("crypto_extract", test_files=("tests/test_crypto.py",)),
        ]
    )
    for entry in payload["case_parsers"]:
        er = entry["factors"]["error_rate"]
        if er.get("documented_value") is None:
            assert er.get("basis"), "None chybovost musí nést zdůvodnění"
    # core algoritmy mají vždy dokumentovanou chybovost
    for core in payload["core_algorithms"]:
        assert core["factors"]["error_rate"].get("documented_value")


def test_coverage_counts_consistent():
    parsers = [
        _parser_record("sqlite", 3),      # peer-review reference (web_browsers)
        _parser_record("evtx", 2),        # jen book — bez peer ani standardu
        _parser_record("twitter_posts"),  # generic — žádná přímá reference
    ]
    payload = _pack(parsers=parsers)
    cov = payload["coverage"]
    assert cov["case_parsers_total"] == 3
    assert cov["with_peer_review_refs"] == 1
    assert cov["no_direct_reference"] == 1


def test_canonical_determinism_and_digest():
    a = _pack(parsers=[_parser_record("sqlite", 7)])
    b = _pack(parsers=[_parser_record("sqlite", 7)])
    ca, cb = canonical_json(a), canonical_json(b)
    assert ca == cb
    assert report_digest(ca) == report_digest(cb)
    # jiný generated_at → jiný digest (časová razítka jsou součástí payloadu)
    c = _pack(parsers=[_parser_record("sqlite", 7)], generated_at="2026-11-18T12:00:00+00:00")
    assert report_digest(canonical_json(c)) != report_digest(ca)


def test_payload_schema_and_factor_labels():
    payload = _pack()
    assert payload["schema"] == "stopa-daubert-pack/v1"
    assert [f["id"] for f in payload["daubert_factors"]] == [
        fid for fid, _ in DAUBERT_FACTORS
    ]
    assert all(f["label"] for f in payload["daubert_factors"])


# ── E2E — presentation vrstva (podepsaný balík + audit) ──────────────────────


@pytest.fixture()
def case_env(tmp_path: Path, monkeypatch):
    """Case DB f55.db pod STOPA_DB_DIR (explicitní id = jméno souboru)."""
    db_dir = tmp_path / "dbdir"
    db_dir.mkdir()
    monkeypatch.setenv("STOPA_DB_DIR", str(db_dir))
    return {"db_dir": db_dir}


def _make_case(cli_env: dict) -> CaseDB:
    from stopa.models import Case

    db = CaseDB(cli_env["db_dir"] / "f55.db")
    # explicitní id = název DB souboru (CLI `_open_db` řeší case_id přes jméno souboru)
    db.add_case(Case(id="f55", name="f55"))
    return db


def test_generate_pack_writes_file_and_audit(case_env: dict):
    from stopa.presentation.daubert import generate_daubert_pack

    db = _make_case(case_env)
    out = generate_daubert_pack(db, "f55")
    json_path: Path = out["json_path"]
    assert json_path.exists()
    doc = json.loads(json_path.read_text(encoding="utf-8"))
    payload = doc["payload"]
    assert payload["schema"] == "stopa-daubert-pack/v1"
    assert payload["case_id"] == "f55" and payload["stopa_version"]
    assert payload["references_total"] >= MIN_REFERENCES_AK
    assert set(doc["signature"]) == {"digest_sha256", "signature_b64", "public_key_b64"}
    assert re.fullmatch(r"[0-9a-f]{64}", out["digest"] or "")
    # audit log — daubert_pack_generated s digestem
    rows = db.conn.execute(
        "SELECT details_json FROM audit_log WHERE action = 'daubert_pack_generated'"
    ).fetchall()
    assert len(rows) == 1
    details = json.loads(rows[0]["details_json"])
    assert details["digest_sha256"] == out["digest"]
    db.close()


def test_sign_verify_roundtrip_e2e(case_env: dict):
    from stopa.presentation.daubert import generate_daubert_pack

    have_crypto = pytest.importorskip("cryptography") is not None
    db = _make_case(case_env)
    out = generate_daubert_pack(db, "f55", out_dir=case_env["db_dir"] / "out")
    doc = json.loads(out["json_path"].read_text(encoding="utf-8"))
    payload = doc["payload"]
    if have_crypto:
        assert out["signature_b64"], "s cryptography musí být balík podepsaný"
        ok = verify_report(payload, out["public_key_b64"], out["signature_b64"])
        assert ok is True
        # digest odpovídá kanonickému JSON payloadu (ne indentovanému souboru)
        assert report_digest(canonical_json(payload)) == out["digest"]
    else:  # graceful degradation — balík bez podpisu, ale s digestem
        assert out["signature_b64"] is None
        assert re.fullmatch(r"[0-9a-f]{64}", out["digest"])
    db.close()


# ── CLI E2E — stopa daubert (JSON + human režim) ─────────────────────────────


def test_cli_daubert_json_mode(case_env: dict, capsys):
    from stopa.cli import cmd_daubert

    _make_case(case_env).close()
    rc = cmd_daubert(Namespace(case_id="f55", out=None, json=True))
    assert rc == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["ok"] is True
    assert emitted["payload"]["references_total"] >= MIN_REFERENCES_AK
    # neexistující případ (DB soubor existuje, ale řádek v cases chybí) → exit 1 + error
    from stopa.models import Case as _Case

    gone = CaseDB(case_env["db_dir"] / "gone.db")
    gone.add_case(_Case(id="other", name="other"))
    gone.close()
    rc = cmd_daubert(Namespace(case_id="gone", out=None, json=True))
    assert rc == 1
    err = json.loads(capsys.readouterr().out)
    assert err["ok"] is False and "nenalezen" in err["error"]


def test_cli_daubert_out_dir_and_human_output(case_env: dict, capsys):
    from stopa.cli import cmd_daubert

    _make_case(case_env).close()
    out_dir = case_env["db_dir"] / "reports"
    rc = cmd_daubert(Namespace(case_id="f55", out=str(out_dir), json=False))
    assert rc == 0
    files = list(out_dir.glob("f55_daubert_*.json"))
    assert len(files) == 1, f"očekáván jeden balík, nalezeno: {files}"
    printed = capsys.readouterr().out
    assert "Daubert pack (F5.5)" in printed
    assert "Reference:" in printed and "Digest SHA-256:" in printed


# ── Web E2E — GET daubert-pack (1-click stahování) ───────────────────────────


@pytest.fixture()
def client(tmp_path: Path):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    return TestClient(create_app(db_dir=tmp_path))


def test_web_endpoint_returns_pack(client):
    r = client.post("/api/cases", json={"name": "F55"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]

    r = client.get(f"/api/cases/{cid}/daubert-pack")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    assert "attachment" in r.headers.get("content-disposition", "")
    body = r.json()
    payload = body["payload"]
    assert payload["schema"] == "stopa-daubert-pack/v1"
    assert payload["case_id"] == cid
    assert payload["references_total"] >= MIN_REFERENCES_AK
    assert set(body["signature"]) == {"digest_sha256", "signature_b64", "public_key_b64"}


def test_web_endpoint_unknown_case_404(client):
    r = client.get("/api/cases/missing-case-xyz/daubert-pack")
    assert r.status_code == 404
