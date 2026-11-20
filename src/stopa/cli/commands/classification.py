"""CLI — P3-3 Automated Classification (classify).

Pravidlová klasifikace souborů případu do kategorií + rizika s důvěrou a
forenzně sledovatelným lidským override. Doména = ``domain/classification.py``,
data = ``data/classification_repository.py``; zde jen CLI hrana (exit kódy,
text/JSON výstup).

Exit: 0 = úspěch (i s needs_review položkami); 2 = chyba (neznámý případ,
neplatná kategorie/důvod override — semantické chyby domény).
"""

from __future__ import annotations

import argparse
import sys

from .._util import _open_db, _print_json


def _render_text(case_id: str, summary: dict, classifications: list[dict]) -> str:
    lines = [
        f"KLASIFIKACE PŘÍPADU {case_id} — {summary['total_files']} souborů",
    ]
    for category in sorted(summary["by_category"]):
        count = summary["by_category"][category]
        flagged = sum(1 for c in classifications if c["category"] == category and c["needs_review"])
        suffix = f"   revize: {flagged}" if flagged else ""
        lines.append(f"  {category:<20} {count:>4}{suffix}")
    review = [c for c in classifications if c["needs_review"]]
    overridden = [c for c in classifications if c["status"] == "overridden"]
    if review:
        lines.append("")
        lines.append(f"ČEKÁ NA REVIZI — {len(review)} souborů (důvěra pod prahem):")
        for c in review:  # deterministické pořadí (rel_path) z repozitáře
            lines.append(
                f"  [?] {c['rel_path']} → {c['category']} ({c['confidence']:.2f})"
            )
    if overridden:
        lines.append("")
        lines.append(f"LIDSKÝ OVERRIDE — {len(overridden)} (automatická hodnota dohledatelná):")
        for c in overridden:
            lines.append(
                f"  [!] {c['rel_path']}: auto {c['category']} → override "
                f"{c['override_category']} ({c['override_reason']})"
            )
    return "\n".join(lines) + "\n"


def cmd_classify(args: argparse.Namespace) -> int:
    """P3-3 — klasifikace souborů případu (+ volitelný lidský override).

    Exit: 0 = úspěch; 2 = chyba (chybějící řádek/kategorie, neplatné vstupy).
    """
    json_mode = getattr(args, "json", False) or getattr(args, "format", None) == "json"
    from stopa.data.classification_repository import ClassificationRepository

    # getattr — starší testy staví Namespace bez nových atributů (P3-5 konvence)
    override_id = getattr(args, "override", None)
    db = _open_db(args.case_id)
    try:
        repo = ClassificationRepository(db.conn)
        if override_id is not None:
            result = repo.override(
                args.case_id,
                int(override_id),
                getattr(args, "category", None),
                actor=getattr(args, "actor", None),
                reason=getattr(args, "reason", None),
            )
            if result is None:
                msg = f"klasifikace neexistuje v případě: {override_id}"
                print(msg, file=sys.stderr) if not json_mode else _print_json(
                    {"ok": False, "error": msg}
                )
                return 2
            if json_mode:
                _print_json({"ok": True, "classification_id": int(override_id), **result})
            else:
                print(
                    f"OVERRIDE #{override_id}: {result['rel_path']} — "
                    f"auto {result['category']} → override {result['override_category']}"
                    + (f" ({result['override_reason']})" if result["override_reason"] else "")
                )
            return 0
        summary = repo.classify_case(args.case_id)
        rows = repo.list_classifications(args.case_id)
        if json_mode:
            _print_json({"ok": True, "summary": summary, "classifications": rows})
        else:
            print(_render_text(args.case_id, summary, rows), end="")
    except (ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr) if not json_mode else _print_json(
            {"ok": False, "error": str(exc)}
        )
        return 2
    finally:
        db.close()
    return 0
