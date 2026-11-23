"""ETAPA B vlna 3 — Bebo Live Chat parser (carving text/JSON).

AXIOM ekvivalent: ``BeboArtifact`` (``Magnet.Artifacts.Bebo``) — zprávy
Bebo Live Chatu. AXIOM Artifact Reference popisuje atributy ``Type`` +
``Content``; zdroj je carved obsah (textový export / JSON fragmenty) ze
souborů Bebo klienta nebo prohlížeče.

Podporovaný formát: **textový chat log**::

    [2019-03-04 12:00:01] user_a said: ahoj
    user_b: jak se máš?

nebo **JSON pole záznamů** ``{"user": ..., "message": ...}``.

Detekce: **name-based** (``bebo``, ``live chat``) + content check.

Artifact type: ``messenger_message`` — jedna zpráva = jeden artifact
(propojí se do chat view jako ostatní messaging typy).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_MESSAGES_PER_FILE = 5_000

# řádek s časem a odesílatelem: ``[ts] user said: text``
_LINE_RE = re.compile(r"^\[(?P<ts>[^\]]+)\]\s+(?P<user>\S+)\s+said:\s*(?P<msg>.*)$")
# řádek bez času: ``user: text``
_PLAIN_RE = re.compile(r"^(?P<user>[A-Za-z0-9_.\-]+):\s*(?P<msg>.+)$")


@dataclass
class BeboMessage:
    """Jedna zpráva Bebo Live Chatu."""

    user: str = ""
    message: str = ""
    timestamp: datetime | None = None


def _parse_ts(raw: str | None) -> datetime | None:
    """Konverze časového řetězce na UTC datetime (None při selhání)."""
    if not raw:
        return None
    s = raw.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_bebo_chat(data: bytes) -> list[BeboMessage]:
    """ČISTÝ parser — Bebo Live Chat export → zprávy.

    Podporuje textový formát (řádky ``[ts] user said: text`` / ``user: text``)
    i JSON pole záznamů ``{"user", "message"}``.

    Raises:
        ValueError: Neplatné JSON (při JSON vstupu).
        TypeError: Platné JSON, ale ne pole záznamů.
    """
    out: list[BeboMessage] = []
    text = data.decode("utf-8", errors="replace")

    # Zkusit JSON pole záznamů. Detekce je konzervativní — textový log začíná
    # na ``[ts] user said:``, proto JSON uznáme jen při jasném signálu:
    # objekt, uzavřené pole obsahující {}/"", nebo kompaktní pole v 1. řádku.
    candidate = text.strip()
    first_line = candidate.split("\n", 1)[0] if candidate else ""
    looks_json = (
        (candidate.startswith("{") and candidate.endswith("}"))
        or (
            candidate.startswith("[")
            and candidate.endswith("]")
            and ("{" in candidate or '"' in candidate)
        )
        or (candidate.startswith("[") and ("{" in first_line or '"' in first_line))
    )
    if looks_json:
        try:
            payload = bounded_json_loads(candidate)
        except json.JSONDecodeError as e:
            raise ValueError(f"Neplatné JSON: {e}") from None
        if not isinstance(payload, list):
            raise TypeError("Očekáváno JSON pole záznamů")
        for item in payload:
            if len(out) >= MAX_MESSAGES_PER_FILE:
                logger.warning("Bebo: limit %d zpráv", MAX_MESSAGES_PER_FILE)
                break
            if not isinstance(item, dict):
                continue
            user = str(item.get("user") or item.get("from") or "").strip()
            msg = str(item.get("message") or item.get("text") or "").strip()
            ts_raw = item.get("timestamp") or item.get("time")
            if isinstance(ts_raw, (int, float)):
                try:
                    ts = datetime.fromtimestamp(float(ts_raw), tz=timezone.utc)
                except (OverflowError, OSError, ValueError):
                    ts = None
            else:
                ts = _parse_ts(str(ts_raw)) if ts_raw is not None else None
            if user or msg:
                out.append(BeboMessage(user=user, message=msg, timestamp=ts))
        return out

    # Textový formát řádek po řádku.
    for line in text.splitlines():
        if len(out) >= MAX_MESSAGES_PER_FILE:
            logger.warning("Bebo: limit %d zpráv", MAX_MESSAGES_PER_FILE)
            break
        line = line.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if m:
            out.append(
                BeboMessage(
                    user=m.group("user"),
                    message=m.group("msg").strip(),
                    timestamp=_parse_ts(m.group("ts")),
                )
            )
            continue
        m = _PLAIN_RE.match(line)
        if m:
            out.append(BeboMessage(user=m.group("user"), message=m.group("msg").strip()))
    return out


def is_bebo_chat_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Bebo Live Chat exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("bebo", "live chat")):
        return False
    if head:
        h = head[:4096].lower()
        markers = (b"bebo", b"said:", b'"user"', b'"message"')
        if not any(m in h for m in markers):
            return False
    return True


def build_bebo_artifacts(messages: list[BeboMessage]) -> list[Artifact]:
    """ČISTÁ funkce: ze zpráv vytvoří artifacty (messenger_message)."""
    artifacts: list[Artifact] = []
    for msg in messages:
        details: dict[str, Any] = {
            "engine": "bebo_chat",
            "user": msg.user,
            "text": msg.message[:500],
            "type": "live_chat",
        }
        artifacts.append(
            Artifact(
                artifact_type="messenger_message",
                timestamp=msg.timestamp,
                title=f"Bebo {msg.user or '?'}: {msg.message[:80]}",
                details=details,
                confidence=0.7 if msg.user else 0.5,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_bebo_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Bebo Live Chat → messenger_message artifacty.

    Chyby (poškozený soubor, IO, neplatné JSON) → log + prázdný výsledek,
    nikdy ne výjimka nahoru.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("Bebo %s: nelze číst (%s)", path, e)
        return []
    if not data:
        return []
    try:
        messages = parse_bebo_chat(data)
    except (ValueError, TypeError) as e:
        logger.debug("Bebo %s: %s", path, e)
        return []
    return build_bebo_artifacts(messages)
