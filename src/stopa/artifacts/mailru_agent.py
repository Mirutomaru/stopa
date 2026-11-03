"""ETAPA B vlna 3 — Mail.Ru Agent parser (desktop IM, lokální logy).

AXIOM ekvivalenty: ``MailRuChatArtifact`` + ``MailRuContactArtifact`` +
``MailRuGroupArtifact`` (``Magnet.Artifacts.MailRu``) — desktop komunikátor
Mail.Ru Agent. AXIOM Artifact Reference popisuje atributy:

- **Messages**: Local User, Remote User ID, Remote Participant Display Name,
  Created Date/Time, Message, Type (Text/Voice Call/Video Call/File Transfer),
  Duration (Seconds), Direction, File Name.
- **Contacts**: First Name, Last Name, Email, Last Seen, Locale.
- **Chat Non-Carved / Groups**: Local User, Name (název skupiny).

Podporovaný formát: **textový lokální log** Mail.Ru Agentu (export/čtení z
lokálního profilu). Řádky jsou oddělené ``|``; typ souboru se určí podle
názvu (contact/group) a obsahu.

Detekce: **name-based** (``mailru``, ``mail.ru``, ``agent``) + content check.

Artifact types: zprávy → ``messenger_message``, kontakty → ``contact``,
skupiny → ``contact`` (group).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_LINES_PER_FILE = 20_000

# typ zprávy → AXIOM hodnoty
_MSG_TYPES = ("Text Message", "Voice Call", "Video Call", "File Transfer")

_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)$"
)


@dataclass
class MailRuMessage:
    """Jedna zpráva / událost Mail.Ru Agent chat logu."""

    local_user: str = ""
    remote_id: str = ""
    display_name: str = ""
    created_dt: datetime | None = None
    message: str = ""
    msg_type: str = "Text Message"
    duration_s: int | None = None
    direction: str = ""
    file_name: str = ""


@dataclass
class MailRuContact:
    """Kontakt Mail.Ru Agent."""

    first_name: str = ""
    last_name: str = ""
    email: str = ""
    last_seen: datetime | None = None
    locale: str = ""


def _parse_ts(raw: str) -> datetime | None:
    raw = raw.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_mailru_chat_log(data: bytes) -> list[MailRuMessage]:
    """ČISTÝ parser — Mail.Ru Agent chat log → zprávy.

    Očekávaný řádek (``|`` oddělovač)::

        2015-03-14 10:23:45 | IN | user123 | John Doe : Ahoj!
        2015-03-14 10:24:01 | OUT | user123 | John Doe : [Voice Call] 120

    Pole: ``ts | direction | remote_id | display_name : message``.
    Volitelný typ/délka se vyčte z hranatých závorek v textu.
    """
    text = data.decode("utf-8", errors="replace")
    out: list[MailRuMessage] = []

    for line in text.splitlines():
        if len(out) >= MAX_LINES_PER_FILE:
            logger.warning("Mail.ru: limit %d řádků", MAX_LINES_PER_FILE)
            break
        stripped = line.strip()
        if not stripped or "|" not in stripped:
            continue

        parts = [p.strip() for p in stripped.split("|")]
        # minimálně ts + direction + remote_id
        if len(parts) < 3:
            continue
        ts_raw, direction, remote_id = parts[0], parts[1].upper(), parts[2]
        created_dt = _parse_ts(ts_raw)
        if created_dt is None:
            continue

        display_name = ""
        message = ""
        # zbývající části: [display_name :] message
        rest = "|".join(parts[3:])
        m = re.match(r"^(?P<name>[^:]{1,80}?)\s*:\s*(?P<body>.+)$", rest)
        if m:
            display_name = m.group("name").strip()
            message = m.group("body").strip()
        else:
            message = rest.strip()

        # typ + délka z hranatých závorek na začátku textu
        msg_type = "Text Message"
        duration_s: int | None = None
        vm = re.match(r"^\[(?P<t>[A-Za-z ]+)\]\s*(?:(\d+))?\s*(.*)$", message)
        if vm and vm.group("t").strip() in _MSG_TYPES:
            msg_type = vm.group("t").strip()
            if vm.group(2):
                duration_s = int(vm.group(2))
            message = (vm.group(3) or "").strip()

        out.append(
            MailRuMessage(
                local_user="",  # lokální uživatel je kontext profilu, ne řádku
                remote_id=remote_id,
                display_name=display_name,
                created_dt=created_dt,
                message=message,
                msg_type=msg_type,
                duration_s=duration_s,
                direction=direction,
            )
        )

    return out


def parse_mailru_contacts(data: bytes) -> list[MailRuContact]:
    """ČISTÝ parser — Mail.Ru Agent kontakty → záznamy.

    Řádek (``|`` oddělovač)::

        John|Doe|john@example.com|2015-03-14 10:00:00|Czech Republic
    """
    text = data.decode("utf-8", errors="replace")
    out: list[MailRuContact] = []
    for line in text.splitlines():
        if len(out) >= MAX_LINES_PER_FILE:
            break
        stripped = line.strip()
        if not stripped or "|" not in stripped:
            continue
        parts = [p.strip() for p in stripped.split("|")]
        if len(parts) < 3:
            continue
        first, last, email = parts[0], parts[1], parts[2]
        last_seen = _parse_ts(parts[3]) if len(parts) > 3 else None
        locale = parts[4] if len(parts) > 4 else ""
        out.append(
            MailRuContact(
                first_name=first,
                last_name=last,
                email=email,
                last_seen=last_seen,
                locale=locale,
            )
        )
    return out


def is_mailru_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Mail.Ru Agent logů."""
    lower = name.lower()
    if not any(k in lower for k in ("mailru", "mail.ru", "agent")):
        return False
    if head:
        h = head[:4096].lower()
        # textový log s | oddělovači nebo kontakty — jemný content check
        if b"|" not in h and b"@mail.ru" not in h:
            return False
    return True


