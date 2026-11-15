"""F3.1 — AI Tool Agent: ReAct smyčka s tool-use nad živým case DB.

AK F3.1 (ROADMAP V2, Fáze 3):
- agent vyřeší testovací případy → **s1–s10** (scripted LLM = deterministicky);
- každá akce v audit logu (append-only hash chain) → s1;
- grounding validuje 100 % citací ve finální odpovědi (fail-closed) → s2/s3.

Unit testy = jednotlivé nástroje bez LLM; integrační scénáře = celá smyčka
s injektovatelným ``FakeLLM`` (offline, bez LM Studio).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

CASE_ID = "case-f31"
SRC_ID = "src-f31"

# ── fixtures ────────────────────────────────────────────────


def _mk_file_rec(src_id: str, name: str):
    from stopa.models import FileRecord, new_id

    return FileRecord(
        id=new_id("f"),
        source_id=src_id,
        rel_path=name,
        name=name,
        size_bytes=1024,
        mtime=datetime(2026, 1, 1),  # deterministické (bez utcnow → DTZ003)
        sha256=hashlib.sha256(name.encode()).hexdigest(),
        extension="txt",
    )


def _seed_case(db, case_id: str, src_id: str) -> None:
    now = "2026-01-01T00:00:00"
    db.conn.execute(
        "INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
        (case_id, case_id.upper(), now),
    )
    db.conn.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES (?, ?, 'folder', '/tmp/f31-seed', ?)",
        (src_id, case_id, now),
    )
    db.conn.commit()


def _mk_art(source_id: str, art_type: str = "browser_history", ts=None, title: str = "T"):
    from stopa.models import Artifact

    return Artifact(
        source_id=source_id,
        artifact_type=art_type,
        timestamp=ts or datetime(2026, 1, 2),
        title=title,
    )


@pytest.fixture()
def case_db(tmp_path: Path):
    """Syntetická case DB: soubor + 2 artefakty + timeline (1 normal/1 anomálie) + entity."""
    from stopa.data.db import CaseDB
    from stopa.data.query_cache import PROCESS_CACHE

    db = CaseDB(str(tmp_path / "case-f31.db"))
    _seed_case(db, CASE_ID, SRC_ID)

    rec = _mk_file_rec(SRC_ID, "ransomware_notes.txt")
    db.upsert_file(rec)
    file_id = rec.id

    art1 = _mk_art(SRC_ID, "browser_history", datetime(2026, 1, 2, 10), "Navštěva platební stránky")
    art2 = _mk_art(SRC_ID, "chat_message", datetime(2026, 1, 3, 9), "Zpráva o zálohách")
    db.upsert_artifact(art1)
    db.upsert_artifact(art2)

    # Timeline — explicitní insert (materializace běží v pipeline; viz E2 bod 2)
    for ev_id, ts_utc, flags in [
        ("tl-normal", "2026-01-02T10:00:00+00:00", None),
        ("tl-anomaly", "2026-01-02T11:30:00+00:00", "timestomp"),
    ]:
        db.conn.execute(
            "INSERT INTO timeline_events (id, source_id, artifact_id, file_id,"
            " rel_path, event_type, ts_utc, title, anomaly_flags)"
            " VALUES (?, ?, ?, NULL, 'ransomware_notes.txt', 'browser_history', ?, 'tl', ?)",
            (ev_id, SRC_ID, art1.id if ev_id == "tl-normal" else None, ts_utc, flags),
        )
    db.conn.commit()

    # Entity + korelace (resolve_entity test)
    db.upsert_entities(
        CASE_ID,
        [
            ("email", "jane.doe@example.com", "Jane.Doe@Example.COM", None, None),
            ("phone", "+420123456789", "+420 123 456 789", None, None),
        ],
    )
    ents = {e["value"]: e["id"] for e in db.list_entities(CASE_ID)}
    db.add_correlation(
        CASE_ID,
        ents["jane.doe@example.com"],
        ents["+420123456789"],
        "same_contact",
        "confirmed",
        [{"note": "test"}],
    )

    PROCESS_CACHE.invalidate(None)  # deterministický stav sdíleného singletonu
    yield SimpleNamespace(
        db=db,
        file_id=file_id,
        art1=art1.id,
        art2=art2.id,
        ent_email=ents["jane.doe@example.com"],
    )
    PROCESS_CACHE.invalidate(None)
    db.close()


# ── scripted LLM (offline determinismus) ────────────────────


class FakeLLM:
    """Sevřená LLM — vrací skriptované ReAct JSON odpovědi po sobě."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.captured: list[list[dict[str, str]]] = []

    def __call__(self, messages, max_tokens):
        self.captured.append([dict(m) for m in messages])
        if not self.responses:
            raise AssertionError("FakeLLM: chybí skriptovaná odpověď")
        return self.responses.pop(0)


