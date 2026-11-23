"""ETAPA B vlna 12 — Microsoft Teams (teams) parser (cloud export / warrant return).

AXIOM ekvivalent: ``CloudMicrosoftTeamsArtifact``
(``Magnet.Artifacts.Cloud.Microsoft.Teams.*``) — seznamy týmů a členství
z Microsoft Teams cloud exportu.

Zdroj dat: JSON exporty/warrant returny (``teams.json``, ``Teams/*.json``).
Typ artifactu: ``contact`` (členství v týmu = sociální entita s rolí).

Design (Clean Architecture):
- Čisté funkce bez I/O — offline testovatelné.
- IO entrypoint ``extract_teams(path)`` s defenzivním try/except.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.models import Artifact

PARSER_VERSION = "1.0"
_LOGGER = logging.getLogger(__name__)


def is_ms_teams_file(path: str) -> bool:
    """Detekce Microsoft Teams exportu podle názvu souboru (bez obsahu)."""
    name = Path(path).name.lower()
    return name in {"teams.json", "ms_teams.json"} or (
        "team" in name and ("microsoft" in path.lower() or "teams" in path.lower())
    )


def _to_int(value: Any) -> int | None:
    """Tolerantní konverze na int."""
    try:
        if value is None:
            return None
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _first_str(item: dict[str, Any], *keys: str) -> str | None:
    """První neprázdný string mezi klíči."""
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def build_team_artifacts(entries: list[dict[str, Any]]) -> list[Artifact]:
    """Převod Teams záznamů na artifacty (čistá funkce).

    Každý tým = ``contact`` artifact s rolí ``team_member`` a detaily
    týmu. Členství se agreguje do details.
    """
    artifacts: list[Artifact] = []
    for item in entries:
        if not isinstance(item, dict):
            continue

        team_name = _first_str(
            item, "displayName", "name", "teamName", "title"
        ) or "Microsoft Teams"
        owner_id = _first_str(item, "ownerId", "owner")
        member_count = _to_int(item.get("memberCount"))

        # Členství — seznam členů v záznamu (volitelné)
        members: list[str] = []
        raw_members = item.get("members") or item.get("users") or []
        if isinstance(raw_members, list):
            for member in raw_members:
                if isinstance(member, dict):
                    name = _first_str(
                        member, "displayName", "name", "email", "userPrincipalName"
                    )
                    if name:
                        members.append(name)
                elif isinstance(member, str) and member.strip():
                    members.append(member.strip())

        details: dict[str, Any] = {
            "engine": "ms_teams",
            "team_name": team_name,
            "role": "team_member",
        }
        if owner_id:
            details["owner"] = owner_id
        if member_count is not None:
            details["member_count"] = member_count
        if members:
            details["members"] = members

        artifacts.append(
            Artifact(
                artifact_type="contact",
                title=f"Microsoft Teams: {team_name}"[:120],
                timestamp=None,
                details=details,
                confidence=0.85,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_teams(path: str | Path) -> list[Artifact]:
    """IO entrypoint — načtení Teams JSON exportu a extrakce artifactů."""
    try:
        data = bounded_json_loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        _LOGGER.warning("ms_teams: selhalo načtení %s: %s", path, exc)
        return []

    # Normalizace na seznam záznamů
    if isinstance(data, dict):
        entries = data.get("teams") or data.get("value") or [data]
    elif isinstance(data, list):
        entries = data
    else:
        return []

    try:
        return build_team_artifacts(entries)
    except Exception as exc:  # noqa: BLE001 — defenzivní IO boundary
        _LOGGER.warning("ms_teams: selhala extrakce %s: %s", path, exc)
        return []
