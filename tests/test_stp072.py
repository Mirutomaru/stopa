"""STP-072 — komparační engine a adjudikace (design ``docs/DIFFERENTIAL_TESTING.md`` §4–6).

Testy čistého doménového vrstvy :mod:`stopa.domain.differential` — plně offline,
deterministické, bez IO. CLI ``stopa differential`` pokrývají testy v
``tests/test_p48_i18n.py`` (sekcce STP-072).

Pokrytí dle designu:
- §4 komparace: spárování podle join keyu, deterministické řazení rozdílu,
  statistika shody (identical_pct), tvar reportu a bitová reprodukovatelnost;
- §5 verdikty: stavy adjudikace + zdůvodnění, default UNADJUDICATED;
- §6 exit kódy: 0 / 3 / 1.
"""
from __future__ import annotations

import json

import pytest

from stopa.domain.differential import (
    ADJUDICATION_STATUSES,
    KIND_EXTRA_IN_STOPA,
    KIND_FIELD_DIFFERS,
    KIND_MISSING_IN_REF,
    STATUS_AMBIGUOUS,
    STATUS_REF_WRONG,
    STATUS_SEMANTIC_DIFF,
    STATUS_STOPA_WRONG,
    TS_KEY,
    Difference,
    adjudicate,
    build_report,
    canonicalize,
    compare_records,
    exit_code_for,
    join_key_display,
)


def _rec(artifact_type: str, ts: int = 1_700_000_000, **fields):
    """Výrobce canonical recordu (epoch unix — default)."""
    return canonicalize(artifact_type, ts, fields)


_JOIN_KEYS = {"visit": ("url",)}


# ════════════════════════════ §4 — compare_records ════════════════════════════

def test_compare_identical_sets_no_differences():
    stopa = [_rec("visit", 1_700_000_000, url="https://a"), _rec("visit", 1_700_000_001, url="https://b")]
    ref = list(stopa)
    result = compare_records(stopa, ref, _JOIN_KEYS)
    assert result.differences == ()
    assert result.identical_pairs == 2
    assert result.union_size == 2
    assert result.identical_pct == 100.0


def test_compare_order_independence_deterministic():
    # design §3.2: pořadí surového výstupu se nepočítá jako rozdíl
    stopa = [_rec("visit", ts, url=f"https://x/{i}") for i, ts in enumerate(range(5))]
    ref_permuted = list(reversed(stopa))
    r1 = compare_records(stopa, ref_permuted, _JOIN_KEYS)
    r2 = compare_records(ref_permuted, stopa, _JOIN_KEYS)  # symetrie stran (žádné jednostranné)
    assert r1.differences == () and r2.differences == ()
    assert r1.identical_pairs == r2.identical_pairs == 5


def test_compare_missing_in_ref_direction():
    # záznam má reference, chybí ve STOPA → missing_in_ref (STOPA podává méně)
    stopa = [_rec("visit", url="https://a")]
    ref = [_rec("visit", url="https://a"), _rec("visit", 1_700_000_005, url="https://jen-ref")]
    result = compare_records(stopa, ref, _JOIN_KEYS)
    assert len(result.differences) == 1
    diff = result.differences[0]
    assert diff.kind == KIND_MISSING_IN_REF
    assert diff.join_key == "visit:https://jen-ref"
    assert diff.count is None  # jedna kopie → do JSON se count nepíše
    assert diff.to_dict() == {
        "kind": "missing_in_ref",
        "join_key": "visit:https://jen-ref",
        "status": "UNADJUDICATED",
    }


def test_compare_extra_in_stopa_direction():
    # záznam má STOPA, nemá ho reference → extra_in_stopa
    stopa = [_rec("visit", url="https://a"), _rec("visit", 1_700_000_006, url="https://jen-stopa")]
    ref = [_rec("visit", url="https://a")]
    result = compare_records(stopa, ref, _JOIN_KEYS)
    assert len(result.differences) == 1
    diff = result.differences[0]
    assert diff.kind == KIND_EXTRA_IN_STOPA
    assert diff.join_key == "visit:https://jen-stopa"


def test_compare_one_sided_duplicates_aggregate_count():
    # kopie se stejným join keyem se agregují do jednoho rozdílu s count (design §4)
    stopa = [_rec("visit", url="https://dup")] * 3 + [_rec("visit", 1_700_000_009, url="https://ok")]
    ref = [_rec("visit", 1_700_000_009, url="https://ok")]  # stejný ts → identický pár
    result = compare_records(stopa, ref, _JOIN_KEYS)
    assert len(result.differences) == 1
    diff = result.differences[0]
    assert diff.kind == KIND_EXTRA_IN_STOPA
    assert diff.count == 3
    # count=1 se do JSON nepíše, count>3 ano (tvar vzoru designu §4)
    assert diff.to_dict()["count"] == 3
    single = Difference(kind=KIND_EXTRA_IN_STOPA, join_key="visit:x")
    assert "count" not in single.to_dict()


