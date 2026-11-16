"""K4.5 — SWGDE-kompatibilní krypto report generátor (10 sekcí).

Vstup = ``CaseDB`` + volitelně on-chain transakce z K3 TxCache (fund-flow sekce).
Sekce jsou deterministicky plněné z DB artefaktů, K3 risk scoringu a audit logu:

    1. Executive Summary          6. Exchange Correlation
    2. Wallet Discovery           7. Entity Attribution
    3. Address Inventory          8. Risk Assessment
    4. Transaction Timeline       9. Methodology
    5. Fund Flow Analysis         10. Chain of Custody

Formáty: ``md`` (default), ``html`` (self-contained, bez CDN), ``json``
(strukturovaná data). Ed25519 podpis + SHA-256 dle legal_docs konvencí;
bez kryptografického backendu = graceful degradation (podpis None, digest zůstává).
"""

from __future__ import annotations

import hashlib
import html as _html
from pathlib import Path

from pydantic import BaseModel, Field

#: Kanonické 10 sekcí SWGDE reportu (klíč → anglický titulek dle specifikace).
REPORT_SECTIONS: tuple[tuple[str, str], ...] = (
    ("executive_summary", "Executive Summary"),
    ("wallet_discovery", "Wallet Discovery"),
    ("address_inventory", "Address Inventory"),
    ("transaction_timeline", "Transaction Timeline"),
    ("fund_flow_analysis", "Fund Flow Analysis"),
    ("exchange_correlation", "Exchange Correlation"),
    ("entity_attribution", "Entity Attribution"),
    ("risk_assessment", "Risk Assessment"),
    ("methodology", "Methodology"),
    ("chain_of_custody", "Chain of Custody"),
)

#: Mapování chain labelů (stejné jako v CLI cmd_onchain — presentation nesmí
#: importovat cli, proto lokální kopie).
_CHAIN_MAP = {
    "bitcoin": "btc",
    "btc": "btc",
    "bitcoin-cash": "btc",
    "ethereum": "eth",
    "eth": "eth",
    "bsc": "eth",
    "polygon": "eth",
}

_MAX_TABLE_ROWS = 50


class CryptoReportData(BaseModel):
    """Strukturovaná data krypto reportu (základ všech formátů)."""

    case_id: str
    stopa_version: str = "1.0.0"
    sections: dict[str, str] = Field(default_factory=dict)  # klíč → markdown text
    stats: dict[str, int] = Field(default_factory=dict)


class CryptoReportResult(BaseModel):
    """Výsledek generování reportu (obsah + integrity podpis)."""

    case_id: str
    format: str  # md | html | json
    content: str
    sha256_hex: str | None = None
    signature_b64: str | None = None
    public_key_b64: str | None = None
    stats: dict[str, int] = Field(default_factory=dict)


