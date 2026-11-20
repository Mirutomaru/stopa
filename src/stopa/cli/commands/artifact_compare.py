"""CLI — P3-2 Artifact Version Comparison (compare-artifacts).

Srovnání dvou verzí téhož logického artefaktu napříč reparse/zachytími:
path-based JSON diff + metadata diff + provenance parser_version obou verzí.
Doména = ``domain/artifact_compare.py``, data = ``data/artifact_compare_repository.py``;
zde jen CLI hrana (exit kódy, text/JSON výstup).
"""

from __future__ import annotations

import argparse
import json
import sys

from .._util import _open_db, _print_json


def _fmt(value) -> str:
    """Deterministické zobrazení JSON hodnoty (truncováno pro čitelnost)."""
    if value is None:
        return "(žádná hodnota)"
    s = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return s if len(s) <= 60 else s[:57] + "…"


def _render_text(result_id_a: str, result_id_b: str, cmp) -> str:
    """Textový výstup — AK3: obě parser_versions vždy viditelné u hlavičky."""
    lines = [
        f"POROVNÁNÍ VERZÍ ARTEFAKTU   klíč: {cmp.key[0]} :: {cmp.key[1] or '(bez cesty)'}",
        (f"  A: {result_id_a} (parser {cmp.parser_versions[0] or '—'})"),
        (f"  B: {result_id_b} (parser {cmp.parser_versions[1] or '—'})"),
    ]
    if cmp.identical:
        lines.append("SHODNÉ — detaily i verze extraktoru bez rozdílů")
        return "\n".join(lines) + "\n"
    lines.append(f"\nJSON DIFF — {len(cmp.json_diffs)} změny:")
    for e in cmp.json_diffs:
        if e.kind == "changed":
            detail = f"{_fmt(e.old)} → {_fmt(e.new)}"
        elif e.kind == "added":
            detail = f"přidáno: {_fmt(e.new)}"
        else:  # removed
            detail = f"odebráno: {_fmt(e.old)}"
        lines.append(f"  {e.path}: {detail}   [{e.kind}]")
    if cmp.metadata_diffs:
        lines.append(f"\nMETADATA DIFF — {len(cmp.metadata_diffs)} změny:")
        for name, old, new in cmp.metadata_diffs:
            lines.append(f"  {name}: {_fmt(old)} → {_fmt(new)}")
    return "\n".join(lines) + "\n"


def cmd_compare_artifacts(args: argparse.Namespace) -> int:
    """P3-2 — srovnání dvou verzí artefaktu (path JSON diff + provenance).

    Exit: 0 = shodné; 1 = nalezeny rozdíly; 2 = chyba (chybějící artefakt,
    jiný artifact_key, neplatné details_json — semantické chyby domény).
    """
    json_mode = getattr(args, "json", False) or getattr(args, "format", None) == "json"
    from stopa.data.artifact_compare_repository import ArtifactCompareRepository
    from stopa.domain.artifact_compare import compare_artifacts, comparison_to_dict

    db = _open_db(args.case_id)
    try:
        repo = ArtifactCompareRepository(db.conn)
        try:
            rec_a = repo.get_record(args.id_a)
            rec_b = repo.get_record(args.id_b)
            missing = [i for i, r in ((args.id_a, rec_a), (args.id_b, rec_b)) if r is None]
            if missing:
                msg = f"artefakt neexistuje: {', '.join(missing)}"
                print(msg, file=sys.stderr) if not json_mode else _print_json(
                    {"ok": False, "error": msg}
                )
                return 2
            result = compare_artifacts(rec_a, rec_b)  # type: ignore[arg-type]
        except (ValueError, TypeError) as exc:
            print(str(exc), file=sys.stderr) if not json_mode else _print_json(
                {"ok": False, "error": str(exc)}
            )
            return 2
    finally:
        db.close()

    if json_mode:
        payload = comparison_to_dict(result)
        payload["ids"] = {"a": args.id_a, "b": args.id_b}
        _print_json(payload)
    else:
        print(_render_text(args.id_a, args.id_b, result), end="")
    return 0 if result.identical else 1
