"""STOPA — Agent Profile (P0 Intelligence, I1).

Pět specializovaných forenzních agentů jako **deklarativní profily** (ne
autonomní systémy): každý má jasně definovaný system prompt, popis vstupů,
Pydantic výstupní model a limity (max tokenů, timeout). Orchestrátor volá
agenta jednou na úkol — žádná autonomní smyčka.

Výstupní modely jsou Pydantic v2 — orchestrátor validuje JSON odpověď LLM
proti nim; nevalidní výstup = ``OrchestrationError`` (fail-closed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

# ── výstupní modely (Pydantic — validace LLM odpovědí) ───────────────────────

class CaseAnalystOutput(BaseModel):
    """Case Analyst: shrnutí případu + nevyřešené otázky."""

    summary: str = Field(min_length=1, description="Shrnutí případu (čeština)")
    open_questions: list[str] = Field(default_factory=list)


class TimelineAnalystOutput(BaseModel):
    """Timeline Analyst: časové rozpory + poznámky."""

    contradictions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Rozpory: {description, event_a, event_b}",
    )
    notes: str = ""


class ArtifactAnalystOutput(BaseModel):
    """Artifact Analyst: vysvětlení artefaktu + neúplnosti."""

    explanation: str = Field(min_length=1)
    gaps: list[str] = Field(default_factory=list, description="Neúplné/nejednoznačné záznamy")


class MediaAnalystOutput(BaseModel):
    """Media Analyst: indikátory manipulace + limity analýzy."""

    indicators: list[str] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list, description="Co analýza NEOVĚŘÍ")


class ReportAnalystOutput(BaseModel):
    """Report Analyst: sekce reportu + citace na zdrojové artefakty."""

    sections: list[dict[str, str]] = Field(
        default_factory=list, description="Sekce: {title, content}"
    )
    citations: list[str] = Field(default_factory=list, description="[art:<id>] tokeny")


# ── deklarativní agent profile ───────────────────────────────────────────────

@dataclass(frozen=True)
class AgentProfile:
    """Jeden specializovaný analytický agent.

    Attributes:
        id: stabilní identifikátor (routing, audit log).
        name: lidsky čitelné jméno.
        system_prompt: role + pravidla pro LLM (čeština výstupu).
        inputs: popis očekávaných vstupů (dokumentace + prompt hint).
        output_model: Pydantic model, proti kterému se validuje odpověď.
        max_tokens: limit délky odpovědi.
        timeout_s: timeout inference (lokální LM Studio může být pomalé).
    """

    id: str
    name: str
    system_prompt: str
    inputs: str
    output_model: type[BaseModel]
    max_tokens: int = 900
    timeout_s: float = 120.0


_COMMON_RULES = (
    "Odpovídej VŽDY v češtině. Odpověz PŘESNĚ JSON objektem bez prose a bez "
    "markdown fence. Každé tvrzení opatři citací [art:<id>] z poskytnutých dat, "
    "pokud existuje. Nejsilnější úroveň důvěryhodnosti: AI hypotéza — nikdy "
    "neprezentuj odhad jako fakt."
)


AGENTS: dict[str, AgentProfile] = {
    "case_analyst": AgentProfile(
        id="case_analyst",
        name="Case Analyst",
        system_prompt=(
            "Jsi forenzní analytik případu. Analyzuj poskytnutá data případu: "
            "shrň, co bylo prozkoumáno, klíčová zjištění a neobvyklé anomálie. "
            "Vytvoř seznam nevyřešených otázek pro další šetření. " + _COMMON_RULES
        ),
        inputs="case summary (stats), findings, sample artifacts",
        output_model=CaseAnalystOutput,
    ),
    "timeline_analyst": AgentProfile(
        id="timeline_analyst",
        name="Timeline Analyst",
        system_prompt=(
            "Jsi analytik časové osy. Prozkoumej události z timeline: detekuj "
            "časové rozpory (např. odpověď před otázkou, dvě akce ve stejném "
            "čase na různých zařízeních), neobvyklé souvislosti a srovnání "
            "událostí napříč zdroji. Každý rozpor popiš s odkazem na obě události. "
            + _COMMON_RULES
        ),
        inputs="timeline events (úsek), zdrojové metadata",
        output_model=TimelineAnalystOutput,
    ),
    "artifact_analyst": AgentProfile(
        id="artifact_analyst",
        name="Artifact Analyst",
        system_prompt=(
            "Jsi analytik artefaktů. Vysvětli jeden extrahovaný artefakt: co je to, "
            "proč je forenzně významný, jaká jsou omezení (confidence). Identifikuj "
            "neúplné nebo nejednoznačné záznamy v detailech. " + _COMMON_RULES
        ),
        inputs="artifact + details_json",
        output_model=ArtifactAnalystOutput,
    ),
    "media_analyst": AgentProfile(
        id="media_analyst",
        name="Media Analyst",
        system_prompt=(
            "Jsi analytik multimediálních dat. Analyzuj metadata souboru (EXIF, "
            "formát, velikost, hash) a případný OCR text: detekuj indikátory "
            "manipulace (např. nesoulad rozlišení a zařízení, chybějící EXIF). "
            "Vždy uveď limity — co analýza NEOVĚŘÍ (pixelová forenzika apod.). "
            + _COMMON_RULES
        ),
        inputs="file metadata + OCR text",
        output_model=MediaAnalystOutput,
    ),
    "report_analyst": AgentProfile(
        id="report_analyst",
        name="Report Analyst",
        system_prompt=(
            "Jsi autor forenzních reportů. Sestav podklady pro odborný report: "
            "sekce s ověřenými zjištěními, každé tvrzení odkazuj na zdrojové "
            "artefakty ([art:<id>]). Jasně rozliš fakta (direct/derived) a "
            "analytické interpretace. " + _COMMON_RULES
        ),
        inputs="findings + evidence refs",
        output_model=ReportAnalystOutput,
    ),
}

#: výchozí agent pro auto-routing (explicitní volba má vždy přednost)
DEFAULT_AGENT = "case_analyst"


def get_agent(agent_id: str) -> AgentProfile | None:
    """Agent profil podle ID; ``None`` pokud neznámý."""
    return AGENTS.get(agent_id)
