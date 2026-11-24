"""B8 — determinismus kolem AI agentů.

Čtyři pilíře, každý s testem:

1. **Fixní sampling** — ``AiSettings.temperature`` (0.2) + ``top_p`` (1.0)
   explicitně v odchozím payloadu; role teplotu přepíše přes ``chat(temperature=)``.
2. **Přísné schéma výstupů** — kromě přítomnosti polí se ověřuje typ
   (``ROLE_OUTPUT_TYPES``); numerická pole odmítají bool (True != 1).
3. **Grounding citací** — citace ``[art:<id>]``/``[file:<id>]`` z textu i pole
   ``citations`` se ověřují proti ID artefaktů DB případu; role slibující
   citace (timeline/hypothesis/report) bez validní → ``payload=None``,
   ``grounded=False``.
4. **Auditní identita** — každý záznam nese model, teplotu a SHA-256 promptu
   (reprodukce: stejný prompt + model + parametry → srovnatelná odpověď).

Plně offline (fake klient), deterministické.
"""

from __future__ import annotations

import json
import re
from typing import Any, Self

import pytest
from test_p12_ai_orchestrator_service import FakeClient  # nese last_model + temperatures

from stopa.data.ai_orchestrator_service import (
    AiOrchestrationError,
    call_role,
    run_role_on_case,
)
from stopa.data.lmstudio_client import AiSettings, LmStudioClient, LmStudioError
from stopa.domain.ai_orchestrator import (
    ROLE_IDS,
    ROLE_OUTPUT_SCHEMA,
    ROLE_OUTPUT_TYPES,
    ROLE_REQUIRES_CITATION,
    build_role_messages,
    build_role_registry,
    extract_citation_ids,
    fingerprint_messages,
    validate_citation_ids,
    validate_role_output,
)


def _hyp(resp: dict[str, Any]) -> str:
    return json.dumps(resp, ensure_ascii=False)


# ════════════════════════════════ 1. fixní sampling (IO vrstva) ═════════════

