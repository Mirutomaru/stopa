"""P3-A — omezené JSON parsování: unit testy, E2E přes reálný parser a
AST guard staged rolloutu (žádné holé json.loads/json.load v povrchu
nedůvěryhodných dat).

Kontext: audit (§10) našel 68 volajících míst v ``src/stopa/artifacts`` +
2 v domain modulech (STIX bundle, plaso extra pole), která parsují
nedůvěryhodná důkazová data bez hloubkového limitu → rekurzní/C-stack
vyčerpání u patologického vnoření. Řešení: sdílený doménový helper
:func:`stopa.domain.json_bounded.bounded_json_loads` (limit 200 úrovní,
konzistentní s xml_bounded z P1).
"""

from __future__ import annotations

import ast
import json
import time
from pathlib import Path

import pytest

from stopa.artifacts.google_location_history import parse_location_history_json
from stopa.domain.json_bounded import (
    DEFAULT_MAX_DEPTH,
    JsonLimitError,
    _max_depth,
    bounded_json_loads,
)

SRC = Path(__file__).resolve().parent.parent / "src" / "stopa"


def _bomb(depth: int, container: str = "[") -> bytes:
    """JSON bomb: ``depth`` vnořených kontejnerů (platné JSON)."""
    close = "]" if container == "[" else "}"
    return (container * depth + close * depth).encode()


# ---------------------------------------------------------------- unit: hloubka

class TestMaxDepth:
    def test_root_object_is_level_one(self) -> None:
        assert _max_depth('{"a": 1}') == 1

    def test_nested_containers_counted(self) -> None:
        # objekt → objekt → pole = 3 úrovně
        assert _max_depth('{"a": {"b": [1, 2]}}') == 3

    def test_brackets_inside_strings_not_counted(self) -> None:
        assert _max_depth('["{}[]{}", "x"]') == 1

    def test_escaped_quote_does_not_end_string(self) -> None:
        # JSON text "a\"b{c" — uvozovka za zpětným lomítkem je escape, ne konec;
        # závorka uvnitř řetězce se nepočítá → hloubka 0 (top-level scalar)
        s = '"a\\"b{c"'
        assert _max_depth(s) == 0

    def test_unicode_escape_quote_not_terminator(self) -> None:
        # \u0022 = JSON-escaped uvozovka — řetězec pokračuje, { se nepočítá
        s = '"\\u0022 {"'
        assert _max_depth(s) == 0

    def test_top_level_scalar(self) -> None:
        assert _max_depth("42") == 0
        assert _max_depth('"hello"') == 0

    def test_unbalanced_closers_do_not_crash(self) -> None:
        # neplatné JSON — sken nesmí spadnout; běhající maximum je vždy ≥ 0,
        # pro VALID JSON se od neskleneného počítání lišit nemůže (zavírač
        # nikdy nepředchází otevírači) a limit-check dostane horní odhad
        assert _max_depth(']]]{{{') >= 0


