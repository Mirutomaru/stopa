"""P0.5 — Golden testy časových značek reportu (forensic integrity hardening).

Kontrakt:
- Interní časy jsou vědomé (aware) v UTC, vykreslené jako ISO 8601 s explicitní TZ.
- Naive vstup = smluvně považován za UTC + evidovaná poznámka o nejistotě.
- Stejný vstup + stejné hodiny = byte-identický deterministický obsah reportu.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stopa.domain.report import (
    ReportData,
    build_html,
    resolve_generated_at,
)


def _data(**kw: object) -> ReportData:
    base: dict[str, object] = {
        "case_id": "case-p05",
        "case_name": "P0.5 TZ",
        "examiner": None,
        "created_at": datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc),
    }
    base.update(kw)
    return ReportData(**base)  # type: ignore[arg-type]


FIXED_NOW = datetime(2026, 11, 22, 8, 30, 45, tzinfo=timezone.utc)


class TestResolveGeneratedAt:
    def test_none_uses_injected_clock(self) -> None:
        dt, note = resolve_generated_at(_data(), now_fn=lambda: FIXED_NOW)
        assert dt == FIXED_NOW
        assert note == ""

    def test_utc_passthrough(self) -> None:
        g = datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc)
        dt, note = resolve_generated_at(_data(generated_at=g))
        assert dt == g
        assert note == ""

    def test_prague_winter_cet_normalized_to_utc(self) -> None:
        # Europe/Prague v zimě (CET, UTC+1): 14:00 lokálně = 13:00 UTC
        cet = timezone(timedelta(hours=1))
        g = datetime(2026, 11, 17, 14, 0, tzinfo=cet)
        dt, note = resolve_generated_at(_data(generated_at=g))
        assert dt == datetime(2026, 11, 17, 13, 0, tzinfo=timezone.utc)
        assert note == ""

    def test_prague_summer_cest_normalized_to_utc(self) -> None:
        # Europe/Prague v létě (CEST, UTC+2): 14:00 lokálně = 12:00 UTC
        cest = timezone(timedelta(hours=2))
        g = datetime(2026, 7, 15, 14, 0, tzinfo=cest)
        dt, note = resolve_generated_at(_data(generated_at=g))
        assert dt == datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
        assert note == ""

    def test_dst_transition_both_offsets(self) -> None:
        # Přechod CEST→CET (25. 10. 2026): obě strany přechodu se normalizují
        cest = timezone(timedelta(hours=2))
        cet = timezone(timedelta(hours=1))
        before = datetime(2026, 10, 25, 3, 0, tzinfo=cest)  # 01:00 UTC
        after = datetime(2026, 10, 25, 3, 30, tzinfo=cet)   # 02:30 UTC
        dt_before, note_b = resolve_generated_at(_data(generated_at=before))
        dt_after, note_a = resolve_generated_at(_data(generated_at=after))
        assert dt_before == datetime(2026, 10, 25, 1, 0, tzinfo=timezone.utc)
        assert dt_after == datetime(2026, 10, 25, 2, 30, tzinfo=timezone.utc)
        assert note_b == "" and note_a == ""

    def test_naive_assumed_utc_with_note(self) -> None:
        g = datetime(2026, 11, 17, 14, 0)  # naive — kontrakt: považovat za UTC
        dt, note = resolve_generated_at(_data(generated_at=g))
        assert dt == datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc)
        assert note == "naive-timestamp-assumed-utc"

    def test_mislabeled_utc_is_documented_not_silent(self) -> None:
        # Čas, který volající MÝLNE označil jako UTC (ve skutečnosti lokalní):
        # kontrakt ho sice vezme za UTC — ale poznámka nejistoty se eviduje,
        # aby chyba nebyla tichá.
        g = datetime(2026, 11, 17, 12, 0)  # "mislabeled" naive
        dt, note = resolve_generated_at(_data(generated_at=g))
        assert dt.tzinfo is not None
        assert note == "naive-timestamp-assumed-utc"


class TestBuildHtmlRendering:
    def test_aware_utc_renders_iso8601(self) -> None:
        g = datetime(2026, 7, 15, 14, 0, tzinfo=timezone(timedelta(hours=2)))
        html_doc = build_html(_data(generated_at=g))
        assert "2026-07-15T12:00:00+00:00" in html_doc

    def test_naive_renders_note_line(self) -> None:
        g = datetime(2026, 11, 17, 14, 0)  # naive
        html_doc = build_html(_data(generated_at=g))
        assert "2026-11-17T14:00:00+00:00" in html_doc
        assert "naive-timestamp-assumed-utc" in html_doc

    def test_generated_at_note_rendered_in_header(self) -> None:
        g = datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc)
        html_doc = build_html(
            _data(generated_at=g, generated_at_note="NTP drift ±5 s")
        )
        assert "NTP drift ±5 s" in html_doc

    def test_none_generated_uses_clock_no_note(self) -> None:
        html_doc = build_html(_data(), _clock=lambda: FIXED_NOW)
        assert "2026-11-22T08:30:45+00:00" in html_doc

    def test_deterministic_bytes_with_fixed_clock(self) -> None:
        # Stejný vstup + stejné hodiny = identické bajty (determinismus reportu).
        g = datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc)
        data = _data(generated_at=g)
        h1 = build_html(data, _clock=lambda: FIXED_NOW)
        h2 = build_html(data, _clock=lambda: FIXED_NOW)
        assert h1 == h2
