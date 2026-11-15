"""F3.4 — Generování právních dokumentů (Forensic Methodology Report,
Chain of Custody Affidavit, Expert Witness Summary Daubert/SWGDE).

AK F3.4 (ROADMAP V2, Fáze 3):
- **3 šablony** → parametrizovaný test generuje všechny tři z case DB;
- **generování < 30 s** → měřený test pro každý dokument (ms v praxi);
- **právní review (lidský)** → explicitní sekce „Právní review“ v každé šabloně;
- **Ed25519 podpis dokumentu** → sign/verify round-trip + tamper detekce +
  graceful degradation bez balíku ``cryptography``.

LLM je injektovatelná (``llm_call(prompt) -> str`` pro narrative sekce);
offline testy s FakeLLM i s deterministickým fallbackem (bez LLM).
"""

from __future__ import annotations

import dataclasses
import hashlib
import time
from datetime import datetime
from pathlib import Path

import pytest

from stopa.domain import integrity
from stopa.intelligence.legal_docs import (
    LEGAL_DOC_TYPES,
    LegalDocError,
    generate_legal_doc,
    verify_legal_doc,
)

CASE_ID = "case-f34"
SRC_ID = "src-f34"


# ── stavba case DB ───────────────────────────────────────────────────


def _fresh_db(root: Path):
    from stopa.data.db import CaseDB

    db = CaseDB(str(root / f"legal_{Path(__file__).stem}.db"))
    now = "2026-01-01T00:00:00"
    db.conn.execute(
        "INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
        (CASE_ID, CASE_ID.upper(), now),
    )
    db.conn.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES (?, ?, 'folder', '/tmp/f34-seed', ?)",
        (SRC_ID, CASE_ID, now),
    )
    db.conn.commit()
    return db


def seed(db):
    """Syntetický případ: 4 soubory / 3 artefakty / entity / timeline + audit."""
    import hashlib as _h

    from stopa.models import Artifact, FileRecord, new_id

    def file(rel_path: str) -> None:
        name = rel_path.rsplit("/", 1)[-1]
        rec = FileRecord(
            id=new_id("f"),
            source_id=SRC_ID,
            rel_path=rel_path,
            name=name,
            size_bytes=4096,
            mtime=datetime(2026, 1, 3),
            sha256=_h.sha256(rel_path.encode()).hexdigest(),
            extension=name.rsplit(".", 1)[-1] if "." in name else "",
        )
        db.upsert_file(rec)

    file("docs/report.pdf")
    file("data/backup.zip")
    file("mail/invoice.eml")
    file("notes/meeting.txt")

    def art(artifact_type: str, title: str = "") -> None:
        a = Artifact(
            source_id=SRC_ID,
            artifact_type=artifact_type,
            timestamp=datetime(2026, 1, 5, 12),
            title=title,
            details={},
            rel_path=f"f34/{artifact_type}/{new_id('art')}",
        )
        db.upsert_artifact(a)

    art("antiforensics/timestomping", "mtime predates ctime")
    art("network/ioc", "IoC c2_beaconing — interval 30 s")
    art("crypto_wallet", "BTC address bc1q... detected")

    db.upsert_entities(
        CASE_ID, [("email", "mirdamatus@gmail.com", "mirdamatus@gmail.com", None, None)]
    )
    db.conn.execute(
        "INSERT INTO timeline_events (id, source_id, artifact_id, file_id,"
        " rel_path, event_type, ts_utc, title, anomaly_flags)"
        " VALUES ('tl-f34-1', ?, NULL, NULL, 'f34/x.bin', 'browser_history',"
        " '2026-01-05T13:00:00+00:00', 'tl timestomp', 'timestomp')",
        (SRC_ID,),
    )
    db.conn.commit()

    # řetěz úlohy — explicitní operace do append-only audit logu
    db.log_operation("source_added", actor="ingest", details={"path": "/tmp/f34-seed"})
    db.log_operation("file_extracted", actor="parser", details={"count": 4})
    db.log_operation("artifact_ingested", actor="pipeline", details={"count": 3})


@pytest.fixture()
def db(tmp_path):
    d = _fresh_db(tmp_path)
    seed(d)
    yield d
    d.close()


