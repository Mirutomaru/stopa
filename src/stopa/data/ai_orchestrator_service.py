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
    ROLE_REQUIRES_CITATION,
    RetryPolicy,
    TokenBudget,
    backoff_delay,
    build_role_messages,
    build_role_registry,
    extract_citation_ids,
    fingerprint_messages,
    validate_citation_ids,
    validate_role_output,
)


class ChatClient(Protocol):
    """Duck-typing kontrakt AI klienta (LmStudioClient ho splňuje; testy fake).

    B8 — ``temperature`` = fixní sampling parametr role (None → default klienta).
    """

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        *,
        temperature: float | None = None,
    ) -> str: ...


class AiOrchestrationError(Exception):
    """Klient nedostupný ani po vyčerpání retry pokusů."""


@dataclass(frozen=True)
class OrchestratedCall:
    """Výsledek jednoho volání role (auditovatelná entita).

    B8 — nová auditní pole: ``citations``/``unknown_citations`` (grounding
    vůči ID z DB případu), ``grounded`` (None = neověřeno, False = role
    vyžadovala citaci a žádná validní nepřišla → payload=None) a ``model``
    (identita modelu, který volání skutečně obsloužil).
    """

    role_id: str
    text: str
    payload: dict[str, Any] | None  # None = JSON nebylo / validace selhala
    tokens_out: int  # odhad (char//4) — bez tokenizeru v hard dependency
    attempts: int
    citations: tuple[str, ...] = ()  # B8 — citované ID (validní vůči DB, resp. veškeré nalezené)
    unknown_citations: tuple[str, ...] = ()  # B8 — „divoké“ citace neexistující v DB
    grounded: bool | None = None  # B8 — None = grounding neověřen (bez validních ID z DB)
    model: str | None = None  # B8 — model, který odpověď vygeneroval


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
        role_id, question, evidence, client=client, budget=budget, audit_sink=audit_sink,
        valid_artifact_ids=used_ids,
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
    valid_artifact_ids: Sequence[str] | None = None,
) -> OrchestratedCall:
    """Vyvolá AI roli s retry+backoff+jitter, token budgetem a validací výstupu.

    Vše stochastické je injektovatelné (``rng``, ``sleep_fn``) → offline testy.

    B8 — determinismus kolem AI agenta:
      * sampling fixní per role (``role.temperature`` explicitně v payloadu),
      * citace z textu i pole ``citations`` se ověřují proti
        ``valid_artifact_ids`` (grounding; role z ``ROLE_REQUIRES_CITATION``
        bez validní citace → ``payload=None``, ``grounded=False``),
      * audit nese reprodukovatelnou identitu: model, teplotu a SHA-256 promptu.
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
    prompt_sha256 = fingerprint_messages(messages)  # B8 — auditní identita promptu

    last_error: Exception | None = None
    text: str | None = None
    attempts = 0
    for attempt in range(1, policy.max_attempts + 1):
        attempts = attempt
        try:
            text = client.chat(messages, max_tokens=role.max_tokens, temperature=role.temperature)
            last_error = None
            break
        except LmStudioError as exc:
            last_error = exc
            if attempt < policy.max_attempts:
                sleep_fn(backoff_delay(policy, attempt, rng))

    if text is None or last_error is not None:
        if audit_sink:
            audit_sink("ai_role_call", {"role": role_id, "ok": False, "attempts": attempts,
                                        "error": str(last_error),
                                        "model": getattr(client, "last_model", None),
                                        "temperature": role.temperature,
                                        "prompt_sha256": prompt_sha256})
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

    # B8 — grounding citací vůči ID artefaktů DB případu
    cited = extract_citation_ids(text)
    if isinstance(payload, dict):
        pcites = payload.get("citations")
        if isinstance(pcites, list):
            for c in pcites:
                if isinstance(c, str) and c not in cited:
                    cited.append(c)
    model_name: str | None = getattr(client, "last_model", None)
    grounded: bool | None = None
    valid_citations: list[str] = []
    unknown_citations: list[str] = []
    if valid_artifact_ids is not None:
        valid_citations, unknown_citations = validate_citation_ids(
            cited, set(valid_artifact_ids)
        )
        grounded = True
        if role_id in ROLE_REQUIRES_CITATION and not valid_citations:
            payload = None  # povinná citace chybí → QA signál jako u nesplněného schématu
            grounded = False
    else:
        valid_citations = cited  # bez DB kontextu se neověřuje, jen zaznamenává

    if audit_sink:
        audit_sink("ai_role_call", {"role": role_id, "ok": True, "attempts": attempts,
                                    "tokens_out": tokens_out,
                                    "model": model_name,
                                    "temperature": role.temperature,
                                    "prompt_sha256": prompt_sha256,
                                    "citations": valid_citations,
                                    "unknown_citations": unknown_citations,
                                    "grounded": grounded})
    return OrchestratedCall(role_id=role_id, text=text, payload=payload,
                            tokens_out=tokens_out, attempts=attempts,
                            citations=tuple(valid_citations),
                            unknown_citations=tuple(unknown_citations),
                            grounded=grounded, model=model_name)
