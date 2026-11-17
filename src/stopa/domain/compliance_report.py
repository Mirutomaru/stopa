"""STOPA — F5.2 SWGDE / ISO 27037 automatizovaný compliance report (Compliance & Court-Readiness).

Doložitelnost pro externího auditora: jeden podepsaný dokument popisuje,
*čím* byl případ zpracován (nástroje+verze), *jak jsou algoritmy validovány*
(C3 registry / C6 report), *jak byl disk chráněn před zápisem* (write-blocker
logy) a *kde je AI důkazem podložená* (AI grounding, F3.x). K tomu chain of
custody (CoC) a Merkle pečeť stavu případu (F5.1).

Čistá logika bez I/O: data vrstva (:mod:`stopa.presentation.compliance_report`)
sběhuje podklady ze SQLite a volá :func:`build_payload`. Ed25519 podpis
přes existující integrity vrstvu (lazy ``cryptography`` — graceful degradation).

Determinismus
-------------
- **Kanonický JSON**: ``json.dumps(sort_keys=True, ensure_ascii=False,
  separators=(",", ":"))`` — stejný obsah = stejné bajty nezávisle na pořadí
  klíčů v Pythonu. Podpis nese SHA-256 digest kanonického JSON (hex), stejně
  jako C4 kontrolní body a F5.1 Merkle pečeti → jednotná verifikační sémantika.
- **HTML render** je deterministická funkce payloadu (žádný runtime timestamp
  mimo ``generated_at`` v payloadu) → stejný payload = stejné PDF.

Sekce dokumentu (SWGDE/ISO 27037 framing)
-----------------------------------------
1. Nástroje a verze, 2. Validace algoritmů (C3/C6), 3. Write-blocker logy,
4. AI grounding report, 5. Chain of custody, 6. Integrity & Merkle seal (F5.1),
7. Podpisový blok (digest + Ed25519 signature + public key).
"""

from __future__ import annotations

import hashlib
import html
import json
from datetime import datetime, timezone

#: Verze formátu compliance reportu — do payloadu i podkopku PDF/JSON.
COMPLIANCE_FORMAT_VERSION = 1

#: Domain tag — oddělení od jiných hash domén (audit chain, case seals).
DOMAIN_TAG = "stopa-compliance/v1"

#: Audit akce inteligentní vrstvy (F3.x) — počítají se do AI grounding sekce.
AI_ACTIONS: tuple[str, ...] = ("ai_agent_action", "nl_query", "hypothesis_graph_generated")

#: Prefix audit akcí write-blocker záznamů (F5.4 je přidá; forward-kompatibilní).
WB_ACTION_PREFIX = "wb_"


