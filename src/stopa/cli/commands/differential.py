"""STP-072 — ``stopa differential`` (diferenciální testování parserů, design §6).

Komparuje normalizované záznamy parseru STOPA s nezávislým referenčním
nástrojem a vydá deterministický report (design ``docs/DIFFERENTIAL_TESTING.md``
§4) + exit kód (§6):

- **0** — shoda: žádné rozdíly vůbec,
- **3** — existují jen rozdíl(y) adjudikované jako SEMANTIC_DIFF,
- **1** — jakýkoli neadjudikovaný (nebo STOPA_WRONG/REF_WRONG/AMBIGUOUS) rozdíl,
- **2** — vstupní chyba (soubor, JSON, deklarace join keyů).

Vlna 28 pracuje se záznamovými soubory obou stran (JSON listy ``{type, ts?,
epoch?, fields}``); spouštění parseru/reference přímo v CLI = pilotní vlny
release 2.8 (§7). Adjudikace (§5) se načítají z JSON mapy ID rozdílu →
``status`` / ``{"status", "reason"}``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from stopa.domain.differential import (
    DifferentialReport,
    JoinKeySpec,
    adjudicate,
    build_report,
    exit_code_for,
    normalize_dataset,
)


def _load_entries(path: str) -> list[dict]:
    """JSON soubor → list surových záznamů ({type, ts?, epoch?, fields})."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"{path}: {exc.strerror or exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: neplatný JSON ({exc})") from exc
    if not isinstance(data, list):
        raise TypeError(f"{path}: očekáváno JSON list záznamů, dostalo {type(data).__name__}")
    return data


def _parse_join_key_arg(value: str) -> tuple[str, JoinKeySpec]:
    """``--join-key TYPE=POLE[,POLE…]`` → (typ, spec); token ``ts`` = timestamp."""
    type_name, sep, fields_part = value.partition("=")
    if not sep or not type_name.strip() or not fields_part.strip():
        raise ValueError(
            f"--join-key: očekáváno TYPE=POLE[,POLE…], dostalo {value!r}"
        )
    field_names = tuple(p.strip() for p in fields_part.split(",") if p.strip())
    return type_name.strip(), field_names


def _load_adjudications(path: str) -> dict[str, str | Mapping[str, Any]]:
    """JSON mapa ID rozdílu → status | {status, reason} (§5)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: chyba načtení adjudikací ({exc})") from exc
    if not isinstance(data, dict):
        raise TypeError(
            f"{path}: očekáváno JSON objekt ID rozdílu → status/reason, "
            f"dostalo {type(data).__name__}"
        )
    return data


def _print_text_report(parser: str, reference_tool: str | None, report: DifferentialReport) -> None:
    """Lidsky čitelný souhrn (výchozí ``--format text``)."""
    tool = reference_tool or "(nedeklarováno)"
    print(f"Diferenciální komparace: parser={parser} reference={tool}")
    print(
        f"STOPA záznamy: {report.stopa_records} | reference: {report.ref_records} "
        f"| identické: {report.identical_pct:.1f} %"
    )
    if not report.differences:
        print("Rozdíly: žádné — výstupy se shodují.")
        return
    print(f"Rozdíly ({len(report.differences)}):")
    for diff in report.differences:
        line = f"  [{diff.kind}] {diff.join_key}"
        if diff.field is not None:
            line += f" {diff.field} stopa={diff.stopa_value!r} ref={diff.ref_value!r}"
        if diff.count and diff.count > 1:
            line += f" ×{diff.count}"
        suffix = "" if diff.status == "UNADJUDICATED" else f" {diff.status}"
        if diff.reason:
            suffix += f" ({diff.reason})"
        print(line + suffix)


def cmd_differential(args: argparse.Namespace) -> int:
    """``stopa differential <parser> --input F --ref F [--tool N] …`` (design §6).

    Returns:
        0 shoda / 3 pouze SEMANTIC_DIFF / 1 neadjudikované i ostatní rozdíly /
        2 vstupní chyba.
    """
    try:
        join_keys: dict[str, JoinKeySpec] = {}
        for item in args.join_key or []:
            type_name, spec = _parse_join_key_arg(item)
            if type_name in join_keys:
                raise ValueError(f"--join-key: typ {type_name!r} deklarován dvakrát")
            join_keys[type_name] = spec

        stopa_entries = _load_entries(args.input)
        ref_entries = _load_entries(args.ref)
        input_sha256 = hashlib.sha256(Path(args.input).read_bytes()).hexdigest()

        # normalizace obou stran (§3) — deklarované typy se validují už tady,
        # typy bez deklarace padnou fail-fast v komparaci (design §3.4)
        stopa_records = normalize_dataset(stopa_entries, join_keys=join_keys or None)
        ref_records = normalize_dataset(ref_entries, join_keys=join_keys or None)

        report = build_report(
            parser=args.parser,
            stopa_records=stopa_records,
            ref_records=ref_records,
            join_keys=join_keys,
            input_sha256=input_sha256,
            reference_tool=args.tool,
            run_id=args.run_id,
        )

        if args.adjudications:
            decisions = _load_adjudications(args.adjudications)
            report = replace(report, differences=tuple(adjudicate(report.differences, decisions)))

        if args.format == "json":
            print(report.to_json())
        else:
            _print_text_report(args.parser, args.tool, report)
    except (ValueError, TypeError, OSError) as exc:
        print(f"stopa differential: {exc}", file=sys.stderr)
        return 2

    return exit_code_for(report.differences)