def test_compare_field_differs_ts_and_values():
    # odlišný join key = jiný záznam (nespárují se) — jeden extra + jeden missing
    stopa = [_rec("visit", 1_700_000_002, url="https://x")]
    ref = [_rec("visit", 1_700_000_000, url="https://y")]
    result = compare_records(stopa, ref, _JOIN_KEYS)
    assert {d.kind for d in result.differences} == {KIND_EXTRA_IN_STOPA, KIND_MISSING_IN_REF}

    # shoda join keyu, liší se ts_epoch → field_differs s hodnotami obou stran
    stopa = [_rec("visit", 1_700_000_002, url="https://x")]
    ref = [_rec("visit", 1_700_000_000, url="https://x")]
    result = compare_records(stopa, ref, _JOIN_KEYS)
    assert len(result.differences) == 1
    diff = result.differences[0]
    assert diff.kind == KIND_FIELD_DIFFERS
    assert diff.field == "ts_epoch"
    assert diff.stopa_value == 1_700_000_002 and diff.ref_value == 1_700_000_000


def test_compare_field_differs_multiple_fields_sorted():
    # více odlišných polí → rozdíl na každé, seřazené podle jména pole (determinismus)
    stopa = [_rec("visit", url="https://x", alpha="1", beta="2")]
    ref = [_rec("visit", url="https://x", alpha="9", beta="8")]
    result = compare_records(stopa, ref, _JOIN_KEYS)
    assert [d.field for d in result.differences] == ["alpha", "beta"]
    by_field = {d.field: d for d in result.differences}
    assert (by_field["alpha"].stopa_value, by_field["alpha"].ref_value) == ("1", "9")


def test_compare_absent_vs_none_equivalent():
    # value-level equivalence: explicitní None a absentní pole = to samé (§3.3 kanonicky)
    stopa = [_rec("visit", url="https://x")]
    ref = canonicalize("visit", 1_700_000_000, {"url": "https://x", "note": None})
    result = compare_records(stopa, [ref], _JOIN_KEYS)
    assert result.differences == ()

    # ale None ≠ "" (design §3.3: chybějící pole ≠ prázdné pole)
    ref_empty_str = canonicalize("visit", 1_700_000_000, {"url": "https://x", "note": ""})
    result2 = compare_records(stopa, [ref_empty_str], _JOIN_KEYS)
    assert len(result2.differences) == 1
    assert result2.differences[0].field == "note"
    assert (result2.differences[0].stopa_value, result2.differences[0].ref_value) == (None, "")


def test_compare_deterministic_difference_ordering():
    # řazení rozdílu: kind → join key → field (design §4 determinismus)
    stopa = [
        _rec("visit", url="https://c"),  # extra_in_stopa
        _rec("visit", 1_700_000_010, url="https://d"),  # extra_in_stopa
        _rec("visit", 1_700_000_020, url="https://e"),  # field_differs (ts)
    ]
    ref = [
        _rec("visit", url="https://c"),
        _rec("visit", 1_700_000_030, url="https://e"),
        _rec("visit", 1_700_000_040, url="https://f"),  # missing_in_ref
    ]
    result = compare_records(stopa, ref, _JOIN_KEYS)
    kinds = [d.kind for d in result.differences]
    assert kinds == sorted(kinds)  # kind jako primární řadicí klíč
    extra_keys = [d.join_key for d in result.differences if d.kind == KIND_EXTRA_IN_STOPA]
    assert extra_keys == sorted(extra_keys)


def test_compare_identical_pct_math_and_rounding():
    # žádné sdílené join klíče → 0 identických párů, union = sjednocení obou stran
    stopa = [_rec("visit", ts, url=f"https://s/{i}") for i, ts in enumerate(range(3))]
    ref = [_rec("visit", 9, url="https://t/9"), _rec("visit", 8, url="https://t/8")]
    result = compare_records(stopa, ref, _JOIN_KEYS)
    assert result.union_size == 5 and result.identical_pairs == 0
    assert result.identical_pct == 0.0

    # zaokrouhlení na 1 desetinné místo: 1 identický pár z unionu 3 → 33.3 %
    stopa2 = [_rec("visit", url="https://same")] + [
        _rec("visit", ts, url=f"https://x/{i}") for i, ts in enumerate((10, 11))
    ]
    ref2 = [_rec("visit", url="https://same")]
    result2 = compare_records(stopa2, ref2, _JOIN_KEYS)
    assert result2.union_size == 3 and result2.identical_pairs == 1
    assert result2.identical_pct == 33.3


