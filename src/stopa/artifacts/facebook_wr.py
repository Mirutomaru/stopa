"""ETAPA B vlna 11 — Facebook warrant return parser (cloud export / warrant return).

AXIOM ekvivalenty: ``CloudFacebookMessengerMessagesArtifact`` +
``CloudFacebookFriendsArtifact`` + ``CloudFacebookTimelineArtifact`` +
``CloudFacebookMobileTimelineArtifact`` + ``CloudFacebookProfileInfoArtifact``
(``Magnet.Artifacts.Cloud.*``) — Messenger zprávy, přátelé, timeline a profil.

Podporovaný formát: **JSON export** (Takeout / cloud export)::

    {"messages": [{"sender": "a", "recipient": "b", "body": "Ahoj!",
                   "timestamp": 1728000000}],
     "friends": [{"name": "User B", "username": "user_b"}],
     "timeline": [{"author": "a", "text": "Post!", "created_time": "..."}]}

   nebo ploché pole (warrant return)::

    [{"from": "a", "to": "b", "message": "Ahoj!", "time": "..."}]

Auto-detekce sekcí podle struktury payloadu — jeden soubor WR může nést
více sekcí. Zprávy = ``chat_message``, přátelé/profil = ``contact``
(``mimetype='sns:facebook'``), timeline = ``sns_post``. Neznámá pole se
ignoruje.

Detekce: **name-based** — SNS marker (``facebook``) v názvu/cestě; v
dispatchi pre-pass na celé cestě PŘED basename chainem (generic basenames
kolidují s ostatními detektory).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_MESSAGES_PER_FILE = 20_000
MAX_CONTACTS_PER_FILE = 20_000
MAX_POSTS_PER_FILE = 5_000


@dataclass
class FbMessageRecord:
    """Jedna Facebook Messenger zpráva."""

    sender: str | None = None
    recipient: str | None = None
    text: str | None = None
    timestamp: int | None = None  # epoch sekundy
    conversation_id: str | None = None


@dataclass
class FbContactRecord:
    """Jeden Facebook kontakt (přítel / vlastní účet)."""

    username: str | None = None
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    relationship: str | None = None  # friend / account


@dataclass
class FbPostRecord:
    """Jeden Facebook timeline příspěvek."""

    author: str | None = None
    text: str | None = None
    timestamp: int | None = None  # epoch sekundy
    url: str | None = None
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


def _to_epoch(value: Any) -> int | None:
    """Tolerantní konverze času na epoch sekundy (int/ms/ISO 8601)."""
    if value is None or isinstance(value, bool):
        return None
    num = _to_int(value)
    if num is not None:
        # milisekundy — heuristika: epoch > 1e12 už jsou ms (rok ~33658)
        return num // 1_000 if abs(num) >= 10**12 else num
    text = _to_str(value)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _extract_list(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """Vytáhne seznam položek (payload je pole nebo dict s klíčem)."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in keys:
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def parse_facebook_messages(data: bytes) -> list[FbMessageRecord]:
    """ČISTÝ parser — Facebook Messenger zprávy JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez zpráv.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[FbMessageRecord] = []

    def add(item: dict[str, Any], conversation_id: str | None = None) -> None:
        sender = _to_str(item.get("sender", item.get("from")))
        recipient = _to_str(item.get("recipient", item.get("to")))
        text = _to_str(
            item.get("body", item.get("text", item.get("message", item.get("content"))))
        )
        if not sender and not text:
            return
        records.append(
            FbMessageRecord(
                sender=sender,
                recipient=recipient,
                text=text,
                timestamp=_to_epoch(
                    item.get("timestamp", item.get("time", item.get("created_time")))
                ),
                conversation_id=conversation_id,
            )
        )

    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            nested = item.get("messages")
            if isinstance(nested, list) and any(
                isinstance(m, dict) for m in nested[:3]
            ):
                conv_id = _to_str(item.get("id", item.get("conversation_id")))
                for m in nested:
                    if isinstance(m, dict):
                        add(m, conv_id)
            else:
                add(item)
    elif isinstance(payload, dict):
        for key in ("messages", "conversations", "value"):
            val = payload.get(key)
            if not isinstance(val, list):
                continue
            for item in val:
                if not isinstance(item, dict):
                    continue
                # vnořená konverzace — {"id": ..., "messages": [...]}
                nested = item.get("messages")
                if isinstance(nested, list) and any(
                    isinstance(m, dict) for m in nested[:3]
                ):
                    conv_id = _to_str(item.get("id", item.get("conversation_id")))
                    for m in nested:
                        if isinstance(m, dict):
                            add(m, conv_id)
                else:
                    add(item)

    records = records[:MAX_MESSAGES_PER_FILE]
    if not records:
        raise TypeError("Nenalezeny Facebook Messenger zprávy")
    return records


def parse_facebook_friends(data: bytes) -> list[FbContactRecord]:
    """ČISTÝ parser — Facebook přátelé JSON → kontakty.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez kontaktů.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[FbContactRecord] = []

    def add(item: dict[str, Any], relationship: str | None = None) -> None:
        username = _to_str(
            item.get("username", item.get("screen_name", item.get("id")))
        )
        full_name = _to_str(item.get("name", item.get("full_name")))
        if not username and not full_name:
            return
        records.append(
            FbContactRecord(
                username=username,
                full_name=full_name,
                email=_to_str(item.get("email")),
                phone=_to_str(item.get("phone", item.get("phone_number"))),
                relationship=_to_str(item.get("relationship")) or relationship,
            )
        )

    if isinstance(payload, dict):
        # vlastní účet — jediný objekt s identitou (bez sekcí přátel)
        has_friends = any(
            isinstance(payload.get(k), list) for k in ("friends", "contacts")
        )
        name = _to_str(payload.get("name"))
        email = _to_str(payload.get("email"))
        if not has_friends and (name or email):
            add(payload, "account")
        for key in ("friends", "contacts"):
            val = payload.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        add(item, "friend")
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                add(item, "friend")

    records = records[:MAX_CONTACTS_PER_FILE]
    if not records:
        raise TypeError("Nenalezeni Facebook přátelé")
    return records


