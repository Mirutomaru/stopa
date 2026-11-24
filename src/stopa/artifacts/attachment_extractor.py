"""ETAPA B vlna 6 — Attachment extractor (MIME / RFC822 přílohy).

AXIOM ekvivalent: ``AttachmentExtractor``
(``Magnet.Artifacts.Common.FileFormats.Xml.AttachmentExtractor``) — generic
extraktor příloh ze souborových formátů; STOPA portuje MIME/RFC822 variantu,
která je v praxi dominantní (emaily).

Podporovaný formát: **MIME / RFC822** zpráva (EML i segment mbox) — prochází
se všechny části (``walk()``); příloha = část s ``Content-Disposition:
attachment`` NEBO s názvem souboru (``filename=``). Pro každou přílohu se
vytvoří samostatný artifact, takže je nezávisle dohledatelná v timeline a
FTS (nezapadá jen pod rodičovský ``email_message``).

Sloupce / metadata přílohy:
- ``filename`` — název souboru (RFC2231 dekodování přes stdlib email)
- ``content_type`` — MIME typ části
- ``size_bytes`` — velikost dekódovaného payloadu (Content-Length fallback)
- ``disposition`` — attachment / inline

Artifact type: ``email_attachment`` — jedna příloha = jeden artifact.
Časová značka dědí datum rodičovské zprávy (přílohy nemají vlastní čas).

Čistá logika bez IO (offline testovatelná); I/O jen v entrypointu.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_ATTACHMENTS_PER_MESSAGE = 50  # obrana proti patologické zprávě


@dataclass
class AttachmentInfo:
    """Metadata jedné MIME přílohy (čistá data, bez IO)."""

    filename: str
    content_type: str = ""
    size_bytes: int | None = None
    disposition: str = "attachment"
    message_id: str = field(default="")


def _part_size(part: Any) -> int | None:
    """Velikost dekódovaného payloadu části; chybí / chyba → None.

    Preferuje Content-Length hlavičku (bez čtení těla); fallback na délku
    dekódovaného payloadu (celá zpráva je už v paměti, takže bez nového peaku).
    """
    cl = part.get("Content-Length")
    if cl:
        try:
            return max(0, int(cl))
        except (ValueError, TypeError):
            logger.debug("Content-Length %r nepárabilní → fallback na další heuristiku", cl)
    try:
        payload = part.get_payload(decode=True)
        if isinstance(payload, (bytes, bytearray)):
            return len(payload)
    except Exception as e:  # noqa: BLE001 — poškozený encoding nepotopí extrakci
        logger.debug("attachment payload size error: %s", e)
    return None


def parse_attachments(raw: bytes) -> tuple[datetime | None, list[AttachmentInfo]]:
    """ČISTÁ funkce (bez IO): z raw MIME zprávy vyčte datum + přílohy.

    Vrací ``(message_date, attachments)``. Celá funkce je obalená try/except —
    poškozená zpráva → ``(None, [])``, nikdy ne výjimka (defenzivní bonus).
    """
    if not raw:
        return None, []
    try:
        from email import policy
        from email.parser import BytesParser

        msg = BytesParser(policy=policy.default).parsebytes(raw)
    except Exception as e:  # noqa: BLE001 — stdlib email padne na patologických hlavičkách
        logger.debug("attachment MIME parse error: %s", e)
        return None, []

    # datum rodičovské zprávy (přílohy ho dědí)
    message_date: datetime | None = None
    date_raw = msg.get("Date")
    if date_raw:
        try:
            from email.utils import parsedate_to_datetime

            dt = parsedate_to_datetime(date_raw.strip())
            if dt is not None and 1980 <= dt.year <= 2200:
                message_date = dt
        except Exception as e:  # noqa: BLE001 — poškozené datum je běžné
            logger.debug("attachment date parse error: %s", e)

    message_id = (msg.get("Message-ID") or "").strip()

    out: list[AttachmentInfo] = []
    try:
        parts = list(msg.walk())
    except Exception as e:  # noqa: BLE001 — walk padne na cyklických strukturách
        logger.debug("attachment walk error: %s", e)
        return message_date, out

    for part in parts:
        try:
            if part.is_multipart():
                continue  # kontejner, ne listinná příloha
            disposition = (part.get("Content-Disposition") or "").lower()
            filename = part.get_filename()
            is_attachment = "attachment" in disposition or bool(filename)
            if not is_attachment:
                continue
            out.append(
                AttachmentInfo(
                    filename=(filename or "(bez názvu)").strip(),
                    content_type=part.get_content_type() or "",
                    size_bytes=_part_size(part),
                    disposition="attachment" if "attachment" in disposition else "inline",
                    message_id=message_id,
                )
            )
        except Exception as e:  # noqa: BLE001 — jedna poškozená část nepotopí zbytek
            logger.debug("attachment part error: %s", e)
            continue
    return message_date, out[:MAX_ATTACHMENTS_PER_MESSAGE]


def build_attachment_artifacts(
    attachments: list[AttachmentInfo],
    message_date: datetime | None = None,
) -> list[Artifact]:
    """ČISTÁ funkce: z příloh vytvoří email_attachment artifacty.

    Každá příloha = jeden artifact s děděným časem rodičovské zprávy.
    """
    out: list[Artifact] = []
    for att in attachments:
        details: dict[str, Any] = {
            "engine": "mime",
            "filename": att.filename,
            "content_type": att.content_type,
            "disposition": att.disposition,
        }
        if att.size_bytes is not None:
            details["size_bytes"] = att.size_bytes
        if att.message_id:
            details["message_id"] = att.message_id

        out.append(
            Artifact(
                artifact_type="email_attachment",
                timestamp=message_date,
                title=att.filename[:500],
                details=details,
                confidence=0.8 if message_date else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return out


def extract_attachments_from_message(raw: bytes) -> list[Artifact]:
    """Pipeline entrypoint (bonus): z jedné MIME zprávy → email_attachment artifacty.

    Volá se uvnitř ``email_mbox.extract_email_artifacts`` pro každý segment.
    Chyby → prázdný výsledek, nikdy ne výjimka.
    """
    message_date, attachments = parse_attachments(raw)
    if not attachments:
        return []
    return build_attachment_artifacts(attachments, message_date)