def test_compare_empty_both_sides():
    result = compare_records([], [], _JOIN_KEYS)
    assert result.differences == ()
    assert result.union_size == 0
    assert result.identical_pct == 100.0  # triviální shoda


def test_compare_type_without_join_key_fails_fast():
    stopa = [_rec("note", url="x")]  # typ "note" nemá deklarovaný join key
    with pytest.raises(ValueError, match="note"):
        compare_records(stopa, [], _JOIN_KEYS)


def test_compare_non_canonical_record_typeerror():
    with pytest.raises(TypeError, match="CanonicalRecord"):
        compare_records(["ne-je-record"], [], _JOIN_KEYS)  # type: ignore[list-item]


def test_compare_missing_join_field_valueerror():
    # záznam bez klíčového pole → make_join_key fail-fast (design §3.4)
    stopa = [canonicalize("visit", 1_700_000_000, {"jiné": "x"})]
    with pytest.raises(ValueError):
        compare_records(stopa, [], _JOIN_KEYS)


# ════════════════════════════ §4 — build_report ════════════════════════════

def test_build_report_metadata_counts_and_json_shape():
    stopa = [_rec("visit", url="https://a")]
    ref = [_rec("visit", 1_700_000_999, url="https://a")]
    report = build_report(
        parser="sqlite",
        stopa_records=stopa,
        ref_records=ref,
        join_keys=_JOIN_KEYS,
        input_sha256="abc123" * 10 + "abcd",
        reference_tool="sqlite3-dump@1.1.x",
        run_id="run-42",
    )
    assert report.parser == "sqlite"
    assert report.stopa_records == 1 and report.ref_records == 1
    data = report.to_dict()
    # klíčové jména dle vzoru designu §4
    assert set(data) == {
        "parser", "input_sha256", "reference_tool",
        "stopa_records", "ref_records", "differences", "identical_pct", "run_id",
    }
    assert data["differences"][0]["kind"] == KIND_FIELD_DIFFERS
    assert data["differences"][0]["field"] == "ts_epoch"


def test_build_report_parser_validation():
    with pytest.raises(TypeError):
        build_report(parser=5, stopa_records=[], ref_records=[], join_keys={})  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        build_report(parser="", stopa_records=[], ref_records=[], join_keys={})


def test_build_report_to_json_bit_reproducible():
    # design §4: opakovaný běh na stejný vstup → bitově shodný report (bez run_id)
    stopa = [_rec("visit", ts, url=f"https://r/{i}") for i, ts in enumerate(range(3))]
    ref = list(reversed(stopa))
    r1 = build_report(parser="sqlite", stopa_records=stopa, ref_records=ref, join_keys=_JOIN_KEYS)
    r2 = build_report(parser="sqlite", stopa_records=list(reversed(stopa)), ref_records=ref,
                      join_keys=_JOIN_KEYS)
    assert r1.to_json() == r2.to_json()  # bitová shoda včetně pořadí klíčů

    parsed = json.loads(r1.to_json())
    assert parsed["identical_pct"] == 100.0 and parsed["differences"] == []
    # seřazené klíče v JSON (determinismus) — "parser" jde před "stopa_records"
    raw = r1.to_json()
    assert raw.index('"differences"') < raw.index('"identical_pct"') < raw.index('"parser"')


def test_difference_id_deterministic_and_unique():
    d1 = Difference(kind=KIND_FIELD_DIFFERS, join_key="visit:https://x", field="ts_epoch")
    d2 = Difference(kind=KIND_EXTRA_IN_STOPA, join_key="visit:https://y")
    assert d1.id == "field_differs:visit:https://x:ts_epoch"
    assert d2.id == "extra_in_stopa:visit:https://y"
    assert len({d1.id, d2.id}) == 2


# ════════════════════════════ §5 — adjudicate (verdikty) ════════════════════════════

