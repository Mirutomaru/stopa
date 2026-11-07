"""STP-055 — Oblast Q Interop: UCO mapping (Unified Cyber Ontology).

STOPA artifact typy → třídy UCO ontologie (``ucoProject/UCO``). Čistá domain
logika bez IO. Mapování je kurátorské a explicitní — každá cílová třída je
ověřená proti reálné UCO ontologii (moduly ``observable``, ``configuration``,
``location``). Typy bez jasného ekvivalentu zůstávají **nezmapped** (``None``)
a export je označí prefixem ``stopa:`` místo aby vymýšlel fiktivní třídu.

Výstup je deterministický (stejný vstup = stejný JSON → stabilní C4 manifest).
"""

from __future__ import annotations

import json
from typing import Any

#: @context pro UCO dokumenty — autoritativní URI ontologie.
UCO_CONTEXT = "https://unifiedcyberontology.org/ontology/uco"

#: STOPA artifact_type → (UCO třída, UCO modul). Kurátorské mapování;
#: třídy ověřené proti ucoProject/UCO (observable/configuration/location).
#: Seřazeno deterministicky podle klíče.
UCO_ARTIFACT_MAP: dict[str, tuple[str, str]] = {
    "app_execution": ("Process", "observable"),
    "autofill_entry": ("Credential", "observable"),
    "browser_bookmark": ("BrowserBookmark", "observable"),
    "browser_cookie": ("BrowserCookie", "observable"),
    "browser_history": ("URLHistoryEntry", "observable"),
    "browser_search": ("URLVisit", "observable"),
    "browser_setting": ("ConfigurationEntry", "configuration"),
    "browser_tab": ("WebPage", "observable"),
    "calendar_event": ("CalendarEntry", "observable"),
    "call_log": ("Call", "observable"),
    "call_record": ("Call", "observable"),
    "chat_message": ("Message", "observable"),
    "cloud_file": ("File", "observable"),
    "cloud_instance": ("Device", "observable"),
    "contact": ("Contact", "observable"),
    "credential": ("Credential", "observable"),
    "document_metadata": ("File", "observable"),
    "email_attachment": ("File", "observable"),
    "email_message": ("EmailMessage", "observable"),
    "event_log_entry": ("EventLog", "observable"),
    "file_metadata": ("File", "observable"),
    "google_account": ("DigitalAccount", "observable"),
    "google_device": ("Device", "observable"),
    "google_location": ("GeoLocationEntry", "observable"),
    "google_mail_info": ("EmailMessage", "observable"),
    "google_maps_activity": ("GeoLocationTrack", "observable"),
    "google_photo": ("Image", "observable"),
    "google_search": ("URLVisit", "observable"),
    "imessage": ("Message", "observable"),
    "location": ("Location", "location"),
    "location_data": ("GeoLocationLog", "observable"),
    "mem_process": ("Process", "observable"),
    "memory_file": ("File", "observable"),
    "memory_process": ("Process", "observable"),
    "messenger_message": ("Message", "observable"),
    "network_connection": ("NetworkConnection", "observable"),
    "property_list": ("ConfigurationEntry", "configuration"),
    "registry_hive": ("Configuration", "configuration"),
    "scheduled_task": ("WindowsTask", "observable"),
    "shell_link": ("File", "observable"),
    "sms_message": ("SMSMessage", "observable"),
    "sns_comment": ("Message", "observable"),
    "sns_post": ("WebPage", "observable"),
    "sqlite_database": ("File", "observable"),
    "user_sid": ("WindowsAccount", "observable"),
    "usn_record": ("File", "observable"),
    "voice_recording": ("Audio", "observable"),
    "voicemail": ("Audio", "observable"),
    "web_page": ("WebPage", "observable"),
    "whatsapp_message": ("Message", "observable"),
    "wifi_profile": ("WirelessNetworkConnection", "observable"),
    "win_driver": ("File", "observable"),
}

#: STOPA typy bez jasného UCO ekvivalentu — explicitně nezmapped.
#: (Komplement k :data:`UCO_ARTIFACT_MAP` nad KNOWN_ARTIFACT_TYPES.)
UCO_UNMAPPED: frozenset[str] = frozenset(
    {
        "clipboard_entry",
        "drive_activity",
        "google_account_event",
        "google_activity",
        "google_export_summary",
        "google_identity_session",
        "google_login",
        "mem_connection",
        "mem_handle",
        "mem_hook",
        "mem_module",
        "plist_date",
        "win_jumplist",
        "win_prefetch",
    }
)


def map_artifact_to_uco(artifact_type: Any) -> tuple[str, str] | None:
    """STOPA artifact_type → ``(uco_class, uco_module)``, nebo ``None``.

    Neznámé / prázdné / nezmapped typy vrací ``None`` — interop nevytváří
    fiktivní třídy. Výsledek je deterministický.
    """
    if not isinstance(artifact_type, str) or not artifact_type:
        return None
    return UCO_ARTIFACT_MAP.get(artifact_type)


def uco_type_label(rec: dict[str, Any]) -> str:
    """Záznam → UCO typový label.

    Zmapped typ → ``<module>:<Class>`` (např. ``observable:BrowserBookmark``);
    nezmapped/neznamý typ → ``stopa:<artifact_type>`` (explicitní rozšíření,
    nikdy fiktivní UCO třída).
    """
    mapped = map_artifact_to_uco(rec.get("artifact_type"))
    if mapped is None:
        atype = rec.get("artifact_type") or "unknown"
        return f"stopa:{atype}"
    cls, module = mapped
    return f"{module}:{cls}"


def to_uco_json(records: list[dict[str, Any]], dataset: str = "artifacts") -> str:
    """Záznamy → UCO JSON dokument (JSON-LD s ``@context``).

    Struktura::

        {
          "@context": "<UCO_CONTEXT>",
          "dataset": "artifacts",
          "count": N,
          "objects": [ {"@type": "...", "name"?, "time"?, "x-stopa"?}, ... ]
        }

    - ``@type`` — UCO třída (zmapped) nebo ``stopa:<typ>`` (nezmapped),
    - ``name`` — z ``title`` / ``rel_path`` (pouze pokud existuje),
    - ``time`` — z ``timestamp_utc`` (pouze pokud existuje; žádný fiktivní čas),
    - ``x-stopa-id`` — původní STOPA ``id`` pro traceability do case DB,
    - ``x-stopa`` — ostatní původní STOPA pole bez ``None``.

    Výstup je deterministický (stejný vstup = stejný text).
    """
    objects: list[dict[str, Any]] = []
    for rec in records:
        obj: dict[str, Any] = {"@type": uco_type_label(rec)}
        name = rec.get("title") or rec.get("rel_path")
        if name is not None and str(name) != "":
            obj["name"] = str(name)
        ts = rec.get("timestamp_utc")
        if ts:
            obj["time"] = str(ts)
        sid = rec.get("id")
        if sid is not None:
            obj["x-stopa-id"] = str(sid)  # traceability do case DB
        ext = {k: v for k, v in rec.items() if v is not None and k != "id"}
        if ext:
            obj["x-stopa"] = ext
        objects.append(obj)
    doc = {
        "@context": UCO_CONTEXT,
        "dataset": dataset,
        "count": len(objects),
        "objects": objects,
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)
