"""STOPA — Parser Validation Registry (P0 Core, C3).

Deklarativní registry všech parserů: identifikátor, verze, podporované formáty,
známá omezení a referenční datasety. Zdroj pravdy pro verze je pipeline
(``ARTIFACT_EXTRACTORS`` / ``NAME_BASED_EXTRACTORS``) — registry se s ním
synchronizuje v ``build_registry()`` (každý extraktor má záznam a naopak,
verze se shodují).

Čistá logika bez I/O; verze pipeline se načítají lazy (domain → pipeline je
směr jen u konvenční funkce, ne při importu modulu).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class ParserValidation:
    """Validační záznam jednoho parseru (C3 zadání §4.2)."""

    parser_id: str  # např. "win_prefetch" — klíč v pipeline extraktorech
    version: str  # synchronizováno s pipeline (ověřeno build_registry)
    formats: tuple[str, ...]  # podporované formáty/varianty
    limitations: tuple[str, ...] = ()  # známá omezení parseru
    reference_dataset: str | None = None  # cesta do tests/reference_datasets/
    expected_results: dict = field(default_factory=dict)  # očekáv. počty na datasetu
    test_files: tuple[str, ...] = ()  # testové soubory pokrývající parser


class RegistryError(Exception):
    """Nesoulad registry a pipeline (chybějící záznam / rozdílná verze)."""


# ── deklarativní registry — formáty/omezení dle docstringů parserů ─────────

PARSER_VALIDATIONS: dict[str, ParserValidation] = {
    "sqlite": ParserValidation(
        parser_id="sqlite",
        version="",  # doplní build_registry z pipeline
        formats=(
            "Chrome/Edge/Opera (urls+visits, µs od Win epochy)",
            "Firefox (moz_places, ms od Unix epochy)",
            "Apple iMessage chat.db (CFAbsoluteTime od 2001)",
            "Android mmssms.db / calllog.db (unix ms)",
            "DuckDuckGo cookies — Chromium `cookies` schéma (ETAPA B vlna 4)",
            "iOS voicemail.db (`voicemail`, unix s + CFAbsoluteTime) (ETAPA B vlna 4)",
            "iOS Local.sqlite parked car locations (`ZRTVEHICLEEVENTMO`) (ETAPA B vlna 4)",
            "Samsung Voice Recording (voice_recorder DB, epoch ms) (ETAPA B vlna 5)",
            "Chrome/Edge search_terms — omnibox dotazy z lišty (GoogleBarArtifact) (ETAPA B vlna 6)",
        ),
        limitations=(
            "časové epochy se liší dle databáze — detekce podle schématu",
            "smazané řádky vyžadují sqlite_recover (samostatný parser)",
        ),
        test_files=("tests/test_sqlite_extract.py", "tests/test_p11_quality_sqlite.py"),
    ),
    "registry_hive": ParserValidation(
        parser_id="registry_hive",
        version="",
        formats=(
            "Windows registry hive (.regf) — Run/RunOnce, MountedDevices, identita",
            "UserAssist MRU (NTUSER.DAT — spuštěné aplikace / dokumenty) (ETAPA B vlna 4)",
        ),
        limitations=(
            "běží generic + Amcache + ShimCache + Clipboard + SID + UserAssist (sdílená regf magic)",
            "závislost na regipy pro dekompozici klíčů",
        ),
        test_files=("tests/test_registry_extract.py",),
    ),
    "plist": ParserValidation(
        parser_id="plist",
        version="",
        formats=("Apple property list — binární bplist00 i XML"),
        limitations=(
            "datetime listy → artifact plist_date; top-level struktura jen triage",
        ),
        test_files=("tests/test_plist_extract.py",),
    ),
    "lnk": ParserValidation(
        parser_id="lnk",
        version="",
        formats=("MS-LNK [MS-LNK] — hlavička 76 B + volitelné bloky podle flags"),
        limitations=(
            "bloky se čtou jen v kanonickém pořadí dle specifikace",
        ),
        test_files=("tests/test_e6.py",),
    ),
    "win_prefetch": ParserValidation(
        parser_id="win_prefetch",
        version="",
        formats=("MS-PREFETCH (MAM) — verze 30-variant-2 / 31, LZXPRESS payload"),
        limitations=(
            "LZXPRESS Huffman dekomprese (MS-XCA §2.2.4)",
            "starší klasické .pf formáty (pre-MAM) nepodporovány",
        ),
        test_files=("tests/test_e6.py", "tests/test_p11_quality_windows.py"),
    ),
    "evtx": ParserValidation(
        parser_id="evtx",
        version="",
        formats=(
            "EVTX — file magic EVTX, chunk magic CHUN (BinXML payload)",
            "ElfFile varianta — magic ElfFile\\0 / ElfChnk\\0 (ground-truth disk)",
        ),
        limitations=("chunked struktura s BinXML — poškozený chunk = ztráta událostí"),
        test_files=("tests/test_e7.py",),
    ),
    "icloud_messages": ParserValidation(
        parser_id="icloud_messages",
        version="",
        formats=(
            (
                "iCloud Messages export (MessagesInICloud.csv — ve skutečnosti XLSX "
                "nebo delimited text)"
            ),
        ),
        limitations=(
            "detekce podle NÁZVU souboru (AXIOM Hunter) — magic bytes nestačí",
        ),
        test_files=("tests/test_imessage_cloud.py", "tests/test_p11_quality_cloud_exports.py"),
    ),
    "win_jumplist": ParserValidation(
        parser_id="win_jumplist",
        version="",
        formats=(
            ".customDestinations-ms kontejnery (u32 version=2) s vloženými MS-LNK",
        ),
        limitations=(
            "empiricky ověřeno na 16 reálných souborech z Win11 image",
            "detekce name-based — kontejner nemá spolehlivou magic",
        ),
        test_files=("tests/test_e6.py", "tests/test_p11_quality_windows.py"),
    ),
    "win_usn": ParserValidation(
        parser_id="win_usn",
        version="",
        formats=(
            "NTFS USN Journal ($Extend\\$UsnJrnl) — záznamy o změnách FS",
        ),
        limitations=(
            "detekce name-based (header verze 2 kontextově ověřen parserem)",
        ),
        test_files=("tests/test_e7.py", "tests/test_p11_quality_windows.py"),
    ),
    # ── ETAPA B vlna 1 — AXIOM port: email / WiFi / Scheduled Tasks / netstat ──
    "email_mbox": ParserValidation(
        parser_id="email_mbox",
        version="",
        formats=(
            "mbox (Unix mailbox) — více zpráv, oddělené From řádky",
            "EML/MSG — jednotlivé zprávy (RFC 822)",
            "MIME/RFC822 přílohy → email_attachment artifacty (AttachmentExtractor bonus) (ETAPA B vlna 6)",
        ),
        limitations=(
            "detekce name-based (.eml/.mbox) + content check (From header)",
            "Date parsování přes email.utils — neplatné datum → None",
            "Body se truncuje na MAX_BODY_LEN pro detaily",
        ),
        test_files=("tests/test_email_mbox.py", "tests/test_p11_quality_email_mbox.py"),
    ),
    "wifi_wlan": ParserValidation(
        parser_id="wifi_wlan",
        version="",
        formats=(
            "Windows WLAN profile XML (C:\\ProgramData\\Microsoft\\WLAN\\Profile)",
        ),
        limitations=(
            "detekce name-based (*.xml s WLANProfile root elementem)",
            "SSID/autentizace z <network><SSIDConfig> a <authentication>",
        ),
        test_files=("tests/test_win_wlan.py",),
    ),
    "win_schedtask": ParserValidation(
        parser_id="win_schedtask",
        version="",
        formats=(
            "Windows Task Scheduler XML (C:\\Windows\\System32\\Tasks\\*.xml)",
        ),
        limitations=(
            "detekce name-based (*.xml s Task root elementem)",
            "Trigger/Action/Principal z <Triggers>/<Actions>/<Principal>",
        ),
        test_files=("tests/test_win_schedtask.py", "tests/test_p11_quality_windows.py"),
    ),
    "net_connections": ParserValidation(
        parser_id="net_connections",
        version="",
        formats=(
            "Windows netstat -ano textový výstup",
            "Unix ss/netstat -an textový výstup",
        ),
        limitations=(
            "detekce name-based (netstat/connections/sockets) + content check (hlavička)",
            "snapshot bez časového razítka — timestamp=None",
            "limit MAX_CONNECTIONS_PER_FILE=5000 spojení",
        ),
        test_files=("tests/test_net_connections.py",),
    ),
    # ETAPA B vlna 2 — AXIOM port: Google lokální profily + scan outputy + CurrentTabs + MSN
    "google_search_history": ParserValidation(
        parser_id="google_search_history",
        version="",
        formats=(
            "Google Search History JSON (My Activity / Takeout)",
        ),
        limitations=(
            "detekce name-based (my activity/search_history) + content check (JSON pole)",
            "timestamp z time.timestamp (epoch s); neplatné → None",
            "limit MAX_ENTRIES_PER_FILE=5000 záznamů",
        ),
        test_files=("tests/test_google_search_history.py","tests/test_p11_quality_google_full.py", ),
    ),
    "google_location_history": ParserValidation(
        parser_id="google_location_history",
        version="",
        formats=(
            "Google Location History JSON Takeout (latitudeE7/longitudeE7)",
            "Warrant return CSV (Timestamp,Latitude,Longitude,...)",
        ),
        limitations=(
            "detekce name-based (location_history) + content check (JSON/CSV hlavička)",
            "souřadnice E7 (×1e-7) → stupně; epoch ms/s konverze",
            "limit MAX_POINTS_PER_FILE=5000 bodů",
        ),
        test_files=("tests/test_google_location_history.py","tests/test_p11_quality_google_full.py", ),
    ),
    "google_login_history": ParserValidation(
        parser_id="google_login_history",
        version="",
        formats=(
            "Google Login/Sign-in History JSON Takeout (sign-ins.json)",
            "Warrant return CSV (Time,Device Name,IP Address,...)",
        ),
        limitations=(
            "detekce name-based (sign-in/login_history) + content check",
            "epoch s/ms konverze; ISO text → display_time bez timestampu",
            "limit MAX_ENTRIES_PER_FILE=5000 záznamů",
        ),
        test_files=("tests/test_google_login_history.py","tests/test_p11_quality_google_full.py", ),
    ),
    "google_account_info": ParserValidation(
        parser_id="google_account_info",
        version="",
        formats=(
            "Google Account Info JSON (account_info.json / profile)",
        ),
        limitations=(
            "detekce name-based (account_info) + content check (JSON objekt s name/email/phone)",
            "snapshot profilu bez času — timestamp=None",
            "neznámá pole do details.extra",
        ),
        test_files=("tests/test_google_account_info.py","tests/test_p11_quality_google_full.py", ),
    ),
    "mem_scan": ParserValidation(
        parser_id="mem_scan",
        version="",
        formats=(
            "CmdScan textový výstup (paměťové procesy: offset + process + cmdline)",
            "FileScan textový výstup (soubory v paměti: cesty)",
        ),
        limitations=(
            "detekce name-based (cmdscan/filescan) + content check (hlavička tabulky)",
            "paměťový snapshot bez času — timestamp=None",
            "limit MAX_ENTRIES_PER_FILE=5000 záznamů; dedupe cest v filescan",
        ),
        test_files=("tests/test_mem_scan.py", "tests/test_p11_quality_memory.py"),
    ),
    "ddg_current_tabs": ParserValidation(
        parser_id="ddg_current_tabs",
        version="",
        formats=(
            "DuckDuckGo Current Tabs JSON (pole záložek url/title)",
            "Textový export — jeden URL na řádek",
        ),
        limitations=(
            "detekce name-based (current_tabs/ddg/tabs.json) + content check",
            "snapshot otevřených záložek bez času — timestamp=None",
            "limit MAX_TABS_PER_FILE=2000; dedupe URL v textovém formátu",
        ),
        test_files=(
            "tests/test_ddg_current_tabs.py",
            "tests/test_p11_quality_crypto_misc.py",
        ),
    ),
    "msn_messenger": ParserValidation(
        parser_id="msn_messenger",
        version="",
        formats=(
            "MSN/Windows Live Messenger chat log text (.txt export)",
        ),
        limitations=(
            "detekce name-based (msn/messenger/chatlog) + content check (nadpis s verzí)",
            "per-message čas chybí — timestamp=None (jen „Chat started on“ v hlavičce)",
            "limit MAX_MESSAGES_PER_FILE=5000 zpráv",
        ),
        test_files=(
            "tests/test_msn_messenger.py",
            "tests/test_p11_quality_crypto_misc.py",
        ),
    ),
    # ── ETAPA B vlna 3 — AXIOM port: legacy mobile/messenger (Kik, Mail.ru, Bebo, Chatroulette, P2P) ──
    "bebo_chat": ParserValidation(
        parser_id="bebo_chat",
        version="",
        formats=(
            "Bebo Live Chat carving text/JSON (Type + Content)",
        ),
        limitations=(
            "detekce name-based (bebo) + content check (chat/markery záznamů)",
            "carved obsah bez spolehlivého času — timestamp=None",
            "limit MAX_MESSAGES_PER_FILE=5000 zpráv",
        ),
        test_files=("tests/test_bebo_chat.py",),
    ),
    "chatroulette": ParserValidation(
        parser_id="chatroulette",
        version="",
        formats=(
            "Chatroulette video chat carving text ([ts] user said: text / user: text)",
            "JSON pole záznamů (partner/message/timestamp)",
        ),
        limitations=(
            "detekce name-based (chatroulette/cr_chat) + content check",
            "carved obsah — čas jen pokud je v řádku; jinak timestamp=None",
            "limit MAX_MESSAGES_PER_FILE=5000 zpráv",
        ),
        test_files=("tests/test_chatroulette.py",),
    ),
    "mailru_agent": ParserValidation(
        parser_id="mailru_agent",
        version="",
        formats=(
            "Mail.Ru Agent desktop IM — chat log text (zprávy)",
            "Kontakty/knihovna kontaktů text (jméno + identifikátor)",
            "Skupinové konverzace text (skupina + zprávy)",
        ),
        limitations=(
            "detekce name-based (mail.ru/mailru/agent) + content check",
            "typ záznamu (chat/kontakt/skupina) určen podle formátu řádků",
            "limit MAX_MESSAGES_PER_FILE=5000 / MAX_CONTACTS_PER_FILE=10000",
        ),
        test_files=("tests/test_mailru_agent.py",),
    ),
    "limewire_p2p": ParserValidation(
        parser_id="limewire_p2p",
        version="",
        formats=(
            "LimeWire/Limerunner/Luckywire P2P shared files — JSON pole záznamů",
            "Pipe-delimited text (name|size|path|hash[|modified][|accessed])",
        ),
        limitations=(
            "detekce name-based (limewire/limerunner/luckywire) + content check; rodina podle prvního markeru (Limerunner má prioritu)",
            "transfer metadata (downloaded/uploaded by/from/to/on) jen pokud jsou ve vstupu",
            "limit MAX_FILES_PER_FILE=20000 souborů",
        ),
        test_files=("tests/test_limewire_p2p.py",),
    ),
    # ── ETAPA B vlna 4 — AXIOM port: portable-local typy (DDG allowlist, OpenOffice Base) ──
    "allowlisted_websites": ParserValidation(
        parser_id="allowlisted_websites",
        version="",
        formats=(
            "DuckDuckGo Allowlisted Websites JSON (seznam povolených domén / tracker exceptions)",
        ),
        limitations=(
            "detekce name-based (allowlist/allowlisted/tracker_exceptions) + content check (JSON pole/stringy)",
            "snapshot seznamu bez času — timestamp=None",
            "limit MAX_DOMAINS_PER_FILE=5000; dedupe domén",
        ),
        test_files=("tests/test_w4_parsers.py",),
    ),
    "openoffice_base": ParserValidation(
        parser_id="openoffice_base",
        version="",
        formats=(
            "OpenOffice/LibreOffice Base (.odb) — OpenDocument ZIP kontejner s metadata (content.xml/mimetype)",
        ),
        limitations=(
            "detekce name-based (*.odb) + content check (ZIP magic + mimetype/content.xml)",
            "metadata z ODF hlavičky; samotné tabulky DB se neparsují",
            "poškozený ZIP → prázdný výsledek, ne výjimka",
        ),
        test_files=("tests/test_w4_parsers.py",),
    ),
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
        test_files=("tests/test_w8_parsers.py",),
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
        test_files=("tests/test_w9_parsers.py", "tests/test_p11_quality_memory.py"),
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
        test_files=("tests/test_w9_parsers.py", "tests/test_p11_quality_memory.py"),
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
        test_files=("tests/test_w9_parsers.py", "tests/test_p11_quality_memory.py"),
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
        test_files=("tests/test_w9_parsers.py", "tests/test_p11_quality_memory.py"),
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
        test_files=("tests/test_w9_parsers.py", "tests/test_p11_quality_memory.py"),
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
        ),
    ),
    # ── ETAPA B vlna 11 — cloud SNS rodina Twitter/X + Facebook ──────────────
    "twitter_posts": ParserValidation(
        parser_id="twitter_posts",
        version="",
        formats=(
            "Twitter/X Posts JSON (cloud export / warrant return — veřejné i soukromé příspěvky)",
        ),
        limitations=(
            "detekce name-based (twitter marker + post/tweet/status) — SNS pre-pass PŘED basename chainem",
            "příspěvek = sns_post; retweety/odpovědi nesou post_type; limit MAX_POSTS_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w11_parsers.py",
            "tests/test_p11_quality_sns.py",
        ),
    ),
    "twitter_messages": ParserValidation(
        parser_id="twitter_messages",
        version="",
        formats=(
            "Twitter/X Direct Messages JSON (cloud export / warrant return — DM konverzace)",
        ),
        limitations=(
            "detekce name-based (twitter marker + message/direct) — SNS pre-pass PŘED basename chainem",
            "konverzační i plošný formát; limit MAX_MESSAGES_PER_FILE=20000 záznamů",
        ),
        test_files=(
            "tests/test_w11_parsers.py",
            "tests/test_p11_quality_sns.py",
        ),
    ),
    "twitter_users": ParserValidation(
        parser_id="twitter_users",
        version="",
        formats=(
            "Twitter/X Users JSON (cloud export / warrant return — účet + sociální graf)",
        ),
        limitations=(
            "detekce name-based (twitter marker + user/follower) — SNS pre-pass PŘED basename chainem",
            "uživatel = contact (mimetype sns:twitter); limit MAX_USERS_PER_FILE=20000 záznamů",
        ),
        test_files=(
            "tests/test_w11_parsers.py",
            "tests/test_p11_quality_sns.py",
        ),
    ),
    "facebook_wr": ParserValidation(
        parser_id="facebook_wr",
        version="",
        formats=(
            "Facebook Warrant Return JSON (cloud export — Messenger/přátelé/timeline/profil)",
        ),
        limitations=(
            "detekce name-based (facebook marker) — SNS pre-pass PŘED basename chainem",
            "auto-detekce sekcí podle struktury payloadu; zprávy = chat_message, přátelé/profil = contact,",
            "timeline = sns_post",
        ),
        test_files=(
            "tests/test_w11_parsers.py",
            "tests/test_p11_quality_sns.py",
        ),
    ),
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
        ),
    ),
    # ── ETAPA B vlna 15 — AXIOM port: SIM TPDU phonebook (F1.6) ──
    "sim_tpdu": ParserValidation(
        parser_id="sim_tpdu",
        version="",
        formats=(
            "SIM TPDU phonebook textový export (AT+CPBR dump / CSV) — kontakty z SIM karty",
        ),
        limitations=(
            "detekce name-based (*.tpdu, *.cpbr, *.simdump, .csv + content check)",
            "kontakt = contact; dedup podle normalizovaného čísla; limit MAX_CONTACTS=500",
        ),
        test_files=("tests/test_sim_tpdu.py",),
    ),
    # K2 — crypto forensics (wallets, exchange CSV, content scan)
    "crypto_extract": ParserValidation(
        parser_id="crypto_extract",
        version="",
        formats=(
            "Electrum wallet JSON (3.x/4.x keystore + legacy ≤2.x)",
            "MetaMask vault JSON (AES-128-CTR, scrypt/pbkdf2-sha256 KDF)",
            "exchange CSV exporty (Binance deposits/withdrawals/trades, Coinbase transactions/balance, Kraken trades/funds)",
            "K1 content scan — vestěné klíče/seedy/adresy/transakční refy v libovolném textu",
        ),
        limitations=(
            "PII guard: seed slova a privátní klíče jen jako SHA-256 fingerprint (spec §7)",
            "MetaMask bez hesla → struktura (decrypted=False), účty až s heslem",
            "K1 content scan: text do 4 MiB; exchange záznamy strop 20 000/soubor",
            "wallet.dat (Berkeley DB) odložen — K2.1 deferred dle specu",
        ),
        test_files=(
            "tests/test_k2_crypto_wallets.py",
            "tests/test_k2_exchange_csv.py",
            "tests/test_k2_pipeline_integration.py",
            "tests/test_p11_quality_crypto_misc.py",
        ),
    ),
}


def build_registry(versions: dict[str, str] | None = None) -> dict[str, ParserValidation]:
    """Synchronizuje registry s pipeline a vrací kompletní registry.

    ``versions`` — verze parserů (výchozí: lazy import z ``stopa.pipeline``).
    Ověření: každý extraktor v pipeline má záznam v registry a naopak;
    verze se shodují. Nesoulad → :class:`RegistryError`.
    """
    if versions is None:  # lazy — domain bez tvrdé závislosti na pipeline při importu
        from stopa.pipeline import parser_versions

        versions = parser_versions()

    out: dict[str, ParserValidation] = {}
    for pid, pv in PARSER_VALIDATIONS.items():
        if pid not in versions:
            raise RegistryError(f"registry {pid!r} nemá odpovídající extraktor v pipeline")
        out[pid] = pv if pv.version else replace(pv, version=versions[pid])

    for pid, ver in versions.items():
        if pid not in PARSER_VALIDATIONS:
            raise RegistryError(f"pipeline extraktor {pid!r} nemá záznam v registry")
        elif out[pid].version != ver:
            raise RegistryError(
                f"verze parseru {pid!r}: pipeline={ver!r}, registry={out[pid].version!r}"
            )
    return out


def registry_report(registry: dict[str, ParserValidation] | None = None) -> list[dict]:
    """Shrnutí registry pro CLI/GUI — řádky s identitou a validací parserů."""
    if registry is None:
        registry = build_registry()
    return [
        {
            "parser_id": pv.parser_id,
            "version": pv.version,
            "formats": list(pv.formats),
            "limitations": list(pv.limitations),
            "reference_dataset": pv.reference_dataset,
            "test_files": list(pv.test_files),
        }
        for pv in sorted(registry.values(), key=lambda p: p.parser_id)
    ]
