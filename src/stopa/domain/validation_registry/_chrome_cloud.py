"""ETAPA B vlny 7–8 — Chrome Bookmarks/History/Autofill/prefs/sync, Contacts,
Skype WR, cloud drive soubory, Google Voice WR, drivers.

P1-4 vlna E — datová sekce rejstříku; záznamy byte-přesně z monolitu.
"""

from __future__ import annotations

from ._types import ParserValidation

_PART = {
    # ── ETAPA B vlna 7 — AXIOM port: Chrome Bookmarks/History/Autofill + Contacts + Skype WR ──
    "chrome_bookmarks": ParserValidation(
        parser_id="chrome_bookmarks",
        version="",
        formats=(
            "Chrome Bookmarks JSON (Takeout / warrant return, roots/date_added µs od 1601)",
        ),
        limitations=(
            "detekce name-based (bookmark/chrome_bookmark) + content check (JSON s roots/bookmark_bar)",
            "date_added = µs od Windows epochy 1601; rekurzivní walk přes roots",
            "limit MAX_BOOKMARKS_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w7_parsers.py",
            "tests/test_p11_quality_chrome_skype.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    "chrome_history_wr": ParserValidation(
        parser_id="chrome_history_wr",
        version="",
        formats=(
            "Chrome History warrant return JSON (pole návštěv, visit_time µs od 1601)",
        ),
        limitations=(
            "detekce name-based (chrome_history/history) + content check (JSON s visit_time/url)",
            "visit_time = µs od Windows epochy 1601; artifact_type=browser_history",
            "limit MAX_ENTRIES_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w7_parsers.py",
            "tests/test_p11_quality_chrome_skype.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    "contacts_wr": ParserValidation(
        parser_id="contacts_wr",
        version="",
        formats=(
            "Google Contacts Takeout / warrant return JSON (name/emails/phoneNumbers)",
        ),
        limitations=(
            "detekce name-based (contact/google_contact) + content check (JSON s givenName/emails)",
            "Takeout formát = pole stringů pro jména; People API tolerantně",
            "limit MAX_CONTACTS_PER_FILE=10000 záznamů",
        ),
        test_files=(
            "tests/test_w7_parsers.py",
            "tests/test_p11_quality_chrome_skype.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    "chrome_autofill": ParserValidation(
        parser_id="chrome_autofill",
        version="",
        formats=(
            "Chrome Autofill / Contact Info warrant return JSON (name/email/phoneNumber/address)",
        ),
        limitations=(
            "detekce name-based (autofill/contact_info) + content check (JSON s autofill klíči)",
            "prázdné záznamy (bez jména i e-mailu) se vynechávají",
            "limit MAX_ENTRIES_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w7_parsers.py",
            "tests/test_p11_quality_chrome_skype.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    "skype_warrant": ParserValidation(
        parser_id="skype_warrant",
        version="",
        formats=(
            "Skype warrant return JSON (AccountDetails/ChatHistory/ConnectionHistory/Contacts)",
        ),
        limitations=(
            "detekce name-based (skype) + content check (msnId/conversationId/composetime)",
            "auto-detekce subtypu podle obsahu; chat→messenger_message, contacts→contact",
            "čas ISO 8601 / epoch s/ms tolerantně; limit MAX_ENTRIES_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w7_parsers.py",
            "tests/test_p11_quality_chrome_skype.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    # ── ETAPA B vlna 8 — AXIOM port: Chrome prefs/sync + cloud drive soubory + Google Voice WR + drivers ──
    "chrome_preferences": ParserValidation(
        parser_id="chrome_preferences",
        version="",
        formats=(
            "Chrome Preferences JSON (profilový export — extensions.settings, default_search_provider_data, sync)",
        ),
        limitations=(
            "detekce name-based (preferences/chrome_prefs/secure_pref) + content check (extensions/account_info/sync)",
            "extensions→browser_extension; search provider + sync settings→browser_setting",
            "snapshot konfigurace bez času — timestamp=None; limit MAX_EXTENSIONS_PER_FILE=2000",
        ),
        test_files=("tests/test_w8_parsers.py", "tests/test_p11_quality_syscore.py"),
    ),
    "cloud_drive_files": ParserValidation(
        parser_id="cloud_drive_files",
        version="",
        formats=(
            "Cloud Drive soubory JSON (Google Drive / OneDrive / Apple Drive — warrant return / Takeout)",
        ),
        limitations=(
            "detekce name-based (drive/onedrive/apple_drive) + content check; PO drive_activity (specifický)",
            "provider auto-detekován podle markerů; verze souboru do details.versions",
            "čas ISO 8601 / epoch s/ms tolerantně; limit MAX_FILES_PER_FILE=5000 záznamů",
        ),
        test_files=("tests/test_w8_parsers.py", "tests/test_p11_quality_cloud_exports.py"),
    ),
    "google_voice_wr": ParserValidation(
        parser_id="google_voice_wr",
        version="",
        formats=(
            "Google Voice warrant return JSON (Texts/Voicemail/ContactsMetadata/SubscriberInformation)",
        ),
        limitations=(
            "detekce name-based (voice/voicemail/gvoice) + content check; PO ios_voicemail (.db) a samsung recording",
            "auto-detekce subtypu: sms→sms_message, voicemail→voicemail, contacts→contact, subscriber→google_account",
            "čas epoch ms/s tolerantně; limit MAX_ENTRIES_PER_FILE=5000 záznamů",
        ),
        test_files=("tests/test_w8_parsers.py","tests/test_p11_quality_google_full.py", ),
    ),
    "win_drivers": ParserValidation(
        parser_id="win_drivers",
        version="",
        formats=(
            "Windows drivers JSON (live forensics / paměťový dump — načtené ovladače)",
        ),
        limitations=(
            "detekce name-based (driver/drivers) + content check (baseAddress/driverName)",
            "adresa normalizována na hex; nesignovaný driver → anomaly flag unsigned_driver",
            "snapshot paměti bez času — timestamp=None; limit MAX_DRIVERS_PER_FILE=2000 záznamů",
        ),
        test_files=("tests/test_w8_parsers.py", "tests/test_p11_quality_windows.py"),
    ),
    "mem_processes": ParserValidation(
        parser_id="mem_processes",
        version="",
        formats=(
            "Memory processes JSON (live forensics / paměťový dump — ProcessList/Processes/ProcessScan/PsxView)",
        ),
        limitations=(
            "detekce name-based (processlist/psxview/mem_process) + content check; PŘED netstatem",
            "pid/name/commandline tolerantně; snapshot paměti bez času — timestamp=None",
            "limit MAX_PROCESSES_PER_FILE=5000 záznamů",
        ),
        test_files=("tests/test_w9_parsers.py", "tests/test_p11_quality_memory.py", "tests/test_p11_quality_locale.py"),
    ),
    "mem_network": ParserValidation(
        parser_id="mem_network",
        version="",
        formats=(
            "Memory network connections JSON (live forensics / paměťový dump — Sockets/OpenConnections/NetworkConnections)",
        ),
        limitations=(
            "detekce name-based (open_connections/network_connections/connscan/sockets) + content check; PŘED netstatem",
            "pid/localAddress/remoteAddress/state tolerantně; snapshot paměti bez času — timestamp=None",
            "limit MAX_CONNECTIONS_PER_FILE=5000 záznamů",
        ),
        test_files=("tests/test_w9_parsers.py", "tests/test_p11_quality_memory.py", "tests/test_p11_quality_locale.py"),
    ),
    "mem_handles": ParserValidation(
        parser_id="mem_handles",
        version="",
        formats=(
            "Memory handles JSON (live forensics / paměťový dump — Handles/OpenHandles)",
        ),
        limitations=(
            "detekce name-based (open_handles/handles) + content check; PŘED netstatem a mem_processes",
            "handle value normalizován na hex string; snapshot paměti bez času — timestamp=None",
            "limit MAX_HANDLES_PER_FILE=5000 záznamů",
        ),
        test_files=("tests/test_w9_parsers.py", "tests/test_p11_quality_memory.py", "tests/test_p11_quality_locale.py"),
    ),
    "mem_modules": ParserValidation(
        parser_id="mem_modules",
        version="",
        formats=(
            "Memory modules JSON (live forensics / paměťový dump — ModScan/Malfind)",
        ),
        limitations=(
            "detekce name-based (modscan/malfind/mem_module) + content check; PŘED netstatem a mem_processes",
            "adresa normalizována na hex; inLdrList=false → anomaly flag hidden_module (DLL injection)",
            "snapshot paměti bez času — timestamp=None; limit MAX_MODULES_PER_FILE=5000 záznamů",
        ),
        test_files=("tests/test_w9_parsers.py", "tests/test_p11_quality_memory.py", "tests/test_p11_quality_locale.py"),
    ),
    "mem_hooks": ParserValidation(
        parser_id="mem_hooks",
        version="",
        formats=(
            "Memory API hooks/callbacks JSON (live forensics / paměťový dump — ApiHooks/Callbacks/ExecutiveObjectCallbacks)",
        ),
        limitations=(
            "detekce name-based (api_hooks/apishot/callbacks/executive_callbacks/mem_hook) + content check; PŘED netstatem",
            "callbackAddress normalizován na hex; snapshot paměti bez času — timestamp=None",
            "limit MAX_HOOKS_PER_FILE=5000 záznamů",
        ),
        test_files=("tests/test_w9_parsers.py", "tests/test_p11_quality_memory.py", "tests/test_p11_quality_locale.py"),
    ),
    "instagram_messages": ParserValidation(
        parser_id="instagram_messages",
        version="",
        formats=(
            "Instagram Direct Messages JSON (cloud export / warrant return — DM konverzace)",
        ),
        limitations=(
            "detekce name-based (instagram marker + message/direct) — SNS pre-pass PŘED basename chainem",
            "konverzační i plošný formát; limit MAX_MESSAGES_PER_FILE=20000 záznamů",
        ),
        test_files=(
            "tests/test_w10_parsers.py",
            "tests/test_p11_quality_instagram_snapchat.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    "instagram_posts": ParserValidation(
        parser_id="instagram_posts",
        version="",
        formats=(
            "Instagram Posts/Media/Photos/Stories/Comments JSON (cloud export — obsah účtu)",
        ),
        limitations=(
            "detekce name-based (instagram marker + post/media/photo/story/comment) — SNS pre-pass",
            "příspěvek = sns_post, komentář = sns_comment; limit MAX_POSTS_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w10_parsers.py",
            "tests/test_p11_quality_instagram_snapchat.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    "instagram_account": ParserValidation(
        parser_id="instagram_account",
        version="",
        formats=(
            "Instagram Account Actions/History/Followers JSON (cloud export — akce účtu + sociální graf)",
        ),
        limitations=(
            "detekce name-based (instagram marker + account/follower) — SNS pre-pass",
            "akce = event_log_entry, follower/following = contact (mimetype sns:instagram)",
            "limit MAX_EVENTS_PER_FILE=20000 záznamů",
        ),
        test_files=(
            "tests/test_w10_parsers.py",
            "tests/test_p11_quality_instagram_snapchat.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    "snapchat_wr": ParserValidation(
        parser_id="snapchat_wr",
        version="",
        formats=(
            "Snapchat Warrant Return JSON (cloud export — zprávy/přátelé/geolokace/IP historie/účet)",
        ),
        limitations=(
            "detekce name-based (snapchat marker) — SNS pre-pass PŘED basename chainem",
            "auto-detekce sekcí podle struktury payloadu; zprávy = chat_message, přátelé = contact,",
            "geolokace = location_data, IP historie = network_connection",
        ),
        test_files=(
            "tests/test_w10_parsers.py",
            "tests/test_p11_quality_instagram_snapchat.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
}
