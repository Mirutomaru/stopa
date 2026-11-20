"""P2-5 Threat Intelligence Workspace — CLI příkazy (intel import/match).

Per-případový IoC feed + deterministické matching × artefakty/entity. Logika žije
v doménové vrstvě (``domain/threat_intel``) a repozitáři (``data/intel_repository``);
tady je jen CLI hrana.

Exit kódy: 0 = OK; 1 = chyba / neznámý případ / semantická chyba / prázdný feed.
"""

from __future__ import annotations

import argparse
import json

from stopa.cli._util import _open_db


def _json_mode(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "json", False)) or getattr(args, "format", None) == "json"


def _parse_ioc_spec(spec: str) -> tuple[str, str]:
    """Rozparsuje ``kind:value``; semantické chyby → ValueError."""
    kind, sep, value = spec.partition(":")
    if not sep or not kind.strip() or not value.strip():
        raise ValueError("IoC musí být ve tvaru druh:hodnota (např. domain:evil.example.com)")
    return kind.strip(), value


def cmd_intel_import(args: argparse.Namespace) -> int:
    """Import IoC do feedu případu (--stix FILE nebo --ioc KIND:VALUE[,…])."""
    from stopa.data.intel_repository import IntelRepository
    from stopa.domain.threat_intel import IoC, import_bundle

    db = _open_db(args.case_id)
    try:
        if args.stix:
            with open(args.stix, encoding="utf-8") as f:
                iocs = import_bundle(f.read())  # ValueError/TypeError → níže
        else:
            specs = [s for s in (args.ioc or "").split(",") if s.strip()]
            if not specs:
                raise ValueError("zadejte --stix FILE nebo aspoň jedno --ioc KIND:HODNOTA")
            iocs = []
            for spec in specs:
                kind, value = _parse_ioc_spec(spec)
                # kanonizace + fail-closed validace proběhnou v konstruktoru IoC
                iocs.append(IoC(kind=kind, value=value, tlp=args.tlp, source=args.source or ""))
        n = IntelRepository(db.conn).import_feed(args.case_id, iocs)
    except (ValueError, TypeError, OSError) as exc:
        raise SystemExit(str(exc))
    finally:
        db.close()
    if _json_mode(args):
        print(json.dumps({"imported": n}, ensure_ascii=False))
    else:
        print(f"Importováno {n} IoC do případu {args.case_id!r}")
    return 0


def cmd_intel_match(args: argparse.Namespace) -> int:
    """Deterministické matching IoC feedu × artefakty/entities (+ P3-5 YARA/Sigma)."""
    from stopa.data.intel_repository import run_intel_match

    db = _open_db(args.case_id)
    try:
        # ValueError (prázdný feed / neplatná YARA DIR nebo Sigma FILE) → níže;
        # getattr: starší volající (testy P2-5) staví Namespace bez novích atributů
        result = run_intel_match(
            db,
            args.case_id,
            yara_dir=getattr(args, "yara", None),
            sigma_file=getattr(args, "sigma", None),
        )
    except ValueError as exc:
        raise SystemExit(str(exc))
    finally:
        db.close()
    if _json_mode(args):
        print(json.dumps(result, ensure_ascii=False))
    else:
        s = result["summary"]
        age = s["by_age"]
        parts = ", ".join(f"{k}={v}" for k, v in sorted(result["by_match_kind"].items())) or "žádné"
        print(
            f"IoC {s['total']} (fresh/stale/old = {age['fresh']}/{age['stale']}/{age['old']}) — "
            f"shody: {result['matches_total']} ({parts})"
        )
    return 0
