"""B7 — konzolidace CLI: skupiny + skryté BC aliasy + legacy integrity.

Pokrývá:
  * dispatch identita: staré top-level jméno (skrytý alias) == nová cestou
    přes skupinu (func + defaults),
  * flagový povrch aliasu == kanonický parser (žádný tichý drift),
  * aliasy jsou skryté v ``--help`` (help=argparse.SUPPRESS),
  * ``rewrite_legacy_integrity``: ``stopa integrity <case_id>`` →
    ``stopa integrity check <case_id>``,
  * ``DeprecationWarning`` z ``main()`` u starých jmen, žádná u nových cest.

Offline a deterministické — bez sítě; DB seed přes CaseDB (STOPA_DB_DIR).
"""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import pytest

from stopa.cli import (
    DEPRECATED_ALIASES,
    build_parser,
    deprecation_warning_for,
    main,
    rewrite_legacy_integrity,
)

# staré jméno → kanonická cesta (skupina, podpříkaz) — jediný zdroj pravdy
_PAIRS: dict[str, tuple[str, str]] = {
    "seal": ("integrity", "seal"),
    "seal-chain": ("integrity", "chain"),
    "integrity-keys": ("integrity", "keys"),
    "rotate-key": ("integrity", "rotate-key"),
    "import-mobile": ("import", "mobile"),
    "plaso-import": ("import", "plaso"),
    "image": ("forensic", "image"),
    "mobile": ("forensic", "mobile"),
    "memory-analyze": ("forensic", "memory"),
    "pcap-analyze": ("forensic", "pcap"),
    "decrypt": ("forensic", "decrypt"),
    "antiforensics-scan": ("forensic", "anti"),
    "onchain": ("crypto", "onchain"),
    "darkweb": ("crypto", "darkweb"),
    "crypto-report": ("crypto", "report"),
    "advanced": ("crypto", "advanced"),
    "compliance": ("court", "swgde"),
    "daubert": ("court", "daubert"),
}


def _top_subparsers(p: argparse.ArgumentParser) -> argparse._SubParsersAction:
    return next(  # type: ignore[return-value]
        a for a in p._actions if type(a).__name__ == "_SubParsersAction"
    )


def _sub_of(group_parser: argparse.ArgumentParser, name: str) -> argparse.ArgumentParser:
    sp = next(a for a in group_parser._actions if type(a).__name__ == "_SubParsersAction")
    return sp.choices[name]  # type: ignore[no-any-return]


class TestAliasDispatch:
    """Staré jméno musí dispatchovat přesně jako nová cestou přes skupinu."""

    def test_alias_registry_matches_deprecated_map(self):
        assert set(_PAIRS) == set(DEPRECATED_ALIASES), "tabulka aliasů v testu vs. kód"

    def test_aliases_dispatch_identical(self):
        parser = build_parser()
        top = _top_subparsers(parser)
        for old, (grp, sub) in sorted(_PAIRS.items()):
            canon = _sub_of(top.choices[grp], sub)
            alias = top.choices[old]
            assert alias._defaults.get("func") is canon._defaults.get("func"), old  # type: ignore[attr-defined]

    def test_alias_defaults_identical(self):
        parser = build_parser()
        top = _top_subparsers(parser)
        for old, (grp, sub) in sorted(_PAIRS.items()):
            canon = _sub_of(top.choices[grp], sub)
            alias = top.choices[old]
            d_c, d_a = canon._defaults, alias._defaults  # type: ignore[attr-defined]
            keys = set(d_c) | set(d_a)
            for k in sorted(keys):
                assert d_c.get(k) is d_a.get(k), (old, k)

    def test_alias_flag_surface_matches_canonical(self):
        parser = build_parser()
        top = _top_subparsers(parser)
        for old, (grp, sub) in sorted(_PAIRS.items()):
            canon = _sub_of(top.choices[grp], sub)
            alias = top.choices[old]

            def opts(p: argparse.ArgumentParser):
                out = []
                for a in p._actions:
                    if type(a).__name__ == "_HelpAction":
                        continue  # -h/--help si argparse přidá ke každému parseru
                    out.append((tuple(getattr(a, "option_strings", ())), getattr(a, "dest", None)))
                return sorted(out)

            assert opts(alias) == opts(canon), old

    def test_alias_help_epilog_matches_canonical(self):
        """R0.4 — sekce „Příklad:" v --help musí přežít přesun pod skupinu."""
        parser = build_parser()
        top = _top_subparsers(parser)
        for old, (grp, sub) in sorted(_PAIRS.items()):
            canon = _sub_of(top.choices[grp], sub)
            alias = top.choices[old]
            assert alias.epilog == canon.epilog, f"{old}: epilog se liší"
            assert alias.formatter_class is canon.formatter_class, old

    def test_aliases_hidden_in_help(self):
        """Skryté aliasy nesmí zneviditelnit --help povrch."""
        parser = build_parser()
        top = _top_subparsers(parser)
        suppressed = {
            ca.dest for ca in getattr(top, "_choices_actions", [])  # type: ignore[attr-defined]
            if getattr(ca, "help", None) is argparse.SUPPRESS
        }
        assert set(_PAIRS) <= suppressed, sorted(set(_PAIRS) - suppressed)

    def test_groups_visible_with_help(self):
        parser = build_parser()
        top = _top_subparsers(parser)
        # v Pythonu 3.11 je help text na pseudo-akcích rodiče, ne na subparseru
        helps = {ca.dest: ca.help for ca in getattr(top, "_choices_actions", [])}  # type: ignore[attr-defined]
        for grp in ("integrity", "import", "forensic", "crypto", "court"):
            h = helps.get(grp)
            assert isinstance(h, str) and h.strip(), f"skupina {grp}: chybí help text"


