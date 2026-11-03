"""STP-019 — PII redaktor pro LLM prompty (unit + E2E s mockovaným LM Studio).

Vrstvy:
- ``domain/pii_redaction.py`` — čistá logika (redact_text/redact_messages/mask_*)
- I1 orchestrátor — ``build_prompt``/``orchestrate`` s parametrem ``redact_pii``
- E11 buildery — maskování promptů ve všech třech režimech
- web E2E — TestClient + fake LmStudioClient: PII je zmaskovaná PŘED chat()
  a auditní záznam (model name + hash promptu) se dostane do analysis_operations.

Žádná síť: LM Studio je nahrazeno (stejný vzor jako test_e11.py).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest
from test_e11 import CASE_ID, ai_case_db, ai_client  # noqa: F401  (fixture sdílené z E11)

from stopa.domain.pii_redaction import (
    PiiDetection,
    mask_email,
    mask_phone,
    redact_messages,
    redact_text,
)

# ════════════════════════════════════════════════════════════════
# domain — čistá logika
# ════════════════════════════════════════════════════════════════

class TestMaskHelpers:
    def test_mask_phone_keeps_prefix_and_suffix(self):
        assert mask_phone("+420777123456") == "+420****3456"

    def test_mask_email_keeps_first_char_and_domain(self):
        assert mask_email("jan.novak@example.com") == "j***@example.com"


class TestRedactText:
    def test_phone_masked_with_detection(self):
        out, dets = redact_text("Zavolejte +420 777 123 456 zítra.")
        assert "+420****3456" in out
        assert "+420 777 123 456" not in out
        assert len(dets) == 1
        assert dets[0].kind == "phone"
        assert dets[0].raw == "+420 777 123 456"

    def test_email_masked(self):
        out, dets = redact_text("Napište na jan.novak@example.com")
        assert "j***@example.com" in out
        assert "jan.novak@" not in out
        assert [d.kind for d in dets] == ["email"]

    def test_whatsapp_jid_masked_once(self):
        # JID obsahuje telefon — priorita zajistí, že se maskuje jednou (jid)
        out, dets = redact_text("WhatsApp: +420777123456@c.us")
        assert "wa:+420****3456" in out
        assert len(dets) == 1 and dets[0].kind == "jid"

    def test_handle_masked(self):
        out, dets = redact_text("Kontakt skype:jan.novak")
        assert "skype:j***" in out
        assert [d.kind for d in dets] == ["handle"]

    def test_no_pii_unchanged(self):
        text = "Soubor report.pdf má 3 MB a je podepsaný."
        out, dets = redact_text(text)
        assert out == text and dets == []

    def test_bare_digits_without_separator_not_masked(self):
        # konzervativně: bez +/00 prefixu a oddělovače → ne telefon
        out, dets = redact_text("ID záznamu 123456789 v databázi.")
        assert "123456789" in out
        assert dets == []

    def test_multiple_pii_in_order(self):
        text = "+420 777 123 456 a jan.novak@example.com a skype:jan.novak"
        _, dets = redact_text(text)
        assert [d.kind for d in dets] == ["phone", "email", "handle"]

    def test_deterministic(self):
        text = "+420 777 123 456 / jan.novak@example.com"
        a, da = redact_text(text)
        b, db_ = redact_text(text)
        assert (a, da) == (b, db_)

    def test_detection_fields(self):
        _, dets = redact_text("jan.novak@example.com")
        det: PiiDetection = dets[0]
        assert det.raw == "jan.novak@example.com"
        assert det.masked == "j***@example.com"


class TestRedactMessages:
    def test_all_messages_redacted(self):
        msgs = [
            {"role": "system", "content": "Role s e-mailem jan.novak@example.com"},
            {"role": "user", "content": "Telefon +420 777 123 456"},
        ]
        out, dets = redact_messages(msgs)
        assert "j***@example.com" in out[0]["content"]
        assert "+420****3456" in out[1]["content"]
        assert len(dets) == 2

    def test_roles_preserved(self):
        msgs = [{"role": "user", "content": "x"}]
        out, _ = redact_messages(msgs)
        assert [m["role"] for m in out] == ["user"]


# ════════════════════════════════════════════════════════════════
# I1 orchestrátor — parametr redact_pii
# ════════════════════════════════════════════════════════════════

class TestOrchestratorRedaction:
    def _ctx(self):
        from stopa.intelligence.case_context import CaseContext

        return CaseContext(
            case_id="c1",
            case_name="Test",
            findings=[{"title": "Kontakt jan.novak@example.com"}],
        )

    def test_build_prompt_redacts_by_default(self):
        from stopa.intelligence.ai_orchestrator import build_prompt, route_agent

        profile = route_agent("shrň případ")
        msgs = build_prompt(profile, self._ctx(), "Kdo je +420 777 123 456?")
        user = msgs[1]["content"]
        assert "+420****3456" in user
        assert "+420 777 123 456" not in user
        # PII i v kontextu případu je zmaskovaná
        assert "j***@example.com" in user

    def test_build_prompt_off_keeps_raw(self):
        from stopa.intelligence.ai_orchestrator import build_prompt, route_agent

        profile = route_agent("shrň případ")
        msgs = build_prompt(
            profile, self._ctx(), "Kdo je +420 777 123 456?", redact_pii=False
        )
        assert "+420 777 123 456" in msgs[1]["content"]

    def test_orchestrate_passes_redaction_to_llm(self):
        from stopa.intelligence.ai_orchestrator import orchestrate

        captured: list[list[dict]] = []

        def llm_call(messages, max_tokens):
            captured.append(messages)
            return json.dumps({"summary": "ok", "open_questions": []})

        ctx = self._ctx()
        orchestrate(llm_call, ctx, "Kdo je +420 777 123 456?")
        assert "+420****3456" in captured[0][1]["content"]

        orchestrate(llm_call, ctx, "Kdo je +420 777 123 456?", redact_pii=False)
        assert "+420 777 123 456" in captured[1][1]["content"]


# ════════════════════════════════════════════════════════════════
# E11 buildery — maskování promptů
# ════════════════════════════════════════════════════════════════

class TestE11BuildersRedaction:
    def test_nl_search_redacts_question(self):
        from stopa.domain.ai_assistant import build_nl_search_prompt

        msgs = build_nl_search_prompt("napiš na jan.novak@example.com", "C")
        assert "j***@example.com" in msgs[1]["content"]
        raw = build_nl_search_prompt(
            "napiš na jan.novak@example.com", "C", redact_pii=False
        )
        assert "jan.novak@example.com" in raw[1]["content"]

    def test_summary_redacts_sample(self):
        from stopa.domain.ai_assistant import build_summary_prompt

        sample = [
            {
                "id": "art-1",
                "artifact_type": "chat_message",
                "title": "zpráva od jan.novak@example.com",
                "timestamp": None,
            }
        ]
        msgs = build_summary_prompt("C", {"files": 1}, {}, sample)
        assert "j***@example.com" in msgs[1]["content"]

    def test_explain_redacts_details(self):
        from stopa.domain.ai_assistant import build_explain_prompt

        art = {
            "id": "art-1",
            "artifact_type": "chat_message",
            "title": None,
            "rel_path": "x.db",
            "timestamp": None,
            "confidence": 0.9,
            "anomaly_flags": [],
            "details": {"author": "+420 777 123 456"},
        }
        msgs = build_explain_prompt(art)
        assert "+420****3456" in msgs[1]["content"]


# ════════════════════════════════════════════════════════════════
# web E2E — maskování PII + audit modelových volání (mock LM Studio)
# ════════════════════════════════════════════════════════════════

class _RecordingAiClient:
    """Fake LmStudioClient — zaznamenává messages předané do chat()."""

    response = "default"
    captured: ClassVar[list[list[dict]]] = []

    def __init__(self, *a, **k) -> None:
        pass

    def health(self) -> dict:
        return {"available": True, "model": "fake-model"}

    def chat(self, messages, max_tokens=None) -> str:
        _RecordingAiClient.captured.append(messages)
        return self.response


def _patch_ai(monkeypatch: pytest.MonkeyPatch, response: str):
    import stopa.web.app as app_mod

    fake = type("Fake", (_RecordingAiClient,), {"response": response})
    monkeypatch.setattr(app_mod, "LmStudioClient", fake)
    return fake


def _ai_query_ops(tmp_path: Path) -> list:
    """Auditní záznamy ai_query (druhé spojení — record_operation commítuje)."""
    from stopa.data.db import CaseDB

    db2 = CaseDB(str(tmp_path / f"{CASE_ID}.db"))
    try:
        return db2.list_operations(case_id=CASE_ID, op_type="ai_query")
    finally:
        db2.close()


class TestE11AuditAndRedaction:
    def test_nl_search_masks_pii_and_audits(self, ai_client, tmp_path, monkeypatch):  # noqa: F811
        _RecordingAiClient.captured.clear()
        _patch_ai(
            monkeypatch,
            json.dumps({"query": "size:>1MB", "explanation": "velké soubory", "confidence": 0.9}),
        )
        r = ai_client.post(
            f"/api/cases/{CASE_ID}/ai/query",
            json={"mode": "nl_search", "question": "kdo volal na +420 777 123 456?"},
        )
        assert r.status_code == 200, r.text

        # PII zmaskovaná PŘED chat()
        sent = _RecordingAiClient.captured[-1]
        user_text = " ".join(m["content"] for m in sent)
        assert "+420****3456" in user_text
        assert "+420 777 123 456" not in user_text

        # auditní záznam: model + hash promptu + agent
        ops = _ai_query_ops(tmp_path)
        assert len(ops) == 1
        p = ops[0].params_json
        assert p["model"] == "fake-model"
        assert p["agent"] == "e11:nl_search"
        assert len(p["prompt_sha256"]) == 64

    def test_settings_toggle_off_disables_redaction(self, ai_client, tmp_path, monkeypatch):  # noqa: F811
        # default ON (žádný settings.json)
        assert ai_client.get("/api/settings").json()["ai_redact_pii"] is True

        _RecordingAiClient.captured.clear()
        _patch_ai(
            monkeypatch,
            json.dumps({"query": "size:>1MB", "explanation": "x", "confidence": 0.5}),
        )
        q = {"mode": "nl_search", "question": "kdo je +420 777 123 456?"}

        r_on = ai_client.post(f"/api/cases/{CASE_ID}/ai/query", json=q)
        assert r_on.status_code == 200, r_on.text

        # toggle OFF → surová PII v promptu
        put = ai_client.put("/api/settings", json={"ai_redact_pii": False})
        assert put.status_code == 200 and put.json()["ai_redact_pii"] is False

        r_off = ai_client.post(f"/api/cases/{CASE_ID}/ai/query", json=q)
        assert r_off.status_code == 200, r_off.text
        sent_off = _RecordingAiClient.captured[-1]
        user_off = " ".join(m["content"] for m in sent_off)
        assert "+420 777 123 456" in user_off

        # audit: dva záznamy s RŮZNÝMI hashi (redakce změnila prompt)
        ops = _ai_query_ops(tmp_path)
        assert len(ops) == 2
        hashes = {o.params_json["prompt_sha256"] for o in ops}
        assert len(hashes) == 2

    def test_summary_and_explain_audited(self, ai_client, tmp_path, monkeypatch):  # noqa: F811
        _patch_ai(monkeypatch, "Shrnutí s citací [art:art-x1].")
        r1 = ai_client.post(
            f"/api/cases/{CASE_ID}/ai/query", json={"mode": "summary"}
        )
        assert r1.status_code == 200, r1.text
        r2 = ai_client.post(
            f"/api/cases/{CASE_ID}/ai/query",
            json={"mode": "explain", "artifact_id": "art-x1"},
        )
        assert r2.status_code == 200, r2.text

        ops = _ai_query_ops(tmp_path)
        agents = [o.params_json["agent"] for o in ops]
        assert "e11:summary" in agents and "e11:explain" in agents


class TestI1AnalyzeRedactionAndAudit:
    def test_analyze_masks_pii_and_audits_model(self, ai_client, tmp_path, monkeypatch):  # noqa: F811
        _RecordingAiClient.captured.clear()
        _patch_ai(monkeypatch, json.dumps({"summary": "ok", "open_questions": []}))
        r = ai_client.post(
            f"/api/cases/{CASE_ID}/ai/analyze",
            json={"question": "Kdo je +420 777 123 456?"},
        )
        assert r.status_code == 200, r.text

        sent = _RecordingAiClient.captured[-1]
        user_text = " ".join(m["content"] for m in sent)
        assert "+420****3456" in user_text
        assert "+420 777 123 456" not in user_text

        ops = _ai_query_ops(tmp_path)
        assert len(ops) == 1
        p = ops[0].params_json
        assert p["model"] == "fake-model"
        assert p["agent"] == "case_analyst"
