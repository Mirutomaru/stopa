"""ETAPA B vlna 4 — DuckDuckGo Allowlisted Websites parser (JSON).

AXIOM ekvivalent: ``AllowlistedWebSitesArtifact`` (Magnet.Artifacts.dll) —
seznam webů, které uživatel explicitně povolil (tracker protection vypnutá),
z profilu DuckDuckGo prohlížeče. Zdroj: JSON soubor v profilovém adresáři
(např. ``allowlisted_websites.json`` / výpis tracker exceptions).

Formát: JSON — buď pole domén, nebo objekt s klíčem ``exceptions``/``allowlist``
(obsahujícím seznam domén). Čistá funkce ``build_allowlisted_artifacts()`` nad
seznamem domén; IO entrypoint ``extract_allowlisted_websites_artifacts(path)``.

Artifact type: ``browser_setting`` (AXIOM AllowlistedWebSites).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

# Klíče, pod kterými může být seznam domén (case-insensitive)
_LIST_KEYS = ("exceptions", "allowlist", "allowed", "websites", "domains", "sites")


def is_allowlisted_websites_file(name: str) -> bool:
    """Name-based detekce — DDG allowlisted websites JSON."""
    n = name.lower()
    return (
        "allowlisted" in n and ("website" in n or "site" in n) and n.endswith(".json")
    ) or n == "allowlisted_websites.json"


def _extract_domains(data: Any) -> list[str]:
    """Defenzivní extrakce seznamu domén z JSON struktury."""
    if isinstance(data, list):
        return [str(x).strip() for x in data if isinstance(x, (str, int)) and str(x).strip()]
    if isinstance(data, dict):
        norm = {k.lower(): v for k, v in data.items()}
        for key in _LIST_KEYS:
            val = norm.get(key)
            if isinstance(val, list):
                return [
                    str(x).strip()
                    for x in val
                    if isinstance(x, (str, int)) and str(x).strip()
                ]
    return []


def build_allowlisted_artifacts(domains: list[str]) -> list[Artifact]:
    """ČISTÁ funkce: seznam domén → browser_setting artifacty."""
    artifacts: list[Artifact] = []
    for domain in domains:
        d = domain.strip().lstrip(".*")  # odstraň wildcard prefix
        if not d:
            continue
        artifacts.append(
            Artifact(
                artifact_type="browser_setting",
                timestamp=None,
                title=f"Allowlisted website: {d}",
                details={
                    "domain": d,
                    "engine": "ddg_allowlisted_websites",
                    "note": "tracker protection disabled for this site",
                },
                confidence=0.7,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_allowlisted_websites_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — DDG allowlisted websites JSON → artifacty."""
    try:
        data = bounded_json_loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("AllowlistedWebsites read %s: %s", path, exc)
        return []
    domains = _extract_domains(data)
    if not domains:
        logger.debug("AllowlistedWebsites %s: no domains found", path)
        return []
    return build_allowlisted_artifacts(domains)
