"""P4-5 — AI eval gate: zlatá suita rolí orchestrátoru (offline, deterministická).

Zlaté scénáře (``EVIDENCE`` + ``GOLDEN_RESPONSES``) přebíráme ze stávajících
testů P1-2 jako **single source of truth** — testy je importují odtud.
Gate spustí každou roli přes produkční cestu :func:`call_role` (prompt build →
validace výstupu podle ``ROLE_OUTPUT_SCHEMA``) na deterministickém klientovi,
který zlaté odpovědi přehrává. Regrese (změna promptu/schéma, která scénář
rozbití) → role ``ok=False`` a CLI exit code 1.

Plně offline: bez LM Studio, bez I/O kromě čistých funkcí domény.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from stopa.data.ai_orchestrator_service import ChatClient, OrchestratedCall, call_role
from stopa.domain.ai_orchestrator import ROLE_IDS, build_role_registry

#: Zlatý důkazní soubor (syntetický) — společný pro všechny role.
EVIDENCE: list[dict[str, Any]] = [
    {
        "id": "a1",
        "title": "SMS od anonymizované osoby",
        "text": json.dumps(
            {"address": "+420****0111", "body": "Heslo je 123456", "sent": True},
            ensure_ascii=False,
        ),
    },
    {
        "id": "a2",
        "title": "Browser history — pošta",
        "text": json.dumps(
            {"url": "https://mail.example.com/inbox", "visited_at": "2024-03-15T10:00:00Z"},
            ensure_ascii=False,
        ),
    },
]

#: Zlaté odpovědi per role — splňují ``ROLE_OUTPUT_SCHEMA`` (validace výstupů).
GOLDEN_RESPONSES: dict[str, str] = {
    "evidence": json.dumps(
        {"findings": [{"artifact_id": "a1", "note": "Zpráva obsahuje heslo."}]},
        ensure_ascii=False,
    ),
    "timeline": json.dumps(
        {
            "events": [
                {
                    "timestamp": "2024-03-15T10:00:00Z",
                    "description": "Odeslání SMS.",
                    "citation": "[art:a1]",
                }
            ]
        },
        ensure_ascii=False,
    ),
    "network": json.dumps(
        {
            "entities": [{"id": "e1", "type": "ip", "value": "192.168.1.10"}],
            "edges": [{"src": "e1", "dst": "e2", "rel": "connects_to"}],
        },
    ),
    "memory": json.dumps(
        {"matches": [{"needle": "flag{test}", "offset": 4096, "context": "..."}]},
    ),
    "intelligence": json.dumps(
        {
            "enrichments": [
                {"entity": "8.8.8.8", "type": "ip", "tactic_id": "TA0010", "note": "exfil"}
            ]
        },
    ),
    "hypothesis": json.dumps(
        {
            "statement": "Uživatel poslal soubor přes e-mail.",
            "confidence": 0.7,
            "citations": ["a1"],
        },
        ensure_ascii=False,
    ),
    "report": json.dumps(
        {
            "title": "Forenzní zpráva — případ C123",
            "sections": [{"heading": "Nálezy", "body": "Viz citace [art:a1]."}],
        },
        ensure_ascii=False,
    ),
    "qa": json.dumps({"verdict": "pass", "issues": []}),
}


@dataclass(frozen=True)
class RoleEvalResult:
    """Výsledek gate pro jednu roli."""

    role_id: str
    ok: bool
    attempts: int
    tokens_out: int
    error: str | None


class GoldenClient:
    """Deterministický klient — přehrává zlaté odpovědi per role (offline).

    Role se rozpozná podle system promptu v messages (každá má unikátní
    text ze ``build_role_registry()``); při neshodě → ``ValueError``.
    Volitelný ``override`` umožňuje simulovat regresi u vybrané role.
    """

    def __init__(self, override: dict[str, str] | None = None) -> None:
        self._override = dict(override or {})

    def chat(
        self, messages: list[dict[str, str]], max_tokens: int | None = None, *, temperature: float | None = None
    ) -> str:
        role_id = _role_from_messages(messages)
        if role_id in self._override:
            return self._override[role_id]
        try:
            return GOLDEN_RESPONSES[role_id]
        except KeyError as exc:
            raise ValueError(f"GoldenClient: chybí zlatá odpověď pro roli {role_id!r}") from exc


def _role_from_messages(messages: list[dict[str, str]]) -> str:
    """Rozpozná ID role podle system promptu (deterministické, offline)."""
    sys_prompt = messages[0]["content"] if messages else ""
    for rid, role in build_role_registry().items():
        if role.system_prompt and role.system_prompt in sys_prompt:
            return rid
    raise ValueError(f"GoldenClient: system prompt neodpovídá žádné roli ({sys_prompt[:60]!r})")


def run_gold_suite(client: ChatClient | None = None) -> list[RoleEvalResult]:
    """Spustí zlatou suitu přes produkční cestu (``call_role``).

    ``ok`` per role = strukturovaný výstup prošel validací ``ROLE_OUTPUT_SCHEMA``.
    Deterministická: jeden pokus per role, bez živého LM Studio. Výjimka z
    volání role se chytá a hlásí (gate má reportovat, ne crashovat).
    """
    cli = client if client is not None else GoldenClient()
    results: list[RoleEvalResult] = []
    for rid in ROLE_IDS:
        try:
            call: OrchestratedCall = call_role(rid, "", EVIDENCE, client=cli)
        except Exception as exc:  # noqa: BLE001 — gate hlásí libovolnou chybu role
            results.append(
                RoleEvalResult(role_id=rid, ok=False, attempts=0, tokens_out=0, error=str(exc))
            )
            continue
        if call.payload is None:
            results.append(
                RoleEvalResult(
                    role_id=rid,
                    ok=False,
                    attempts=call.attempts,
                    tokens_out=call.tokens_out,
                    error="výstup nesplňuje ROLE_OUTPUT_SCHEMA",
                )
            )
        else:
            results.append(
                RoleEvalResult(rid, True, call.attempts, call.tokens_out, None)  # type: ignore[arg-type]
            )
    return results


def suite_summary(results: list[RoleEvalResult]) -> dict[str, Any]:
    """Shrnutí suity pro CLI/Web (``failed`` = role se selháním, deterministické pořadí)."""
    failed = [r.role_id for r in results if not r.ok]
    return {
        "suite": "gold",
        "total": len(results),
        "passed": sum(1 for r in results if r.ok),
        "failed": failed,
        "results": [
            {
                "role_id": r.role_id,
                "ok": r.ok,
                "attempts": r.attempts,
                "tokens_out": r.tokens_out,
                "error": r.error,
            }
            for r in results
        ],
    }