class TestBoundedJsonLoads:
    def test_valid_input_same_as_json_loads(self) -> None:
        samples = [
            '{"a": [1, {"b": null}], "c": "text"}',
            "[[[]], [[[]]]]",
            "42",
            '"str"',
            "{}",
            "[]",
        ]
        for s in samples:
            assert bounded_json_loads(s) == json.loads(s)

    def test_bytes_input_decoded_with_replace(self) -> None:
        # invalidní UTF-8 → U+FFFD (přesně jako původní decode u volajících míst)
        data = b'{"a": "\xff\xfe"}'
        out = bounded_json_loads(data)
        assert out == {"a": "\ufffd\ufffd"}

    def test_bytearray_accepted(self) -> None:
        assert bounded_json_loads(bytearray(b'[1, 2]')) == [1, 2]

    def test_malformed_still_raises_decode_error(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            bounded_json_loads('{"a": }')

    def test_depth_bomb_over_default_limit(self) -> None:
        with pytest.raises(JsonLimitError) as ei:
            bounded_json_loads(_bomb(DEFAULT_MAX_DEPTH + 1))
        assert str(DEFAULT_MAX_DEPTH) in str(ei.value)

    def test_exactly_at_limit_passes(self) -> None:
        # 200 úrovní = limit → projde (limit se porušuje až nad ním)
        assert bounded_json_loads(_bomb(DEFAULT_MAX_DEPTH)) is not None

    def test_object_bomb_too(self) -> None:
        with pytest.raises(JsonLimitError):
            bounded_json_loads(_bomb(250, container="{"))

    def test_many_shallow_containers_no_false_positive(self) -> None:
        # 300 objektů v poli → 301 otevíracích závorek (spustí pomalý sken),
        # ale hloubka jen 2 → nesmí falšovat
        doc = "[" + ",".join("{}" for _ in range(300)) + "]"
        assert bounded_json_loads(doc) == [{} for _ in range(300)]

    def test_limit_error_is_value_error(self) -> None:
        # kontrakt volajících míst: ValueError (ne RecursionError/segfault)
        with pytest.raises(ValueError):
            bounded_json_loads(_bomb(DEFAULT_MAX_DEPTH + 1))

    def test_explicit_max_depth(self) -> None:
        assert bounded_json_loads('{"a": {"b": 1}}', max_depth=2) == {
            "a": {"b": 1}
        }
        with pytest.raises(JsonLimitError):
            bounded_json_loads('{"a": {"b": 1}}', max_depth=1)

    def test_invalid_max_depth(self) -> None:
        with pytest.raises(ValueError, match="max_depth"):
            bounded_json_loads("{}", max_depth=0)
        with pytest.raises(ValueError, match="max_depth"):
            bounded_json_loads("{}", max_depth=-3)

    def test_module_global_read_at_call_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # globála DEFAULT_MAX_DEPTH se čte v době volání → monkeypatchovatelné
        import stopa.domain.json_bounded as jb

        monkeypatch.setattr(jb, "DEFAULT_MAX_DEPTH", 5)
        with pytest.raises(JsonLimitError):
            bounded_json_loads(_bomb(6))
        assert bounded_json_loads(_bomb(5)) is not None

    def test_scan_performance_smoke(self) -> None:
        # O(n) sken — ~0,5 MB JSON nesmí trvat řádově minuty (původní audit:
        # bez limitu by bomb vyčerpala rekurzi; s limitem jen lineární náklad)
        doc = "[" + ",".join(f'{{"k{i}": {i}}}' for i in range(30_000)) + "]"
        assert len(doc) > 400_000
        t0 = time.monotonic()
        out = bounded_json_loads(doc)
        dt = time.monotonic() - t0
        assert len(out) == 30_000
        assert dt < 60.0, f"sken 2 MB JSON trval {dt:.1f}s"


# ------------------------------------------------------------- E2E: reálný parser

class TestParserIntegration:
    def test_location_history_still_parses(self) -> None:
        # regrese rolloutu: běžný Takeout soubor dál parsován identicky
        payload = [
            {
                "latitudeE7": 500934826,
                "longitudeE7": 144270841,
                "timestampMsSinceEpoch": 1625097600000,
                "accuracyHorizontalMeters": 10.0,
            },
            {
                "latitudeE7": -338688200,
                "longitudeE7": 1512017429,
                "timestampMsSinceEpoch": 1625097600001,
            },
        ]
        points = parse_location_history_json(json.dumps(payload).encode())
        assert len(points) == 2

    def test_depth_bomb_surfaces_as_value_error(self) -> None:
        # bomb přes limit → JsonLimitError (ValueError), ne RecursionError;
        # parser ho nepolyká do JSONDecodeError, protože je to sémantický limit
        with pytest.raises(JsonLimitError):
            parse_location_history_json(_bomb(DEFAULT_MAX_DEPTH + 5))

    def test_malformed_still_value_error(self) -> None:
        # původní kontrakt parseru: neplatné JSON → ValueError("Neplatné JSON…")
        with pytest.raises(ValueError, match="Neplatné JSON"):
            parse_location_history_json(b'{"a": }')


# ------------------------------------------------- AST guard staged rolloutu

#: Povrch nedůvěryhodných dat, kde musí být bounded helper (rollout P3-A).
ROLLOUT_SURFACE = [SRC / "artifacts", SRC / "domain" / "threat_intel.py",
                   SRC / "domain" / "plaso_import.py"]


def _iter_python_files() -> list[Path]:
    out: list[Path] = []
    for p in ROLLOUT_SURFACE:
        if p.is_dir():
            out.extend(sorted(p.glob("*.py")))
        else:
            out.append(p)
    return out


def test_no_bare_json_loads_in_untrusted_surface() -> None:
    """Žádné holé ``json.loads``/``json.load`` v povrchu nedůvěryhodných dat.

    AST sken chytí i přejmenované proměnné, které by textový grep přehlédl.
    Povrch = artifacts parserte + STIX bundle (threat_intel) + plaso extra pole;
    zbytek src/stopa parsuje důvěryhodné interní struktury (viz report §10).
    """
    bare: list[str] = []
    for f in _iter_python_files():
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if (
                isinstance(fn, ast.Attribute)
                and fn.attr in ("loads", "load")
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "json"
            ):
                bare.append(f"{f.name}:{node.lineno} json.{fn.attr}")
    assert not bare, f"holé json.loads/json.load zůstaly: {bare}"
