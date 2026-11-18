"""P1-2 — AI orchestrátor: testy I/O služby (offline přes fake klienta)."""

from __future__ import annotations

import random

import pytest

from stopa.data.ai_orchestrator_service import (
    AiOrchestrationError,
    call_role,
    estimate_tokens,
)
from stopa.data.lmstudio_client import LmStudioError
from stopa.domain.ai_orchestrator import RetryPolicy, TokenBudget


class FakeClient:
    """Sekvence odpovědí/výjimek; každý chat() consumuje jeden prvek."""

    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls: list[tuple] = []

    def chat(self, messages, max_tokens=None):
        self.calls.append((messages, max_tokens))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


GOOD_HYPOTHESIS = '{"statement": "infekce", "confidence": 0.7, "citations": ["art-1"]}'


class TestCallRole:
    def test_success_validates_payload(self):
        client = FakeClient([GOOD_HYPOTHESIS])
        result = call_role("hypothesis", "Jaká je hypotéza?", [], client=client)
        assert result.role_id == "hypothesis"
        assert result.payload is not None and result.payload["statement"] == "infekce"
        assert result.attempts == 1
        # max_tokens = limit role (600 pro hypothesis)
        assert client.calls[0][1] == 600

    def test_retry_then_success_records_delays(self):
        client = FakeClient([LmStudioError("down"), GOOD_HYPOTHESIS])
        sleeps: list[float] = []
        result = call_role(
            "hypothesis", "q", [], client=client, rng=random.Random(1), sleep_fn=sleeps.append
        )
        assert len(client.calls) == 2 and result.attempts == 2
        assert len(sleeps) == 1  # jen před druhým pokusem
        assert 0.75 <= sleeps[0] <= 1.25  # base 1.0 ± jitter

    def test_exhausted_raises_and_audits_failure(self):
        client = FakeClient([LmStudioError("a"), LmStudioError("b"), LmStudioError("c")])
        audit: list[tuple] = []
        sleeps: list[float] = []
        with pytest.raises(AiOrchestrationError, match="3 pokusech"):
            call_role(
                "report", "q", [], client=client, rng=random.Random(2), sleep_fn=sleeps.append,
                audit_sink=lambda a, p: audit.append((a, p)),
            )
        assert len(client.calls) == 3 and len(sleeps) == 2
        assert audit[0][0] == "ai_role_call" and audit[0][1]["ok"] is False

    def test_budget_exhausted_valueerror(self):
        client = FakeClient(["x" * 100])  # odhad = 25 tokenů > limit 2
        with pytest.raises(ValueError, match="token budget exhausted"):
            call_role("evidence", "q", [], client=client,
                      budget=TokenBudget(session_limit=2))

    def test_invalid_schema_payload_none_but_call_ok(self):
        client = FakeClient(['{"foo": 1}'])  # dict bez povinných polí role hypothesis
        result = call_role("hypothesis", "q", [], client=client)
        assert result.payload is None and result.text == '{"foo": 1}'

    def test_non_json_text_payload_none(self):
        client = FakeClient(["Dobrý den, shrnutí nenačteno."])
        result = call_role("evidence", "q", [], client=client)
        assert result.payload is None and estimate_tokens(result.text) >= 1

    def test_audit_sink_records_success(self):
        client = FakeClient([GOOD_HYPOTHESIS])
        audit: list[tuple] = []
        call_role("hypothesis", "q", [], client=client,
                  audit_sink=lambda a, p: audit.append((a, p)))
        assert len(audit) == 1
        action, payload = audit[0]
        assert action == "ai_role_call" and payload["ok"] is True
        assert payload["role"] == "hypothesis" and payload["attempts"] == 1

    def test_unknown_role_valueerror_before_client(self):
        client = FakeClient([GOOD_HYPOTHESIS])
        with pytest.raises(ValueError, match="neznámá AI role"):
            call_role("ceo", "q", [], client=client)
        assert not client.calls  # klient vůbec nebyl volán

    def test_default_retry_policy_three_attempts(self):
        policy = RetryPolicy()
        client = FakeClient([LmStudioError("x")] * policy.max_attempts)
        sleeps: list[float] = []
        with pytest.raises(AiOrchestrationError):
            call_role("qa", "q", [], client=client, rng=random.Random(3), sleep_fn=sleeps.append)
        assert len(sleeps) == policy.max_attempts - 1
