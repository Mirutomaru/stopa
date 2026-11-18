"""CLI — životní cyklus případu (validate/analyze/audit/backup).

P1-4 (refaktor god-file ``cli.py``): přesunuto bez změny chování;
facade ``stopa.cli`` re-exportuje implementace pro kompatibilitu.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_log = logging.getLogger("stopa.cli.lifecycle")

from .._util import (
    _db_dir,
    _load_ai_redact_pii,
    _open_db,
    _print_json,
    _rich_progress,
    case_examiner,
)


def cmd_validate(args: argparse.Namespace) -> int:
    """P0 Core C6 — Evidence Validation Report per případ."""
    from stopa.data.validation_report import build_validation_report, report_to_json

    db = _open_db(args.case_id)
    rep = build_validation_report(db, args.case_id)
    cov = rep["coverage"]

    if not getattr(args, "json", False):
        print(f"Validační report: {args.case_id} ({rep['total_artifacts']} artefaktů)")
        for status, n in sorted(rep["by_status"].items()):
            print(f"  {status}: {n}")
        print(
            f"Coverage validace: {cov['covered_artifacts']}/{cov['total_artifacts']} "
            f"({cov['coverage_pct']}%)"
        )
        if cov["uncovered_parsers"]:
            print("Nepokrivené parsery: " + ", ".join(cov["uncovered_parsers"]))

    if args.json:
        print(report_to_json(rep))
    db.close()
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    """P0 Intelligence I1 — AI orchestrace (5 agentů, auto/explicitní routing)."""
    import json as _json

    from stopa.data.lmstudio_client import LmStudioClient, LmStudioUnavailable
    from stopa.intelligence import (
        OrchestrationError,
        audit_ai_query,
        build_case_context,
        orchestrate,
        prompt_hash,
        retrieve,
    )

    db = _open_db(args.case_id)
    try:
        client = LmStudioClient()
        health = client.health()
        if not health["available"]:
            if getattr(args, "json", False):
                _print_json({"error": "lmstudio_unavailable"})
            else:
                print("AI nedostupná — spusťte LM Studio (localhost:1234)")
            return 1

        context = build_case_context(db, args.case_id)
        # P0 Intelligence I2 — Forensic RAG: retrieval napříč vrstvami
        rag = retrieve(args.question, db=db, case_id=args.case_id)
        # STP-019 — PII redaktor (settings.json toggle, default ON)
        redact_pii = _load_ai_redact_pii()
        json_mode = getattr(args, "json", False)
        # R0.4 — progress bar u analyze (LLM volání trvá řádově desítky sekund)
        bar = None if json_mode else _rich_progress()
        task_id = bar.add("AI orchestrace…", 100) if bar is not None else None
        try:
            result = orchestrate(
                client.chat,
                context,
                args.question,
                agent_id=args.agent,
                rag=rag,
                redact_pii=redact_pii,
            )
        except LmStudioUnavailable as exc:
            if json_mode:
                _print_json({"error": "lmstudio_unavailable", "detail": str(exc)})
            else:
                print(f"AI nedostupná: {exc}")
            return 1
        except OrchestrationError as exc:
            if json_mode:
                _print_json({"error": "orchestration_failed", "detail": str(exc)})
            else:
                print(f"AI orchestrace selhala: {exc}")
            return 1
        finally:
            if bar is not None and task_id is not None:
                try:
                    bar.update(task_id, completed=100)
                    bar.stop()
                except Exception as exc:  # noqa: BLE001 — progress je kosmetický
                    _log.debug("Rich progress completion selhala: %s", exc)

        # audit AI dotazu (evidence modelu + promptu) — analysis_operations
        from stopa.intelligence.ai_orchestrator import build_prompt, route_agent

        profile = route_agent(args.question, args.agent)
        ph = prompt_hash(
            build_prompt(profile, context, args.question, rag=rag, redact_pii=redact_pii)
        )
        audit_ai_query(
            db,
            case_id=args.case_id,
            question=args.question,
            model=str(health.get("model") or None),
            prompt_sha256=ph,
            citations=result.citations,
            agent=result.agent_id,
        )

        db.log_operation(
            "ai_analyzed",
            actor="cli",
            details={
                "agent": result.agent_id,
                "question": args.question[:200],
                "citations": result.citations,
                "duration_ms": round(result.duration_ms, 1),
            },
        )

        if args.json:
            print(
                _json.dumps(
                    {
                        "agent": result.agent_id,
                        "output": result.output.model_dump(mode="json"),
                        "citations": result.citations,
                        "rag": {
                            "case": len(rag.case_chunks),
                            "technical": len(rag.technical_chunks),
                            "knowledge": len(rag.knowledge_chunks),
                        },
                        "prompt_chars": result.prompt_chars,
                        "duration_ms": round(result.duration_ms, 1),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            print(f"Agent: {result.agent_id} ({result.duration_ms:.0f} ms)")
            print(_json.dumps(result.output.model_dump(mode="json"), ensure_ascii=False, indent=2))
            if result.citations:
                print("Citace: " + ", ".join(result.citations))
        return 0
    finally:
        db.close()


def cmd_audit(args: argparse.Namespace) -> int:
    """E1 Evidence Manager: neměnná stopa operací (audit trail)."""
    db = _open_db(args.case_id)
    entries = db.list_audit_log(limit=args.limit, offset=args.offset)
    if getattr(args, "json", False):
        # chronologicky — nejstarší první (stopa čtená od začátku)
        _print_json([
            {
                "ts": e["ts"],
                "action": e["action"],
                "actor": e.get("actor"),
                "details": e["details"] if args.verbose else None,
            }
            for e in reversed(entries)
        ])
    elif not entries:
        print("(prázdný audit log)")
    else:
        # chronologicky — nejstarší první (stopa čtená od začátku)
        for e in reversed(entries):
            ts = e["ts"][:19].replace("T", " ")
            actor = f" [{e['actor']}]" if e.get("actor") else ""
            details = {k: v for k, v in e["details"].items() if not str(k).endswith("_total")}
            det = f"  {json.dumps(details, ensure_ascii=False)}" if details and args.verbose else ""
            print(f"{ts}  {e['action']}{actor}{det}")
    db.close()
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    """E1 Evidence Manager: záloha case DB (SQLite .backup() — konzistentní snapshot).

    Pravidlo 4: před migracemi vytvářej zálohu. Výchozí název <case>_backup_<ts>.db.
    """
    import sqlite3
    from datetime import datetime, timezone

    db = _open_db(args.case_id)
    out_dir = Path(args.out).expanduser() if args.out else _db_dir().parent / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"{args.case_id}_backup_{stamp}.db"

    src = db.conn
    dst = sqlite3.connect(out_path)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()

    # integrita zálohy — otevření + kontrola integrity (PRAGMA quick_check)
    chk = sqlite3.connect(out_path)
    ok = chk.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    n_files = chk.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    chk.close()

    db.log_operation(
        "db_backed_up",
        actor=case_examiner(db, args.case_id),
        details={
            "case_id": args.case_id,
            "path": str(out_path),
            "integrity_ok": ok,
            "files_in_backup": n_files,
        },
    )
    db.close()
    if not ok:
        if getattr(args, "json", False):
            _print_json({"error": "integrity_check_failed", "path": str(out_path)})
        else:
            print(f"Záloha selhala integritní kontrolou: {out_path}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        _print_json({
            "path": str(out_path),
            "size_mb": round(out_path.stat().st_size / 1e6, 2),
            "files_in_backup": n_files,
            "integrity_ok": ok,
        })
        return 0
    size = out_path.stat().st_size / 1e6
    print(f"Záloha vytvořena: {out_path} ({size:.2f} MB, {n_files} souborů, integrity OK)")
    return 0


