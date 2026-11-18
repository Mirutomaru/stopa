"""CLI — write-blocker a compliance (wb status/attach/remove, compliance, daubert, attack-map).

P1-4 (refaktor god-file ``cli.py``): přesunuto bez změny chování;
facade ``stopa.cli`` re-exportuje implementace pro kompatibilitu.
"""
from __future__ import annotations

import argparse
import json
import sys

from stopa.data.write_blocker_repository import WriteBlockerRepository  # F5.4
from stopa.domain.write_blocker import (  # F5.4 — write-blocker API
    detect_write_blocker,
    ingest_gate,
    known_vendor_ids,
    vendor_label,
)

from .._util import _load_require_write_blocker, _open_db, _print_json, case_examiner


def cmd_wb_status(args: argparse.Namespace) -> int:
    """F5.4 — aktuální WB stav + rozhodnutí brány (exit 2 = blokováno)."""
    db = _open_db(args.case_id)
    repo = WriteBlockerRepository(db.conn, db.audit_repo)
    state = repo.latest_state()
    require = _load_require_write_blocker()
    gate = ingest_gate(state, require)
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "case_id": args.case_id,
                    "state": state,
                    "require_wb": require,
                    "allowed": gate.allowed,
                    "warning": gate.warning,
                },
                ensure_ascii=False,
            )
        )
    else:
        if state is None:
            print("WB: není připojen (žádný wb_* záznam v audit logu)")
        elif state.get("attached"):
            v = vendor_label(state.get("vendor")) or state.get("vendor") or "?"
            prod = f" {state['product']}" if state.get("product") else ""
            dev = f" ({state['device']})" if state.get("device") else ""
            print(
                f"WB: ✓ připojen — {v}{prod}{dev} "
                f"@ {state.get('ts') or '?'} by {state.get('actor') or '—'}"
            )
        else:
            reason = state.get("reason") or "—"
            print(f"WB: ⚠ odebrán ({reason}) @ {state.get('ts') or '?'}")
        gate_note = "zapnutá" if require else "vypnutá"
        verdict = "pouští ingest" if gate.allowed else "blokuje ingest"
        print(f"Brána (require_write_blocker): {gate_note} → {verdict}")
    return 0 if gate.allowed else 2


def cmd_wb_attach(args: argparse.Namespace) -> int:
    """F5.4 — zaznamenat připojení WB (auto-detekce vendoru z --device)."""
    db = _open_db(args.case_id)
    repo = WriteBlockerRepository(db.conn, db.audit_repo)
    device = (args.device or "").strip()
    match = detect_write_blocker(device) if device else None
    vendor_id = args.vendor or (match.vendor_id if match else None)
    if not vendor_id:
        ids = ", ".join(known_vendor_ids())
        print(
            f"Auto-detekce vendoru nezdarila ({device!r}) — zadte --vendor {ids}",
            file=sys.stderr,
        )
        return 2
    row_id = repo.attach(
        vendor=vendor_id,
        product=args.product,
        device=device or None,
        notes=args.notes,
        actor=case_examiner(db, args.case_id),
    )
    label = vendor_label(vendor_id) or vendor_id
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "case_id": args.case_id,
                    "vendor": vendor_id,
                    "label": label,
                    "detected_from_device": match is not None and bool(device),
                    "audit_id": row_id,
                },
                ensure_ascii=False,
            )
        )
    else:
        src_note = f" (auto-detekce z {device!r})" if match else ""
        print(f"✓ WB připojen: {label}{src_note} [audit #{row_id}]")
    return 0


def cmd_wb_remove(args: argparse.Namespace) -> int:
    """F5.4 — zaznamenat odebrání WB."""
    db = _open_db(args.case_id)
    repo = WriteBlockerRepository(db.conn, db.audit_repo)
    row_id = repo.remove(reason=args.reason, actor=case_examiner(db, args.case_id))
    if getattr(args, "json", False):
        print(json.dumps({"case_id": args.case_id, "audit_id": row_id}, ensure_ascii=False))
    else:
        reason_note = f" ({args.reason})" if args.reason else ""
        print(f"✓ WB odebrán{reason_note} [audit #{row_id}]")
    return 0


