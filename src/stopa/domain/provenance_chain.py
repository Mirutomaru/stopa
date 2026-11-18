"""P0-1 — Evidence Provenance Engine: řetězec provenience jednoho artefaktu.

Čistá logika bez I/O — vstupy jsou normalizované řádky z datové vrstvy
(files / sources / custody_items / analysis_operations / lineage_events),
které připraví ``data.provenance_repository.ProvenanceRepository``.

Řetězec = nabytí zdroje → vyhasování souboru → extrakce (operace) → artefakt,
plus volitelný odkaz na nadřazený (odvozený) artefakt a související lineage
události. Souhrnná zpráva rozlišuje:

- ``gaps`` — tvrdé mezery v řetězci (řetězec je neúplný),
- ``warnings`` — měkké mezery např. u legacy řádků bez ``hashed_at``
  (před schématem v21), které nesnižují formální úplnost, ale signalizují
  slabší důkazní sílu.

Krok se vrací chronologicky; při stejném časovém razítku rozhoduje priorita
druhu kroku (acquisition → file_hash → operation → lineage → parent_link),
tj. výsledek je deterministický nezávisle na pořadí vstupních řádků.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

# Priorita druhu kroku při stejném časovém razítku (deterministické řazení).
_KIND_ORDER: dict[str, int] = {
    "acquisition": 0,
    "file_hash": 1,
    "operation": 2,
    "lineage": 3,
    "parent_link": 4,
}


@dataclass(frozen=True)
class ProvenanceStep:
    """Jedna prověřená spojka řetězce (v reportu chronologicky seřazené)."""

    kind: str  # acquisition | file_hash | operation | lineage | parent_link
    description: str
    timestamp: str | None = None  # ISO UTC; None = čas neznámý
    tool_version: str | None = None
    config_hash: str | None = None


@dataclass(frozen=True)
class ProvenanceChain:
    """Rekonstruovaný řetězec provenience artefaktu + zpráva o úplnosti."""

    artifact_id: str
    steps: tuple[ProvenanceStep, ...] = field(default_factory=tuple)
    gaps: tuple[str, ...] = field(default_factory=tuple)  # tvrdé mezery → neúplný
    warnings: tuple[str, ...] = field(default_factory=tuple)  # měkké mezery

    @property
    def complete(self) -> bool:
        return not self.gaps


def build_provenance(
    *,
    artifact_id: str,
    file_row: Mapping[str, Any] | None = None,
    source_row: Mapping[str, Any] | None = None,
    custody_row: Mapping[str, Any] | None = None,
    operations: Sequence[Mapping[str, Any]] = (),
    lineage_events: Sequence[Mapping[str, Any]] = (),
    parent_artifact_id: str | None = None,
    parent_exists: bool | None = None,  # None = žádný odkaz; True/False = existuje nadřazený?
) -> ProvenanceChain:
    """Sestaví řetězec provenience a zprávu o úplnosti.

    Chybová sémantika: typový nesoulad vstupu → ``TypeError``; semantické
    mezery se hromadí do ``gaps``/``warnings`` (žádná výjimka).
    """
    if not isinstance(artifact_id, str) or not artifact_id:
        raise TypeError("artifact_id musí být neprázdný řetězec")

    steps: list[ProvenanceStep] = []
    gaps: list[str] = []
    warnings: list[str] = []

    # --- nabytí zdroje -----------------------------------------------------
    if source_row is None:
        gaps.append("missing_source")
    else:
        ts = (custody_row or {}).get("acquired_at") or source_row.get("added_at")
        desc = f"{source_row.get('kind', 'unknown')}: {source_row.get('path', '?')}"
        custodian = (custody_row or {}).get("custodian")
        if custodian:
            desc += f" (custodian: {custodian})"
        steps.append(
            ProvenanceStep(
                kind="acquisition",
                description=desc,
                timestamp=ts,
                tool_version=(custody_row or {}).get("tool_version"),
            )
        )

    # --- vyhasování souboru -------------------------------------------------
    sha256 = str((file_row or {}).get("sha256") or "").strip()
    if not sha256:
        gaps.append("missing_file_hash")
    else:
        hashed_at = (file_row or {}).get("hashed_at")
        if not hashed_at:
            warnings.append("hash_without_timestamp")  # legacy řádek před v21
        steps.append(
            ProvenanceStep(
                kind="file_hash",
                description=f"SHA-256 {sha256[:12]}…",
                timestamp=hashed_at,
            )
        )

    # --- metadata nabytí (custody) ------------------------------------------
    if source_row is not None:
        cust = custody_row or {}
        has_meta = any(str(cust.get(k) or "").strip() for k in ("acquisition_tool", "verified_hash"))
        if custody_row is None or not has_meta:
            warnings.append("acquisition_metadata_missing")

    # --- operace (extrakce a další) ------------------------------------------
    extracts = 0
    for op in operations:
        op_type = str(op.get("op_type") or "")
        if op_type.startswith("extract"):
            extracts += 1
        steps.append(
            ProvenanceStep(
                kind="operation",
                description=f"{op_type} {op.get('id', '?')}",
                timestamp=op.get("created_at"),
                tool_version=op.get("stopa_version"),
                config_hash=op.get("config_hash"),
            )
        )
    if source_row is not None and extracts == 0:
        gaps.append("no_extraction_in_lineage")

    # --- lineage události (souvisící s artefaktem/souborem/zdrojem) -----------
    for ev in lineage_events:
        steps.append(
            ProvenanceStep(
                kind="lineage",
                description=f"lineage {ev.get('id', '?')} ({ev.get('op_type', '?')})",
                timestamp=ev.get("created_at"),
                tool_version=ev.get("tool_version"),
                config_hash=ev.get("config_hash"),
            )
        )

    # --- odvozený artefakt (parent link) --------------------------------------
    if parent_artifact_id:
        if parent_exists is False:
            gaps.append("broken_parent_link")
        steps.append(
            ProvenanceStep(
                kind="parent_link",
                description=f"odvozeno z artefaktu {parent_artifact_id}",
            )
        )

    # Deterministické chronologické řazení (tie-break: priorita druhu, popis).
    steps.sort(key=lambda s: (s.timestamp or "", _KIND_ORDER.get(s.kind, 9), s.description))
    return ProvenanceChain(
        artifact_id=artifact_id,
        steps=tuple(steps),
        gaps=tuple(gaps),
        warnings=tuple(warnings),
    )


def provenance_report(chain: ProvenanceChain) -> dict[str, Any]:
    """JSON-serializovatelná zpráva (CLI --json / Web endpoint)."""
    return {
        "artifact_id": chain.artifact_id,
        "complete": chain.complete,
        "gaps": list(chain.gaps),
        "warnings": list(chain.warnings),
        "step_count": len(chain.steps),
        "steps": [asdict(s) for s in chain.steps],
    }
