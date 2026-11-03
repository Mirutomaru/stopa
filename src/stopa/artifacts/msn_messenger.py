"""ETAPA B vlna 2 — MSN/Windows Live Messenger chat log parser (lokální profil).

AXIOM ekvivalent: ``MSNArtifact`` (``Magnet.Artifacts.MSN.MSNArtifact``) —
textové chat logy MSN / Windows Live / Skype for Business.

Podporovaný formát: **textový chat log** (.txt export)::

    Microsoft® Windows Live™ Messenger 8.5.0.134
    Chat started on 2/14/2010 at 10:23 AM
    ----------------------------------------
    jan@example.com (Jan Novák): Ahoj!
    petra@example.com (Petra): Jsi to ty?

Řádek zprávy = ``sender (display name): text``; sender je e-mail nebo nickname.
Nadpis s verzí + „Chat started on" potvrzuje formát (content check).

Detekce: **name-based** (``msn``, ``messenger``, ``chatlog``) + content check.

Artifact type: ``messenger_message`` — jedna zpráva = jeden artifact
(propojí se do chat view jako ostatní messaging typy).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_MESSAGES_PER_FILE = 5_000

# sender: e-mail, nickname s tečkou nebo display name; pak ": text"
_MSG_RE = re.compile(
    r"^(?P<sender>[^\n:]{2,64}?)(?:\s*\((?P<display>[^)]{1,80})\))?\s*:\s*(?P<text>.+)$"
)

# nadpis — verze klienta + čas zahájení chatu
_HEADER_RE = re.compile(
    r"(?im)^.*messenger\s+\d[\d.]*\s*$"
)
_STARTED_RE = re.compile(r"(?i)chat started on\s+(?P<when>[^\n]+)")


@dataclass
class MsnMessage:
    """Jedna zpráva MSN chat logu."""

    sender: str = ""
    display_name: str = ""
    text: str = ""


def parse_msn_chat_log(data: bytes) -> list[MsnMessage]:
    """ČISTÝ parser — MSN chat log text → zprávy.

    Raises:
        ValueError: Nadpis s verzí Messenger nenalezen (nejde o chat log).
    """
    head = data[:4096]
    if not _HEADER_RE.search(head.decode("utf-8", errors="replace")):
        raise ValueError("Nadpis MSN/Messenger verze nenalezen")

    text = data.decode("utf-8", errors="replace")
    messages: list[MsnMessage] = []
    in_chat = False

    for line in text.splitlines():
        if len(messages) >= MAX_MESSAGES_PER_FILE:
            logger.warning("MSN: limit %d zpráv", MAX_MESSAGES_PER_FILE)
            break

        stripped = line.strip()
        # hlavičkové řádky (verze, „Chat started on", oddělovače)
        if not in_chat:
            if _STARTED_RE.search(stripped):
                in_chat = True
                continue  # samotný řádek startu není zpráva
            elif re.fullmatch(r"[-=]{3,}", stripped):
                continue
            else:
                # řádek před „Chat started on" — hlavička, přeskočit
                if not _MSG_RE.match(stripped) or "messenger" in stripped.lower():
                    continue

        m = _MSG_RE.match(stripped)
        if not m:
            continue

        sender = m.group("sender").strip()
        # sender bez tečky ani @ a delší než 40 znaků = pravděpodobně šum
        if len(sender) > 40 and "." not in sender and "@" not in sender:
            continue

        messages.append(
            MsnMessage(
                sender=sender,
                display_name=(m.group("display") or "").strip(),
                text=m.group("text").strip(),
            )
        )

    return messages


def is_msn_chat_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce MSN/Messenger chat logu."""
    lower = name.lower()
    if not any(k in lower for k in ("msn", "messenger", "chatlog")):
        return False
    if head:
        h = head[:4096].lower()
        markers = (b"messenger", b"windows live")
        if not any(m in h for m in markers):
            return False
    return True


def build_msn_artifacts(messages: list[MsnMessage]) -> list[Artifact]:
    """ČISTÁ funkce: ze zpráv vytvoří artifacty (messenger_message)."""
    artifacts: list[Artifact] = []
    for msg in messages:
        who = msg.display_name or msg.sender
        details: dict[str, Any] = {
            "engine": "msn_messenger",
            "sender": msg.sender,
            "display_name": msg.display_name,
            "text": msg.text[:500],
        }
        artifacts.append(
            Artifact(
                artifact_type="messenger_message",
                timestamp=None,  # chat log nemá per-message čas (jen start)
                title=f"MSN {who}: {msg.text[:80]}",
                details=details,
                confidence=0.8 if msg.sender else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_msn_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — MSN chat log → messenger_message artifacty.

    Chyby (poškozený soubor, IO) → log + prázdný výsledek, nikdy ne výjimka.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("MSN %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        messages = parse_msn_chat_log(data)
    except ValueError as e:
        logger.debug("MSN %s: %s", path, e)
        return []

    return build_msn_artifacts(messages)