def _collect_addresses(db) -> dict[str, str]:
    """Adresy z crypto artefaktů → {addr: chain} (unikační, stabilní pořadí)."""

    def norm(chain: object) -> str:
        return _CHAIN_MAP.get(str(chain or "").lower(), "unknown")

    addrs: dict[str, str] = {}
    for art in db.list_artifacts(artifact_type="crypto_detection"):
        d = art.details if isinstance(art.details, dict) else {}
        for a in d.get("addresses", []) or []:
            raw = a.get("raw_value")
            if raw and raw not in addrs:
                addrs[raw] = norm(a.get("chain"))
    for art in db.list_artifacts(artifact_type="crypto_wallet"):
        d = art.details if isinstance(art.details, dict) else {}
        for w in d.get("wallets", []) or []:
            chain = norm(w.get("chain"))
            for raw in w.get("public_addresses", []) or []:
                if raw and raw not in addrs:
                    addrs[raw] = chain
    return addrs


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def build_crypto_report_data(
    db,
    case_id: str,
    *,
    txs_by_addr: dict[str, list] | None = None,
    stopa_version: str = "1.0.0",
) -> CryptoReportData:
    """Sestaví data všech 10 sekcí z DB (čistá čtení + injektovatelné TX)."""
    from stopa.domain.crypto.fund_flow import build_fund_flow, to_d3_json
    from stopa.domain.crypto.risk_scoring import score_addresses
    from stopa.domain.crypto.tx_graph import build_graph

    addrs = _collect_addresses(db)
    scores = score_addresses(list(addrs)) if addrs else {}
    wallet_arts = db.list_artifacts(artifact_type="crypto_wallet")
    exchange_arts = db.list_artifacts(artifact_type="crypto_exchange_record")

    level_counts: dict[str, int] = {"none": 0, "high": 0, "critical": 0}
    for s in scores.values():
        if s.level in level_counts:
            level_counts[s.level] += 1
    high_risk = [s for s in scores.values() if s.level in ("high", "critical")]

    all_txs: list = []
    if txs_by_addr:
        seen: set[str] = set()
        for lst in txs_by_addr.values():
            for t in lst or []:
                if t.txid not in seen:
                    seen.add(t.txid)
                    all_txs.append(t)

    # ── 1. Executive Summary ────────────────────────────────────────
    lines = [
        f"Case **{case_id}** — crypto analysis by STOPA {stopa_version}.",
        "",
        _md_table(
            ["Metric", "Value"],
            [
                ["Wallets discovered", str(len(wallet_arts))],
                ["Crypto addresses total", str(len(addrs))],
                ["Addresses high/critical risk", f"{level_counts['high']}/{level_counts['critical']}"],
                ["Exchange records", str(len(exchange_arts))],
                ["On-chain transactions (cached)", str(len(all_txs))],
            ],
        ),
    ]

    # ── 2. Wallet Discovery ─────────────────────────────────────────
    if wallet_arts:
        lines_wallet = [f"{len(wallet_arts)} wallet artifact(s):", ""]
        for a in wallet_arts[:_MAX_TABLE_ROWS]:
            lines_wallet.append(f"- **{a.title}** (source: {a.source_id})")
        if len(wallet_arts) > _MAX_TABLE_ROWS:
            lines_wallet.append(f"… +{len(wallet_arts) - _MAX_TABLE_ROWS} more")
    else:
        lines_wallet = ["No wallet artifacts found in this case."]

    # ── 3. Address Inventory ────────────────────────────────────────
    if addrs:
        rows = []
        scored = [(a, scores[a]) for a in sorted(addrs)]  # invariant: všechny adresy jsou skórovány
        for addr, s in sorted(scored, key=lambda p: (-p[1].score, p[0])):
            if len(rows) >= _MAX_TABLE_ROWS:
                break
            rows.append(
                [
                    f"`{addr}`",
                    addrs[addr],
                    str(s.score if s else 0),
                    (s.level if s else "none"),
                    "; ".join(s.reasons[:2] if s else []) or "—",
                ]
            )
        inv = _md_table(["Address", "Chain", "Score", "Level", "Top reasons"], rows[:_MAX_TABLE_ROWS])
        if len(rows) > _MAX_TABLE_ROWS:
            inv += f"\n\n… +{len(rows) - _MAX_TABLE_ROWS} more addresses (full list in JSON format)."
    else:
        inv = "No crypto addresses detected."

    # ── 4. Transaction Timeline ─────────────────────────────────────
    if all_txs:
        tx_rows = []
        for t in sorted(all_txs, key=lambda t: (t.timestamp or 0, t.txid))[:_MAX_TABLE_ROWS]:
            def _short(a: str | None) -> str:
                if not a:
                    return "?"
                return a[:16] + ("…" if len(a) > 16 else "")

            date = _iso_date(t.timestamp)
            ins = ", ".join(_short(i.address) for i in t.inputs[:3])
            outs = ", ".join(_short(o.address) for o in t.outputs[:3])
            tx_rows.append([f"`{t.txid}`", date, str(t.total_in), ins, outs])
        timeline = _md_table(["TxID", "Date", "Amount (sats/wei)", "Inputs (≤3)", "Outputs (≤3)"], tx_rows)
    else:
        timeline = (
            "No cached on-chain transactions. Run `stopa onchain <case>` to fetch "
            "(opt-in API keys) or seed the TxCache, then regenerate this report."
        )

    # ── 5. Fund Flow Analysis ───────────────────────────────────────
    if all_txs:
        graph = build_graph(all_txs)
        diagram = build_fund_flow(graph, risks=scores)
        d3 = to_d3_json(diagram)
        cat_counts: dict[str, int] = {}
        for nd in diagram.nodes:
            cat_counts[nd.category] = cat_counts.get(nd.category, 0) + 1
        flow_lines = [
            (f"Graph: **{diagram.node_count} nodes**, **{diagram.link_count} aggregated links** ")
            + f"(from {len(all_txs)} transactions).",
            "",
            "Node categories (sanction tags): " + ", ".join(
                f"{k}={v}" for k, v in sorted(cat_counts.items())
            ),
            "",
            "<details><summary>D3 JSON (force-layout input)</summary>",
            "",
            "```json",
            _d3_json_compact(d3),
            "```",
            "</details>",
        ]
    else:
        flow_lines = ["No cached transactions — fund-flow diagram unavailable."]

    # ── 6. Exchange Correlation ─────────────────────────────────────
    if exchange_arts:
        exch_lines = [f"{len(exchange_arts)} exchange record(s):", ""]
        for a in exchange_arts[:_MAX_TABLE_ROWS]:
            exch_lines.append(f"- **{a.title}**")
        if len(exchange_arts) > _MAX_TABLE_ROWS:
            exch_lines.append(f"… +{len(exchange_arts) - _MAX_TABLE_ROWS} more")
    else:
        exch_lines = ["No exchange CSV records in this case."]

    # ── 7. Entity Attribution ───────────────────────────────────────
    entities: dict[str, set[str]] = {}
    for s in scores.values():
        for e in s.entries:
            if e.entity:
                entities.setdefault(e.entity, set()).update(e.tags or [])
    if entities:
        attr_lines = [f"{len(entities)} sanctioned entit(y/ies) matched:", ""]
        rows = []
        for name in sorted(entities):
            s_entry = next(
                (s for s in scores.values() if any(e.entity == name for e in s.entries)), None
            )
            rows.append([f"**{name}**", "; ".join(sorted(entities[name])), str(s_entry.score if s_entry else 0)])
        attr_lines.append(_md_table(["Entity", "Tags", "Score"], rows))
    else:
        attr_lines = ["No matches against bundled OFAC/EU sanction entities."]

    # ── 8. Risk Assessment ──────────────────────────────────────────
    risk_lines = [
        (f"Risk distribution — none: **{level_counts['none']}**, high: ")
        + f"**{level_counts['high']}**, critical: **{level_counts['critical']}**.",
    ]
    for s in sorted(high_risk, key=lambda x: (-x.score, x.address))[:_MAX_TABLE_ROWS]:
        risk_lines.append(
            f"- `{s.address}` — **{s.level}** ({s.score}): " + "; ".join(s.reasons)
        )

    # ── 9. Methodology ──────────────────────────────────────────────
    from stopa.domain.crypto.risk_scoring import load_sanction_lists

    ofac, eu = load_sanction_lists()
    methodology = (
        f"STOPA {stopa_version} crypto pipeline: K1 content-scan detectors "
        "(address regex + checksum validation), K2 wallet parsers (Electrum/MetaMask/"
        "Bitcoin Core BDB), K3 on-chain analysis (bundled sanction lists — OFAC "
        f"{len(ofac)} entries, EU {len(eu)} entries; clustering & fund-flow graph), "
        "K4 dark-web detectors (ransom note template matching, marketplace evidence, "
        "CoinJoin/mixer heuristics). Risk scoring is deterministic: 0/none, 95/high, "
        "100/critical per sanction match. Report integrity: SHA-256 + Ed25519 signature."
    )

    # ── 10. Chain of Custody ────────────────────────────────────────
    audit = db.list_audit_log(limit=50)
    if audit:
        custody_lines = ["Audit trail (latest operations):", ""]
        for r in reversed(audit):  # chronologicky vzestupně pro report
            custody_lines.append(
                f"- {r.get('ts', '?')} · **{r.get('actor', '?')}**: {r.get('action', '?')}"
            )
    else:
        custody_lines = ["No audit records for this case."]

    sections = {key: "\n".join(body) for key, body in [
        ("executive_summary", lines),
        ("wallet_discovery", lines_wallet),
        ("address_inventory", [inv]),
        ("transaction_timeline", [timeline]),
        ("fund_flow_analysis", flow_lines),
        ("exchange_correlation", exch_lines),
        ("entity_attribution", attr_lines),
        ("risk_assessment", risk_lines),
        ("methodology", [methodology]),
        ("chain_of_custody", custody_lines),
    ]}

    stats = {
        "wallets_total": len(wallet_arts),
        "addresses_total": len(addrs),
        "high_risk_count": level_counts["high"],
        "critical_risk_count": level_counts["critical"],
        "exchange_records": len(exchange_arts),
        "transactions_cached": len(all_txs),
    }
    return CryptoReportData(case_id=case_id, stopa_version=stopa_version, sections=sections, stats=stats)


