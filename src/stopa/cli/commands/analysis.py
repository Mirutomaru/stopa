"""CLI — kvalita parserů, AI orchestrátor a reparse (parser-quality/ai-run/parser-status/reparse).

P1-4 (refaktor god-file ``cli.py``): přesunuto bez změny chování;
facade ``stopa.cli`` re-exportuje implementace pro kompatibilitu.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from stopa.data.db import CaseDB
from stopa.models import Case, EvidenceSource

from .._util import _open_db, _print_json


def cmd_parser_quality(args: argparse.Namespace) -> int:
    """P1-1 parser quality framework — per-parser pokrytí 8 quality kategorií.

    Pokrytí = unie ``# quality:`` markerů všech testovacích souborů deklarovaných
    pro parser v C3 registry. Nevyžaduje case DB (registry level).
    Exit: 0 = OK; 1 = chyba; 2 = --fail-below a category_coverage_pct pod prahem.
    """
    json_mode = getattr(args, "json", False) or getattr(args, "format", None) == "json"

    from stopa.data.parser_quality_service import build_parser_quality_report

    try:
        report = build_parser_quality_report()
    except Exception as e:  # noqa: BLE001 — CLI hrana (log + exit kód)
        if json_mode:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
        else:
            print(f"Chyba stavby quality reportu: {e}")
        return 1

    threshold = getattr(args, "fail_below", None)
    if not json_mode:
        print(
            f"P1-1 parser quality — {report['quality_complete']}/{report['count']} "
            f"parserů kompletních (coverage {report['coverage_pct']} %, "
            f"kategorie {report['category_coverage_pct']} %)"
        )
        for row in report["parsers"]:
            mark = "✓" if not row["missing"] else "·"
            missing = ",".join(row["missing"]) or "—"
            print(f"{mark} {row['parser_id']:<28} chybí: {missing}")
    else:
        print(json.dumps(report, ensure_ascii=False))

    if threshold is not None and report["category_coverage_pct"] < float(threshold):
        return 2
    return 0


def cmd_ai_run(args: argparse.Namespace) -> int:
    """P1-2 — AI role agenta nad důkazy případu (LM Studio orchestrátor).

    Důkaz = explicitní ``--artifact`` ID, nebo implicitně poslední 5 artefaktů.
    Auditní záznamy ``ai_role_call`` jdou do case audit_log (+ WS push F4.2).
    Exit: 0 = validovaný strukturovaný výstup; 2 = volání OK, ale výstup
    nesplnil schema role (payload=None — QA signál); 1 = chyba (role/artefakt/
    nedostupný klient/překročený budget).
    """
    json_mode = getattr(args, "json", False)

    from stopa.data.ai_orchestrator_service import AiOrchestrationError, run_role_on_case

    db = _open_db(args.case_id)
    try:
        call, used_ids = run_role_on_case(
            db, args.role, question=args.question or "", artifact_ids=args.artifact
        )
    except (ValueError, AiOrchestrationError) as e:  # CLI hrana — obojí semantické chyby
        if json_mode:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
        else:
            print(f"Chyba AI role {args.role!r}: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()

    result = {
        "role": call.role_id,
        "validated": call.payload is not None,
        "payload": call.payload,
        "text": call.text,
        "tokens_out": call.tokens_out,
        "attempts": call.attempts,
        "evidence": used_ids,
    }
    if json_mode:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"AI role {call.role_id} — pokusů {call.attempts}, tokenů(out) {call.tokens_out}")
        print(f"Důkaz: {', '.join(used_ids)}")
        if call.payload is not None:
            print(json.dumps(call.payload, ensure_ascii=False, indent=2))
        else:
            print("Výstup nesplnil schema role (payload=None) — QA signál:")
            print(f"  {call.text[:400]}")
    return 0 if call.payload is not None else 2


def cmd_ai_eval(args: argparse.Namespace) -> int:
    """P4-5 — AI eval gate: zlatá suita rolí orchestrátoru (offline, deterministická).

    Spustí každou roli přes produkční cestu (prompt build → validace výstupu
    podle ROLE_OUTPUT_SCHEMA) na deterministickém klientovi s přehráváním
    zlatých odpovědí. Regrese (rozbitý scénář) → exit 1; vše zelené → 0.

    Příklad::

        stopa ai-eval --suite gold [--json]
    """
    json_mode = getattr(args, "json", False)
    suite = getattr(args, "suite", None) or "gold"
    if suite != "gold":
        print(f"Chyba: neznámá suita {suite!r} (očekáváno 'gold')", file=sys.stderr)
        return 1

    from stopa.intelligence.ai_eval import run_gold_suite, suite_summary

    summary = suite_summary(run_gold_suite())
    if json_mode:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        for r in summary["results"]:
            mark = "OK  " if r["ok"] else "FAIL"
            line = f"{mark} {r['role_id']}"
            if not r["ok"]:
                line += f" — {r['error']}"
            print(line)
        print(
            f"\nSUITA gold: {summary['passed']}/{summary['total']} rolí OK"
            + (f", selhaly: {', '.join(summary['failed'])}" if summary["failed"] else "")
        )
    return 0 if not summary["failed"] else 1


def cmd_parser_status(args: argparse.Namespace) -> int:
    """P0-4 validation lab — per-parser validační status (registry level).

    Staví na C3 registry (`domain.validation_registry`): pro každý registrovaný
    parser vypíše validační status, pokrytí testy a reference dataset. Nevyžaduje
    case DB — jde o stav registrace parserové sady, ne jednotlivého případu.

    Exit: 0 = OK (případně --fail-on-unvalidated a vše validované);
          1 = chyba;
          2 = --fail-on-unvalidated a existují unvalidované parserty (CI gate).
    """
    json_mode = getattr(args, "json", False) or getattr(args, "format", None) == "json"
    fail_on_unvalidated = getattr(args, "fail_on_unvalidated", False)

    from stopa.data.parser_status_service import load_parser_status

    try:
        report = load_parser_status()
    except Exception as e:  # noqa: BLE001 — CLI obal: libovolná chyba → čitelný výstup
        if json_mode:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
        else:
            print(f"parser status selhal: {e}", file=sys.stderr)
        return 1

    if json_mode:
        print(json.dumps(report, ensure_ascii=False, default=str))
    else:
        print(
            f"Parser status (C3 registry + P0-4): "
            f"{report['validated']}/{report['count']} validováno, "
            f"reference datasety {report['dataset_coverage_pct']} %"
        )
        for r in report["parsers"]:
            ds = "✓" if r["reference_dataset"] else "-"
            lim = f", {r['limitations_count']} limitací" if r["limitations_count"] else ""
            print(
                f"{r['validation_status']:<12} {r['parser_id']:<34} "
                f"v{r['version']}  formáty={r['formats_count']}  "
                f"testy={r['direct_tests']}/{r['total_tests']}  dataset={ds}{lim}"
            )
        if report["unvalidated"]:
            print(f"\nUnvalidované parserty: {', '.join(report['unvalidated'])}")

    return (2 if fail_on_unvalidated and report["unvalidated"] else 0)


def cmd_reparse(args: argparse.Namespace) -> int:
    """F5.3 — re-run extrakce s deklarovánou verzí parseru + diff report.

    Semantika (staví na C5 Reproducibility Engine):
      1. base snapshot = nejnovější extract operace zdroje (analysis_operations),
      2. ověření vstupních souborů (SHA-256 na disku vs. snapshot),
      3. čistá dočasná DB — původní případ se nedotkne (append-only evidence);
         extrakce běží s prokládanou verzí parserové sady (pinned provenience),
      4. diff report: deterministický souhrn výstupů + mapy verzí parserů,
      5. snapshot storage — reparse se appenduje do analysis_operations.

    Exit: 0 = vstupy OK a výstupy identické (reprodukovatelné); 1 = chyba;
    2 = nalezeny rozdíly (vstupy nebo výstupy).
    """
    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    try:
        import tempfile
        import time as _time

        from stopa import __version__ as _stopa_ver
        from stopa.domain.hashing import hash_file
        from stopa.domain.reproducibility import (
            compare_outputs,
            verify_inputs,
            version_diffs,
        )
        from stopa.pipeline import parser_versions, process_source, summarize_outputs

        base_op = db.artifact_repo.latest_extract_op(source_id=args.source_id)
        if base_op is None:
            msg = "žádná zaznamenaná extrakční operace (op_type='extract') v případě"
            print(msg, file=sys.stderr) if not json_mode else _print_json(
                {"ok": False, "error": msg}
            )
            return 1
        source_id = base_op.source_id
        src_row = db.conn.execute(
            "SELECT path FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if src_row is None:
            raise KeyError(f"zdroj {source_id} nenalezen v DB")
        root = Path(src_row["path"])
        if not root.exists():
            raise FileNotFoundError(f"kořen zdroje neexistuje na disku: {root}")
        profile_name = base_op.params_json.get("profile", "forensic")

        # 1) vstupní ověření — aktuální hashe na disku vs. base snapshot (C5)
        current_hashes: dict[str, str | None] = {}
        for f in base_op.input_files:
            rel = f.get("rel_path") or ""
            p = root / rel if not root.is_file() else root
            try:
                digests = hash_file(p, ["sha256"]) or {}
                current_hashes[rel] = digests.get("sha256")
            except OSError:
                current_hashes[rel] = None  # soubor zmizel / nečitelný
        inputs_ok, input_diffs = verify_inputs(list(base_op.input_files), current_hashes)

        # 2) čistá dočasná DB — původní případ se nedotkne (append-only evidence)
        workdir = Path(args.workdir) if getattr(args, "workdir", None) else Path(
            tempfile.gettempdir()
        )
        tmp_db_path = workdir / f"stopa-reparse-{source_id}.db"
        t0 = _time.monotonic()
        replay_db = CaseDB(tmp_db_path)
        try:
            case = Case(name=f"reparse {source_id}")
            replay_db.add_case(case)
            src = EvidenceSource(
                case_id=case.id, kind="folder", path=str(root), size_bytes=None
            )
            replay_db.add_source(src)
            result = process_source(
                replay_db,
                src.id,
                root,
                profile_name=profile_name,
                pinned_parser_version=args.parser_version,
            )
        finally:
            replay_db.close()

        # 3) snapshot storage — reparse operace se appenduje do case DB (historie verzí)
        new_versions = {**parser_versions(), "pinned": args.parser_version}
        new_op_id = db.record_operation(
            "reparse",
            case_id=base_op.case_id,
            source_id=source_id,
            input_files=list(base_op.input_files),
            parser_versions=new_versions,
            stopa_version=_stopa_ver,
            config_hash=base_op.config_hash,
            params={
                "profile": profile_name,
                "pinned_parser_version": args.parser_version,
                "original_op_id": base_op.id,
            },
            outputs=summarize_outputs(result),
            duration_ms=int((_time.monotonic() - t0) * 1000),
        )
        db.log_operation(
            "reparse_completed",
            details={
                "source_id": source_id,
                "pinned_parser_version": args.parser_version,
                "original_op_id": base_op.id,
                "reparse_op_id": new_op_id,
                "inputs_identical": inputs_ok,
            },
        )

        # 4) diff report — výstupy + verze parserů (base vs. reparse)
        out_report = compare_outputs(base_op.outputs_json, summarize_outputs(result))
        vdiffs = version_diffs(base_op.parser_versions or {}, new_versions)
        out = {
            "ok": True,
            "case_id": db.path.stem,
            "source_id": source_id,
            "profile": profile_name,
            "pinned_parser_version": args.parser_version,
            "original_op_id": base_op.id,
            "reparse_op_id": new_op_id,
            "inputs_identical": inputs_ok,
            "input_diffs": list(input_diffs),
            "outputs_identical": out_report.identical,
            "output_diffs": list(out_report.diffs),
            "version_diffs": list(vdiffs),
        }
        if json_mode:
            _print_json(out)
        else:
            print(f"Reparse (F5.3) — zdroj {source_id}, prokládaná verze parseru: {args.parser_version}")
            print(f"  base snapshot: op {base_op.id} ({profile_name}) → reparse op {new_op_id}")
            if inputs_ok:
                print(f"  vstupní soubory: OK ({len(base_op.input_files)}× SHA-256 shodné)")
            else:
                print("  vstupní soubory: ZMĚNENY")
                for d in list(input_diffs)[:10]:
                    print(f"    - {d}")
                if len(input_diffs) > 10:
                    print(f"    … a dalších {len(input_diffs) - 10}")
            if out_report.identical:
                print("  výstupy: identické (reprodukovatelné)")
            else:
                print("  výstupy: LIŠÍ")
                for d in list(out_report.diffs)[:20]:
                    print(f"    - {d}")
            if vdiffs:
                print("  verze parserů:")
                for d in list(vdiffs)[:15]:
                    print(f"    - {d}")
        return 0 if (inputs_ok and out_report.identical) else 2
    except Exception as e:  # noqa: BLE001 — defenzivně: reparse nezanechá traceback
        if json_mode:
            _print_json({"ok": False, "error": f"reparse selhalo: {e}"})
        else:
            print(f"reparse selhalo: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()


# ── F5.4 — Write-blocker integration API (status/attach/remove) ────────────────
