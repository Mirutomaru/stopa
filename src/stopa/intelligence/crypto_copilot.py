"""K5.5 — AI Copilot pro krypto analýzu (injektovatelná LLM + deterministický fallback).

Stejný kontrakt jako F3.x: ``llm_call(prompt) -> str``; bez funkční LLM nebo při
nevalidním výstupu → deterministický fallback (stejný vstup → stejný výsledek).

LLM má vrátit JSON objekt::

    {"risk_level": "low|medium|high|critical",
     "key_findings": ["...", ...],
     "recommended_actions": ["...", ...]}

Výstup LLM je datový, ne autoritativní — validace risk_level + typy; cokoliv jiného
→ fallback. Fallback pracuje nad souhrnem K5/K3 nálezů (počty per kategorie).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

RISK_LEVELS = ("low", "medium", "high", "critical")
_MAX_ITEMS = 10


class CryptoCopilotError(Exception):
    """Chyba výstupu LLM (nevalidní JSON / schéma) → spustí fallback."""


@dataclass(frozen=True)
class CopilotResult:
    """Výsledek krypto copilotu — deterministicky serializovatelný."""

    risk_level: str  # low | medium | high | critical
    key_findings: tuple[str, ...] = ()
    recommended_actions: tuple[str, ...] = ()
    source: str = "fallback"  # llm | fallback

    def to_dict(self) -> dict:
        return asdict(self)


def build_prompt(summary: dict) -> str:
    """Deterministická šablona promptu z K5/K3 souhrnu."""
    lines = [
        "You are a crypto-forensics copilot. Analyze the findings summary and respond",
        "with a JSON object only (no prose, no code fences) with keys:",
        '  "risk_level": one of low|medium|high|critical,',
        '  "key_findings": array of at most 10 short strings,',
        '  "recommended_actions": array of at most 10 short strings.',
        "",
        "Findings summary (JSON):",
        json.dumps(summary, ensure_ascii=False, sort_keys=True),
    ]
    return "\n".join(lines)


def _parse_llm_output(raw: str) -> dict:
    """Extrahuje JSON objekt z LLM odpovědi (toleruje code fence)."""
    text = (raw or "").strip()
    if not text:
        raise CryptoCopilotError("prázdná odpověď LLM")
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    elif not (text.startswith("{") and text.endswith("}")):
        # najdi první {...} blok
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise CryptoCopilotError("odpověď LLM neobsahuje JSON objekt")
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CryptoCopilotError(f"nevalidní JSON od LLM: {exc}") from exc
    if not isinstance(data, dict):
        raise CryptoCopilotError("JSON od LLM není objekt")
    return data


def _coerce_str_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    out = [str(v).strip() for v in value[:_MAX_ITEMS] if str(v).strip()]
    return tuple(out)


def deterministic_result(summary: dict) -> CopilotResult:
    """Deterministický fallback — risk level z počtů nálezů."""
    defi = int(summary.get("defi_findings", 0) or 0)
    nft = int(summary.get("nft_findings", 0) or 0)
    bridges = int(summary.get("bridge_links", 0) or 0)
    privacy = int(summary.get("privacy_findings", 0) or 0)
    critical_sanctions = int(summary.get("critical_sanctions", 0) or 0)

    if critical_sanctions > 0:
        level = "critical"
    elif defi + nft + bridges >= 4 or privacy >= 5:
        level = "high"
    elif defi + nft + bridges >= 1 or privacy >= 2:
        level = "medium"
    else:
        level = "low"

    findings: list[str] = []
    if defi:
        findings.append(f"{defi} DeFi indikátor(ů) (protokoly/kontrakty)")
    if nft:
        findings.append(f"{nft} NFT indikátor(ů) (sbírky/marketplaces/token ids)")
    if bridges:
        findings.append(f"{bridges} cross-chain bridge propojení")
    if privacy:
        findings.append(f"{privacy} privacy coin důkaz(ů) (XMR/Zcash)")
    if critical_sanctions:
        findings.append(f"{critical_sanctions} kritických sankčních shod (K3)")
    if not findings:
        findings.append("žádné krypto indikátory nad práh")

    actions = {
        "low": ["monitorovat adresy v sankčních seznamech", "doplnit on-chain data (K3)"],
        "medium": [
            "ověřit DeFi/NFT kontraktové interakce na chaině",
            "zkoumat bridge přechody mezi řetězci",
            "kontrolovat privacy coin výdeje",
        ],
        "high": [
            "prioritně ověřit cross-chain pohyby (bridge)",
            "trhovat cluster na entity (K3 clustering)",
            "hledat off-chain důkazy (e-mail, chat) k adresám",
        ],
        "critical": [
            "imediálně provázat sankční shodu s držitelem",
            "zajistit on-chain snapshot + podpis (K4 report)",
            "notifikovat prokuraturu o kritickém riziku",
        ],
    }[level]

    return CopilotResult(
        risk_level=level,
        key_findings=tuple(findings),
        recommended_actions=tuple(actions),
        source="fallback",
    )


def run_crypto_copilot(llm_call: object | None, summary: dict) -> CopilotResult:
    """Spustí copilota; LLM volitelná (None → fallback).

    ``llm_call`` — callable ``(prompt: str) -> str`` (injektovatelné pro testy).
    Jakákoli chyba LLM/výstupu → deterministický fallback (žádná výjimka ven).
    """
    if llm_call is None:
        return deterministic_result(summary)

    try:
        raw = llm_call(build_prompt(summary))  # type: ignore[operator]
        data = _parse_llm_output(str(raw))
        level = str(data.get("risk_level", "")).strip().lower()
        if level not in RISK_LEVELS:
            raise CryptoCopilotError(f"neznámé risk_level: {level!r}")
        return CopilotResult(
            risk_level=level,
            key_findings=_coerce_str_list(data.get("key_findings")),
            recommended_actions=_coerce_str_list(data.get("recommended_actions")),
            source="llm",
        )
    except Exception:  # noqa: BLE001 — fallback je smlouva (LLM selže → deterministicky)
        return deterministic_result(summary)
