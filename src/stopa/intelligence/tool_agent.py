"""STOPA — AI Tool Agent (F3.1, Fáze 3).

ReAct agent s tool-use nad živým case DB: LLM plánuje kroky (thought →
action/params), runtime spustí nástroj a vrátí observation; smyčka končí na
``final_answer`` nebo ``max_steps``. Nad deklarativními profily z P0 I1 —
tenhle agent **ne** volá LLM jednou, ale iteruje s přístupem k datům.

Nástroje (deterministické, bez nových externích závislostí):
- ``search_fts``        — FTS5 full-text search nad case DB
- ``get_timeline``      — materializovaná timeline (filtry čas/typ/anomalie)
- ``resolve_entity``    — kanonické entity + korelace pro zadanou hodnotu
- ``run_yara``          — deterministický signature scanner (K1 crypto vzory:
                         WIF, BTC/ETH adresy, BIP-39 seed; řádková reportace)
- ``generate_hypothesis`` — strukturovaná hypotéza s grounding validací citací

AK F3.1: agent vyřeší testovací případy (scripted LLM = deterministicky);
každá akce v audit logu (append-only hash chain přes ``db.log_operation``);
grounding validuje 100 % citací ve final answer (fail-closed).

``llm_call`` je injektovatelný callable ``(messages, max_tokens) -> str`` —
celý agent se testuje offline bez LM Studio (stejný vzor jako ai_orchestrator).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, ValidationError, model_validator

from stopa.data.db import CaseDB
from stopa.intelligence.ai_orchestrator import extract_citations

logger = logging.getLogger(__name__)


# ── výjimky ──────────────────────────────────────────────────────────────────


class ToolAgentError(Exception):
    """Chyba ReAct smyčky (nevalidní LLM krok, neznámý nástroj…)."""


class GroundingError(ToolAgentError):
    """Final answer cituje artefakt/soubor, který v case DB neexistuje.

    AK F3.1: grounding validuje 100 % citací — jediná nevalidní citace =
    fail-closed (auditovatelné).
    """


class MaxStepsError(ToolAgentError):
    """Smyčka dosáhla ``max_steps`` bez final_answer."""


# ── výstupní model jednoho LLM kroku (fail-closed validace) ─────────────────


class ReActStep(BaseModel):
    """Jeden krok agenta: myšlenka + buď akce, nebo finální odpověď.

    Kontrakt pro LLM (viz ``REACT_SYSTEM_PROMPT``): přesně jeden z
    ``action`` / ``final_answer`` je nenulový. Nevalidní JSON/konflikt =
    ``ToolAgentError`` (auditovatelné v kroku).
    """

    thought: str = Field(min_length=1, description="Interní úvaha agenta")
    action: str | None = Field(default=None, description="Název nástroje")
    params: dict[str, Any] = Field(default_factory=dict)
    final_answer: str | None = Field(
        default=None, description="Finální odpověď s citacemi [art:<id>]"
    )

    @model_validator(mode="after")
    def _xor(self) -> ReActStep:
        if (self.action is None) == (self.final_answer is None):
            raise ValueError("přesně jeden z action / final_answer musí být nastaven")
        return self


# ── nástroje ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolSpec:
    """Deklarativní popis jednoho nástroje (prompt + runtime handler)."""

    name: str
    description: str  # pro LLM prompt
    params: dict[str, str]  # param → popis (JSON schema v promptu)
    handler: Callable[[CaseDB, str, dict[str, Any]], Any]  # (db, case_id, params)


class ToolError(Exception):
    """Chyba jednoho nástroje (observation pro LLM — smyčka může opravit)."""


def _iso(value: Any, name: str) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ToolError(f"{name}: očekávám ISO 8601 datetimes, dostal jsem {value!r}") from exc


def _int_param(params: dict[str, Any], name: str, default: int) -> int:
    value = params.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ToolError(f"{name}: očekávám kladné celé číslo, dostal jsem {value!r}")
    return value


def _tool_search_fts(db: CaseDB, case_id: str, params: dict[str, Any]) -> list[dict]:
    query = params.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolError("search_fts: 'query' (neprázdný text) je povinné")
    limit = _int_param(params, "limit", 20)
    recs = db.search(query, None, limit)
    return [
        {
            "id": r.id,
            "name": r.name,
            "rel_path": r.rel_path,
            "size_bytes": r.size_bytes,
        }
        for r in recs
    ]


def _tool_get_timeline(db: CaseDB, case_id: str, params: dict[str, Any]) -> list[dict]:
    limit = _int_param(params, "limit", 50)
    events = db.list_timeline_events(
        source_id=params.get("source_id"),
        event_type=params.get("event_type"),
        from_ts=_iso(params.get("from_ts"), "from_ts"),
        to_ts=_iso(params.get("to_ts"), "to_ts"),
        anomalies_only=bool(params.get("anomalies_only", False)),
        limit=limit,
    )
    out: list[dict] = []
    for e in events:
        ts = e.get("ts_utc") or e.get("timestamp")
        out.append(
            {
                "event_id": e.get("id"),
                "artifact_id": e.get("artifact_id"),
                "ts": str(ts) if ts else "",
                "type": e.get("event_type") or e.get("artifact_type"),
                "title": e.get("title"),
                "source_file": e.get("rel_path"),
                "anomaly_flags": e.get("anomaly_flags") or [],
            }
        )
    return out


def _tool_resolve_entity(db: CaseDB, case_id: str, params: dict[str, Any]) -> dict:
    value = params.get("value")
    if not isinstance(value, str) or not value.strip():
        raise ToolError("resolve_entity: 'value' (neprázdný text) je povinné")
    kind = params.get("kind")

    entities = db.list_entities(case_id)
    needle = value.strip().lower()
    matches = [
        e
        for e in entities
        if (kind is None or e.get("kind") == kind)
        and (needle in str(e.get("value", "")).lower())
    ]

    correlations = db.list_correlations(case_id)
    matched_ids = {m.get("id") for m in matches}
    rels = [
        c
        for c in correlations
        if c.get("entity_a") in matched_ids or c.get("entity_b") in matched_ids
    ]
    return {"matches": matches, "correlations": rels[:20]}


# ── run_yara: deterministický signature scanner (bez yara-python) ───────────

#: WIF = Base58Check 51–52 znaků (verze 0x8 → první znak obvykle K/L/M/N/2-9)
_WIF_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{51,52}\b")
_BTC_RE = re.compile(r"\b(?:bc1[a-z0-9]{25,60}|[13][A-HJ-NP-Za-km-z1-9]{25,39})\b")
_ETH_RE = re.compile(r"\b0x[0-9a-fA-F]{40}\b")


def _scan_rules(text: str) -> list[dict]:
    """Spustí všechny vestavěné pravidla nad textem → řádkové matche."""
    from stopa.domain.crypto.seeds import detect_in_text

    findings: list[dict] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        for m in _WIF_RE.finditer(line):
            findings.append({"rule": "wif_private_key", "line": line_no, "match": m.group(0)})
        for m in _BTC_RE.finditer(line):
            findings.append({"rule": "btc_address", "line": line_no, "match": m.group(0)})
        for m in _ETH_RE.finditer(line):
            findings.append({"rule": "eth_address", "line": line_no, "match": m.group(0)})
    try:
        for sm in detect_in_text(text):
            findings.append(
                {
                    "rule": "bip39_seed",
                    "line": 1,  # detekce je tokenová (sliding window) — řádek se neukládá
                    "match": f"({sm.length} slov)",
                    "fingerprint": sm.fingerprint_sha256[:12],
                }
            )
    except Exception:
        logger.debug("run_yara: bip39 detekce selhala", exc_info=True)
    return findings


def _tool_run_yara(db: CaseDB, case_id: str, params: dict[str, Any]) -> dict:
    content = params.get("content")
    file_path = params.get("file_path")
    if isinstance(content, str) and content:
        text = content
    elif isinstance(file_path, str) and file_path:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read(1_000_000)  # omezení velikosti (scanner není pro obrazy)
        except OSError as exc:
            raise ToolError(f"run_yara: nelze číst {file_path!r} ({exc})") from exc
    else:
        raise ToolError("run_yara: 'content' nebo 'file_path' je povinné")

    max_matches = _int_param(params, "max_matches", 100)
    findings = _scan_rules(text)[:max_matches]
    return {"matches": findings, "rules_applied": ["wif_private_key", "btc_address", "eth_address", "bip39_seed"]}


def _tool_generate_hypothesis(db: CaseDB, case_id: str, params: dict[str, Any]) -> dict:
    claim = params.get("claim")
    if not isinstance(claim, str) or not claim.strip():
        raise ToolError("generate_hypothesis: 'claim' (neprázdný text) je povinné")

    support = [s for s in params.get("support", []) if isinstance(s, str)]
    against = [a for a in params.get("against", []) if isinstance(a, str)]

    # grounding: 100 % citovaných artefaktů musí existovat v case DB (fail-closed)
    missing = sorted({i for i in support + against if db.get_artifact(i) is None})
    if missing:
        raise ToolError(f"generate_hypothesis: neexistující artefakty: {missing}")

    # confidence: podíl citace na celkovém počtu artifactů případu (0.1–0.9)
    total = db.artifact_stats().get("total", 0) or len(support + against) or 1
    coverage = min(1.0, (len(support) - len(set(missing))) / max(total, 1))
    confidence = round(min(0.9, max(0.1, 0.2 + coverage * 0.7)), 2)
    return {
        "claim": claim.strip(),
        "support": support,
        "against": against,
        "confidence": confidence,
        "evidence_total_in_case": total,
    }


def build_tools() -> list[ToolSpec]:
    """Výchozí sada nástrojů F3.1 (5 toolů z ROADMAP)."""

    return [
        ToolSpec(
            name="search_fts",
            description=(
                "Full-text search nad soubory případu (FTS5). Vrátí seznam souborů "
                "(id, název, cesta, velikost) seřazených podle relevance."
            ),
            params={"query": "text dotazu (FTS5 termíny, prefix *, AND/OR/NOT)", "limit": "max výsledků (default 20)"},
            handler=_tool_search_fts,
        ),
        ToolSpec(
            name="get_timeline",
            description=(
                "Časová osa případu z materializované tabulky. Filtry: časový rozsah, "
                "typ události, jen anomálie."
            ),
            params={
                "from_ts": "ISO 8601 začátek (volitelné)",
                "to_ts": "ISO 8601 konec (volitelné)",
                "event_type": "filtr typu události (volitelné)",
                "anomalies_only": "true = jen události s anomaly_flags",
                "limit": "max událostí (default 50)",
            },
            handler=_tool_get_timeline,
        ),
        ToolSpec(
            name="resolve_entity",
            description=(
                "Dohledání kanonické entity podle hodnoty (substring, case-insensitive) "
                "+ její korelace s ostatními entitami."
            ),
            params={"value": "hodnota entity (e-mail, telefon, adresa…)", "kind": "filtr typu entity (volitelné)"},
            handler=_tool_resolve_entity,
        ),
        ToolSpec(
            name="run_yara",
            description=(
                "Deterministický signature scanner nad textem: WIF privátní klíče, "
                "BTC/ETH adresy, BIP-39 seed phrase. Vrátí řádkové matche."
            ),
            params={
                "content": "text ke skenování (volitelné)",
                "file_path": "cesta k souboru do 1 MB (volitelné)",
                "max_matches": "max matchů (default 100)",
            },
            handler=_tool_run_yara,
        ),
        ToolSpec(
            name="generate_hypothesis",
            description=(
                "Vytvoří strukturovanou hypotézu s citacemi na artefakty (grounding: "
                "všechny citace musí existovat) a heuristickou confidence."
            ),
            params={
                "claim": "tvrzení hypotézy",
                "support": "seznam ID artefaktů podporujících [art:<id>]",
                "against": "seznam ID artefaktů proti",
            },
            handler=_tool_generate_hypothesis,
        ),
    ]


# ── prompt sestavení ─────────────────────────────────────────────────────────

REACT_SYSTEM_PROMPT = """Jsi forenzní AI agent STOPA. Řešíš dotaz uživatele pomocí nástrojů (ReAct smyčka).

