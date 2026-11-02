"""E11 — AI Forensic Assistant: čistá logika promptů a parsování odpovědí LM Studio.

Design (Clean Architecture):
- **bez IO** — HTTP klient žije v ``data/lmstudio_client.py``, DB lookup citací
  v web endpointu; zde jen string → string transformace, které se dají testovat
  bez spuštěného LM Studio
- tři režimy: ``nl_search`` (přirozená řeč → FTS query), ``summary`` (shrnutí
  případu), ``explain`` (vysvětlení jednoho artifactu)
- citace: model označuje artifacty inline tokenem ``[art:<id>]``; parser je
  validuje proti množině reálných ID a z textu odstraní (GUI je vykreslí jako
  klikací odkazy)

LM Studio hovoří OpenAI-kompatibilním API (default ``http://localhost:1234/v1``),
proto prompty jsou standardní chat messages.
"""

from __future__ import annotations

import json
import re
from typing import Any

# ── konstanty ────────────────────────────────────────────────────────────────

AI_MODES = ("nl_search", "summary", "explain")

#: inline citace artifactu — model píše ``[art:abc123]`` do odpovědi
CITATION_RE = re.compile(r"\[(?:art|citace):([A-Za-z0-9_-]{1,64})\]")

#: markdown code fence (```json ... ```) — LLMy rádi obalují JSON
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class AiParseError(ValueError):
    """Odpověď LM Studio se nedá rozparsovat (chybějící JSON, špatný tvar)."""


# ── prompt buildery ──────────────────────────────────────────────────────────

_FTS_SYNTAX = """STOPA search syntax (FTS5 + metadata filtry):
- text terms: words/phrases, prefix with * (e.g. "hesl*"), boolean AND/OR/NOT
- size:>1MB  / size:<5KB / size:=2GB   (file size filter)
- mtime:2026-01..2026-06 or mtime:>2026-03-15 or mtime:<2025-12-31T23:59:59
- ext:jpg  (or .pdf) — file extension filter, repeatable
- in-artifact:text — match inside extracted artifact content (e.g. chat messages)"""


def build_nl_search_prompt(question: str, case_name: str) -> list[dict[str, str]]:
    """Chat messages pro režim ``nl_search``.

    Model má vrátit JSON::

        {"query": "<STOPA FTS query>", "explanation": "...", "confidence": 0.0-1.0}
    """
    system = (
        f"You are a forensic search assistant for the STOPA case \"{case_name}\". "
        "Translate the user's natural-language question into ONE STOPA search query. "
        + _FTS_SYNTAX
        + "\nRespond with STRICT JSON only, no prose: "
        '{"query": "...", "explanation": "<one short sentence in Czech>", '
        '"confidence": <0.0-1.0 how confident you are the query matches intent>}. '
        "Use double quotes inside the query for phrases."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": question.strip()},
    ]