def act(action: str, params: dict | None = None) -> str:
    return json.dumps({"thought": "krok", "action": action, "params": params or {}}, ensure_ascii=False)


def fin(answer: str) -> str:
    return json.dumps({"thought": "zaver", "final_answer": answer}, ensure_ascii=False)


# ── unit testy nástrojů (bez LLM) ───────────────────────────


class TestToolsUnit:
    def test_search_fts(self, case_db):
        from stopa.intelligence.tool_agent import ToolError, _tool_search_fts

        db = case_db.db
        res = _tool_search_fts(db, CASE_ID, {"query": "ransomware"})
        assert len(res) == 1
        assert res[0]["id"] == case_db.file_id
        assert res[0]["name"] == "ransomware_notes.txt"

        with pytest.raises(ToolError):
            _tool_search_fts(db, CASE_ID, {"query": "   "})
        with pytest.raises(ToolError):
            _tool_search_fts(db, CASE_ID, {})

    def test_get_timeline_filters(self, case_db):
        from stopa.intelligence.tool_agent import _tool_get_timeline

        db = case_db.db
        all_events = _tool_get_timeline(db, CASE_ID, {"limit": 10})
        assert len(all_events) == 2
        assert {e["event_id"] for e in all_events} == {"tl-normal", "tl-anomaly"}

        anomalies = _tool_get_timeline(db, CASE_ID, {"anomalies_only": True})
        assert len(anomalies) == 1
        assert anomalies[0]["event_id"] == "tl-anomaly"
        assert anomalies[0]["anomaly_flags"] == ["timestomp"]

        window = _tool_get_timeline(
            db, CASE_ID, {"from_ts": "2026-01-03T00:00:00+00:00", "to_ts": "2026-01-04T00:00:00+00:00"}
        )
        assert window == []  # obě události jsou 2. ledna

    def test_resolve_entity(self, case_db):
        from stopa.intelligence.tool_agent import _tool_resolve_entity

        db = case_db.db
        res = _tool_resolve_entity(db, CASE_ID, {"value": "jane.doe"})
        assert len(res["matches"]) == 1
        assert res["matches"][0]["kind"] == "email"
        assert res["correlations"], "očekávám korelaci email↔phone"

        none = _tool_resolve_entity(db, CASE_ID, {"value": "zzz-neexistuje"})
        assert none["matches"] == []
        assert none["correlations"] == []

    def test_run_yara_crypto_signatures(self, case_db, tmp_path):
        from stopa.intelligence.tool_agent import ToolError, _tool_run_yara

        db = case_db.db
        content = (
            "wallet key: L4rK1yDtCWekvXuE6oXDkhw7eQjFocddzSV5bG5hpYA7R9AmCE3c\n"
            "btc: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa\n"
            "eth: 0x742d35cc6634c0532925a3b844bc454e4438f44e\n"
            "seed: abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about\n"
        )
        res = _tool_run_yara(db, CASE_ID, {"content": content})
        rules = {m["rule"] for m in res["matches"]}
        assert rules == {"wif_private_key", "btc_address", "eth_address", "bip39_seed"}

        by_rule = {m["rule"]: m for m in res["matches"]}
        assert by_rule["wif_private_key"]["line"] == 1
        assert by_rule["btc_address"]["line"] == 2
        assert by_rule["eth_address"]["line"] == 3
        assert by_rule["bip39_seed"]["fingerprint"], "očekávám fingerprint seed phrase"

        # file_path cesta + chybějící parametry
        p = tmp_path / "scan.txt"
        p.write_text("eth: 0x742d35cc6634c0532925a3b844bc454e4438f44e\n", encoding="utf-8")
        res_file = _tool_run_yara(db, CASE_ID, {"file_path": str(p)})
        assert {m["rule"] for m in res_file["matches"]} == {"eth_address"}

        with pytest.raises(ToolError):
            _tool_run_yara(db, CASE_ID, {})

    def test_generate_hypothesis_grounding(self, case_db):
        from stopa.intelligence.tool_agent import ToolError, _tool_generate_hypothesis

        db = case_db.db
        res = _tool_generate_hypothesis(
            db, CASE_ID, {"claim": "Ransomware infekce", "support": [case_db.art1]}
        )
        assert 0.1 <= res["confidence"] <= 0.9
        assert res["evidence_total_in_case"] == 2
        assert res["support"] == [case_db.art1]

        with pytest.raises(ToolError, match="ghost-art"):
            _tool_generate_hypothesis(db, CASE_ID, {"claim": "x", "against": ["ghost-art"]})


