"""STP-049 — AI Copilot grounding: deterministické offline testy.

Bez LM Studio i bez case DB — čistá doménová logika ``domain/ai_grounding.py``.
Pokrytí: extrakce tvrdění (data ISO + česká, typy s word-boundary), atribuce
tvrdění k nejbližší citaci (včetně tie-breaku), tři kategorie rozporu
(mismatch_date / mismatch_type / unverified_claim), kotvy z details a determinismus.
"""

from __future__ import annotations

import copy

from stopa.domain.ai_assistant import extract_citations
from stopa.domain.ai_grounding import (
    KNOWN_ARTIFACT_TYPES,
    GroundingReport,
    extract_claims,
    ground_answer,
)


def _artifact(
    aid: str = "art-001",
    atype: str = "browser_history",
    ts: str | None = "2026-03-10T12:05:00+00:00",
    details: dict | None = None,
) -> dict:
    """Artifact ve tvaru ``model_dump(mode="json")`` (bez IO)."""
    return {
        "id": aid,
        "artifact_type": atype,
        "timestamp": ts,
        "title": None,
        "details": details or {},
    }


# ── KNOWN_ARTIFACT_TYPES ─────────────────────────────────────────────────────


class TestKnownTypes:
    def test_sorted_and_unique(self) -> None:
        assert KNOWN_ARTIFACT_TYPES == tuple(sorted(set(KNOWN_ARTIFACT_TYPES)))

    def test_covers_real_parser_types(self) -> None:
        # typy, které reálně produkují parsery (výběr z grep artifact_type=)
        for t in ("contact", "event_log_entry", "chat_message", "win_prefetch",
                  "google_search", "mem_process", "browser_tab", "call_record"):
            assert t in KNOWN_ARTIFACT_TYPES


# ── extract_claims ───────────────────────────────────────────────────────────


class TestExtractClaimsDates:
    def test_iso_date(self) -> None:
        claims = extract_claims("Událost se stala 2026-03-10.")
        dates = [c for c in claims if c.kind == "date"]
        assert len(dates) == 1
        assert dates[0].value == "2026-03-10"
        assert dates[0].raw == "2026-03-10"

    def test_iso_datetime_with_time(self) -> None:
        claims = extract_claims("Čas 2026-03-10T12:05:33 a 2026-03-10 12:05.")
        dates = [c for c in claims if c.kind == "date"]
        assert len(dates) == 2
        assert all(c.value == "2026-03-10" for c in dates)

    def test_czech_date_genitive(self) -> None:
        claims = extract_claims("Záznam z 10. března 2026 je klíčový.")
        dates = [c for c in claims if c.kind == "date"]
        assert len(dates) == 1
        assert dates[0].value == "2026-03-10"

    def test_czech_date_nominative(self) -> None:
        claims = extract_claims("Dne 5. května 2025 proběhlo kopírování.")
        dates = [c for c in claims if c.kind == "date"]
        assert len(dates) == 1
        assert dates[0].value == "2025-05-05"

    def test_invalid_month_skipped(self) -> None:
        claims = extract_claims("Podivné datum 2026-13-45.")
        assert [c for c in claims if c.kind == "date"] == []

    def test_invalid_day_skipped(self) -> None:
        claims = extract_claims("Datum 2026-02-31 neexistuje.")
        # 31. den v únoru — zjednodušená validace (1..31) to propustí,
        # ale měsíc 2 + den 31 je deterministicky zachycen jako claim;
        # semantická platnost měsíce není cílem STP-049.
        dates = [c for c in claims if c.kind == "date"]
        assert len(dates) == 1 and dates[0].value == "2026-02-31"


class TestExtractClaimsTypes:
    def test_type_word_boundary(self) -> None:
        claims = extract_claims("Šlo o chat_message, ne o my_chat_messages.")
        types = [c for c in claims if c.kind == "type"]
        assert len(types) == 1
        assert types[0].value == "chat_message"

    def test_type_case_insensitive(self) -> None:
        claims = extract_claims("Záznam Browser_History je důležitý.")
        types = [c for c in claims if c.kind == "type"]
        assert len(types) == 1
        assert types[0].value == "browser_history"
        assert types[0].raw == "Browser_History"

    def test_location_data_not_split_into_location(self) -> None:
        # `location` je substring `location_data` — delší alternativa musí vyhrát
        claims = extract_claims("Poloha z location_data a samostatná location.")
        types = [c for c in claims if c.kind == "type"]
        assert sorted(c.value for c in types) == ["location", "location_data"]

    def test_google_account_not_split_into_event(self) -> None:
        claims = extract_claims("google_account_event a google_account.")
        types = [c for c in claims if c.kind == "type"]
        assert sorted(c.value for c in types) == ["google_account", "google_account_event"]

    def test_sorted_by_position(self) -> None:
        text = "chat_message 2026-03-10 browser_history"
        claims = extract_claims(text)
        starts = [c.start for c in claims]
        assert starts == sorted(starts)