class FakeLLM:
    """Deterministická LLM pro narrative sekce — vrací marker text."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.text


# ── AK: 3 šablony + < 30 s + Ed25519 podpis ───────────────────────────


@pytest.mark.parametrize("doc_type", LEGAL_DOC_TYPES)
def test_ak_all_three_templates_generate(db, doc_type):
    res = generate_legal_doc(db, CASE_ID, doc_type)
    assert res.doc_type == doc_type
    assert len(res.body_markdown) > 200, "dokument podezřele krátký"
    # kanonický hash odpovídá podepsanému obsahu (bez integritního bloku)
    assert hashlib.sha256(res.signed_content.encode()).hexdigest() == res.sha256_hex
    # Ed25519 podpis klíčem případu + nezávislé ověření
    assert res.signature_b64 is not None, "chybí Ed25519 podpis"
    assert res.public_key_b64 is not None
    assert verify_legal_doc(res) is True
    # integritní blok v dokumentu
    assert "Integrita dokumentu" in res.body_markdown
    assert res.sha256_hex in res.body_markdown
    # právní review = lidský krok (AK) — explicitní sekce
    assert "Právní review" in res.body_markdown


def test_ak_generation_under_30_seconds(db):
    llm = FakeLLM("AI generovaný text pro rychlostní test.")
    for doc_type in LEGAL_DOC_TYPES:
        t0 = time.monotonic()
        res = generate_legal_doc(db, CASE_ID, doc_type, llm_call=llm)
        elapsed = time.monotonic() - t0
        assert verify_legal_doc(res) is True
        assert elapsed < 30.0, f"{doc_type}: generování {elapsed:.2f} s ≥ 30 s"


# ── obsah šablon ──────────────────────────────────────────────────────


def test_methodology_lists_artifact_types(db):
    res = generate_legal_doc(db, CASE_ID, "forensic_methodology")
    assert "`antiforensics/timestomping`" in res.body_markdown
    assert "`crypto_wallet`" in res.body_markdown
    assert str(res.stats["artifacts"]) == "3"


def test_custody_chain_contains_audit_operations(db):
    res = generate_legal_doc(db, CASE_ID, "chain_of_custody")
    for action in ("source_added", "file_extracted", "artifact_ingested"):
        assert action in res.body_markdown, f"chybí operace {action} v řetězu úlohy"
    assert "ingest" in res.body_markdown  # actor z audit logu
    assert res.stats["audit_rows"] >= 3


def test_expert_witness_daubert_and_anomalies(db):
    res = generate_legal_doc(db, CASE_ID, "expert_witness")
    assert "Daubert" in res.body_markdown
    assert "SWGDE" in res.body_markdown
    assert "`timestomp`" in res.body_markdown  # anomálie z timeline


# ── LLM narrative + fallback ──────────────────────────────────────────


def test_llm_narrative_injected(db):
    llm = FakeLLM("AI-NAZOR-MARKER unikátní text experta.")
    res = generate_legal_doc(db, CASE_ID, "expert_witness", llm_call=llm)
    assert "AI-NAZOR-MARKER" in res.body_markdown
    assert len(llm.calls) >= 1


def test_deterministic_fallback_without_llm(db):
    res = generate_legal_doc(db, CASE_ID, "forensic_methodology")  # llm_call=None
    assert "deterministickými STOPA parsery" in res.body_markdown
    assert verify_legal_doc(res) is True


def test_llm_failure_falls_back_to_template(db):
    def broken(prompt: str) -> str:
        raise RuntimeError("LM Studio offline")

    res = generate_legal_doc(db, CASE_ID, "forensic_methodology", llm_call=broken)
    assert "deterministickými STOPA parsery" in res.body_markdown
    assert verify_legal_doc(res) is True


# ── podpis: tamper detekce + graceful degradation ─────────────────────


def test_tampered_body_fails_verification(db):
    res = generate_legal_doc(db, CASE_ID, "chain_of_custody")
    # tampering v těle dokumentu (před integritním blokem) → neověřeno
    tampered = dataclasses.replace(
        res, body_markdown=res.body_markdown.replace("Prohlášení", "PROHLÁŠENÍ")
    )
    assert verify_legal_doc(tampered) is False


def test_graceful_degradation_without_cryptography(db, monkeypatch):
    def no_crypto(*a, **kw):
        raise RuntimeError("Ed25519 vyžaduje balík 'cryptography'")

    monkeypatch.setattr(integrity, "sign_hash", no_crypto)
    res = generate_legal_doc(db, CASE_ID, "forensic_methodology")
    assert res.signature_b64 is None
    assert "nepodepsáno" in res.body_markdown
    # nepodepsaný dokument ≠ ověřený (ale obsah je konzistentní)
    assert verify_legal_doc(res) is False


# ── chybové cesty ──────────────────────────────────────────────────────


def test_unknown_doc_type(db):
    with pytest.raises(LegalDocError, match="neznámý typ"):
        generate_legal_doc(db, CASE_ID, "notarial_deed")


def test_missing_case(db):
    with pytest.raises(LegalDocError, match="případ nenalezen"):
        generate_legal_doc(db, "case-neexistuje", "chain_of_custody")
