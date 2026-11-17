"""STOPA — Daubert pack: IO vrstva (F5.5).

Sběr podkladů z C3 registry × C6 validation report, podepsání Ed25519 klíčem
případu (stejný pattern jako F5.2 compliance report) a zápis kanonického JSON
balíku + audit log akce ``daubert_pack_generated``. Čistá logika žije v
:mod:`stopa.domain.daubert`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.data.db import CaseDB
from stopa.domain.compliance_report import canonical_json, report_digest, sign_report, utc_now_iso


def collect_daubert_data(db: CaseDB, case_id: str) -> dict[str, Any]:
    """Sběr podkladů pro :func:`stopa.domain.daubert.build_daubert_pack`.

    Čistá agregace nad DB — C3 registry (verze/testy/omezení parserů) × C6
    validation report (počty artefaktů per parser v případu).
    """
    from stopa.data.validation_report import build_validation_report
    from stopa.domain.validation_registry import PARSER_VALIDATIONS

    case_row = db.conn.execute(
        "SELECT id, name FROM cases WHERE id = ?", (case_id,)
    ).fetchone()
    if case_row is None:
        raise KeyError(f"případ nenalezen: {case_id!r}")

    vr = build_validation_report(db, case_id)
    by_parser: dict[str, Any] = vr.get("by_parser") or {}
    parsers: list[dict[str, Any]] = []
    for pid in sorted(by_parser):
        rec = PARSER_VALIDATIONS.get(pid)
        parsers.append(
            {
                "parser_id": pid,
                "version": rec.version if rec else None,
                "artifacts": int(by_parser[pid]),  # type: ignore[arg-type]
                "test_files": tuple(rec.test_files) if rec else (),
                "reference_dataset": rec.reference_dataset if rec else None,
                "limitations": tuple(rec.limitations) if rec else (),
            }
        )

    return {"case_id": case_row["id"], "case_name": case_row["name"], "parsers": parsers}


def generate_daubert_pack(
    db: CaseDB, case_id: str, out_dir: str | Path | None = None
) -> dict[str, Any]:
    """Vygeneruje podepsaný Daubert pack (1-click JSON balík pro soud).

    Returns:
        ``{json_path, digest, signature_b64|None, public_key_b64, references_total,
        case_parsers}`` — bez cryptography je podpis None (graceful degradation),
        digest vždy přítomen (SHA-256 kanonického JSON). Audit log dostane
        ``daubert_pack_generated``.
    """
    from stopa import __version__
    from stopa.domain.daubert import build_daubert_pack

    data = collect_daubert_data(db, case_id)
    payload = build_daubert_pack(
        case_id=data["case_id"],  # type: ignore[arg-type]
        case_name=data["case_name"],  # type: ignore[arg-type]
        generated_at=utc_now_iso(),
        stopa_version=__version__,
        parsers=data["parsers"],
    )

    digest = report_digest(canonical_json(payload))
    sig_b64: str | None = None
    pub_b64: str | None = db.audit_repo.integrity_public_key()
    try:
        # klíč musí existovat PŘED čtením public key (nový případ → ještě není)
        priv_b64, created_pub = db.audit_repo.ensure_integrity_key()
        pub_b64 = created_pub or pub_b64
        digest, sig_b64 = sign_report(payload, priv_b64)
    except RuntimeError:  # cryptography nenainstalována → nepodepsaný balík
        pass

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = Path(out_dir) if out_dir else db.path.parent
    base.mkdir(parents=True, exist_ok=True)
    json_path = base / f"{case_id}_daubert_{stamp}.json"
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

    db.log_operation(
        "daubert_pack_generated",
        details={
            "digest_sha256": digest,
            "json_path": str(json_path),
            "signed": sig_b64 is not None,
            "references_total": payload["references_total"],
            "case_parsers": len(payload["case_parsers"]),
        },
    )

    return {
        "json_path": json_path,
        "digest": digest,
        "signature_b64": sig_b64,
        "public_key_b64": pub_b64,
        "references_total": payload["references_total"],
        "case_parsers": len(payload["case_parsers"]),
    }
