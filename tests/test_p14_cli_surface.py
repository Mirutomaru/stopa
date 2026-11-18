"""P1-4 — charakterizační test povrchu CLI (golden snapshot).

Než se god-file ``cli.py`` rozloží do balíku ``stopa.cli.commands``, zafixujeme
celý argparse povrch: každý subpříkaz, jeho option flags. Snapshot
(tests/golden/p14_cli_surface.json) se generuje ze stavu PŘED refaktorem; po
rozkladu musí být povrch byte-přesně stejný (backward-kompatibilita).

Deterministický, offline — bez spuštění příkazů.
"""
from __future__ import annotations

import json
from pathlib import Path

from stopa.cli import build_parser

GOLDEN = Path(__file__).parent / "golden" / "p14_cli_surface.json"


def _build_inventory() -> dict:
    """Rekurzivní inventář: {cesta_subpříkazu: {"opts": [flags]}}."""
    inv: dict[str, dict] = {}

    def rec(p, prefix):
        opts = sorted(
            s for action in p._actions  # type: ignore[attr-defined]
            for s in getattr(action, "option_strings", [])
        )
        inv[prefix or "<root>"] = {"opts": opts}
        for action in p._actions:  # type: ignore[attr-defined]
            if type(action).__name__ == "_SubParsersAction" and action.choices:
                for sub_name, sub_parser in sorted(action.choices.items()):
                    new_prefix = f"{prefix}/{sub_name}" if prefix else str(sub_name)
                    rec(sub_parser, new_prefix)

    rec(build_parser(), "")
    return inv


def test_cli_surface_matches_golden():
    """Povrch CLI (subpříkazy + flags) se shoduje s golden snapshotem PŘED refaktorem."""
    current = _build_inventory()
    if not GOLDEN.exists():
        # první běh: vygeneruje snapshot (vyžaduje explicitní potvrzení commitem)
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert current == expected, (
        "CLI povrch se liší od golden snapshotu — buď aktualizujte snapshot "
        "(tests/golden/p14_cli_surface.json), nebo došlo k nechtěné změně rozhraní"
    )


def test_all_commands_have_help_example():
    """Každý LISTOVÝ subpříkaz má v epilogu příklad (R0.4 kontrakt).

    Výjimky: grupové uzly (mají vlastní subparser — např. case/plugin/wb) a
    skryté kompatibilitní aliasy (help=argparse.SUPPRESS, např. plugin-run).
    """
    import argparse as _ap

    p = build_parser()

    def rec(parser, name):
        for action in parser._actions:  # type: ignore[attr-defined]
            if type(action).__name__ == "_SubParsersAction" and action.choices:
                # skryté aliasy: pseudo-akce s help==SUPPRESS (dest = název subpříkazu)
                suppressed = {
                    ca.dest for ca in getattr(action, "_choices_actions", [])  # type: ignore[attr-defined]
                    if getattr(ca, "help", None) is _ap.SUPPRESS
                }
                for sub_name, sub_parser in sorted(action.choices.items()):
                    full = f"{name} {sub_name}".strip()
                    has_subparsers = any(
                        type(a).__name__ == "_SubParsersAction" for a in sub_parser._actions  # type: ignore[attr-defined]
                    )
                    if not has_subparsers and sub_name not in suppressed:
                        epilog = getattr(sub_parser, "epilog", "") or ""
                        assert "Příklad:" in epilog, f"{full}: chybí příklad v --help"
                    rec(sub_parser, full)

    rec(p, "")
