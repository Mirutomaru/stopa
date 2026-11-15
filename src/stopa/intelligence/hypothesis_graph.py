"""Hypothesis Graph (F3.5) — AI generuje graf hypotéz, člověk potvrzuje/vyvrací.

Uzel = claim + důkazy PRO/PROTI (ID artefaktů → lineage k důkazu) + confidence
(0.1–0.9, interval interpretace). Strom podhypotéz přes ``parent_id``.

Navázání na existující infrastrukturu:
- **F3.2 triage** — deterministický fallback: každý detekovaný profil = hypotéza
  (claim z template, důkazy = evidence ID signálů).
- grounding jako v F3.1 ``generate_hypothesis`` — citované artefakty musí existovat
  v case DB; neexistující se vyřadí (fail-soft) a počítají se do statistik.
- LLM je injektovatelná (``llm_call(prompt) -> str``, JSON výstup) → offline testy.

AK F3.5: graf v UI ✓ (web modul Hypothesis Graph); lineage k artifactům ✓
(``graph_payload()["lineage"]`` rozřeší citace na artefakty); export PDF/JSON ✓.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from stopa.data.db import CaseDB
from stopa.intelligence.triage import run_triage

_logger = logging.getLogger(__name__)

#: Maximální počet uzlů v jednom grafu (AI nesmí explodovat).
MAX_NODES = 20
#: Confidence je interval interpretace — nikdy „jistota“ (0.1–0.9 jako F3.1).
MIN_CONFIDENCE = 0.1
MAX_CONFIDENCE = 0.9
#: Kolik důkazů na stranu (pro/proti) se ukládá do uzlu.
EVIDENCE_CAP_PER_SIDE = 25

LLMCall = Callable[[str], str]


class HypothesisGraphError(Exception):
    """Chyba generování grafu (např. neplatný JSON výstup LLM)."""


@dataclass
class HypothesisNode:
    """Uzel grafu hypotéz (před uložením i po něm)."""

    claim: str
    confidence: float = 0.5
    status: str = "pending"  # pending | confirmed | refuted
    support: list[str] = field(default_factory=list)  # ID artefaktů — důkazy PRO
    against: list[str] = field(default_factory=list)  # ID artefaktů — důkazy PROTI
    id: str = ""  # přiřazeno při ukládání (new_id("hyp"))
    parent_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "claim": self.claim,
            "confidence": self.confidence,
            "status": self.status,
            "support": list(self.support),
            "against": list(self.against),
            "parent_id": self.parent_id,
        }


def _clamp_confidence(value: Any) -> float:
    """Clamp na [0.1, 0.9]; nečíselné → 0.5."""
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.5
    return round(min(MAX_CONFIDENCE, max(MIN_CONFIDENCE, c)), 2)


def _existing_artifacts(db: CaseDB, ids: list[str]) -> tuple[list[str], int]:
    """Fail-soft grounding: (existující ID v pořadí, počet vyřazených duplikátů/neplatných)."""
    seen: set[str] = set()
    kept: list[str] = []
    dropped = 0
    for i in ids:
        if not isinstance(i, str) or i in seen:
            dropped += 1
            continue
        if db.get_artifact(i) is None:
            dropped += 1
            continue
        seen.add(i)
        kept.append(i)
    return kept[:EVIDENCE_CAP_PER_SIDE], dropped


def _llm_prompt(db: CaseDB, case_id: str) -> str:
    """Prompt pro LLM: kontext případu + požadovaný JSON formát."""
    stats = db.artifact_stats() or {}
    triage_lines = []
    for rep in run_triage(db, case_id):
        if rep.detected:
            triage_lines.append(f"- {rep.profile.title}: skóre {rep.score} ({rep.signal_summary})")
    context = "\n".join(triage_lines) or "- žádné detekované triage profily"
    return (
        "Jsi forenzní analytik. Na základě kontextu případu STOPA vygeneruj graf hypotéz.\n"
        f"Případ: {case_id}; artefaktů v případě: {stats.get('total', 0)}; zdrojů: "
        f"{db.conn.execute('SELECT COUNT(*) FROM sources WHERE case_id = ?', (case_id,)).fetchone()[0]}\n"
        f"Triage signály:\n{context}\n\n"
        "Vrať POUZE JSON pole objektů (max 20), každý s klíči:\n"
        '- "claim": text hypotézy (str)\n'
        '- "support": [ID artefaktů — důkazy PRO]\n'
        '- "against": [ID artefaktů — důkazy PROTI]\n'
        '- "confidence": 0.1–0.9 (volitelné, default 0.5)\n'
        '- "parent": index staršího uzlu v poli = podhypotéza (volitelné)\n'
        "ID artefaktů musí odpovídat ID z kontextu/signálů."
    )


def _parse_llm_graph(db: CaseDB, raw: str) -> tuple[list[HypothesisNode], dict[str, Any]]:
    """Parsování + validace JSON výstupu LLM. Vrací (uzly, statistika)."""
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        raise HypothesisGraphError(f"LLM nevrátila platný JSON: {e}") from e
    if not isinstance(data, list):
        raise HypothesisGraphError("LLM výstup musí být JSON pole uzlů")

    entries: list[tuple[int, HypothesisNode]] = []  # (pozice v JSON poli, uzel)
    dropped_citations = 0
    for src_idx, item in enumerate(data[:MAX_NODES]):
        if not isinstance(item, dict):
            continue
        claim = item.get("claim")
        if not isinstance(claim, str) or not claim.strip():
            continue
        support_raw = [x for x in (item.get("support") or []) if isinstance(x, str)]
        against_raw = [x for x in (item.get("against") or []) if isinstance(x, str)]
        support, d1 = _existing_artifacts(db, support_raw)
        against, d2 = _existing_artifacts(db, against_raw)
        dropped_citations += d1 + d2
        entries.append(
            (
                src_idx,
                HypothesisNode(
                    claim=claim.strip(),
                    confidence=_clamp_confidence(item.get("confidence", 0.5)),
                    support=support,
                    against=against,
                ),
            )
        )

    # parent odkazy: LLM používá index v JSON poli → mapujeme na pozici uzlu.
    kept_pos = {src_idx: pos for pos, (src_idx, _) in enumerate(entries)}
    nodes = [node for _, node in entries]
    for src_idx, node in entries:
        item = data[src_idx]
        parent_raw = item.get("parent") if isinstance(item, dict) else None
        if (
            isinstance(parent_raw, int)
            and not isinstance(parent_raw, bool)
            and 0 <= parent_raw < src_idx
            and parent_raw in kept_pos
        ):
            node.parent_id = f"__idx:{kept_pos[parent_raw]}"

    stats = {"nodes": len(nodes), "dropped_citations": dropped_citations}
    return nodes, stats


def _fallback_graph(db: CaseDB, case_id: str) -> tuple[list[HypothesisNode], dict[str, Any]]:
    """Deterministický fallback bez LLM: detekované triage profily → hypotézy."""
    nodes: list[HypothesisNode] = []
    for rep in run_triage(db, case_id):
        if not rep.detected:
            continue
        support: list[str] = []
        seen: set[str] = set()
        for m in rep.matched:
            for eid in m.evidence_ids:
                if eid not in seen:
                    seen.add(eid)
                    support.append(eid)
        nodes.append(
            HypothesisNode(
                claim=rep.hypothesis(case_id),
                confidence=_clamp_confidence(0.5 + 0.1 * len(rep.matched)),
                support=support[:EVIDENCE_CAP_PER_SIDE],
            )
        )
    return nodes, {"nodes": len(nodes), "dropped_citations": 0}


def build_hypothesis_graph(db: CaseDB, case_id: str, llm_call: LLMCall | None = None) -> list[HypothesisNode]:
    """Sestaví graf hypotéz (AI, případně deterministický fallback).

    ``llm_call`` — injektovatelné volání LLM ``(prompt) -> str`` (JSON výstup);
    bez něj (nebo při selhání) běží fallback na triage profilech F3.2.
    """
    if llm_call is not None:
        try:
            nodes, _stats = _parse_llm_graph(db, llm_call(_llm_prompt(db, case_id)))
            return nodes
        except HypothesisGraphError:
            raise  # fail-closed: volající se může rozhodnout pro fallback/422
        except Exception:
            _logger.debug("LLM graf hypotéz selhal, používám triage fallback", exc_info=True)
    return _fallback_graph(db, case_id)[0]


def store_graph(
    db: CaseDB,
    case_id: str,
    nodes: list[HypothesisNode],
    source: str = "fallback",
) -> list[str]:
    """Uloží uzly do case DB (pořadí zachováno; parent index → ID). Vrací ID."""
    ids: list[str] = []
    for node in nodes[:MAX_NODES]:
        parent_id: str | None = None
        if isinstance(node.parent_id, str) and node.parent_id.startswith("__idx:"):
            pidx = int(node.parent_id.split(":", 1)[1])
            if 0 <= pidx < len(ids):
                parent_id = ids[pidx]
        ids.append(
            db.add_hypothesis(
                case_id,
                node.claim,
                confidence=node.confidence,
                support=list(node.support),
                against=list(node.against),
                parent_id=parent_id,
            )
        )
    if ids:
        # doplnit ID zpět na objekty (pro volatele)
        for node, hid in zip(nodes[: len(ids)], ids):
            node.id = hid
    db.log_operation(
        "hypothesis_graph_generated",
        details={"source": source, "nodes": len(ids), "case_id": case_id},
    )
    return ids


def graph_payload(db: CaseDB, case_id: str) -> dict[str, Any]:
    """Kompletní graf pro UI/export: uzly + hrany + lineage k artefaktům.

    ``lineage[hyp_id]`` = rozřešené důkazy (artifact_type + title) — AK F3.5
    „lineage k artifactům“. Neexistující citace se vyřadí (fail-soft).
    """
    rows = db.list_hypotheses(case_id)

    def _resolve(ids: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i in ids:
            art = db.get_artifact(i)
            if art is not None:
                out.append(
                    {
                        "id": art.id,
                        "artifact_type": art.artifact_type,
                        "title": art.title or "",
                    }
                )
        return out

    nodes = [
        {
            "id": r["id"],
            "claim": r["claim"],
            "confidence": r["confidence"],
            "status": r["status"],
            "support": r["support"],
            "against": r["against"],
            "parent_id": r["parent_id"],
        }
        for r in rows
    ]
    edges: list[dict[str, str]] = []
    lineage: dict[str, Any] = {}
    by_id = {r["id"]: r for r in rows}
    for n in nodes:
        if n["parent_id"] and n["parent_id"] in by_id:
            edges.append({"source": n["id"], "target": n["parent_id"], "type": "parent"})
        for side, art_ids in (("support", n["support"]), ("against", n["against"])):
            lineage.setdefault(n["id"], {})[side] = _resolve(art_ids)
            for a in lineage[n["id"]][side]:
                edges.append({"source": n["id"], "target": a["id"], "type": side})
    return {"case_id": case_id, "nodes": nodes, "edges": edges, "lineage": lineage}


def export_graph_json(db: CaseDB, case_id: str) -> str:
    """Export grafu do JSON (AK F3.5)."""
    payload = graph_payload(db, case_id)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _graph_html(payload: dict[str, Any]) -> str:
    rows = []
    for n in payload["nodes"]:
        sup = ", ".join(a["id"] for a in payload["lineage"].get(n["id"], {}).get("support", [])) or "—"
        agn = ", ".join(a["id"] for a in payload["lineage"].get(n["id"], {}).get("against", [])) or "—"
        rows.append(
            "<tr>"
            f"<td>{_esc(n['claim'])}</td>"
            f"<td>{n['confidence']:.2f}</td>"
            f"<td class='status-{_esc(n['status'])}'>{_esc(n['status'])}</td>"
            f"<td class='mono small'>{sup}</td>"
            f"<td class='mono small'>{agn}</td>"
            "</tr>"
        )
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>body{font-family:DejaVu Sans,sans-serif;font-size:10pt}"
        "table{width:100%;border-collapse:collapse}th,td{border:1px solid #999;"
        "padding:4px;text-align:left;vertical-align:top}th{background:#eee}"
        ".status-confirmed{color:#1a7f37;font-weight:bold}.status-refuted{color:#c62828;font-weight:bold}"
        ".mono{font-family:monospace}.small{font-size:8pt}</style></head><body>"
        f"<h2>Hypothesis Graph — případ {payload['case_id']}</h2>"
        "<table><tr><th>Claim</th><th>Confidence</th><th>Status</th><th>Důkazy PRO (artefakty)</th>"
        "<th>Důkazy PROTI (artefakty)</th></tr>" + "".join(rows) + "</table></body></html>"
    )


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def export_graph_pdf(db: CaseDB, case_id: str, out_path: Any) -> None:
    """Export grafu do PDF (WeasyPrint lazy — volitelná závislost)."""
    from pathlib import Path

    html_doc = _graph_html(graph_payload(db, case_id))
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]  # lazy — volitelná závislost
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "WeasyPrint není nainstalován (pip install weasyprint) — PDF export nedostupný"
        ) from e
    HTML(string=html_doc).write_pdf(str(Path(out_path)))


__all__: list[str] = [
    "EVIDENCE_CAP_PER_SIDE",
    "MAX_CONFIDENCE",
    "MAX_NODES",
    "MIN_CONFIDENCE",
    "HypothesisGraphError",
    "HypothesisNode",
    "build_hypothesis_graph",
    "export_graph_json",
    "export_graph_pdf",
    "graph_payload",
    "store_graph",
]
