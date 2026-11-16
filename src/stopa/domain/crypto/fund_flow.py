"""K4.4 — Fund Flow Diagram: D3-kompatibilní JSON + self-contained HTML/SVG render.

Vstup = K3 ``TxGraph`` (uzly + orientované hrany s částkami) + risk skóre
(bundlované OFAC/EU listy, offline). Výstup je plně deterministický:

- kategorie uzlu ze sankčních tagů (mixer > darknet_market > exchange > unknown);
- layout = kruh seřazený podle ``out_amount`` desc → id (bez náhodnosti,
  bez externího force-directed algoritmu — offline-first);
- HTML = samostatný soubor (SVG + minimální JS zoom), žádný CDN.

Metrika KPI: render < 5 s pro 1000 transakcí (test ``TestFundFlowPerf``).
"""

from __future__ import annotations

import html as _html
import math

from pydantic import BaseModel, Field

from stopa.domain.crypto.onchain_models import TxGraph
from stopa.domain.crypto.risk_scoring import RiskScore, score_addresses

#: Priorita tagů při více shodách (mixer má přednost — nejvyšší entropie toku).
_CATEGORY_PRIORITY = ("mixer", "darknet_market", "exchange")
_TAG_TO_CATEGORY = {"mixer": "mixer", "darknet_market": "darknet", "exchange": "exchange"}

#: Barvy kategorií (legend + SVG fill) — stabilní, testované.
CATEGORY_COLORS: dict[str, str] = {
    "mixer": "#8e44ad",
    "darknet": "#c0392b",
    "exchange": "#f39c12",
    "unknown": "#7f8c8d",
}


class FlowNode(BaseModel):
    """Uzel fund-flow grafu (adresa + statistiky + kategorie + souřadnice)."""

    id: str
    category: str = "unknown"
    risk_score: int = 0
    risk_level: str = "none"
    in_amount: int = 0
    out_amount: int = 0
    tx_in: int = 0
    tx_out: int = 0
    x: float | None = None
    y: float | None = None


class FlowLink(BaseModel):
    """Agregovaná hrana (src→dst, součet částek všech paralelních transakcí)."""

    source: str
    target: str
    value: int = 0


class FlowDiagram(BaseModel):
    """Fund-flow diagrama — uzly + agregované hrany."""

    nodes: list[FlowNode] = Field(default_factory=list)
    links: list[FlowLink] = Field(default_factory=list)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def link_count(self) -> int:
        return len(self.links)


def category_for(risk: RiskScore) -> str:
    """Kategorie adresy ze sankčních tagů (priorita mixer > darknet > exchange)."""
    tags: set[str] = set()
    for e in risk.entries:
        tags.update(e.tags or [])
    for tag in _CATEGORY_PRIORITY:
        if tag in tags:
            return _TAG_TO_CATEGORY[tag]
    return "unknown"


def build_fund_flow(
    graph: TxGraph, risks: dict[str, RiskScore] | None = None
) -> FlowDiagram:
    """Sestaví fund-flow diagramu z K3 grafu + risk skóre.

    ``risks`` lze injektovat (testy); default = bundlované listy pro všechny uzly.
    Layout je deterministický kruh seřazený podle ``(-out_amount, id)``.
    """
    if risks is None:
        risks = score_addresses(list(graph.nodes))

    ordered = sorted(
        graph.nodes.items(), key=lambda kv: (-kv[1].out_amount, kv[0])
    )
    n = len(ordered)
    nodes: list[FlowNode] = []
    for i, (addr, stats) in enumerate(ordered):
        risk = risks.get(addr, RiskScore(address=addr, score=0, level="none"))
        x: float | None = None
        y: float | None = None
        if n == 1:
            x, y = 0.0, 0.0
        elif n > 1:
            radius = 50.0 + 12.0 * math.sqrt(n)
            angle = -math.pi / 2 + 2.0 * math.pi * i / n
            x = round(radius * math.cos(angle), 2)
            y = round(radius * math.sin(angle), 2)
        nodes.append(
            FlowNode(
                id=addr,
                category=category_for(risk),
                risk_score=risk.score,
                risk_level=risk.level,
                in_amount=stats.in_amount,
                out_amount=stats.out_amount,
                tx_in=stats.tx_in,
                tx_out=stats.tx_out,
                x=x,
                y=y,
            )
        )

    # paralelní hrany agregujeme na (src,dst) — součástka = součet; pořadí stabilní
    agg: dict[tuple[str, str], int] = {}
    for e in graph.edges:
        if not e.src or not e.dst:
            continue
        key = (e.src, e.dst)
        agg[key] = agg.get(key, 0) + max(0, e.amount)
    links = [
        FlowLink(source=k[0], target=k[1], value=v) for k, v in sorted(agg.items())
    ]
    return FlowDiagram(nodes=nodes, links=links)


