"""STOPA — Unified Evidence Model (P0 Core, C1).

Jednotný datový model pro analytické moduly: provenance artefaktů, derived
findings a 5-úrovňové rozlišení důvěryhodnosti zjištění (AI grounding).

Čistá logika — bez I/O, bez sítě; Pydantic v2 boundary modely. Žádné importy
z ``stopa.models`` (aby models.py mohl naopak importovat odtud bez cyklu).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_finding_id() -> str:
    """Deterministicky čitelné ID s prefixem (forenzní stopa v logech)."""
    return f"finding-{uuid.uuid4().hex[:12]}"


class ConfidenceLevel(str, Enum):
    """5-úrovňové rozlišení zjištění — AI grounding (§5.3 zadání).

    AI nesmí prezentovat domněnku jako skutečnost: každé tvrzení nese přesně
    jednu úroveň a GUI/odpovědi ji vykreslují explicitně.
    """

    DIRECT = "direct"  # přímo extrahovaný údaj (parser výstup)
    DERIVED = "derived"  # deterministická transformace (korelace, agregace)
    INTERPRETATION = "interpretation"  # analytická interpretace (člověk/agent)
    HYPOTHESIS = "hypothesis"  # AI hypotéza
    UNVERIFIED = "unverified"  # neověřená informace (cizí zdroj, import)


class Provenance(BaseModel):
    """Původ jednoho zjištění/artefaktu — doložitelnost až k důkaznímu zdroji.

    Minimální sady podle zadání §4.1: identifikace parseru + verze, čas
    extrakce, reference na zdrojový záznam/offset (pokud dostupné), stav
    validace a kvalita/omezení extrakce.
    """

    source_id: str | None = None  # evidence source (None = např. AI observation)
    file_id: str | None = None  # původní soubor (FileRecord.id)
    offset: int | None = Field(default=None, ge=0)  # offset do souboru
    record_ref: str | None = None  # reference na zdrojový záznam (řádek/klíč/event ID)
    parser_id: str  # identifikátor parseru (Parser Validation Registry)
    parser_version: str  # verze extraktoru, který údaj vygeneroval
    extracted_at: datetime | None = Field(default_factory=_utcnow)
    validation_status: str = "extracted"  # extracted | validated | needs_validation
    quality_notes: str | None = None  # kvalita a omezení extrakce (volitelné)


class Finding(BaseModel):
    """Derived finding / analytical observation — výsledek analýzy nad artefakty.

    Každé zjištění musí mít alespoň jeden Provenance záznam (doložitelnost),
    jinak není forenzně použitelné (§4.1 zadání).
    """

    id: str = Field(default_factory=new_finding_id)
    case_id: str
    kind: str  # correlation | anomaly | contradiction | ai_observation | …
    confidence_level: ConfidenceLevel = ConfidenceLevel.DERIVED
    provenance: list[Provenance] = Field(default_factory=list)
    details_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)

    @model_validator(mode="after")
    def _require_provenance(self) -> Finding:
        if not self.provenance:
            raise ValueError(
                f"Finding {self.id} bez provenance — doložitelnost je povinná (§4.1)"
            )
        return self
