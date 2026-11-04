"""ETAPA B vlna 1 — mbox / EML email parser.

AXIOM ekvivalent: ``CloudMboxEmailArtifact`` + ``OfflineGmailArtifact``.

Podporované formáty:
- **mbox** (Unix mailbox) — soubor s více zprávami, oddělenými řádkem
  začínajícím ``From `` (mbox delimiter; v těle je „From " escapováno
  jako ``>From ``). Detekce name-based (``.mbox``, ``.eml``) — mbox nemá
  spolehlivou magic bytes.
- **EML / RFC822** — jedna zpráva, hlavičky + prázdný řádek + tělo.

Parsuje se ručně (ne stdlib ``email``) — determinismus + obrana proti
patologickým vstupům (stdlib email má známé DoS problémy na poškozených
hlavičkách). Hlavičky: From/To/Cc/Subject/Date/Message-ID; přílohy z
``Content-Disposition: attachment; filename=...``.

Artifact type: ``email_message`` — jedna zpráva = jeden artifact.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_MESSAGES_PER_FILE = 10_000  # obrana proti patologickému souboru
BODY_PREVIEW_LEN = 500  # nevtěsnávat celé tělo do detailů
MAX_ATTACHMENTS = 20

# mbox delimiter — řádek začínající přesně "From " (F + mezera)
_MBOX_DELIM = b"From "
# RFC822 hlavička, kterou .eml soubor vždy obsahuje na začátku
_EML_HEAD_MARKERS = (b"From:", b"To:", b"Subject:", b"Date:", b"Received:")

_FILENAME_RE = re.compile(r'filename\*?="?([^";]+)"?', re.IGNORECASE)


@dataclass
class EmailMessage:
    """Jeden email — hlavičky + tělo (preview)."""

    sender: str = ""
    recipients: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    subject: str = ""
    date: datetime | None = None
    message_id: str = ""
    attachments: list[str] = field(default_factory=list)
    body_preview: str = ""


def _decode_header(raw: bytes) -> str:
    """Bezpečné dekodování hlavičky (utf-8 → latin-1 fallback)."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def _parse_date(raw: str) -> datetime | None:
    """RFC2822 datum z hlavičky Date — neplatné → None (nikdy výjimka)."""
    if not raw:
        return None
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(raw.strip())
        if dt is None or dt.year < 1980 or dt.year > 2200:
            return None
        return dt
    except Exception:  # noqa: BLE001 — poškozené datum je běžné u starých zpráv
        return None


def _split_headers(raw: bytes) -> tuple[dict[str, str], int]:
    """Rozloží hlavičky zprávy (s foldingem) → (mapa, offset těla).

    Hlavičky končí prvním prázdným řádkem. Pokračovací řádky (začínající
    mezerou/tabulátorem) se připojí k předchozí hlavičce (RFC822 folding).
    """
    headers: dict[str, str] = {}
    lines = raw.split(b"\n")
    body_start = 0
    current_key: str | None = None

    for i, line in enumerate(lines):
        if not line.strip():
            body_start = i + 1
            break
        text = _decode_header(line.rstrip(b"\r"))
        if text[:1] in (" ", "\t") and current_key is not None:
            # folding — pokračování předchozí hlavičky
            headers[current_key] += " " + text.strip()
            continue
        if ":" in text:
            key, _, value = text.partition(":")
            current_key = key.strip().lower()
            headers[current_key] = value.strip()

    return headers, body_start


def _extract_attachments(raw: bytes) -> list[str]:
    """Názvy příloh z Content-Disposition hlaviček (celá zpráva)."""
    out: list[str] = []
    for m in re.finditer(rb"Content-Disposition:\s*attachment[^;\n]*;?\s*", raw, re.IGNORECASE):
        chunk = raw[m.start() : m.end() + 200]
        fm = _FILENAME_RE.search(chunk.decode("utf-8", errors="replace"))
        if fm:
            name = fm.group(1).strip().strip('"')
            if name and name not in out:
                out.append(name)
    return out[:MAX_ATTACHMENTS]


def _body_preview(raw: bytes, body_start: int) -> str:
    """Textový náhled těla (první BODY_PREVIEW_LEN znaků, bez hlaviček)."""
    lines = raw.split(b"\n")
    parts: list[str] = []
    for line in lines[body_start : body_start + 60]:
        text = _decode_header(line.rstrip(b"\r")).strip()
        if not text or text.startswith(("From ", ">From ")):
            continue
        parts.append(text)
        if sum(len(p) for p in parts) >= BODY_PREVIEW_LEN:
            break
    return " ".join(parts)[:BODY_PREVIEW_LEN]