def utc_now_iso() -> str:
    """Aktuální UTC čas v ISO 8601 (pro ``generated_at``)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json(payload: dict) -> bytes:
    """Kanonický JSON payloadu — deterministický přes pořadí klíčů."""
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def report_digest(canonical: bytes) -> str:
    """SHA-256 digest kanonického JSON (hex 64 znaků) — co se podpisuje."""
    return hashlib.sha256(canonical).hexdigest()


def build_payload(
    *,
    case_id: str,
    case_name: str | None,
    examiner: str | None,
    tools: list[dict],
    algorithms: dict,
    write_blockers: list[dict],
    ai_grounding: dict,
    chain_of_custody: list[dict],
    merkle_seal: dict | None = None,
    generated_at: str | None = None,
) -> dict:
    """Sestaví kompletní payload compliance reportu.

    Všechny sekce jsou povinné (prázdné seznamy = explicitní „žádný záznam“),
    kromě ``merkle_seal`` (None, pokud případ ještě nebyl zamčen).
    """
    return {
        "format_version": COMPLIANCE_FORMAT_VERSION,
        "domain_tag": DOMAIN_TAG,
        "generated_at": generated_at or utc_now_iso(),
        "case": {"id": case_id, "name": case_name, "examiner": examiner},
        "tools": tools,
        "algorithms": algorithms,
        "write_blockers": write_blockers,
        "ai_grounding": ai_grounding,
        "chain_of_custody": chain_of_custody,
        "merkle_seal": merkle_seal,
    }


def sign_report(payload: dict, private_b64: str) -> tuple[str, str]:
    """Ed25519 podpis payloadu. Vrací ``(digest_hex, signature_b64)``.

    Podpisuje se hex digest kanonického JSON (stejná sémantika jako C4
    kontrolní body a F5.1 Merkle pečeti). Volá integrity vrstvu → vyžaduje
    balík ``cryptography`` (RuntimeError bez něj — caller degraduje).
    """
    from stopa.domain.integrity import sign_hash  # lazy cryptography

    digest = report_digest(canonical_json(payload))
    return digest, sign_hash(private_b64, digest)


def verify_report(payload: dict, public_b64: str | None, signature_b64: str | None) -> bool:
    """Ověří podpis payloadu veřejným klíčem; chybějící klíč/podpis → False."""
    from stopa.domain.integrity import verify_signature  # lazy cryptography

    if not public_b64 or not signature_b64:
        return False
    return verify_signature(public_b64, report_digest(canonical_json(payload)), signature_b64)


def _esc(value: object) -> str:
    """HTML escape pro libovolnou hodnotu (None → em-dash)."""
    if value is None:
        return "&mdash;"
    return html.escape(str(value))


def render_html(payload: dict, signature_b64: str | None = None) -> str:
    """Deterministický HTML dokument SWGDE/ISO 27037 reportu.

    Sekce 1–7 dle modulové docstringy; ``signature_b64`` se vkládá do
    podpisového bloku (None → „podpis chybí — cryptography nenainstalována“).
    """
    case = payload["case"]
    alg = payload.get("algorithms") or {}
    ai = payload.get("ai_grounding") or {}
    seal = payload.get("merkle_seal")

    tools_rows = "".join(
        f"<tr><td>{_esc(t.get('name'))}</td><td>{_esc(t.get('version'))}</td></tr>"
        for t in payload.get("tools", [])
    )
    status_rows = "".join(
        f"<tr><td>{_esc(k)}</td><td>{v}</td></tr>"
        for k, v in sorted((alg.get("by_status") or {}).items())
    )
    parsers: list[dict] = alg.get("parsers") or []
    parser_rows = "".join(
        f"<tr><td>{_esc(p.get('parser_id'))}</td>"
        f"<td>{_esc(p.get('status'))}</td><td>{p.get('artifacts', 0)}</td></tr>"
        for p in parsers
    )

    wbs: list[dict] = payload.get("write_blockers") or []
    if wbs:
        wb_rows = "".join(
            f"<tr><td>{_esc(wb.get('ts'))}</td><td>{_esc(wb.get('action'))}</td>"
            f"<td>{_esc(wb.get('actor'))}</td><td>{_esc(wb.get('details'))}</td></tr>"
            for wb in wbs
        )
        wb_section = (
            "<table class='wb'><thead><tr><th>Čas</th><th>Akce</th>"
            f"<th>Aktor</th><th>Detaily</th></tr></thead><tbody>{wb_rows}</tbody></table>"
        )
    else:
        wb_section = (
            "<p class='note'><b>Žádné write-blocker záznamy v audit logu.</b> "
            "Auditor musí ověřit ochranu před zápisem ručně (manual verification required).</p>"
        )

    tool_counts: dict[str, int] = ai.get("tools_used") or {}
    ai_rows = "".join(
        f"<tr><td>{_esc(t)}</td><td>{c}</td></tr>" for t, c in sorted(tool_counts.items())
    )
    coc: list[dict] = payload.get("chain_of_custody") or []
    coc_rows = "".join(
        f"<tr><td>{_esc(c.get('source_id'))}</td><td>{_esc(c.get('kind'))}</td>"
        f"<td>{_esc(c.get('path'))}</td><td>{_esc(c.get('added_at'))}</td>"
        f"<td>{c.get('artifacts_count', 0)}</td></tr>"
        for c in coc
    )

    if seal:
        seal_ok = bool(seal.get("seals_valid")) and not bool(
            [s for s in (seal.get("seals") or []) if not s.get("ok", True)]
        )
        seal_section = (
            f"<p>Pečetí celkem: <b>{seal.get('seals_total', 0)}</b>, "
            f"platných: <b>{seal.get('seals_valid', 0)}</b>; "
            f"poslední root: <code>{_esc(seal.get('latest_root_hash'))}</code> — "
            f"{'OK' if seal_ok else 'ROZDÍL'}</p>"
        )
    else:
        seal_section = "<p class='note'>Případ ještě nebyl zamčen (F5.1 pečeť chybí).</p>"

    digest_hex = report_digest(canonical_json(payload))
    if signature_b64:
        sig_block = (
            f"<p>SHA-256 digest payloadu: <code>{digest_hex}</code><br>"
            f"Ed25519 podpis: <code>{_esc(signature_b64)}</code></p>"
        )
    else:
        sig_block = (
            f"<p>SHA-256 digest payloadu: <code>{digest_hex}</code><br>"
            "<span class='note'>Podpis chybí — balík cryptography nenainstalován "
            "(graceful degradation).</span></p>"
        )

    return f"""<!DOCTYPE html>
