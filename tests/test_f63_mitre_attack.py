"""F6.3 — MITRE ATT&CK mapping (auto-mapování IoC + heat-mapa + STIX export).

Pokrývá AK F6.3:
- ≥ 80 % ``KNOWN_ARTIFACT_TYPES`` mapováno na tactics/techniques;
- deterministická heat-mapa taktik×technik (UI payload) se vzorky artefaktů;
- export do STIX 2.1 ``intrusion-set`` bundle (validace přes stix2-validator);
- E2E: CLI ``stopa attack-map`` (json/stix, --out) a Web endpoint
  GET /api/cases/{id}/attack-map (+ ?format=stix).

Celá suite běží offline na dočasných DB; stix2 je volitelná závislost
(extras [stix]) — testy s ním používají ``pytest.importorskip``.
"""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from stopa.data.db import CaseDB
from stopa.domain.ai_grounding import KNOWN_ARTIFACT_TYPES
from stopa.domain.mitre_attack import (
    ATTACK_MAP,
    ATTACK_TACTICS,
    ATTACK_TECHNIQUES,
    ATTACK_UNMAPPED,
    build_attack_heatmap,
    map_artifact,
    to_stix_bundle_intrusion_set,
    to_stix_intrusion_set,
)

# ── integrita mapy ─────────────────────────────────────────────────────────────


def test_map_integrity_all_refs_defined():
    """Každá referovaná technika existuje v ATTACK_TECHNIQUES."""
    refs = {t for techs in ATTACK_MAP.values() for t in techs}
    assert refs, "mapa není prázdná"
    assert refs <= set(ATTACK_TECHNIQUES), (
        f"neurčené techniky: {sorted(refs - set(ATTACK_TECHNIQUES))}"
    )


def test_map_and_unmapped_disjoint_and_cover_known():
    """Mapa ∩ UNMAPPED = ∅; každý KNOWN typ je buď mapován, nebo zdůvodněn."""
    known = set(KNOWN_ARTIFACT_TYPES)
    assert not (set(ATTACK_MAP) & set(ATTACK_UNMAPPED)), "typ v obou tabulkách"
    orphans = known - set(ATTACK_MAP) - set(ATTACK_UNMAPPED)
    assert not orphans, f"KNOWN typy bez mapování ani zdůvodnění: {sorted(orphans)}"


def test_coverage_ak_at_least_80_pct():
    """AK F6.3: ≥ 80 % IoC (artifact typů) je mapováno."""
    hm = build_attack_heatmap([])
    assert hm["summary"]["coverage_pct"] >= 80.0, hm["summary"]


def test_tactic_order_follows_mitre():
    """Řádky heat-mapu = MITRE pořadí taktik (deterministický layout)."""
    hm = build_attack_heatmap([])
    assert [t["id"] for t in hm["tactics"]] == [tid for tid, _ in ATTACK_TACTICS]


def test_map_artifact_hits_and_unknown():
    hits = map_artifact("browser_history")
    assert hits and all(h["technique"] == "T1071" for h in hits)
    assert all(h["tactic"] == "TA000A" for h in hits)
    assert hits[0]["name"] == ATTACK_TECHNIQUES["T1071"][0]
    # neznámý / prázdný typ → žádné hity (žádné házené výjimky)
    assert map_artifact("neexistujici_typ") == []
    assert map_artifact("") == []


def test_every_known_type_maps_or_documented():
    """Deterministická kontrola: každý KNOWN typ buď mape, nebo je zdůvodněn."""
    for t in sorted(KNOWN_ARTIFACT_TYPES):
        hits = map_artifact(t)
        if not hits:
            assert t in ATTACK_UNMAPPED, f"{t} bez hity a bez zdůvodnění"


# ── heat-mapa ──────────────────────────────────────────────────────────────────


def _row(artifact_type: str, title: str = "t", rel_path: str | None = None) -> dict:
    return {"artifact_type": artifact_type, "title": title, "rel_path": rel_path, "details": None}


def test_heatmap_counts_and_samples_cap():
    arts = [_row("browser_history", f"stranka-{i}") for i in range(5)] + [
        _row("mem_process", "powershell.exe")
    ]
    hm = build_attack_heatmap(arts, max_samples=3)
    by_id = {t["id"]: t for t in hm["techniques"]}
    assert by_id["T1071"]["count"] == 5
    assert by_id["T1057"]["count"] == 1
    # vzorky omezené na max_samples, deterministicky (první N)
    samples = hm["cells"]["T1071"]
    assert len(samples) == 3
    assert [s["title"] for s in samples] == ["stranka-0", "stranka-1", "stranka-2"]
    s = hm["summary"]
    assert (s["artifacts_total"], s["mapped_artifacts"]) == (6, 6)


