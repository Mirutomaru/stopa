"""F5.2 — SWGDE / ISO 27037 automatizovaný compliance report (Compliance & Court-Readiness).

Testy: doménová logika (kanonický JSON, digest, Ed25519 sign/verify round-trip,
tamper → FAIL, deterministický HTML render) + presentation vrstva (sběr WB logů
z audit logu, AI grounding agregace, chain of custody, Merkle seal sekce F5.1,
generace podepsaného JSON+PDF, graceful degradation bez cryptography). Plně offline.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from stopa.data.db import CaseDB
from stopa.domain.compliance_report import (
    AI_ACTIONS,
    COMPLIANCE_FORMAT_VERSION,
    build_payload,
    canonical_json,
    render_html,
    report_digest,
    sign_report,
    verify_report,
)
from stopa.models import Artifact, Case, EvidenceSource

try:  # cryptography je volitelná závislost (extra 'fde') — v .venv nainstalovaná
    import cryptography  # noqa: F401

    HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    HAS_CRYPTO = False

requires_crypto = pytest.mark.skipif(not HAS_CRYPTO, reason="chybí cryptography (extra [fde])")


@pytest.fixture()
def db(tmp_path: Path) -> Iterator[CaseDB]:
    # jméno souboru == case id (konvence _open_db) — stejné jako F5.1
    d = CaseDB(tmp_path / "case-x.db")
    yield d
    d.close()


def _seed(db: CaseDB, examiner: str | None = "znalec@x.cz") -> str:
    """Případ + zdroj + 2 artifacty — vrací source_id."""
    db.add_case(Case(id="case-x", name="Test case F5.2", examiner=examiner))
    src = EvidenceSource(case_id="case-x", kind="folder", path="/tmp/x")
    db.add_source(src)
    for i in range(2):
        db.artifact_repo.upsert_artifact(
            Artifact(
                source_id=src.id,
                artifact_type="chat_message",
                rel_path=f"chat/{i}.msg",  # unikátní → upsert nededuplikuje
                title=f"msg-{i}",
            )
        )
    return src.id


def _small_payload() -> dict:
    return build_payload(
        case_id="case-x",
        case_name="Test case F5.2",
        examiner="znalec@x.cz",
        tools=[{"name": "STOPA", "version": "2.0.0"}],
        algorithms={"total_artifacts": 2, "by_status": {"extracted": 2}, "coverage": None},
        write_blockers=[],
        ai_grounding={"total_actions": 0, "tools_used": {}},
        chain_of_custody=[{"source_id": "src-1", "kind": "folder"}],
        generated_at="2026-11-17T12:00:00+00:00",
    )


class TestDomain:
    def test_canonical_json_deterministic(self) -> None:
        """Stejné data v jiném pořadí klíčů → stejné bajty (sort_keys)."""
        p1 = build_payload(
            case_id="c", case_name=None, examiner=None, tools=[{"name": "A", "version": "1"}],
            algorithms={"b": 2, "a": 1}, write_blockers=[], ai_grounding={}, chain_of_custody=[],
        )
        p2 = build_payload(
            case_id="c", case_name=None, examiner=None, tools=[{"name": "A", "version": "1"}],
            algorithms={"a": 1, "b": 2}, write_blockers=[], ai_grounding={}, chain_of_custody=[],
        )
        assert canonical_json(p1) == canonical_json(p2)

    def test_report_digest_stable(self) -> None:
        c = canonical_json(_small_payload())
        d = report_digest(c)
        assert len(d) == 64 and all(ch in "0123456789abcdef" for ch in d)
        assert report_digest(canonical_json(_small_payload())) == d

    def test_build_payload_structure(self) -> None:
        p = _small_payload()
        assert p["format_version"] == COMPLIANCE_FORMAT_VERSION == 1
        assert p["domain_tag"].startswith("stopa-compliance/")
        for section in ("case", "tools", "algorithms", "write_blockers",
                        "ai_grounding", "chain_of_custody", "merkle_seal"):
            assert section in p
        assert p["case"]["id"] == "case-x"

    @requires_crypto
    def test_sign_verify_roundtrip(self) -> None:
        from stopa.domain.integrity import generate_keypair, verify_signature

        priv_b64, pub_b64 = generate_keypair()
        payload = _small_payload()
        _digest, sig = sign_report(payload, priv_b64)
        assert verify_report(payload, pub_b64, sig) is True
        # stejná sémantika jako C4/F5.1 — podpisuje se hex digest kanonického JSON
        assert verify_signature(pub_b64, report_digest(canonical_json(payload)), sig)

    @requires_crypto
    def test_tampered_payload_fails_verify(self) -> None:
        from stopa.domain.integrity import generate_keypair

        priv_b64, pub_b64 = generate_keypair()
        payload = _small_payload()
        _, sig = sign_report(payload, priv_b64)
        tampered = json.loads(json.dumps(payload))  # hluboká kopie
        tampered["tools"][0]["version"] = "9.9.9"  # změna verze nástroje
        assert verify_report(tampered, pub_b64, sig) is False

    def test_verify_missing_keys_false(self) -> None:
        p = _small_payload()
        assert verify_report(p, None, None) is False
        assert verify_report(p, "pub", None) is False
        assert verify_report(p, None, "sig") is False

    @requires_crypto
    def test_render_html_sections_and_determinism(self) -> None:
        from stopa.domain.integrity import generate_keypair

        priv_b64, _pub = generate_keypair()
        payload = _small_payload()
        _, sig = sign_report(payload, priv_b64)
        html_doc = render_html(payload, signature_b64=sig)
        for needle in (
            "SWGDE / ISO 27037 Compliance Report",
            "case-x", "znalec@x.cz",
            "1. Nástroje a verze", "2. Validace algoritmů",
            "3. Write-blocker logy", "4. AI grounding report",
            "5. Chain of custody", "6. Integrity &amp; Merkle seal",
            "7. Podpis dokumentu (Ed25519)",
            sig,  # podpis v bloku
        ):
            assert needle in html_doc
        assert render_html(payload, signature_b64=sig) == html_doc  # deterministické


class TestPresentation:
    def test_write_blocker_rows_from_audit_log(self, db: CaseDB) -> None:
        _seed(db)
        db.log_operation("wb_attached", actor="znalec@x.cz",
                        details={"device": "Tableau T3", "write_blocker": True})
        # druhá cesta — akce bez wb_ prefixu, ale details obsahují write_blocker
        db.conn.execute(
            "INSERT INTO audit_log (ts, action, actor, details_json)"
            " VALUES ('2026-11-17T10:00:00+00:00', 'disk_imaged', 'znalec@x.cz',"
            " '{\"write_blocker\": \"sgdisk\"}')"
        )
        db.conn.commit()
        from stopa.presentation.compliance_report import _write_blocker_rows

        rows = _write_blocker_rows(db.conn)
        actions = [r["action"] for r in rows]
        assert "wb_attached" in actions and "disk_imaged" in actions
        wb_row = next(r for r in rows if r["action"] == "wb_attached")
        assert wb_row["details"]["device"] == "Tableau T3"

    def test_ai_grounding_aggregation(self, db: CaseDB) -> None:
        _seed(db)
        for tool in ("search_files", "read_file"):
            db.log_operation("ai_agent_action", actor="case_analyst",
                            details={"step": 1, "tool": tool})
        db.log_operation("nl_query", actor="nl_query", details={"case_id": "case-x"})
        assert AI_ACTIONS[:2] == ("ai_agent_action", "nl_query")
        from stopa.presentation.compliance_report import _ai_grounding_summary

        s = _ai_grounding_summary(db.conn)
        assert s["total_actions"] == 3
        assert s["tools_used"] == {"read_file": 1, "search_files": 1}

    def test_collect_includes_coc_and_case(self, db: CaseDB) -> None:
        _seed(db)
        from stopa.presentation.compliance_report import collect_compliance_data

        data = collect_compliance_data(db, "case-x")
        assert data["case_id"] == "case-x" and data["examiner"] == "znalec@x.cz"
        assert any(t["name"] == "STOPA" for t in data["tools"])
        coc = data["chain_of_custody"]
        assert len(coc) >= 1 and coc[0]["artifacts_count"] == 2
        # bez pečetí → None; po seal_case → sekce s rootem
        assert data["merkle_seal"] is None

    @requires_crypto
    def test_merkle_seal_section_after_seal(self, db: CaseDB) -> None:
        _seed(db)
        assert db.seal_case(actor="znalec@x.cz") is not None
        from stopa.presentation.compliance_report import collect_compliance_data

        data = collect_compliance_data(db, "case-x")
        seal = data["merkle_seal"]
        assert seal is not None and seal["seals_total"] == 1
        assert seal["seals_valid"] == 1 and len(seal["latest_root_hash"]) == 64

    @requires_crypto
    def test_generate_writes_signed_report(self, db: CaseDB, tmp_path: Path) -> None:
        _seed(db)
        from stopa.presentation.compliance_report import generate_compliance_report

        out = generate_compliance_report(db, "case-x", out_dir=tmp_path / "reports")
        assert out["json_path"].exists() and out["pdf_path"] is not None
        assert out["pdf_path"].exists()
        doc = json.loads(out["json_path"].read_text(encoding="utf-8"))
        payload, sig_block = doc["payload"], doc["signature"]
        assert verify_report(payload, sig_block["public_key_b64"],
                             sig_block["signature_b64"]) is True
        # audit log dostal záznam o generaci
        rows = db.conn.execute(
            "SELECT details_json FROM audit_log WHERE action='compliance_report_generated'"
        ).fetchall()
        assert len(rows) == 1 and json.loads(rows[0]["details_json"])["signed"] is True

    def test_graceful_degradation_no_cryptography(self, db: CaseDB, tmp_path: Path) -> None:
        _seed(db)

        def _raise(*_a, **_k):
            raise RuntimeError("cryptography není nainstalována")

        db.audit_repo.ensure_integrity_key = _raise  # type: ignore[method-assign]
        from stopa.presentation.compliance_report import generate_compliance_report

        out = generate_compliance_report(db, "case-x", out_dir=tmp_path / "deg")
        assert out["json_path"].exists()  # report vznikne i nepodepsaný
        assert out["signature_b64"] is None and out["digest"] is None
        doc = json.loads(out["json_path"].read_text(encoding="utf-8"))
        assert doc["signature"]["signature_b64"] is None
        rows = db.conn.execute(
            "SELECT details_json FROM audit_log WHERE action='compliance_report_generated'"
        ).fetchall()
        assert json.loads(rows[-1]["details_json"])["signed"] is False

    @pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography není nainstalována")
    def test_html_contains_seal_and_wb(self, db: CaseDB) -> None:
        """Kompletní render — WB logy + Merkle pečeť se projevují v HTML."""
        _seed(db)
        db.log_operation("wb_attached", details={"device": "Tableau T3"})
        assert db.seal_case(actor="znalec@x.cz") is not None
        from stopa.presentation.compliance_report import collect_compliance_data

        data = collect_compliance_data(db, "case-x")
        payload = build_payload(**data)
        html_doc = render_html(payload)
        assert "Tableau T3" in html_doc  # WB záznam v sekci 3
        assert "Pečetí celkem: <b>1</b>" in html_doc  # F5.1 sekce

    def test_unknown_case_raises_keyerror(self, db: CaseDB) -> None:
        _seed(db)
        from stopa.presentation.compliance_report import collect_compliance_data

        with pytest.raises(KeyError):
            collect_compliance_data(db, "case-unknown")


if __name__ == "__main__":  # rychlý lokální běh bez pytestu
    raise SystemExit(pytest.main([__file__, "-q"]))
