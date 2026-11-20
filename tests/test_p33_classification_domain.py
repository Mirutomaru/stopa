"""P3-3 W1 — pravidlový klasifikátor (čistá doména domain/classification.py).

Offline determinismus: žádné I/O, síť ani ML. AK pokrytí:
- AK1 stejné vstupy → stejné výstupy (včetně permutace pořadí typů)
- AK2 každá klasifikace nese neprázdné reasons[]
- taxonomie limitována na hodnoty artifact_type z rejstříku parserů
"""

from __future__ import annotations

import pytest

from stopa.domain.classification import (
    ARTIFACT_TYPE_RULES,
    CATEGORIES,
    DEFAULT_THRESHOLD,
    UNKNOWN_CATEGORY,
    Classification,
    ClassificationInput,
    classification_to_dict,
    classify,
)

# Kanonický seznam hodnot artifact_type — konvence viz ai_grounding.py:
# grep -rhoE 'artifact_type="[^"]+"' src/stopa/**/*.py (74 unikátních hodnot).
CANONICAL_ARTIFACT_TYPES = frozenset(
    {
        "app_execution",
        "autofill_entry",
        "browser_bookmark",
        "browser_cookie",
        "browser_history",
        "browser_search",
        "browser_setting",
        "browser_tab",
        "calendar_event",
        "call_log",
        "call_record",
        "chat_message",
        "clipboard_entry",
        "cloud_file",
        "cloud_instance",
        "contact",
        "credential",
        "crypto_detection",
        "crypto_exchange_record",
        "crypto_wallet",
        "disk_image",
        "document_metadata",
        "drive_activity",
        "email_attachment",
        "email_message",
        "event_log_entry",
        "file_metadata",
        "google_account",
        "google_account_event",
        "google_activity",
        "google_device",
        "google_export_summary",
        "google_identity_session",
        "google_location",
        "google_login",
        "google_mail_info",
        "google_maps_activity",
        "google_photo",
        "google_search",
        "imessage",
        "location",
        "location_data",
        "mem_connection",
        "mem_handle",
        "mem_hook",
        "mem_module",
        "mem_process",
        "memory_file",
        "memory_process",
        "messenger_message",
        "network_connection",
        "parser_error",
        "plist_date",
        "property_list",
        "registry_hive",
        "scheduled_task",
        "shell_link",
        "skype_account",
        "sms_message",
        "sns_comment",
        "sns_post",
        "sqlite_database",
        "sqlite_deleted_row",
        "user_sid",
        "usn_record",
        "voice_recording",
        "voicemail",
        "web_page",
        "whatsapp_message",
        "wifi_profile",
        "win_driver",
        "win_jumplist",
        "win_prefetch",
    }
)


class TestTaxonomy:
    def test_categories_unique_and_closed(self):
        assert len(CATEGORIES) == 11
        assert len(set(CATEGORIES)) == 11
        assert UNKNOWN_CATEGORY in CATEGORIES

    def test_rules_reference_valid_categories_and_weights(self):
        for name, (category, weight) in ARTIFACT_TYPE_RULES.items():
            assert category in CATEGORIES, name
            assert 0 < weight <= 1.0, name

    def test_rule_coverage_matches_canonical_set(self):
        """Pravidla pokrývají přesně kanonický soubor artifact_type hodnot."""
        assert set(ARTIFACT_TYPE_RULES) == CANONICAL_ARTIFACT_TYPES


class TestClassifyCore:
    def test_browser_file_high_confidence(self):
        c = classify(ClassificationInput(file_name="History", artifact_types=("browser_history",)))
        assert c.category == "browser"
        assert c.confidence == 1.0
        assert c.needs_review is False
        assert c.risk_flags == ()

    def test_chat_messaging_from_multiple_types(self):
        c = classify(
            ClassificationInput(
                file_name="wa.db", artifact_types=("chat_message", "sms_message")
            )
        )
        assert c.category == "chat_messaging"
        assert c.confidence == 1.0

    def test_mixed_content_goes_to_review(self):
        """Browser + e-mail v jednom souboru → rozdělená důvěra pod prahem."""
        c = classify(
            ClassificationInput(
                artifact_types=("browser_history", "email_message")
            )
        )
        assert c.needs_review is True  # 0.5 < 0.6
        assert c.confidence == pytest.approx(0.5, abs=1e-9)
        assert any("0.50" in r for r in c.reasons)

    def test_parser_error_only_low_confidence_unknown(self):
        c = classify(ClassificationInput(file_name="x.bin", artifact_types=("parser_error",)))
        assert c.category == UNKNOWN_CATEGORY
        assert c.confidence <= 0.4
        assert c.needs_review is True

    def test_unlisted_artifact_type_weak_signal(self):
        c = classify(
            ClassificationInput(artifact_types=("future_parser_type",))
        )
        assert c.category == UNKNOWN_CATEGORY
        assert c.confidence <= 0.4
        assert any("neznámé artifact_type" in r for r in c.reasons)

    def test_entity_corroboration_raises_confidence(self):
        """E-mail + slabý signál identity; entity e-mail potvrzují → nad prahem."""
        inp = ClassificationInput(
            file_name="export.mbox",
            artifact_types=("email_message", "autofill_entry"),
            entity_kinds=("email",),
        )
        c = classify(inp)
        assert c.category == "email"
        # 1.0/1.6 ≈ 0.62 → +0.1 corroboration → ~0.72 (mezihranice zaokrouhlení)
        assert 0.7 <= c.confidence <= 0.8
        assert c.needs_review is False
        assert any("potvrzeno entitami" in r for r in c.reasons)

    def test_risk_flags_and_reasons(self):
        c = classify(
            ClassificationInput(
                file_name="notes.pdf",
                artifact_types=("document_metadata",),
                hash_set_hit=True,
                bad_extension=True,
            )
        )
        assert c.risk_flags == ("hash_set_hit", "bad_extension")
        joined = "\n".join(c.reasons)
        assert "hash set" in joined
        assert "extenze" in joined

    def test_threshold_strict_less_than(self):
        inp = ClassificationInput(artifact_types=("browser_history",))
        # confidence 1.0: threshold 1.0 → NENÍ revize (1.0 < 1.0 je False)
        assert classify(inp, threshold=1.0).needs_review is False
        assert classify(inp).needs_review is False

    def test_threshold_validation(self):
        inp = ClassificationInput(artifact_types=("browser_history",))
        for bad in (0, -0.5, 1.5):
            with pytest.raises(ValueError):
                classify(inp, threshold=bad)