class TestLegacyIntegrityRewrite:
    """``stopa integrity <case_id>`` (legacy) → ``integrity check <case_id>``."""

    @pytest.mark.parametrize(
        ("argv", "expected", "rewritten"),
        [
            (["integrity", "CASE1"], ["integrity", "check", "CASE1"], True),
            (["integrity", "CASE1", "--json"], ["integrity", "check", "CASE1", "--json"], True),
            (["integrity", "check", "CASE1"], ["integrity", "check", "CASE1"], False),
            (["integrity", "seal", "CASE1"], ["integrity", "seal", "CASE1"], False),
            (["integrity", "-h"], ["integrity", "-h"], False),
            (["integrity"], ["integrity"], False),  # jen jméno skupiny → help
            (["stats", "CASE1"], ["stats", "CASE1"], False),
        ],
    )
    def test_rewrite(self, argv: list[str], expected: list[str], rewritten: bool):
        out, flag = rewrite_legacy_integrity(list(argv))
        assert out == expected
        assert flag is rewritten

    def test_input_not_mutated(self):
        argv = ["integrity", "CASE1"]
        rewrite_legacy_integrity(argv)
        assert argv == ["integrity", "CASE1"], "vstupní lista nesmí být mutována"


class TestDeprecationWarning:
    """main() emituje DeprecationWarning jen u starých jmen."""

    def test_pure_mapping(self):
        for old, (grp, sub) in sorted(_PAIRS.items()):
            msg = deprecation_warning_for(old, legacy_integrity=False)
            assert msg and f"stopa {old}" in msg and f"{grp} {sub}" in msg
        # nové cesty: command = jméno skupiny → žádná varování
        for grp in ("integrity", "import", "forensic", "crypto", "court"):
            assert deprecation_warning_for(grp, legacy_integrity=False) is None
        assert deprecation_warning_for(None, legacy_integrity=False) is None
        # legacy integrity má přednost
        msg = deprecation_warning_for("integrity", legacy_integrity=True)
        assert msg and "check" in msg

    @pytest.fixture()
    def seeded_case(self, tmp_path: Path, monkeypatch):
        from stopa.data.db import CaseDB
        from stopa.models import Case

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        case = Case(name="B7 E2E", examiner="Tester")
        db = CaseDB(str(tmp_path / f"{case.id}.db"))
        try:
            db.add_case(case)
        finally:
            db.close()
        return case.id

    def _run(self, argv: list[str]):  # type: ignore[no-untyped-def]
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                rc = main(argv)  # type: ignore[call-arg]
            except SystemExit as e:  # argparse/help cesty — code může být i str
                rc = e.code
        deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        return rc, deps

    def test_old_name_warns(self, seeded_case: str):
        rc, deps = self._run(["seal", "--json", seeded_case])
        assert len(deps) == 1, "staré jméno musí emitovat přesně jedno varování"
        assert "integrity seal" in str(deps[0].message)
        assert isinstance(rc, (int, type(None), str))

    def test_new_path_no_warning(self, seeded_case: str):
        rc, deps = self._run(["integrity", "seal", "--json", seeded_case])
        assert deps == [], [str(w.message) for w in deps]
        assert isinstance(rc, (int, type(None), str))

    def test_legacy_integrity_warns(self, seeded_case: str):
        _rc, deps = self._run(["integrity", "--json", seeded_case])
        assert len(deps) == 1, "legacy forma integrity musí emitovat varování"
        assert "check" in str(deps[0].message)