def test_heatmap_unmapped_excluded_but_counted():
    arts = [_row("browser_history"), _row("sqlite_database")]
    hm = build_attack_heatmap(arts)
    assert len(hm["techniques"]) == 1
    s = hm["summary"]
    assert (s["artifacts_total"], s["mapped_artifacts"], s["unmapped_artifacts"]) == (2, 1, 1)


def test_heatmap_empty_case():
    hm = build_attack_heatmap([])
    assert hm["techniques"] == []
    assert hm["cells"] == {}
    assert hm["summary"]["tactics_hit"] == []
    assert hm["summary"]["artifacts_total"] == 0


def test_heatmap_accepts_dict_and_object_rows():
    """Pydantic-like objekty i slovníkové řádky — stejný výsledek."""
    obj = SimpleNamespace(artifact_type="email_message", title="mail", rel_path=None, details=None)
    hm_obj = build_attack_heatmap([obj])
    hm_dict = build_attack_heatmap([_row("email_message")])
    assert [t["id"] for t in hm_obj["techniques"]] == [t["id"] for t in hm_dict["techniques"]]
    assert hm_obj["summary"]["mapped_artifacts"] == 1


def test_heatmap_deterministic():
    arts = [_row("chat_message", "a"), _row("drive_activity", "usb")]
    a, b = build_attack_heatmap(arts), json.loads(json.dumps(build_attack_heatmap(arts)))
    assert a == b


# ── STIX intrusion-set export ──────────────────────────────────────────────────


def test_intrusion_set_structure():
    hm = build_attack_heatmap([_row("browser_history"), _row("mem_process")])
    res = to_stix_intrusion_set("case-1", case_name="Případ 1", heatmap=hm)
    main, related = res["intrusion_set"], res["related_objects"]
    assert main["type"] == "intrusion-set" and main["spec_version"] == "2.1"
    assert main["id"].startswith("intrusion-set--")
    # deterministické časy (C4 — export nesmí měnit hash)
    assert main["created"] == main["modified"]
    ext = main["x-stopa"]
    assert ext["stopa_case_id"] == "case-1"
    assert ext["techniques_hit"] == 2 and ext["mapped_artifacts"] == 2
    # object_refs → přesně id příbuzných objektů (techniky + taktiky)
    ref_ids = {o["id"] for o in related}
    assert set(main["object_refs"]) <= ref_ids
    tactics = [o for o in related if "x-stopa-tactic-id" in o]
    techs = [o for o in related if "x-stopa-technique-id" in o]
    assert {t["x-stopa-tactic-id"] for t in tactics} == set(hm["summary"]["tactics_hit"])
    assert len(techs) == 2
    counts = {t["x-stopa-technique-id"]: t["x-stopa-artifacts-count"] for t in techs}
    assert counts.get("T1071") == 1 and counts.get("T1057") == 1


def test_bundle_deterministic_and_case_scoped():
    hm = build_attack_heatmap([_row("browser_history")])
    a = to_stix_bundle_intrusion_set("case-a", heatmap=hm)
    b = to_stix_bundle_intrusion_set("case-a", heatmap=hm)
    c = to_stix_bundle_intrusion_set("case-b", heatmap=hm)
    assert a == b, "stejný případ → byte-identický bundle (C4)"
    assert a != c, "jiný případ → jiný id"


def test_bundle_validates_with_stix2():
    stix2 = pytest.importorskip("stix2")  # volitelná závislost [stix]
    from stopa.domain.export import validate_stix_bundle

    hm = build_attack_heatmap(
        [_row(t) for t in ("browser_history", "mem_process", "credential", "sqlite_database")]
    )
    bundle = to_stix_bundle_intrusion_set("case-v", case_name="Validace", heatmap=hm)
    ok, detail = validate_stix_bundle(bundle)
    assert ok, f"stix2-validator: {detail}"
    stix2.parse(bundle, allow_custom=True)  # tvrdý parse bez výjimky
    doc_types = [o["type"] for o in json.loads(bundle)["objects"]]
    assert "intrusion-set" in doc_types


def test_bundle_empty_heatmap():
    """Prázdný případ → intrusion-set bez technik, validní bundle."""
    bundle = to_stix_bundle_intrusion_set("case-empty")
    doc = json.loads(bundle)
    assert len(doc["objects"]) == 1  # jen intrusion-set
    main = next(o for o in doc["objects"] if o["type"] == "intrusion-set")
    assert main["object_refs"] == []


# ── CLI E2E — stopa attack-map ────────────────────────────────────────────────