def parse_facebook_timeline(data: bytes) -> list[FbPostRecord]:
    """ČISTÝ parser — Facebook timeline JSON → příspěvky.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez příspěvků.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[FbPostRecord] = []
    for item in _extract_list(
        payload, ("timeline", "posts", "feed", "value")
    )[:MAX_POSTS_PER_FILE]:
        author = _to_str(item.get("author", item.get("from", item.get("user"))))
        text = _to_str(item.get("text", item.get("message", item.get("body"))))
        if not author and not text:
            continue
        records.append(
            FbPostRecord(
                author=author,
                text=text,
                timestamp=_to_epoch(
                    item.get("created_time", item.get("timestamp", item.get("time")))
                ),
                url=_to_str(item.get("url", item.get("permalink"))),
            )
        )

    if not records:
        raise TypeError("Nenalezeny Facebook timeline příspěvky")
    return records


def parse_facebook_profile(data: bytes) -> FbContactRecord | None:
    """ČISTÝ parser — Facebook profil info JSON → kontakt (vlastní účet)."""
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(payload, dict):
        return None
    name = _to_str(payload.get("name", payload.get("full_name")))
    email = _to_str(payload.get("email"))
    phone = _to_str(payload.get("phone", payload.get("phone_number")))
    username = _to_str(
        payload.get("username", payload.get("screen_name", payload.get("id")))
    )
    if not (name or email or phone or username):
        return None
    return FbContactRecord(
        username=username,
        full_name=name,
        email=email,
        phone=phone,
        relationship="account",
    )


def build_facebook_message_artifacts(records: list[FbMessageRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze zpráv vytvoří artifacty (chat_message)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "facebook_wr"}
        if r.sender:
            details["sender"] = r.sender
        if r.recipient:
            details["recipient"] = r.recipient
        if r.conversation_id:
            details["conversation_id"] = r.conversation_id

        title_parts = []
        if r.sender:
            title_parts.append(f"od {r.sender}")
        if r.recipient:
            title_parts.append(f"→ {r.recipient}")
        preview = (r.text or "")[:80]
        title = f"Facebook Messenger ({', '.join(title_parts)})" + (f": {preview}" if preview else "")

        artifacts.append(
            Artifact(
                artifact_type="chat_message",
                timestamp=None,  # epoch v details — konverze na ISO v reportu
                title=title[:120],
                details=details | ({"timestamp_epoch": r.timestamp} if r.timestamp is not None else {}),
                confidence=0.7 if (r.sender and r.text) else 0.5,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def build_facebook_contact_artifacts(records: list[FbContactRecord]) -> list[Artifact]:
    """ČISTÁ funkce: z kontaktů vytvoří artifacty (contact)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {
            "engine": "facebook_wr",
            "mimetype": "sns:facebook",
        }
        if r.relationship:
            details["relationship"] = r.relationship
        if r.email:
            details["email"] = r.email
        if r.phone:
            details["phone"] = r.phone

        display = r.full_name or r.username or "?"
        title = f"Facebook {r.relationship or 'user'}: {display}"
        artifacts.append(
            Artifact(
                artifact_type="contact",
                timestamp=None,
                title=title[:120],
                details=details,
                confidence=0.6 if (r.username or r.full_name) else 0.4,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def build_facebook_timeline_artifacts(records: list[FbPostRecord]) -> list[Artifact]:
    """ČISTÁ funkce: z timeline příspěvků vytvoří artifacty (sns_post)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {
            "engine": "facebook_wr",
            "post_type": "timeline",
        }
        if r.author:
            details["author"] = r.author
        if r.url:
            details["url"] = r.url[:300]

        preview = (r.text or "")[:80]
        title = f"Facebook timeline ({r.author or '?'})" + (f": {preview}" if preview else "")
        artifacts.append(
            Artifact(
                artifact_type="sns_post",
                timestamp=None,  # epoch v details — konverze na ISO v reportu
                title=title[:120],
                details=details | ({"timestamp_epoch": r.timestamp} if r.timestamp is not None else {}),
                confidence=0.7 if (r.author and r.text) else 0.5,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_facebook_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Facebook WR JSON → artifacty podle obsahu.

    Auto-detekce typu podle struktury payloadu (zprávy / přátelé / timeline /
    profil) — jeden soubor WR může nést více sekcí.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("FacebookWR %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    artifacts: list[Artifact] = []
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.debug("FacebookWR %s: neplatné JSON", path.name)
        return []

    # auto-detekce sekcí podle klíčů payloadu
    lower_keys = set()
    if isinstance(payload, dict):
        lower_keys = {str(k).lower() for k in payload}
    elif isinstance(payload, list) and payload:
        first = next((x for x in payload if isinstance(x, dict)), {})
        lower_keys = {str(k).lower() for k in first}

    try:
        if any(k in lower_keys for k in ("messages", "conversations")) or (
            isinstance(payload, list) and any(
                isinstance(x, dict)
                and (
                    "body" in x
                    or "message" in x
                    or ("from" in x and "to" in x)
                )
                for x in payload[:5]
            )
        ):
            artifacts.extend(build_facebook_message_artifacts(parse_facebook_messages(data)))
    except (ValueError, TypeError):
        logger.debug("Facebook messages: parse selhal → bez message artefaktů")

    try:
        if any(k in lower_keys for k in ("friends", "contacts")) or (
            isinstance(payload, list) and any(
                isinstance(x, dict)
                and ("name" in x or "username" in x)
                and not ("body" in x or "message" in x or "text" in x)
                for x in payload[:5]
            )
        ):
            artifacts.extend(build_facebook_contact_artifacts(parse_facebook_friends(data)))
    except (ValueError, TypeError):
        logger.debug("Facebook contacts/friends: parse selhal → bez contact artefaktů")

    try:
        if any(k in lower_keys for k in ("timeline", "posts", "feed")) or (
            isinstance(payload, list) and any(
                isinstance(x, dict)
                and ("created_time" in x or "post_id" in x)
                for x in payload[:5]
            )
        ):
            artifacts.extend(build_facebook_timeline_artifacts(parse_facebook_timeline(data)))
    except (ValueError, TypeError):
        logger.debug("Facebook timeline: parse selhal → bez timeline artefaktů")

    try:
        if isinstance(payload, dict) and any(
            k in lower_keys for k in ("name", "email", "phone")
        ) and not (lower_keys & {"messages", "friends", "contacts", "timeline"}):
            profile = parse_facebook_profile(data)
            if profile:
                artifacts.extend(build_facebook_contact_artifacts([profile]))
    except (ValueError, TypeError):
        logger.debug("Facebook profile: parse selhal → bez profilu")

    return artifacts


def is_facebook_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Facebook WR exportu.

    Vyžaduje SNS marker (``facebook``) v názvu/cestě — generic basenames bez
    markery nepadnou, aby se nekradly cizí exporty.
    """
    lower = name.lower()
    if "facebook" not in lower:
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