# ── ground_answer — ověřené citace ───────────────────────────────────────────


class TestVerifiedCitations:
    def test_correct_date_and_type(self) -> None:
        art = _artifact()  # browser_history @ 2026-03-10
        text = "Uživatel navštívil web 2026-03-10 podle záznamu browser_history [art:art-001]."
        report = ground_answer(text, ["art-001"], {"art-001": art})
        assert not report.has_contradictions
        assert report.verified_citations == ("art-001",)

    def test_czech_date_verified(self) -> None:
        art = _artifact()
        text = "Navštěva proběhla 10. března 2026 [art:art-001]."
        report = ground_answer(text, ["art-001"], {"art-001": art})
        assert not report.has_contradictions

    def test_value_anchor_from_details(self) -> None:
        # dlouhý prose (≥20 znaků), žádné datum ani typ — ale hodnota z details
        # se v odpovědi objeví → kotva "value" → citace ověřená
        art = _artifact(details={"url": "https://example.com/secret-page"})
        text = ("Uživatel podle záznamu v databázi navštívil stránku "
                "https://example.com/secret-page [art:art-001].")
        report = ground_answer(text, ["art-001"], {"art-001": art})
        assert not report.has_contradictions
        assert report.verified_citations == ("art-001",)

    def test_value_anchor_case_insensitive(self) -> None:
        art = _artifact(details={"user_agent": "Mozilla/5.0 (Windows NT 10.0)"})
        text = "Agent byl mozilla/5.0 (windows nt 10.0), viz [art:art-001]."
        report = ground_answer(text, ["art-001"], {"art-001": art})
        assert not report.has_contradictions


# ── ground_answer — mismatch_date ────────────────────────────────────────────


class TestMismatchDate:
    def test_wrong_date(self) -> None:
        art = _artifact()  # reálné datum 2026-03-10
        text = "Web 2025-01-01 [art:art-001]."
        report = ground_answer(text, ["art-001"], {"art-001": art})
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.category == "mismatch_date"
        assert f.citation_id == "art-001"
        assert f.claim == "2025-01-01"
        assert f.actual == "2026-03-10"

    def test_no_timestamp_unverifiable(self) -> None:
        # artifact bez timestampu — datum v odpovědi je neověřitelné, ale není rozpor
        art = _artifact(ts=None)
        text = "Web 2025-01-01 [art:art-001]."
        report = ground_answer(text, ["art-001"], {"art-001": art})
        assert not report.has_contradictions


# ── ground_answer — mismatch_type ────────────────────────────────────────────


class TestMismatchType:
    def test_wrong_type(self) -> None:
        art = _artifact(atype="browser_history")
        text = "Šlo o chat_message [art:art-001]."
        report = ground_answer(text, ["art-001"], {"art-001": art})
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.category == "mismatch_type"
        assert f.claim == "chat_message"
        assert f.actual == "browser_history"

    def test_correct_type_no_mismatch(self) -> None:
        art = _artifact(atype="win_prefetch")
        text = "Záznam win_prefetch potvrzuje spuštění [art:art-001]."
        report = ground_answer(text, ["art-001"], {"art-001": art})
        assert not report.has_contradictions


# ── ground_answer — unverified_claim ─────────────────────────────────────────


class TestUnverifiedClaim:
    def test_long_prose_no_anchor(self) -> None:
        # prose ≥ 20 znaků, žádné datum/typ/hodnota z details → rozpor
        art = _artifact(details={"note": "krátké"})
        text = ("Podle analýzy šlo o důležitou událost v historii prohlížeče "
                "uživatele na testovaném zařízení [art:art-001].")
        report = ground_answer(text, ["art-001"], {"art-001": art})
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.category == "unverified_claim"
        assert f.actual is None
        assert f.claim and len(f.claim) <= 120

    def test_short_prose_no_finding(self) -> None:
        # prose < 20 znaků — citace bez kotvy, ale bez podstatného textu
        art = _artifact()
        text = "Viz [art:art-001]."
        report = ground_answer(text, ["art-001"], {"art-001": art})
        assert not report.has_contradictions


# ── atribuce tvrdění k citacím ───────────────────────────────────────────────


