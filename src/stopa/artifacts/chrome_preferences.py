"""ETAPA B vlna 8 — Google Chrome Preferences parser (cloud / sync export).

AXIOM ekvivalenty: ``CloudGoogleChromeExtensionsArtifact`` +
``CloudGoogleChromeExtensionSettingsArtifact`` +
``CloudGoogleChromeSearchEnginesArtifact`` +
``CloudGoogleChromeSyncSettingsAppSettingsArtifact`` +
``CloudGoogleChromeSyncSettingsAppsArtifact`` +
``CloudGoogleChromeSyncSettingsPreferencesArtifact``.

Podporovaný formát: **Chrome ``Preferences`` JSON** (profilový soubor z
Takeout / cloud sync exportu). Jeden soubor nese více sekcí; parser je
rozbaluje do samostatných artifactů::

    {
      "account_info": [{"email": "...", "full_name": "...", "gaia": 123}],
      "extensions": {"settings": {"<ext_id>": {"state": 1, "location": 1}}},
      "default_search_provider_data": {"template_url_data": {
          "short_name": "Google", "search_url": "https://..."}},
      "sync": {"preferred": true, ...}
    }

   Sekce → artifact type:
   - ``extensions.settings`` → ``browser_extension`` (jedna rozšíření = 1 art)
   - ``default_search_provider_data`` / ``search_engines`` → ``browser_setting``
   - ``sync`` + per-category sync settings → ``browser_setting``

Detekce: **name-based** (``preferences``, ``chrome_prefs``, ``secure_preferences``)
+ content check (JSON s ``extensions``/``account_info``/``default_search_provider``).

Artifact types: ``browser_extension`` + ``browser_setting``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_EXTENSIONS_PER_FILE = 2_000
MAX_SETTINGS_PER_FILE = 5_000


@dataclass
class ChromePrefRecord:
    """Jeden záznam z Chrome Preferences (rozbalený podle sekce)."""

    kind: str  # "extension" | "search_engine" | "sync_setting"
    name: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def _parse_extensions(payload: dict[str, Any], records: list[ChromePrefRecord]) -> None:
    """Sekce ``extensions.settings`` → browser_extension záznamy."""
    ext_block = payload.get("extensions")
    if not isinstance(ext_block, dict):
        return
    settings = ext_block.get("settings")
    if not isinstance(settings, dict):
        return
    for ext_id, meta in settings.items():
        if len(records) >= MAX_EXTENSIONS_PER_FILE:
            break
        if not isinstance(meta, dict):
            continue
        manifest = meta.get("manifest")
        manifest_name = str(manifest.get("name")).strip() if isinstance(manifest, dict) else ""
        name = (manifest_name or str(meta.get("name") or ext_id)).strip()
        details: dict[str, Any] = {"extension_id": str(ext_id)}
        for key in ("state", "location", "was_installed_by_default"):
            if key in meta:
                details[key] = meta[key]
        if isinstance(manifest, dict):
            mver = manifest.get("version")
            if isinstance(mver, (str, int)) and str(mver).strip():
                details["version"] = str(mver).strip()
        records.append(ChromePrefRecord(kind="extension", name=name, details=details))


def _parse_search_engines(payload: dict[str, Any], records: list[ChromePrefRecord]) -> None:
    """Sekce ``default_search_provider_data`` / ``search_engines`` → browser_setting."""
    dsp = payload.get("default_search_provider_data") or payload.get(
        "default_search_provider"
    )
    if isinstance(dsp, dict):
        tpl = dsp.get("template_url_data", dsp)
        if isinstance(tpl, dict):
            name = str(tpl.get("short_name") or "").strip()
            details: dict[str, Any] = {"setting": "default_search_provider"}
            for key in ("search_url", "keyword", "suggest_url"):
                val = tpl.get(key)
                if isinstance(val, str) and val:
                    details[key] = val
            records.append(ChromePrefRecord(kind="search_engine", name=name or "výchozí vyhledávač", details=details))

    # volitelný seznam dalších vyhledávačů (search_engines / template_urls)
    engines = payload.get("search_engines")
    if isinstance(engines, dict):
        for tpl in engines.values():
            if len(records) >= MAX_SETTINGS_PER_FILE:
                break
            if not isinstance(tpl, dict):
                continue
            name = str(tpl.get("short_name") or "").strip()
            details = {"setting": "search_engine"}
            url = tpl.get("search_url")
            if isinstance(url, str) and url:
                details["search_url"] = url
            records.append(ChromePrefRecord(kind="search_engine", name=name or "vyhledávač", details=details))


def _parse_sync_settings(payload: dict[str, Any], records: list[ChromePrefRecord]) -> None:
    """Sekce ``sync`` → browser_setting (app settings / apps / preferences)."""
    sync = payload.get("sync")
    if isinstance(sync, dict):
        details: dict[str, Any] = {"setting": "sync"}
        for key in ("preferred", "passthrough"):
            if key in sync:
                details[key] = sync[key]
        # per-category přepínače (data_type_enabled apod.)
        enabled = [k for k, v in sync.items() if isinstance(v, bool) and k not in ("preferred", "passthrough")]
        if enabled:
            details["enabled_categories"] = sorted(enabled)
        records.append(ChromePrefRecord(kind="sync_setting", name="Sync nastavení", details=details))

    # instalované aplikace z sync (apps / installed_apps)
    apps = payload.get("apps") or payload.get("installed_apps")
    if isinstance(apps, dict):
        for app_id, meta in list(apps.items())[:MAX_SETTINGS_PER_FILE]:
            name = str(meta.get("name", app_id)).strip() if isinstance(meta, dict) else str(app_id).strip()
            details = {"setting": "sync_app", "app_id": str(app_id)}
            records.append(ChromePrefRecord(kind="sync_setting", name=name or "aplikace", details=details))


def parse_chrome_preferences(data: bytes) -> list[ChromePrefRecord]:
    """ČISTÝ parser — Chrome Preferences JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne objekt.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    if not isinstance(payload, dict):
        raise TypeError("Očekáván JSON objekt (Chrome Preferences)")

    records: list[ChromePrefRecord] = []
    _parse_extensions(payload, records)
    _parse_search_engines(payload, records)
    _parse_sync_settings(payload, records)
    return records


def is_chrome_preferences_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Chrome Preferences exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("preferences", "chrome_prefs", "secure_pref")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith(b"{"):
            return False
        joined = head[:2048].lower()
        if not any(k in joined for k in (b"extensions", b"account_info", b"default_search_provider", b"sync")):
            return False
    return True


def build_pref_artifacts(records: list[ChromePrefRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (browser_extension / browser_setting)."""
    artifacts: list[Artifact] = []
    for r in records:
        if r.kind == "extension":
            atype = "browser_extension"
            title = f"Chrome Extension: {r.name}"
            confidence = 0.85
        else:
            atype = "browser_setting"
            title = f"Chrome Setting: {r.name}"
            confidence = 0.7

        details: dict[str, Any] = {"engine": "chrome_preferences"}
        details.update(r.details)

        artifacts.append(
            Artifact(
                artifact_type=atype,
                timestamp=None,  # snapshot konfigurace bez času
                title=title[:120],
                details=details,
                confidence=confidence,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_chrome_pref_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Chrome Preferences JSON → browser_extension/browser_setting."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("ChromePreferences %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_chrome_preferences(data)
    except (ValueError, TypeError) as e:
        logger.debug("ChromePreferences %s: %s", path, e)
        return []

    return build_pref_artifacts(records)
