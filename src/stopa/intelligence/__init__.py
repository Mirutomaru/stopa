"""STOPA — AI Forensic Intelligence Engine (P0 Intelligence, I1).

Multi-agent analytika nad jádrem STOPA. Čistá logika bez I/O: deklarativní
agent profile (5×), Pydantic výstupní modely a orchestrátor (routing + prompt
+ validace výstupu). IO vrstva = ``data/lmstudio_client.py`` (injektovaná jako
callable), takže celá intelligence se dá testovat bez spuštěného LM Studio.

Architektura: viz ``docs/STOPA_AI_ARCHITECTURE.md`` §2.
"""

from stopa.intelligence.agents import (
    AGENTS,
    AgentProfile,
    ArtifactAnalystOutput,
    CaseAnalystOutput,
    MediaAnalystOutput,
    ReportAnalystOutput,
    TimelineAnalystOutput,
)
from stopa.intelligence.ai_orchestrator import (
    AgentResult,
    OrchestrationError,
    orchestrate,
    route_agent,
)
from stopa.intelligence.case_context import CaseContext, build_case_context
from stopa.intelligence.rag import (
    RagChunk,
    RagContext,
    audit_ai_query,
    chunk_markdown,
    load_doc_layer,
    prompt_hash,
    retrieve,
    sanitize_fts_query,
    technical_registry_chunks,
)

__all__ = [
    "AGENTS",
    "AgentProfile",
    "AgentResult",
    "ArtifactAnalystOutput",
    "CaseAnalystOutput",
    "CaseContext",
    "MediaAnalystOutput",
    "OrchestrationError",
    "RagChunk",
    "RagContext",
    "ReportAnalystOutput",
    "TimelineAnalystOutput",
    "audit_ai_query",
    "build_case_context",
    "chunk_markdown",
    "load_doc_layer",
    "orchestrate",
    "prompt_hash",
    "retrieve",
    "route_agent",
    "sanitize_fts_query",
    "technical_registry_chunks",
]
