"""CLI — P2-3 Advanced Timeline Intelligence (``stopa timeline-intel``).

Hrana nad čistým doménovým modulem ``domain/timeline_adv.py``: načte
materializovanou timeline + E4 correlations z case DB, spustí analýzu a
vytiskne výsledek (lidsky čitelně nebo JSON). Žádné IO mimo CaseDB.

Exit kódy: 0 = OK; 1 = chyba / neznámý případ / semantická chyba.
"""
from __future__ import annotations

import argparse

from stopa.domain.timeline_adv import analyze_timeline_adv, entity_confidence_map

from .._util import _open_db, _print_json


def cmd_timeline_intel(args: argparse.Namespace) -> int:
    """P2-3 — pokročilá timeline intelligence (gapy/outliery/korelace/nejistota)."""
    db = _open_db(args.case_id)   # neznámý případ → SystemExit("Případ ... nenalezen")
    try:
        events = db.list_timeline_events()
        conf_map = entity_confidence_map(db.list_correlations(args.case_id))
        result = analyze_timeline_adv(events, entity_confidence=conf_map)
    except (ValueError, TypeError) as exc:
        raise SystemExit(str(exc))   # semantická chyba → exit 1
    finally:
        db.close()

    if args.json:
        _print_json(result.to_dict())
        return 0

    s = result.to_dict()["summary"]
    print(f"P2-3 timeline intelligence — {args.case_id}")
    print(
        f"  událostí: {len(events)} | gaps: {s['gaps']} | outliery: {s['outliers']} "
        f"| korelační skupiny: {s['correlation_groups']} | nejisté události: {s['events_flagged']}"
    )
    for g in result.gaps[:5]:
        print(f"  GAP   {g.start_event_id} → {g.end_event_id}: {g.duration_seconds:.0f}s")
    if len(result.gaps) > 5:
        print(f"         …a dalších {len(result.gaps) - 5}")
    for o in result.outliers[:5]:
        print(
            f"  OUTLIER {o.event_id}: izolován (před {o.prev_gap_seconds:.0f}s, "
            f"za {o.next_gap_seconds:.0f}s)"
        )
    if len(result.outliers) > 5:
        print(f"          …a dalších {len(result.outliers) - 5}")
    for c in result.correlations[:5]:
        print(
            f"  KORELACE {c.subject} [{c.confidence}] zdroje={','.join(c.source_ids)} "
            f"události={len(c.event_ids)}"
        )
    if len(result.correlations) > 5:
        print(f"           …a dalších {len(result.correlations) - 5}")
    top_reasons = sorted(s["by_reason"].items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    for reason, count in top_reasons:
        print(f"  NEJISTOTA {reason}: {count}")
    return 0
