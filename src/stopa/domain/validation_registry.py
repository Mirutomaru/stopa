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
        test_files=("tests/test_sqlite_extract.py",),
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
        test_files=("tests/test_e6.py",),
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
        test_files=("tests/test_imessage_cloud.py",),
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
        test_files=("tests/test_e6.py",),
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
        test_files=("tests/test_e7.py",),
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
        test_files=("tests/test_email_mbox.py",),
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
        test_files=("tests/test_win_schedtask.py",),
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
        test_files=("tests/test_google_search_history.py",),
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
        test_files=("tests/test_google_location_history.py",),
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
        test_files=("tests/test_google_login_history.py",),
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
        test_files=("tests/test_google_account_info.py",),
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
        test_files=("tests/test_mem_scan.py",),
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
        test_files=("tests/test_ddg_current_tabs.py",),
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
        test_files=("tests/test_msn_messenger.py",),
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
        test_files=("tests/test_w5_parsers.py",),
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
        test_files=("tests/test_w5_parsers.py",),
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
        test_files=("tests/test_w5_parsers.py",),
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
        test_files=("tests/test_w5_parsers.py",),
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
        test_files=("tests/test_w5_parsers.py",),
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
        test_files=("tests/test_w5_parsers.py",),
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
        test_files=("tests/test_w5_parsers.py",),
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
        test_files=("tests/test_w5_parsers.py",),
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
        test_files=("tests/test_w6_parsers.py",),
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
        test_files=("tests/test_w6_parsers.py",),
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
