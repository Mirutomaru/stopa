"""STOPA — AXIOM coverage matrix generator.

Datově klasifikuje všech 237 položek z ``docs/re-axiom/axiom-artifact-extractors.json``
do kategorií podle toho, co STOPA už pokrývá a co je portovatelné:

- **covered**        — STOPA umí (existující parser / artifact_type)
- **portable-local** — lokálně portovatelný (čistý Python, bez cloud API)
- **cloud-export**   — JSON export / warrant return (Google/Microsoft/Twitter/…)
- **memory**         — live forensics (potřebuje paměťový dump)
- **base-class**     — rozhraní / základní třída (ne extraktor jako takový)

Výstup: ``docs/re-axiom/AXIOM_COVERAGE.md`` + ``AXIOM_COVERAGE.json``
+ ``STOPA_COVERAGE_MATRIX.csv`` (FÁZE 15 — centrální matice v kořeni).
Deterministický — stejný vstup = stejná matice (žádné časy/ID).
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "re-axiom" / "axiom-artifact-extractors.json"
OUT_MD = ROOT / "docs" / "re-axiom" / "AXIOM_COVERAGE.md"
OUT_JSON = ROOT / "docs" / "re-axiom" / "AXIOM_COVERAGE.json"
OUT_CSV = ROOT / "STOPA_COVERAGE_MATRIX.csv"  # FÁZE 15 — centrální matice v kořeni

# FÁZE 15 stavy implementace (z kategorie portu)
_STATUS_BY_CAT = {
    "covered": ("SUPPORTED", "testováno"),
    "portable-local": ("NOT_SUPPORTED", "plánovaný port (čistý Python)"),
    "cloud-export": ("NOT_SUPPORTED", "čeká na exportní modul (JSON/warrant return)"),
    "memory": ("NOT_SUPPORTED", "live forensics — potřebuje paměťový dump"),
    "base-class": ("DEPRECATED", "rozhraní / základní třída, ne extraktor"),
}

# ── STOPA pokrytí: AXIOM typ → (stav, STOPA mechanismus) ────────────────────
# covered = existující parser; portable-local = první vlna portu.
COVERED: dict[str, str] = {
    "AppleIMessageArtifact": "covered",  # sqlite_extract imessage
    "CallLogsArtifact": "covered",  # sqlite_extract call_log
    "JumpListsArtifact": "covered",  # win_jumplist
    "IeTypedUrlArtifact": "covered",  # browser_history (chrome/firefox)
    "GoogleBrowsingHistoryArtifact": "covered",  # browser_history
    "CloudGoogleChromeBrowserHistoryArtifact": "covered",  # browser_history
    "TimelineArtifact": "covered",  # timeline engine
    "MapArtifact": "covered",  # timeline/map
    "WorldMapArtifact": "covered",  # world map (timeline)
    "MftArtifact": "covered",  # TSK disk image MFT
    "OfficeArtifact": "covered",  # OOXML document
    "DocumentMetadataExtractor": "covered",  # OOXML metadata
    "ImageInfoArtifact": "covered",  # magic bytes image info
    "MediaMetadataExtractor": "covered",  # media family
    "SamsungContactArtifact": "covered",  # mobile_extract contacts2
    "SamsungMessagesArtifact": "covered",  # mobile_extract sms
    "SamsungConnectionsArtifact": "covered",  # mobile_extract calllog
    "MicrosoftTeamsMessagesArtifact": "covered",  # sqlite generic (teams.db)
    "MicrosoftTeamsMessagesBaseArtifact": "covered",
    "MicrosoftTeamsMessagesComputerArtifact": "covered",
    # ETAPA B vlna 1 — port AXIOM extraktorů (6 nových parserů, testováno)
    "CloudMboxEmailArtifact": "covered",  # email_mbox
    "OfflineGmailArtifact": "covered",  # email_mbox
    "WiFiLocationsArtifact": "covered",  # win_wlan
    "ScheduledTasksArtifact": "covered",  # win_schedtask
    "ClipboardArtifact": "covered",  # win_clipboard (sekundární registry průchod)
    "ConnscanArtifact": "covered",  # net_connections
    "NetScanArtifact": "covered",  # net_connections
    "SockscanArtifact": "covered",  # net_connections
    "GetsidsArtifact": "covered",  # win_sids (sekundární registry průchod)
    "SidsArtifact": "covered",  # win_sids
    "UserSidsArtifact": "covered",  # win_sids
    # ETAPA B vlna 2 — port AXIOM extraktorů (7 nových parserů, testováno)
    "GoogleSearchHistoryArtifact": "covered",  # google_search_history
    "CloudGoogleLocationHistoryArtifact": "covered",  # google_location_history (warrant return)
    "GoogleLocationHistoryArtifact": "covered",  # google_location_history
    "GoogleLoginHistoryArtifact": "covered",  # google_login_history
    "GoogleAccountInfoArtifact": "covered",  # google_account_info
    "CmdScanArtifact": "covered",  # mem_scan (textový výstup)
    "FileScanArtifact": "covered",  # mem_scan (textový výstup)
    "CurrentTabsArtifact": "covered",  # ddg_current_tabs
    "MSNArtifact": "covered",  # msn_messenger
    # ETAPA B vlna 3 — port AXIOM extraktorů (5 nových parserů, testováno)
    "KikLocalUserExtractor": "covered",  # kik_messenger (SQLite dispatch chain)
    "MailRuChatArtifact": "covered",  # mailru_agent
    "MailRuContactArtifact": "covered",  # mailru_agent
    "MailRuGroupArtifact": "covered",  # mailru_agent
    "BeboArtifact": "covered",  # bebo_chat
    "ChatrouletteArtifact": "covered",  # chatroulette
    "LimewireArtifact": "covered",  # limewire_p2p
    "LimerunnerArtifact": "covered",  # limewire_p2p
    "LuckywireArtifact": "covered",  # limewire_p2p
    # ETAPA B vlna 4 — port AXIOM extraktorů (6 nových parserů, testováno)
    "DuckDuckGoCookiesArtifact": "covered",  # ddg_cookies (Chromium cookies SQLite)
    "AllowlistedWebSitesArtifact": "covered",  # allowlisted_websites (DDG JSON)
    "OpenOfficeBaseArtifact": "covered",  # openoffice_base (.odb ZIP kontejner)
    "ParkedCarLocationsArtifact": "covered",  # parked_car_locations (iOS Local.sqlite)
    "VoiceMailArtifact": "covered",  # ios_voicemail (voicemail.db)
    # ETAPA B vlna 5 — port AXIOM extraktorů (6 nových parserů, testováno)
    "GoogleAggregatedActivitiesArtifact": "covered",  # google_aggregated_activities (My Activity JSON)
    "GoogleAggregatedActivitiesIdentitySessionsArtifact": "covered",  # google_aggregated_activities (identity sessions)
    "GoogleMapsActivityArtifact": "covered",  # google_maps_activity (semantic location history)
    "GoogleChatArtifact": "covered",  # google_chat_family (Takeout JSON)
    "GoogleHangoutsArtifact": "covered",  # google_chat_family (Takeout JSON)
    "GooglePlusChatArtifact": "covered",  # google_chat_family (Takeout JSON)
    "GoogleTalkArtifact": "covered",  # google_chat_family (Takeout JSON)
    "GoogleAccountChangeHistoryArtifact": "covered",  # google_account_meta (change history JSON)
    "GoogleDevicesArtifact": "covered",  # google_account_meta (linked devices JSON)
    "GoogleExportSummaryArtifact": "covered",  # google_account_meta (export summary JSON)
    "DriveActivityArtifact": "covered",  # drive_activity (Drive activity log JSON)
    "SamsungVoiceRecordingArtifact": "covered",  # samsung_voice_recording (SQLite dispatch chain)
    # ETAPA B vlna 6 — port AXIOM extraktorů (4 nové parsery, testováno)
    "GooglePhotosArtifact": "covered",  # google_photos (Takeout/warrant JSON, photoTakenTime/geoData)
    "GoogleMailMessageInformationArtifact": "covered",  # google_mail_info (Gmail warrant return JSON)
    "GoogleBarArtifact": "covered",  # google_bar (Chrome History search_terms bonus v sqlite_extract)
    "AttachmentExtractor": "covered",  # attachment_extractor (MIME/RFC822 přílohy, bonus v email_mbox)
    # ETAPA B vlna 7 — port AXIOM extraktorů (5 nových parserů, testováno)
    "GoogleChromeBookmarksWarrantReturnArtifact": "covered",  # google_chrome_bookmarks (Bookmarks JSON)
    "CloudGoogleChromeBookmarksArtifact": "covered",  # google_chrome_bookmarks (Bookmarks JSON)
    "GoogleChromeHistoryWarrantReturnArtifact": "covered",  # google_chrome_history_wr (History warrant JSON)
    "GoogleContactsWarrantReturnArtifact": "covered",  # google_contacts_wr (Contacts Takeout/warrant JSON)
    "CloudGoogleContactsArtifact": "covered",  # google_contacts_wr (Contacts Takeout/warrant JSON)
    "GoogleChromeAutofillWarrantReturnArtifact": "covered",  # google_chrome_autofill (Autofill/ContactInfo JSON)
    "GoogleChromeContactInfoWarrantReturnArtifact": "covered",  # google_chrome_autofill (Autofill/ContactInfo JSON)
    "CloudGoogleChromeAutofillArtifact": "covered",  # google_chrome_autofill (Autofill/ContactInfo JSON)
    "SkypeWarrantReturnAccountDetailsArtifact": "covered",  # skype_warrant_return (account details)
    "SkypeWarrantReturnChatHistoryRecordsArtifact": "covered",  # skype_warrant_return (chat history)
    "SkypeWarrantReturnConnectionHistoryArtifact": "covered",  # skype_warrant_return (connection history)
    "SkypeWarrantReturnContactsArtifact": "covered",  # skype_warrant_return (contacts)
    # ETAPA B vlna 8 — port AXIOM extraktorů (4 nové parsery, testováno)
    "CloudGoogleChromeExtensionsArtifact": "covered",  # chrome_preferences (extensions.settings)
    "CloudGoogleChromeExtensionSettingsArtifact": "covered",  # chrome_preferences (extension settings detail)
    "CloudGoogleChromeSearchEnginesArtifact": "covered",  # chrome_preferences (search engines)
    "CloudGoogleChromeSyncSettingsAppSettingsArtifact": "covered",  # chrome_preferences (sync app settings)
    "CloudGoogleChromeSyncSettingsAppsArtifact": "covered",  # chrome_preferences (sync apps)
    "CloudGoogleChromeSyncSettingsPreferencesArtifact": "covered",  # chrome_preferences (sync preferences)
    "CloudDriveFileArtifact": "covered",  # cloud_drive_files (Google Drive soubory)
    "CloudDriveFileVersionArtifact": "covered",  # cloud_drive_files (verze souboru)
    "CloudOneDriveFileArtifact": "covered",  # cloud_drive_files (OneDrive soubory)
    "CloudOneDriveFileVersionArtifact": "covered",  # cloud_drive_files (OneDrive verze)
    "CloudAppleDriveArtifact": "covered",  # cloud_drive_files (Apple Drive)
    "GoogleVoiceTexts2025Artifact": "covered",  # google_voice_wr (SMS texty)
    "GoogleVoicemail2025Artifact": "covered",  # google_voice_wr (hlasové schránky)
    "GoogleVoiceContactsMetadata2026Artifact": "covered",  # google_voice_wr (kontakty)
    "GoogleVoiceSubscriberInformation2026Artifact": "covered",  # google_voice_wr (předplatitel)
    "DriversArtifact": "covered",  # win_drivers (načtené ovladače z paměti)
    # ETAPA B vlna 9 — memory forensics (live forensics / paměťový dump)
    "ProcessListArtifact": "covered",  # mem_processes (seznam procesů)
    "ProcessesArtifact": "covered",  # mem_processes (procesy)
    "ProcessScanArtifact": "covered",  # mem_processes (scan procesů)
    "PsxViewArtifact": "covered",  # mem_processes (EPROCESS vs PEB mismatch)
    "SocketsArtifact": "covered",  # mem_network (sockety)
    "OpenConnectionsArtifact": "covered",  # mem_network (otevřená spojení)
    "NetworkConnectionsArtifact": "covered",  # mem_network (síťová spojení)
    "HandlesArtifact": "covered",  # mem_handles (handlery)
    "OpenHandlesArtifact": "covered",  # mem_handles (otevřené handlery)
    "ModScanArtifact": "covered",  # mem_modules (scan modulů)
    "MalfindArtifact": "covered",  # mem_modules (skryté moduly / DLL injection)
    "ApiHooksArtifact": "covered",  # mem_hooks (API hooky)
    "CallbacksArtifact": "covered",  # mem_hooks (callback funkce)
    "ExecutiveObjectCallbacksArtifact": "covered",  # mem_hooks (executive callbacky)
    # ETAPA B vlna 10 — cloud SNS exporty (Instagram/Snapchat warrant return)
    "InstagramMessagesArtifact": "covered",  # instagram_messages (DM konverzace)
    "CloudInstagramDirectMessagesArtifact": "covered",  # instagram_messages (cloud DM)
    "CloudFacebookInstagramMessagesArtifact": "covered",  # instagram_messages (FB↔IG cross-posting)
    "InstagramDirectSharesArtifact": "covered",  # instagram_messages (sdílená média v DM)
    "CloudInstagramPostsArtifact": "covered",  # instagram_posts (posts/media/stories)
    "CloudInstagramPostsAxiom2Pt1Artifact": "covered",  # instagram_posts (AXIOM 2.1 varianta)
    "InstagramMediaArtifact": "covered",  # instagram_posts (média)
    "InstagramPhotosArtifact": "covered",  # instagram_posts (fotky)
    "InstagramArchivedStoriesArtifact": "covered",  # instagram_posts (archivované stories)
    "InstagramDirectStoriesArtifact": "covered",  # instagram_posts (direct stories)
    "InstagramCommentsArtifact": "covered",  # instagram_posts (komentáře)
    "InstagramAccountActionsArtifact": "covered",  # instagram_account (akce účtu — login/password/device)
    "InstagramAccountHistoryArtifact": "covered",  # instagram_account (historie účtu)
    "InstagramFollowersAndFollowingArtifact": "covered",  # instagram_account (followery/following)
    "SnapchatMessagesWarrantReturnArtifact": "covered",  # snapchat_wr (zprávy WR)
    "SnapchatGroupChatMessagesArtifact": "covered",  # snapchat_wr (skupinové chaty)
    "SnapchatFriendsArtifact": "covered",  # snapchat_wr (přátelé)
    "SnapchatGeolocationArtifact": "covered",  # snapchat_wr (geolokace)
    "SnapchatIpHistoryArtifact": "covered",  # snapchat_wr (IP historie)
    "SnapchatAccountInformationArtifact": "covered",  # snapchat_wr (info o účtu)
}

# base-class / rozhraní — ne extraktor jako takový
BASE_CLASSES = {
    "IArtifact", "ICloudArtifact", "ICustomArtifact", "ILegacyArtifact",
    "IWorldMapArtifact", "SimpleArtifact", "Artifact", "CloudArtifact",
    "CustomArtifact", "LegacyArtifact", "MappedArtifact", "DbArtifact",
    "XmlArtifact", "MessageArtifact", "ChannelArtifact", "LabelArtifact",
    "ServerArtifact", "UserArtifact", "DevicesArtifact", "DllArtifact",
    "MemoryArtifact", "IAttachmentExtractor", "BinaryTextExtractor",
    "EventExtractor", "IconExtractor", "LsaRegistryExtractor",
    "TpduDataExtractor", "IUnifiedLogsExtractor", "ICustomXmlArtifact",
    "ILsaRegistryExtractor", "ITpduDataExtractor", "IContainerEnabledArtifact",
    "CaseAmendingTestArtifact", "MappedLegacyEmailArtifact",
}

# memory / live forensics (Volatility-style) — potřebuje paměťový dump
MEMORY = {
    "ApiHooksArtifact", "CallbacksArtifact", "ExecutiveObjectCallbacksArtifact",
    "MalfindArtifact", "ModScanArtifact", "ProcessListArtifact",
    "ProcessScanArtifact", "ProcessesArtifact", "SocketsArtifact",
    "OpenConnectionsArtifact", "OpenHandlesArtifact", "HandlesArtifact",
    "NetworkConnectionsArtifact", "DriversArtifact", "PsxViewArtifact",
}

# cloud-export / warrant return — JSON export (Google/Microsoft/Twitter/FB/…)
CLOUD_PREFIXES = ("Cloud",)
CLOUD_MARKERS = ("WarrantReturn", "2025", "2026", "Takeout")


def classify(name: str, dll: str) -> tuple[str, str]:
    """Vrátí (kategorie, mechanismus/popis)."""
    if name in COVERED:
        return COVERED[name], _covered_desc(name)
    if name in BASE_CLASSES:
        return "base-class", "rozhraní / základní třída"
    if name in MEMORY:
        return "memory", "live forensics (paměťový dump)"
    # cloud export — prefix Cloud* nebo warrant-return marker
    if any(name.startswith(p) for p in CLOUD_PREFIXES):
        return "cloud-export", "JSON export / warrant return"
    if any(m in name for m in CLOUD_MARKERS):
        return "cloud-export", "warrant return (JSON)"
    # Google* bez Cloud prefixu = lokální profil / takeout
    if name.startswith("Google"):
        return "portable-local", "lokální profil / takeout"
    # Samsung/Kik/MailRu/Bebo/Chatroulette/Limewire — legacy mobile/messenger (sqlite)
    if any(name.startswith(p) for p in ("Samsung", "Kik", "MailRu", "Bebo", "Chatroulette", "Limewire", "Limerunner", "Luckywire")):
        return "portable-local", "legacy mobile / messenger (SQLite)"
    # Instagram/Snapchat lokální (ne Cloud) — sqlite/DB export
    if name.startswith(("Instagram", "Snapchat")):
        return "cloud-export", "JSON/DB export"
    # Audit* / GoogleAccessLog = EVTX event log
    if name.startswith(("Audit", "GoogleAccessLog")):
        return "covered", "EVTX event log (evtx parser)"
    # browser cookies / bookmarks lokální
    if "Cookies" in name or "Bookmarks" in name:
        return "portable-local", "browser cookies/bookmarks"
    # Skype warrant return
    if name.startswith("SkypeWarrantReturn"):
        return "cloud-export", "warrant return (JSON)"
    # default — lokálně portovatelný
    return "portable-local", "lokální parser (čistý Python)"


def _covered_desc(name: str) -> str:
    m = {
        "AppleIMessageArtifact": "sqlite_extract → imessage",
        "CallLogsArtifact": "sqlite_extract → call_log",
        "JumpListsArtifact": "win_jumplist parser",
        "IeTypedUrlArtifact": "browser_history (chrome/firefox)",
        "GoogleBrowsingHistoryArtifact": "browser_history",
        "CloudGoogleChromeBrowserHistoryArtifact": "browser_history",
        "TimelineArtifact": "timeline engine",
        "MapArtifact": "timeline / map",
        "WorldMapArtifact": "world map (timeline)",
        "MftArtifact": "TSK disk image MFT",
        "OfficeArtifact": "OOXML document parser",
        "DocumentMetadataExtractor": "OOXML metadata",
        "ImageInfoArtifact": "magic bytes → image info",
        "MediaMetadataExtractor": "media family",
        "SamsungContactArtifact": "mobile_extract → contacts2",
        "SamsungMessagesArtifact": "mobile_extract → sms",
        "SamsungConnectionsArtifact": "mobile_extract → calllog",
        "MicrosoftTeamsMessagesArtifact": "sqlite generic (teams.db)",
        "MicrosoftTeamsMessagesBaseArtifact": "sqlite generic",
        "MicrosoftTeamsMessagesComputerArtifact": "sqlite generic",
        # ETAPA B vlna 1 — port AXIOM extraktorů
        "CloudMboxEmailArtifact": "email_mbox parser",
        "OfflineGmailArtifact": "email_mbox parser",
        "WiFiLocationsArtifact": "win_wlan parser (WLAN profile XML)",
        "ScheduledTasksArtifact": "win_schedtask parser (Task Scheduler XML)",
        "ClipboardArtifact": "win_clipboard (sekundární registry průchod NTUSER.DAT)",
        "ConnscanArtifact": "net_connections parser",
        "NetScanArtifact": "net_connections parser",
        "SockscanArtifact": "net_connections parser",
        "GetsidsArtifact": "win_sids (sekundární registry průchod SAM/SECURITY)",
        "SidsArtifact": "win_sids (sekundární registry průchod SAM/SECURITY)",
        "UserSidsArtifact": "win_sids (sekundární registry průchod + ProfileList)",
        # ETAPA B vlna 2 — port AXIOM extraktorů
        "GoogleSearchHistoryArtifact": "google_search_history parser (JSON Takeout)",
        "CloudGoogleLocationHistoryArtifact": "google_location_history parser (warrant return CSV/JSON)",
        "GoogleLocationHistoryArtifact": "google_location_history parser (JSON Takeout + CSV)",
        "GoogleLoginHistoryArtifact": "google_login_history parser (sign-ins JSON/CSV)",
        "GoogleAccountInfoArtifact": "google_account_info parser (account_info.json)",
        "CmdScanArtifact": "mem_scan parser (textový výstup — procesy v paměti)",
        "FileScanArtifact": "mem_scan parser (textový výstup — soubory v paměti)",
        "CurrentTabsArtifact": "ddg_current_tabs parser (JSON/text záložky)",
        "MSNArtifact": "msn_messenger parser (chat log text)",
        # ETAPA B vlna 3 — port AXIOM extraktorů
        "KikLocalUserExtractor": "kik_messenger parser (SQLite dispatch chain, iOS ZKIK*/Android users+messages)",
        "MailRuChatArtifact": "mailru_agent parser (chat log text | formát)",
        "MailRuContactArtifact": "mailru_agent parser (kontakty)",
        "MailRuGroupArtifact": "mailru_agent parser (skupiny)",
        "BeboArtifact": "bebo_chat parser (text/JSON live chat)",
        "ChatrouletteArtifact": "chatroulette parser (text/JSON video chat)",
        "LimewireArtifact": "limewire_p2p parser (P2P shared files JSON/pipe)",
        "LimerunnerArtifact": "limewire_p2p parser (P2P shared files JSON/pipe)",
        "LuckywireArtifact": "limewire_p2p parser (P2P shared files JSON/pipe)",
        # ETAPA B vlna 4 — port AXIOM extraktorů
        "DuckDuckGoCookiesArtifact": "ddg_cookies parser (Chromium cookies SQLite, µs od 1601)",
        "AllowlistedWebSitesArtifact": "allowlisted_websites parser (DDG tracker exceptions JSON)",
        "OpenOfficeBaseArtifact": "openoffice_base parser (.odb = ZIP/ODF kontejner + DC metadata)",
        "ParkedCarLocationsArtifact": "parked_car_locations parser (iOS Local.sqlite ZRTVEHICLEEVENTMO, CFAbsoluteTime)",
        "VoiceMailArtifact": "ios_voicemail parser (voicemail.db, date=unix s / trashed_date=CFAbsoluteTime)",
        # ETAPA B vlna 5 — port AXIOM extraktorů
        "GoogleAggregatedActivitiesArtifact": "google_aggregated_activities parser (My Activity daily JSON)",
        "GoogleAggregatedActivitiesIdentitySessionsArtifact": "google_aggregated_activities parser (identity sessions JSON)",
        "GoogleMapsActivityArtifact": "google_maps_activity parser (semantic location history, placeVisit/activitySegment E7)",
        "GoogleChatArtifact": "google_chat_family parser (Takeout chat JSON)",
        "GoogleHangoutsArtifact": "google_chat_family parser (Takeout Hangouts JSON)",
        "GooglePlusChatArtifact": "google_chat_family parser (Takeout Plus Chat JSON)",
        "GoogleTalkArtifact": "google_chat_family parser (Takeout Talk JSON)",
        "GoogleAccountChangeHistoryArtifact": "google_account_meta parser (account change history JSON)",
        "GoogleDevicesArtifact": "google_account_meta parser (linked devices JSON)",
        "GoogleExportSummaryArtifact": "google_account_meta parser (export summary JSON)",
        "DriveActivityArtifact": "drive_activity parser (Drive activity log JSON)",
        "SamsungVoiceRecordingArtifact": "samsung_voice_recording parser (SQLite dispatch chain, voice recorder DB)",
        # ETAPA B vlna 6 — port AXIOM extraktorů
        "GooglePhotosArtifact": "google_photos parser (Takeout/warrant JSON, photoTakenTime/geoData E7)",
        "GoogleMailMessageInformationArtifact": "google_mail_info parser (Gmail warrant return JSON, threadId/internalDate µs)",
        "GoogleBarArtifact": "google_bar parser (Chrome History search_terms — omnibox dotazy z lišty)",
        "AttachmentExtractor": "attachment_extractor parser (MIME/RFC822 přílohy → email_attachment artifacty)",
        # ETAPA B vlna 7 — port AXIOM extraktorů
        "GoogleChromeBookmarksWarrantReturnArtifact": "google_chrome_bookmarks parser (Bookmarks JSON, date_added µs od 1601)",
        "CloudGoogleChromeBookmarksArtifact": "google_chrome_bookmarks parser (Bookmarks JSON, date_added µs od 1601)",
        "GoogleChromeHistoryWarrantReturnArtifact": "google_chrome_history_wr parser (History warrant return JSON, visit_time µs od 1601)",
        "GoogleContactsWarrantReturnArtifact": "google_contacts_wr parser (Contacts Takeout/warrant JSON, name/emails/phoneNumbers)",
        "CloudGoogleContactsArtifact": "google_contacts_wr parser (Contacts Takeout/warrant JSON, name/emails/phoneNumbers)",
        "GoogleChromeAutofillWarrantReturnArtifact": "google_chrome_autofill parser (Autofill/ContactInfo JSON, name/email/address)",
        "GoogleChromeContactInfoWarrantReturnArtifact": "google_chrome_autofill parser (Autofill/ContactInfo JSON, name/email/address)",
        "CloudGoogleChromeAutofillArtifact": "google_chrome_autofill parser (Autofill/ContactInfo JSON, name/email/address)",
        "SkypeWarrantReturnAccountDetailsArtifact": "skype_warrant_return parser (account details — account/email/displayName)",
        "SkypeWarrantReturnChatHistoryRecordsArtifact": "skype_warrant_return parser (chat history records — conversationId/composetime)",
        "SkypeWarrantReturnConnectionHistoryArtifact": "skype_warrant_return parser (connection history — contact/status/dateAdded)",
        "SkypeWarrantReturnContactsArtifact": "skype_warrant_return parser (contacts — msnId/displayName/email)",
        # ETAPA B vlna 8 — port AXIOM extraktorů
        "CloudGoogleChromeExtensionsArtifact": "chrome_preferences parser (extensions.settings — ID/název/stav rozšíření)",
        "CloudGoogleChromeExtensionSettingsArtifact": "chrome_preferences parser (detail nastavení rozšíření)",
        "CloudGoogleChromeSearchEnginesArtifact": "chrome_preferences parser (default_search_provider_data + custom search engines)",
        "CloudGoogleChromeSyncSettingsAppSettingsArtifact": "chrome_preferences parser (sync data_type_enabled — app settings)",
        "CloudGoogleChromeSyncSettingsAppsArtifact": "chrome_preferences parser (sync apps)",
        "CloudGoogleChromeSyncSettingsPreferencesArtifact": "chrome_preferences parser (sync preferences)",
        "CloudDriveFileArtifact": "cloud_drive_files parser (Google Drive soubory — název/velikost/checksum/čas)",
        "CloudDriveFileVersionArtifact": "cloud_drive_files parser (verze souboru do details.versions)",
        "CloudOneDriveFileArtifact": "cloud_drive_files parser (OneDrive soubory — lastModifiedDateTime marker)",
        "CloudOneDriveFileVersionArtifact": "cloud_drive_files parser (OneDrive verze souboru)",
        "CloudAppleDriveArtifact": "cloud_drive_files parser (Apple Drive soubory)",
        "GoogleVoiceTexts2025Artifact": "google_voice_wr parser (SMS texty — from/to/body/timestampMsInEpoch)",
        "GoogleVoicemail2025Artifact": "google_voice_wr parser (hlasové schránky — duration/transcript)",
        "GoogleVoiceContactsMetadata2026Artifact": "google_voice_wr parser (kontakty — name/phoneNumber/emailAddress)",
        "GoogleVoiceSubscriberInformation2026Artifact": "google_voice_wr parser (předplatitel — subscriberNumber/carrierName)",
        "DriversArtifact": "win_drivers parser (načtené ovladače z paměti — baseAddress/signed, anomaly unsigned_driver)",
        # ETAPA B vlna 9 — memory forensics (live forensics / paměťový dump)
        "ProcessListArtifact": "mem_processes parser (seznam procesů — pid/name/cmdline/user)",
        "ProcessesArtifact": "mem_processes parser (procesy z paměti — pid/name/ppid/threads)",
        "ProcessScanArtifact": "mem_processes parser (scan procesů — offset/pid/name)",
        "PsxViewArtifact": "mem_processes parser (EPROCESS vs PEB mismatch, anomaly psxview_mismatch)",
        "SocketsArtifact": "mem_network parser (sockety — pid/localAddress/remoteAddress/state)",
        "OpenConnectionsArtifact": "mem_network parser (otevřená spojení — proto/state)",
        "NetworkConnectionsArtifact": "mem_network parser (síťová spojení z paměti)",
        "HandlesArtifact": "mem_handles parser (handlery — handleValue/type/name, hex normalizace)",
        "OpenHandlesArtifact": "mem_handles parser (otevřené handlery procesů)",
        "ModScanArtifact": "mem_modules parser (načtené moduly — baseAddress/size/inLdrList)",
        "MalfindArtifact": "mem_modules parser (skryté moduly, anomaly hidden_module / DLL injection)",
        "ApiHooksArtifact": "mem_hooks parser (API hooky — apiFunction/callbackAddress/hookType)",
        "CallbacksArtifact": "mem_hooks parser (callback funkce v paměti)",
        "ExecutiveObjectCallbacksArtifact": "mem_hooks parser (executive object callbacky)",
        # ETAPA B vlna 10 — cloud SNS exporty (Instagram/Snapchat warrant return)
        "InstagramMessagesArtifact": "instagram_messages parser (DM konverzace — participants/messages, tolerantní klíče)",
        "CloudInstagramDirectMessagesArtifact": "instagram_messages parser (cloud DM export)",
        "CloudFacebookInstagramMessagesArtifact": "instagram_messages parser (FB↔IG cross-posted zprávy)",
        "InstagramDirectSharesArtifact": "instagram_messages parser (sdílená média v DM, message_type=share)",
        "CloudInstagramPostsArtifact": "instagram_posts parser (posts — caption/likes/media_url/comments)",
        "CloudInstagramPostsAxiom2Pt1Artifact": "instagram_posts parser (AXIOM 2.1 posts varianta)",
        "InstagramMediaArtifact": "instagram_posts parser (média — url/type)",
        "InstagramPhotosArtifact": "instagram_posts parser (fotky)",
        "InstagramArchivedStoriesArtifact": "instagram_posts parser (archivované stories, is_story=True)",
        "InstagramDirectStoriesArtifact": "instagram_posts parser (direct stories)",
        "InstagramCommentsArtifact": "instagram_posts parser (komentáře — user/text/post_id)",
        "InstagramAccountActionsArtifact": "instagram_account parser (akce účtu → event_log_entry, ip_address/device)",
        "InstagramAccountHistoryArtifact": "instagram_account parser (historie účtu → event_log_entry)",
        "InstagramFollowersAndFollowingArtifact": "instagram_account parser (followery/following → contact sns:instagram)",
        "SnapchatMessagesWarrantReturnArtifact": "snapchat_wr parser (zprávy WR — from/to/body/time, konverzace i flat)",
        "SnapchatGroupChatMessagesArtifact": "snapchat_wr parser (skupinové chaty — group_id)",
        "SnapchatFriendsArtifact": "snapchat_wr parser (přátelé → contact sns:snapchat:user)",
        "SnapchatGeolocationArtifact": "snapchat_wr parser (geolokace → location_data, lat/lon tolerantní klíče)",
        "SnapchatIpHistoryArtifact": "snapchat_wr parser (IP historie → network_connection, ip_address/event_type)",
        "SnapchatAccountInformationArtifact": "snapchat_wr parser (info o účtu → contact user/email/phone)",
    }
    return m.get(name, "existující parser")


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for x in data:
        name = x["type"].split(".")[-1]
        cat, desc = classify(name, x["dll"])
        rows.append({"name": name, "category": cat, "mechanism": desc})

    # dedupe (některé typy se opakují napříč DLL) — zachovat pořadí prvního výskytu
    seen: set[str] = set()
    unique: list[dict] = []
    for r in rows:
        if r["name"] not in seen:
            seen.add(r["name"])
            unique.append(r)

    counts = Counter(r["category"] for r in unique)
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in unique:
        by_cat[r["category"]].append(r)

    # ── JSON výstup ──
    OUT_JSON.write_text(
        json.dumps(
            {
                "total_entries": len(data),
                "unique_types": len(unique),
                "counts": dict(counts),
                "by_category": {k: [r["name"] for r in sorted(v, key=lambda x: x["name"])] for k, v in by_cat.items()},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # ── Markdown matice ──
    order = ["covered", "portable-local", "cloud-export", "memory", "base-class"]
    titles = {
        "covered": "✅ COVERED — STOPA už umí (existující parser)",
        "portable-local": "🔧 PORTABLE-LOCAL — lokálně portovatelný (čistý Python)",
        "cloud-export": "☁️ CLOUD-EXPORT — JSON export / warrant return",
        "memory": "💾 MEMORY — live forensics (paměťový dump)",
        "base-class": "🧩 BASE-CLASS — rozhraní / základní třída",
    }
    lines = [
        "# STOPA × Magnet AXIOM — pokryvací matice extraktorů",
        "",
        f"Zdroj: `axiom-artifact-extractors.json` ({len(data)} položek, {len(unique)} unikátních typů).",
        "Klasifikace je datová (deterministická) — generováno `scripts/build_axiom_coverage.py`.",
        "",
        "## Souhrn",
        "",
    ]
    for cat in order:
        lines.append(f"- **{titles[cat].split('—')[0].strip()}**: {counts.get(cat, 0)}")
    lines += ["", "---", ""]
    for cat in order:
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines.append(f"## {titles[cat]} ({len(items)})")
        lines.append("")
        for r in sorted(items, key=lambda x: x["name"]):
            lines.append(f"- `{r['name']}` — {r['mechanism']}")
        lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    # ── FÁZE 15 — centrální matice v kořeni (CSV) ──
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "artifact_type",
                "platforma",
                "zdroj_dat",
                "parser_stopa",
                "stav_implementace",
                "stav_testovani",
                "verze",
                "znamá_omezeni",
                "referencni_dataset",
                "vysledek_validace",
            ]
        )
        for r in sorted(unique, key=lambda x: (x["category"], x["name"])):
            status, test_state = _STATUS_BY_CAT[r["category"]]
            w.writerow(
                [
                    r["name"],
                    "multi" if r["category"] != "memory" else "windows-memory",
                    r["mechanism"],
                    r["mechanism"] if r["category"] == "covered" else "",
                    status,
                    test_state,
                    "",  # verze parseru — doplní se při portu z PARSER_VERSION
                    "",  # známá omezení
                    "",  # referenční dataset (syntetický fixture)
                    "",  # výsledek validace (C6 benchmark report)
                ]
            )

    print(f"total={len(data)} unique={len(unique)}")
    for cat in order:
        print(f"  {cat}: {counts.get(cat, 0)}")


if __name__ == "__main__":
    main()