def build_mailru_artifacts(
    messages: list[MailRuMessage], contacts: list[MailRuContact]
) -> list[Artifact]:
    """ČISTÁ funkce: z Mail.Ru dat vytvoří artifacty."""
    artifacts: list[Artifact] = []

    for m in messages:
        who = m.display_name or m.remote_id
        details: dict[str, Any] = {
            "engine": "mailru_agent",
            "remote_id": m.remote_id,
            "display_name": m.display_name,
            "message": m.message[:500],
            "msg_type": m.msg_type,
            "direction": m.direction,
        }
        if m.duration_s is not None:
            details["duration_s"] = m.duration_s
        artifacts.append(
            Artifact(
                artifact_type="messenger_message",
                timestamp=m.created_dt,
                title=f"Mail.ru {who}: {m.message[:80] or m.msg_type}",
                details=details,
                confidence=0.7 if m.remote_id else 0.5,
                parser_version=PARSER_VERSION,
            )
        )

    for c in contacts:
        name = f"{c.first_name} {c.last_name}".strip() or c.email or "(neznámý)"
        details = {
            "engine": "mailru_agent",
            "first_name": c.first_name,
            "last_name": c.last_name,
            "email": c.email,
            "locale": c.locale,
        }
        artifacts.append(
            Artifact(
                artifact_type="contact",
                timestamp=c.last_seen,
                title=f"Mail.ru kontakt — {name}",
                details=details,
                confidence=0.8 if c.email else 0.6,
                parser_version=PARSER_VERSION,
            )
        )

    return artifacts


def extract_mailru_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Mail.Ru Agent log → artifacty.

    Typ souboru (chat/contacts) určí podle názvu; chyby → log + prázdný výsledek.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("Mail.ru %s: nelze číst (%s)", path, e)
        return []
    if not data:
        return []

    lower = path.name.lower()
    messages: list[MailRuMessage] = []
    contacts: list[MailRuContact] = []

    try:
        if "contact" in lower or b"@mail.ru" in data[:4096].lower():
            contacts = parse_mailru_contacts(data)
        else:
            messages = parse_mailru_chat_log(data)
    except (ValueError, TypeError) as e:
        logger.debug("Mail.ru %s: %s", path, e)

    if not messages and not contacts:
        return []
    return build_mailru_artifacts(messages, contacts)
