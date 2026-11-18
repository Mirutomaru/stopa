"""CLI — integrita a původ (verify/seal/klíče/provenance/evidence-graph).

P1-4 (refaktor god-file ``cli.py``): přesunuto bez změny chování;
facade ``stopa.cli`` re-exportuje implementace pro kompatibilitu.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .._util import _open_db, _print_json, case_examiner


def cmd_verify(args: argparse.Namespace) -> int:
    """E1 Evidence Manager: re-hash všech souborů v případu a porovnání s evidencí.

    Důkaz integrity — SHA-256 + MD5 (chunked, read-only přístup k originálům).
    Výsledek se zapíše do neměnného audit logu (`hash_verified`).
    """
    from stopa.domain.hashing import hash_file

    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    sources = db.list_sources(args.case_id)
    if not sources:
        if json_mode:
            _print_json({"ok": 0, "mismatched": 0, "missing": 0, "skipped": 0,
                         "problems": [], "sources": 0})
        else:
            print("(žádné evidence sources)")
        db.close()
        return 0

    ok = mismatched = missing = skipped = 0
    problems: list[str] = []
    for src in sources:
        root = Path(src.path).expanduser()
        rows = db.conn.execute(
            "SELECT rel_path, sha256, md5 FROM files WHERE source_id = ? ORDER BY rel_path",
            (src.id,),
        ).fetchall()
        for r in rows:
            if root.is_file():
                p = root  # file zdroj — rel_path je jen jméno souboru
            else:
                p = root / r["rel_path"]
            if not p.exists():
                missing += 1
                problems.append(f"CHYBÍ: {src.path}/{r['rel_path']}")
                continue
            try:
                digests = hash_file(p, ["md5", "sha256"])
            except OSError as e:
                skipped += 1
                problems.append(f"NELZE ČÍST: {r['rel_path']}: {e}")
                continue
            bad = []
            if r["sha256"] and digests.get("sha256") != r["sha256"]:
                bad.append("SHA-256")
            if r["md5"] and digests.get("md5") != r["md5"]:
                bad.append("MD5")
            if bad:
                mismatched += 1
                problems.append(f"ROZDÍL ({', '.join(bad)}): {r['rel_path']}")
            else:
                ok += 1

    # F5.1 — Merkle zamčení případu: DB-only ověření všech pečetí (nezávislé na
    # E1 re-hashování; nový audit řádek pečeť neruší — snapshot s předponou).
    seal_reports = db.seal_repo.verify_all()
    seals_valid = sum(1 for r in seal_reports if r["ok"])

    db.log_operation(
        "hash_verified",
        actor=case_examiner(db, args.case_id),
        details={
            "ok": ok,
            "mismatched": mismatched,
            "missing": missing,
            "skipped": skipped,
            "seals_total": len(seal_reports),
            "seals_valid": seals_valid,
        },
    )
    if json_mode:
        _print_json({
            "ok": ok, "mismatched": mismatched, "missing": missing,
            "skipped": skipped, "problems": problems[: args.limit],
            "sources": len(sources),
            "merkle_seal": {
                "total": len(seal_reports),
                "valid": seals_valid,
                "seals": seal_reports,
            },
        })
    else:
        print(f"Integrita: {ok} OK, {mismatched} rozdílů, {missing} chybí, {skipped} nečitelných")
        for p in problems[: args.limit]:
            print(f"  ! {p}")
        if len(problems) > args.limit:
            print(f"  … a dalších {len(problems) - args.limit}")
        if seal_reports:
            print(f"Merkle zamčení (F5.1): {len(seal_reports)} pečetí — {seals_valid} platných")
            for r in seal_reports:
                if r["ok"]:
                    status = "root OK, podpis OK"
                else:
                    changed = ", ".join(r["changed_tables"]) or "—"
                    status = (f"root {'OK' if r['root_ok'] else 'ROZDÍL'} ({changed}), "
                              f"podpis {'OK' if r['sig_ok'] else 'NEPLATNÝ'}")
                print(f"  [{'✓' if r['ok'] else '✗'}] #{r['id']} {r['ts']} — {status}")
        else:
            print("Merkle zamčení (F5.1): žádné pečetě (stopa seal <case_id>)")
    db.close()
    return 1 if (mismatched or missing or seals_valid != len(seal_reports)) else 0


def cmd_seal(args: argparse.Namespace) -> int:
    """F5.1 — Merkle zamčení případu: snapshot stavu zamčený podepsaným kořenem."""
    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    actor = case_examiner(db, args.case_id)
    try:
        seal = db.seal_case(reason=args.reason, actor=actor)
    except RuntimeError as e:  # chybí volitelný balík cryptography
        if not json_mode:
            print(f"Ed25519 nedostupné ({e})", file=sys.stderr)
        db.close()
        return 2
    if seal is None:
        msg = "Ed25519 klíč případu nevygenerován (vyžaduje balík cryptography)"
        if json_mode:
            _print_json({"ok": 0, "seal_id": None, "reason": "no_key"})
        else:
            print(msg, file=sys.stderr)
        db.close()
        return 2
    if json_mode:
        _print_json(seal)
    else:
        print(f"Případ zamčen (F5.1): pečeť #{seal['id']}")
        print(f"  Root: {seal['root_hash']}")
        print(
            f"  Rozsah: artifacts={seal['artifacts']}, "
            f"timeline_events={seal['timeline_events']}, audit_log={seal['audit_log']} řádků"
        )
        who = seal["sealed_by"] or "—"
        why = f" — {seal['reason']}" if seal["reason"] else ""
        print(f"  Zamčeno: {who} ({seal['ts']}){why}")
    db.close()
    return 0


def _ed25519_fingerprint(public_b64: str) -> str:
    """P0-2: krátký otisk veřejného klíče (SHA-256 raw klíče, první 8 B hex)."""
    import base64 as _b64
    import hashlib

    return hashlib.sha256(_b64.b64decode(public_b64)).hexdigest()[:16]


def _rotate_err(e: RuntimeError, json_mode: bool) -> None:
    """P0-2: jednotná chyba `rotate-key` (chybí cryptography)."""
    if json_mode:
        _print_json({"ok": False, "error": str(e)})
    else:
        print(f"Ed25519 nedostupné ({e})", file=sys.stderr)


def cmd_integrity_keys(args: argparse.Namespace) -> int:
    """P0-2 — export veřejného integrity klíče případu (nezávislá verifikace).

    Třetí strana drží pouze tento výstup + kontrolní body a může ověřit,
    že audit trail nebyl upraven od posledního kontrolního bodu. Exit 0 =
    klíč existuje; 2 = nevygenerován (použij `stopa integrity --init-key`).
    """
    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    try:
        pub = db.integrity_public_key()
        if pub is None:
            msg = "Ed25519 klíč nevygenerován (použij `stopa integrity --init-key`)"
            if json_mode:
                _print_json({"ok": False, "error": "no_key"})
            else:
                print(msg, file=sys.stderr)
            return 2
        out = {
            "case_id": args.case_id,
            "public_key_b64": pub,
            "fingerprint_sha256_8b": _ed25519_fingerprint(pub),
            # P0-2: každý kontrolní bod nesne i klíč podpisu (rotace-safe);
            # export obsahuje historii generací pro nezávislou verifikaci.
            "key_generations": [
                {
                    "checkpoint_id": cp["id"],
                    "ts": cp["ts"],
                    "reason": cp["reason"],
                    "public_key_b64": cp["public_key_b64"] or pub,
                    "fingerprint_sha256_8b": _ed25519_fingerprint(
                        cp["public_key_b64"] or pub
                    ),
                }
                for cp in db.list_integrity_checkpoints()
            ],
        }
        if json_mode:
            _print_json(out)
        else:
            print(f"Ed25519 veřejný klíč případu {args.case_id}:")
            print(f"  b64:       {pub}")
            print(f"  otisk:     {_ed25519_fingerprint(pub)} (SHA-256, první 8 B)")
            gens = out["key_generations"]
            if gens:
                print(f"  kontrolních bodů: {len(gens)}")
    finally:
        db.close()
    return 0


def cmd_rotate_key(args: argparse.Namespace) -> int:
    """P0-2 — rotace Ed25519 integrity klíče případu.

    Staré kontrolní body zůstávají ověřitelné (drží vlastní public key);
    nová generace je ukotvena rotačním bodem podepsaným NOVÝM klíčem.
    Exit 0 = rotace provedena; 2 = chybí cryptography / klíč nevygenerován.
    """
    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    try:
        if db.integrity_public_key() is None:
            # first-time init — zachováme staré chování `integrity --init-key`
            try:
                priv_raw, pub = db.ensure_integrity_key()  # RuntimeError bez crypto
            except RuntimeError as e:
                _rotate_err(e, json_mode)
                return 2
            del priv_raw
            out = {
                "rotated": False,
                "initialized": True,
                "public_key_b64": pub,
                "fingerprint_sha256_8b": _ed25519_fingerprint(pub),
            }
        else:
            try:
                out = db.audit_repo.rotate_integrity_key(reason=args.reason)
                if out is None:  # prakticky nedosažitelné (klíč existuje)
                    raise RuntimeError("rotace se nepodařila")
                out["fingerprint_sha256_8b"] = _ed25519_fingerprint(
                    out["public_key_b64"]
                )
            except RuntimeError as e:  # chybí volitelný balík cryptography
                _rotate_err(e, json_mode)
                return 2
        if json_mode:
            _print_json({"ok": True, **out})
        else:
            verb = "inicializován" if out.get("initialized") else "rotace provedena"
            print(f"P0-2 Ed25519 klíč {verb}:")
            old = out.get("old_public_key")
            if old:
                print(f"  starý otisk: {_ed25519_fingerprint(old)}")
            print(
                f"  nový otisk:  {out['fingerprint_sha256_8b']} "
                f"(SHA-256, první 8 B)"
            )
            cp_id = out.get("checkpoint_id")
            if cp_id is not None:
                print(f"  rotační kontrolní bod: #{cp_id} ({out.get('reason') or 'key_rotation'})")
    finally:
        db.close()
    return 0


def cmd_provenance(args: argparse.Namespace) -> int:
    """P0-1 — řetězec provenience artefaktu (kroky + mezery; JSON report).

    Exit 0 = kompletní řetězec; 2 = neúplný (existují gaps); 1 = chyba /
    neznámý artefakt. Zpráva zahrnuje kroky chronologicky, tvrdé mezery
    (gaps) a měkká upozornění (warnings, např. legacy hash bez timestampu).
    """
    json_mode = getattr(args, "json", False) or getattr(args, "format", None) == "json"
    db = _open_db(args.case_id)
    try:
        from stopa.data.provenance_repository import ProvenanceRepository

        ctx = ProvenanceRepository(db.conn).get_artifact_context(args.artifact_id)
    finally:
        db.close()
    if ctx is None:
        if json_mode:
            print(json.dumps({"artifact_id": args.artifact_id, "error": "not_found"}, ensure_ascii=False))
        else:
            print(f"Artefakt '{args.artifact_id}' v případu neexistuje")
        return 1

    from stopa.domain.provenance_chain import build_provenance, provenance_report

    report = provenance_report(build_provenance(**ctx))
    if json_mode:
        print(json.dumps(report, ensure_ascii=False, default=str))
        return 0 if report["complete"] else 2
    state = "COMPLETE" if report["complete"] else "INCOMPLETE"
    print(f"Provenance chain {report['artifact_id']} [{state}]")
    for s in report["steps"]:
        ts = s.get("timestamp") or "?"
        extra = f" cfg={s['config_hash'][:12]}…" if s.get("config_hash") else ""
        print(f"  {ts}  {s['kind']:<14} — {s['description']}{extra}")
    for g in report["gaps"]:
        print(f"  gap: {g}")
    for w in report["warnings"]:
        print(f"  warning: {w}")
    return 0 if report["complete"] else 2


def cmd_graph(args: argparse.Namespace) -> int:
    """P1-3 — unifikovaný Evidence Graph (důkaz↔entita↔událost↔zjištění).

    Graf spojuje korelace entit, hypotézy s důkazy pro/proti, timeline události
    (subjekty + rozporné skupiny) a findings; každá hrana nese důvod vzniku a
    polaritu (podpůrná/protichůdná). Ruční/AI hrany z ``graph_edges`` mají
    přednost před odvozenými se stejným klíčem.

    Exit: 0 = graf sestaven; 1 = neznámý případ / chyba.
    """
    json_mode = getattr(args, "json", False) or getattr(args, "format", None) == "json"
    db = _open_db(args.case_id)
    try:
        from stopa.data.graph_repository import GraphRepository

        repo = GraphRepository(db.conn)
        correlations = db.entity_repo.list_correlations(args.case_id)
        hypotheses = db.hypothesis_repo.list_by_case(args.case_id)
        events = db.list_timeline_events()
        manual_rows = repo.list_edges(args.case_id)
        # C1 findings (pydantic) → plain dicty pro čistou doménu.
        findings = [
            {
                "id": f.id,
                "kind": f.kind,
                "details_json": dict(f.details_json or {}),
                "provenance_json": [p.model_dump(mode="json") for p in (f.provenance or [])],
            }
            for f in db.list_findings(args.case_id)
        ]
        # Provenance odkazuje kanonicky na FileRecord.id → teprve přes mapu na artefakt
        file_to_artifacts = {a.file_id: a.id for a in db.list_artifacts() if a.file_id}
    finally:
        db.close()

    from stopa.domain.evidence_graph import EvidenceGraph, build_evidence_graph

    # explicitní ruční/AI hrany mají přednost (derived s tímto klíčem se přeskočí)
    manual = EvidenceGraph()
    for row in manual_rows:
        manual.add_edge(
            src_type=row["src_type"], src_id=row["src_id"],
            dst_type=row["dst_type"], dst_id=row["dst_id"],
            relation=row["relation"], polarity=row.get("polarity") or "neutral",
            confidence=float(row.get("confidence") or 0.5), reason=row["reason"],
            origin="manual",
        )
    graph = build_evidence_graph(
        base=manual, correlations=correlations, hypotheses=hypotheses,
        findings=findings, events=events, file_to_artifacts=file_to_artifacts,
    )

    if json_mode:
        print(json.dumps(graph.to_dict(), ensure_ascii=False, default=str))
        return 0

    s = graph.summary()
    n = s["nodes"]
    e = s["edges"]
    print(f"Evidence graph {args.case_id}")
    print(
        f"  nodes: artifact={n['artifact']} entity={n['entity']} event={n['event']}"
        f" finding={n['finding']} hypothesis={n['hypothesis']}"
    )
    bp = e["by_polarity"]
    print(f"  edges: total={e['total']} supports={bp.get('supports', 0)}"
          f" contradicts={bp.get('contradicts', 0)} neutral={bp.get('neutral', 0)}")
    for rel in sorted(e["by_relation"]):
        print(f"    {rel}: {e['by_relation'][rel]}")
    return 0


