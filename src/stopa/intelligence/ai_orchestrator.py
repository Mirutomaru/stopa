"""STOPA — AI Orchestrátor (P0 Intelligence, I1).

Jednoduchý orchestrátor nad 5 agenty: explicitní volba nebo auto-routing podle
dotazu → sestavení promptu (system + user s CaseContext) → jeden LLM call →
validace JSON výstupu proti Pydantic modelu agenta (fail-closed).

``llm_call`` je injektovatelný callable ``(messages, max_tokens) -> str``,
tudíž celá orchestrace se testuje bez spuštěného LM Studio (offline).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from stopa.intelligence.agents import AGENTS, DEFAULT_AGENT, AgentProfile
from stopa.intelligence.case_context import CaseContext


class OrchestrationError(Exception):
    """Chyba orchestrace (neznámý agent, nevalidní výstup LLM…)."""


#: citace [art:<id>] / [file:<id>] v odpovědi LLM
_CITATION_RE = re.compile(r"\[(?:art|file):([A-Za-z0-9_-]+)\]")

# auto-routing: klíčová slova → agent (řazení = priorita)
_ROUTE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("timeline_analyst", ("časová osa", "časovou osu", "timeline", "chronolog")),
    ("media_analyst", ("obrázek", "video", "audio", "exif", "manipulace", "multimedi")),
    ("artifact_analyst", ("artefakt", "artifact", "vysvětli", "explain")),
    ("report_analyst", ("report", "zpráva", "sestav podklady")),
]


def route_agent(question: str, agent_id: str | None = None) -> AgentProfile:
    """Vybere agenta.

    Explicitní ``agent_id`` má vždy přednost (neznámá → ``OrchestrationError``).
    Jinak auto-routing podle klíčových slov; default = case_analyst.
    """
    if agent_id is not None:
        prof = AGENTS.get(agent_id)
        if prof is None:
            raise OrchestrationError(f"neznámý agent: {agent_id}")
        return prof

    q = question.lower()
    for aid, keywords in _ROUTE_KEYWORDS:
        if any(kw in q for kw in keywords):
            return AGENTS[aid]
    return AGENTS[DEFAULT_AGENT]


def build_prompt(profile: AgentProfile, context: CaseContext, question: str) -> list[dict[str, str]]:
    """Messages pro LLM: system (role agenta) + user (dotaz + kontext případu)."""
    user = (
        f"Dotaz: {question}\n\n"
        f"Dostupné vstupy tohoto agenta: {profile.inputs}.\n\n"
        "Data případu (read-only snapshot):\n"
        f"{context.to_prompt_block()}"
    )
    return [
        {"role": "system", "content": profile.system_prompt},
        {"role": "user", "content": user},
    ]


def extract_citations(text: str) -> list[str]:
    """Unikátní citace [art:<id>]/[file:<id>] v pořadí výskytu."""
    seen: dict[str, None] = {}
    for m in _CITATION_RE.finditer(text):
        seen.setdefault(m.group(1), None)
    return list(seen)


def parse_output(profile: AgentProfile, raw_text: str) -> BaseModel:
    """Validuje JSON odpověď LLM proti výstupnímu modelu agenta (fail-closed).

    Zvládne markdown fence a proza kolem JSON objektu. Nevalidní →
    ``OrchestrationError`` s úryvkem odpovědi (auditovatelné).
    """
    text = raw_text.strip()
    # odstranění markdown fence ```json … ```
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # první { → poslední } (LLM občas přidá proza kolem)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise OrchestrationError(
            f"agent {profile.id}: JSON objekt nenalezen v odpovědi: {raw_text[:200]!r}"
        )
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise OrchestrationError(f"agent {profile.id}: nevalidní JSON ({exc})") from exc
    try:
        return profile.output_model.model_validate(data)
    except ValidationError as exc:
        raise OrchestrationError(
            f"agent {profile.id}: výstup nesedí na model "
            f"{profile.output_model.__name__} ({exc.error_count()} chyb)"
        ) from exc


@dataclass(frozen=True)
class AgentResult:
    """Výsledek jednoho agentova úkolu (auditovatelný)."""

    agent_id: str
    output: BaseModel  # validovaný výstupní model agenta
    raw_text: str
    citations: list[str]
    prompt_chars: int
    duration_ms: float


def orchestrate(
    llm_call: Callable[[list[dict[str, str]], int], str],
    context: CaseContext,
    question: str,
    agent_id: str | None = None,
) -> AgentResult:
    """Spustí jeden analytický úkol přes vybraného agenta.

    Args:
        llm_call: ``(messages, max_tokens) -> text odpovědi`` (IO vrstva).
        context: read-only snapshot případu.
        question: dotaz uživatele.
        agent_id: explicitní agent; ``None`` = auto-routing.

    Returns:
        ``AgentResult`` s validovaným výstupem + auditními metadaty.

    Raises:
        OrchestrationError: neznámý agent / nevalidní výstup LLM.
    """
    profile = route_agent(question, agent_id)
    messages = build_prompt(profile, context, question)
    prompt_chars = sum(len(m["content"]) for m in messages)

    t0 = time.monotonic()
    raw_text = llm_call(messages, profile.max_tokens)
    duration_ms = (time.monotonic() - t0) * 1000.0

    output = parse_output(profile, raw_text)
    return AgentResult(
        agent_id=profile.id,
        output=output,
        raw_text=raw_text,
        citations=extract_citations(raw_text),
        prompt_chars=prompt_chars,
        duration_ms=duration_ms,
    )
