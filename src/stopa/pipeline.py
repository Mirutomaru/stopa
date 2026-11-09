"""STOPA pipeline — jediný analyze() entrypoint sdílený CLI i web GUI.

Postup (FTK-style processing):
1. walk zdroje → WalkedFile záznamy
2. pro každý soubor: hashy podle profilu + signatura (magic bytes)
3. bad extension check, dedupe napříč případem, known-bad hash sets
4. upsert do case DB + ProcessResult summary

Jeden kódový průchod pro CLI i web — jedna cesta k debugování.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

import stopa as _stopa_pkg  # __version__ (single-source z pyproject)
from stopa.artifacts.allowlisted_websites import PARSER_VERSION as ALLOWLISTED_WEBSITES_VERSION
from stopa.artifacts.allowlisted_websites import (
    extract_allowlisted_websites_artifacts,
    is_allowlisted_websites_file,
)
from stopa.artifacts.amazon_cloudtrail import PARSER_VERSION as AMAZON_CLOUDTRAIL_VERSION
from stopa.artifacts.amazon_cloudtrail import (
    extract_cloudtrail_artifacts,
    is_amazon_cloudtrail_file,
)
from stopa.artifacts.amazon_ec2_s3 import PARSER_VERSION as AMAZON_EC2_S3_VERSION
from stopa.artifacts.amazon_ec2_s3 import (
    extract_amazon_ec2_s3_artifacts,
    is_amazon_ec2_s3_file,
)
from stopa.artifacts.apple_cloud import PARSER_VERSION as APPLE_CLOUD_VERSION
from stopa.artifacts.apple_cloud import extract_apple_cloud_artifacts, is_apple_file
from stopa.artifacts.bebo_chat import PARSER_VERSION as BEBO_CHAT_VERSION
from stopa.artifacts.bebo_chat import extract_bebo_artifacts, is_bebo_chat_file
from stopa.artifacts.box_cloud import PARSER_VERSION as BOX_CLOUD_VERSION
from stopa.artifacts.box_cloud import (
    extract_box_artifacts,
    is_box_file,
)
from stopa.artifacts.chatroulette import PARSER_VERSION as CHATROULETTE_VERSION
from stopa.artifacts.chatroulette import (
    extract_chatroulette_artifacts,
    is_chatroulette_file,
)
from stopa.artifacts.chrome_preferences import PARSER_VERSION as CHROME_PREFS_VERSION
from stopa.artifacts.chrome_preferences import (
    extract_chrome_pref_artifacts,
    is_chrome_preferences_file,
)
from stopa.artifacts.cloud_drive_files import PARSER_VERSION as CLOUD_DRIVE_FILES_VERSION
from stopa.artifacts.cloud_drive_files import (
    extract_cloud_drive_artifacts,
    is_cloud_drive_file,
)
from stopa.artifacts.cloud_generic import PARSER_VERSION as CLOUD_GENERIC_VERSION
from stopa.artifacts.cloud_generic import (
    extract_cloud_generic_artifacts,
    is_cloud_generic_file,
)
from stopa.artifacts.ddg_current_tabs import PARSER_VERSION as DDG_TABS_VERSION
from stopa.artifacts.ddg_current_tabs import extract_current_tabs_artifacts, is_current_tabs_file
from stopa.artifacts.drive_activity import PARSER_VERSION as DRIVE_ACTIVITY_VERSION
from stopa.artifacts.drive_activity import (
    extract_drive_activity_artifacts,
    is_drive_activity_file,
)
from stopa.artifacts.dropbox_mega import PARSER_VERSION as DROPBOX_MEGA_VERSION
from stopa.artifacts.dropbox_mega import (
    extract_dropbox_mega_artifacts,
    is_dropbox_file,
    is_mega_file,
)
from stopa.artifacts.email_mbox import PARSER_VERSION as EMAIL_MBOX_VERSION
from stopa.artifacts.email_mbox import extract_email_artifacts, is_email_file
from stopa.artifacts.facebook_wr import PARSER_VERSION as FACEBOOK_WR_VERSION
from stopa.artifacts.facebook_wr import extract_facebook_artifacts, is_facebook_file
from stopa.artifacts.gmail_messages import PARSER_VERSION as GMAIL_MESSAGES_VERSION
from stopa.artifacts.gmail_messages import extract_gmail_artifacts, is_gmail_file
from stopa.artifacts.google_2025_wr import PARSER_VERSION as GOOGLE_2025_WR_VERSION
from stopa.artifacts.google_2025_wr import (
    extract_google_2025_artifacts,
    is_google_2025_file,
)
from stopa.artifacts.google_account_info import PARSER_VERSION as GOOGLE_ACCT_VERSION
from stopa.artifacts.google_account_info import extract_account_artifacts, is_account_info_file
from stopa.artifacts.google_account_meta import (
    PARSER_VERSION as GOOGLE_ACCOUNT_META_VERSION,
)
from stopa.artifacts.google_account_meta import (
    extract_account_change_history_artifacts,
    extract_export_summary_artifacts,
    extract_linked_devices_artifacts,
    is_account_change_history_file,
    is_export_summary_file,
    is_linked_devices_file,
)
from stopa.artifacts.google_aggregated_activities import (
    PARSER_VERSION as GOOGLE_AGGREGATED_VERSION,
)
from stopa.artifacts.google_aggregated_activities import (
    extract_aggregated_activities_artifacts,
    extract_identity_sessions_artifacts,
    is_aggregated_activities_file,
    is_identity_sessions_file,
)
from stopa.artifacts.google_calendar_events import (
    PARSER_VERSION as GOOGLE_CALENDAR_EVENTS_VERSION,
)
from stopa.artifacts.google_calendar_events import (
    extract_google_calendar_artifacts,
    is_google_calendar_file,
)
from stopa.artifacts.google_chat_family import PARSER_VERSION as GOOGLE_CHAT_FAMILY_VERSION
from stopa.artifacts.google_chat_family import (
    extract_google_chat_artifacts,
    is_google_chat_file,
)
from stopa.artifacts.google_chrome_autofill import (
    PARSER_VERSION as CHROME_AUTOFILL_VERSION,
)
from stopa.artifacts.google_chrome_autofill import (
    extract_chrome_autofill_artifacts,
    is_chrome_autofill_file,
)
from stopa.artifacts.google_chrome_bookmarks import (
    PARSER_VERSION as CHROME_BOOKMARKS_VERSION,
)
from stopa.artifacts.google_chrome_bookmarks import (
    extract_bookmarks_artifacts,
    is_chrome_bookmarks_file,
)
from stopa.artifacts.google_chrome_history_wr import (
    PARSER_VERSION as CHROME_HISTORY_WR_VERSION,
)
from stopa.artifacts.google_chrome_history_wr import (
    extract_chrome_history_wr_artifacts,
    is_chrome_history_wr_file,
)
from stopa.artifacts.google_contacts_wr import PARSER_VERSION as CONTACTS_WR_VERSION
from stopa.artifacts.google_contacts_wr import (
    extract_contacts_wr_artifacts,
    is_contacts_wr_file,
)
from stopa.artifacts.google_keep_tasks import PARSER_VERSION as GOOGLE_KEEP_TASKS_VERSION
from stopa.artifacts.google_keep_tasks import (
    extract_google_keep_artifacts,
    is_google_keep_file,
)
from stopa.artifacts.google_location_history import (
    PARSER_VERSION as GOOGLE_LOC_VERSION,
)
from stopa.artifacts.google_location_history import (
    extract_location_artifacts,
    is_location_history_file,
)
from stopa.artifacts.google_login_history import PARSER_VERSION as GOOGLE_LOGIN_VERSION
from stopa.artifacts.google_login_history import extract_login_artifacts, is_login_history_file
from stopa.artifacts.google_mail_info import PARSER_VERSION as GOOGLE_MAIL_INFO_VERSION
from stopa.artifacts.google_mail_info import (
    extract_mail_info_artifacts,
    is_mail_info_file,
)
from stopa.artifacts.google_maps_activity import PARSER_VERSION as GOOGLE_MAPS_ACTIVITY_VERSION
from stopa.artifacts.google_maps_activity import (
    extract_maps_activity_artifacts,
    is_maps_activity_file,
)
from stopa.artifacts.google_photos import PARSER_VERSION as GOOGLE_PHOTOS_VERSION
from stopa.artifacts.google_photos import extract_photos_artifacts, is_photos_file
from stopa.artifacts.google_search_history import (
    PARSER_VERSION as GOOGLE_SEARCH_VERSION,
)
from stopa.artifacts.google_search_history import (
    extract_google_search_artifacts,
    is_google_search_history_file,
)
from stopa.artifacts.google_voice_wr import PARSER_VERSION as GOOGLE_VOICE_WR_VERSION
from stopa.artifacts.google_voice_wr import (
    extract_google_voice_artifacts,
    is_google_voice_file,
)
from stopa.artifacts.imessage_cloud import (
    PARSER_VERSION as IMESSAGE_CLOUD_VERSION,
)
from stopa.artifacts.imessage_cloud import extract_icloud_messages, is_icloud_messages_file
from stopa.artifacts.instagram_account import PARSER_VERSION as INSTAGRAM_ACCOUNT_VERSION
from stopa.artifacts.instagram_account import (
    extract_instagram_account_artifacts,
    is_instagram_account_file,
)
from stopa.artifacts.instagram_messages import PARSER_VERSION as INSTAGRAM_MESSAGES_VERSION
from stopa.artifacts.instagram_messages import (
    extract_instagram_message_artifacts,
    is_instagram_messages_file,
)
from stopa.artifacts.instagram_posts import PARSER_VERSION as INSTAGRAM_POSTS_VERSION
from stopa.artifacts.instagram_posts import (
    extract_instagram_post_artifacts,
    is_instagram_posts_file,
)
from stopa.artifacts.limewire_p2p import PARSER_VERSION as LIMEWIRE_P2P_VERSION
from stopa.artifacts.limewire_p2p import (
    extract_shared_files_artifacts,
    is_limewire_family_file,
)
from stopa.artifacts.mailru_agent import PARSER_VERSION as MAILRU_AGENT_VERSION
from stopa.artifacts.mailru_agent import extract_mailru_artifacts, is_mailru_file
from stopa.artifacts.maps_labeled_places import (
    PARSER_VERSION as MAPS_LABELED_PLACES_VERSION,
)
from stopa.artifacts.maps_labeled_places import (
    extract_maps_labeled_artifacts,
    is_maps_labeled_file,
)
from stopa.artifacts.mem_handles import PARSER_VERSION as MEM_HANDLES_VERSION
from stopa.artifacts.mem_handles import extract_mem_handle_artifacts, is_mem_handles_file
from stopa.artifacts.mem_hooks import PARSER_VERSION as MEM_HOOKS_VERSION
from stopa.artifacts.mem_hooks import extract_mem_hook_artifacts, is_mem_hooks_file
from stopa.artifacts.mem_modules import PARSER_VERSION as MEM_MODULES_VERSION
from stopa.artifacts.mem_modules import extract_mem_module_artifacts, is_mem_modules_file
from stopa.artifacts.mem_network import PARSER_VERSION as MEM_NETWORK_VERSION
from stopa.artifacts.mem_network import extract_mem_connection_artifacts, is_mem_network_file
from stopa.artifacts.mem_processes import PARSER_VERSION as MEM_PROCESSES_VERSION
from stopa.artifacts.mem_processes import extract_mem_process_artifacts, is_mem_processes_file
from stopa.artifacts.mem_scan import PARSER_VERSION as MEMSCAN_VERSION
from stopa.artifacts.mem_scan import extract_mem_scan_artifacts, is_mem_scan_file
from stopa.artifacts.ms_contacts import PARSER_VERSION as MS_CONTACTS_VERSION
from stopa.artifacts.ms_contacts import (
    extract_ms_contact_artifacts,
    is_ms_contacts_file,
)
from stopa.artifacts.ms_mail_pst import PARSER_VERSION as MS_MAIL_PST_VERSION
from stopa.artifacts.ms_mail_pst import extract_ms_mail_artifacts, is_ms_mail_file
from stopa.artifacts.ms_outlook_calendar import (
    PARSER_VERSION as MS_OUTLOOK_CALENDAR_VERSION,
)
from stopa.artifacts.ms_outlook_calendar import (
    extract_outlook_calendar_artifacts,
    is_ms_outlook_calendar_file,
)
from stopa.artifacts.ms_teams_conversations import (
    PARSER_VERSION as MS_TEAMS_CONVERSATIONS_VERSION,
)
from stopa.artifacts.ms_teams_conversations import (
    extract_teams_conversation_artifacts,
    is_ms_teams_conversations_file,
)
from stopa.artifacts.ms_teams_teams import PARSER_VERSION as MS_TEAMS_TEAMS_VERSION
from stopa.artifacts.ms_teams_teams import extract_teams, is_ms_teams_file
from stopa.artifacts.msn_messenger import PARSER_VERSION as MSN_VERSION
from stopa.artifacts.msn_messenger import extract_msn_artifacts, is_msn_chat_file
from stopa.artifacts.net_connections import PARSER_VERSION as NETSTAT_VERSION
from stopa.artifacts.net_connections import extract_netstat_artifacts, is_netstat_file
from stopa.artifacts.openoffice_base import PARSER_VERSION as OPENOFFICE_BASE_VERSION
from stopa.artifacts.openoffice_base import (
    extract_openoffice_base_artifacts,
    is_openoffice_base_file,
)
from stopa.artifacts.plist_extract import PARSER_VERSION as PLIST_VERSION
from stopa.artifacts.plist_extract import extract_plist_artifacts
from stopa.artifacts.registry_extract import PARSER_VERSION as REGISTRY_VERSION
from stopa.artifacts.registry_extract import extract_registry_artifacts
from stopa.artifacts.sharepoint_wr import PARSER_VERSION as SHAREPOINT_WR_VERSION
from stopa.artifacts.sharepoint_wr import (
    extract_sharepoint_artifacts,
    is_sharepoint_file,
)
from stopa.artifacts.skype_warrant_return import PARSER_VERSION as SKYPE_WR_VERSION
from stopa.artifacts.skype_warrant_return import (
    extract_skype_artifacts,
    is_skype_warrant_file,
)
from stopa.artifacts.snapchat_wr import PARSER_VERSION as SNAPCHAT_WR_VERSION
from stopa.artifacts.snapchat_wr import extract_snapchat_artifacts, is_snapchat_file
from stopa.artifacts.sqlite_extract import PARSER_VERSION as SQLITE_VERSION
from stopa.artifacts.sqlite_extract import extract_sqlite_artifacts
from stopa.artifacts.sqlite_recover import recover_deleted_rows
from stopa.artifacts.twitter_messages import PARSER_VERSION as TWITTER_MESSAGES_VERSION
from stopa.artifacts.twitter_messages import (
    extract_twitter_message_artifacts,
    is_twitter_messages_file,
)
from stopa.artifacts.twitter_posts import PARSER_VERSION as TWITTER_POSTS_VERSION
from stopa.artifacts.twitter_posts import (
    extract_twitter_post_artifacts,
    is_twitter_posts_file,
)
from stopa.artifacts.twitter_users import PARSER_VERSION as TWITTER_USERS_VERSION
from stopa.artifacts.twitter_users import (
    extract_twitter_user_artifacts,
    is_twitter_users_file,
)
from stopa.artifacts.whatsapp_cloud import PARSER_VERSION as WHATSAPP_CLOUD_VERSION
from stopa.artifacts.whatsapp_cloud import extract_whatsapp_artifacts, is_whatsapp_file
from stopa.artifacts.win_amcache import extract_amcache_artifacts
from stopa.artifacts.win_clipboard import extract_clipboard_artifacts
from stopa.artifacts.win_drivers import PARSER_VERSION as WIN_DRIVERS_VERSION
from stopa.artifacts.win_drivers import (
    extract_win_driver_artifacts,
    is_win_drivers_file,
)
from stopa.artifacts.win_eventlog import PARSER_VERSION as EVTX_VERSION
from stopa.artifacts.win_eventlog import extract_evtx_artifacts
from stopa.artifacts.win_jumplist import PARSER_VERSION as JUMPLIST_VERSION
from stopa.artifacts.win_jumplist import extract_jump_list_artifacts, is_jump_list_file
from stopa.artifacts.win_lnk import PARSER_VERSION as LNK_VERSION
from stopa.artifacts.win_lnk import extract_lnk_artifacts
from stopa.artifacts.win_prefetch import PARSER_VERSION as PREFETCH_VERSION
from stopa.artifacts.win_prefetch import extract_prefetch_artifacts
from stopa.artifacts.win_schedtask import (
    PARSER_VERSION as SCHEDTASK_VERSION,
)
from stopa.artifacts.win_schedtask import extract_scheduled_task_artifacts, is_scheduled_task_file
from stopa.artifacts.win_shimcache import extract_shimcache_artifacts
from stopa.artifacts.win_sids import extract_sid_artifacts
from stopa.artifacts.win_userassist import extract_userassist_artifacts
from stopa.artifacts.win_usn import (
    PARSER_VERSION as USN_VERSION,
)
from stopa.artifacts.win_usn import extract_usn_artifacts, is_usn_journal_file
from stopa.artifacts.win_wlan import PARSER_VERSION as WLAN_VERSION
from stopa.artifacts.win_wlan import extract_wifi_artifacts, is_wlan_profile_file
from stopa.data.db import CaseDB
from stopa.data.ingest import WalkedFile, walk_source
from stopa.domain.bad_extension import extension_of, is_bad_extension
from stopa.domain.dedupe import Deduper
from stopa.domain.entities import extract_entities
from stopa.domain.hashing import hash_bytes, hash_file
from stopa.domain.lineage import config_hash
from stopa.domain.profiles import get_profile
from stopa.domain.reproducibility import (
    AnalysisOperation,
    ReplayResult,
    compare_outputs,
    verify_inputs,
)
from stopa.domain.sandbox import (
    CATEGORY_BAD_PAYLOAD,
    CATEGORY_CRASH,
    SandboxConfig,
    SandboxResult,
    run_extractor_sandboxed,
    sandbox_available,
)
from stopa.domain.signatures import detect_signature
from stopa.domain.timeline_anomaly import AnomalyContext, detect_anomalies
from stopa.domain.timeline_intel import analyze_timeline
from stopa.models import Artifact, FileRecord, ProcessingProfile, ProcessResult

log = logging.getLogger("stopa.pipeline")

SIGNATURE_HEAD_BYTES = 65536  # stačí pro všechny signatury v hlavičce

# ETAPA E vlna 2 (STP-047) — parser sandbox: extraktory běží v dceřiném
# procesu s timeoutem, aby poškozený vstupní soubor nevisel a nepadl pipeline.
# Vypnutí pro debug / CI bez subprocessu: STOPA_SANDBOX=0 (fallback = přímé volání).
SANDBOX_ENABLED = os.environ.get("STOPA_SANDBOX", "1") != "0"
SANDBOX_CONFIG = SandboxConfig()  # defaultní limity (30 s / 16 MiB) z domain/sandbox.py


def _extract_sqlite_all(path: Path) -> list[Artifact]:
    """SQLite — aktivní řádky (schema matchery) + carving smazaných (.db + .wal).

    Obě cesty jsou nezávislé; jedna selže → log + prázdný výsledek, druhá běží dál.
    """
    arts = extract_sqlite_artifacts(path)
    try:
        arts.extend(recover_deleted_rows(path))
    except Exception as e:  # noqa: BLE001 — carving je bonus, nesmí potopit extrakci
        log.warning("SQLite recover %s: %s", path, e)
    return arts


def _extract_registry_all(path: Path) -> list[Artifact]:
    """Registry hive (regf) — generic + Amcache + ShimCache + Clipboard + SID + UserAssist.

    Všechny extraktory sdílejí `regf` magic → jeden kombinovaný dispatch
    (pattern jako `_extract_sqlite_all`). Každá cesta je nezávislá: Amcache
    běží jen na Amcache.hve, ShimCache jen na SYSTEM hive; bez příslušného
    klíče vrátí prázdný výsledek. ETAPA B vlna 1: + Clipboard (NTUSER.DAT)
    a SID extrakce (SAM/SECURITY/ProfileList). ETAPA B vlna 4: + UserAssist MRU
    (NTUSER.DAT — spuštěné aplikace / otevřené dokumenty).
    """
    arts = extract_registry_artifacts(path)
    try:
        arts.extend(extract_amcache_artifacts(path))
    except Exception as e:  # noqa: BLE001 — Amcache je bonus, nesmí potopit extrakci
        log.warning("Amcache %s: %s", path, e)
    try:
        arts.extend(extract_shimcache_artifacts(path))
    except Exception as e:  # noqa: BLE001 — ShimCache je bonus, nesmí potopit extrakci
        log.warning("ShimCache %s: %s", path, e)
    try:
        arts.extend(extract_clipboard_artifacts(path))
    except Exception as e:  # noqa: BLE001 — Clipboard je bonus (ETAPA B vlna 1)
        log.warning("Clipboard %s: %s", path, e)
    try:
        arts.extend(extract_sid_artifacts(path))
    except Exception as e:  # noqa: BLE001 — SID je bonus (ETAPA B vlna 1)
        log.warning("SID %s: %s", path, e)
    try:
        arts.extend(extract_userassist_artifacts(path))
    except Exception as e:  # noqa: BLE001 — UserAssist je bonus (ETAPA B vlna 4)
        log.warning("UserAssist %s: %s", path, e)
    return arts


# signatura → (extraktor, verze_parseru) — E1: verze se eviduje v audit logu.
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

# name-based fallback (AXIOM Hunter) — soubory bez spolehlivé magiky.
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
    return None


def parser_versions() -> dict[str, str]:
    """Verze všech registrovaných parserů — pro audit log (reprodukovatelnost)."""
    return {sig: ver for sig, (_fn, ver) in ARTIFACT_EXTRACTORS.items()} | {
        name: ver for name, (_fn, ver) in NAME_BASED_EXTRACTORS.items()
    }


def summarize_outputs(result: ProcessResult) -> dict:
    """Deterministický souhrn výsledku pro porovnání při replay (P0 Core C5).

    Obsahuje jen stabilní počty — ne ID ani časy, aby stejný vstup na stejném
    prostředí vždy dal stejný souhrn (determinismus porovnání).
    """
    return {
        "files_total": result.files_total,
        "bytes_total": result.bytes_total,
        "hashed_md5": result.hashed_md5,
        "hashed_sha256": result.hashed_sha256,
        "signatures_detected": result.signatures_detected,
        "bad_extensions": result.bad_extensions,
        "duplicates": result.duplicates,
        "hash_set_hits": result.hash_set_hits,
        "artifacts_extracted": result.artifacts_extracted,
        "errors": len(result.errors),
    }


def _parser_error_artifact(
    fn: Callable[[Path], list[Artifact]], ver: str | None, res: SandboxResult
) -> Artifact:
    """Selhání parseru → ``parser_error`` artifact (ETAPA E vlna 2, STP-047).

    Pipeline nepadne — selhání je záznam s kategorií z ``SandboxResult``
    (timeout | truncated | bad_payload | crash) pro audit log.
    """
    category = res.category or CATEGORY_CRASH
    return Artifact(
        artifact_type="parser_error",
        title=f"parser selhal ({category})",
        details={
            "category": category,
            "error": res.error or "",
            "parser": f"{fn.__module__}.{fn.__name__}",
        },
        parser_version=ver,
    )


def _run_extractor(
    fn: Callable[[Path], list[Artifact]], path: Path, ver: str | None
) -> list[Artifact]:
    """Jeden extraktor — přes sandbox subprocess (default) nebo přímo.

    ETAPA E vlna 2 (STP-047): poškozený vstupní soubor nesmí viset ani
    crashnout celou pipeline. Sandbox běží parser v dceřiném procesu s
    timeoutem; selhání → ``parser_error`` artifact s kategorií z
    ``SandboxResult``. Fallback (sandbox vypnutý / worker nedostupný) =
    přímé volání, původní chování.
    """
    if SANDBOX_ENABLED and sandbox_available():
        res = run_extractor_sandboxed(fn.__module__, fn.__name__, path, SANDBOX_CONFIG)
        if res.ok:
            try:
                return [Artifact.model_validate(d) for d in res.artifacts]
            except ValidationError as e:  # payload prošel strukturou, ale ne modelem
                log.warning(
                    "sandbox parser %s.%s — model validace selhala: %s",
                    fn.__module__,
                    fn.__name__,
                    e,
                )
                return [
                    _parser_error_artifact(
                        fn,
                        ver,
                        SandboxResult(ok=False, category=CATEGORY_BAD_PAYLOAD, error=str(e)),
                    )
                ]
        log.warning(
            "sandbox parser %s.%s selhal (%s): %s",
            fn.__module__,
            fn.__name__,
            res.category,
            res.error,
        )
        return [_parser_error_artifact(fn, ver, res)]
    # fallback — přímé volání (STOPA_SANDBOX=0 nebo worker modul chybí)
    return fn(path)


def _extract_artifacts_for(
    path: Path, signature_type: str | None
) -> tuple[list[Artifact], str | None]:
    """Artifact extraktoři pro jeden soubor — signatura PŘED name-based fallbackem.

    AXIOM Hunter pattern: iCloud Messages export (`MessagesInICloud.csv`) nemá
    spolehlivou magic (XLSX je generic OOXML, delimited text žádnou), proto se
    detekuje podle názvu souboru — jen když signatura nic nenašla.

    Vrací ``(artifacts, parser_version)`` — verze se eviduje na každém artifactu
    (E2 provenience / reprodukovatelnost). Bez extraktoru → ``([], None)``.

    ETAPA E vlna 2 (STP-047): všechny cesty běží přes ``_run_extractor`` —
    sandbox subprocess s timeoutem; selhání parseru → ``parser_error`` artifact
    (pipeline nepadne). Fallback bez sandboxu = přímé volání.
    """
    if signature_type in ARTIFACT_EXTRACTORS:
        fn, ver = ARTIFACT_EXTRACTORS[signature_type]
        return _run_extractor(fn, path, ver), ver
    # ETAPA B vlna 10 — cloud SNS (Instagram/Snapchat): generic basenames kolidují
    # s Google detektory → pre-pass na celé cestě PŘED basename chainem.
    sns_match = _sns_prepass(str(path))
    if sns_match is not None:
        fn, ver = sns_match
        return _run_extractor(fn, path, ver), ver
    name_match = _name_based_match(path.name)  # name-based fallback (AXIOM Hunter)
    if name_match is None:
        # ETAPA B vlna 8 — Takeout soubory se generic názvy (Drive/Files.json, Voice/Texts.json):
        # klíčové slovo je v rodičovské složce → retry na celé cestě. Parsery jsou
        # defenzivní (ne-JSON → []), takže cizí soubory jen projdou bez artifactů.
        name_match = _name_based_match(str(path))
    if name_match is not None:
        fn, ver = name_match
        return _run_extractor(fn, path, ver), ver
    return [], None


def _read_head(path: Path) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read(SIGNATURE_HEAD_BYTES)
    except OSError as e:
        log.warning("signatura — nelze číst %s: %s", path, e)
        return b""


@dataclass
class _FileWork:
    """E3 paralelizace: výsledek worker vlákna pro jeden soubor (bez DB).

    DB writes + dedupe zůstávají v hlavním vlákně — pořadí zpracování určuje
    originál vs. duplikát (FTK hide duplicates), takže musí být deterministické.
    """

    rec: FileRecord
    artifacts: list[Artifact] = field(default_factory=list)
    parser_version: str | None = None
    error: str | None = None  # hashing OSError — soubor se upsertuje bez hashů


def _process_file_worker(
    wf: WalkedFile,
    abs_path: Path,
    source_id: str,
    profile: ProcessingProfile,
    normalized_sets: dict[str, set[str]],
) -> _FileWork:
    """Hashing + signatura + bad ext + hash sets + artifact extraktoři (bez DB).

    Drahé operace (disk IO + CPU hashing + parsery) běží v worker vláknech;
    ``hashlib`` i ``sqlite3`` uvolňují GIL, takže se vláknům reálně překrývají.
    """
    rec = FileRecord(
        source_id=source_id,
        rel_path=wf.rel_path,
        name=wf.name,
        size_bytes=wf.size_bytes,
        mtime=wf.mtime,
        ctime=wf.ctime,
        atime=wf.atime,
    )

    # ── hashing podle profilu ────────────────────────────
    algs: list[str] = []
    if profile.compute_md5:
        algs.append("md5")
    if profile.compute_sha1:
        algs.append("sha1")
    if profile.compute_sha256:
        algs.append("sha256")
    if profile.compute_sha512:  # STP-022 — SHA-512 (forensic profil)
        algs.append("sha512")
    hash_error: str | None = None
    try:
        if algs and wf.size_bytes > 0:
            digests = hash_file(abs_path, algs)
            rec.md5 = digests.get("md5")
            rec.sha256 = digests.get("sha256")
            rec.sha512 = digests.get("sha512")
        elif algs:  # prázdný soubor — platné prázdné digesty
            digests = hash_bytes(b"", algs)
            rec.md5 = digests.get("md5")
            rec.sha256 = digests.get("sha256")
            rec.sha512 = digests.get("sha512")
    except OSError as e:
        # hashing selhal (IO) — soubor se upsertuje bez hashů, ale signatura +
        # artifacts se zkouší dál (původní sekvenční chování — IO chyba nemusí
        # znemožnit čtení hlavičky / parsery).
        hash_error = f"{wf.rel_path}: {e}"

    # ── signatura (magic bytes) ──────────────────────────
    if profile.signature_analysis and wf.size_bytes > 0:
        sig = detect_signature(_read_head(abs_path))
        if sig is not None:
            rec.signature_type, _family = sig

    # ── bad extension (FTK Flag Bad Extensions) ─────────
    rec.extension = extension_of(wf.name)
    if profile.flag_bad_extensions and rec.signature_type is not None:
        rec.bad_extension = is_bad_extension(rec.signature_type, wf.name)

    # ── known-bad hash sets (FTK) — MD5 i SHA-256 sety ───
    if profile.match_hash_sets and normalized_sets:
        for digest in (rec.sha256, rec.md5):
            if digest is None:
                continue
            for name, hashes in normalized_sets.items():
                if digest.lower() in hashes:
                    rec.hash_set_hit = name
                    break
            if rec.hash_set_hit:
                break

    # ── artifact extraktoři (AXIOM-style) — signatura → extraktor (+ name fallback) ──
    arts: list[Artifact] = []
    parser_ver: str | None = None
    if profile.extract_artifacts:
        arts, parser_ver = _extract_artifacts_for(abs_path, rec.signature_type)

    return _FileWork(
        rec=rec, artifacts=arts, parser_version=parser_ver, error=hash_error
    )


def process_source(
    db: CaseDB,
    source_id: str,
    root: Path,
    profile_name: str = "forensic",
    hash_sets: dict[str, set[str]] | None = None,
    progress: Callable[[int, int], None] | None = None,
    resume: bool = False,
    max_workers: int | None = None,
) -> ProcessResult:
    """Zpracuje jeden evidence source daným processing profilem.

    `hash_sets` — {název_setu: množina_hashů} (FTK known-bad sets; malá hex).
    `progress` — callback (soubory_hotovo, souborů_celkem) po každém souboru.
    `resume` — E3 checkpointing: přeskočí soubory už v DB pro tento zdroj
        (předchozí běh byl dokončený); doplní jen nové soubory a timeline se
        nečistí. Default False = plný re-ingest (idempotentní upsert).
    `max_workers` — E3 paralelizace: počet worker vláken pro hashing/parsing;
        None = auto (min(8, cpu_count)). DB writes + dedupe zůstávají v hlavním
        vlákně → deterministický výsledek nezávislý na počtu vláken.
    """
    profile = get_profile(profile_name)
    result = ProcessResult(source_id=source_id, profile=profile.name)
    _t0 = time.monotonic()  # P0 Core C5: čas zpracování operace (reproducibility)

    # E1 Evidence Manager: neměnná stopa operací (provenience — SWGDE-style)
    db.log_operation(
        "processing_started",
        details={"source_id": source_id, "profile": profile_name},
    )

    walked = walk_source(root)
    total = len(walked)

    # E3 checkpointing (resume): soubory už v DB pro tento zdroj se přeskočí —
    # předchozí běh je dokončený, neděláme hashing/parsing znovu. Timeline se
    # nečistí (události z prvního běhu jsou platné), doplníme jen nové soubory.
    if resume:
        existing_paths = {
            r["rel_path"]
            for r in db.conn.execute(
                "SELECT rel_path FROM files WHERE source_id = ?", (source_id,)
            ).fetchall()
        }
        to_process = [wf for wf in walked if wf.rel_path not in existing_paths]
    else:
        to_process = list(walked)

    skipped = total - len(to_process)  # E3 resume — hotové z předchozího běhu
    if progress is not None:
        progress(skipped, total)

    # dedupe napříč celým případem — seed z DB (jiné zdroje / předchozí běhy)
    # oba hashy: SHA-256 profily i MD5-only (FTK eDiscovery); STP-022: +SHA-512
    deduper = Deduper()
    existing = db.conn.execute("SELECT sha256, md5, sha512, rel_path FROM files").fetchall()
    deduper.seed(
        [(r["sha256"], r["rel_path"]) for r in existing]
        + [(r["md5"], r["rel_path"]) for r in existing]
        + [(r["sha512"], r["rel_path"]) for r in existing]
    )

    # hash sets — normalizace na malá hex pro rychlé porovnání
    normalized_sets: dict[str, set[str]] = {}
    if profile.match_hash_sets and hash_sets:
        for name, hashes in hash_sets.items():
            normalized_sets[name] = {h.lower() for h in hashes}

    root_resolved = root.resolve()

    # E2 Timeline Engine — kontext pro detekci nesrovnalostí.
    # Operační okno (min/max) se seeduje ze stavu DB a průběžně rozšiřuje;
    # seen_timestamps naplňuje duplikát detekci během běhu.
    now_utc = datetime.now(timezone.utc)
    win = db.timeline_window(source_id=source_id)
    anomaly_ctx = AnomalyContext(
        window_start=win.get("window_start"),
        window_end=win.get("window_end"),
    )
    # re-ingest stejného zdroje → čisté timeline (idempotence, žádné duplicitní události).
    # E3 resume: nečistíme — události z předchozího běhu jsou platné, doplníme jen nové.
    if not resume:
        db.clear_timeline_events(source_id=source_id)

    # E3 paralelizace: drahé operace (hashing + signatura + parsery) běží v
    # worker vláknech; DB writes + dedupe zůstávají v hlavním vlákně v pořadí
    # procházky → deterministický originál vs. duplikát (FTK hide duplicates).
    n = len(to_process)
    if max_workers is None:
        workers = min(8, os.cpu_count() or 4) if n > 1 else 1
    else:
        workers = max(1, max_workers)

    def _abs(wf: WalkedFile) -> Path:
        return root_resolved / wf.rel_path if not root.is_file() else root_resolved

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _process_file_worker, wf, _abs(wf), source_id, profile, normalized_sets
            )
            for wf in to_process
        ]
        # konzumace v pořadí procházky — DB writes + dedupe deterministické
        for i, (wf, fut) in enumerate(zip(to_process, futures)):
            work = fut.result()
            rec = work.rec

            result.files_total += 1
            result.bytes_total += wf.size_bytes
            if work.error is not None:
                result.errors.append(work.error)
            else:
                result.hashed_md5 += int(rec.md5 is not None)
                result.hashed_sha256 += int(rec.sha256 is not None)

            # signatura — worker ji detekoval; počítáme jen pokud je nastavena
            if rec.signature_type is not None:
                result.signatures_detected += 1
            if rec.bad_extension:
                result.bad_extensions += 1

            # ── dedupe napříč případem (FTK Advanced De-duplication) ──
            # hlavní vlákno, pořadí procházky → deterministický originál
            if profile.deduplicate:
                # SHA-256 profily i MD5-only (eDiscovery); STP-022: +SHA-512
                for digest in (rec.sha256, rec.md5, rec.sha512):
                    original = deduper.check_and_register(digest, wf.rel_path)
                    if original is not None:
                        rec.is_duplicate_of = original
                        result.duplicates += 1
                        break

            # ── known-bad hash sets — worker jen nastaví flag, tady počítáme ──
            if rec.hash_set_hit:
                result.hash_set_hits += 1

            # kanonický file id — při re-ingestu se drží původní řádek (FK stability)
            file_id = db.upsert_file(rec)  # nejdřív soubor — FK pro artifacts níže

            # ── artifact extraktoři — worker je už extrahoval, tady jen DB + timeline ──
            if profile.extract_artifacts:
                arts = work.artifacts
                parser_ver = work.parser_version
                for a in arts:
                    a.source_id = source_id
                    a.file_id = file_id
                    a.rel_path = wf.rel_path
                    # E2 Timeline Engine — provenience (reprodukovatelnost analýzy):
                    # kdy byl artifact extrahován + jakou verzí parseru.
                    if a.extracted_at is None:
                        a.extracted_at = now_utc
                    if a.parser_version is None and parser_ver is not None:
                        a.parser_version = parser_ver
                db.replace_artifacts_for_file(file_id, arts)
                result.artifacts_extracted += len(arts)
                # P0 Core C2: Evidence Lineage — output_refs kroku extract (ID artefaktů)
                result.extracted_artifact_ids.extend(a.id for a in arts)

                # E2 Timeline Engine — materializace timeline + detekce nesrovnalostí.
                for a in arts:
                    if a.timestamp is None:
                        continue  # bez času události → není timeline event
                    flags = detect_anomalies(
                        a.artifact_type,
                        a.timestamp,
                        title=a.title,
                        rel_path=wf.rel_path,
                        file_mtime=rec.mtime,
                        file_ctime=rec.ctime,
                        ctx=anomaly_ctx,
                    )
                    if flags:
                        a.anomaly_flags = tuple(flags)
                    # STP-018 — normalizované entity subjektu (pro detekci rozporů);
                    # čistá logika bez IO, defenzivně (chyba extrakce ≠ pád pipeline).
                    try:
                        subject_values = tuple(sorted({e.value for e in extract_entities(a)}))
                    except Exception:  # noqa: BLE001 — analytický bonus, ne kritická cesta
                        log.debug("subject extraction failed for artifact %s", a.id)
                        subject_values = ()
                    db.add_timeline_event(
                        source_id=source_id,
                        artifact_id=a.id,
                        file_id=file_id,
                        rel_path=wf.rel_path,
                        event_type=a.artifact_type,
                        ts_utc=a.timestamp,
                        title=a.title,
                        confidence=a.confidence,
                        parser_version=a.parser_version,
                        extracted_at=a.extracted_at,
                        anomaly_flags=tuple(flags),
                        ts_origin=getattr(a, "ts_origin", None) or "source",
                        subject_values=subject_values,
                    )
                    # průběžné doplnění kontextu — duplikát detekce + rozšiřování okna
                    key = f"{a.artifact_type}|{a.title or ''}|{wf.rel_path}"
                    anomaly_ctx.seen_timestamps.append((a.timestamp, key))
                    if (anomaly_ctx.window_start is None
                            or a.timestamp < anomaly_ctx.window_start):
                        anomaly_ctx.window_start = a.timestamp
                    if (anomaly_ctx.window_end is None
                            or a.timestamp > anomaly_ctx.window_end):
                        anomaly_ctx.window_end = a.timestamp

            if progress is not None and ((i + 1) % 10 == 0 or i + 1 == n):
                progress(skipped + i + 1, total)

    db.commit()
    # E1 Evidence Manager: uzavření běhu — souhrny + verze parserů (reprodukovatelnost)
    db.log_operation(
        "processing_completed",
        details={
            "source_id": source_id,
            "files_total": result.files_total,
            "bytes_total": result.bytes_total,
            "signatures_detected": result.signatures_detected,
            "bad_extensions": result.bad_extensions,
            "duplicates": result.duplicates,
            "hash_set_hits": result.hash_set_hits,
            "artifacts_extracted": result.artifacts_extracted,
            "errors": len(result.errors),
            "parser_versions": parser_versions(),
        },
    )
    # P0 Core C2: Evidence Lineage — krok extrakce (zdroj → artefakty).
    # Input = zdroj + zpracované soubory; output = ID extrahovaných artefaktů.
    if result.artifacts_extracted or result.files_total:
        db.log_lineage(
            "extract",
            case_id=_case_id_for_source(db, source_id),
            tool_version=_stopa_pkg.__version__,
            config_hash=config_hash({"profile": profile_name}),
            input_refs=(source_id,),
            output_refs=tuple(result.extracted_artifact_ids),
            details={
                "files_total": result.files_total,
                "artifacts_extracted": result.artifacts_extracted,
                "parser_versions": parser_versions(),
            },
        )
    # P0 Core C5: Reproducibility Engine — záznam operace pro opakování + porovnání.
    # Vstupní soubory se SHA-256 (z DB po upsertu) → replay ověří, že se zpracovává totéž.
    input_files = [
        {"rel_path": r["rel_path"], "sha256": r["sha256"]}
        for r in db.conn.execute(
            "SELECT rel_path, sha256 FROM files WHERE source_id = ? ORDER BY rel_path",
            (source_id,),
        ).fetchall()
    ]
    db.record_operation(
        "extract",
        case_id=_case_id_for_source(db, source_id),
        source_id=source_id,
        input_files=input_files,
        parser_versions=parser_versions(),
        stopa_version=_stopa_pkg.__version__,
        config_hash=config_hash({"profile": profile_name}),
        params={"profile": profile_name},
        outputs=summarize_outputs(result),
        duration_ms=int((time.monotonic() - _t0) * 1000),
    )
    # STP-069 — Plánované/periodické exporty: opt-in automatický ZIP bundle po
    # úspěšném dokončení processingu. Fail-safe: chyba auto-exportu nikdy nepadne
    # hlavní flow (log + pokračování). Deterministický výstup (C4) přes to_zip_bundle.
    _maybe_auto_export(db, source_id)
    return result


def _maybe_auto_export(db: CaseDB, source_id: str) -> None:
    """STP-069 — vygeneruje auto-bundle, pokud je u případu zapnutý (opt-in).

    Volá se na konci ``process_source()`` po úspěšném dokončení. Celé tělo je
    obalené v try/except — selhání auto-exportu se pouze zloguje a nikdy nepadne
    hlavní ingest/analysis flow (fail-safe, default off).
    """
    case_id = _case_id_for_source(db, source_id)
    if not case_id:
        return
    try:
        case = db.get_case(case_id)
        if case is None or not case.auto_export_enabled:
            return
        from stopa.domain.export import build_auto_bundle

        data, out_path = build_auto_bundle(db, case_id)
        # atomický zápis (tmp → rename), aby UI nikdy nevidělo poloviční soubor
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_suffix(".zip.tmp")
        tmp_path.write_bytes(data)
        tmp_path.replace(out_path)
        db.set_last_auto_export(case_id, str(out_path))
        db.log_operation(
            "auto_bundle_exported",
            actor=case.examiner,
            details={
                "source_id": source_id,
                "path": str(out_path),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
        )
    except Exception as exc:  # noqa: BLE001 — fail-safe, nikdy nepadne flow
        logging.getLogger(__name__).warning(
            "STP-069 auto-export selhal (case=%s): %s", case_id, exc
        )


def run_timeline_intel(
    db: CaseDB, window_seconds: float = 60.0
) -> dict[str, int]:
    """STP-018 Timeline Intelligence 2.0 — post-pass nad celou case DB.

    Běží po zpracování zdrojů (CLI ``add`` / web process) nebo explicitně
    (``stopa timeline --intel``). Čistá logika z ``domain/timeline_intel.py``:
    rozpory (souběžná aktivita subjektu) + duplikáty napříč zdroji. Výsledek se
    materializuje do ``timeline_events`` (group ID + kanonické flagy) —
    idempotentní, deterministický, bez dotyku původních artifactů.

    Vrací souhrn pro logování/UI: počet událostí, rozporových skupin a duplikátů.
    """
    db.clear_timeline_intel_groups()
    events = db.list_timeline_events()
    result = analyze_timeline(events, window_seconds=window_seconds)
    updated = db.set_timeline_intel_groups(
        result.event_contradiction_groups, result.event_dup_groups
    )
    log.info(
        "timeline intel: %d událostí → %d rozporových skupin, %d dup. skupin (%d řádků upraveno)",
        len(events),
        len(result.contradictions),
        len(result.dup_groups),
        updated,
    )
    return {
        "events": len(events),
        "contradiction_groups": len(result.contradictions),
        "dup_groups": len(result.dup_groups),
        "updated_rows": updated,
    }


def _case_id_for_source(db: CaseDB, source_id: str) -> str | None:
    """Case ID zdroje pro lineage (None pokud zdroj neexistuje — defenzivní)."""
    src = db.get_source(source_id)
    return src.case_id if src else None


def replay_extract(
    op: AnalysisOperation, root: Path, workdir: Path | None = None
) -> ReplayResult:
    """Opakuje zaznamenanou extrakci a porovná výsledek s původním (P0 Core C5).

    1. ověří vstupní soubory (SHA-256 na disku vs. záznam operace),
    2. spustí ``process_source`` do ČISTÉ dočasné DB (původní případ se nedotkne —
       „nikdy neměň originální důkazní data"),
    3. porovná deterministický souhrn výstupů s původním záznamem.

    ``workdir`` — kde leží dočasná DB (default: systémový tmp). Volání zavře
    dočasnou DB; soubor zůstává pro inspekcí (volající ho smaže, pokud chce).
    """
    from stopa.data.db import CaseDB as _CaseDB  # lokální — bez cyklu při importu
    from stopa.models import Case, EvidenceSource

    t0 = time.monotonic()
    profile_name = op.params_json.get("profile", "forensic")

    # 1) vstupní ověření — aktuální hashe na disku (jen soubory ze záznamu)
    current_hashes: dict[str, str | None] = {}
    for f in op.input_files:
        p = root / f["rel_path"] if not root.is_file() else root
        try:
            digests = hash_file(p, ["sha256"])
            current_hashes[f["rel_path"]] = digests.get("sha256")
        except OSError:
            current_hashes[f["rel_path"]] = None  # soubor zmizel / nečitelný
    inputs_ok, input_diffs = verify_inputs(list(op.input_files), current_hashes)

    # 2) čistá dočasná DB — původní případ se nedotkne (append-only evidence)
    tmp_db_path = Path(workdir or tempfile.gettempdir()) / f"stopa-replay-{op.id}.db"
    replay_db = _CaseDB(tmp_db_path)
    try:
        case = Case(name=f"replay {op.op_type} {op.id}")
        replay_db.add_case(case)
        src = EvidenceSource(
            case_id=case.id, kind="folder", path=str(root), size_bytes=None
        )
        replay_db.add_source(src)
        result = process_source(replay_db, src.id, root, profile_name=profile_name)
    finally:
        replay_db.close()

    # 3) porovnání výstupů — deterministický souhrn vs. původní záznam
    report = compare_outputs(op.outputs_json, summarize_outputs(result))
    return ReplayResult(
        op_id=op.id,
        inputs_identical=inputs_ok,
        input_diffs=input_diffs,
        outputs_identical=report.identical,
        output_diffs=report.diffs,
        duration_ms=int((time.monotonic() - t0) * 1000),
    )


def load_hash_sets(paths: list[Path]) -> dict[str, set[str]]:
    """Načte known-bad hash sety z textových souborů (FTK-style).

    Formát: jeden hash na řádek (# komentář), SHA-256 nebo MD5 — detekce podle délky.
    Název setu = jméno souboru bez přípony.
    """
    sets: dict[str, set[str]] = {}
    for p in paths:
        name = p.stem
        hashes: set[str] = set()
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip().lower()
                if not line or line.startswith("#"):
                    continue
                if len(line) in (32, 40, 64):  # md5 / sha1 / sha256 hex
                    hashes.add(line)
        sets[name] = hashes
    return sets
