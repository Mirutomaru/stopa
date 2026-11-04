"""ETAPA B vlna 11 — Twitter/X posts parser (cloud export / warrant return).

AXIOM ekvivalenty: ``CloudTwitterPostsArtifact`` + ``CloudTwitterPostsPublicArtifact``
+ ``CloudTwitterWarrantReturnPostsArtifact`` (``Magnet.Artifacts.Cloud.*``) —
veřejné i soukromé příspěvky účtu z Twitteru/X.

Podporovaný formát: **JSON export příspěvků** (Takeout / cloud export)::

    [{"id": "123", "author": "user_a", "text": "Ahoj světe!",
      "created_at": 1728000000, "likes": 5, "retweets": 2}]

   nebo warrant return s ISO datem a alternativními klíči::

    [{"tweet_id": "...", "from_user": "user_a", "body": "Ahoj!",
      "date": "2024-10-03T12:00:00Z"}]

Jeden příspěvek = jeden artifact (``sns_post``, ``details.engine='twitter_posts'``).
Retweety/odpovědi nesou ``post_type``; neznámá pole se ignoruje.

Detekce: **name-based** — SNS marker (``twitter``) + klíčová slova
(``post``, ``tweet``, ``status``); v dispatchi pre-pass na celé cestě PŘED
basename chainem (generic basenames kolidují s ostatními detektory).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_POSTS_PER_FILE = 5_000


@dataclass
class TwPostRecord:
    """Jeden Twitter/X příspěvek."""

    author: str | None = None
    text: str | None = None
    timestamp: int | None = None  # epoch sekundy
    post_type: str | None = None  # tweet / retweet / reply
    url: str | None = None
    likes: int | None = None
    retweets: int | None = None
    replies: int | None = None
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
    """Tolerantní konverze času na epoch sekundy.

    Podporuje: int/float (sekundy i milisekundy), ISO 8601 stringy
    (s ``Z`` i offsetem). Neznámé tvary → None.
    """
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


def _extract_posts(payload: Any) -> list[dict[str, Any]]:
    """Vytáhne seznam příspěvků (pole nebo pod klíčem)."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("posts", "tweets", "statuses", "value", "items"):
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def parse_twitter_posts(data: bytes) -> list[TwPostRecord]:
    """ČISTÝ parser — Twitter/X posts JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez příspěvků.
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[TwPostRecord] = []
    for item in _extract_posts(payload)[:MAX_POSTS_PER_FILE]:
        author = _to_str(
            item.get("author", item.get("from_user", item.get("user")))
        )
        text = _to_str(item.get("text", item.get("body", item.get("content"))))
        if not author and not text:
            continue

        post_type = None
        if item.get("is_retweet") or "retweeted_status" in item:
            post_type = "retweet"
        elif _to_str(item.get("in_reply_to_status_id")):
            post_type = "reply"
        else:
            raw_type = _to_str(item.get("type", item.get("post_type")))
            if raw_type in ("tweet", "retweet", "reply"):
                post_type = raw_type

        records.append(
            TwPostRecord(
                author=author,
                text=text,
                timestamp=_to_epoch(
                    item.get("created_at", item.get("timestamp", item.get("date")))
                ),
                post_type=post_type,
                url=_to_str(item.get("url", item.get("permalink"))),
                likes=_to_int(item.get("likes", item.get("like_count"))),
                retweets=_to_int(
                    item.get("retweets", item.get("retweet_count"))
                ),
                replies=_to_int(item.get("replies", item.get("reply_count"))),
            )
        )

    if not records:
        raise TypeError("Nenalezeny Twitter/X příspěvky")
    return records


def build_twitter_post_artifacts(records: list[TwPostRecord]) -> list[Artifact]:
    """ČISTÁ funkce: z příspěvků vytvoří artifacty (sns_post)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "twitter_posts"}
        if r.author:
            details["author"] = r.author
        if r.post_type:
            details["post_type"] = r.post_type
        if r.url:
            details["url"] = r.url[:300]
        if r.likes is not None:
            details["likes"] = r.likes
        if r.retweets is not None:
            details["retweets"] = r.retweets
        if r.replies is not None:
            details["replies"] = r.replies

        preview = (r.text or "")[:80]
        title = f"Twitter/X post ({r.author or '?'})" + (f": {preview}" if preview else "")
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


def extract_twitter_post_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Twitter/X posts JSON → sns_post artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("TwitterPosts %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_twitter_posts(data)
    except (ValueError, TypeError) as e:
        logger.debug("TwitterPosts %s: %s", path.name, e)
        return []

    return build_twitter_post_artifacts(records)


def is_twitter_posts_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Twitter/X posts exportu.

    Vyžaduje SNS marker (``twitter``) v názvu/cestě + klíčová slova
    příspěvků — generic basenames bez markery nepadnou, aby se nekradly
    cizí exporty.
    """
    lower = name.lower()
    if "twitter" not in lower:
        return False
    if not any(k in lower for k in ("post", "tweet", "status")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
