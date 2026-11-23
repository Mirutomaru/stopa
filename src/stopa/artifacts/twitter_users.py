"""ETAPA B vlna 11 — Twitter/X users parser (cloud export / warrant return).

AXIOM ekvivalenty: ``CloudTwitterUsersArtifact`` +
``CloudTwitterWarrantReturnUsersArtifact`` (``Magnet.Artifacts.Cloud.*``) —
účet a sociální graf (followery/following) z Twitteru/X.

Podporovaný formát: **JSON export uživatelů** (Takeout / cloud export)::

    [{"id": "1", "screen_name": "user_a", "name": "User A",
      "followers_count": 42, "friends_count": 7}]

   nebo warrant return s alternativními klíči::

    [{"username": "user_b", "full_name": "User B", "relationship": "follower"}]

Jeden uživatel = jeden artifact (``contact``, ``details.engine='twitter_users'``,
``mimetype='sns:twitter'``). Vlastní účet nesou ``relationship='account'``.
Neznámá pole se ignoruje.

Detekce: **name-based** — SNS marker (``twitter``) + klíčová slova
(``user``, ``follower``); v dispatchi pre-pass na celé cestě PŘED basename
chainem (generic basenames kolidují s ostatními detektory).
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

MAX_USERS_PER_FILE = 20_000


@dataclass
class TwUserRecord:
    """Jeden Twitter/X uživatel (účet / follower / following)."""

    username: str | None = None
    full_name: str | None = None
    relationship: str | None = None  # account / follower / following
    followers_count: int | None = None
    friends_count: int | None = None
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


def parse_twitter_users(data: bytes) -> list[TwUserRecord]:
    """ČISTÝ parser — Twitter/X users JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez uživatelů.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[TwUserRecord] = []

    def add(item: dict[str, Any], relationship: str | None = None) -> None:
        username = _to_str(
            item.get("screen_name", item.get("username", item.get("user")))
        )
        full_name = _to_str(item.get("name", item.get("full_name")))
        if not username and not full_name:
            return
        records.append(
            TwUserRecord(
                username=username,
                full_name=full_name,
                relationship=_to_str(item.get("relationship")) or relationship,
                followers_count=_to_int(
                    item.get("followers_count", item.get("followers"))
                ),
                friends_count=_to_int(
                    item.get("friends_count", item.get("following_count"))
                ),
            )
        )

    if isinstance(payload, dict):
        # vlastní účet — jediný objekt s identitou
        username = _to_str(
            payload.get("screen_name", payload.get("username", payload.get("user")))
        )
        full_name = _to_str(payload.get("name", payload.get("full_name")))
        if username or full_name:
            add(payload, "account")
        # seznamy followerů/following pod klíči
        for key in ("followers", "following", "friends"):
            val = payload.get(key)
            if isinstance(val, list):
                rel = "follower" if key == "followers" else "following"
                for item in val:
                    if isinstance(item, dict):
                        add(item, rel)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                add(item)

    records = records[:MAX_USERS_PER_FILE]
    if not records:
        raise TypeError("Nenalezeni Twitter/X uživatelé")
    return records


def build_twitter_user_artifacts(records: list[TwUserRecord]) -> list[Artifact]:
    """ČISTÁ funkce: z uživatelů vytvoří artifacty (contact)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {
            "engine": "twitter_users",
            "mimetype": "sns:twitter",
        }
        if r.relationship:
            details["relationship"] = r.relationship
        if r.followers_count is not None:
            details["followers_count"] = r.followers_count
        if r.friends_count is not None:
            details["friends_count"] = r.friends_count

        display = r.username or r.full_name or "?"
        title = f"Twitter/X {r.relationship or 'user'}: {display}"
        artifacts.append(
            Artifact(
                artifact_type="contact",
                timestamp=None,
                title=title[:120],
                details=details,
                confidence=0.6 if r.username else 0.4,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_twitter_user_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Twitter/X users JSON → contact artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("TwitterUsers %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_twitter_users(data)
    except (ValueError, TypeError) as e:
        logger.debug("TwitterUsers %s: %s", path.name, e)
        return []

    return build_twitter_user_artifacts(records)


def is_twitter_users_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Twitter/X users exportu.

    Vyžaduje SNS marker (``twitter``) v názvu/cestě + klíčová slova
    uživatelů — generic basenames bez markery nepadnou, aby se nekradly
    cizí exporty.
    """
    lower = name.lower()
    if "twitter" not in lower:
        return False
    if not any(k in lower for k in ("user", "follower")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
