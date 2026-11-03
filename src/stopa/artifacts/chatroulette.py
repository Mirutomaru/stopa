"""ETAPA B vlna 3 — Chatroulette parser (video chat carving).

AXIOM ekvivalent: ``ChatrouletteArtifact`` (``Magnet.Artifacts.Chatroulette``) —
zprávy z video chatu Chatroulette. AXIOM Artifact Reference popisuje atributy
``Type`` + ``Content``; zdroj je carved obsah ze souborů klienta / cache
prohlížeče.

Podporovaný formát: **textový chat log**::

    [2018-05-06 09:30:00] partner_abc said: hi there
    me: hello!

nebo **JSON pole záznamů** ``{"partner": ..., "message": ...}``.

Detekce: **name-based** (``chatroulette``, ``cr_chat``) + content check.

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

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_MESSAGES_PER_FILE = 5_000

# řádek s časem a odesílatelem: ``[ts] user said: text``
_LINE_RE = re.compile(r"^\[(?P<ts>[^\]]+)\]\s+(?P<user>\S+)\s+said:\s*(?P<msg>.*)$")
# řádek bez času: ``user: text``
_PLAIN_RE = re.compile(r"^(?P<user>[A-Za-z0-9_.\-]+):\s*(?P<msg>.+)$")


@dataclass
class ChatrouletteMessage:
    """Jedna zpráva video chatu Chatroulette."""

    partner: str = ""
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


def parse_chatroulette(data: bytes) -> list[ChatrouletteMessage]:
    """ČISTÝ parser — Chatroulette export → zprávy.

    Podporuje textový formát (řádky ``[ts] user said: text`` / ``user: text``)
    i JSON pole záznamů ``{"partner", "message"}``.

    Raises:
        ValueError: Neplatné JSON (při JSON vstupu).
        TypeError: Platné JSON, ale ne pole záznamů.
    """
    out: list[ChatrouletteMessage] = []
    text = data.decode("utf-8", errors="replace")

    # Konzervativní JSON detekce — textový log začíná na ``[ts] user said:``,
    # proto JSON uznáme jen při jasném signálu (objekt, uzavřené pole s {}/"",
    # nebo kompaktní pole v prvním řádku).
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
            payload = json.loads(candidate)
        except json.JSONDecodeError as e:
            raise ValueError(f"Neplatné JSON: {e}") from None
        if not isinstance(payload, list):
            raise TypeError("Očekáváno JSON pole záznamů")
        for item in payload:
            if len(out) >= MAX_MESSAGES_PER_FILE:
                logger.warning("Chatroulette: limit %d zpráv", MAX_MESSAGES_PER_FILE)
                break
            if not isinstance(item, dict):
                continue
            partner = str(item.get("partner") or item.get("user") or "").strip()
            msg = str(item.get("message") or item.get("text") or "").strip()
            ts_raw = item.get("timestamp") or item.get("time")
            if isinstance(ts_raw, (int, float)):
                try:
                    ts = datetime.fromtimestamp(float(ts_raw), tz=timezone.utc)
                except (OverflowError, OSError, ValueError):
                    ts = None
            else:
                ts = _parse_ts(str(ts_raw)) if ts_raw is not None else None
            if partner or msg:
                out.append(ChatrouletteMessage(partner=partner, message=msg, timestamp=ts))
        return out

    for line in text.splitlines():
        if len(out) >= MAX_MESSAGES_PER_FILE:
            logger.warning("Chatroulette: limit %d zpráv", MAX_MESSAGES_PER_FILE)
            break
        line = line.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if m:
            out.append(
                ChatrouletteMessage(
                    partner=m.group("user"),
                    message=m.group("msg").strip(),
                    timestamp=_parse_ts(m.group("ts")),
                )
            )
            continue
        m = _PLAIN_RE.match(line)
        if m:
            out.append(ChatrouletteMessage(partner=m.group("user"), message=m.group("msg").strip()))
    return out


def is_chatroulette_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Chatroulette exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("chatroulette", "cr_chat")):
        return False
    if head:
        h = head[:4096].lower()
        markers = (b"chatroulette", b"said:", b'"partner"', b'"message"')
        if not any(m in h for m in markers):
            return False
    return True


def build_chatroulette_artifacts(messages: list[ChatrouletteMessage]) -> list[Artifact]:
    """ČISTÁ funkce: ze zpráv vytvoří artifacty (messenger_message)."""
    artifacts: list[Artifact] = []
    for msg in messages:
        details: dict[str, Any] = {
            "engine": "chatroulette",
            "partner": msg.partner,
            "text": msg.message[:500],
            "type": "video_chat",
        }
        artifacts.append(
            Artifact(
                artifact_type="messenger_message",
                timestamp=msg.timestamp,
                title=f"Chatroulette {msg.partner or '?'}: {msg.message[:80]}",
                details=details,
                confidence=0.7 if msg.partner else 0.5,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_chatroulette_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Chatroulette → messenger_message artifacty.

    Chyby (poškozený soubor, IO, neplatné JSON) → log + prázdný výsledek,
    nikdy ne výjimka nahoru.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("Chatroulette %s: nelze číst (%s)", path, e)
        return []
    if not data:
        return []
    try:
        messages = parse_chatroulette(data)
    except (ValueError, TypeError) as e:
        logger.debug("Chatroulette %s: %s", path, e)
        return []
    return build_chatroulette_artifacts(messages)
