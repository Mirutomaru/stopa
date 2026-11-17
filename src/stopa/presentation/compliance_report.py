"""STOPA — F5.2 compliance report: IO vrstva (SBĚR + GENERACE souborů).

Čistá logika žije v :mod:`stopa.domain.compliance_report`; zde se čte case DB,
podpisuje se klíčem případu (``meta.integrity_priv``, idempotentní
``ensure_integrity_key``) a zapisují se výstupy:

- ``<case>_compliance_<stamp>.json`` — payload + podpisový blok (machine-readable)
- ``<case>_compliance_<stamp>.pdf``  — SWGDE/ISO 27037 dokument (WeasyPrint)

Graceful degradation: bez balíku ``cryptography`` report vznikne nepodepsaný
(``signature_b64=None``); bez WeasyPrint chybí jen PDF. Audit log dostane
záznam ``compliance_report_generated`` s digestem a cestami.
"""

from __future__ import annotations

import json
import platform
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.data.db import CaseDB
from stopa.domain.compliance_report import (
    AI_ACTIONS,
    WB_ACTION_PREFIX,
    build_payload,
    render_html,
    sign_report,
)


def _stopa_version() -> str:
    """Verze STOPA (lazy importlib.metadata; fallback pro dev run)."""
    try:
        from importlib.metadata import version

        return version("stopa")
    except Exception:  # noqa: BLE001 — dev run bez instalace / chybějící metadata
        return "2.0.0"


