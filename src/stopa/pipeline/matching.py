"""Souborové matchery — SNS prepass a název-souboru heuristiky.

P1-4 vlna D: vyčleněno z monolitu ``pipeline.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from stopa.artifacts.allowlisted_websites import is_allowlisted_websites_file
from stopa.artifacts.amazon_cloudtrail import is_amazon_cloudtrail_file
from stopa.artifacts.amazon_ec2_s3 import is_amazon_ec2_s3_file
from stopa.artifacts.apple_cloud import is_apple_file
from stopa.artifacts.bebo_chat import is_bebo_chat_file
from stopa.artifacts.box_cloud import is_box_file
from stopa.artifacts.chatroulette import is_chatroulette_file
from stopa.artifacts.chrome_preferences import is_chrome_preferences_file
from stopa.artifacts.cloud_drive_files import is_cloud_drive_file
from stopa.artifacts.cloud_generic import is_cloud_generic_file
from stopa.artifacts.crypto_extract import is_crypto_candidate_file
from stopa.artifacts.ddg_current_tabs import is_current_tabs_file
from stopa.artifacts.drive_activity import is_drive_activity_file
from stopa.artifacts.dropbox_mega import is_dropbox_file, is_mega_file
from stopa.artifacts.email_mbox import is_email_file
from stopa.artifacts.facebook_wr import is_facebook_file
from stopa.artifacts.gmail_messages import is_gmail_file
from stopa.artifacts.google_2025_wr import is_google_2025_file
from stopa.artifacts.google_account_info import is_account_info_file
from stopa.artifacts.google_account_meta import (
    is_account_change_history_file,
    is_export_summary_file,
    is_linked_devices_file,
)
from stopa.artifacts.google_aggregated_activities import (
    is_aggregated_activities_file,
    is_identity_sessions_file,
)
from stopa.artifacts.google_calendar_events import is_google_calendar_file
from stopa.artifacts.google_chat_family import is_google_chat_file
from stopa.artifacts.google_chrome_autofill import is_chrome_autofill_file
from stopa.artifacts.google_chrome_bookmarks import is_chrome_bookmarks_file
from stopa.artifacts.google_chrome_history_wr import is_chrome_history_wr_file
from stopa.artifacts.google_contacts_wr import is_contacts_wr_file
from stopa.artifacts.google_keep_tasks import is_google_keep_file
from stopa.artifacts.google_location_history import is_location_history_file
from stopa.artifacts.google_login_history import is_login_history_file
from stopa.artifacts.google_mail_info import is_mail_info_file
from stopa.artifacts.google_maps_activity import is_maps_activity_file
from stopa.artifacts.google_photos import is_photos_file
from stopa.artifacts.google_search_history import is_google_search_history_file
from stopa.artifacts.google_voice_wr import is_google_voice_file
from stopa.artifacts.imessage_cloud import is_icloud_messages_file
from stopa.artifacts.instagram_account import is_instagram_account_file
from stopa.artifacts.instagram_messages import is_instagram_messages_file
from stopa.artifacts.instagram_posts import is_instagram_posts_file
from stopa.artifacts.limewire_p2p import is_limewire_family_file
from stopa.artifacts.mailru_agent import is_mailru_file
from stopa.artifacts.maps_labeled_places import is_maps_labeled_file
from stopa.artifacts.mem_handles import is_mem_handles_file
from stopa.artifacts.mem_hooks import is_mem_hooks_file
from stopa.artifacts.mem_modules import is_mem_modules_file
from stopa.artifacts.mem_network import is_mem_network_file
from stopa.artifacts.mem_processes import is_mem_processes_file
from stopa.artifacts.mem_scan import is_mem_scan_file
from stopa.artifacts.ms_contacts import is_ms_contacts_file
from stopa.artifacts.ms_mail_pst import is_ms_mail_file
from stopa.artifacts.ms_outlook_calendar import is_ms_outlook_calendar_file
from stopa.artifacts.ms_teams_conversations import is_ms_teams_conversations_file
from stopa.artifacts.ms_teams_teams import is_ms_teams_file
from stopa.artifacts.msn_messenger import is_msn_chat_file
from stopa.artifacts.net_connections import is_netstat_file
from stopa.artifacts.openoffice_base import is_openoffice_base_file
from stopa.artifacts.sharepoint_wr import is_sharepoint_file
from stopa.artifacts.sim_tpdu import is_sim_tpdu_file
from stopa.artifacts.skype_warrant_return import is_skype_warrant_file
from stopa.artifacts.snapchat_wr import is_snapchat_file
from stopa.artifacts.twitter_messages import is_twitter_messages_file
from stopa.artifacts.twitter_posts import is_twitter_posts_file
from stopa.artifacts.twitter_users import is_twitter_users_file
from stopa.artifacts.whatsapp_cloud import is_whatsapp_file
from stopa.artifacts.win_drivers import is_win_drivers_file
from stopa.artifacts.win_jumplist import is_jump_list_file
from stopa.artifacts.win_schedtask import is_scheduled_task_file
from stopa.artifacts.win_usn import is_usn_journal_file
from stopa.artifacts.win_wlan import is_wlan_profile_file

from .registry import NAME_BASED_EXTRACTORS


def _sns_prepass(full_path: str) -> tuple[Callable[[Path], list], str] | None:
    """ETAPA B vlna 10/11/12/13/14 — cloud SNS + Microsoft/Amazon/Google II pre-pass na celé cestě.

    Instagram/Snapchat/Twitter/Facebook exporty mají generic basenames
    (``Messages.json``, ``Photos.json``, ``Friends.json``), které kolidují s
    Google detektory v basename chainu → SNS markery se zkoušejí PŘED ním.
    ETAPA B vlna 12: + Microsoft/Amazon cloud exporty (generic basenames
    ``contacts.json`` / ``events.json`` / ``instances.json``) — specifické
    detektory PŘED obecnějšími (conversations PŘED teams, contacts PŘED mail).
    ETAPA B vlna 13: + Google Calendar/Keep a Box/Dropbox/Mega cloud exporty
    (generic basenames ``events.json`` / ``notes.json`` / ``files.json``) —
    calendar PŘED keep (oba mohou mít generic JSON), dropbox/mega dle markery.
    ETAPA B vlna 14: + dokončení cloud-export — Apple rodina, Google 2025 WR,
    WhatsApp, Gmail Messages a Maps Labeled Places (specifické PŘED obecným
    ``cloud_generic`` metadata parserem).
    """
    for key, detector in (
        ("instagram_messages", is_instagram_messages_file),
        # account PŘED posts — "AccountHistory" obsahuje substring "stor(y)"
        ("instagram_account", is_instagram_account_file),
        ("instagram_posts", is_instagram_posts_file),
        ("snapchat_wr", is_snapchat_file),
        # ETAPA B vlna 11 — Twitter/X + Facebook (messages PŘED users/posts)
        ("twitter_messages", is_twitter_messages_file),
        ("twitter_users", is_twitter_users_file),
        ("twitter_posts", is_twitter_posts_file),
        ("facebook_wr", is_facebook_file),
        # ETAPA B vlna 12 — Microsoft (contacts PŘED mail; conversations PŘED teams)
        ("ms_contacts", is_ms_contacts_file),
        ("ms_mail_pst", is_ms_mail_file),
        ("ms_teams_conversations", is_ms_teams_conversations_file),
        ("ms_teams_teams", is_ms_teams_file),
        ("ms_outlook_calendar", is_ms_outlook_calendar_file),
        # ETAPA B vlna 12 — SharePoint + Amazon (cloudtrail PŘED ec2_s3)
        ("sharepoint_wr", is_sharepoint_file),
        ("amazon_cloudtrail", is_amazon_cloudtrail_file),
        ("amazon_ec2_s3", is_amazon_ec2_s3_file),
        # ETAPA B vlna 13 — Google II (calendar PŘED keep; oba generic JSON)
        ("google_calendar_events", is_google_calendar_file),
        ("google_keep_tasks", is_google_keep_file),
        # ETAPA B vlna 13 — cloud storage Box/Dropbox/Mega (dle markery)
        ("box_cloud", is_box_file),
        ("dropbox_mega", is_dropbox_file),
        ("dropbox_mega", is_mega_file),
        # ETAPA B vlna 14 — dokončení cloud-export: specifické PŘED obecným generic
        ("apple_cloud", is_apple_file),
        ("google_2025_wr", is_google_2025_file),
        ("whatsapp_cloud", is_whatsapp_file),
        ("gmail_messages", is_gmail_file),
        ("maps_labeled_places", is_maps_labeled_file),
        # nejobecnější poslední — chytí AccountsInfo/ConnectedApps/RecentDevices/
        # Timeline/Passwords/AndroidBackups/AzureVM, co nezachytilo nic výše
        ("cloud_generic", is_cloud_generic_file),
    ):
        if detector(full_path):
            fn, ver = NAME_BASED_EXTRACTORS[key]
            return fn, ver
    return None


def _name_based_match(name: str) -> tuple[Callable[[Path], list], str] | None:
    """Name-based fallback dispatch — AXIOM Hunter pattern.

    iCloud Messages export a Jump Lists nemají spolehlivou magic; detekce
    podle názvu souboru, jen když signatura nic nenašla (viz _extract_artifacts_for).
    ETAPA B vlna 1: + email (.eml/.mbox), WiFi WLAN profile XML, Scheduled Tasks
    XML a netstat/connstat text — všechny bez spolehlivé magiky.
    ETAPA B vlna 2: + Google lokální profily (Search/Location/Login History,
    Account Info JSON/CSV), cmdscan/filescan paměťové skeny, DuckDuckGo Current
    Tabs a MSN/Messenger chat logy — všechny bez spolehlivé magiky.
    ETAPA B vlna 3: + Bebo Live Chat, Chatroulette video chat, Mail.Ru Agent
    (chat/kontakty) a P2P shared files (LimeWire/Limerunner/Luckywire) —
    textové/JSON logy bez spolehlivé magiky. Kik běží schéma-based v SQLite
    dispatch chainu (viz sqlite_extract), ne zde. ETAPA B vlna 4: + DuckDuckGo
    Allowlisted Websites (JSON) a OpenOffice/LibreOffice Base (.odb ZIP kontejner).
    ETAPA B vlna 5: + Google Takeout rodina — Aggregated Activities, Identity
    Sessions, Maps Activity (semantic location history), IM chat rodina
    (Chat/Hangouts/Plus/Talk), Account Change History, Linked Devices, Export
    Summary a Drive activity logy. Samsung Voice Recording běží schéma-based v
    SQLite dispatch chainu (viz sqlite_extract). ETAPA B vlna 9: + memory
    forensics exporty (procesy, síťová spojení, handlery, moduly, API hooks) —
    JSON výstupy paměťových scannerů bez spolehlivé magiky; detekce PŘED
    netstatem kvůli sdíleným klíčovým slovům.
    """
    if is_icloud_messages_file(name):
        return NAME_BASED_EXTRACTORS["icloud_messages"]
    if is_jump_list_file(name):
        return NAME_BASED_EXTRACTORS["win_jumplist"]
    if is_usn_journal_file(name):
        return NAME_BASED_EXTRACTORS["win_usn"]
    if is_email_file(name):
        return NAME_BASED_EXTRACTORS["email_mbox"]
    if is_wlan_profile_file(name):
        return NAME_BASED_EXTRACTORS["wifi_wlan"]
    if is_scheduled_task_file(name):
        return NAME_BASED_EXTRACTORS["win_schedtask"]
    # ETAPA B vlna 9 — memory forensics (PŘED netstatem: sdílená klíčová slova
    # "connections"/"sockets"; memory exporty jsou JSON, parsery defenzivní)
    if is_mem_processes_file(name):
        return NAME_BASED_EXTRACTORS["mem_processes"]
    if is_mem_network_file(name):
        return NAME_BASED_EXTRACTORS["mem_network"]
    if is_mem_handles_file(name):
        return NAME_BASED_EXTRACTORS["mem_handles"]
    if is_mem_modules_file(name):
        return NAME_BASED_EXTRACTORS["mem_modules"]
    if is_mem_hooks_file(name):
        return NAME_BASED_EXTRACTORS["mem_hooks"]
    if is_netstat_file(name):
        return NAME_BASED_EXTRACTORS["net_connections"]
    # ETAPA B vlna 5 — Google Takeout rodina (specifické PŘED obecnějšími vlna-2 detekcemi)
    if is_aggregated_activities_file(name):
        return NAME_BASED_EXTRACTORS["google_aggregated_activities"]
    if is_identity_sessions_file(name):
        return NAME_BASED_EXTRACTORS["google_identity_sessions"]
    if is_maps_activity_file(name):
        return NAME_BASED_EXTRACTORS["google_maps_activity"]
    if is_google_chat_file(name):
        return NAME_BASED_EXTRACTORS["google_chat_family"]
    if is_account_change_history_file(name):
        return NAME_BASED_EXTRACTORS["google_account_change_history"]
    if is_linked_devices_file(name):
        return NAME_BASED_EXTRACTORS["google_linked_devices"]
    if is_export_summary_file(name):
        return NAME_BASED_EXTRACTORS["google_export_summary"]
    if is_drive_activity_file(name):
        return NAME_BASED_EXTRACTORS["drive_activity"]
    # ETAPA B vlna 6 — Google Photos + Mail Message Information (WarrantReturn JSON)
    if is_photos_file(name):
        return NAME_BASED_EXTRACTORS["google_photos"]
    if is_mail_info_file(name):
        return NAME_BASED_EXTRACTORS["google_mail_info"]
    # ETAPA B vlna 2 — Google profily (specifické názvy PŘED obecnějšími)
    if is_google_search_history_file(name):
        return NAME_BASED_EXTRACTORS["google_search_history"]
    if is_location_history_file(name):
        return NAME_BASED_EXTRACTORS["google_location_history"]
    if is_login_history_file(name):
        return NAME_BASED_EXTRACTORS["google_login_history"]
    if is_account_info_file(name):
        return NAME_BASED_EXTRACTORS["google_account_info"]
    # ETAPA B vlna 7 — Chrome Bookmarks/History/Autofill + Contacts + Skype WR
    # (specifické PŘED obecnějšími; autofill PŘED contacts — "contactinfo" ⊃ "contact")
    if is_chrome_bookmarks_file(name):
        return NAME_BASED_EXTRACTORS["chrome_bookmarks"]
    if is_chrome_autofill_file(name):
        return NAME_BASED_EXTRACTORS["chrome_autofill"]
    if is_chrome_history_wr_file(name):
        return NAME_BASED_EXTRACTORS["chrome_history_wr"]
    if is_contacts_wr_file(name):
        return NAME_BASED_EXTRACTORS["contacts_wr"]
    if is_skype_warrant_file(name):
        return NAME_BASED_EXTRACTORS["skype_warrant"]
    # ETAPA B vlna 8 — Chrome prefs/sync + cloud drive soubory + Google Voice WR + drivers
    # (chrome_preferences PŘED obecnějšími; cloud_drive PO drive_activity — ten je specifický)
    if is_chrome_preferences_file(name):
        return NAME_BASED_EXTRACTORS["chrome_preferences"]
    if is_cloud_drive_file(name):
        return NAME_BASED_EXTRACTORS["cloud_drive_files"]
    if is_google_voice_file(name):
        return NAME_BASED_EXTRACTORS["google_voice_wr"]
    if is_win_drivers_file(name):
        return NAME_BASED_EXTRACTORS["win_drivers"]
    # ETAPA B vlna 2 — paměťové skeny / záložky / MSN chat logy
    if is_mem_scan_file(name):
        return NAME_BASED_EXTRACTORS["mem_scan"]
    if is_current_tabs_file(name):
        return NAME_BASED_EXTRACTORS["ddg_current_tabs"]
    if is_msn_chat_file(name):
        return NAME_BASED_EXTRACTORS["msn_messenger"]
    # ETAPA B vlna 3 — legacy mobile/messenger (Bebo, Chatroulette, Mail.ru, P2P)
    if is_bebo_chat_file(name):
        return NAME_BASED_EXTRACTORS["bebo_chat"]
    if is_chatroulette_file(name):
        return NAME_BASED_EXTRACTORS["chatroulette"]
    if is_mailru_file(name):
        return NAME_BASED_EXTRACTORS["mailru_agent"]
    if is_limewire_family_file(name):
        return NAME_BASED_EXTRACTORS["limewire_p2p"]
    # ETAPA B vlna 4 — DDG allowlisted websites (JSON) + OpenOffice Base (.odb ZIP)
    if is_allowlisted_websites_file(name):
        return NAME_BASED_EXTRACTORS["allowlisted_websites"]
    if is_openoffice_base_file(name):
        return NAME_BASED_EXTRACTORS["openoffice_base"]
    # ETAPA B vlna 15 — SIM TPDU phonebook (AT+CPBR textový export)
    if is_sim_tpdu_file(name):
        return NAME_BASED_EXTRACTORS["sim_tpdu"]
    # K2 — crypto forensics: wallet/vault/exchange soubory podle názvu
    # (default_wallet bez přípony → full-path retry níže v _extract_artifacts_for)
    if is_crypto_candidate_file(name):
        return NAME_BASED_EXTRACTORS["crypto_extract"]
    return None