class TestHeuristics:
    """Soubory bez parser artefaktů — extenze/signatura (kap pod prahem)."""

    def test_document_extension(self):
        c = classify(ClassificationInput(file_name="report.docx", file_extension="docx"))
        assert c.category == "documents_media"
        assert c.confidence == 0.5
        assert c.needs_review is True
        assert any("heuristiky" in r for r in c.reasons)

    def test_media_extension(self):
        c = classify(ClassificationInput(file_name="clip.mp4", file_extension="mp4"))
        assert c.category == "documents_media"
        assert c.confidence == 0.4
        assert c.needs_review is True

    def test_signature_beats_extension(self):
        """Binární signatura evtx má přednost nad extenzí .dat."""
        c = classify(
            ClassificationInput(
                file_name="System.dat",
                file_extension="dat",
                signature_type="evtx",
            )
        )
        assert c.category == "system_logs"
        assert c.confidence == 0.5

    def test_signature_sqlite_unknown(self):
        c = classify(
            ClassificationInput(file_name="data.sqlite", signature_type="sqlite")
        )
        assert c.category == UNKNOWN_CATEGORY
        assert c.confidence <= 0.3

    def test_no_signal_at_all(self):
        c = classify(ClassificationInput(file_name="blob.bin"))
        assert c.category == UNKNOWN_CATEGORY
        assert c.confidence == 0.2
        assert c.needs_review is True


class TestDeterminism:
    """AK1 — stejné vstupy → stejné výstupy."""

    def test_same_input_same_output(self):
        inp = ClassificationInput(
            file_name="a.db",
            artifact_types=("chat_message", "contact"),
            entity_kinds=("phone",),
        )
        a, b = classify(inp), classify(inp)
        assert a == b  # frozen dataclass → rovnost po polích
        assert classification_to_dict(a) == classification_to_dict(b)

    def test_permuted_artifact_types_same_result(self):
        base = ClassificationInput(artifact_types=("browser_history", "email_message"))
        flipped = ClassificationInput(
            artifact_types=tuple(reversed(base.artifact_types))
        )
        assert classify(base) == classify(flipped)


class TestExplainability:
    """AK2 — reasons nikdy nejsou prázdné."""

    @pytest.mark.parametrize(
        "inp",
        [
            ClassificationInput(),  # úplně prázdný vstup
            ClassificationInput(file_name="x"),
            ClassificationInput(artifact_types=("parser_error",)),
            ClassificationInput(signature_type="evtx"),
            ClassificationInput(hash_set_hit=True),
            ClassificationInput(artifact_types=("crypto_wallet", "mem_process")),
        ],
    )
    def test_reasons_never_empty(self, inp):
        c = classify(inp)
        assert len(c.reasons) >= 1
        assert all(isinstance(r, str) and r for r in c.reasons)


class TestSerialization:
    def test_to_dict_shape(self):
        c = Classification(
            category="browser",
            confidence=0.95,
            reasons=("r1", "r2"),
            needs_review=False,
            risk_flags=("bad_extension",),
        )
        d = classification_to_dict(c)
        assert set(d) == {"category", "confidence", "reasons", "needs_review", "risk_flags"}
        assert isinstance(d["reasons"], list)
        assert isinstance(d["risk_flags"], list)

    def test_default_threshold_constant(self):
        assert DEFAULT_THRESHOLD == 0.6


if __name__ == "__main__":  # ruční spustitelnost bez pytestu
    raise SystemExit(pytest.main([__file__, "-v"]))
