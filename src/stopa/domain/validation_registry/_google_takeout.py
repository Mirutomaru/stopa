"""ETAPA B vlny 5–6 — Google Takeout rodina + Drive activity, Google Photos,
Mail Message Information (WarrantReturn).

P1-4 vlna E — datová sekce rejstříku; záznamy byte-přesně z monolitu.
"""

from __future__ import annotations

from ._types import ParserValidation

_PART = {
    # ── ETAPA B vlna 5 — AXIOM port: Google Takeout rodina + Drive activity ──
    "google_aggregated_activities": ParserValidation(
        parser_id="google_aggregated_activities",
        version="",
        formats=(
            "Google Aggregated Activities JSON (My Activity / Takeout, denní agregace)",
        ),
        limitations=(
            "detekce name-based (aggregated_activities) + content check (JSON pole)",
            "timestamp z ISO 8601; neplatné → None",
            "limit MAX_ENTRIES_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w5_parsers.py",
            "tests/test_p11_quality_google_takeout.py",
            "tests/test_p11_quality_google_rest.py",
        ),
    ),
    "google_identity_sessions": ParserValidation(
        parser_id="google_identity_sessions",
        version="",
        formats=(
            "Google Identity Sessions JSON (Takeout, přihlašovací seance)",
        ),
        limitations=(
            "detekce name-based (identity_sessions) + content check (JSON pole)",
            "timestamp z ISO 8601; neplatné → None",
            "limit MAX_ENTRIES_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w5_parsers.py",
            "tests/test_p11_quality_google_takeout.py",
            "tests/test_p11_quality_google_rest.py",
        ),
    ),
    "google_maps_activity": ParserValidation(
        parser_id="google_maps_activity",
        version="",
        formats=(
            "Google Maps Activity / semantic location history JSON (placeVisit + activitySegment)",
        ),
        limitations=(
            "detekce name-based (maps_activity/location_history_semantic) + content check (JSON objekt)",
            "souřadnice E7 (×1e-7) → stupně; epoch ms/s konverze",
            "limit MAX_POINTS_PER_FILE=5000 bodů",
        ),
        test_files=(
            "tests/test_w5_parsers.py",
            "tests/test_p11_quality_google_takeout.py",
            "tests/test_p11_quality_google_rest.py",
        ),
    ),
    "google_chat_family": ParserValidation(
        parser_id="google_chat_family",
        version="",
        formats=(
            "Google IM chat rodina (Chat/Hangouts/Plus/Talk) — Takeout Hangouts JSON",
        ),
        limitations=(
            "detekce name-based (hangouts/google_chat/plus_chat/talk) + content check (JSON s conversations)",
            "timestamp = webkit µs od epochy → s; text zpojený ze segmentů (type TEXT)",
            "limit MAX_MESSAGES_PER_FILE=5000 zpráv",
        ),
        test_files=(
            "tests/test_w5_parsers.py",
            "tests/test_p11_quality_google_takeout.py",
            "tests/test_p11_quality_google_rest.py",
        ),
    ),
    "google_account_change_history": ParserValidation(
        parser_id="google_account_change_history",
        version="",
        formats=(
            "Google Account Change History JSON (události změny účtu)",
        ),
        limitations=(
            "detekce name-based (account_change_history) + content check (JSON pole)",
            "timestamp z ISO 8601 / epoch s/ms; neplatné → None",
            "limit MAX_ENTRIES_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w5_parsers.py",
            "tests/test_p11_quality_google_takeout.py",
            "tests/test_p11_quality_google_rest.py",
        ),
    ),
    "google_linked_devices": ParserValidation(
        parser_id="google_linked_devices",
        version="",
        formats=(
            "Google Linked Devices JSON (propojená zařízení)",
        ),
        limitations=(
            "detekce name-based (devices/linked_devices) + content check (JSON pole)",
            "timestamp z ISO 8601 / epoch s/ms; neplatné → None",
            "limit MAX_ENTRIES_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w5_parsers.py",
            "tests/test_p11_quality_google_takeout.py",
            "tests/test_p11_quality_google_rest.py",
        ),
    ),
    "google_export_summary": ParserValidation(
        parser_id="google_export_summary",
        version="",
        formats=(
            "Google Takeout Export Summary JSON (metadata exportu)",
        ),
        limitations=(
            "detekce name-based (export_summary) + content check (JSON objekt)",
            "jeden snapshot = jeden artifact; timestamp z createdTime",
        ),
        test_files=(
            "tests/test_w5_parsers.py",
            "tests/test_p11_quality_google_takeout.py",
            "tests/test_p11_quality_google_rest.py",
        ),
    ),
    "drive_activity": ParserValidation(
        parser_id="drive_activity",
        version="",
        formats=(
            "Google Drive Activity JSON (log aktivit souborů)",
        ),
        limitations=(
            "detekce name-based (drive_activity/google_drive) + content check (JSON pole)",
            "timestamp z ISO 8601 / epoch s/ms; neplatné → None",
            "limit MAX_ENTRIES_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w5_parsers.py",
            "tests/test_p11_quality_google_takeout.py",
            "tests/test_p11_quality_capstone.py",
        ),
    ),
    # ── ETAPA B vlna 6 — AXIOM port: Google Photos + Mail Message Information (WarrantReturn) ──
    "google_photos": ParserValidation(
        parser_id="google_photos",
        version="",
        formats=(
            "Google Photos metadata JSON (Takeout / warrant return sidecar, photoTakenTime/geoData)",
        ),
        limitations=(
            "detekce name-based (photos/google_photos) + content check (JSON s photo klíči)",
            "souřadnice E7 (×1e-7) → stupně; ISO 8601 / epoch s/ms konverze",
            "limit MAX_ENTRIES_PER_FILE=5000 záznamů",
        ),
        test_files=("tests/test_w6_parsers.py", "tests/test_p11_quality_google_rest.py"),
    ),
    "google_mail_info": ParserValidation(
        parser_id="google_mail_info",
        version="",
        formats=(
            "Google Mail Message Information JSON (Gmail Takeout / warrant return, threadId/internalDate µs)",
        ),
        limitations=(
            "detekce name-based (gmail/mail_message_information/messages.json) + content check (JSON s mail klíči)",
            "internalDate = µs od Unix epochy; tolerantně i ISO 8601 / s / ms",
            "limit MAX_ENTRIES_PER_FILE=5000 záznamů",
        ),
        test_files=("tests/test_w6_parsers.py", "tests/test_p11_quality_google_rest.py",),
    ),
}