<html lang="cs"><head><meta charset="utf-8">
<title>SWGDE / ISO 27037 Compliance Report — {_esc(case['id'])}</title>
<style>
body {{ font-family: sans-serif; margin: 2em; color: #1a1a1a; }}
h1 {{ font-size: 1.4em; border-bottom: 2px solid #333; padding-bottom: .3em; }}
h2 {{ font-size: 1.1em; margin-top: 1.6em; color: #333; }}
table {{ border-collapse: collapse; width: 100%; margin: .6em 0; font-size: .9em; }}
th, td {{ border: 1px solid #bbb; padding: .35em .6em; text-align: left; }}
th {{ background: #f0f0f0; }}
.note {{ color: #8a5a00; font-size: .92em; }}
code {{ font-family: monospace; word-break: break-all; }}
.meta {{ color: #444; margin-bottom: 1.2em; }}
</style></head>
<body>
<h1>SWGDE / ISO 27037 Compliance Report</h1>
<p class="meta">Případ <b>{_esc(case['id'])}</b> — {_esc(case.get('name'))} ·
Znalec: {_esc(case.get('examiner'))} · Vygenerováno: {_esc(payload.get('generated_at'))}<br>
Formát verze {payload.get('format_version')} ({DOMAIN_TAG})</p>

<h2>1. Nástroje a verze</h2>
<table><thead><tr><th>Nástroj</th><th>Verze</th></tr></thead><tbody>{tools_rows}</tbody></table>

<h2>2. Validace algoritmů (C3 registry / C6 report)</h2>
<p>Celkem artefaktů: <b>{alg.get('total_artifacts', 0)}</b>,
coverage validovaných parserů: <b>{_esc(alg.get('coverage'))}</b></p>
<table><thead><tr><th>Status</th><th>Počet</th></tr></thead><tbody>{status_rows}</tbody></table>
<table><thead><tr><th>Parser</th><th>Status</th><th>Artefakty</th></tr></thead><tbody>{parser_rows}</tbody></table>

<h2>3. Write-blocker logy (ochrana zdroje před zápisem)</h2>
{wb_section}

<h2>4. AI grounding report (F3.x inteligentní vrstva)</h2>
<p>Celkem AI akcí v audit logu: <b>{ai.get('total_actions', 0)}</b></p>
<table><thead><tr><th>Nástroj</th><th>Použití</th></tr></thead><tbody>{ai_rows}</tbody></table>

<h2>5. Chain of custody (ISO 27037 — zachování důkazní hodnoty)</h2>
<table><thead><tr><th>Zdroj</th><th>Druh</th><th>Cesta</th><th>Přidáno</th>"
f"<th>Artefakty</th></tr></thead><tbody>{coc_rows}</tbody></table>

<h2>6. Integrity &amp; Merkle seal (F5.1)</h2>
{seal_section}

<h2>7. Podpis dokumentu (Ed25519)</h2>
{sig_block}
</body></html>"""