def parse_email_message(raw: bytes) -> EmailMessage | None:
    """ČISTÝ parser jedné zprávy (RFC822/mbox segment).

    Returns:
        EmailMessage, nebo None pokud hlavičky chybí (poškozený segment).
    """
    headers, body_start = _split_headers(raw)
    if not any(k in headers for k in ("from", "to", "subject", "date")):
        return None

    msg = EmailMessage(
        sender=headers.get("from", ""),
        recipients=[r.strip() for r in headers.get("to", "").split(",") if r.strip()],
        cc=[c.strip() for c in headers.get("cc", "").split(",") if c.strip()],
        subject=headers.get("subject", ""),
        date=_parse_date(headers.get("date", "")),
        message_id=headers.get("message-id", ""),
        attachments=_extract_attachments(raw),
    )
    msg.body_preview = _body_preview(raw, body_start)
    return msg


def split_mbox(data: bytes) -> list[bytes]:
    """Rozdělí mbox na segmenty zpráv (mbox delimiter ``From ``).

    EML bez delimitru → jeden segment. Delimiter musí být na začátku řádku;
    escapované ``>From `` v těle se nepočítá.
    """
    segments: list[bytes] = []
    current: list[bytes] = []
    for line in data.split(b"\n"):
        if line.startswith(_MBOX_DELIM) and current:
            segments.append(b"\n".join(current))
            current = [line]  # From_ řádek patří k nové zprávě (sender + čas)
        else:
            current.append(line)
    if current:
        segments.append(b"\n".join(current))

    out: list[bytes] = []
    for seg in segments[:MAX_MESSAGES_PER_FILE]:
        # segment musí obsahovat aspoň jednu hlavičku — jinak jen From_ řádek
        if any(marker in seg[:2048] for marker in _EML_HEAD_MARKERS):
            out.append(seg)
    return out


def is_email_file(name: str) -> bool:
    """Name-based detekce (AXIOM Hunter pattern) — .eml / .mbox."""
    lower = name.lower()
    return lower.endswith((".eml", ".mbox")) or lower in ("mail", "mailbox")


def build_email_artifacts(messages: list[EmailMessage]) -> list[Artifact]:
    """ČISTÁ funkce: ze zpráv vytvoří artifacty (email_message)."""
    artifacts: list[Artifact] = []
    for msg in messages:
        if not msg.sender and not msg.subject:
            continue
        details: dict[str, Any] = {
            "engine": "mbox",
            "from": msg.sender,
            "to": msg.recipients,
            "subject": msg.subject,
        }
        if msg.cc:
            details["cc"] = msg.cc
        if msg.message_id:
            details["message_id"] = msg.message_id
        if msg.attachments:
            details["attachments"] = msg.attachments
        if msg.body_preview:
            details["body_preview"] = msg.body_preview

        sender_label = msg.sender.split("<")[0].strip() or "(neznámý odesílatel)"
        artifacts.append(
            Artifact(
                artifact_type="email_message",
                timestamp=msg.date,
                title=f"{msg.subject or '(bez předmětu)'} — {sender_label}",
                details=details,
                confidence=0.9 if msg.date else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_email_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — mbox/EML soubor → email_message artifacty.

    Chyby (poškozený soubor, IO) → log + prázdný výsledek, nikdy ne výjimka.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("Email %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    messages: list[EmailMessage] = []
    for seg in split_mbox(data):
        try:
            msg = parse_email_message(seg)
        except Exception as e:  # noqa: BLE001 — jedna poškozená zpráva nepotopí soubor
            logger.warning("Email %s: chyba segmentu (%s)", path, e)
            continue
        if msg is not None:
            messages.append(msg)

    if len(messages) >= MAX_MESSAGES_PER_FILE:
        logger.warning("Email %s: dosáhnut limit %d zpráv", path, MAX_MESSAGES_PER_FILE)

    artifacts = build_email_artifacts(messages)

    # ETAPA B vlna 6 — AttachmentExtractor bonus (AXIOM Common.dll): každá MIME
    # příloha → samostatný email_attachment artifact (nejen jméno v detailu).
    try:
        from stopa.artifacts.attachment_extractor import extract_attachments_from_message

        for seg in split_mbox(data):
            artifacts.extend(extract_attachments_from_message(seg))
    except Exception as e:  # noqa: BLE001 — bonus nesmí potopit hlavní extrakci
        logger.debug("attachment extractor bonus %s: %s", path, e)

    return artifacts
