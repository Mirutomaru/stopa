"""P4-8 — i18n CLI (+ legacy UI katalog) testy.

Pokrytí:
- JSON katalogy (cs/en): parsing, parity klíčů, žádné české diakritiky v EN
- helper ``t()``: aktivní jazyk, fallback en→cs, chybějící klíč → sám klíč, params
- priorita výběru jazyka: flag --lang > env STOPA_LANG > default cs
- CS CLI povrch byte-kompatibilní (golden p48_cli_help_cs.json)
- EN akceptační kritéria: top-level help + 100 % epilogů v angličtině
- Web routa /api/i18n/{lang} (200 pro cs/en, jinak 404)

Offline a deterministicky — bez sítě, fixní korpus.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stopa import i18n
from stopa.i18n import resolve_lang, set_lang, t

GOLDEN = Path(__file__).parent / "golden" / "p48_cli_help_cs.json"

# striktní sada českých diakritik (bez prostého z/Z — žádné false positive)
CZ_CHARS = set("áčďéěíňóřšťúůýž") | set("ÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ")


@pytest.fixture(autouse=True)
def _restore_lang():
    """Po každém testu vrátit aktivní jazyk (globální stav modulu)."""
    saved = i18n.get_lang()
    yield
    set_lang(saved)


def _walk_help(parser: argparse.ArgumentParser, path: str) -> dict[str, str]:
    """Rekurzivně sbírá help texty všech parserů (stejná konvence jako baseline)."""
    res: dict[str, str] = {}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            parser.print_help()
        except SystemExit:
            pass
    res[path] = buf.getvalue()
    for grp in [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]:
        for name, sub in sorted(grp.choices.items()):
            res.update(_walk_help(sub, f"{path} {name}".strip()))
    return res


def _all_help(lang: str) -> dict[str, str]:
    """Celý --help povrch v daném jazyce (klíče bez <root> prefixu)."""
    set_lang(lang)
    from stopa.cli import build_parser

    data = _walk_help(build_parser(), "<root>")
    return {k.removeprefix("<root> "): v for k, v in data.items()}


class TestCatalogs:
    def test_catalogs_parse_and_have_keys(self):
        cs = i18n.load_catalog("cs")
        en = i18n.load_catalog("en")
        assert len(cs) >= 300 and len(en) >= 300

    def test_key_parity_cs_en(self):
        cs, en = i18n.load_catalog("cs"), i18n.load_catalog("en")
        assert set(cs) == set(en), "parity klíčů mezi katalogy"
        for lang, cat in (("cs", cs), ("en", en)):
            assert all(isinstance(v, str) and v.strip() for v in cat.values()), f"{lang}: prázdná hodnota"

    def test_en_has_no_czech_diacritics(self):
        en = i18n.load_catalog("en")
        bad = {k: sorted({c for c in v if c in CZ_CHARS}) for k, v in en.items() if any(c in CZ_CHARS for c in v)}
        assert not bad, f"české diakritiky v EN katalogu: {bad}"


class TestTHelper:
    def test_default_lang_is_cs(self):
        assert i18n.get_lang() == "cs"

    def test_t_uses_active_language(self):
        cs_val = t("cli.top.description")
        set_lang("en")
        en_val = t("cli.top.description")
        assert cs_val != en_val, "CS a EN překlad se musí lišit"
        assert en_val == i18n.load_catalog("en")["cli.top.description"]

    def test_fallback_to_cs_for_missing_key(self):
        set_lang("en")
        en_cache = i18n.load_catalog("en")  # zahřej cache (t() čte přes ni)
        saved = en_cache.pop("cli.opt.json.help", None)
        try:
            assert t("cli.opt.json.help") == i18n.load_catalog("cs")["cli.opt.json.help"]
        finally:
            if saved is not None:
                en_cache["cli.opt.json.help"] = saved

    def test_missing_key_returns_key(self):
        assert t("cli.neexistujici.klic") == "cli.neexistujici.klic"

    def test_params_formatting(self):
        out = t("cli.h.330", defaults="a.b, c.d")
        assert "{defaults}" not in out and "a.b, c.d" in out

    def test_set_lang_invalid_raises(self):
        with pytest.raises(ValueError):
            set_lang("de")


class TestResolveLang:
    def test_default_cs(self, monkeypatch):
        monkeypatch.delenv(i18n.ENV_VAR, raising=False)
        assert resolve_lang(["case", "new"]) == ("cs", ["case", "new"])

    def test_env_var_respected(self, monkeypatch):
        monkeypatch.setenv(i18n.ENV_VAR, "en")
        assert resolve_lang(["serve"]) == ("en", ["serve"])

    def test_flag_beats_env(self, monkeypatch):
        monkeypatch.setenv(i18n.ENV_VAR, "cs")
        assert resolve_lang(["--lang", "en", "case"]) == ("en", ["case"])

    def test_flag_equal_form(self, monkeypatch):
        monkeypatch.delenv(i18n.ENV_VAR, raising=False)
        assert resolve_lang(["--lang=en", "--version"]) == ("en", ["--version"])

    def test_invalid_value_raises(self, monkeypatch):
        monkeypatch.delenv(i18n.ENV_VAR, raising=False)
        with pytest.raises(ValueError):
            resolve_lang(["--lang", "de"])

    def test_scan_stops_at_first_positional(self, monkeypatch):
        # --lang ZA subpříkazem patří subparseru (např. stopa report --lang), ne top-level
        monkeypatch.delenv(i18n.ENV_VAR, raising=False)
        assert resolve_lang(["serve", "--lang", "en"]) == ("cs", ["serve", "--lang", "en"])

    def test_invalid_env_raises(self, monkeypatch):
        monkeypatch.setenv(i18n.ENV_VAR, "DE")
        with pytest.raises(ValueError):
            resolve_lang(["case"])


class TestCliSurface:
    def test_cs_surface_byte_compatible(self):
        """Default cs musí být byte-identický se stavem před P4-8 (golden)."""
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        data = _all_help("cs")
        assert set(data) == set(golden), "počet/cesty CLI povrchu se změnily"
        diff = [k for k in sorted(golden) if data.get(k) != golden[k]]
        assert not diff, f"CS help se liší od goldenu: {diff[:5]}"

    def test_en_acceptance_criteria(self):
        """AK: top-level help + 100 % epilogů v angličtině."""
        data = _all_help("en")
        root = data["<root>"]
        assert root.splitlines()[0] == "usage: stopa [-h] [--version]"
        assert i18n.load_catalog("en")["cli.top.description"] in root, "EN description v top-level help"
        # všechny epilogy (cesty s příkladem) EN — bez jediného 'Příklad'
        with_example = [k for k, v in data.items() if "Example:" in v]
        assert len(with_example) >= 79, f"příliš málo epilogů: {len(with_example)}"
        for key, text in data.items():
            assert "Příklad" not in text, f"'Příklad' zůstává v EN povrchu: [{key}]"
        # žádné české diakritiky nikde na EN povrchu (usage + help + epilog)
        bad = [k for k, v in data.items() if any(c in CZ_CHARS for c in v)]
        assert not bad, f"české znaky na EN CLI povrchu: {bad[:5]}"

    def test_main_lang_flag_invalid(self, capsys):
        from stopa.cli import main

        rc = main(["--lang", "de"])  # neplatná hodnota → stderr + exit code 2
        err = capsys.readouterr().err
        assert rc == 2 and "neznámá hodnota" in err

    def test_main_lang_flag_valid_version(self, capsys):
        from stopa.cli import main

        with pytest.raises(SystemExit) as exc:  # argparse --version končí exit(0)
            main(["--lang", "en", "--version"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert out.startswith("stopa ")


class TestWebRoute:
    @pytest.fixture()
    def client(self, tmp_path):
        from stopa.web.app import create_app

        return TestClient(create_app(db_dir=tmp_path))

    def test_cs_catalog_200(self, client):
        r = client.get("/api/i18n/cs")
        assert r.status_code == 200
        body = r.json()
        assert body["lang"] == "cs"
        assert body["messages"]["cli.top.description"] == i18n.load_catalog("cs")["cli.top.description"]

    def test_en_catalog_200(self, client):
        r = client.get("/api/i18n/en")
        assert r.status_code == 200
        assert r.json()["messages"]["cli.mv.file"] == "FILE"

    def test_unknown_lang_404(self, client):
        r = client.get("/api/i18n/de")
        assert r.status_code == 404
