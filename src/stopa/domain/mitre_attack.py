"""F6.3 — MITRE ATT&CK mapping (čistá doménová logika, bez I/O).

Auto-mapování artefaktů (IoC) na tactics/techniques MITRE ATT&CK Enterprise:
declarativní tabulka :data:`ATTACK_MAP` pokrývá ``KNOWN_ARTIFACT_TYPES``
(F1.3 grounding registry) — AK F6.3 = ≥ 80 % typů mapováno.

Zásady konzervativního mapování (stejná filozofie jako F6.2 STIX mapa):
- každý artefakt dostává techniky, které jeho *přítomnost* reálně indikuje;
  neexistuje sémantika → typ zůstává ve :data:`ATTACK_UNMAPPED` se zdůvodněním
  (žádné vymyšlené mapování);
- determinismus: stejný vstup = stejný výstup, žádné I/O ani náhoda;
- evidence = konkrétní pole artefaktu (title/rel_path/details), které mapping
  podpořilo — pro dohledatelnost v UI i v STIX exportu.

Taktika techniky je jediná primární (dle oficiálního ATT&CK Enterprise) —
techniky s více taktikami nese STOPA jen pod primární, aby heat-mapa a STIX
export zůstaly jednoznačné.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from collections.abc import Iterable
from typing import Any

# ── ATT&CK Enterprise reference (primární taktika + oficiální názvy) ─────────
#: id techniky → (oficiální název, taktika). Taktika = primární dle MITRE.
ATTACK_TECHNIQUES: dict[str, tuple[str, str]] = {
    # TA0001 Initial Access
    "T1566.001": ("Malicious Attachment", "TA0001"),
    "T1078": ("Valid Accounts", "TA0001"),
    # TA0002 Execution
    "T1204": ("User Execution", "TA0002"),
    "T1059": ("Command and Scripting Interpreter", "TA0002"),
    # TA0003 Persistence
    "T1547": ("Boot or Logon Autostart Execution", "TA0003"),
    "T1053": ("Scheduled Task/Job", "TA0003"),
    # TA0005 Defense Evasion
    "T1497": ("Virtualization/Sandbox Evasion", "TA0005"),
    "T1070": ("Indicator Removal on Hosts", "TA0005"),
    # TA0006 Credential Access
    "T1185": ("Browser Session Hijacking", "TA0006"),
    "T1552": ("Unsecured Credentials", "TA0006"),
    "T1555": ("Credentials in Files", "TA0006"),
    "T1056": ("Input Capture", "TA0006"),
    # TA0007 Discovery
    "T1033": ("System Owner/User Discovery", "TA0007"),
    "T1082": ("System Information Discovery", "TA0007"),
    "T1049": ("System Network Connections Discovery", "TA0007"),
    "T1057": ("Process Discovery", "TA0007"),
    "T1016": ("System Network Configuration Discovery", "TA0007"),
    # TA000A Command and Control
    "T1071": ("Application Layer Protocol", "TA000A"),
    # TA000B Exfiltration
    "T1567": ("Exfiltration Over Web Service", "TA000B"),
    "T1052": ("Exfiltration Over Physical Medium", "TA000B"),
    # TA0009 Collection
    "T1030": ("Data Stored Locally", "TA0009"),
}

#: id taktiky → oficiální název (pořadí = řádky heat-mapu, dle MITRE).
ATTACK_TACTICS: tuple[tuple[str, str], ...] = (
    ("TA0001", "Initial Access"),
    ("TA0002", "Execution"),
    ("TA0003", "Persistence"),
    ("TA0004", "Privilege Escalation"),
    ("TA0005", "Defense Evasion"),
    ("TA0006", "Credential Access"),
    ("TA0007", "Discovery"),
    ("TA0008", "Lateral Movement"),
    ("TA0009", "Collection"),
    ("TA000A", "Command and Control"),
    ("TA000B", "Exfiltration"),
    ("TA000C", "Impact"),
)

#: artifact_type → techniky, které přítomnost tohoto artefaktu indikuje.
ATTACK_MAP: dict[str, tuple[str, ...]] = {
    # ── Execution: důkazy o spuštění programu (user execution indikator) ──
    "app_execution": ("T1204",),
    "win_jumplist": ("T1204",),       # JOL = historie spuštěných aplikací
    "shell_link": ("T1204",),         # .lnk — klasický vektor user execution
    "win_prefetch": ("T1204",),       # PEF = důkaz, že program běžel
    # ── Initial Access: e-mail (phishing / malicious attachment) ──
    "email_message": ("T1566.001",),
    "google_mail_info": ("T1566.001",),
    "email_attachment": ("T1566.001",),
    # ── Initial Access: valid accounts (identita / login důkazy) ──
    "google_account": ("T1078",),
    "google_account_event": ("T1078",),
    "google_login": ("T1078",),
    # ── Command and Control: webová aktivita = aplikační protokol (C2 kandidát) ──
    "web_page": ("T1071",),            # webová stránka = aplikační protokol
    "browser_history": ("T1071",),
    "browser_search": ("T1071",),
    "browser_tab": ("T1071",),
    "browser_bookmark": ("T1071",),
    "google_activity": ("T1071",),
    "google_search": ("T1071",),
    # ── Command and Control: messengery / SNS (C2 přes webovou službu) ──
    "chat_conversation": ("T1071",),
    "chat_message": ("T1071",),
    "imessage": ("T1071",),
    "messenger_message": ("T1071",),
    "sms_message": ("T1071",),
    "whatsapp_message": ("T1071",),
    "sns_post": ("T1071",),
    "sns_comment": ("T1071",),
    # ── Credential Access: uložené / přebírané kredence ──
    "credential": ("T1552",),
    "clipboard_entry": ("T1552",),     # schránka často nese zkopírované kredence
    "autofill_entry": ("T1555",),      # autofill = kredence v souborech prohlížeče
    "browser_cookie": ("T1185",),       # cookie = session token (hijack kandidát)
    "google_identity_session": ("T1185",),
    # ── Credential Access: API hooks (input capture / interception) ──
    "mem_hook": ("T1056",),
    # ── Discovery: identita a prostředí ──
    "contact": ("T1033",),             # kontakty = kdo se s uživatelem propojuje
    "call_log": ("T1033",),            # hovorové záznamy = discovery uživatelů
    "call_record": ("T1033",),         # detail hovoru = discovery identit
    "user_sid": ("T1033",),            # SID = identita Windows uživatele
    "google_device": ("T1082",),        # metadata zařízení = systémová informace
    "mem_handle": ("T1057",),          # handlery odhalují zdroje procesů
    "mem_module": ("T1057",),           # načtené moduly = process discovery
    "mem_process": ("T1057",),         # tabulka procesů = process discovery
    "memory_process": ("T1057",),      # alias procesu v paměti
    "wifi_profile": ("T1016",),         # uložené sítě = network config discovery
    # ── Discovery: síťová spojení (live snapshot vs. paměťový záznam) ──
    "network_connection": ("T1071",),  # live spojení = C2 kandidát (aplikační protokol)
    "mem_connection": ("T1049",),       # tabulka spojení v paměti = discovery
    # ── Collection: lokálně uložená data / média ──
    "cloud_file": ("T1567",),          # cloudové soubory = exfil cíl (web service)
    "drive_activity": ("T1052",),       # USB aktivita = exfil přes fyz. médium
    "google_photo": ("T1030",),         # média = lokálně uložená data
    "voice_recording": ("T1030",),
    "voicemail": ("T1030",),
    "file_metadata": ("T1030",),       # metadata souborů = lokalizace dat
    "document_metadata": ("T1030",),
    # ── Persistence: registry + plánovače ──
    "registry_hive": ("T1547",),        # registry run keys = autostart persistence
    "scheduled_task": ("T1053",),      # plánované úlohy = scheduled task persistence
    # ── Defense Evasion: indikátory skrytí / odstranění stop ──
    "event_log_entry": ("T1070",),      # analýza logů odhaluje mazání/tampering
    "memory_file": ("T1070",),          # soubor v RAM po smazání = indicator removal
    "usn_record": ("T1070",),           # USN journal ukazuje smazané soubory
    "win_driver": ("T1497",),           # kernel drivery často anti-VM/rootkit
}

#: artifact typy bez přímé ATT&CK techniky (zdůvodněno — viz AK ≥ 80 %).
ATTACK_UNMAPPED: dict[str, str] = {
    "browser_setting": "konfigurační data prohlížeče bez přímé techniky",
    "calendar_event": "plánovací data uživatele bez přímé techniky",
    "cloud_instance": "infrastrukturní metadata bez přímé techniky",
    "google_export_summary": "agregátní souhrn exportu bez přímé techniky",
    "google_location": "geolokační data (rekonstrukce pohybu)",
    "google_maps_activity": "geolokační data mapové aktivity",
    "location": "geolokační data bez přímé ATT&CK techniky",
    "location_data": "geolokační data bez přímé ATT&CK techniky",
    "plist_date": "surová datumová metadata v plist kontejneru",
    "property_list": "surová strukturovaná data bez sémantiky",
    "sqlite_database": "binární kontejner bez sémantické typové informace",
}

#: Pořadí zobrazení technik v rámci taktiky (deterministický heatmap layout).
_TECH_ORDER = tuple(ATTACK_TECHNIQUES)


def _details_str(details: object) -> str:
    """Detaily artefaktu jako text pro evidence (None-safe, deterministicky)."""
    if not details:
        return ""
    try:
        return json.dumps(details, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(details)


def map_artifact(artifact_type: str, title: str | None = None, rel_path: str | None = None, details: object = None) -> list[dict]:
    """Zmapuje jeden artefakt na techniky ATT&CK (deterministicky).

    Returns:
        Seznam hitů ``{"technique", "tactic", "name"}`` — po jedné záznamu
        pro každou techniku v :data:`ATTACK_MAP`. Prázdný list = typ není
        mapován (viz :data:`ATTACK_UNMAPPED`) nebo neznámý.

    Evidence (title/rel_path/details) se připojuje na úrovni
    :func:`build_attack_heatmap` — zde je mapping čistě deklarativní.
    """
    techs = ATTACK_MAP.get(artifact_type or "")
    if not techs:
        return []
    out: list[dict] = []
    for tid in techs:
        name, tactic = ATTACK_TECHNIQUES[tid]
        out.append({"technique": tid, "tactic": tactic, "name": name})
    return out


def build_attack_heatmap(artifacts: Iterable[Any], max_samples: int = 3) -> dict:
    """Heat-mapa taktik×technik z artefaktů případu (AK F6.3).

    Args:
        artifacts: seznam objektů s atributy ``artifact_type``, ``title``,
            ``rel_path`` a ``details`` (Pydantic :class:`stopa.models.Artifact`
            i slovníkové řádky — přístup přes ``getattr``/``get`` fallback).
        max_samples: strop vzorků artefaktů na techniku (UI tooltip; deterministicky).

    Returns:
        Deterministický payload::

            {
              "tactics": [{"id", "name"}, ...],          # řádky matrice (MITRE pořadí)
              "techniques": [{id, name, tactic, count}], # jen s>0 hitů, stabilní pořadí
              "cells": {"T1204": [{"artifact_type","title","rel_path"}, ...]},
              "summary": {
                "artifacts_total", "mapped_artifacts", "unmapped_artifacts",
                "techniques_hit", "tactics_hit", "coverage_pct"  # map. typů / KNOWN
              }
            }

    ``coverage_pct`` = podíl *mapovaných artifact typů* na :data:`KNOWN_ARTIFACT_TYPES`
    (AK F6.3: ≥ 80 %) — lazy import, aby doména zůstala bez I/O i bez cyklu.
    """
    arts = list(artifacts)
    counter: Counter[str] = Counter()
    samples: dict[str, list[dict]] = {}
    mapped_artifacts = 0
    total = len(arts)

    for art in arts:
        atype = _attr(art, "artifact_type") or ""
        hits = map_artifact(
            atype,
            title=_attr(art, "title"),
            rel_path=_attr(art, "rel_path"),
            details=_attr(art, "details"),
        )
        if not hits:
            continue
        mapped_artifacts += 1
        for hit in hits:
            tid = hit["technique"]
            counter[tid] += 1
            bucket = samples.setdefault(tid, [])
            sample = {
                "artifact_type": atype,
                "title": _attr(art, "title"),
                "rel_path": _attr(art, "rel_path"),
            }
            if len(bucket) < max_samples:
                bucket.append(sample)

    techniques = [
        {"id": tid, "name": ATTACK_TECHNIQUES[tid][0], "tactic": ATTACK_TECHNIQUES[tid][1], "count": counter[tid]}
        for tid in _TECH_ORDER if counter.get(tid)
    ]
    tactics_hit = sorted({t["tactic"] for t in techniques})

    # coverage AK: mapované typy / KNOWN_ARTIFACT_TYPES (lazy import, bez I/O)
    from stopa.domain.ai_grounding import KNOWN_ARTIFACT_TYPES

    known = set(KNOWN_ARTIFACT_TYPES)
    mapped_types = {t for t in ATTACK_MAP if t in known}
    coverage_pct = round(100.0 * len(mapped_types) / len(known), 1) if known else 0.0

    return {
        "tactics": [{"id": tid, "name": name} for tid, name in ATTACK_TACTICS],
        "techniques": techniques,
        "cells": samples,
        "summary": {
            "artifacts_total": total,
            "mapped_artifacts": mapped_artifacts,
            "unmapped_artifacts": total - mapped_artifacts,
            "techniques_hit": len(techniques),
            "tactics_hit": tactics_hit,
            "coverage_pct": coverage_pct,
        },
    }


def _attr(obj: object, name: str) -> object:
    """Atribut nebo klíč slovníku (None-safe) — Pydantic model i dict řádek."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def to_stix_intrusion_set(case_id: str, case_name: str | None = None, heatmap: dict | None = None) -> dict:
    """STIX 2.1 ``intrusion-set`` s referencemi na taktiky/techniky (AK F6.3).

    Deterministický objekt: id = UUIDv5 nad stálým STOPA namespace + case_id,
    takže re-export téhož případu je byte-identický. Techniky nesou
    ``x-stopa`` rozšíření s počtem artefaktů a vzorky — stejná filozofie
    jako F6.2 STIX bundle (explicitní extenze, žádná fabrikace sémantiky).

    Args:
        case_id: STOPA ID případu (neseno v ``x-stopa.stopa_case_id``).
        case_name: název případu (volitelný; default = case_id).
        heatmap: výstup :func:`build_attack_heatmap` (None = prázdná mapa).

    Returns:
        STIX objekt (dict) — sérializace do bundle/JSON je na volajícím.
    """
    from stopa.domain.export import _stix_id  # F6.2 — sdílený deterministický id

    hm = heatmap or {}
    techniques = hm.get("techniques") or []
    summary = hm.get("summary") or {}

    name = case_name or case_id
    objects: list[dict] = [
        {
            "type": "tactic",  # x-stopa taktika (ATT&CK taktiky nejsou nativní STIX typ)
            "id": _stix_id("tactic", tid),
            "name": name_for(tid, kind="tactic"),
            "x-stopa-tactic-id": tid,
        }
        for tid in summary.get("tactics_hit") or []
    ]
    tech_objects: list[dict] = []
    for t in techniques:
        obj = {
            "type": "x-stopa-technique",  # ATT&CK techniky jako explicitní extenzní typ
            "id": _stix_id("attack-technique", t["id"]),
            "name": f"{t['id']} — {t['name']}",
            "x-stopa-technique-id": t["id"],
            "x-stopa-artifacts-count": t.get("count", 0),
        }
        tech_objects.append(obj)

    main = {
        "type": "intrusion-set",
        "id": _stix_id("intrusion-set", case_id),
        "name": f"STOPA case: {name}",
        "spec_version": "2.1",
        "created": "2026-01-01T00:00:00Z",  # deterministické (C4) — čas exportu nesmí měnit hash
        "modified": "2026-01-01T00:00:00Z",
        "object_refs": [o["id"] for o in tech_objects],
        "x-stopa": {
            "stopa_case_id": case_id,
            "tactics_hit": summary.get("tactics_hit") or [],
            "techniques_hit": len(techniques),
            "mapped_artifacts": summary.get("mapped_artifacts", 0),
            "artifacts_total": summary.get("artifacts_total", 0),
        },
    }
    return {"intrusion_set": main, "related_objects": objects + tech_objects}