def cmd_compliance(args: argparse.Namespace) -> int:
    """F5.2 — SWGDE/ISO 27037 compliance report (JSON + PDF, Ed25519 podpis)."""
    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    try:
        from stopa.presentation.compliance_report import generate_compliance_report

        out = generate_compliance_report(db, args.case_id, out_dir=args.out)
    except KeyError as e:  # případ nenalezen
        if json_mode:
            _print_json({"ok": False, "error": str(e)})
        else:
            print(str(e), file=sys.stderr)
        db.close()
        return 1
    if json_mode:
        import json as _json

        doc = _json.loads(out["json_path"].read_text(encoding="utf-8"))
        _print_json({"ok": True, **doc})
    else:
        signed = "podpsán (Ed25519)" if out["signature_b64"] else "nepodepsaný (chybí cryptography)"
        print(f"Compliance report (F5.2) — {args.case_id}, {signed}")
        print(f"  JSON: {out['json_path']}")
        pdf = out.get("pdf_path")
        if pdf is not None:
            print(f"  PDF:  {pdf}")
        else:
            print("  PDF:  chybí (balík weasyprint nenainstalován)", file=sys.stderr)
        if out.get("digest"):
            print(f"  Digest SHA-256: {out['digest']}")
    db.close()
    return 0


def cmd_daubert(args: argparse.Namespace) -> int:
    """F5.5 — Daubert challenge preparedness pack (1-click JSON balík pro soud)."""
    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    try:
        from stopa.presentation.daubert import generate_daubert_pack

        out = generate_daubert_pack(db, args.case_id, out_dir=args.out)
    except KeyError as e:  # případ nenalezen
        if json_mode:
            _print_json({"ok": False, "error": str(e)})
        else:
            print(str(e), file=sys.stderr)
        db.close()
        return 1
    if json_mode:
        import json as _json

        doc = _json.loads(out["json_path"].read_text(encoding="utf-8"))
        _print_json({"ok": True, **doc})
    else:
        signed = "podepsán (Ed25519)" if out["signature_b64"] else "nepodepsaný (chybí cryptography)"
        print(f"Daubert pack (F5.5) — {args.case_id}, {signed}")
        print(f"  JSON: {out['json_path']}")
        print(
            f"  Reference: {out['references_total']} "
            f"(parserů v případu: {out['case_parsers']})"
        )
        if out.get("digest"):
            print(f"  Digest SHA-256: {out['digest']}")
    db.close()
    return 0


def cmd_attack_map(args: argparse.Namespace) -> int:
    """F6.3 — MITRE ATT&CK mapping: heat-mapa taktik×technik + STIX intrusion-set."""
    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    try:
        from stopa.domain.mitre_attack import (
            ATTACK_TACTICS,
            build_attack_heatmap,
            to_stix_bundle_intrusion_set,
        )

        arts = db.list_artifacts(limit=10_000)
        hm = build_attack_heatmap(arts)
        case_name = None
        case = db.get_case(args.case_id)  # type: ignore[call-arg]
        if case is not None:
            case_name = getattr(case, "name", None)

        fmt = args.format
        if fmt == "stix":
            payload = to_stix_bundle_intrusion_set(
                args.case_id, case_name=case_name, heatmap=hm
            )
        else:
            import json as _json

            payload = _json.dumps(hm, ensure_ascii=False, indent=2)

        if args.out:
            from pathlib import Path

            out_path = Path(args.out).expanduser().resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(payload + "\n", encoding="utf-8")
            target = str(out_path)
        else:
            target = None

        s_ = hm["summary"]
        if json_mode:
            envelope: dict = {
                "ok": True,
                "format": fmt,
                "case_id": args.case_id,
                "out": target,
                **s_,
            }
            if target is None:  # celý payload v JSON obálce (jediný dokument na stdout)
                if fmt == "json":
                    envelope["heatmap"] = hm
                else:
                    import json as _stix_json

                    envelope["bundle"] = _stix_json.loads(payload)
            _print_json(envelope)
        else:
            print(
                f"ATT&CK map (F6.3) — {args.case_id}, formát {fmt}"
                + (f", výstup {target}" if target else "")
            )
            print(
                f"  Artefakty: {s_['artifacts_total']} "
                f"(mapováno {s_['mapped_artifacts']}, techniky {s_['techniques_hit']})"
            )
            by_tactic: dict[str, list[dict]] = {}
            for t in hm["techniques"]:
                by_tactic.setdefault(t["tactic"], []).append(t)
            for tid, tname in ATTACK_TACTICS:
                rows = by_tactic.get(tid)
                if not rows:
                    continue
                parts = ", ".join(
                    f"{r['id']} {r['name']}" + (f" (×{r['count']})" if r["count"] > 1 else "")
                    for r in sorted(rows, key=lambda x: x["id"])
                )
                print(f"  [{tid}] {tname}: {parts}")
    finally:
        db.close()
    return 0


# ── F6.4 — Plugin ecosystem ─────────────────────────────────────


