"""ETAPA B vlna 10 — Instagram Posts/Media/Photos/Stories/Comments parser (cloud export).

AXIOM ekvivalenty: ``InstagramPostsArtifact`` + ``InstagramPostsAxiom2Pt1Artifact``
+ ``InstagramMediaArtifact`` + ``InstagramPhotosArtifact`` +
``InstagramArchivedStoriesArtifact`` + ``InstagramDirectStoriesArtifact`` +
``InstagramCommentsArtifact`` (``Magnet.Artifacts.Cloud.*``) — obsah účtu.

Podporovaný formát: **JSON export příspěvků** (Takeout / cloud export)::

    [{"id": "post-1", "caption": "Víkend u jezera",
      "timestamp": 1728000000, "likes_count": 42,
      "media_url": "https://...", "comments": [
          {"user": "fan_1", "text": "Krásné!", "time": "..."}]}]

   nebo plošný seznam médií (``InstagramMediaArtifact``)::

    [{"id": "m-1", "url": "https://...", "type": "image", "timestamp": ...}]

Jeden příspěvek = jeden artifact (``sns_post``, ``details.engine='instagram_posts'``);
jeden komentář = jeden artifact (``sns_comment``). Neznámá pole se ignoruje.

Detekce: **name-based** — SNS marker (``instagram``) + klíčová slova
(``posts``, ``media``, ``photos``, ``stories``, ``comments``); v dispatchi
pre-pass na celé cestě PŘED basename chainem.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_POSTS_PER_FILE = 5_000


@dataclass
class IgPostRecord:
    """Jeden Instagram příspěvek / médium."""

    post_id: str | None = None
    caption: str | None = None
    timestamp: int | None = None
    likes_count: int | None = None
    media_url: str | None = None
    media_type: str | None = None  # image / video / carousel / story
    is_story: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class IgCommentRecord:
    """Jeden komentář pod příspěvkem."""

    post_id: str | None = None
    user: str | None = None
    text: str | None = None
    timestamp: int | None = None


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


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    """Vytáhne seznam položek (pole nebo pod klíčem)."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("posts", "media", "photos", "stories", "value", "items"):
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def parse_instagram_posts(data: bytes) -> tuple[list[IgPostRecord], list[IgCommentRecord]]:
    """ČISTÝ parser — Instagram posts JSON → (příspěvky, komentáře).

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez položek.
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    items = _extract_items(payload)
    if not items:
        raise TypeError("Nenalezeny Instagram položky")

    posts: list[IgPostRecord] = []
    comments: list[IgCommentRecord] = []

    for item in items[:MAX_POSTS_PER_FILE]:
        post_id = _to_str(item.get("id", item.get("post_id")))
        caption = _to_str(item.get("caption", item.get("text")))
        ts = _to_int(item.get("timestamp", item.get("time", item.get("created_time"))))
        likes = _to_int(
            item.get("likes_count", item.get("like_count", item.get("likes")))
        )
        media_url = _to_str(item.get("media_url", item.get("url", item.get("link"))))
        media_type = _to_str(item.get("type", item.get("media_type")))

        # story detekce — archivované / sdílené stories nesou marker v názvu klíče
        is_story = bool(
            item.get("isStory") or item.get("story_id") or "story" in (media_type or "").lower()
        )

        extra: dict[str, Any] = {}
        location = _to_str(item.get("location", item.get("place_name")))
        if location:
            extra["location"] = location[:200]

        posts.append(
            IgPostRecord(
                post_id=post_id,
                caption=caption,
                timestamp=ts,
                likes_count=likes,
                media_url=media_url,
                media_type=media_type,
                is_story=is_story,
                extra=extra,
            )
        )

        # komentáře vnořené pod příspěvkem
        raw_comments = item.get("comments")
        if isinstance(raw_comments, list):
            for c in raw_comments:
                if not isinstance(c, dict):
                    continue
                comments.append(
                    IgCommentRecord(
                        post_id=post_id,
                        user=_to_str(c.get("user", c.get("username"))),
                        text=_to_str(c.get("text", c.get("comment"))),
                        timestamp=_to_int(c.get("time", c.get("timestamp"))),
                    )
                )

    return posts, comments


def build_instagram_post_artifacts(
    posts: list[IgPostRecord],
    comments: list[IgCommentRecord] | None = None,
) -> list[Artifact]:
    """ČISTÁ funkce: z příspěvků a komentářů vytvoří artifacty."""
    artifacts: list[Artifact] = []

    for p in posts:
        details: dict[str, Any] = {"engine": "instagram_posts"}
        if p.post_id:
            details["post_id"] = p.post_id
        if p.likes_count is not None:
            details["likes_count"] = p.likes_count
        if p.media_url:
            details["media_url"] = p.media_url[:300]
        if p.media_type:
            details["media_type"] = p.media_type
        if p.is_story:
            details["is_story"] = True
        details.update(p.extra)

        kind = "Story" if p.is_story else "Post"
        preview = (p.caption or "")[:80]
        title = f"Instagram {kind}" + (f": {preview}" if preview else "")

        artifacts.append(
            Artifact(
                artifact_type="sns_post",
                timestamp=None,  # epoch v details — konverze na ISO v reportu
                title=title[:120],
                details=details | ({"timestamp_epoch": p.timestamp} if p.timestamp is not None else {}),
                confidence=0.7 if (p.post_id and (p.caption or p.media_url)) else 0.5,
                parser_version=PARSER_VERSION,
            )
        )

    for c in comments or []:
        details: dict[str, Any] = {"engine": "instagram_posts"}
        if c.post_id:
            details["post_id"] = c.post_id
        if c.user:
            details["user"] = c.user
        preview = (c.text or "")[:80]
        title = f"Instagram comment ({c.user or '?'})" + (f": {preview}" if preview else "")

        artifacts.append(
            Artifact(
                artifact_type="sns_comment",
                timestamp=None,
                title=title[:120],
                details=details | ({"timestamp_epoch": c.timestamp} if c.timestamp is not None else {}),
                confidence=0.6 if (c.user and c.text) else 0.4,
                parser_version=PARSER_VERSION,
            )
        )

    return artifacts


def extract_instagram_post_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Instagram posts JSON → sns_post/sns_comment artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("InstagramPosts %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        posts, comments = parse_instagram_posts(data)
    except (ValueError, TypeError) as e:
        logger.debug("InstagramPosts %s: %s", path.name, e)
        return []

    return build_instagram_post_artifacts(posts, comments)


def is_instagram_posts_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Instagram posts/media/stories/comments exportu.

    Vyžaduje SNS marker (``instagram``) v názvu/cestě + klíčová slova obsahu —
    generic basenames bez markery nepadnou, aby se nekradly cizí exporty.
    """
    lower = name.lower()
    if "instagram" not in lower:
        return False
    if not any(k in lower for k in ("post", "media", "photo", "stor", "comment")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
