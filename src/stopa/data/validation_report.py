"""STOPA — Evidence Validation Reports (P0 Core, C6 / E13).

Report pro každý artefakt: parser ID+verze, validation status, confidence,
provenance; souhrn coverage (kolik artefaktů je z validovaných parserů podle
Parser Validation Registry). Čistá agregace nad DB — bez I/O mimo SQLite.
"""

from __future__ import annotations

import json
from collections import Counter

from stopa.data.db import CaseDB
from stopa.domain.benchmark import validation_coverage
from stopa.domain.validation_registry import build_registry


def _parser_id_of(artifact) -> str | None:
    """Parser ID artefaktu — z provenance (C1) nebo parser_version fallback."""
    for prov in getattr(artifact, "provenance", None) or []:
        pid = getattr(prov, "parser_id", None)
        if pid:
            return pid
    # parser_version je jen verze — bez ID ho nepočítáme do coverage
    return None


def build_validation_report(db: CaseDB, case_id: str | None = None) -> dict:
    """Sestaví validační report případu (nebo celého DB).

    Returns:
        {case_id, total_artifacts, by_status, by_parser, coverage, artifacts:[...]}
    """
    registry = build_registry()
    registry_ids = set(registry)

    if case_id:
        # artifacts nemají přímé case_id — filtr přes zdroje případu
        arts: list = []
        for src in db.list_sources(case_id):
            arts.extend(db.list_artifacts(source_id=src.id))
    else:
        arts = db.list_artifacts()
    status_counts: Counter[str] = Counter()
    parser_counts: Counter[str] = Counter()
    rows: list[dict] = []

    for a in arts:
        pid = _parser_id_of(a) or "unknown"
        status = getattr(a, "validation_status", None) or "extracted"
        status_counts[status] += 1
        parser_counts[pid] += 1
        rows.append(
            {
                "artifact_id": a.id,
                "type": a.artifact_type,
                "parser_id": pid if pid != "unknown" else None,
                "validation_status": status,
                "confidence": getattr(a, "confidence", None),
                "provenance_count": len(getattr(a, "provenance", None) or []),
            }
        )

    coverage = validation_coverage(dict(parser_counts), registry_ids)
    return {
        "case_id": case_id,
        "total_artifacts": len(arts),
        "by_status": dict(status_counts),
        "by_parser": dict(sorted(parser_counts.items())),
        "coverage": coverage,
        "artifacts": rows,
    }


def report_to_json(report: dict) -> str:
    """Deterministický JSON (sorted keys) pro export."""
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