def to_d3_json(diagram: FlowDiagram) -> dict:
    """D3.js force-layout vstupní formát (``d3.forceSimulation(data.nodes)…``)."""
    return {
        "nodes": [
            {
                "id": nd.id,
                "category": nd.category,
                "risk_score": nd.risk_score,
                "in_amount": nd.in_amount,
                "out_amount": nd.out_amount,
            }
            for nd in diagram.nodes
        ],
        "links": [
            {"source": lk.source, "target": lk.target, "value": lk.value}
            for lk in diagram.links
        ],
    }


def render_html(diagram: FlowDiagram, title: str = "STOPA — Fund Flow") -> str:
    """Self-contained HTML (SVG + inline JS wheel-zoom), deterministický výstup."""
    t = _html.escape(title)
    w = h = 900
    cx, cy = w / 2, h / 2

    parts: list[str] = []
    max_value = max((lk.value for lk in diagram.links), default=0) or 1

    def _pos(addr: str) -> tuple[float, float]:
        for nd in diagram.nodes:
            if nd.id == addr:
                return (cx + (nd.x or 0.0), cy + (nd.y or 0.0))
        return (cx, cy)

    for lk in diagram.links:
        x1, y1 = _pos(lk.source)
        x2, y2 = _pos(lk.target)
        width = max(1.0, min(8.0, 1.0 + 7.0 * lk.value / max_value))
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#bdc3c7" stroke-width="{width:.1f}"/>'
        )

    for nd in diagram.nodes:
        if nd.x is None or nd.y is None:
            continue
        x, y = cx + nd.x, cy + nd.y
        color = CATEGORY_COLORS.get(nd.category, CATEGORY_COLORS["unknown"])
        label = _html.escape(nd.id[:12] + ("…" if len(nd.id) > 12 else ""))
        stroke = "#e74c3c" if nd.risk_level in ("high", "critical") else "none"
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="{color}" '
            f'stroke="{stroke}" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{x + 9:.1f}" y="{y - 6:.1f}" font-size="10" '
            f'font-family="monospace">{label}</text>'
        )

    legend = " ".join(
        f'<span style="display:inline-block;width:12px;height:12px;background:{c};'
        f'margin-right:4px"></span>{name}'
        for name, c in CATEGORY_COLORS.items()
    )
    nodes_svg = "\n".join(parts)
    zoom_js = (
        "(function(){var s=document.getElementById('ff'),k=1;"
        "s.addEventListener('wheel',function(e){e.preventDefault();"
        "k=Math.min(8,Math.max(.2,k*(e.deltaY<0?1.1:.9)));"
        f"s.setAttribute('viewBox',( {cx} - {cx}/k)+' '+( {cy} - {cy}/k)"
        f"+' '+({w}/k)+' '+({h}/k));}});}})();"
    )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="cs">\n<head>\n<meta charset="utf-8"/>\n'
        f"<title>{t}</title>\n</head>\n<body style=\"margin:0;background:#1a1d23;\">\n"
        f'<h2 style="color:#ecf0f1;font-family:sans-serif;padding:12px;margin:0 0 4px">{t}'
        f' <small>({diagram.node_count} uzlů, {diagram.link_count} hran)</small></h2>\n'
        f'<div style="padding:0 12px;color:#95a5a6;font-size:12px">{legend}</div>\n'
        '<svg id="ff" xmlns="http://www.w3.org/2000/svg" width="' + str(w) + '" height="' + str(h) + '">\n'
        f"{nodes_svg}\n</svg>\n"
        f"<script>{zoom_js}</script>\n"
        "</body>\n</html>\n"
    )