class TestSamplingPin:
    def test_settings_defaults(self):
        s = AiSettings()
        assert (s.temperature, s.top_p) == (0.2, 1.0)

    @staticmethod
    def _fake_http(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> None:
        """Nahradí httpx.Client offline fake; zachytí odchozí payload chat()."""
        import stopa.data.lmstudio_client as lm_mod

        class _Resp:
            def __init__(self, data: dict[str, Any]) -> None:
                self._d = data
                self.status_code = 200
                self.text = json.dumps(data)

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return self._d

        class _HTTP:
            def __init__(self, **_kw: Any) -> None:
                return None

            def __enter__(self) -> Self:
                return self

            def __exit__(self, *_a: object) -> bool:
                return False

            def get(self, url: str) -> _Resp:
                assert url.endswith("/models")
                return _Resp({"data": [{"id": "m-1"}]})

            def post(self, url: str, json: dict[str, Any] | None = None) -> _Resp:
                captured["payload"] = json or {}
                return _Resp({"choices": [{"message": {"content": "odpověď"}}]})

        monkeypatch.setattr(lm_mod.httpx, "Client", _HTTP)

    def test_chat_pins_sampling_and_tracks_model(self, monkeypatch: pytest.MonkeyPatch):
        captured: dict[str, Any] = {}
        self._fake_http(monkeypatch, captured)
        client = LmStudioClient(AiSettings(base_url="http://fake:1234"))

        out = client.chat([{"role": "user", "content": "q"}])

        assert out == "odpověď"
        p = captured["payload"]
        assert p["model"] == "m-1"
        assert p["temperature"] == 0.2 and p["top_p"] == 1.0  # fixní pin, ne implicitní default LLM
        assert client.last_model == "m-1"

    def test_chat_role_temperature_override(self, monkeypatch: pytest.MonkeyPatch):
        captured: dict[str, Any] = {}
        self._fake_http(monkeypatch, captured)
        client = LmStudioClient(AiSettings(base_url="http://fake:1234"))

        client.chat([{"role": "user", "content": "q"}], temperature=0.9)

        assert captured["payload"]["temperature"] == 0.9
        assert captured["payload"]["top_p"] == 1.0


# ════════════════════════════ 2. přísná typová schémata (doména) ═════════════

class TestStrictRoleTypes:
    def test_types_cover_all_roles_and_schema_fields(self):
        assert set(ROLE_OUTPUT_TYPES) == set(ROLE_OUTPUT_SCHEMA)
        for rid, typed in ROLE_OUTPUT_TYPES.items():
            fields = {k for k, _ in typed}
            assert fields <= set(ROLE_OUTPUT_SCHEMA[rid]), f"role {rid!r}: typy mimo schema"

    def test_valid_payload_passes(self):
        p = {"statement": "s", "confidence": 0.5, "citations": ["a1"]}
        assert validate_role_output("hypothesis", p) is p

    def test_int_confidence_ok(self):
        p = validate_role_output("hypothesis", {"statement": "s", "confidence": 1, "citations": []})
        assert p["confidence"] == 1

    def test_string_confidence_rejected(self):
        with pytest.raises(ValueError, match="confidence"):
            validate_role_output(
                "hypothesis", {"statement": "s", "confidence": "high", "citations": []}
            )

    def test_bool_confidence_rejected(self):
        """True je isinstance(int) — bez explicitní výjimky by prošel jako 1."""
        with pytest.raises(ValueError, match="confidence"):
            validate_role_output("hypothesis", {"statement": "s", "confidence": True, "citations": []})

    def test_findings_must_be_list(self):
        with pytest.raises(ValueError, match="findings"):
            validate_role_output("evidence", {"findings": "text"})


# ════════════════════════ 3. otisk promptu + citace (doména) ═════════════════

class TestFingerprintAndCitations:
    def test_fingerprint_deterministic(self):
        m = [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
        assert fingerprint_messages(m) == fingerprint_messages([dict(x) for x in m])

    def test_fingerprint_sensitive_to_content_and_order(self):
        a = fingerprint_messages([{"role": "u", "content": "1"}])
        b = fingerprint_messages([{"role": "u", "content": "2"}])
        c = fingerprint_messages([{"role": "user", "content": "1"}])
        assert len({a, b, c}) == 3

    def test_fingerprint_rejects_non_list(self):
        with pytest.raises(TypeError):
            fingerprint_messages("x")  # type: ignore[arg-type]

    def test_extract_citation_ids_order_and_dedup(self):
        text = "viz [art:a-1] a [file:b_2], znovu [art:a-1]"
        assert extract_citation_ids(text) == ["a-1", "b_2"]

    def test_extract_rejects_non_str(self):
        with pytest.raises(TypeError):
            extract_citation_ids(None)  # type: ignore[arg-type]

    def test_validate_citation_ids_split_and_dedupe(self):
        valid, unknown = validate_citation_ids(["x", "a-1", "x"], {"a-1"})
        assert (valid, unknown) == (["a-1"], ["x"])

    def test_requires_citation_is_promised_subset_of_roles(self):
        """Povinná citace jen u rolí, které ji v system promptu slibují."""
        assert ROLE_REQUIRES_CITATION <= set(ROLE_IDS)
        assert ROLE_REQUIRES_CITATION == {"timeline", "hypothesis", "report"}


# ════════════════════════ 4. grounding + auditní identita (služba) ═══════════

EV = [{"id": "a-1", "title": "", "text": "t"}]


class TestCallRoleGrounding:
    def test_valid_citation_grounded(self):
        resp = _hyp({"statement": "x [art:a-1]", "confidence": 0.5, "citations": ["a-1"]})
        client = FakeClient([resp])

        call = call_role("hypothesis", "", EV, client=client, valid_artifact_ids=["a-1"])

        assert call.grounded is True and call.citations == ("a-1",)
        assert call.unknown_citations == () and call.payload is not None

    def test_unknown_citation_hypothesis_ungrounded_payload_none(self):
        resp = _hyp({"statement": "x", "confidence": 0.5, "citations": ["ghost"]})
        client = FakeClient([resp])

        call = call_role("hypothesis", "", EV, client=client, valid_artifact_ids=["a-1"])

        assert call.grounded is False and call.payload is None
        assert call.citations == () and call.unknown_citations == ("ghost",)

    def test_no_valid_ids_records_without_checking(self):
        resp = _hyp({"statement": "x [art:zz]", "confidence": 0.5, "citations": ["zz"]})
        client = FakeClient([resp])

        call = call_role("hypothesis", "", EV, client=client)

        assert call.grounded is None and call.citations == ("zz",) and call.unknown_citations == ()

    def test_mixed_citations_valid_and_unknown(self):
        resp = _hyp({"statement": "x [art:a-1]", "confidence": 0.5, "citations": ["a-1", "ghost"]})
        client = FakeClient([resp])

        call = call_role("hypothesis", "", EV, client=client, valid_artifact_ids=["a-1"])

        assert call.grounded is True
        assert call.citations == ("a-1",) and call.unknown_citations == ("ghost",)

    def test_evidence_role_structured_reference_not_penalized(self):
        """Evidence role odkazuje přes findings[].artifact_id — bez [art:] tokenu."""
        resp = _hyp({"findings": [{"artifact_id": "a-1"}]})
        client = FakeClient([resp])

        call = call_role("evidence", "", EV, client=client, valid_artifact_ids=["a-1"])

        assert call.grounded is True and call.payload is not None


class TestAuditIdentity:
    def test_success_audit_b8_fields(self):
        resp = _hyp({"statement": "x [art:a-1]", "confidence": 0.5, "citations": ["a-1"]})
        client = FakeClient([resp])
        audits: list[tuple[str, dict[str, Any]]] = []

        call = call_role(
            "hypothesis", "Q", EV, client=client, valid_artifact_ids=["a-1"],
            audit_sink=lambda a, p: audits.append((a, p)),
        )

        assert len(audits) == 1 and audits[0][0] == "ai_role_call"
        p = audits[0][1]
        assert p["ok"] is True and p["role"] == "hypothesis"
        assert call.grounded is True and call.citations == ("a-1",)
        # B8 — reprodukovatelná identita volání
        assert p["model"] == "fake-model"  # z klienta, ne z settings
        role = build_role_registry()["hypothesis"]
        assert p["temperature"] == role.temperature == 0.2
        assert p["prompt_sha256"] == fingerprint_messages(build_role_messages("hypothesis", "Q", EV))
        assert p["citations"] == ["a-1"] and p["unknown_citations"] == []
        assert p["grounded"] is True

    def test_role_temperature_forwarded_to_client(self):
        resp = _hyp({"statement": "x", "confidence": 0.5, "citations": []})
        client = FakeClient([resp])

        call_role("hypothesis", "", EV, client=client)

        assert client.temperatures == [build_role_registry()["hypothesis"].temperature]

    def test_failure_audit_has_prompt_hash(self):
        audits: list[tuple[str, dict[str, Any]]] = []
        with pytest.raises(AiOrchestrationError):
            call_role(
                "evidence", "", EV,
                client=FakeClient([LmStudioError("a"), LmStudioError("b"), LmStudioError("c")]),
                sleep_fn=lambda _s: None,
                audit_sink=lambda a, p: audits.append((a, p)),
            )
        assert len(audits) == 1 and audits[0][1]["ok"] is False
        assert re.fullmatch(r"[0-9a-f]{64}", audits[0][1]["prompt_sha256"])


class TestRunRoleGroundingWiring:
    def test_run_role_on_case_grounds_against_used_ids(self):
        from test_p12_ai_orchestrator_eval import FakeDB, _fake_artifact

        db = FakeDB([_fake_artifact("art-0", "2024-01-01T00:00:00")])
        resp = _hyp({"statement": "x [art:art-0]", "confidence": 0.5, "citations": ["art-0"]})

        call, used = run_role_on_case(
            db, "hypothesis", artifact_ids=["art-0"], client=FakeClient([resp])
        )

        assert used == ["art-0"]
        assert call.grounded is True and call.citations == ("art-0",)
        # audit v case DB nese i B8 pole (grounding + identita promptu)
        op = db.ops[0]
        assert op["action"] == "ai_role_call" and op["details"]["grounded"] is True
        assert re.fullmatch(r"[0-9a-f]{64}", op["details"]["prompt_sha256"])
