"""ETAPA B vlna 10 — Instagram Account Actions/History/Followers parser (cloud export).

AXIOM ekvivalenty: ``InstagramAccountActionsArtifact`` +
``InstagramAccountHistoryArtifact`` + ``InstagramFollowersAndFollowingArtifact``
(``Magnet.Artifacts.Cloud.*``) — akce účtu a sociální graf.

Podporovaný formát: **JSON export** (Takeout / cloud export)::

    Akce/historie: [{"type": "login", "timestamp": 1728000000,
                     "device": "...", "ip_address": "..."}]
    Followers/following: {"followers": [{"username": "fan_1", "full_name": "..."}],
                          "following": [{"username": "user_x"}]}

Jedna akce = jeden artifact (``event_log_entry``, ``details.engine='instagram_account'``);
jeden follower/following uživatel = jeden artifact (``contact``,
``details.mimetype='sns:instagram'`` — E4 entity extrakce). Neznámá pole se ignoruje.

Detekce: **name-based** — SNS marker (``instagram``) + klíčová slova
(``account_actions``, ``account_history``, ``followers_and_following``);
v dispatchi pre-pass na celé cestě PŘED basename chainem.
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

MAX_EVENTS_PER_FILE = 20_000


@dataclass
class IgAccountEvent:
    """Jedna akce / historická událost účtu."""

    event_type: str | None = None
    timestamp: int | None = None
    device: str | None = None
    ip_address: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class IgSnsUser:
    """Jeden uživatel z followers/following seznamu."""

    username: str | None = None
    full_name: str | None = None
    relationship: str | None = None  # follower / following
    extra: dict[str, Any] = field(default_factory=dict)


def _to_int(value: Any) -> int | None:
    """Tolerantní konverze na int (int / numeric string)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _to_str(value: Any) -> str | None:
    """Tolerantní konverze na non-empty string."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_instagram_account(data: bytes) -> tuple[list[IgAccountEvent], list[IgSnsUser]]:
    """ČISTÝ parser — Instagram account JSON → (události, uživatelé).

    Auto-detekce formátu podle struktury payloadu:
    - pole s ``type``/``timestamp`` klíči → akce/historie
    - dict s ``followers``/``following`` poli → sociální graf

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez rozpoznatelných záznamů.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    events: list[IgAccountEvent] = []
    users: list[IgSnsUser] = []

    # sociální graf — followers/following
    if isinstance(payload, dict):
        for rel_key, relationship in (("followers", "follower"), ("following", "following")):
            raw = payload.get(rel_key)
            if not isinstance(raw, list):
                continue
            for item in raw[:MAX_EVENTS_PER_FILE]:
                if not isinstance(item, dict):
                    continue
                username = _to_str(item.get("username", item.get("user")))
                full_name = _to_str(item.get("full_name", item.get("name")))
                if not username and not full_name:
                    continue
                extra: dict[str, Any] = {}
                profile_pic = _to_str(item.get("profile_picture_url"))
                if profile_pic:
                    extra["profile_picture"] = profile_pic[:300]
                users.append(
                    IgSnsUser(
                        username=username,
                        full_name=full_name,
                        relationship=relationship,
                        extra=extra,
                    )
                )

    # akce / historie — pole událostí (přímo nebo pod klíčem)
    raw_events: list[Any] = []
    if isinstance(payload, list):
        raw_events = payload
    elif isinstance(payload, dict):
        for key in ("actions", "history", "events", "value"):
            val = payload.get(key)
            if isinstance(val, list):
                raw_events = val
                break

    for item in raw_events[:MAX_EVENTS_PER_FILE]:
        if not isinstance(item, dict):
            continue
        etype = _to_str(item.get("type", item.get("action")))
        ts = _to_int(item.get("timestamp", item.get("time")))
        if etype is None and ts is None:
            continue
        extra: dict[str, Any] = {}
        for key in ("details", "description"):
            val = _to_str(item.get(key))
            if val:
                extra[key] = val[:300]
        events.append(
            IgAccountEvent(
                event_type=etype,
                timestamp=ts,
                device=_to_str(item.get("device", item.get("device_info"))),
                ip_address=_to_str(item.get("ip_address", item.get("ip"))),
                extra=extra,
            )
        )

    if not events and not users:
        raise TypeError("Nenalezeny Instagram account záznamy")
    return events, users


def build_instagram_account_artifacts(
    events: list[IgAccountEvent],
    users: list[IgSnsUser] | None = None,
) -> list[Artifact]:
    """ČISTÁ funkce: z událostí a uživatelů vytvoří artifacty."""
    artifacts: list[Artifact] = []

    for e in events:
        details: dict[str, Any] = {"engine": "instagram_account"}
        if e.event_type:
            details["event_type"] = e.event_type
        if e.device:
            details["device"] = e.device[:200]
        if e.ip_address:
            details["ip_address"] = e.ip_address
        details.update(e.extra)

        title = f"Instagram account event ({e.event_type or '?'})"
        artifacts.append(
            Artifact(
                artifact_type="event_log_entry",
                timestamp=None,  # epoch v details — konverze na ISO v reportu
                title=title[:120],
                details=details | ({"timestamp_epoch": e.timestamp} if e.timestamp is not None else {}),
                confidence=0.7 if (e.event_type and e.timestamp is not None) else 0.5,
                parser_version=PARSER_VERSION,
            )
        )

    for u in users or []:
        details: dict[str, Any] = {
            "engine": "instagram_account",
            "mimetype": "sns:instagram",
        }
        if u.relationship:
            details["relationship"] = u.relationship
        details.update(u.extra)

        display = u.username or u.full_name or "?"
        title = f"Instagram {u.relationship or 'user'}: {display}"
        artifacts.append(
            Artifact(
                artifact_type="contact",
                timestamp=None,
                title=title[:120],
                details=details,
                confidence=0.6 if u.username else 0.4,
                parser_version=PARSER_VERSION,
            )
        )

    return artifacts


def extract_instagram_account_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Instagram account JSON → event/contact artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("InstagramAccount %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        events, users = parse_instagram_account(data)
    except (ValueError, TypeError) as e:
        logger.debug("InstagramAccount %s: %s", path.name, e)
        return []

    return build_instagram_account_artifacts(events, users)


def is_instagram_account_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Instagram account exportu.

    Vyžaduje SNS marker (``instagram``) v názvu/cestě + klíčová slova účtu —
    generic basenames bez markery nepadnou, aby se nekradly cizí exporty.
    """
    lower = name.lower()
    if "instagram" not in lower:
        return False
    if not any(k in lower for k in ("account", "follower")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
