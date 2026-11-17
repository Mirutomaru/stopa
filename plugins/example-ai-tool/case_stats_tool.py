"""Ukázkový plugin F6.4 — vlastní AI tool pro F3.1 agent framework.

Kontrakt dle ``docs/PLUGINS_API.md``: factory ``build_tools()`` vrací
``list[ToolSpec]`` (kontrakt ``stopa.intelligence.tool_agent.ToolSpec``).
Handler podpis: ``(db, case_id, params) -> Any`` (JSON-serializovatelné).

Ukázkový tool: **artifact_type_breakdown** — rozložení artefaktů podle typu
(s deterministickým řazením a explicitní kapcí pro transparentnost LLMu).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from stopa.data.db import CaseDB
from stopa.intelligence.tool_agent import ToolError, ToolSpec

#: Kapce skenu (transparency v odpovědi — 'truncated' flag)
DEFAULT_LIMIT = 2000
MAX_LIMIT = 10_000


def _tool_artifact_type_breakdown(
    db: CaseDB, case_id: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Rozložení artefaktů podle artifact_type (s kapcí)."""
    limit = int(params.get("limit", DEFAULT_LIMIT))
    if not 1 <= limit <= MAX_LIMIT:
        raise ToolError(f"limit: očekávám 1..{MAX_LIMIT}, dostal jsem {limit!r}")
    arts = db.list_artifacts(limit=limit)  # CaseDB je per-case — case_id v podpisu pro konzistenci ToolSpec kontraktu
    counts = Counter(a.artifact_type for a in arts)
    return {
        "total_scanned": len(arts),
        "truncated": len(arts) >= limit,
        "by_type": dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def build_tools() -> list[ToolSpec]:
    """Vrátí AI tools dodávané tímto pluginem."""
    return [
        ToolSpec(
            name="artifact_type_breakdown",
            description=(
                "Počty artefaktů podle typu v case (deterministické řazení, "
                f"kapce {DEFAULT_LIMIT} — flag truncated signalizuje ořez). "
                "Vhodné pro první přehled obsahu obrazu."
            ),
            params={
                "limit": f"max. počet artefaktů ke skenu (1..{MAX_LIMIT}, default {DEFAULT_LIMIT})",
            },
            handler=_tool_artifact_type_breakdown,
        )
    ]