def _pkg_version(name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:  # noqa: BLE001 — volitelný balík nemusí být nainstalován
        return None


def tool_versions() -> list[dict]:
    """Nástroje + verze pro sekci 1 reportu (doložitelnost prostředí)."""
    tools = [
        {"name": "STOPA", "version": _stopa_version()},
        {"name": "Python", "version": platform.python_version()},
        {"name": "sqlite3", "version": sqlite3.sqlite_version},
    ]
    for pkg in ("weasyprint", "cryptography"):
        v = _pkg_version(pkg)
        if v:
            tools.append({"name": pkg, "version": v})
    return tools


def _write_blocker_rows(conn: sqlite3.Connection) -> list[dict]:
    """WB záznamy z audit logu (akce wb_* nebo details s write_blocker)."""
    rows = conn.execute(
        "SELECT ts, action, actor, details_json FROM audit_log"
        " WHERE action LIKE ? OR details_json LIKE '%write_blocker%'"
        " ORDER BY id",
        (f"{WB_ACTION_PREFIX}%",),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        try:
            details = json.loads(r["details_json"] or "{}")
        except (TypeError, ValueError):
            details = {}
        out.append(
            {
                "ts": r["ts"],
                "action": r["action"],
                "actor": r["actor"],
                "details": details if isinstance(details, dict) else {"raw": str(details)},
            }
        )
    return out


def _ai_grounding_summary(conn: sqlite3.Connection) -> dict:
    """Souhrn AI akcí (F3.x) z audit logu — sekce 4 reportu."""
    placeholders = ",".join("?" * len(AI_ACTIONS))
    total = conn.execute(
        f"SELECT COUNT(*) FROM audit_log WHERE action IN ({placeholders})",
        AI_ACTIONS,
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT details_json FROM audit_log WHERE action = 'ai_agent_action'"
    ).fetchall()
    tools_used: dict[str, int] = {}
    for r in rows:
        try:
            d = json.loads(r["details_json"] or "{}")
            tool = str(d.get("tool") or "unknown")
        except (TypeError, ValueError):
            tool = "unknown"
        tools_used[tool] = tools_used.get(tool, 0) + 1
    return {
        "total_actions": int(total),
        "tools_used": {k: v for k, v in sorted(tools_used.items())},
    }


def collect_compliance_data(db: CaseDB, case_id: str) -> dict[str, Any]:
    """Sběr podkladů pro :func:`build_payload` — čistá agregace nad DB."""
    from stopa.data.validation_report import build_validation_report

    case_row = db.conn.execute(
        "SELECT id, name, examiner FROM cases WHERE id = ?", (case_id,)
    ).fetchone()
    if case_row is None:
        raise KeyError(f"případ nenalezen: {case_id!r}")

    # Validace algoritmů — C3 registry × C6 report (souhrn, ne per-artifact řádky)
    from stopa.domain.validation_registry import build_registry

    vr = build_validation_report(db, case_id)
    registry = build_registry()  # C3 — parser ID → validační záznam
    parsers: list[dict] = [
        {
            "parser_id": pid,
            "status": "validated" if pid in registry else "unknown",
            "version": registry[pid].version if pid in registry else None,
            "artifacts": int(count),
        }
        for pid, count in sorted((vr.get("by_parser") or {}).items())
    ]
    algorithms = {
        "total_artifacts": int(vr.get("total_artifacts", 0)),
        "by_status": dict(vr.get("by_status") or {}),
        "coverage": vr.get("coverage"),
        "parsers": parsers,
    }

    sources = db.conn.execute(
        "SELECT id, kind, path, added_at FROM sources WHERE case_id = ? ORDER BY added_at",
        (case_id,),
    ).fetchall()
    artifacts_counts = {
        row["source_id"]: row["n"]
        for row in db.conn.execute(
            "SELECT source_id, COUNT(*) AS n FROM artifacts GROUP BY source_id"
        )
    }
    chain_of_custody: list[dict] = [
        {
            "source_id": s["id"],
            "kind": s["kind"],
            "path": s["path"],
            "added_at": s["added_at"],
            "artifacts_count": int(artifacts_counts.get(s["id"], 0)),
        }
        for s in sources
    ]
    for item in db.audit_repo.list_custody_items():
        chain_of_custody.append({"custody_item": True, **item})

    # F5.1 — Merkle pečeti stavu případu (None, pokud žádná)
    seals = db.seal_repo.verify_all() if hasattr(db, "seal_repo") else []
    merkle_seal: dict | None = None
    if seals:
        latest = max(seals, key=lambda s: int(s.get("id", 0)))
        merkle_seal = {
            "seals_total": len(seals),
            "seals_valid": sum(1 for s in seals if s.get("ok")),
            "latest_root_hash": latest.get("root_hash"),
        }

    return {
        "case_id": case_row["id"],
        "case_name": case_row["name"],
        "examiner": case_row["examiner"],
        "tools": tool_versions(),
        "algorithms": algorithms,
        "write_blockers": _write_blocker_rows(db.conn),
        "ai_grounding": _ai_grounding_summary(db.conn),
        "chain_of_custody": chain_of_custody,
        "merkle_seal": merkle_seal,
    }


def generate_compliance_report(
    db: CaseDB, case_id: str, out_dir: str | Path | None = None
) -> dict[str, Any]:
    """Vygeneruje podepsaný compliance report (JSON + PDF).

    Returns:
        ``{json_path, pdf_path|None, digest, signature_b64|None, public_key_b64}``
        — bez cryptography je podpis None (graceful degradation), bez WeasyPrint
        chybí jen PDF. Audit log dostane ``compliance_report_generated``.
    """
    data = collect_compliance_data(db, case_id)
    payload = build_payload(**data)

    digest: str | None = None
    sig_b64: str | None = None
    pub_b64: str | None = db.audit_repo.integrity_public_key()
    try:
        priv_b64, pub_b64 = db.audit_repo.ensure_integrity_key()
        digest, sig_b64 = sign_report(payload, priv_b64)
    except RuntimeError:  # cryptography nenainstalována → nepodepsaný report
        pass

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = Path(out_dir) if out_dir else db.path.parent
    base.mkdir(parents=True, exist_ok=True)
    json_path = base / f"{case_id}_compliance_{stamp}.json"
    doc = {
        "payload": payload,
        "signature": {
            "digest_sha256": digest,
            "signature_b64": sig_b64,
            "public_key_b64": pub_b64,
        },
    }
    json_path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    pdf_path: Path | None = None
    try:
        from weasyprint import HTML  # lazy — volitelná závislost pro PDF

        html_doc = render_html(payload, signature_b64=sig_b64)
        pdf_path = base / f"{case_id}_compliance_{stamp}.pdf"
        HTML(string=html_doc).write_pdf(str(pdf_path))
    except Exception:  # noqa: BLE001 — bez WeasyPrint zůstává JSON + digest
        pdf_path = None

    db.log_operation(
        "compliance_report_generated",
        details={
            "digest_sha256": digest,
            "json_path": str(json_path),
            "pdf_path": str(pdf_path) if pdf_path else None,
            "signed": sig_b64 is not None,
        },
    )
    return {
        "json_path": json_path,
        "pdf_path": pdf_path,
        "digest": digest,
        "signature_b64": sig_b64,
        "public_key_b64": pub_b64,
    }
