"""ETAPA B vlny 1–4 — AXIOM port: email/WiFi/tasks/netstat, Google profily,
legacy mobile/messenger, portable-local typy.

P1-4 vlna E — datová sekce rejstříku; záznamy byte-přesně z monolitu.
"""

from __future__ import annotations

from ._types import ParserValidation

_PART = {
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
        test_files=("tests/test_win_wlan.py", "tests/test_p11_quality_chat_net.py"),
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
        test_files=("tests/test_net_connections.py", "tests/test_p11_quality_chat_net.py"),
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
        test_files=("tests/test_mem_scan.py", "tests/test_p11_quality_memory.py", "tests/test_p11_quality_locale.py"),
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
        test_files=("tests/test_bebo_chat.py", "tests/test_p11_quality_chat_net.py"),
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
        test_files=("tests/test_chatroulette.py", "tests/test_p11_quality_chat_net.py"),
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
        test_files=("tests/test_mailru_agent.py", "tests/test_p11_quality_capstone.py"),
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
        test_files=("tests/test_limewire_p2p.py", "tests/test_p11_quality_chat_net.py"),
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
        test_files=("tests/test_w4_parsers.py", "tests/test_p11_quality_capstone.py"),
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
        test_files=("tests/test_w4_parsers.py", "tests/test_p11_quality_capstone.py"),
    ),
}