def _iso_date(ts_s: int | None) -> str:
    if not ts_s:
        return "—"
    import datetime

    try:
        return datetime.datetime.fromtimestamp(ts_s, datetime.timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    except (OverflowError, OSError, ValueError):
        return f"ts={ts_s}"


def _d3_json_compact(d: dict) -> str:
    import json

    return json.dumps(d, indent=1, ensure_ascii=False)


# ── renderování formátů ────────────────────────────────────────────────────


def render_markdown(data: CryptoReportData) -> str:
    """Markdown report — 10 sekcí v kanonickém pořadí."""
    out = [f"# SWGDE Crypto Report — {data.case_id}", ""]
    for i, (key, title) in enumerate(REPORT_SECTIONS, start=1):
        out.append(f"## {i}. {title}")
        out.append("")
        out.append(data.sections.get(key, ""))
        out.append("")
    return "\n".join(out)


def _md_to_html(md: str) -> str:
    """Minimální deterministický md→html (nadpisy, tabulky, odrážky, code)."""
    import re

    lines = md.splitlines()
    out: list[str] = []
    in_table = False
    in_code = False
    table_buf: list[list[str]] = []

    def flush_table() -> None:
        nonlocal table_buf, in_table
        if not table_buf:
            in_table = False
            return
        rows_html = []
        for j, row in enumerate(table_buf):
            tag = "th" if j == 0 else "td"
            rows_html.append("<tr>" + "".join(f"<{tag}>{_cell(c)}</{tag}>" for c in row) + "</tr>")
        out.append("<table>" + "".join(rows_html) + "</table><p></p>")
        table_buf = []
        in_table = False

    def _cell(s: str) -> str:
        s = _html.escape(s.strip())
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        return s

    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("```"):
            if not in_code:
                out.append("<pre><code>")
                in_code = True
            else:
                out.append("</code></pre><p></p>")
                in_code = False
            continue
        if in_code:
            out.append(_html.escape(ln))
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if all(set(c) <= {"-", " ", ":"} for c in cells):  # oddělovač řádku
                continue
            if not in_table:
                in_table = True
            table_buf.append(cells)
            continue
        elif in_table:
            flush_table()
        if stripped.startswith("## "):
            out.append(f"<h2>{_html.escape(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            out.append(f"<h1>{_html.escape(stripped[2:])}</h1>")
        elif stripped.startswith("- "):
            out.append("<ul><li>" + _cell(stripped[2:]) + "</li></ul>")
        elif not stripped:
            continue
        else:
            s = _html.escape(stripped)
            s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
            s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
            out.append(f"<p>{s}</p>")
    if in_table:
        flush_table()
    return "\n".join(out)


def render_html(data: CryptoReportData, title: str | None = None) -> str:
    """Self-contained HTML report (bez CDN), deterministický."""
    t = _html.escape(title or f"SWGDE Crypto Report — {data.case_id}")
    body_parts: list[str] = []
    for i, (key, sec_title) in enumerate(REPORT_SECTIONS, start=1):
        body_parts.append(f"<h2>{i}. {_html.escape(sec_title)}</h2>")
        body_parts.append(_md_to_html(data.sections.get(key, "")))
    stats = ", ".join(f"{k}: {v}" for k, v in sorted(data.stats.items()))
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\"/>\n"
        f"<title>{t}</title>\n<style>body{{font-family:sans-serif;max-width:1000px;margin:"
        "24px auto;padding:0 16px;color:#2c3e50}}table{{border-collapse:collapse;width:100%;}"
        "th,td{{border:1px solid #bdc3c7;padding:4px 8px;font-size:13px;text-align:left}}"
        "code{{background:#ecf0f1;padding:1px 4px;border-radius:3px}}pre{{background:#2c3e50;"
        "color:#ecf0f1;padding:12px;overflow-x:auto}}</style>\n</head>\n<body>\n"
        f"<h1>{t}</h1>\n<p>STOPA {data.stopa_version} · case <code>{_html.escape(data.case_id)}</code>"
        f" · {stats}</p>\n<hr/>\n" + "\n".join(body_parts) + "\n</body>\n</html>\n"
    )


# ── integrity podpis (legal_docs konvence: Ed25519 + SHA-256) ───────────────


def sign_report(content: str, db) -> tuple[str, str | None, str | None]:
    """SHA-256 digest + Ed25519 podpis (legal_docs konvence; None = bez backendu)."""
    from stopa.domain import integrity

    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    pub_b64: str | None = (
        db.integrity_public_key() if hasattr(db, "integrity_public_key") else None
    )
    sig_b64: str | None = None
    try:
        priv_b64, pub_b64 = db.ensure_integrity_key()
        sig_b64 = integrity.sign_hash(priv_b64, digest)
    except RuntimeError:  # chybí cryptography → nepodepsáno (graceful degradation)
        pass
    return digest, sig_b64, pub_b64


def generate_crypto_report(
    db,
    case_id: str,
    fmt: str = "md",
    *,
    out: Path | None = None,
    txs_by_addr: dict[str, list] | None = None,
) -> CryptoReportResult:
    """Vygeneruje report ve formátu md|html|json; ``out`` → uloží do souboru."""
    import json as _json

    if fmt not in ("md", "html", "json"):
        raise ValueError(f"neznámý formát: {fmt!r} (očekáváno md|html|json)")
    data = build_crypto_report_data(db, case_id, txs_by_addr=txs_by_addr)
    if fmt == "md":
        content = render_markdown(data)
    elif fmt == "html":
        content = render_html(data)
    else:
        content = _json.dumps(
            {
                "case_id": data.case_id,
                "stopa_version": data.stopa_version,
                "sections": data.sections,
                "stats": data.stats,
            },
            indent=2,
            ensure_ascii=False,
        )
    digest, sig_b64, pub_b64 = sign_report(content, db)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
    return CryptoReportResult(
        case_id=case_id,
        format=fmt,
        content=content,
        sha256_hex=digest,
        signature_b64=sig_b64,
        public_key_b64=pub_b64,
        stats=data.stats,
    )