# ── integrační scénáře (AK: agent vyřeší 10/10 testovacích případů) ─────────


class TestReActScenarios:
    def test_s1_audit_log_records_every_action(self, case_db):
        """AK: každá akce v audit logu (append-only hash chain)."""
        from stopa.intelligence.tool_agent import run_tool_agent

        db = case_db.db
        llm = FakeLLM(
            [
                act("search_fts", {"query": "ransomware"}),
                act("get_timeline", {"anomalies_only": True}),
                fin("Nalezen soubor se stopami ransomwaru."),
            ]
        )
        res = run_tool_agent(llm, db, CASE_ID, "Co je v případě?", actor="f31-test")

        assert len(res.steps) == 3
        rows = db.conn.execute(
            "SELECT details_json FROM audit_log WHERE action = 'ai_agent_action' ORDER BY id"
        ).fetchall()
        assert len(rows) == 2, "každá AKCE (ne finální krok) patří do audit logu"
        steps_in_audit = sorted(json.loads(r["details_json"])["step"] for r in rows)
        assert steps_in_audit == [1, 2]

        # hash chain zůstal platný i po agentových zápisech (ChainReport.ok)
        report = db.verify_audit_chain()
        assert report.ok is True and report.rows_checked == 2
        for s in res.steps:
            if s.action is not None:
                assert s.audit_row_id is not None

    def test_s2_grounding_valid_citations_pass(self, case_db):
        """AK: grounding validuje 100 % citací — platné projdou."""
        from stopa.intelligence.tool_agent import run_tool_agent

        llm = FakeLLM(
            [fin(f"Závěr potvrzen artefaktem [art:{case_db.art1}] a souborem [file:{case_db.file_id}].")]
        )
        res = run_tool_agent(llm, case_db.db, CASE_ID, "Shrni důkazy.")

        assert res.final_answer.startswith("Závěr potvrzen")
        assert res.grounding_total == 2
        assert len(res.steps) == 1

    def test_s3_grounding_invalid_citation_fails_closed(self, case_db):
        """AK: grounding validuje 100 % citací — nevalidní = fail-closed."""
        from stopa.intelligence.tool_agent import GroundingError, run_tool_agent

        llm = FakeLLM([fin("Podle [art:ghost-art-123] je to jisté.")])
        with pytest.raises(GroundingError, match="ghost-art-123"):
            run_tool_agent(llm, case_db.db, CASE_ID, "Shrni důkazy.")

    def test_s4_max_steps_guardrail(self, case_db):
        """Smyčka bez final_answer dosáhne limitu → MaxStepsError."""
        from stopa.intelligence.tool_agent import MaxStepsError, run_tool_agent

        llm = FakeLLM([act("search_fts", {"query": "x"})] * 5)
        with pytest.raises(MaxStepsError):
            run_tool_agent(llm, case_db.db, CASE_ID, "Otázka", max_steps=3)

    def test_s5_invalid_llm_json_fails_closed(self, case_db):
        """Nevalidní JSON od LLM → ToolAgentError (auditovatelné)."""
        from stopa.intelligence.tool_agent import ToolAgentError, run_tool_agent

        llm = FakeLLM(["tohle není json"])
        with pytest.raises(ToolAgentError):
            run_tool_agent(llm, case_db.db, CASE_ID, "Otázka")

    def test_s6_unknown_tool_recovery(self, case_db):
        """Neznámý nástroj = observation s chybou; agent může opravit a dokončit."""
        from stopa.intelligence.tool_agent import run_tool_agent

        llm = FakeLLM(
            [
                act("neznamy_nastroj", {"a": 1}),
                fin(f"Hotovo, viz [file:{case_db.file_id}]."),
            ]
        )
        res = run_tool_agent(llm, case_db.db, CASE_ID, "Otázka")

        assert len(res.steps) == 2
        assert res.steps[0].action == "neznamy_nastroj"
        assert res.steps[0].observation_chars and res.steps[0].observation_chars > 0
        # audit obsahuje i krok s neznámým nástrojem (každá akce = záznam)
        rows = case_db.db.conn.execute(
            "SELECT details_json FROM audit_log WHERE action = 'ai_agent_action'"
        ).fetchall()
        assert len(rows) == 1

    def test_s7_react_step_xor_validation(self, case_db):
        """ReAct kontrakt: přesně jeden z action/final_answer."""
        from stopa.intelligence.tool_agent import ToolAgentError, run_tool_agent

        both = json.dumps(
            {"thought": "x", "action": "search_fts", "params": {}, "final_answer": "y"}
        )
        llm = FakeLLM([both])
        with pytest.raises(ToolAgentError):
            run_tool_agent(llm, case_db.db, CASE_ID, "Otázka")

    def test_s8_pii_redaction_default_on(self, case_db):
        """STP-019: PII (e-mail) v messages před LLM je zmaskovaná."""
        from stopa.intelligence.tool_agent import run_tool_agent

        llm = FakeLLM([fin("Hotovo.")])
        run_tool_agent(
            llm, case_db.db, CASE_ID, "Kontakt mirda@example.cz byl v pozadí?"
        )
        for batch in llm.captured:
            for msg in batch:
                assert "mirda@example.cz" not in msg["content"]

    def test_s9_markdown_fence_tolerance(self, case_db):
        """LLM obalí JSON do markdown fence — runtime to zvládne."""
        from stopa.intelligence.tool_agent import run_tool_agent

        fenced = "```json\n" + act("search_fts", {"query": "ransomware"}) + "\n```"
        llm = FakeLLM(
            [
                fenced,
                fin(f"Soubor nalezen: [file:{case_db.file_id}]."),
            ]
        )
        res = run_tool_agent(llm, case_db.db, CASE_ID, "Najdi ransomware poznámky.")

        assert len(res.steps) == 2
        assert res.final_answer.endswith("]") or "file:" in res.final_answer

    def test_s10_ransomware_case_end_to_end(self, case_db):
        """Flagová scénář: agent řeší celý případ (4 kroky + hypotéza)."""
        from stopa.intelligence.tool_agent import run_tool_agent

        llm = FakeLLM(
            [
                act("search_fts", {"query": "ransomware"}),
                act("get_timeline", {"anomalies_only": True}),
                act(
                    "generate_hypothesis",
                    {
                        "claim": "Ransomware infekce potvrzena anomáliemi v timeline",
                        "support": [case_db.art1],
                    },
                ),
                fin(
                    f"Detekována ransomware infekce: [art:{case_db.art1}] + "
                    f"[file:{case_db.file_id}]. Anomálie timestomp v timeline."
                ),
            ]
        )
        res = run_tool_agent(llm, case_db.db, CASE_ID, "Byl počítač napaden ransomwarem?")

        assert len(res.steps) == 4
        assert res.llm_calls == 4
        assert res.grounding_total == 2
        # audit: 3 akce (hypotéza včetně), finální krok ne
        rows = case_db.db.conn.execute(
            "SELECT details_json FROM audit_log WHERE action = 'ai_agent_action' ORDER BY id"
        ).fetchall()
        assert [json.loads(r["details_json"])["tool"] for r in rows] == [
            "search_fts",
            "get_timeline",
            "generate_hypothesis",
        ]
