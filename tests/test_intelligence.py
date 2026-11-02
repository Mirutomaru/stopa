"""P0 Intelligence I1 — AI orchestrace: 5 agentů, routing, validace výstupu.

Plně offline: LLM je injektovaný fake callable (žádné LM Studio).
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest
from pydantic import BaseModel

from stopa.data.db import CaseDB
from stopa.intelligence import (
    AGENTS,
    AgentResult,
    OrchestrationError,
    build_case_context,
    orchestrate,
    route_agent,
)
from stopa.intelligence.agents import (
    ArtifactAnalystOutput,
    CaseAnalystOutput,
    MediaAnalystOutput,
    ReportAnalystOutput,
    TimelineAnalystOutput,
)
from stopa.intelligence.ai_orchestrator import build_prompt, extract_citations, parse_output

# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def db(tmp_path):
    d = CaseDB(tmp_path / "case.db")
    yield d
    d.close()


@pytest.fixture()
def ctx(db: CaseDB) -> object:
    """Případ se zdrojem, artefaktem a findingem pro snapshot."""
    from stopa.domain.evidence_model import ConfidenceLevel, Finding, Provenance
    from stopa.models import Artifact, Case, EvidenceSource

    case = Case(name="AI test")
    db.add_case(case)
    src = EvidenceSource(case_id=case.id, kind="folder", path="/tmp/x")
    db.add_source(src)
    art = Artifact(
        source_id=src.id,
        rel_path="a.dat",
        artifact_type="browser_history",
        title="Test artefakt",
    )
    db.upsert_artifact(art)
    finding = Finding(
        case_id=case.id,
        kind="anomaly",
        confidence_level=ConfidenceLevel.DERIVED,
        provenance=[Provenance(parser_id="sqlite", parser_version="1")],
        details_json={"description": "Nalezen rozpor v čase"},
    )
    db.add_finding(finding)
    return build_case_context(db, case.id)


def _fake_llm(payload: dict):
    """Fake LLM — vrátí JSON odpověď (volitelně s markdown fence)."""

    def call(messages, max_tokens):
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        return json.dumps(payload, ensure_ascii=False)

    return call


# ── agent profile ───────────────────────────────────────────────────────────

class TestAgentProfiles:
    def test_five_agents(self):
        assert set(AGENTS) == {
            "case_analyst",
            "timeline_analyst",
            "artifact_analyst",
            "media_analyst",
            "report_analyst",
        }

    def test_profiles_have_output_model_and_prompt(self):
        for p in AGENTS.values():
            assert p.system_prompt.strip()
            assert issubclass(p.output_model, BaseModel)
            assert p.max_tokens > 0 and p.timeout_s > 0

    def test_profile_frozen(self):
        p = AGENTS["case_analyst"]
        with pytest.raises(FrozenInstanceError):
            p.name = "x"  # type: ignore[misc]


# ── routing ─────────────────────────────────────────────────────────────────

class TestRouting:
    def test_explicit_wins(self):
        assert route_agent("cokoliv", agent_id="media_analyst").id == "media_analyst"

    def test_unknown_explicit_raises(self):
        with pytest.raises(OrchestrationError, match="neznámý agent"):
            route_agent("x", agent_id="ghost")

    def test_auto_routing_keywords(self):
        assert route_agent("Projdě časovou osu a najdi rozpory").id == "timeline_analyst"
        assert route_agent("Analyzuj obrázek na manipulaci (EXIF)").id == "media_analyst"
        assert route_agent("Vysvětli tento artefakt").id == "artifact_analyst"
        assert route_agent("Sestav podklady pro report").id == "report_analyst"

    def test_default_is_case_analyst(self):
        assert route_agent("Shrni případ").id == "case_analyst"


# ── prompt + citace ─────────────────────────────────────────────────────────

class TestPromptAndCitations:
    def test_prompt_structure(self, ctx):
        prof = AGENTS["case_analyst"]
        msgs = build_prompt(prof, ctx, "Shrni případ")
        assert len(msgs) == 2
        assert "forenzní analytik" in msgs[0]["content"].lower() or "analytik" in msgs[0]["content"].lower()
        # user blok obsahuje dotaz + data případu (JSON s case ID)
        assert "Shrni případ" in msgs[1]["content"]
        assert ctx.case_id in msgs[1]["content"]

    def test_citations_extracted_in_order(self):
        text = 'Nalezen rozpor [art:abc-123] a soubor [file:f-9]. Opakování [art:abc-123].'
        assert extract_citations(text) == ["abc-123", "f-9"]

    def test_no_citations(self):
        assert extract_citations("bez odkazů") == []


# ── validace výstupu (fail-closed) ──────────────────────────────────────────

class TestParseOutput:
    def test_valid_json(self):
        prof = AGENTS["case_analyst"]
        out = parse_output(prof, '{"summary": "Shrnutí", "open_questions": ["Kdo?"]} [art:a1]')
        assert isinstance(out, CaseAnalystOutput)
        assert out.summary == "Shrnutí"

    def test_markdown_fence(self):
        prof = AGENTS["timeline_analyst"]
        raw = '```json\n{"contradictions": [], "notes": "OK"}\n```'
        out = parse_output(prof, raw)
        assert isinstance(out, TimelineAnalystOutput)

    def test_missing_json_raises(self):
        with pytest.raises(OrchestrationError, match="JSON objekt nenalezen"):
            parse_output(AGENTS["case_analyst"], "jen proza bez jsonu")

    def test_invalid_json_raises(self):
        with pytest.raises(OrchestrationError, match="nevalidní JSON"):
            parse_output(AGENTS["case_analyst"], '{"summary": }')

    def test_schema_mismatch_raises(self):
        # summary chybí → ValidationError → OrchestrationError (fail-closed)
        with pytest.raises(OrchestrationError, match="nesedí na model"):
            parse_output(AGENTS["case_analyst"], '{"open_questions": []}')

    def test_each_agent_model_validates(self):
        samples = {
            "case_analyst": {"summary": "s"},
            "timeline_analyst": {"contradictions": [{"description": "d"}], "notes": ""},
            "artifact_analyst": {"explanation": "e", "gaps": []},
            "media_analyst": {"indicators": [], "limits": ["pixelová"]},
            "report_analyst": {"sections": [{"title": "t", "content": "c"}], "citations": ["a1"]},
        }
        for aid, payload in samples.items():
            out = parse_output(AGENTS[aid], json.dumps(payload))
            assert isinstance(out, AGENTS[aid].output_model)


# ── orchestrace (fake LLM — offline) ───────────────────────────────────────

class TestOrchestrate:
    def test_full_run_case_analyst(self, ctx):
        llm = _fake_llm({"summary": "Případ obsahuje 1 rozpor.", "open_questions": ["Kdo vlastnil zařízení?"], })
        res = orchestrate(llm, ctx, "Shrni případ")
        assert isinstance(res, AgentResult)
        assert res.agent_id == "case_analyst"
        assert res.output.summary.startswith("Případ")
        assert res.prompt_chars > 0 and res.duration_ms >= 0

    def test_explicit_agent_override(self, ctx):
        llm = _fake_llm({"explanation": "Browser history", "gaps": []})
        res = orchestrate(llm, ctx, "Shrni případ", agent_id="artifact_analyst")
        assert res.agent_id == "artifact_analyst"
        assert isinstance(res.output, ArtifactAnalystOutput)

    def test_auto_routing_media(self, ctx):
        llm = _fake_llm({"indicators": ["chybí EXIF"], "limits": []})
        res = orchestrate(llm, ctx, "Analyzuj obrázek na manipulaci")
        assert res.agent_id == "media_analyst"
        assert isinstance(res.output, MediaAnalystOutput)

    def test_citations_in_result(self, ctx):
        llm = _fake_llm({"summary": "Rozpor [art:a-1] potvrzen.", "open_questions": []})
        res = orchestrate(llm, ctx, "Shrni případ")
        assert res.citations == ["a-1"]

    def test_invalid_output_raises(self, ctx):
        llm = _fake_llm({"wrong_field": 1})
        with pytest.raises(OrchestrationError):
            orchestrate(llm, ctx, "Shrni případ")

    def test_report_analyst_citations(self, ctx):
        llm = _fake_llm(
            {"sections": [{"title": "Zjištění", "content": "Rozpor [art:a-1]"}], "citations": ["a-1"]}
        )
        res = orchestrate(llm, ctx, "Sestav podklady pro report")
        assert isinstance(res.output, ReportAnalystOutput)
        assert res.citations == ["a-1"]


# ── case context (read-only snapshot) ───────────────────────────────────────

class TestCaseContext:
    def test_snapshot_contents(self, ctx):
        assert ctx.case_id.startswith("case-")
        assert ctx.findings and ctx.findings[0]["details_json"]["description"] == "Nalezen rozpor v čase"
        assert any(a["id"] for a in ctx.sample_artifacts)

    def test_prompt_block_is_json(self, ctx):
        block = ctx.to_prompt_block()
        data = json.loads(block)  # deterministický JSON
        assert data["case"]["id"] == ctx.case_id

    def test_missing_case_raises(self, db: CaseDB):
        with pytest.raises(ValueError, match="případ neexistuje"):
            build_case_context(db, "case-000000000000")