def build_summary_prompt(
    case_name: str,
    stats: dict[str, Any],
    artifact_stats: dict[str, int],
    sample_artifacts: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Chat messages pro režim ``summary`` — shrnutí případu z statistik.

    Citace konkrétních artifactů model označí tokenem ``[art:<id>]``.
    """
    top_types = sorted(artifact_stats.items(), key=lambda kv: -kv[1])[:8]
    types_line = ", ".join(f"{t}: {n}" for t, n in top_types) or "—"
    sample_lines = "\n".join(
        f"- [{a.get('id')}] ({a.get('artifact_type')}) {a.get('title') or ''} "
        f"@ {a.get('timestamp') or 'no-time'}"
        for a in sample_artifacts[:15]
    )
    system = (
        "You are a forensic case analyst. Summarize the STOPA case in Czech, 3-6 "
        "sentences: what was examined, key findings, notable anomalies. "
        "Cite concrete artifacts inline as [art:<id>] using ONLY ids from the sample list."
    )
    user = (
        f"Case: {case_name}\n"
        f"Stats — files: {stats.get('files', 0)}, bytes: {stats.get('bytes', 0)}, "
        f"signed: {stats.get('signed', 0)}, bad-ext: {stats.get('bad_ext', 0)}, "
        f"duplicates: {stats.get('dups', 0)}\n"
        f"Artifact types: {types_line}\n"
        f"Sample artifacts (id, type, title, timestamp):\n{sample_lines or '- none'}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_explain_prompt(artifact: dict[str, Any]) -> list[dict[str, str]]:
    """Chat messages pro režim ``explain`` — vysvětlení jednoho artifactu.

    Výstup má obsahovat inline citaci ``[art:<id>]`` na vysvětlovaný záznam.
    """
    details = json.dumps(artifact.get("details") or {}, ensure_ascii=False)[:1500]
    system = (
        "You are a forensic analyst explaining ONE artifact to an investigator in Czech. "
        "2-4 sentences: what it is, why it matters forensically, caveats (confidence). "
        "End with the citation token [art:<id>] of this exact artifact."
    )
    user = (
        f"Artifact id: {artifact.get('id')}\n"
        f"type: {artifact.get('artifact_type')}\n"
        f"title: {artifact.get('title') or '—'}\n"
        f"file: {artifact.get('rel_path') or '—'}\n"
        f"timestamp (UTC): {artifact.get('timestamp') or '—'}\n"
        f"confidence: {artifact.get('confidence')}\n"
        f"anomaly flags: {', '.join(artifact.get('anomaly_flags') or []) or 'none'}\n"
        f"details JSON: {details}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ── parsování odpovědí (čistá logika) ───────────────────────────────────────

def _extract_json(text: str) -> dict[str, Any]:
    """Vytaž první JSON objekt z odpovědi LLM (s nebo bez code fence)."""
    candidates = [m.strip() for m in _FENCE_RE.findall(text)]
    if not candidates:
        # bez fence — hledej první {...} blok (greedy od první { po poslední })
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            candidates.append(text[start : end + 1])
    for cand in candidates:
        try:
            data = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    raise AiParseError(f"žádný JSON objekt v odpovědi: {text[:120]!r}")


def parse_nl_search(text: str) -> tuple[str | None, str | None, float | None]:
    """Rozparsuj odpověď režimu ``nl_search`` → ``(query, explanation, confidence)``.

    Tolerantní k markdown fence a okolnímu prose; chybějící pole → ``None``.
    """
    data = _extract_json(text)
    query = data.get("query")
    if isinstance(query, str):
        query = query.strip() or None
    explanation = data.get("explanation")
    if not isinstance(explanation, str):
        explanation = None
    confidence = data.get("confidence")
    if isinstance(confidence, (int, float)) and 0.0 <= float(confidence) <= 1.0:
        confidence = float(confidence)
    else:
        confidence = None
    return query, explanation, confidence


def extract_citations(
    text: str, valid_ids: set[str] | dict[str, Any]
) -> tuple[str, list[str]]:
    """Validuj a vyčisti inline citace ``[art:<id>]``.

    Vrací ``(clean_text, citation_ids)`` — jen ID přítomné v ``valid_ids``
    (set nebo dict id→meta), deduplikované v pořadí prvního výskytu;
    neplatné tokeny se z textu odstraní.
    """
    valid = set(valid_ids)  # funguje pro set i dict (klíče)
    seen: list[str] = []

    def _sub(m: re.Match[str]) -> str:
        aid = m.group(1)
        if aid in valid and aid not in seen:
            seen.append(aid)
        return ""  # token z textu — GUI ho vykreslí jako odkaz

    clean = CITATION_RE.sub(_sub, text)
    clean = re.sub(r"[ \t]{2,}", " ", clean).strip()
    return clean, seen


def parse_confidence(text: str) -> float | None:
    """Volitelné ``confidence`` z odpovědi (JSON nebo „confidence: 0.8“)."""
    m = re.search(r"\"?confidence\"?\s*[:=]\s*(0(?:\.\d+)?|1(?:\.0+)?)", text)
    if not m:
        return None
    val = float(m.group(1))
    return val if 0.0 <= val <= 1.0 else None
