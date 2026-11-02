"""STOPA — Case Context (P0 Intelligence, I1).

Read-only snapshot případu pro AI agenty. Sestavuje se web/CLI vrstvou přes
``CaseDB`` a předá orchestrátorovi — čistá logika orchestrace tak DB nevidí
(Clean Architecture: jádro AI nevidí, AI čte přes read-only rozhraní).

Snapshot je omezený (max N findings / timeline událostí / artefaktů), aby se
do promptu nedostalo bezmezné množství dat.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CaseContext:
    """Read-only snapshot případu pro AI orchestraci."""

    case_id: str
    case_name: str
    stats: dict[str, int] = field(default_factory=dict)  # files/bytes/dups…
    artifact_stats: dict[str, int] = field(default_factory=dict)  # type → count
    findings: list[dict[str, Any]] = field(default_factory=list)
    timeline_events: list[dict[str, Any]] = field(default_factory=list)
    sample_artifacts: list[dict[str, Any]] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        """Deterministický textový blok pro prompt (JSON, omezené délky)."""
        return json.dumps(
            {
                "case": {"id": self.case_id, "name": self.case_name},
                "stats": self.stats,
                "artifact_types": self.artifact_stats,
                "findings": self.findings[:20],
                "timeline_events": self.timeline_events[:50],
                "sample_artifacts": self.sample_artifacts[:15],
            },
            ensure_ascii=False,
            sort_keys=True,
        )


def build_case_context(
    db: Any,  # CaseDB — bez importu (intelligence → data by byl cyklus přes web)
    case_id: str,
    *,
    max_findings: int = 20,
    max_timeline: int = 50,
    max_artifacts: int = 15,
) -> CaseContext:
    """Sestaví read-only snapshot případu z ``CaseDB``.

    Args:
        db: otevřená ``CaseDB`` (read-only přístup).
        case_id: ID případu.
        max_findings / max_timeline / max_artifacts: limity velikosti snapshotu.

    Returns:
        ``CaseContext``; prázdné pole = nic nenalezeno (ne chyba).
    """
    case = db.get_case(case_id)
    if case is None:
        raise ValueError(f"případ neexistuje: {case_id}")

    stats = db.stats() or {}
    artifact_stats = db.artifact_stats() or {}

    findings = [
        f.model_dump(mode="json") for f in db.list_findings(case_id=case_id)[:max_findings]
    ]

    timeline_events = db.list_timeline_events(limit=max_timeline) or []

    # sample artifacts — nejnovější, jen ID/type/title/timestamp (bez details)
    arts: list[dict[str, Any]] = []
    for src in db.list_sources(case_id):
        for a in db.list_artifacts(source_id=src.id, limit=max_artifacts):
            d = a.model_dump(mode="json")
            arts.append(
                {
                    "id": d.get("id"),
                    "artifact_type": d.get("artifact_type"),
                    "title": d.get("title"),
                    "timestamp": d.get("timestamp"),
                    "confidence": d.get("confidence"),
                }
            )
    arts = arts[:max_artifacts]

    return CaseContext(
        case_id=case_id,
        case_name=case.name or case_id,
        stats=stats,
        artifact_stats=artifact_stats,
        findings=findings,
        timeline_events=timeline_events,
        sample_artifacts=arts,
    )
