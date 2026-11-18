"""Rejstřík extraktorů artefaktů — signatury (magic bytes) a název-souboru.

P1-4 vlna D: vyčleněno z monolitu ``pipeline.py``; jediný zdroj pravdy pro
mapování typ souboru → extraktor (ARTIFACT_EXTRACTORS) a název-souboru
(NAME_BASED_EXTRACTORS) + verze parserů (PARSER_VERSION aliasy).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from stopa.artifacts.allowlisted_websites import PARSER_VERSION as ALLOWLISTED_WEBSITES_VERSION
from stopa.artifacts.allowlisted_websites import extract_allowlisted_websites_artifacts
from stopa.artifacts.amazon_cloudtrail import PARSER_VERSION as AMAZON_CLOUDTRAIL_VERSION
from stopa.artifacts.amazon_cloudtrail import extract_cloudtrail_artifacts
from stopa.artifacts.amazon_ec2_s3 import PARSER_VERSION as AMAZON_EC2_S3_VERSION
from stopa.artifacts.amazon_ec2_s3 import extract_amazon_ec2_s3_artifacts
from stopa.artifacts.apple_cloud import PARSER_VERSION as APPLE_CLOUD_VERSION
from stopa.artifacts.apple_cloud import extract_apple_cloud_artifacts
from stopa.artifacts.bebo_chat import PARSER_VERSION as BEBO_CHAT_VERSION
from stopa.artifacts.bebo_chat import extract_bebo_artifacts
from stopa.artifacts.box_cloud import PARSER_VERSION as BOX_CLOUD_VERSION
from stopa.artifacts.box_cloud import extract_box_artifacts
from stopa.artifacts.chatroulette import PARSER_VERSION as CHATROULETTE_VERSION
from stopa.artifacts.chatroulette import extract_chatroulette_artifacts
from stopa.artifacts.chrome_preferences import PARSER_VERSION as CHROME_PREFS_VERSION
from stopa.artifacts.chrome_preferences import extract_chrome_pref_artifacts
from stopa.artifacts.cloud_drive_files import PARSER_VERSION as CLOUD_DRIVE_FILES_VERSION
from stopa.artifacts.cloud_drive_files import extract_cloud_drive_artifacts
from stopa.artifacts.cloud_generic import PARSER_VERSION as CLOUD_GENERIC_VERSION
from stopa.artifacts.cloud_generic import extract_cloud_generic_artifacts
from stopa.artifacts.crypto_extract import CRYPTO_EXTRACT_VERSION, extract_crypto_artifacts
from stopa.artifacts.ddg_current_tabs import PARSER_VERSION as DDG_TABS_VERSION
from stopa.artifacts.ddg_current_tabs import extract_current_tabs_artifacts
from stopa.artifacts.drive_activity import PARSER_VERSION as DRIVE_ACTIVITY_VERSION
from stopa.artifacts.drive_activity import extract_drive_activity_artifacts
from stopa.artifacts.dropbox_mega import PARSER_VERSION as DROPBOX_MEGA_VERSION
from stopa.artifacts.dropbox_mega import extract_dropbox_mega_artifacts
from stopa.artifacts.email_mbox import PARSER_VERSION as EMAIL_MBOX_VERSION
from stopa.artifacts.email_mbox import extract_email_artifacts
from stopa.artifacts.facebook_wr import PARSER_VERSION as FACEBOOK_WR_VERSION
from stopa.artifacts.facebook_wr import extract_facebook_artifacts
from stopa.artifacts.gmail_messages import PARSER_VERSION as GMAIL_MESSAGES_VERSION
from stopa.artifacts.gmail_messages import extract_gmail_artifacts
from stopa.artifacts.google_2025_wr import PARSER_VERSION as GOOGLE_2025_WR_VERSION
from stopa.artifacts.google_2025_wr import extract_google_2025_artifacts
from stopa.artifacts.google_account_info import PARSER_VERSION as GOOGLE_ACCT_VERSION
from stopa.artifacts.google_account_info import extract_account_artifacts
from stopa.artifacts.google_account_meta import (
    PARSER_VERSION as GOOGLE_ACCOUNT_META_VERSION,
)
from stopa.artifacts.google_account_meta import (
    extract_account_change_history_artifacts,
    extract_export_summary_artifacts,
    extract_linked_devices_artifacts,
)
from stopa.artifacts.google_aggregated_activities import (
    PARSER_VERSION as GOOGLE_AGGREGATED_VERSION,
)
from stopa.artifacts.google_aggregated_activities import (
    extract_aggregated_activities_artifacts,
    extract_identity_sessions_artifacts,
)
from stopa.artifacts.google_calendar_events import (
    PARSER_VERSION as GOOGLE_CALENDAR_EVENTS_VERSION,
)
from stopa.artifacts.google_calendar_events import extract_google_calendar_artifacts
from stopa.artifacts.google_chat_family import PARSER_VERSION as GOOGLE_CHAT_FAMILY_VERSION
from stopa.artifacts.google_chat_family import extract_google_chat_artifacts
from stopa.artifacts.google_chrome_autofill import (
    PARSER_VERSION as CHROME_AUTOFILL_VERSION,
)
from stopa.artifacts.google_chrome_autofill import extract_chrome_autofill_artifacts
from stopa.artifacts.google_chrome_bookmarks import (
    PARSER_VERSION as CHROME_BOOKMARKS_VERSION,
)
from stopa.artifacts.google_chrome_bookmarks import extract_bookmarks_artifacts
from stopa.artifacts.google_chrome_history_wr import (
    PARSER_VERSION as CHROME_HISTORY_WR_VERSION,
)
from stopa.artifacts.google_chrome_history_wr import extract_chrome_history_wr_artifacts
from stopa.artifacts.google_contacts_wr import PARSER_VERSION as CONTACTS_WR_VERSION
from stopa.artifacts.google_contacts_wr import extract_contacts_wr_artifacts
from stopa.artifacts.google_keep_tasks import PARSER_VERSION as GOOGLE_KEEP_TASKS_VERSION
from stopa.artifacts.google_keep_tasks import extract_google_keep_artifacts
from stopa.artifacts.google_location_history import (
    PARSER_VERSION as GOOGLE_LOC_VERSION,
)
from stopa.artifacts.google_location_history import extract_location_artifacts
from stopa.artifacts.google_login_history import PARSER_VERSION as GOOGLE_LOGIN_VERSION
from stopa.artifacts.google_login_history import extract_login_artifacts
from stopa.artifacts.google_mail_info import PARSER_VERSION as GOOGLE_MAIL_INFO_VERSION
from stopa.artifacts.google_mail_info import extract_mail_info_artifacts
from stopa.artifacts.google_maps_activity import PARSER_VERSION as GOOGLE_MAPS_ACTIVITY_VERSION
from stopa.artifacts.google_maps_activity import extract_maps_activity_artifacts
from stopa.artifacts.google_photos import PARSER_VERSION as GOOGLE_PHOTOS_VERSION
from stopa.artifacts.google_photos import extract_photos_artifacts
from stopa.artifacts.google_search_history import (
    PARSER_VERSION as GOOGLE_SEARCH_VERSION,
)
from stopa.artifacts.google_search_history import extract_google_search_artifacts
from stopa.artifacts.google_voice_wr import PARSER_VERSION as GOOGLE_VOICE_WR_VERSION
from stopa.artifacts.google_voice_wr import extract_google_voice_artifacts
from stopa.artifacts.imessage_cloud import (
    PARSER_VERSION as IMESSAGE_CLOUD_VERSION,
)
from stopa.artifacts.imessage_cloud import extract_icloud_messages
from stopa.artifacts.instagram_account import PARSER_VERSION as INSTAGRAM_ACCOUNT_VERSION
from stopa.artifacts.instagram_account import extract_instagram_account_artifacts
from stopa.artifacts.instagram_messages import PARSER_VERSION as INSTAGRAM_MESSAGES_VERSION
from stopa.artifacts.instagram_messages import extract_instagram_message_artifacts
from stopa.artifacts.instagram_posts import PARSER_VERSION as INSTAGRAM_POSTS_VERSION
from stopa.artifacts.instagram_posts import extract_instagram_post_artifacts
from stopa.artifacts.limewire_p2p import PARSER_VERSION as LIMEWIRE_P2P_VERSION
from stopa.artifacts.limewire_p2p import extract_shared_files_artifacts
from stopa.artifacts.mailru_agent import PARSER_VERSION as MAILRU_AGENT_VERSION
from stopa.artifacts.mailru_agent import extract_mailru_artifacts
from stopa.artifacts.maps_labeled_places import (
    PARSER_VERSION as MAPS_LABELED_PLACES_VERSION,
)
from stopa.artifacts.maps_labeled_places import extract_maps_labeled_artifacts
from stopa.artifacts.mem_handles import PARSER_VERSION as MEM_HANDLES_VERSION
from stopa.artifacts.mem_handles import extract_mem_handle_artifacts
from stopa.artifacts.mem_hooks import PARSER_VERSION as MEM_HOOKS_VERSION
from stopa.artifacts.mem_hooks import extract_mem_hook_artifacts
from stopa.artifacts.mem_modules import PARSER_VERSION as MEM_MODULES_VERSION
from stopa.artifacts.mem_modules import extract_mem_module_artifacts
from stopa.artifacts.mem_network import PARSER_VERSION as MEM_NETWORK_VERSION
from stopa.artifacts.mem_network import extract_mem_connection_artifacts
from stopa.artifacts.mem_processes import PARSER_VERSION as MEM_PROCESSES_VERSION
from stopa.artifacts.mem_processes import extract_mem_process_artifacts
from stopa.artifacts.mem_scan import PARSER_VERSION as MEMSCAN_VERSION
from stopa.artifacts.mem_scan import extract_mem_scan_artifacts
from stopa.artifacts.ms_contacts import PARSER_VERSION as MS_CONTACTS_VERSION
from stopa.artifacts.ms_contacts import extract_ms_contact_artifacts
from stopa.artifacts.ms_mail_pst import PARSER_VERSION as MS_MAIL_PST_VERSION
from stopa.artifacts.ms_mail_pst import extract_ms_mail_artifacts
from stopa.artifacts.ms_outlook_calendar import (
    PARSER_VERSION as MS_OUTLOOK_CALENDAR_VERSION,
)
from stopa.artifacts.ms_outlook_calendar import extract_outlook_calendar_artifacts
from stopa.artifacts.ms_teams_conversations import (
    PARSER_VERSION as MS_TEAMS_CONVERSATIONS_VERSION,
)
from stopa.artifacts.ms_teams_conversations import extract_teams_conversation_artifacts
from stopa.artifacts.ms_teams_teams import PARSER_VERSION as MS_TEAMS_TEAMS_VERSION
from stopa.artifacts.ms_teams_teams import extract_teams
from stopa.artifacts.msn_messenger import PARSER_VERSION as MSN_VERSION
from stopa.artifacts.msn_messenger import extract_msn_artifacts
from stopa.artifacts.net_connections import PARSER_VERSION as NETSTAT_VERSION
from stopa.artifacts.net_connections import extract_netstat_artifacts
from stopa.artifacts.openoffice_base import PARSER_VERSION as OPENOFFICE_BASE_VERSION
from stopa.artifacts.openoffice_base import extract_openoffice_base_artifacts
from stopa.artifacts.plist_extract import PARSER_VERSION as PLIST_VERSION
from stopa.artifacts.plist_extract import extract_plist_artifacts
from stopa.artifacts.registry_extract import PARSER_VERSION as REGISTRY_VERSION
from stopa.artifacts.sharepoint_wr import PARSER_VERSION as SHAREPOINT_WR_VERSION
from stopa.artifacts.sharepoint_wr import extract_sharepoint_artifacts
from stopa.artifacts.sim_tpdu import PARSER_VERSION as SIM_TPDU_VERSION
from stopa.artifacts.sim_tpdu import extract_tpdu_artifacts
from stopa.artifacts.skype_warrant_return import PARSER_VERSION as SKYPE_WR_VERSION
from stopa.artifacts.skype_warrant_return import extract_skype_artifacts
from stopa.artifacts.snapchat_wr import PARSER_VERSION as SNAPCHAT_WR_VERSION
from stopa.artifacts.snapchat_wr import extract_snapchat_artifacts
from stopa.artifacts.sqlite_extract import PARSER_VERSION as SQLITE_VERSION
from stopa.artifacts.twitter_messages import PARSER_VERSION as TWITTER_MESSAGES_VERSION
from stopa.artifacts.twitter_messages import extract_twitter_message_artifacts
from stopa.artifacts.twitter_posts import PARSER_VERSION as TWITTER_POSTS_VERSION
from stopa.artifacts.twitter_posts import extract_twitter_post_artifacts
from stopa.artifacts.twitter_users import PARSER_VERSION as TWITTER_USERS_VERSION
from stopa.artifacts.twitter_users import extract_twitter_user_artifacts
from stopa.artifacts.whatsapp_cloud import PARSER_VERSION as WHATSAPP_CLOUD_VERSION
from stopa.artifacts.whatsapp_cloud import extract_whatsapp_artifacts
from stopa.artifacts.win_drivers import PARSER_VERSION as WIN_DRIVERS_VERSION
from stopa.artifacts.win_drivers import extract_win_driver_artifacts
from stopa.artifacts.win_eventlog import PARSER_VERSION as EVTX_VERSION
from stopa.artifacts.win_eventlog import extract_evtx_artifacts
from stopa.artifacts.win_jumplist import PARSER_VERSION as JUMPLIST_VERSION
from stopa.artifacts.win_jumplist import extract_jump_list_artifacts
from stopa.artifacts.win_lnk import PARSER_VERSION as LNK_VERSION
from stopa.artifacts.win_lnk import extract_lnk_artifacts
from stopa.artifacts.win_prefetch import PARSER_VERSION as PREFETCH_VERSION
from stopa.artifacts.win_prefetch import extract_prefetch_artifacts
from stopa.artifacts.win_schedtask import (
    PARSER_VERSION as SCHEDTASK_VERSION,
)
from stopa.artifacts.win_schedtask import extract_scheduled_task_artifacts
from stopa.artifacts.win_usn import (
    PARSER_VERSION as USN_VERSION,
)
from stopa.artifacts.win_usn import extract_usn_artifacts
from stopa.artifacts.win_wlan import PARSER_VERSION as WLAN_VERSION
from stopa.artifacts.win_wlan import extract_wifi_artifacts

from .extractors import (
    _extract_registry_all,
    _extract_sqlite_all,
)

ARTIFACT_EXTRACTORS: dict[str, tuple[Callable[[Path], list], str]] = {
    "sqlite": (_extract_sqlite_all, SQLITE_VERSION),
    # E7: registry hivy běží generic + Amcache + ShimCache (sdílená regf magic)
    "registry_hive": (_extract_registry_all, REGISTRY_VERSION),
    "plist": (extract_plist_artifacts, PLIST_VERSION),
    # E6 Windows parsery vlna 1 — LNK + SuperFetch prefetch (MAM)
    "lnk": (extract_lnk_artifacts, LNK_VERSION),
    "win_prefetch": (extract_prefetch_artifacts, PREFETCH_VERSION),
    # E7 Windows Event Log (.evtx) — magic "EVTX" i ground-truth "ElfFile\0"
    "evtx": (extract_evtx_artifacts, EVTX_VERSION),
}


NAME_BASED_EXTRACTORS: dict[str, tuple[Callable[[Path], list], str]] = {
    "icloud_messages": (extract_icloud_messages, IMESSAGE_CLOUD_VERSION),
    # E6 Jump Lists — .customDestinations-ms kontejnery (magic je jen u32 version)
    "win_jumplist": (extract_jump_list_artifacts, JUMPLIST_VERSION),
    # E7 NTFS USN Journal ($UsnJrnl) — metadata file bez spolehlivé magiky
    "win_usn": (extract_usn_artifacts, USN_VERSION),
    # ETAPA B vlna 1 — AXIOM port: email / WiFi / Scheduled Tasks / netstat
    "email_mbox": (extract_email_artifacts, EMAIL_MBOX_VERSION),
    "wifi_wlan": (extract_wifi_artifacts, WLAN_VERSION),
    "win_schedtask": (extract_scheduled_task_artifacts, SCHEDTASK_VERSION),
    "net_connections": (extract_netstat_artifacts, NETSTAT_VERSION),
    # ETAPA B vlna 2 — AXIOM port: Google lokální profily + scan outputy + CurrentTabs + MSN
    "google_search_history": (extract_google_search_artifacts, GOOGLE_SEARCH_VERSION),
    "google_location_history": (extract_location_artifacts, GOOGLE_LOC_VERSION),
    "google_login_history": (extract_login_artifacts, GOOGLE_LOGIN_VERSION),
    "google_account_info": (extract_account_artifacts, GOOGLE_ACCT_VERSION),
    "mem_scan": (extract_mem_scan_artifacts, MEMSCAN_VERSION),
    "ddg_current_tabs": (extract_current_tabs_artifacts, DDG_TABS_VERSION),
    "msn_messenger": (extract_msn_artifacts, MSN_VERSION),
    # ETAPA B vlna 3 — AXIOM port: legacy mobile/messenger (Bebo, Chatroulette, Mail.ru, P2P)
    "bebo_chat": (extract_bebo_artifacts, BEBO_CHAT_VERSION),
    "chatroulette": (extract_chatroulette_artifacts, CHATROULETTE_VERSION),
    "mailru_agent": (extract_mailru_artifacts, MAILRU_AGENT_VERSION),
    "limewire_p2p": (extract_shared_files_artifacts, LIMEWIRE_P2P_VERSION),
    # ETAPA B vlna 4 — AXIOM port: DDG allowlisted websites + OpenOffice Base (.odb)
    "allowlisted_websites": (extract_allowlisted_websites_artifacts, ALLOWLISTED_WEBSITES_VERSION),
    "openoffice_base": (extract_openoffice_base_artifacts, OPENOFFICE_BASE_VERSION),
    # ETAPA B vlna 15 — SIM TPDU phonebook (AT+CPBR textový export)
    "sim_tpdu": (extract_tpdu_artifacts, SIM_TPDU_VERSION),
    # K2 — crypto forensics (Electrum/MetaMask wallets, exchange CSV, content scan)
    "crypto_extract": (extract_crypto_artifacts, CRYPTO_EXTRACT_VERSION),
    # ETAPA B vlna 5 — AXIOM port: Google Takeout rodina + Drive activity
    "google_aggregated_activities": (
        extract_aggregated_activities_artifacts,
        GOOGLE_AGGREGATED_VERSION,
    ),
    "google_identity_sessions": (extract_identity_sessions_artifacts, GOOGLE_AGGREGATED_VERSION),
    "google_maps_activity": (extract_maps_activity_artifacts, GOOGLE_MAPS_ACTIVITY_VERSION),
    "google_chat_family": (extract_google_chat_artifacts, GOOGLE_CHAT_FAMILY_VERSION),
    "google_account_change_history": (
        extract_account_change_history_artifacts,
        GOOGLE_ACCOUNT_META_VERSION,
    ),
    "google_linked_devices": (extract_linked_devices_artifacts, GOOGLE_ACCOUNT_META_VERSION),
    "google_export_summary": (extract_export_summary_artifacts, GOOGLE_ACCOUNT_META_VERSION),
    "drive_activity": (extract_drive_activity_artifacts, DRIVE_ACTIVITY_VERSION),
    # ETAPA B vlna 6 — AXIOM port: Google Photos + Mail Message Information (WarrantReturn)
    "google_photos": (extract_photos_artifacts, GOOGLE_PHOTOS_VERSION),
    "google_mail_info": (extract_mail_info_artifacts, GOOGLE_MAIL_INFO_VERSION),
    # ETAPA B vlna 7 — AXIOM port: Chrome Bookmarks/History/Autofill + Contacts + Skype WR
    "chrome_bookmarks": (extract_bookmarks_artifacts, CHROME_BOOKMARKS_VERSION),
    "chrome_history_wr": (extract_chrome_history_wr_artifacts, CHROME_HISTORY_WR_VERSION),
    "contacts_wr": (extract_contacts_wr_artifacts, CONTACTS_WR_VERSION),
    "chrome_autofill": (extract_chrome_autofill_artifacts, CHROME_AUTOFILL_VERSION),
    "skype_warrant": (extract_skype_artifacts, SKYPE_WR_VERSION),
    # ETAPA B vlna 8 — AXIOM port: Chrome prefs/sync + cloud drive soubory + Google Voice WR + drivers
    "chrome_preferences": (extract_chrome_pref_artifacts, CHROME_PREFS_VERSION),
    "cloud_drive_files": (extract_cloud_drive_artifacts, CLOUD_DRIVE_FILES_VERSION),
    "google_voice_wr": (extract_google_voice_artifacts, GOOGLE_VOICE_WR_VERSION),
    "win_drivers": (extract_win_driver_artifacts, WIN_DRIVERS_VERSION),
    # ETAPA B vlna 9 — AXIOM port: memory forensics (procesy/spojení/handlery/moduly/hooks)
    "mem_processes": (extract_mem_process_artifacts, MEM_PROCESSES_VERSION),
    "mem_network": (extract_mem_connection_artifacts, MEM_NETWORK_VERSION),
    "mem_handles": (extract_mem_handle_artifacts, MEM_HANDLES_VERSION),
    "mem_modules": (extract_mem_module_artifacts, MEM_MODULES_VERSION),
    "mem_hooks": (extract_mem_hook_artifacts, MEM_HOOKS_VERSION),
    # ETAPA B vlna 10 — cloud SNS exporty (Instagram/Snapchat)
    "instagram_messages": (extract_instagram_message_artifacts, INSTAGRAM_MESSAGES_VERSION),
    "instagram_posts": (extract_instagram_post_artifacts, INSTAGRAM_POSTS_VERSION),
    "instagram_account": (extract_instagram_account_artifacts, INSTAGRAM_ACCOUNT_VERSION),
    "snapchat_wr": (extract_snapchat_artifacts, SNAPCHAT_WR_VERSION),
    # ETAPA B vlna 11 — cloud SNS rodina Twitter/X + Facebook
    "twitter_posts": (extract_twitter_post_artifacts, TWITTER_POSTS_VERSION),
    "twitter_messages": (extract_twitter_message_artifacts, TWITTER_MESSAGES_VERSION),
    "twitter_users": (extract_twitter_user_artifacts, TWITTER_USERS_VERSION),
    "facebook_wr": (extract_facebook_artifacts, FACEBOOK_WR_VERSION),
    # ETAPA B vlna 12 — cloud-export rodina Microsoft + Amazon
    "ms_contacts": (extract_ms_contact_artifacts, MS_CONTACTS_VERSION),
    "ms_mail_pst": (extract_ms_mail_artifacts, MS_MAIL_PST_VERSION),
    "ms_teams_conversations": (
        extract_teams_conversation_artifacts,
        MS_TEAMS_CONVERSATIONS_VERSION,
    ),
    "ms_teams_teams": (extract_teams, MS_TEAMS_TEAMS_VERSION),
    "ms_outlook_calendar": (
        extract_outlook_calendar_artifacts,
        MS_OUTLOOK_CALENDAR_VERSION,
    ),
    "sharepoint_wr": (extract_sharepoint_artifacts, SHAREPOINT_WR_VERSION),
    "amazon_cloudtrail": (extract_cloudtrail_artifacts, AMAZON_CLOUDTRAIL_VERSION),
    "amazon_ec2_s3": (extract_amazon_ec2_s3_artifacts, AMAZON_EC2_S3_VERSION),
    # ETAPA B vlna 13 — cloud-export rodina Google II + Box/Dropbox/Mega
    "google_calendar_events": (
        extract_google_calendar_artifacts,
        GOOGLE_CALENDAR_EVENTS_VERSION,
    ),
    "google_keep_tasks": (extract_google_keep_artifacts, GOOGLE_KEEP_TASKS_VERSION),
    "box_cloud": (extract_box_artifacts, BOX_CLOUD_VERSION),
    "dropbox_mega": (extract_dropbox_mega_artifacts, DROPBOX_MEGA_VERSION),
    # ETAPA B vlna 14 — dokončení cloud-export: Apple rodina + Google 2025 WR + WhatsApp
    # + generic cloud metadata + Gmail Messages + Maps Labeled Places
    "apple_cloud": (extract_apple_cloud_artifacts, APPLE_CLOUD_VERSION),
    "google_2025_wr": (extract_google_2025_artifacts, GOOGLE_2025_WR_VERSION),
    "whatsapp_cloud": (extract_whatsapp_artifacts, WHATSAPP_CLOUD_VERSION),
    "cloud_generic": (extract_cloud_generic_artifacts, CLOUD_GENERIC_VERSION),
    "gmail_messages": (extract_gmail_artifacts, GMAIL_MESSAGES_VERSION),
    "maps_labeled_places": (
        extract_maps_labeled_artifacts,
        MAPS_LABELED_PLACES_VERSION,
    ),
}
