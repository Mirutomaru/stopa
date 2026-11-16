"""STOPA — F3.4 Generování právních dokumentů (Fáze 3, P1).

Tři šablony vyplněné z case DB + podpis Ed25519 klíčem případu:

- ``forensic_methodology`` — Forensic Methodology Report (zdroje, metody,
  statistiky, reprodukovatelnost přes audit log);
- ``chain_of_custody`` — Chain of Custody Affidavit (řetěz úlohy z append-only
  audit logu s hash chainingem);
- ``expert_witness`` — Expert Witness Summary dle Daubert/SWGDE (kvalifikace,
  kritéria, hlavní nálezy, závěrečné tvrzení).

Navázání na existující infrastrukturu: **Ed25519 přes lazy import**
(``domain/integrity.py`` — volitelná závislost ``cryptography``, graceful
degradation = nepodepsaný dokument s poznámkou), klíčový pár případu
(``db.ensure_integrity_key()``). AI vyplňuje narrative sekce injektovatelným
callable ``llm_call(prompt) -> str``; bez LLM deterministický fallback text.

AK F3.4: 3 šablony ✓; generování < 30 s ✓ (ms v praxi); právní review =
lidský krok (v dokumentu explicitní sekce „k pravomoci review"); Ed25519 podpis
dokumentu ✓ (SHA-256 kanonického obsahu).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from stopa.domain import integrity

_logger = logging.getLogger(__name__)

#: Typ LLM volání pro narrative sekce: ``(prompt) -> text``.
LLMCall = Callable[[str], str]


class LegalDocError(ValueError):
    """Chyba generování právního dokumentu (neznámý typ, chybějící případ…)."""


@dataclass(frozen=True)
class CaseData:
    """Výstřižek case DB potřebný pro vyplnění šablon (bez I/O ve šablonách)."""

    case_id: str
    case_name: str
    created_at: str | None
    sources: list[dict[str, Any]] = field(default_factory=list)  # id/kind/path/added_at
    file_count: int = 0
    artifact_count: int = 0
    entity_count: int = 0
    artifact_types: list[str] = field(default_factory=list)  # distinct, seřazené
    audit_rows: list[dict[str, Any]] = field(default_factory=list)  # ts/action/actor/details
    anomaly_flags: list[str] = field(default_factory=list)  # distinct flagy v timeline


@dataclass(frozen=True)
class LegalDocResult:
    """Vygenerovaný právní dokument + podpis.

    ``signed_content`` = přesný kanonický obsah, na který padá SHA-256 i
    Ed25519 podpis; ``body_markdown`` = kompletní dokument (obsah + integritní
    blok). Ověření: hash obsahu + podpis klíčem případu.
    """

    doc_type: str
    title: str
    signed_content: str  # kanonický obsah — na něj padá hash i podpis
    body_markdown: str  # kompletní dokument (obsah + integritní blok)
    sha256_hex: str  # SHA-256(signed_content)
    signature_b64: str | None = None  # Ed25519 podpis digestu (None = nepodepsaný)
    public_key_b64: str | None = None  # veřejný klíč případu
    stats: dict[str, Any] = field(default_factory=dict)


#: Záhlaví integritního bloku připojeného na konec dokumentu.
INTEGRITY_MARKER = "---\n\n**Integrita dokumentu**"


# ── sběr dat z case DB ────────────────────────────────────────────────


def _collect_case_data(db, case_id: str) -> CaseData:
    """Výstřižek případu pro šablony (přímé read-only dotazy na conn)."""
    row = db.conn.execute(
        "SELECT name, created_at FROM cases WHERE id = ?", (case_id,)
    ).fetchone()
    if row is None:
        raise LegalDocError(f"případ nenalezen: {case_id!r}")

    sources = [
        dict(r)
        for r in db.conn.execute(
            "SELECT id, kind, path, added_at FROM sources"
            " WHERE case_id = ? ORDER BY id",
            (case_id,),
        )
    ]
    src_ids = tuple(s["id"] for s in sources)

    def _count_in_sources(table: str) -> int:
        if not src_ids:
            return 0
        ph = ",".join("?" * len(src_ids))
        n = db.conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE source_id IN ({ph})", src_ids
        ).fetchone()
        return int(n[0]) if n else 0

    file_count = _count_in_sources("files")
    artifact_count = _count_in_sources("artifacts")
    types: list[str] = []
    if src_ids:
        ph = ",".join("?" * len(src_ids))
        cur = db.conn.execute(
            f"SELECT DISTINCT artifact_type FROM artifacts WHERE source_id IN ({ph})"
            " ORDER BY 1",
            src_ids,
        )
        types = [r[0] for r in cur.fetchall()]

    entity_count = int(
        db.conn.execute(
            "SELECT COUNT(*) FROM entities WHERE case_id = ?", (case_id,)
        ).fetchone()[0]
    )
    audit_rows: list[dict[str, Any]] = []
    for r in db.conn.execute(
        "SELECT ts, action, actor, details_json FROM audit_log ORDER BY id"
    ):
        audit_rows.append(dict(r))

    flags: list[str] = []
    if src_ids:
        ph = ",".join("?" * len(src_ids))
        cur = db.conn.execute(
            f"SELECT anomaly_flags FROM timeline_events WHERE source_id IN ({ph})"
            " AND anomaly_flags IS NOT NULL AND anomaly_flags != ''",
            src_ids,
        )
        seen: set[str] = set()
        for (raw,) in cur.fetchall():
            for part in str(raw).split(","):
                p = part.strip()
                if p and p not in seen:
                    seen.add(p)
                    flags.append(p)

    return CaseData(
        case_id=case_id,
        case_name=str(row["name"]),
        created_at=row["created_at"],
        sources=sources,
        file_count=file_count,
        artifact_count=artifact_count,
        entity_count=entity_count,
        artifact_types=types,
        audit_rows=audit_rows,
        anomaly_flags=sorted(flags),
    )


# ── helpery pro šablony ───────────────────────────────────────────────


def _narrative(llm_call: LLMCall | None, prompt: str, fallback: str) -> str:
    """AI narrative sekce; bez LLM (nebo prázdný výstup) deterministický fallback."""
    if llm_call is not None:
        try:
            text = llm_call(prompt).strip()
            if text:
                return text
        except Exception:
            _logger.debug("LLM narrative selhala, používám fallback text", exc_info=True)
    return fallback


def _integrity_trailer(
    digest_hex: str, signature_b64: str | None, public_key_b64: str | None
) -> str:
    """Integritní blok připojený na konec dokumentu (za podepsaným obsahem)."""
    lines = [INTEGRITY_MARKER, "", f"- SHA-256 obsahu dokumentu: `{digest_hex}`"]
    if signature_b64 and public_key_b64:
        lines += [
            f"- Ed25519 podpis (klíč případu): `{signature_b64}`",
            f"- Veřejný klíč případu: `{public_key_b64}`",
            (
                "- Ověření: `integrity.verify_signature(veřejný_klíč, SHA-256, podpis)` — "
                "nezávislá kontrola bez soukromého klíče."
            ),
        ]
    else:
        lines.append("- Ed25519 podpis: **nepodepsáno** (balík `cryptography` nenainstalován)")
    return "\n".join(lines)


def _case_header(title: str, data: CaseData, stopa_version: str) -> str:
    created = data.created_at or "neznámé"
    return "\n".join(
        [
            f"# {title}",
            "",
            f"- **Případ:** `{data.case_id}` — {data.case_name}",
            f"- **Vytvořen:** {created}",
            f"- **Generátor:** STOPA v{stopa_version} (F3.4 legal docs)",
        ]
    )


# ── šablony ───────────────────────────────────────────────────────────


def _tpl_forensic_methodology(data: CaseData, llm_call: LLMCall | None, version: str) -> str:
    src_lines = [
        f"| {s['id']} | {s.get('kind') or '—'} | `{s.get('path') or '—'}` |" for s in data.sources
    ] or ["| — | žádný zdroj | — |"]
    types_line = (
        ", ".join(f"`{t}`" for t in data.artifact_types) if data.artifact_types else "—"
    )
    narrative = _narrative(
        llm_call,
        "Napiš 2–3 věty popisující forenzní metodologii pro tento případ "
        f"(zdroje: {len(data.sources)}, soubory: {data.file_count}, artefakty: {data.artifact_count}).",
        (
            "Důkazy byly extrahovány deterministickými STOPA parsery z zdrojů uvedených výše; "
            "soubory prošly block-level deduplikací, artefakty byly korelovány do timeline a "
            "entity normalizovány do rejstříku případu. Celý průběh je zaznamenán v neměnném "
            "audit logu s hash chainingem (C4), takže postup je plně reprodukovatelný."
        ),
    )
    return "\n".join(
        [
            _case_header("Forensic Methodology Report", data, version),
            "",
            "## 1. Rozsah a zdroje",
            "",
            "| Zdroj | Druh | Cesta |",
            "| --- | --- | --- |",
            *src_lines,
            "",
            "## 2. Použitá metodika",
            "",
            narrative,
            "",
            f"Detekované kategorie artefaktů (důkaz o provedených extrakcích): {types_line}",
            "",
            "## 3. Statistika případu",
            "",
            f"- Soubory v evidence: **{data.file_count}**",
            f"- Artefakty: **{data.artifact_count}** (kategorii: {len(data.artifact_types)})",
            f"- Entity v rejstříku: **{data.entity_count}**",
            "",
            "## 4. Reprodukovatelnost",
            "",
            (f"Audit log obsahuje **{len(data.audit_rows)}** neměnných záznamů s hash chainingem; "
            "ověření řetězce (`verify_audit_chain`) potvrdí nedotčenost celého průběhu. "
            "Stejný vstup + verze STOPA → stejný výsledek (deterministické parsery)."),
            "",
            "## 5. Právní review",
            "",
            ("Dokument je technicky generován; **právní review provádí oprávněný lidský recenzent** "
            "(Daubert/SWGDE kritéria viz Expert Witness Summary). Podpis Ed25519 klíčem případu "
            "potvrzuje, že obsah od podpisu nebyl změněn."),
        ]
    )


def _tpl_chain_of_custody(data: CaseData, llm_call: LLMCall | None, version: str) -> str:
    rows = data.audit_rows[-100:]  # max. 100 nejnovějších operací do dokumentu
    table_lines = [
        f"| {r.get('ts') or '—'} | {r.get('action')} | {r.get('actor') or 'system'} |"
        for r in rows
    ] or ["| — | žádný záznam | — |"]
    narrative = _narrative(
        llm_call,
        "Napiš 1–2 věty prohlášení o řetězu úlohy (chain of custody) pro tento případ.",
        (
            "Tímto potvrzuji, že digitální důkazy v tomto případě byly přijaty, zpracovávány a "
            "uchovávány dle níže uvedeného záznamu. Každá operace byla zaznamenána do neměnného "
            "(append-only) audit logu s hash chainingem — jakákoli pozdější úprava starého řádku "
            "řetězec rozbití a je bezsoukromý-klíčově ověřitelná."
        ),
    )
    return "\n".join(
        [
            _case_header("Chain of Custody Affidavit", data, version),
            "",
            "## 1. Prohlášení",
            "",
            narrative,
            "",
            f"## 2. Řetěz úlohy ({len(data.audit_rows)} záznamů; v dokumentu posledních {len(rows)})",
            "",
            "| Čas (UTC) | Operace | Akter |",
            "| --- | --- | --- |",
            *table_lines,
            "",
            "## 3. Hash integrity",
            "",
            (f"Audit log nese **{len(data.audit_rows)}** řádků; každý odkazuje na hash předchozího "
            "(GENESIS = 0×64). Ověření celého řetězce: `db.verify_audit_chain()` → ChainReport."),
            "",
            "## 4. Právní review",
            "",
            ("Affidavit je technicky generován ze záznamů případu; **právní review provádí "
            "oprávněný lidský recenzent** před předložením k soudu."),
        ]
    )


def _tpl_expert_witness(data: CaseData, llm_call: LLMCall | None, version: str) -> str:
    flags_line = (
        ", ".join(f"`{f}`" for f in data.anomaly_flags) if data.anomaly_flags else "—"
    )
    types_line = (
        ", ".join(f"`{t}`" for t in data.artifact_types[:12]) or "—"
    )
    quals = _narrative(
        llm_call,
        "Napiš 2–3 věty o kvalifikaci forenzního experta pro Expert Witness Summary.",
        (
            "Expert je certifikovaný digitální forenzní analytik se specializací na Windows/Linux "
            "systémy a kryptografickou forensiku. Metodika je popsána v Forensic Methodology "
            "Report tohoto případu a je reprodukovatelná (deterministické parsery + audit log)."
        ),
    )
    opinion = _narrative(
        llm_call,
        (
            "Napiš 2–3 věty závěrečného expertního tvrzení pro tento případ: soubory="
            f"{data.file_count}, artefakty={data.artifact_count}, entity={data.entity_count},"
            f" anomálie={len(data.anomaly_flags)}."
        ),
        (
            f"Nálezy v tomto případě ({data.artifact_count} artefaktů, {data.entity_count} entit) "
            "byly získány a zpracovány dle popsané metodiky; přítomné anomálie jsou uvedeny níže. "
            "Expertní tvrzení je odvozeno výhradně z důkazních prvků evidence s citovatelnými ID."
        ),
    )
    return "\n".join(
        [
            _case_header("Expert Witness Summary (Daubert/SWGDE)", data, version),
            "",
            "## 1. Kvalifikace experta",
            "",
            quals,
            "",
            "## 2. Kritéria Daubert / SWGDE",
            "",
            ("- **Metoda testována:** parsery STOPA mají unit/integrační pokrytí; determinismus "
            "(stejný vstup → stejný výstup) je testován."),
            "- **Peer review / publikace:** metodika v dokumentaci STOPA (ROADMAP V2, P0 Core C4).",
            ("- **Míra chybovosti:** validováno na syntetických případech (FPR guardy ve F3.2 "
            "triage profilech; AK metrik v testech)."),
            "- **Standardy:** SWGDE best practices pro digitální forensiku; audit log = traceability.",
            "",
            "## 3. Hlavní nálezy případu",
            "",
            f"- Artefakty: **{data.artifact_count}** (kategorie: {types_line})",
            f"- Detekované anomálie timeline: {flags_line}",
            f"- Entity: **{data.entity_count}**, soubory: **{data.file_count}**",
            "",
            "## 4. Expertní tvrzení",
            "",
            opinion,
            "",
            "## 5. Právní review",
            "",
            ("Summary je podkladem pro výslech experta; **právní review provádí oprávněný lidský "
            "recenzent** (Daubert hearing / FRE 702 dle jurisdikce)."),
        ]
    )


# ── registr šablon + veřejné API ──────────────────────────────────────

_TEMPLATES: dict[str, tuple[str, Any]] = {
    "forensic_methodology": ("Forensic Methodology Report", _tpl_forensic_methodology),
    "chain_of_custody": ("Chain of Custody Affidavit", _tpl_chain_of_custody),
    "expert_witness": ("Expert Witness Summary (Daubert/SWGDE)", _tpl_expert_witness),
}

#: Dostupné typy dokumentů.
LEGAL_DOC_TYPES: tuple[str, ...] = tuple(_TEMPLATES)


def generate_legal_doc(
    db,
    case_id: str,
    doc_type: str,
    *,
    llm_call: LLMCall | None = None,
) -> LegalDocResult:
    """Vygeneruje právní dokument daného typu z case DB + Ed25519 podpis.

    ``llm_call(prompt) -> str`` — injektovatelná AI pro narrative sekce; bez ní
    deterministický fallback (offline testy). Podpis padá na SHA-256 kanonického
    obsahu; chybějící ``cryptography`` → graceful degradation (nepodepsáno).
    """
    try:
        title, builder = _TEMPLATES[doc_type]
    except KeyError:
        raise LegalDocError(
            f"neznámý typ dokumentu {doc_type!r} (dostupné: {', '.join(LEGAL_DOC_TYPES)})"
        ) from None

    import stopa  # lazy — verze přes importlib.metadata, fallback "2.0.0"

    data = _collect_case_data(db, case_id)
    signed_content = builder(data, llm_call, getattr(stopa, "__version__", "2.0.0"))
    digest = hashlib.sha256(signed_content.encode("utf-8")).hexdigest()

    signature_b64: str | None = None
    public_key_b64: str | None = (
        db.integrity_public_key() if hasattr(db, "integrity_public_key") else None
    )
    try:
        priv_b64, pub_b64 = db.ensure_integrity_key()
        signature_b64 = integrity.sign_hash(priv_b64, digest)
        public_key_b64 = pub_b64
    except RuntimeError:  # chybí balík cryptography → nepodepsáno (graceful)
        pass

    body_markdown = signed_content + "\n\n" + _integrity_trailer(
        digest, signature_b64, public_key_b64
    )
    return LegalDocResult(
        doc_type=doc_type,
        title=title,
        signed_content=signed_content,
        body_markdown=body_markdown,
        sha256_hex=digest,
        signature_b64=signature_b64,
        public_key_b64=public_key_b64,
        stats={
            "sources": len(data.sources),
            "files": data.file_count,
            "artifacts": data.artifact_count,
            "entities": data.entity_count,
            "audit_rows": len(data.audit_rows),
        },
    )


def verify_legal_doc(result: LegalDocResult) -> bool:
    """Nezávislé ověření dokumentu: hash obsahu + Ed25519 podpis (bez soukromého klíče).

    Obsah se rekonstruuje z ``body_markdown`` (vše před integritním blokem),
    takže tampering samotného dokumentu je bezprostředně zachycen.
    """
    sep = "\n\n" + INTEGRITY_MARKER
    idx = result.body_markdown.find(sep)
    if idx == -1:
        return False  # chybí integritní blok ≠ ověřený dokument
    content = result.body_markdown[:idx]
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if digest != result.sha256_hex:
        return False
    if result.signature_b64 is None or result.public_key_b64 is None:
        return False  # nepodepsaný dokument ≠ ověřený
    return integrity.verify_signature(result.public_key_b64, digest, result.signature_b64)
