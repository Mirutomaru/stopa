"""P1-2 — AI orchestrátor: I/O vrstva nad LM Studio klientem.

Tenký wrapper kolem ``LmStudioClient`` + domény ``domain/ai_orchestrator.py``:
build zpráv per role, enforcement token budgetu a retry policy (backoff+jitter),
validace strukturovaného výstupu. Auditní zápisy jdou přes injektovatelný
callback ``audit_sink(action, payload)`` — služba se tak nezavádí na CaseDB
(db.py drží řádkový rozpočet).

Chybové sémantiky: neznámá role → ``ValueError``, nedostupný klient po vyčerpání
retry → ``AiOrchestrationError``, překročení budgetu → ``ValueError``.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from stopa.data.lmstudio_client import LmStudioClient, LmStudioError, settings_from_env
from stopa.domain.ai_orchestrator import (
    RetryPolicy,
    TokenBudget,
    backoff_delay,
    build_role_messages,
    build_role_registry,
    validate_role_output,
)


class ChatClient(Protocol):
    """Duck-typing kontrakt AI klienta (LmStudioClient ho splňuje; testy fake)."""

    def chat(self, messages: list[dict[str, str]], max_tokens: int | None = None) -> str: ...


class AiOrchestrationError(Exception):
    """Klient nedostupný ani po vyčerpání retry pokusů."""


@dataclass(frozen=True)
class OrchestratedCall:
    """Výsledek jednoho volání role (auditovatelná entita)."""

    role_id: str
    text: str
    payload: dict[str, Any] | None  # None = JSON nebylo / validace selhala
    tokens_out: int  # odhad (char//4) — bez tokenizeru v hard dependency
    attempts: int


def estimate_tokens(text: str) -> int:
    """Hrubý odhad tokenů (1 token ≈ 4 znaky) — dostatečný pro budgetování."""
    return max(1, len(text) // 4)


# ── case-level wiring (CLI/Web sdílená cesta) ───────────────────────────────

#: Počet nejnovějších artefaktů jako implicitní důkaz (bez explicitních ID).
DEFAULT_EVIDENCE_LIMIT = 5


def artifact_to_evidence(art: Any) -> dict[str, Any]:
    """Jeden ``Artifact`` → evidence item pro prompt ``{"id","title","text"}``.

    Text důkazu = JSON ``details`` (nebo ``title``, pokud details prázdné);
    délku omezuje ``sanitize_evidence_text`` v ``build_role_messages``.
    """
    from stopa.models import Artifact  # lazy — vyhnout se cyklu při startu

    if not isinstance(art, Artifact):
        raise TypeError(f"očekáván Artifact, got {type(art).__name__}")
    text = json.dumps(art.details, ensure_ascii=False) if art.details else (art.title or "")
    return {"id": art.id, "title": art.title or "", "text": text}


def run_role_on_case(
    db: Any,
    role_id: str,
    question: str = "",
    artifact_ids: Sequence[str] | None = None,
    *,
    client: ChatClient | None = None,
    budget_limit: int = 20_000,
) -> tuple[OrchestratedCall, list[str]]:
    """Spustí AI roli nad důkazy case DB; audit jde do ``db.log_operation``.

    Důkazní sada: explicitní ``artifact_ids`` (každé musí existovat →
    ``ValueError``) nebo implicitně posledních ``DEFAULT_EVIDENCE_LIMIT``
    artefaktů chronologicky. Neznámá role / prázdný case → ``ValueError``;
    nedostupný klient po retrych → ``AiOrchestrationError``.

    Vrací ``(call, used_artifact_ids)`` — auditní záznamy nesmí ztratit
    kontext, který důkaz byl modelu podán.
    """
    roles = build_role_registry()
    if role_id not in roles:  # doménová ValueError (stejná jako v call_role)
        raise ValueError(f"neznámá AI role {role_id!r}")

    if artifact_ids is None:
        # chronologicky vzestupně (repo ORDER BY timestamp ASC) → ocas = nejnovější
        arts = list(db.list_artifacts())[-DEFAULT_EVIDENCE_LIMIT:]
        if not arts:
            raise ValueError("case nemá žádné artefakty (zadej explicitní --artifact)")
    else:
        arts = []
        missing = [aid for aid in artifact_ids if db.get_artifact(aid) is None]
        if missing:
            raise ValueError(f"artefakty nenalezeny v případě: {', '.join(missing)}")
        arts = [db.get_artifact(aid) for aid in artifact_ids]

    evidence = [artifact_to_evidence(art) for art in arts]
    used_ids = [art.id for art in arts]
    budget = TokenBudget(session_limit=budget_limit)

    def audit_sink(action: str, payload: dict[str, Any]) -> None:
        db.log_operation(
            action, actor="ai_orchestrator", details={**payload, "evidence": used_ids}
        )

    call = call_role(
        role_id, question, evidence, client=client, budget=budget, audit_sink=audit_sink
    )
    return call, used_ids


def _extract_json(text: str) -> Any | None:
    """První JSON objekt v odpovědi (model obaluje JSON do prose/markdown)."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None


def call_role(
    role_id: str,
    question: str,
    evidence: Sequence[dict[str, Any]],
    *,
    client: ChatClient | None = None,
    budget: TokenBudget | None = None,
    retry_policy: RetryPolicy | None = None,
    rng: random.Random | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    audit_sink: Callable[[str, dict[str, Any]], None] | None = None,
) -> OrchestratedCall:
    """Vyvolá AI roli s retry+backoff+jitter, token budgetem a validací výstupu.

    Vše stochastické je injektovatelné (``rng``, ``sleep_fn``) → offline testy.
    """
    roles = build_role_registry()
    if role_id not in roles:  # doménová ValueError, ne orchestrátorová
        raise ValueError(f"neznámá AI role {role_id!r}")
    role = roles[role_id]
    budget = budget or TokenBudget()
    policy = retry_policy or RetryPolicy()
    rng = rng or random.Random()
    if client is None:
        client = LmStudioClient(settings_from_env())
    messages = build_role_messages(role_id, question, evidence)

    last_error: Exception | None = None
    text: str | None = None
    attempts = 0
    for attempt in range(1, policy.max_attempts + 1):
        attempts = attempt
        try:
            text = client.chat(messages, max_tokens=role.max_tokens)
            last_error = None
            break
        except LmStudioError as exc:
            last_error = exc
            if attempt < policy.max_attempts:
                sleep_fn(backoff_delay(policy, attempt, rng))

    if text is None or last_error is not None:
        if audit_sink:
            audit_sink("ai_role_call", {"role": role_id, "ok": False, "attempts": attempts,
                                        "error": str(last_error)})
        raise AiOrchestrationError(f"role {role_id!r} selhala po {attempts} pokusech: {last_error}")

    tokens_out = estimate_tokens(text)
    budget.consume(tokens_out)  # ValueError při překročení session limitu

    payload = _extract_json(text)
    if isinstance(payload, dict):
        try:
            validate_role_output(role_id, payload)
        except (ValueError, TypeError):
            payload = None  # volání OK, ale výstup nesplnil schema — QA to ohodnotí
    else:
        payload = None

    if audit_sink:
        audit_sink("ai_role_call", {"role": role_id, "ok": True, "attempts": attempts,
                                    "tokens_out": tokens_out})
    return OrchestratedCall(role_id=role_id, text=text, payload=payload,
                            tokens_out=tokens_out, attempts=attempts)
