"""Case report IO wrapper — čtení case DB + zápis HTML/PDF souborů.

Čistá logika (dataclass ReportData, build_html) žije v ``domain/report.py``;
tady je jen IO: naplnění dat z CaseDB a zápis výstupních souborů.

PDF přes WeasyPrint — volitelná závislost (lazy import); bez ní se dá
generovat vždy HTML (court-ready i tak, tiskne se z prohlížeče).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from stopa.data.db import CaseDB
from stopa.domain.report import (
    AuditEntry,
    CustodyItem,
    FlaggedFile,
    MarkedFile,
    ReportData,
    SourceInfo,
    build_html,
)

log = logging.getLogger("stopa.presentation.report")


def _flags_for(bad_ext: bool, dup_of: str | None, hash_set: str | None) -> tuple[str, ...]:
    """Flagy souboru — stejná logika jako CLI (BAD-EXT / DUP→… / HASHSET:…)."""
    flags: list[str] = []
    if bad_ext:
        flags.append("BAD-EXT")
    if dup_of:
        flags.append(f"DUP→{dup_of}")
    if hash_set:
        flags.append(f"HASHSET:{hash_set}")
    return tuple(flags)


def build_report_data(db: CaseDB, case_id: str) -> ReportData:
    """Naplní ReportData z case DB — jediný IO průchod pro report."""
    case = db.get_case(case_id)
    if case is None:
        raise ValueError(f"případ {case_id} nenalezen v case DB")

    sources = [
        SourceInfo(
            id=s.id, kind=s.kind, path=s.path, added_at=s.added_at, size_bytes=s.size_bytes
        )
        for s in db.list_sources(case_id)
    ]
    per_source: dict[str, dict[str, int]] = {s.id: db.stats(s.id) for s in sources}
    totals = db.stats()

    # artifacty — jen počty podle typu (detaily jsou v timeline CLI)
    art_stats = db.artifact_stats()
    artifact_counts = {k: v for k, v in art_stats.items() if k != "total"}

    # chain of custody + flagované soubory — jeden průchod přes files
    rows = db.conn.execute(
        "SELECT source_id, rel_path, size_bytes, sha256, md5, bad_extension,"
        " is_duplicate_of, hash_set_hit FROM files ORDER BY source_id, rel_path"
    ).fetchall()
    custody: list[CustodyItem] = []
    flagged: list[FlaggedFile] = []
    for r in rows:
        custody.append(
            CustodyItem(
                source_id=r["source_id"],
                rel_path=r["rel_path"],
                size_bytes=int(r["size_bytes"] or 0),
                sha256=r["sha256"],
                md5=r["md5"],
            )
        )
        flags = _flags_for(bool(r["bad_extension"]), r["is_duplicate_of"], r["hash_set_hit"])
        if flags:
            flagged.append(FlaggedFile(rel_path=r["rel_path"], flags=flags, sha256=r["sha256"]))

    # ručně označené soubory (GUI File Inspector → „Mark as Evidence“ / „Add to Report“)
    marked = tuple(
        MarkedFile(
            rel_path=rec.rel_path,
            flags=flags,
            size_bytes=int(rec.size_bytes or 0),
            sha256=rec.sha256,
        )
        for rec, flags in db.list_marked()
    )

    # E1 Evidence Manager: audit trail + custody metadata (průběžná evidence)
    audit_entries = tuple(
        AuditEntry(ts=e["ts"], action=e["action"], actor=e.get("actor"), details=e["details"])
        for e in db.list_audit_log(limit=500)
    )
    # list_audit_log vrací nejnovější první — report chce chronologický pořádek
    audit_entries = tuple(reversed(audit_entries))
    custody_metadata = {c["source_id"]: c for c in db.list_custody_items()}

    return ReportData(
        case_id=case.id,
        case_name=case.name,
        examiner=case.examiner,
        created_at=case.created_at,
        notes=case.notes,
        sources=tuple(sources),
        per_source_stats=per_source,
        totals=totals,
        artifact_counts=artifact_counts,
        custody_items=tuple(custody),
        flagged_files=tuple(flagged),
        marked_files=marked,
        audit_entries=audit_entries,
        custody_metadata=custody_metadata,
    )


def generate_html_report(db: CaseDB, case_id: str, out_path: Path | str) -> Path:
    """Vygeneruje HTML report a zapíše do `out_path`. Vrací cestu."""
    data = build_report_data(db, case_id)
    html_doc = build_html(data)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_doc, encoding="utf-8")
    db.log_operation(
        "report_generated",
        actor=data.examiner,
        details={"case_id": case_id, "format": "html", "path": str(out)},
    )
    log.info("HTML report %s → %s", case_id, out)
    return out


def generate_pdf_report(
    db: CaseDB, case_id: str, out_path: Path | str
) -> Path:
    """Vygeneruje PDF report (WeasyPrint). Bez WeasyPrintu → RuntimeError."""
    html_doc = build_html(build_report_data(db, case_id))
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]  # lazy — volitelná závislost
    except ImportError as e:
        raise RuntimeError(
            "WeasyPrint není nainstalován (pip install weasyprint) — "
            "použij HTML report"
        ) from e

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_doc).write_pdf(str(out))
    db.log_operation(
        "report_generated",
        details={"case_id": case_id, "format": "pdf", "path": str(out)},
    )
    log.info("PDF report %s → %s", case_id, out)
    return out


def default_report_name(case: str | None, fmt: str = "html") -> str:
    """Výchozí název souboru reportu — <case>_<datum>.<fmt>."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = case or "case"
    return f"{base}_report_{stamp}.{fmt}"
