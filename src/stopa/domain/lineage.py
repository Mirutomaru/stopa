"""STOPA — Evidence Lineage Engine (P0 Core, C2).

Sledování původu každého zjištění: originální evidence → parser → extrahovaný
artefakt → transformace → analytická korelace → finding → report. Každý krok
je zaznamenán jako ``LineageEvent`` s verzí nástroje, konfigurací (hash),
vstupy a výstupy — zpětné dohledání tvrzení v reportu až k původnímu zdroji.

Čistá logika (model + chain traversal) bez I/O; tenká IO vrstva ``log_lineage``
žije v CaseDB (stejný vzor jako audit_log / run_correlation).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def new_lineage_id() -> str:
    """Deterministicky čitelné ID s prefixem (forenzní stopa v logech)."""
    return f"lineage-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class LineageEvent:
    """Jeden krok v řetězci důkazů — neměnný záznam (append-only).

    ``input_refs`` / ``output_refs`` jsou ID entit vyššího modelu
    (source/file/artifact/entity/correlation/finding) nebo cesty k výstupním
    souborům (report). Prázdné output_refs = kořenový krok (např. extrakce,
    jejíž artefaktová provenance žije v ``artifacts.provenance_json``).
    """

    op_type: str  # extract | correlate | finding_added | report_generated | …
    case_id: str | None = None  # None = operace nevázaná na konkrétní případ
    tool_version: str | None = None  # verze STOPA / parseru, který krok provedl
    config_hash: str | None = None  # SHA-256 normalizované konfigurace (reprodukovatelnost)
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    details_json: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=new_lineage_id)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def config_hash(config: dict[str, Any]) -> str:
    """Deterministický hash konfigurace — kanonické JSON (seřazené klíče), SHA-256.

    Stejná konfigurace → stejný hash nezávisle na pořadí klíčů v dictu.
    """
    canonical = json.dumps(config, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _refs_of(ev: LineageEvent) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return ev.input_refs, ev.output_refs


def build_chain(db: Any, ref: str) -> list[LineageEvent]:
    """Zpětné dohledání řetězce pro referenci (finding/correlation/artifact/report).

    Najde všechny kroky, jejichž ``output_refs`` obsahují ``ref``, a rekurzivně
    pokračuje po jejich ``input_refs``. Vrací události v chronologickém pořadí
    (nejstarší první) — tedy směr *zdroj → … → ref*.

    Tenká IO vrstva nad CaseDB (vzor ``run_correlation``); samotná traversální
    logika je deterministická a testovatelná bez DB.
    """
    events = db.list_lineage()  # lineage je append-only a nízkofrekvenční → plný scan stačí
    by_output: dict[str, list[LineageEvent]] = {}
    for ev in events:
        for out in _refs_of(ev)[1]:
            by_output.setdefault(out, []).append(ev)

    seen: set[str] = set()
    chain: list[LineageEvent] = []

    def visit(r: str) -> None:
        for ev in by_output.get(r, ()):  # deterministické pořadí = pořadí v DB
            if ev.id in seen:
                continue
            seen.add(ev.id)
            chain.append(ev)
            for inp in _refs_of(ev)[0]:
                visit(inp)

    visit(ref)
    chain.sort(key=lambda e: (e.created_at, e.id))  # nejstarší první = směr zdroje
    return chain


def lineage_summary(events: list[LineageEvent]) -> dict[str, Any]:
    """Shrnutí řetězce pro CLI/GUI — počty kroků podle typu + koncové refy."""
    by_type: dict[str, int] = {}
    for ev in events:
        by_type[ev.op_type] = by_type.get(ev.op_type, 0) + 1
    return {
        "steps": len(events),
        "by_op_type": by_type,
        "first_ref": events[0].input_refs[0] if events and events[0].input_refs else None,
        "last_outputs": list(events[-1].output_refs) if events else [],
    }