def test_adjudicate_statuses_and_reasons():
    diffs = [
        Difference(kind=KIND_FIELD_DIFFERS, join_key="visit:https://a", field="ts_epoch"),
        Difference(kind=KIND_EXTRA_IN_STOPA, join_key="visit:https://b"),
    ]
    decisions = {
        diffs[0].id: {"status": STATUS_SEMANTIC_DIFF, "reason": "offset 2 s — jiná reprezentace"},
        diffs[1].id: STATUS_STOPA_WRONG,
    }
    out = adjudicate(diffs, decisions)
    assert [d.status for d in out] == [STATUS_SEMANTIC_DIFF, STATUS_STOPA_WRONG]
    assert out[0].reason == "offset 2 s — jiná reprezentace"
    assert out[1].reason is None
    # vstup se nemění (frozen dataclass → nová instance)
    assert diffs[0].status == "UNADJUDICATED" and diffs[1].status == "UNADJUDICATED"


def test_adjudicate_unknown_id_fails_fast():
    diff = Difference(kind=KIND_EXTRA_IN_STOPA, join_key="visit:https://x")
    with pytest.raises(ValueError, match="neznámé-id"):
        adjudicate([diff], {"neznámé-id": STATUS_AMBIGUOUS})


def test_adjudicate_invalid_status_valueerror():
    diff = Difference(kind=KIND_EXTRA_IN_STOPA, join_key="visit:https://x")
    for bad in ("WRONG", "", 5):
        with pytest.raises(ValueError):
            adjudicate([diff], {diff.id: bad})  # type: ignore[dict-item]
    assert ADJUDICATION_STATUSES == frozenset({
        "UNADJUDICATED", "STOPA_WRONG", "REF_WRONG", "SEMANTIC_DIFF", "AMBIGUOUS",
    })


def test_adjudicate_non_str_reason_valueerror():
    diff = Difference(kind=KIND_EXTRA_IN_STOPA, join_key="visit:https://x")
    with pytest.raises(ValueError):
        adjudicate([diff], {diff.id: {"status": STATUS_REF_WRONG, "reason": 42}})


def test_adjudicate_all_five_statuses_roundtrip():
    # všechny pět stavů z designu §5 je validní a zachovatelné
    diffs = [Difference(kind=KIND_EXTRA_IN_STOPA, join_key=f"visit:https://s/{i}") for i in range(5)]
    statuses = ["UNADJUDICATED", "STOPA_WRONG", "REF_WRONG", "SEMANTIC_DIFF", "AMBIGUOUS"]
    out = adjudicate(diffs, {d.id: s for d, s in zip(diffs, statuses)})
    assert [d.status for d in out] == statuses


# ════════════════════════════ §6 — exit kódy ════════════════════════════

def test_exit_code_zero_no_differences():
    assert exit_code_for([]) == 0


def test_exit_code_three_only_semantic_diff():
    diffs = [
        Difference(kind=KIND_FIELD_DIFFERS, join_key="visit:https://a", field="ts_epoch",
                   status=STATUS_SEMANTIC_DIFF),
        Difference(kind=KIND_EXTRA_IN_STOPA, join_key="visit:https://b", status=STATUS_SEMANTIC_DIFF),
    ]
    assert exit_code_for(diffs) == 3


def test_exit_code_one_other_cases():
    # neadjudikovaný rozdíl → 1 (konzervativní volba dle designu §6)
    unadj = Difference(kind=KIND_EXTRA_IN_STOPA, join_key="visit:https://x")
    assert exit_code_for([unadj]) == 1
    # adjudikované STOPA_WRONG / REF_WRONG / AMBIGUOUS → také 1
    for status in (STATUS_STOPA_WRONG, STATUS_REF_WRONG, STATUS_AMBIGUOUS):
        diff = Difference(kind=KIND_EXTRA_IN_STOPA, join_key="visit:https://x", status=status)
        assert exit_code_for([diff]) == 1
    # SEMANTIC_DIFF + jeden neadjudikovaný → 1 (ne všechny jsou semantic)
    mixed = [
        Difference(kind=KIND_FIELD_DIFFERS, join_key="visit:a", field="ts_epoch",
                   status=STATUS_SEMANTIC_DIFF),
        Difference(kind=KIND_EXTRA_IN_STOPA, join_key="visit:b"),
    ]
    assert exit_code_for(mixed) == 1


# ════════════════════════════ join key display ════════════════════════════

def test_join_key_display_single_multi_and_ts():
    rec = _rec("visit", url="https://x")
    assert join_key_display(rec, ("url",)) == "visit:https://x"

    multi = canonicalize("note", 1_700_000_000, {"a": "1", "b": "2"})
    assert join_key_display(multi, ("a", "b")) == "note:1:2"

    ts_rec = _rec("visit", url="https://x")
    # TS_KEY se vykresluje jako epoch (str(int)) — deterministicky
    assert join_key_display(ts_rec, (TS_KEY,)) == f"visit:{ts_rec.ts_epoch}"