def name_for(tech_or_tactic_id: str, kind: str = "technique") -> str:
    """Oficiální název techniky nebo taktiky (None-safe → id jako fallback)."""
    if kind == "tactic":
        for tid, name in ATTACK_TACTICS:
            if tid == tech_or_tactic_id:
                return name
        return tech_or_tactic_id
    entry = ATTACK_TECHNIQUES.get(tech_or_tactic_id)
    return entry[0] if entry else tech_or_tactic_id


def to_stix_bundle_intrusion_set(case_id: str, case_name: str | None = None, heatmap: dict | None = None) -> str:
    """STIX 2.1 bundle (JSON) s intrusion-set — pro ``stopa attack-map --format stix``."""
    result = to_stix_intrusion_set(case_id, case_name=case_name, heatmap=heatmap)
    objects = [result["intrusion_set"], *result["related_objects"]]
    return json.dumps({"type": "bundle", "id": _stix_bundle_id(case_id), "objects": objects}, ensure_ascii=False, indent=2)


def _stix_bundle_id(case_id: str) -> str:
    """Deterministický bundle id (UUIDv5 nad case_id) — C4 reprodukovatelnost."""
    from stopa.domain.export import STIX_NAMESPACE  # F6.2 — sdílený namespace

    return f"bundle--{uuid.uuid5(STIX_NAMESPACE, 'stopa-attack-map-' + case_id)}"