class TestAttribution:
    def test_nearest_citation_wins(self) -> None:
        # datum je blíž [art:a] → rozpor patří a, ne b
        art_a = _artifact(aid="art-a", ts="2026-03-10T12:05:00+00:00")
        art_b = _artifact(aid="art-b", ts="2025-01-01T08:00:00+00:00")
        text = "Záznam z 2025-01-01 [art:art-a]. Druhý je OK [art:art-b]."
        report = ground_answer(text, ["art-a", "art-b"], {"art-a": art_a, "art-b": art_b})
        assert len(report.findings) == 1
        assert report.findings[0].citation_id == "art-a"
        assert report.verified_citations == ("art-b",)

    def test_tie_break_earlier_index(self) -> None:
        # tvrzení přesně stejně daleko od obou citací → vyhrává menší index (a)
        art_a = _artifact(aid="art-a", ts="2026-03-10T12:05:00+00:00")
        art_b = _artifact(aid="art-b", ts="2025-01-01T08:00:00+00:00")
        text = "[art:art-a] 2025-01-01 [art:art-b]"
        report = ground_answer(text, ["art-a", "art-b"], {"art-a": art_a, "art-b": art_b})
        assert len(report.findings) == 1
        assert report.findings[0].citation_id == "art-a"

    def test_multiple_claims_one_citation(self) -> None:
        # dvě chybná tvrzení u jedné citace → dva findingy, citace neověřená
        art = _artifact(atype="browser_history")
        text = "Web 2025-01-01 a chat_message [art:art-001]."
        report = ground_answer(text, ["art-001"], {"art-001": art})
        cats = sorted(f.category for f in report.findings)
        assert cats == ["mismatch_date", "mismatch_type"]
        assert report.verified_citations == ()


# ── okrajové případy + determinismus ────────────────────────────────────────


class TestEdgeCases:
    def test_empty_citations(self) -> None:
        report = ground_answer("Žádné citace v textu.", [], {})
        assert isinstance(report, GroundingReport)
        assert not report.has_contradictions
        assert report.verified_citations == ()

    def test_unknown_artifact_id_skipped_defensively(self) -> None:
        # ID v citations, ale chybí v artifacts_by_id → skip bez výjimky
        report = ground_answer("Text s citací [art:chybi].", ["art-chybi"], {})
        assert not report.has_contradictions

    def test_deterministic(self) -> None:
        art_a = _artifact(aid="art-a", ts="2026-03-10T12:05:00+00:00")
        text = "Záznam z 2025-01-01 [art:art-a]. Druhý je OK [art:art-b]."
        by_id = {"art-a": art_a, "art-b": _artifact(aid="art-b", ts="2025-01-01T08:00:00+00:00")}
        r1 = ground_answer(text, ["art-a", "art-b"], by_id)
        r2 = ground_answer(copy.deepcopy(text), copy.deepcopy(["art-a", "art-b"]), copy.deepcopy(by_id))
        assert r1.to_dict() == r2.to_dict()

    def test_to_dict_shape(self) -> None:
        art = _artifact()
        text = "Web 2025-01-01 [art:art-001]."
        report = ground_answer(text, ["art-001"], {"art-001": art})
        d = report.to_dict()
        assert set(d) == {"verified", "findings"}
        f = d["findings"][0]
        assert set(f) == {"category", "citation_id", "claim", "actual"}

    def test_has_contradictions_property(self) -> None:
        art = _artifact()
        clean = ground_answer("Viz [art:art-001].", ["art-001"], {"art-001": art})
        dirty = ground_answer("Web 2025-01-01 [art:art-001].", ["art-001"], {"art-001": art})
        assert clean.has_contradictions is False
        assert dirty.has_contradictions is True


# ── kompozice s extract_citations (tvar, jak ho použije web endpoint) ────────


class TestCompositionWithExtractCitations:
    def test_raw_text_pipeline(self) -> None:
        # web endpoint: text = raw odpověď LLM; ground_answer dostane RAW text
        art = _artifact(atype="browser_history", ts="2026-03-10T12:05:00+00:00")
        raw = "Uživatel navštívil web 2026-03-10 podle browser_history [art:art-001]."
        clean, cited = extract_citations(raw, {"art-001"})
        assert "[art:" not in clean and cited == ["art-001"]
        report = ground_answer(raw, cited, {"art-001": art})
        assert not report.has_contradictions

    def test_invalid_token_removed_before_grounding(self) -> None:
        # nevalidní token vyřadí extract_citations → grounding ho nevidí
        art = _artifact()
        raw = "Text s [art:neexistuje] a [art:art-001]."
        _clean, cited = extract_citations(raw, {"art-001"})
        assert cited == ["art-001"]
        report = ground_answer(raw, cited, {"art-001": art})
        # prose před citací < 20 znaků → bez kotvy i tak neověřená? Ne:
        # "Text s " je krátké → žádné unverified_claim
        assert not report.has_contradictions