@pytest.fixture()
def case_env(tmp_path: Path, monkeypatch):
    """Case DB f63.db pod STOPA_DB_DIR s artefakty (mapovanými i ne)."""
    db_dir = tmp_path / "dbdir"
    db_dir.mkdir()
    monkeypatch.setenv("STOPA_DB_DIR", str(db_dir))

    from stopa.models import Artifact, Case, EvidenceSource

    db = CaseDB(db_dir / "f63.db")
    db.add_case(Case(id="f63", name="F63 test"))
    src = EvidenceSource(case_id="f63", kind="file", path="/tmp/f63.dat")
    db.add_source(src)

    def art(rel: str, atype: str, title: str) -> None:
        a = Artifact(
            source_id=src.id,
            rel_path=rel,
            artifact_type=atype,
            title=title,
            validation_status="extracted",
        )
        db.upsert_artifact(a)

    art("hist-1.dat", "browser_history", "stranka-a")
    art("hist-2.dat", "browser_history", "stranka-b")
    art("proc-1.dat", "mem_process", "powershell.exe")
    art("db-1.dat", "sqlite_database", "bez_techniky.db")
    db.close()
    return {"db_dir": db_dir}


def test_cli_attack_map_json_mode(case_env: dict, capsys):
    from stopa.cli import cmd_attack_map

    rc = cmd_attack_map(Namespace(case_id="f63", format="json", out=None, json=True))
    assert rc == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["ok"] is True and emitted["format"] == "json"
    assert emitted["artifacts_total"] == 4
    assert emitted["mapped_artifacts"] == 3
    assert emitted["techniques_hit"] >= 2
    assert emitted["coverage_pct"] >= 80.0


def test_cli_attack_map_human_and_stix_out(case_env: dict, tmp_path: Path, capsys):
    pytest.importorskip("stix2")  # volitelné extra [stix] — validátor (P4-1 min profil)

    from stopa.cli import cmd_attack_map

    out_file = tmp_path / "map" / "attack.json"
    rc = cmd_attack_map(
        Namespace(case_id="f63", format="stix", out=str(out_file), json=False)
    )
    assert rc == 0
    printed = capsys.readouterr().out
    assert "ATT&CK map (F6.3)" in printed and "formát stix" in printed

    payload = out_file.read_text(encoding="utf-8")
    from stopa.domain.export import validate_stix_bundle

    ok, detail = validate_stix_bundle(payload)
    assert ok, f"stix2-validator: {detail}"
    doc = json.loads(payload)
    main = next(o for o in doc["objects"] if o["type"] == "intrusion-set")
    assert main["x-stopa"]["stopa_case_id"] == "f63"


# ── Web E2E — GET /api/cases/{id}/attack-map ──────────────────────────────────


@pytest.fixture()
def client(tmp_path: Path):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    return TestClient(create_app(db_dir=tmp_path))


def _web_case_with_artifacts(client) -> str:
    r = client.post("/api/cases", json={"name": "F63 web"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]

    from stopa.models import Artifact, EvidenceSource

    db = CaseDB(client.app.state.db_dir / f"{cid}.db")  # type: ignore[attr-defined]
    src = EvidenceSource(case_id=cid, kind="file", path="/tmp/f63w.dat")
    db.add_source(src)
    for i, (rel, atype) in enumerate(
        [("h1", "browser_history"), ("p1", "mem_process"), ("d1", "sqlite_database")]
    ):
        db.upsert_artifact(
            Artifact(
                source_id=src.id,
                rel_path=f"{rel}.dat",
                artifact_type=atype,
                title=f"t{i}",
                validation_status="extracted",
            )
        )
    db.close()
    return cid


def test_web_attack_map_json(client):
    cid = _web_case_with_artifacts(client)
    r = client.get(f"/api/cases/{cid}/attack-map")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["artifacts_total"] == 3
    assert body["summary"]["mapped_artifacts"] == 2
    ids = {t["id"] for t in body["techniques"]}
    assert "T1071" in ids and "T1057" in ids
    # řádky matrice v MITRE pořadí
    tac_ids = [t["id"] for t in body["tactics"]]
    assert tac_ids == [tid for tid, _ in ATTACK_TACTICS]


def test_web_attack_map_stix_download(client):
    cid = _web_case_with_artifacts(client)
    r = client.get(f"/api/cases/{cid}/attack-map", params={"format": "stix"})
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers.get("content-disposition", "")
    doc = json.loads(r.text)
    assert doc["type"] == "bundle"
    main = next(o for o in doc["objects"] if o["type"] == "intrusion-set")
    assert main["x-stopa"]["stopa_case_id"] == cid


def test_web_attack_map_404_for_unknown_case(client):
    r = client.get("/api/cases/chybi-123/attack-map")
    assert r.status_code == 404
