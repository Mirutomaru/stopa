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
from stopa.intelligence.legal_docs import (
    INTEGRITY_MARKER,
    LEGAL_DOC_TYPES,
    LegalDocError,
    LegalDocResult,
    generate_legal_doc,
    verify_legal_doc,
)
from stopa.intelligence.nl_query import (
    DEFAULT_TIMEOUT_S,
    MAX_ROWS_HARD_CAP,
    InvalidQueryError,
    NLQueryError,
    NLQueryResult,
    QueryTimeoutError,
    build_schema_context,
    execute_sandboxed,
    known_tables,
    run_nl_query,
)
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
from stopa.intelligence.tool_agent import (
    GroundingError,
    MaxStepsError,
    ReActStep,
    ToolAgentError,
    ToolAgentResult,
    run_tool_agent,
)
from stopa.intelligence.triage import (
    CSAM_MEDIA,
    EXFILTRATION,
    INSIDER_THREAT,
    PROFILES,
    RANSOMWARE,
    MatchedSignal,
    ProfileReport,
    SignalSpec,
    TriageProfile,
    evaluate_profile,
    get_profile,
    run_triage,
)

__all__ = [
    "AGENTS",
    "CSAM_MEDIA",
    "DEFAULT_TIMEOUT_S",
    "EXFILTRATION",
    "INSIDER_THREAT",
    "INTEGRITY_MARKER",
    "LEGAL_DOC_TYPES",
    "MAX_ROWS_HARD_CAP",
    "PROFILES",
    "RANSOMWARE",
    "AgentProfile",
    "AgentResult",
    "ArtifactAnalystOutput",
    "CaseAnalystOutput",
    "CaseContext",
    "GroundingError",
    "InvalidQueryError",
    "LegalDocError",
    "LegalDocResult",
    "MatchedSignal",
    "MaxStepsError",
    "MediaAnalystOutput",
    "NLQueryError",
    "NLQueryResult",
    "OrchestrationError",
    "ProfileReport",
    "QueryTimeoutError",
    "RagChunk",
    "RagContext",
    "ReActStep",
    "ReportAnalystOutput",
    "SignalSpec",
    "TimelineAnalystOutput",
    "ToolAgentError",
    "ToolAgentResult",
    "TriageProfile",
    "audit_ai_query",
    "build_case_context",
    "build_schema_context",
    "chunk_markdown",
    "evaluate_profile",
    "execute_sandboxed",
    "generate_legal_doc",
    "get_profile",
    "known_tables",
    "load_doc_layer",
    "orchestrate",
    "prompt_hash",
    "retrieve",
    "route_agent",
    "run_nl_query",
    "run_tool_agent",
    "run_triage",
    "sanitize_fts_query",
    "technical_registry_chunks",
    "verify_legal_doc",
]
