"""STOPA STP-071 — Normalizační vrstva diferenciálního testování parserů (oblast P ★).

První celek release 2.8 dle designu ``docs/DIFFERENTIAL_TESTING.md`` §3:
čistá doménová funkce bez IO, která převádí surové záznamy na jediný
canonical record tvar pro komparační engine (§4).

Pokrytí (plně offline + deterministické):
- ``normalize_ts`` — epoch konverze (unix / CFAbsoluteTime / Windows FILETIME),
  floor sémantika, typová vs. semantická chyba (bool jako past isinstance).
- ``normalize_field_value`` — NFKC text, None ≠ "", plošné fieldy, nekonečné float.
- ``CanonicalRecord``/``canonicalize`` — neměnnost, nezávislost na vstupním mappingu.
- ``make_join_key`` — deklarované join klíče, token TS_KEY, chybějící pole → ValueError.
- ``sort_records``/``normalize_dataset`` — deterministické řazení (typ → ts → stabilní
  klíč), pořadí surového výstupu se nepočítá jako rozdíl, validace join klíčů dle typu.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from stopa.domain.differential import (
    TS_KEY,
    CanonicalRecord,
    canonicalize,
    make_join_key,
    normalize_dataset,
    normalize_field_value,
    normalize_ts,
    sort_records,
)

# ── normalize_ts: epoch konverze ────────────────────────────────────────


def test_ts_unix_int_passthrough():
    assert normalize_ts(1_700_000_000) == 1_700_000_000


def test_ts_unix_float_floor():
    # podsekundová část se zaokrouhluje dolů (determinismus, design §3.1)
    assert normalize_ts(1_700_000_000.987) == 1_700_000_000


def test_ts_numeric_string():
    assert normalize_ts("1700000005") == 1_700_000_005
    assert normalize_ts("  42 ") == 42


def test_ts_negative_pre_1970_floor():
    # floor (ne truncation) — konzistentní s FILETIME dělením; -0.5 → -1
    assert normalize_ts(-86_400) == -86_400
    assert normalize_ts(-0.5) == -1


def test_ts_bool_is_type_error():
    # isinstance(True, int) je True — bez explicitní kontroly by True prošlo jako 1
    with pytest.raises(TypeError):
        normalize_ts(True)


@pytest.mark.parametrize("bad", [None, [1], {"t": 1}, object()])
def test_ts_wrong_type_raises(bad):
    with pytest.raises(TypeError):
        normalize_ts(bad)


def test_ts_garbage_string_is_value_error():
    # typ (str) sedí, hodnota nedaří → semantická chyba
    with pytest.raises(ValueError):
        normalize_ts("abc")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "-inf"])
def test_ts_non_finite_raises(bad):
    with pytest.raises(ValueError):
        normalize_ts(bad)


def test_ts_unknown_epoch():
    with pytest.raises(ValueError):
        normalize_ts(100, epoch="apple_coredata")


def test_ts_cfabsolute_known_offset():
    # CFAbsoluteTime 0 = 2001-01-01T00:00:00Z; offset ověřen nezávisle přes datetime
    expected = int(datetime(2001, 1, 1, tzinfo=timezone.utc).timestamp())
    assert normalize_ts(0, epoch="cfabsolute") == expected
    # a obecně: cf hodnota + offset = unix
    assert normalize_ts(86_400, epoch="cfabsolute") == expected + 86_400


def test_ts_windows_filetime_epoch_boundary():
    # FILETIME pro Unix epoch 0 = 11 644 473 600 s * 1e7 ticků (100 ns)
    assert normalize_ts(11_644_473_600 * 10**7, epoch="windows_filetime") == 0


def test_ts_windows_filetime_roundtrip():
    unix = 1_700_000_000
    filetime = (unix + 11_644_473_600) * 10**7
    assert normalize_ts(filetime, epoch="windows_filetime") == unix


def test_ts_windows_filetime_sub_tick_floor():
    # sub-tick zbytek zaokrouhlí dolů na celou sekundu
    assert normalize_ts(11_644_473_600 * 10**7 + 5, epoch="windows_filetime") == 0


# ── normalize_field_value: NFKC + None ≠ "" ─────────────────────────────


def test_field_nfkc_ligature():
    assert normalize_field_value("ﬁle ﬁnding") == "file finding"


def test_field_nfkc_fullwidth():
    # plné šířky (fullwidth) znaky → ASCII ekvivalenty
    assert normalize_field_value("ＡＢＣ１２３") == "ABC123"


def test_field_none_vs_empty_distinct():
    # design §3.3: chybějící pole ≠ prázdné pole — explicitní rozlišení
    assert normalize_field_value(None) is None
    assert normalize_field_value("") == ""
    assert normalize_field_value(None) != normalize_field_value("")


@pytest.mark.parametrize("value", [42, 3.14, True, False])
def test_field_numeric_bool_passthrough(value):
    assert normalize_field_value(value) is value


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_field_non_finite_float_raises(bad):
    # porušuje determinismus sérializace reportu
    with pytest.raises(ValueError):
        normalize_field_value(bad)


@pytest.mark.parametrize("bad", [{"a": 1}, [1, 2], (1,), b"raw"])
def test_field_complex_type_raises(bad):
    # canonical fields jsou ploché — strukturované typy patří do detailů parseru
    with pytest.raises(TypeError):
        normalize_field_value(bad)


# ── CanonicalRecord / canonicalize ───────────────────────────────────────


def test_canonicalize_builds_normalized_record():
    record = canonicalize(
        "visit",
        1_700_000_000.9,
        {"url": "ﬁle://x", "count": 3},
    )
    assert isinstance(record, CanonicalRecord)
    assert record.type == "visit"
    assert record.ts_epoch == 1_700_000_000  # floor
    assert record.fields["url"] == "file://x"  # NFKC
    assert record.fields["count"] == 3


def test_canonicalize_none_ts():
    record = canonicalize("note", None, {"body": "bez času"})
    assert record.ts_epoch is None


def test_record_is_immutable_and_independent_of_input():
    raw = {"url": "https://x"}
    record = canonicalize("visit", 100, raw)
    with pytest.raises(FrozenInstanceError):
        record.type = "other"  # type: ignore[misc]
    # fields je neměnné mapping…
    with pytest.raises(TypeError):
        record.fields["url"] = "mutated"  # type: ignore[index]
    # …a nezávislé na vstupním dictu (defenzivní kopie)
    raw["url"] = "https://mutated"
    assert record.fields["url"] == "https://x"


@pytest.mark.parametrize("bad_type", [5, None, b"visit"])
def test_canonicalize_bad_artifact_type(bad_type):
    with pytest.raises(TypeError):
        canonicalize(bad_type, 100, {})  # type: ignore[arg-type]


def test_canonicalize_empty_artifact_type():
    with pytest.raises(ValueError):
        canonicalize("", 100, {})


def test_canonicalize_non_str_field_key():
    with pytest.raises(TypeError):
        canonicalize("visit", 100, {5: "x"})  # type: ignore[arg-type]


# ── make_join_key: deklarované klíče (design §3.4) ──────────────────────


def _record(type_: str, ts: int | None = 1_700_000_000, **fields: object) -> CanonicalRecord:
    return canonicalize(type_, ts, fields)


def test_join_key_deterministic():
    record = _record("visit", url="https://x|y\x1fz", extra="q")
    key = make_join_key(record, ("url", "extra"))
    assert key == make_join_key(record, ("url", "extra"))  # deterministické napříč voláními
    # repr + \x1f oddělovač: hodnoty obsahující běžné oddělovače neničí strukturu klíče
    assert key == repr("https://x|y\x1fz") + "\x1f" + repr("q")


def test_join_key_multi_field_spec_order():
    record = _record("email", from_="a@b", subject="Re: x")  # type: ignore[arg-type]
    k12 = make_join_key(record, ("from_", "subject"))
    k21 = make_join_key(record, ("subject", "from_"))
    assert k12 != k21  # pořadí spec určuje pořadí částí klíče
    assert k12 == repr("a@b") + "\x1f" + repr("Re: x")


def test_join_key_ts_token():
    record = _record("email", ts=1_700_000_042, from_="a@b", subject="s")  # type: ignore[arg-type]
    key = make_join_key(record, (TS_KEY, "subject"))
    assert key == repr(1_700_000_042) + "\x1f" + repr("s")


def test_join_key_missing_field_raises():
    record = _record("visit", extra="y")  # bez 'url'
    with pytest.raises(ValueError, match="'url'"):
        make_join_key(record, ("url",))


def test_join_key_none_value_raises():
    record = _record("email", from_="a@b", subject=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="'subject'"):
        make_join_key(record, (TS_KEY, "from_", "subject"))


def test_join_key_empty_ts_raises():
    record = _record("email", ts=None, from_="a@b", subject="s")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="'ts'"):
        make_join_key(record, (TS_KEY,))


def test_join_key_empty_spec_raises():
    with pytest.raises(ValueError):
        make_join_key(_record("visit"), ())


# ── sort_records / normalize_dataset: deterministické řazení (§3.2) ─────


def _mixed_unsorted() -> list[CanonicalRecord]:
    """Surové pořadí záznamů — cíleně NEseřazené."""
    return [
        _record("email", ts=1_700_000_100, from_="z@b", subject="late"),
        _record("visit", ts=None, url="https://no-ts"),
        _record("visit", ts=1_699_999_500, url="https://early"),
        _record("email", ts=1_700_000_050, from_="a@b", subject="first"),
        _record("visit", ts=1_700_000_000, url="https://mid"),
    ]


def test_sort_records_type_ts_stable_key():
    expected_order = [
        ("email", 1_700_000_050),
        ("email", 1_700_000_100),
        ("visit", 1_699_999_500),
        ("visit", 1_700_000_000),
        ("visit", None),  # záznam bez času za těmi s časem uvnitř typu
    ]
    got = [(r.type, r.ts_epoch) for r in sort_records(_mixed_unsorted())]
    assert got == expected_order


def test_sort_records_input_order_irrelevant():
    # pořadí v surovém výstupu se nepočítá jako rozdíl (design §3.2)
    base = _mixed_unsorted()
    permuted = [base[3], base[1], base[4], base[0], base[2]]  # explicitní permutace všech 5
    assert sort_records(base) == sort_records(permuted)


def test_sort_records_stable_key_breaks_ties():
    # stejný typ+ts → rozhoduje stabilní klíč (repr polí), ne vstupní pořadí
    a = _record("note", ts=100, body="aaa")
    b = _record("note", ts=100, body="bbb")
    assert sort_records([b, a]) == [a, b]


def test_sort_records_returns_copy():
    # sorted() vrací novou listu — vstupní pořadí se nemění
    base = _mixed_unsorted()
    before = [r for r in base]
    out = sort_records(base)
    assert out is not base
    out.reverse()
    assert base == before


# ── normalize_dataset: batch API pro engine (§3.1–3.2) ───────────────────


def test_normalize_dataset_end_to_end():
    entries = [
        {
            "type": "visit",
            "ts": 0,  # CFAbsoluteTime 0 → 2001-01-01 UTC
            "epoch": "cfabsolute",
            "fields": {"url": "ﬁle://a"},
        },
        {
            "type": "visit",
            "ts": (1_700_000_000 + 11_644_473_600) * 10**7,
            "epoch": "windows_filetime",
            "fields": {"url": "https://b"},
        },
    ]
    records = normalize_dataset(entries, join_keys={"visit": ("url",)})
    # seřazené po ts (2001 < 2023) + NFKC normalizace pole
    assert [r.ts_epoch for r in records] == [9_783_072_00, 1_700_000_000]
    assert [r.fields["url"] for r in records] == ["file://a", "https://b"]


def test_normalize_dataset_join_key_validation():
    entries = [
        {"type": "email", "ts": 100, "fields": {"from_": "a@b", "subject": None}},
    ]
    # from+subject+ts je deklarovaný join key (design §3.4) — subject=None → selže explicitně
    with pytest.raises(ValueError, match="'subject'"):
        normalize_dataset(entries, join_keys={"email": ("from_", "subject", TS_KEY)})


def test_normalize_dataset_no_spec_no_validation():
    # typ bez deklarovaného join keye se normalizuje (engine to pak posoudí)
    records = normalize_dataset([{"type": "note", "fields": {}}])
    assert len(records) == 1 and records[0].ts_epoch is None


def test_normalize_dataset_missing_fields_key():
    with pytest.raises(ValueError, match="'fields'"):
        normalize_dataset([{"type": "visit"}])


def test_normalize_dataset_non_mapping_entry():
    with pytest.raises(TypeError):
        normalize_dataset(["not-a-mapping"])  # type: ignore[list-item]


@pytest.mark.parametrize("bad_type", [5, None, b"v"])
def test_normalize_dataset_bad_type_field(bad_type):
    with pytest.raises(TypeError):
        normalize_dataset([{"type": bad_type, "fields": {}}])


def test_normalize_dataset_empty_type():
    with pytest.raises(ValueError):
        normalize_dataset([{"type": "", "fields": {}}])


def test_normalize_dataset_preserves_none_and_empty_fields():
    # None ≠ "" i přes batch cestu (design §3.3)
    records = normalize_dataset(
        [{"type": "note", "ts": 1, "fields": {"a": None, "b": ""}}]
    )
    assert records[0].fields["a"] is None
    assert records[0].fields["b"] == ""


def test_normalize_dataset_deterministic_across_input_orders():
    entries = [
        {"type": "x", "ts": 3, "fields": {"k": "c"}},
        {"type": "x", "ts": 1, "fields": {"k": "a"}},
        {"type": "y", "ts": 2, "fields": {}},
    ]
    order1 = normalize_dataset(entries)
    order2 = normalize_dataset(list(reversed(entries)))
    assert [(r.type, r.ts_epoch) for r in order1] == [(r.type, r.ts_epoch) for r in order2]
    assert order1 == order2


def test_sort_key_helper_is_total():
    # deterministický totální řád: stejné záznamy → stejný sort key
    a = _record("t", ts=5, v="x")
    b = _record("t", ts=5, v="x")
    from stopa.domain.differential import _sort_key

    assert _sort_key(a) == _sort_key(b)


def test_ts_filetime_int_exact_second_boundaries():
    # int cesta = přesná celočíselná aritmetika — žádné float64 zaokrouhlení
    # pod celosekundovou hranici (off-by-one) u typických FILETIME hodnot ~1.3e17
    for sec in (0, 1_700_000_000, 4_294_967_295):
        ticks = (sec + 11_644_473_600) * 10**7
        assert normalize_ts(ticks, epoch="windows_filetime") == sec


def test_ts_filetime_digit_string_exact():
    # celočíselný string = také přesná cesta — float64 by u hodnot nad 2^53
    # (FILETIME ~1.3e17) ztratil přesnost a mohl vrátit s-1
    ticks = (1_700_000_000 + 11_644_473_600) * 10**7
    assert normalize_ts(str(ticks), epoch="windows_filetime") == 1_700_000_000
    assert normalize_ts(f" {ticks} ", epoch="windows_filetime") == 1_700_000_000


def test_ts_filetime_decimal_string_float_path():
    # desetinný string zůstává na float cestě (podsekundová přesnost, floor)
    ticks = (1_700_000_000 + 11_644_473_600) * 10**7
    assert normalize_ts(f"{ticks}.9", epoch="windows_filetime") == 1_700_000_000
