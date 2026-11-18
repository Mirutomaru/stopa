"""ETAPA B vlny 12–14 — cloud-export Microsoft/Amazon, Google II,
Box/Dropbox/Mega, Apple rodina, WhatsApp, Gmail, Maps Labeled Places.

P1-4 vlna E — datová sekce rejstříku; záznamy byte-přesně z monolitu.
"""

from __future__ import annotations

from ._types import ParserValidation

_PART = {
    # ── ETAPA B vlna 12 — cloud-export rodina Microsoft + Amazon ─────────────
    "ms_contacts": ParserValidation(
        parser_id="ms_contacts",
        version="",
        formats=(
            "Microsoft Contacts JSON (cloud export / warrant return — kontakty účtu)",
        ),
        limitations=(
            "detekce name-based (microsoft/outlook marker + contact) — pre-pass PŘED basename chainem",
            "kontakt = contact (mimetype ms:contacts); limit MAX_CONTACTS_PER_FILE=20000 záznamů",
        ),
        test_files=(
            "tests/test_w12_parsers.py",
            "tests/test_p11_quality_ms_amazon.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    "ms_mail_pst": ParserValidation(
        parser_id="ms_mail_pst",
        version="",
        formats=(
            "Microsoft Mail/PST JSON (cloud export / warrant return — e-mailové zprávy)",
        ),
        limitations=(
            "detekce name-based (microsoft/outlook marker + mail/pst/message/email) — pre-pass PŘED basename chainem",
            "zpráva = email_message (mimetype ms:mail); limit MAX_MESSAGES_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w12_parsers.py",
            "tests/test_p11_quality_ms_amazon.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    "ms_teams_conversations": ParserValidation(
        parser_id="ms_teams_conversations",
        version="",
        formats=(
            "Microsoft Teams Conversations JSON (cloud export — konverzace/zprávy)",
        ),
        limitations=(
            "detekce name-based (microsoft/teams marker + conversation/message/chat) — pre-pass PŘED basename chainem",
            "zpráva = chat_message (mimetype ms:teams); limit MAX_MESSAGES_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w12_parsers.py",
            "tests/test_p11_quality_ms_amazon.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    "ms_teams_teams": ParserValidation(
        parser_id="ms_teams_teams",
        version="",
        formats=(
            "Microsoft Teams Teams JSON (cloud export — týmy + členství)",
        ),
        limitations=(
            "detekce name-based (teams.json / ms_teams.json, nebo team + microsoft/teams v cestě) — pre-pass PŘED basename chainem",
            "tým = contact s rolí team_member; členství se agreguje do details",
        ),
        test_files=(
            "tests/test_w12_parsers.py",
            "tests/test_p11_quality_ms_amazon.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    "ms_outlook_calendar": ParserValidation(
        parser_id="ms_outlook_calendar",
        version="",
        formats=(
            "Microsoft Outlook Calendar JSON (cloud export — události/kalendář)",
        ),
        limitations=(
            "detekce name-based (microsoft/outlook marker + calendar/event/appointment) — pre-pass PŘED basename chainem",
            "událost = calendar_event (mimetype ms:calendar); limit MAX_EVENTS_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w12_parsers.py",
            "tests/test_p11_quality_ms_amazon.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    "sharepoint_wr": ParserValidation(
        parser_id="sharepoint_wr",
        version="",
        formats=(
            "SharePoint JSON (cloud export / warrant return — obsah/dokumenty/site pages)",
        ),
        limitations=(
            "detekce name-based (sharepoint marker) — pre-pass PŘED basename chainem",
            "dokument = cloud_file, site page = web_page; limit MAX_ITEMS_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w12_parsers.py",
            "tests/test_p11_quality_ms_amazon.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    "amazon_cloudtrail": ParserValidation(
        parser_id="amazon_cloudtrail",
        version="",
        formats=(
            "Amazon CloudTrail JSON (cloud export — auditní události + Insights anomálie)",
        ),
        limitations=(
            "detekce name-based (cloudtrail marker) — pre-pass PŘED basename chainem",
            "událost = event_log_entry (mimetype aws:cloudtrail); limit MAX_EVENTS_PER_FILE=20000 záznamů",
        ),
        test_files=(
            "tests/test_w12_parsers.py",
            "tests/test_p11_quality_ms_amazon.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    "amazon_ec2_s3": ParserValidation(
        parser_id="amazon_ec2_s3",
        version="",
        formats=(
            "Amazon EC2/S3 JSON (cloud export — instance + S3 objekty, auto-detekce formátu)",
        ),
        limitations=(
            "detekce name-based (amazon/aws marker + ec2/s3/instance/bucket) — pre-pass PŘED basename chainem",
            "instance = cloud_instance (aws:ec2), S3 objekt = cloud_file (aws:s3); limit MAX_ITEMS_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w12_parsers.py",
            "tests/test_p11_quality_ms_amazon.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    # ETAPA B vlna 13 — cloud-export rodina Google II + Box/Dropbox/Mega
    "google_calendar_events": ParserValidation(
        parser_id="google_calendar_events",
        version="",
        formats=(
            "Google Calendar Events JSON (Takeout / warrant return — události s start/end, organizátorem a účastníky)",
        ),
        limitations=(
            "detekce name-based (google/takeout marker + calendar/event) — pre-pass PŘED basename chainem",
            "událost = calendar_event; limit MAX_ITEMS_PER_FILE=5000 záznamů",
        ),
        test_files=("tests/test_w13_parsers.py","tests/test_p11_quality_google_full.py", ),
    ),
    "google_keep_tasks": ParserValidation(
        parser_id="google_keep_tasks",
        version="",
        formats=(
            "Google Keep Notes + Tasks JSON (Takeout / warrant return — poznámky a úkoly)",
        ),
        limitations=(
            "detekce name-based (google/takeout marker + keep/task/note) — pre-pass PŘED basename chainem",
            "poznámka/úkol = document_metadata (kind=keep_note|task); limit MAX_ITEMS_PER_FILE=5000 záznamů",
        ),
        test_files=("tests/test_w13_parsers.py","tests/test_p11_quality_google_full.py", ),
    ),
    "box_cloud": ParserValidation(
        parser_id="box_cloud",
        version="",
        formats=(
            "Box Cloud JSON (cloud export — soubory, složky a audit/enterprise eventy)",
        ),
        limitations=(
            "detekce name-based (box marker + file/folder/event) — pre-pass PŘED basename chainem",
            "soubor/složka = document_metadata (kind=file|folder), event = kind=event s akcí; limit MAX_ITEMS_PER_FILE=5000 záznamů",
        ),
        test_files=("tests/test_w13_parsers.py", "tests/test_p11_quality_cloud_exports.py"),
    ),
    "dropbox_mega": ParserValidation(
        parser_id="dropbox_mega",
        version="",
        formats=(
            "Dropbox + Mega Cloud JSON (cloud export — soubory a složky, auto-detekce provideru)",
        ),
        limitations=(
            "detekce name-based (dropbox/mega marker) — pre-pass PŘED basename chainem",
            "soubor/složka = document_metadata (provider=dropbox|mega); limit MAX_ITEMS_PER_FILE=5000 záznamů",
        ),
        test_files=("tests/test_w13_parsers.py", "tests/test_p11_quality_cloud_exports.py"),
    ),
    # ETAPA B vlna 14 — dokončení cloud-export: Apple rodina + Google 2025 WR + WhatsApp
    # + generic cloud metadata + Gmail Messages + Maps Labeled Places
    "apple_cloud": ParserValidation(
        parser_id="apple_cloud",
        version="",
        formats=(
            "Apple Cloud JSON (cloud export — kontakty, keychain, e-mail, fotky a zálohy; auto-detekce podtypu)",
        ),
        limitations=(
            "detekce name-based (apple/icloud marker) — pre-pass PŘED basename chainem",
            "podtyp = contact|keychain|mail|photo|backup (auto-detekce); limit MAX_ITEMS_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w14_parsers.py",
            "tests/test_p11_quality_cloud_warrant.py",
            "tests/test_p11_quality_capstone.py",
        ),
    ),
    "google_2025_wr": ParserValidation(
        parser_id="google_2025_wr",
        version="",
        formats=(
            "Google 2025 Warrant Return JSON (AccessLogDevices + AccountTargetAssociation + Calls)",
        ),
        limitations=(
            "detekce name-based (accesslog/targetassoc/google+call) — pre-pass PŘED basename chainem",
            "podtyp = access_log|target_assoc|call (auto-detekce); limit MAX_ITEMS_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w14_parsers.py",
            "tests/test_p11_quality_cloud_warrant.py",
            "tests/test_p11_quality_google_rest.py",
        ),
    ),
    "whatsapp_cloud": ParserValidation(
        parser_id="whatsapp_cloud",
        version="",
        formats=(
            "WhatsApp Cloud JSON (cloud export — chaty a zálohy; auto-detekce podtypu)",
        ),
        limitations=(
            "detekce name-based (whatsapp marker) — pre-pass PŘED basename chainem",
            "podtyp = chat|backup (auto-detekce); limit MAX_ITEMS_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w14_parsers.py",
            "tests/test_p11_quality_cloud_warrant.py",
            "tests/test_p11_quality_capstone.py",
        ),
    ),
    "cloud_generic": ParserValidation(
        parser_id="cloud_generic",
        version="",
        formats=(
            "Generic Cloud Metadata JSON (AccountsInfo + ConnectedApps + RecentDevices + Timeline + Passwords + AndroidBackups + AzureVM)",
        ),
        limitations=(
            "detekce name-based (cloud marker + klíčové slovo) — pre-pass POSLEDNÍ (nejobecnější)",
            "podtyp = accounts|apps|devices|timeline|passwords|android_backup|azure_vm; limit MAX_ITEMS_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w14_parsers.py",
            "tests/test_p11_quality_cloud_warrant.py",
            "tests/test_p11_quality_cloud_exports.py",
        ),
    ),
    "gmail_messages": ParserValidation(
        parser_id="gmail_messages",
        version="",
        formats=(
            "Gmail Messages JSON (cloud export — e-mailové zprávy s odesílatelem/příjemcem/tématem)",
        ),
        limitations=(
            "detekce name-based (gmail marker) — pre-pass PŘED basename chainem",
            "zpráva = email_message; limit MAX_ITEMS_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w14_parsers.py",
            "tests/test_p11_quality_cloud_warrant.py",
            "tests/test_p11_quality_capstone.py",
        ),
    ),
    "maps_labeled_places": ParserValidation(
        parser_id="maps_labeled_places",
        version="",
        formats=(
            "Google Maps Labeled Places Warrant Return JSON (označená místa s label + souřadnicemi)",
        ),
        limitations=(
            "detekce name-based (maps marker + labeled/place) — pre-pass PŘED basename chainem",
            "místo = location_point (label + lat/lon); limit MAX_ITEMS_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w14_parsers.py",
            "tests/test_p11_quality_cloud_warrant.py",
            "tests/test_p11_quality_capstone.py",
        ),
    ),
}