Formát odpovědi — PŘESNĚ jeden JSON objekt na řádek, bez markdown fence:
- krok s akcí: {"thought": "...", "action": "<název nástroje>", "params": {...}}
- finální odpověď: {"thought": "...", "final_answer": "..."}

Pravidla:
1. Nejdříve sbírej důkady nástroji, teprve pak formuluj závěr.
2. Finální odpověď cituje konkrétní artefakty tokeny [art:<id>] a soubory [file:<id>].
3. Každá citace musí odkazovat na skutečný záznam (grounding validaci provede runtime).
4. Odpovícej v češtině, stručně, s jasným závěrem."""


def _tools_block(tools: list[ToolSpec]) -> str:
    lines = ["Dostupné nástroje:"]
    for t in tools:
        params_json = json.dumps(t.params, ensure_ascii=False)
        lines.append(f"- {t.name}: {t.description} Parametry (popis): {params_json}")
    return "\n".join(lines)


# ── JSON extrakce LLM výstupu (stejná tolerance jako ai_orchestrator) ───────


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ToolAgentError(f"JSON objekt nenalezen v odpovědi LLM: {raw[:200]!r}")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ToolAgentError(f"nevalidní JSON v kroku agenta ({exc})") from exc
    if not isinstance(data, dict):
        raise ToolAgentError("očekávám JSON objekt (dict)")
    return data


# ── audit kroků + výsledek ───────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentStep:
    """Jeden krok ReAct smyčky (auditovatelný záznam)."""

    step_no: int
    thought: str
    action: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    observation_chars: int | None = None  # None = finální krok
    duration_ms: float = 0.0
    audit_row_id: int | None = None


@dataclass(frozen=True)
class ToolAgentResult:
    """Výsledek běhu agenta (auditovatelný)."""

    question: str
    final_answer: str
    steps: list[AgentStep]
    llm_calls: int
    prompt_chars_total: int
    duration_ms: float
    grounding_total: int  # počet citací ve final answer


# ── ReAct smyčka ─────────────────────────────────────────────────────────────


def _ground_check(db: CaseDB, answer: str) -> tuple[int, list[str]]:
    """Grounding validace: vrací (počet citací, seznam nevalidních)."""
    citations = extract_citations(answer)
    invalid: list[str] = []
    for cid in citations:
        if db.get_artifact(cid) is None and not _file_exists(db, cid):
            invalid.append(cid)
    return len(citations), invalid


def _file_exists(db: CaseDB, file_id: str) -> bool:
    row = db.conn.execute("SELECT 1 FROM files WHERE id = ?", (file_id,)).fetchone()
    return row is not None


def run_tool_agent(
    llm_call: Callable[[list[dict[str, str]], int], str],
    db: CaseDB,
    case_id: str,
    question: str,
    *,
    tools: list[ToolSpec] | None = None,
    actor: str | None = None,
    max_steps: int = 8,
    redact_pii: bool = True,
) -> ToolAgentResult:
    """Spustí ReAct smyčku agenta nad živým case DB.

    Args:
        llm_call: ``(messages, max_tokens) -> text odpovědi`` (IO vrstva;
            testovatelně injektovatelná — offline bez LM Studio).
        db: CaseDB s načteným případem.
        case_id: ID případu (entity korelace jsou per-case).
        question: dotaz uživatele.
        tools: sada nástrojů (default = ``build_tools()``).
        actor: atribuce audit logu (explicitní > case examiner, viz STP-022).
        max_steps: limit kroků smyčky (bez final_answer → ``MaxStepsError``).
        redact_pii: maskovat PII v messages před každým LLM voláním (default ON).

    Returns:
        ``ToolAgentResult`` s finální odpovědí, kroky a auditními metadaty.

    Raises:
        ToolAgentError: nevalidní JSON/krok od LLM.
        GroundingError: final answer cituje neexistující záznam (100 % validace).
        MaxStepsError: smyčka dosáhla limitu kroků bez finální odpovědi.
    """
    tool_list = tools if tools is not None else build_tools()
    registry: dict[str, ToolSpec] = {t.name: t for t in tool_list}
    messages: list[dict[str, str]] = [
        {"role": "system", "content": REACT_SYSTEM_PROMPT + "\n\n" + _tools_block(tool_list)},
        {"role": "user", "content": f"Dotaz: {question}"},
    ]

    steps: list[AgentStep] = []
    prompt_chars_total = 0
    t_start = time.monotonic()
    final_answer: str | None = None

    for step_no in range(1, max_steps + 1):
        if redact_pii:
            from stopa.domain.pii_redaction import redact_messages

            messages, _ = redact_messages(messages)

        t0 = time.monotonic()
        raw = llm_call(messages, 2048)
        duration_ms = (time.monotonic() - t0) * 1000.0
        prompt_chars_total += sum(len(m["content"]) for m in messages)

        data = _extract_json_object(raw)
        try:
            step = ReActStep.model_validate(data)
        except ValidationError as exc:
            raise ToolAgentError(f"krok {step_no}: nevalidní ReAct krok ({exc.error_count()} chyb)") from exc

        # audit: KAŽDÁ akce do logu (append-only hash chain — AK F3.1)
        obs: dict[str, Any] = {}
        observation_chars: int | None = None
        if step.action is not None and step.action not in registry:
            obs = {"ok": False, "error": f"neznámý nástroj: {step.action}"}
            observation_chars = len(json.dumps(obs))
        elif step.action is not None:
            try:
                result = registry[step.action].handler(db, case_id, step.params)
                obs = {"ok": True, "result": result}
            except ToolError as exc:
                obs = {"ok": False, "error": str(exc)}
            observation_chars = len(json.dumps(obs, ensure_ascii=False, default=str))

        audit_row_id: int | None = None
        if step.action is not None:
            audit_row_id = db.log_operation(
                action="ai_agent_action",
                actor=actor,
                details={
                    "step": step_no,
                    "tool": step.action,
                    "params": step.params,
                    "observation_chars": observation_chars,
                    "thought": step.thought[:200],
                },
            )

        if step.final_answer is not None:
            steps.append(
                AgentStep(
                    step_no=step_no,
                    thought=step.thought,
                    action=None,
                    params={},
                    observation_chars=None,
                    duration_ms=duration_ms,
                    audit_row_id=audit_row_id,
                )
            )
            final_answer = step.final_answer
            break

        steps.append(
            AgentStep(
                step_no=step_no,
                thought=step.thought,
                action=step.action,
                params=dict(step.params),
                observation_chars=observation_chars,
                duration_ms=duration_ms,
                audit_row_id=audit_row_id,
            )
        )
        messages.append(
            {
                "role": "user",
                "content": f"Krok {step_no} — Observation:\n{json.dumps(obs, ensure_ascii=False, default=str)[:4000]}",
            }
        )

    if final_answer is None:
        raise MaxStepsError(f"smyčka dosáhla limitu {max_steps} kroků bez final_answer")

    total_citations, invalid = _ground_check(db, final_answer)
    if invalid:
        raise GroundingError(
            f"grounding selhalo — nevalidní citace ve finální odpovědi: {invalid}"
        )

    return ToolAgentResult(
        question=question,
        final_answer=final_answer,
        steps=steps,
        llm_calls=len(steps),
        prompt_chars_total=prompt_chars_total,
        duration_ms=(time.monotonic() - t_start) * 1000.0,
        grounding_total=total_citations,
    )
