"""CLI — P3-4 Evidence Storage Manager (``evidence-storage``).

Příkazy:
    * ``verify <case> [--export FILE | --import FILE]`` — read-only rehash
      kvarentény případu; exit 0 = bez chybějících/poškozených (no_reference
      není fatální), exit 2 = rozdíly nebo chyba domény/repository/prostředí;
    * ``report <case> [--budget MB]`` — kapacitní rozpočet z DB metadata.

JSON výstup nese plné hash a report (machine-readable); text = český souhrn.
"""

from __future__ import annotations

import json
from typing import Any

from stopa.cli._util import _open_db, _print_json
from stopa.data.evidence_storage_repository import EvidenceStorageRepository
from stopa.domain.evidence_storage import build_report


def _entry_dict(e: Any) -> dict[str, Any]:
    return {
        "source_id": e.source_id,
        "rel_path": e.rel_path,
        "status": e.status,
        "expected_sha256": e.expected_sha256,
        "actual_sha256": e.actual_sha256,
        "expected_size": e.expected_size,
        "actual_size": e.actual_size,
    }


def _render_verify_text(case_id: str, report: Any, entries: list[Any]) -> str:
    lines = [
        f"EVIDENCE STORAGE — {case_id} (verify)",
        (f"SOUBORŮ: {report.total_files} | verified {report.verified} | corrupt "
         f"{report.corrupt} | missing {report.missing} | no_reference {report.no_reference}"),
    ]
    labels = {
        "corrupt": "POŠKOZENÝ (hash se liší od referenčního)",
        "missing": "CHYBÍ NA DISKU",
        "no_reference": "BEZ REFERENČNÍHO HASHU (neověřitelný)",
    }
    problems = [e for e in entries if e.status != "verified"]
    for e in problems:
        lines.append(f"  [!] {e.source_id}/{e.rel_path} — {labels[e.status]}")
    if not problems:
        lines.append("  ✓ všechny soubory odpovídají referenci")
    return "\n".join(lines)


def _render_report_text(case_id: str, data: dict[str, Any]) -> str:
    cap = data["capacity"]
    budget = f"{cap['budget_bytes']} B" if cap["budget_bytes"] is not None else "—"
    util = f"{cap['utilization']:.2%}" if cap["utilization"] is not None else "—"
    over = " — PŘE RODPOČETU!" if cap["over_budget"] else ""
    return "\n".join(
        [
            f"EVIDENCE STORAGE — {case_id} (report)",
            f"SOUBORŮ: {data['total_files']} | CELKEM: {data['total_bytes']} B",
            f"ROZPOČET: {budget} | VYUŽITÍ: {util}{over}",
        ]
    )


def cmd_evidence_storage(args: Any) -> int:
    action = getattr(args, "action", None)
    json_mode = bool(getattr(args, "json", False)) or getattr(args, "format", None) == "json"

    budget_bytes: int | None = None
    if getattr(args, "budget", None) is not None:
        # B009 — getattr záměrný: verify Namespace nemá --budget (P3-5 konvence)
        budget_bytes = int(getattr(args, "budget") * 1024 * 1024)  # MB → B  # noqa: B009

    db = _open_db(args.case_id)
    try:
        repo = EvidenceStorageRepository(db.conn)

        if action == "report":
            if getattr(args, "export", None) or getattr(args, "import_file", None):
                raise ValueError("--export/--import patří k akci verify")
            data = repo.report_meta(args.case_id, budget_bytes)
            payload: dict[str, Any] = {"ok": True, "action": "report", **data}
            if json_mode:
                _print_json(payload)
            else:
                print(_render_report_text(args.case_id, payload))
            return 0

        # ── action == "verify" (argparse required=True; defenzivně ValueError)
        entries = repo.verify(args.case_id)
        report = build_report(entries)
        export_to = getattr(args, "export", None)
        import_from = getattr(args, "import_file", None)
        if export_to and import_from:
            raise ValueError("--export a --import jsou vzájemně výlučné")

        imported_count: int | None = None
        if import_from:
            with open(import_from, encoding="utf-8") as handle:
                try:
                    manifest_data = json.load(handle)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"manifest není validní JSON: {exc}") from exc
            repo.import_manifest(args.case_id, manifest_data)
            imported_count = len(manifest_data.get("entries", [])) if isinstance(manifest_data, dict) else 0
            # okamžitá kontrola disku proti importované reference (cizí kvarenténa)
            ref: dict[tuple[str, str], tuple[str, int]] = {}
            for e in manifest_data.get("entries", []) if isinstance(manifest_data, dict) else []:
                ref[(e["source_id"], e["rel_path"])] = (e["sha256"], int(e["size"]))
            entries = repo.verify(args.case_id, reference=ref)
            report = build_report(entries)

        ok = report.missing == 0 and report.corrupt == 0
        payload: dict[str, Any] = {
            "ok": ok,
            "action": "verify",
            "report": {
                "total_files": report.total_files,
                "verified": report.verified,
                "corrupt": report.corrupt,
                "missing": report.missing,
                "no_reference": report.no_reference,
                "expected_bytes": report.expected_bytes,
                "actual_bytes": report.actual_bytes,
            },
            "entries": [_entry_dict(e) for e in entries],
        }

        if export_to:
            manifest = repo.export_manifest(args.case_id, pre_verified=entries)
            with open(export_to, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            payload["manifest_file"] = export_to

        if json_mode:
            _print_json(payload)
        else:
            print(_render_verify_text(args.case_id, report, entries))
            if imported_count is not None:
                print(f"  [i] reference manifest importován ({imported_count} položek)")
            if export_to:
                print(f"  [✓] manifest exportován do {export_to!r}")
        return 0 if ok else 2
    except (ValueError, TypeError) as exc:  # semantická chyba domény/repository → exit 2
        _emit_error(json_mode, action, str(exc))
        return 2
    except RuntimeError as exc:  # např. chybějící cryptography pro Ed25519 podpis
        _emit_error(json_mode, action, f"chyba prostředí: {exc}")
        return 2
    finally:
        db.close()


def _emit_error(json_mode: bool, action: Any, message: str) -> None:
    if json_mode:
        _print_json({"ok": False, "action": action, "error": message})
    else:
        print(f"CHYBA: {message}")
