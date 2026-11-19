"""P2-3 Advanced Timeline Intelligence — domain vrstva (Wave 1).

Pokrytí návrhu (docs/P2_DESIGNS.md §P2-3):
- normalizace do UTC s deklarovanou přesností (epoch s/ms/µs Chrome, ISO+offset,
  TZ edge cases: DST přechody Europe/Prague),
- gap/outlier detekce na celé timeline (IQR + konfigurovatelný prah) —
  syntetická timeline s známými gaps/outliery → přesný počet i ID,
- cross-source korelace (sdílená entita v okně z odlišných zdrojů) s E4 confidence,
- vysvětlení nejistoty per událost + souhrn,
- determinismus: stejné vstupy (i v jiném pořadí) = stejný JSON.

Čistě offline — žádné IO, žádné LLM.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from stopa.domain.timeline_adv import (
    analyze_timeline_adv,
    detect_gaps,
    detect_outliers,
    explain_uncertainty,
    find_cross_source_correlations,
    normalize_to_utc,
    uncertainty_summary,
)


def _ev(eid: str, ts: datetime | str, *, source: str = "s1", subjects=(), **kw) -> dict:
    """Řádek ve tvaru výstupu db.list_timeline_events()."""
    base: dict = {
        "id": eid,
        "source_id": source,
        "event_type": "test_event",
        "ts_utc": ts.isoformat() if isinstance(ts, datetime) else ts,
        "title": None,
        "confidence": 0.9,
        "parser_version": "p1",
        "anomaly_flags": [],
        "ts_origin": "source",
        "subject_values": list(subjects),
        "contradiction_group_id": None,
        "dup_group_id": None,
    }
    base.update(kw)
    return base


# ── Normalizace s deklarovanou přesností ─────────────────────────────────────


class TestNormalizeToUtc:
    def test_epoch_seconds(self):
        r = normalize_to_utc(1_700_000_000)   # 2023-11-14T22:13:20Z (známá hodnota)
        assert r.ts_utc == datetime(2023, 11, 14, 22, 13, 20)
        assert r.precision == "second"

    def test_epoch_milliseconds(self):
        r = normalize_to_utc(1_700_000_000_123)   # magnitude ≥1e10 → ms
        assert r.ts_utc == datetime(2023, 11, 14, 22, 13, 20, 123_000)
        assert r.precision == "millisecond"

    def test_epoch_microseconds_chrome(self):
        r = normalize_to_utc(1_700_000_000_123_456)   # magnitude ≥1e13 → µs (Chrome)
        assert r.ts_utc == datetime(2023, 11, 14, 22, 13, 20, 123_456)
        assert r.precision == "microsecond"

    def test_iso_with_offset_converted_to_utc(self):
        r = normalize_to_utc("2026-03-29T04:30:00+02:00")
        assert r.ts_utc == datetime(2026, 3, 29, 2, 30)

    def test_naive_with_iana_zone_dst_spring(self):
        # EU léto 2026: přechod v neděli 2026-03-29 v 01:00Z (CET→CEST).
        before = normalize_to_utc("2026-03-28T23:30:00", tz="Europe/Prague")   # CET +01
        assert before.ts_utc == datetime(2026, 3, 28, 22, 30)
        after = normalize_to_utc("2026-03-29T03:30:00", tz="Europe/Prague")    # CEST +02
        assert after.ts_utc == datetime(2026, 3, 29, 1, 30)

    def test_naive_with_iana_zone_dst_autumn(self):
        # Podzim 2026: přechod v neděli 2026-10-25 v 01:00Z (CEST→CET).
        r = normalize_to_utc("2026-10-25T04:00:00", tz="Europe/Prague")   # už CET +01
        assert r.ts_utc == datetime(2026, 10, 25, 3, 0)

    def test_naive_without_zone_is_utc(self):
        r = normalize_to_utc("2026-01-01T00:00:00")
        assert r.ts_utc == datetime(2026, 1, 1, 0, 0)

    def test_aware_datetime_input(self):
        dt = datetime(2026, 1, 1, 5, 0, tzinfo=ZoneInfo("Europe/Prague"))   # CET +01
        r = normalize_to_utc(dt)
        assert r.ts_utc == datetime(2026, 1, 1, 4, 0)

    def test_invalid_inputs(self):
        with pytest.raises(ValueError, match="nepodporovaný tvar"):
            normalize_to_utc("garbage")
        with pytest.raises(ValueError, match="nezáporný"):
            normalize_to_utc(-1)


# ── Gapy (IQR + absolutní prah) ──────────────────────────────────────────────


def _regular_with_gap() -> list[dict]:
    """10 událostí po 60 s + jedna o 7200 s dál → přesně jeden známý gap."""
    out: list[dict] = []
    base = datetime(2026, 5, 1, 12, 0, 0)

    for i in range(10):
        out.append(_ev(f"e{i}", base + timedelta(seconds=60 * i)))
    out.append(_ev("g1", base + timedelta(seconds=9 * 60 + 7200)))
    return out


class TestDetectGaps:
    def test_exact_known_gap(self):
        gaps = detect_gaps(_regular_with_gap())
        assert len(gaps) == 1
        g = gaps[0]
        assert (g.start_event_id, g.end_event_id) == ("e9", "g1")
        assert g.duration_seconds == 7200.0

    def test_small_timeline_uses_absolute_floor_only(self):
        # 4 události → jen 3 intervaly (< MIN_IQR_SAMPLES=8) → IQR se nepoužije,
        # platí pouze absolutní prah (default 60 s).
        base = datetime(2026, 5, 1, 12)
    
        evs = [_ev(f"s{i}", base + timedelta(seconds=120 * i)) for i in range(4)]
        gaps = detect_gaps(evs)
        assert len(gaps) == 3
        assert all(g.duration_seconds == 120.0 for g in gaps)

    def test_empty_and_single(self):
        assert detect_gaps([]) == ()
        assert detect_gaps([_ev("a", "2026-05-01T12:00:00")]) == ()


# ── Outliery (izolované oboustranně) ─────────────────────────────────────────


def _burst_isolated_burst() -> list[dict]:
    """Burst A (15×10 s), izolovaná událost, burst B — přesně jeden outlier."""

    base = datetime(2026, 5, 1, 12)
    evs: list[dict] = []
    for i in range(15):   # A: t = 0..140 s
        evs.append(_ev(f"a{i}", base + timedelta(seconds=10 * i)))
    evs.append(_ev("lone", base + timedelta(seconds=3740)))
    for i in range(15):   # B: t = 7200..7340 s
        evs.append(_ev(f"b{i}", base + timedelta(seconds=7200 + 10 * i)))
    return evs


class TestDetectOutliers:
    def test_exact_isolated_event(self):
        outliers = detect_outliers(_burst_isolated_burst())
        assert len(outliers) == 1
        o = outliers[0]
        assert o.event_id == "lone"
        assert o.prev_gap_seconds == 3600.0   # 3740 - 140
        assert o.next_gap_seconds == 3460.0   # 7200 - 3740

    def test_too_few_events(self):
        base = "2026-05-01T12:00:00"
        assert detect_outliers([_ev("a", base)]) == ()
        assert detect_outliers([_ev("a", base), _ev("b", "2026-05-01T13:00:00")]) == ()


# ── Cross-source korelace ────────────────────────────────────────────────────

SUBJ_A = "email:alice@example.com"
SUBJ_B = "tel:+420777000111"


class TestCrossSourceCorrelations:
    def test_basic_pair_within_window(self):
        base = datetime(2026, 5, 1, 12)
    
        evs = [
            _ev("e1", base, source="s1", subjects=[SUBJ_A]),
            _ev("e2", base + timedelta(seconds=60), source="s2", subjects=[SUBJ_A]),
        ]
        groups = find_cross_source_correlations(evs)
        assert len(groups) == 1
        g = groups[0]
        assert g.subject == SUBJ_A
        assert g.source_ids == ("s1", "s2")
        assert g.event_ids == ("e1", "e2")
        assert g.confidence == "possible"   # default bez entity_confidence

    def test_entity_confidence_applied(self):
        base = datetime(2026, 5, 1, 12)
    
        evs = [
            _ev("e1", base, source="s1", subjects=[SUBJ_A]),
            _ev("e2", base + timedelta(seconds=60), source="s2", subjects=[SUBJ_A]),
        ]
        groups = find_cross_source_correlations(
            evs, entity_confidence={SUBJ_A: "confirmed"}
        )
        assert len(groups) == 1 and groups[0].confidence == "confirmed"

    def test_invalid_confidence_falls_back_to_default(self):
        base = datetime(2026, 5, 1, 12)
    
        evs = [
            _ev("e1", base, source="s1", subjects=[SUBJ_A]),
            _ev("e2", base + timedelta(seconds=60), source="s2", subjects=[SUBJ_A]),
        ]
        groups = find_cross_source_correlations(evs, entity_confidence={SUBJ_A: "bogus"})
        assert len(groups) == 1 and groups[0].confidence == "possible"

    def test_outside_window_no_group(self):
        base = datetime(2026, 5, 1, 12)
    
        evs = [
            _ev("e1", base, source="s1", subjects=[SUBJ_A]),
            _ev("e2", base + timedelta(seconds=40 * 60), source="s2", subjects=[SUBJ_A]),
        ]
        assert find_cross_source_correlations(evs) == ()

    def test_same_source_not_cross(self):
        base = datetime(2026, 5, 1, 12)
    
        evs = [
            _ev("e1", base, source="s1", subjects=[SUBJ_A]),
            _ev("e2", base + timedelta(seconds=60), source="s1", subjects=[SUBJ_A]),
        ]
        assert find_cross_source_correlations(evs) == ()

    def test_transitive_component_per_subject_groups(self):
        """Komponenta přes dva subjekty → jedna skupina na (subjekt, komponentu)."""
        base = datetime(2026, 5, 1, 12)
    
        evs = [
            _ev("e1", base, source="s1", subjects=[SUBJ_A, SUBJ_B]),
            _ev("e2", base + timedelta(seconds=60), source="s2", subjects=[SUBJ_B]),
            _ev("e3", base + timedelta(seconds=120), source="s3", subjects=[SUBJ_A]),
        ]
        groups = find_cross_source_correlations(evs)
        assert len(groups) == 2
        by_subject = {g.subject: g for g in groups}
        assert set(by_subject) == {SUBJ_A, SUBJ_B}
        ga, gb = by_subject[SUBJ_A], by_subject[SUBJ_B]
        assert ga.event_ids == ("e1", "e3") and ga.source_ids == ("s1", "s3")
        assert gb.event_ids == ("e1", "e2") and gb.source_ids == ("s1", "s2")


# ── Vysvětlení nejistoty ─────────────────────────────────────────────────────


class TestExplainUncertainty:
    def test_dirty_event_all_reasons_sorted(self):
        ev = _ev(
            "e1", "2026-05-01T12:00:00", confidence=0.3, ts_origin="derived",
            anomaly_flags=["out_of_range", "duplicate"],
            contradiction_group_id="tci-x", dup_group_id="dup-y", parser_version="",
        )
        exps = explain_uncertainty([ev])
        assert len(exps) == 1
        e = exps[0]
        assert e.event_id == "e1"
        assert e.reasons == (
            "anomaly_flag:duplicate",
            "anomaly_flag:out_of_range",
            "cross_source_duplicate",
            "derived_timestamp",
            "in_contradiction",
            "low_confidence",
            "no_parser_version",
        )
        assert e.severity == "high"

    def test_clean_event_not_returned(self):
        ev = _ev("e1", "2026-05-01T12:00:00")   # confidence 0.9, source, p1, bez flagů
        assert explain_uncertainty([ev]) == ()

    def test_weak_precision_on_unparseable_ts(self):
        ev = _ev("e3", "garbage")
        exps = explain_uncertainty([ev])
        assert len(exps) == 1 and exps[0].reasons == ("weak_precision",)
        assert exps[0].severity == "low"

    def test_sorted_by_event_id_regardless_of_input_order(self):
        a = _ev("a1", "2026-05-01T12:00:00", confidence=0.2)
        b = _ev("b1", "2026-05-01T13:00:00", ts_origin="derived")
        assert [e.event_id for e in explain_uncertainty([a, b])] == ["a1", "b1"]
        assert [e.event_id for e in explain_uncertainty([b, a])] == ["a1", "b1"]

    def test_summary_counts(self):
        dirty = _ev(
            "e1", "2026-05-01T12:00:00", confidence=0.3, ts_origin="derived",
            anomaly_flags=["duplicate"], parser_version="",
        )
        weak = _ev("e3", "garbage")
        s = uncertainty_summary(explain_uncertainty([dirty, weak]))
        assert s["events_flagged"] == 2
        assert s["by_severity"]["high"] >= 1 and s["by_severity"]["low"] == 1
        assert s["by_reason"]["anomaly_flag"] == 1
        assert s["by_reason"]["weak_precision"] == 1


# ── Agregátor + determinismus ────────────────────────────────────────────────


def _mixed_events() -> list[dict]:
    """Timeline pokrývající gaps, outlier i korelace najednou."""

    base = datetime(2026, 5, 1, 12)
    evs: list[dict] = []
    for i in range(15):   # burst A — s1, subjekt A
        evs.append(_ev(f"a{i}", base + timedelta(seconds=10 * i), source="s1", subjects=[SUBJ_A]))
    evs.append(_ev("lone", base + timedelta(seconds=3740)))
    for i in range(15):   # burst B — s2, sdílený subjekt A (korelace přes okno)
        ts = base + timedelta(seconds=7200 + 10 * i)
        evs.append(_ev(f"b{i}", ts, source="s2", subjects=[SUBJ_A] if i < 3 else []))
    return evs


class TestAnalyzeAndDeterminism:
    def test_analyze_runs_all_layers(self):
        result = analyze_timeline_adv(_mixed_events())
        assert len(result.gaps) >= 1          # burst A → lone a lone → burst B
        assert any(o.event_id == "lone" for o in result.outliers)
        d = result.to_dict()
        assert set(d) == {"gaps", "outliers", "correlations", "uncertainty", "summary"}

    def test_deterministic_json_independent_of_input_order(self):
        evs = _mixed_events()
        import random

        shuffled = list(evs)
        random.Random(42).shuffle(shuffled)
        a = json.dumps(analyze_timeline_adv(evs).to_dict(), sort_keys=True)
        b = json.dumps(analyze_timeline_adv(shuffled).to_dict(), sort_keys=True)
        assert a == b
