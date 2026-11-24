"""CLI — reprodukovatelnost (integrity/replay/benchmark).

P1-4 (refaktor god-file ``cli.py``): přesunuto bez změny chování;
facade ``stopa.cli`` re-exportuje implementace pro kompatibilitu.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .._util import _open_db, _print_json, case_examiner


def cmd_integrity(args: argparse.Namespace) -> int:
    """P0 Core C4 — Evidence Integrity 2.0: hash chaining + Ed25519 kontrolní body."""
    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)

    # 1) Hash chaining audit logu (ověřitelné bez klíče).
    report = db.verify_audit_chain()
    if not json_mode:
        if report.ok:
            print(f"Hash řetězec audit logu: OK ({report.rows_checked} řádků)")
        else:
            print(
                f"Hash řetězec audit logu: ROZBITÝ na řádku {report.broken_at_id}"
                f" — {report.reason}",
                file=sys.stderr,
            )

    # 2) Ed25519 klíč + kontrolní body.
    pub = db.integrity_public_key()
    if args.init_key and pub is None:
        _, new_pub = db.ensure_integrity_key()
        if not json_mode:
            print(f"Ed25519 klíč vygenerován: {new_pub[:16]}…")
        pub = new_pub
    elif pub is not None and not json_mode:
        print(f"Ed25519 veřejný klíč: {pub[:16]}… ({len(pub)} b64 znaků)")
    elif pub is None and not args.init_key and not json_mode:
        print("Ed25519 klíč: nevygenerován (použij --init-key)")

    cps = db.list_integrity_checkpoints()
    results: list[dict] = []
    if not cps and not json_mode:
        print("Kontrolní body: 0")
    elif cps:
        results = db.verify_integrity_checkpoints()
        ok_count = sum(1 for r in results if r.get("ok"))
        if not json_mode:
            print(f"Kontrolní body: {len(cps)} ({ok_count} platných podpisů)")
            for cp, res in zip(cps, results):
                mark = "✓" if res.get("ok") else "✗"
                print(
                    f"  [{mark}] #{cp['id']} audit_row={cp['audit_row_id']} "
                    f"{cp['reason'] or '—'} {cp['ts']}"
                )

    # 3) Nový kontrolní bod na požádání.
    new_cp_id = None
    if args.checkpoint:
        if db.integrity_public_key() is None:
            print("Klíč nevygenerován — použij --init-key", file=sys.stderr)
            db.close()
            return 2
        new_cp_id = db.add_integrity_checkpoint(args.checkpoint)
        if new_cp_id is None:
            print("Kontrolní bod neuložen (chybí klíč)", file=sys.stderr)
            db.close()
            return 2
        if not json_mode:
            print(f"Nový kontrolní bod #{new_cp_id} ({args.checkpoint})")

    if json_mode:
        _print_json({
            "audit_chain_ok": report.ok,
            "rows_checked": report.rows_checked,
            "broken_at_id": report.broken_at_id,
            "reason": None if report.ok else report.reason,
            "public_key": pub,
            "checkpoints_total": len(cps),
            "checkpoints_valid": sum(1 for r in results if r.get("ok")),
            "new_checkpoint_id": new_cp_id,
        })
    db.close()
    # exit code: 0 = řetězec OK, 1 = rozbitý řetězec
    return 0 if report.ok else 1


def cmd_replay(args: argparse.Namespace) -> int:
    """P0 Core C5 — Reproducibility Engine: opakovat zaznamenanou operaci + porovnání."""
    from stopa.pipeline import replay_extract

    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    ops = db.list_operations(case_id=args.case_id, op_type="extract")
    if not ops:
        if json_mode:
            _print_json({"error": "no_extract_operations"})
        else:
            print("Žádné zaznamenané extract operace (předtím `stopa add`)", file=sys.stderr)
        db.close()
        return 2

    target = db.get_operation(args.op) if args.op else ops[-1]
    if target is None:
        if json_mode:
            _print_json({"error": "operation_not_found", "op_id": args.op})
        else:
            print(f"Operace nenalezena: {args.op}", file=sys.stderr)
        db.close()
        return 2

    src = db.get_source(target.source_id or "")
    if src is None:
        if json_mode:
            _print_json({"error": "source_not_found", "source_id": target.source_id})
        else:
            print(f"Zdroj operace neexistuje: {target.source_id}", file=sys.stderr)
        db.close()
        return 2
    root = Path(src.path).expanduser()
    if not root.exists():
        if json_mode:
            _print_json({"error": "source_path_missing", "path": str(root)})
        else:
            print(f"Zdroj už není na disku: {root}", file=sys.stderr)
        db.close()
        return 2

    if not json_mode:
        print(f"Replay operace {target.id} (zdroj: {src.path})")
    res = replay_extract(target, root)

    if not json_mode:
        if res.inputs_identical:
            print("Vstupní soubory: OK (SHA-256 shodné se záznamem)")
        else:
            print(f"Vstupní soubory: ZMĚNĚNY ({len(res.input_diffs)} rozdílů)", file=sys.stderr)
            for d in res.input_diffs[:10]:
                print(f"  ! {d}", file=sys.stderr)

        if res.outputs_identical:
            print("Výstupní souhrn: IDENTICKÝ (operace je reprodukovatelná)")
        else:
            print(f"Výstupní souhrn: LIŠÍ ({len(res.output_diffs)} rozdílů)", file=sys.stderr)
            for d in res.output_diffs[:10]:
                print(f"  ! {d}", file=sys.stderr)

    db.log_operation(
        "operation_replayed",
        actor=case_examiner(db, args.case_id),
        details={
            "op_id": target.id,
            "inputs_identical": res.inputs_identical,
            "outputs_identical": res.outputs_identical,
        },
    )
    db.close()
    if json_mode:
        _print_json({
            "op_id": target.id,
            "source_path": src.path,
            "inputs_identical": res.inputs_identical,
            "outputs_identical": res.outputs_identical,
            "input_diffs": res.input_diffs[:10],
            "output_diffs": res.output_diffs[:10],
        })
    return 0 if (res.inputs_identical and res.outputs_identical) else 1


def cmd_benchmark(args: argparse.Namespace) -> int:
    """P0 Core C6 — Benchmark Engine: deterministické benchmarky + detekce regresí."""
    from stopa.data.benchmark_engine import (
        check_regressions,
        run_benchmark,
        save_history,
    )

    json_mode = getattr(args, "json", False)
    if not json_mode:
        print(f"Benchmark suite: {args.suite}")
    results = run_benchmark(suite=args.suite)
    if not results:
        if json_mode:
            _print_json({"suite": args.suite, "results": [], "error": "all_workloads_failed"})
        else:
            print("Žádné výsledky (selhaly všechny workloads)", file=sys.stderr)
        return 2

    if not json_mode:
        for r in results:
            pct = ""
            if r.median_ms is not None and r.p95_ms is not None:  # B6: osa medián/P95
                pct = f" | med {r.median_ms:.3f} p95 {r.p95_ms:.3f}"
            print(
                f"  {r.name:<24} {r.duration_ms:>10.3f} ms{pct} | "
                f"RAM peak {r.ram_peak_bytes / 1e6:>8.2f} MB | artefakty {r.artifacts}"
            )

    # historie + regresní detekce (jen s případem — meta benchmark_history)
    warnings: list = []
    if args.case_id:
        db = _open_db(args.case_id)
        warnings = check_regressions(db, results)
        save_history(db, results)
        db.log_operation(
            "benchmark_run",
            actor=case_examiner(db, args.case_id),
            details={"suite": args.suite, "results": len(results)},
        )
        db.close()
        if not json_mode:
            if warnings:
                print(f"\n⚠ Regrese výkonu (>20% proti baseline): {len(warnings)}")
                for w in warnings:
                    print(
                        f"  ! [{w.axis}] {w.name}: {w.baseline_ms:.3f} → "
                        f"{w.current_ms:.3f} ms (+{w.delta_pct}%)"
                    )
            else:
                print("\nRegrese výkonu: žádná (baseline OK)")

    if json_mode:
        _print_json({
            "suite": args.suite,
            "results": [
                {"name": r.name, "duration_ms": r.duration_ms,
                 "median_ms": r.median_ms,  # B6: osa medián (None = starý běh)
                 "p95_ms": r.p95_ms,
                 "ram_peak_bytes": r.ram_peak_bytes, "artifacts": r.artifacts}
                for r in results
            ],
            "regressions": [
                {"name": w.name, "axis": w.axis,  # B6: osa regrese (mean|median|p95)
                 "baseline_ms": w.baseline_ms,
                 "current_ms": w.current_ms, "delta_pct": w.delta_pct}
                for w in warnings
            ],
        })
    return 0


