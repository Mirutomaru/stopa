"""STP-019 — PII redaktor pro LLM prompty (deterministický, bez I/O).

Maskuje osobní data PŘED odesláním do lokálního LLM, aby surová PII
(telefonní čísla, e-maily, platformní účty) neopustila pracovní stanici:

- **telefony** → ``+420****3456`` (drží se předpona + poslední 4 číslice);
- **e-maily** → ``j***@example.com`` (maskuje local part, drží doménu);
- **WhatsApp JID** → ``wa:+420****3456`` (kanonický tvar platformního účtu);
- **platformní handle** (``skype:``, ``telegram:``…) → schéma + maskovaný handle.

Stavební kameny (regexy, normalizace) se opakují z :mod:`stopa.domain.entities`
a :mod:`stopa.domain.entity_resolution` — žádná nová heuristika. Výsledek je
deterministický: stejný vstup → stejný redigovaný text + stejný seznam detekcí
(pro audit do ``analysis_operations``).

Clean Architecture: čistá domain logika bez I/O; napojují se na ni prompt
buildery (I1 orchestrace, E11 asistent) přes parametr ``redact_pii``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from stopa.domain.entities import _PHONE_TOKEN_RE, normalize_email, normalize_phone
from stopa.domain.entity_resolution import is_whatsapp_jid

#: WhatsApp JID ve volném textu (neanchored varianta — inline hledání).
_JID_INLINE_RE = re.compile(r"\(?[+\d][\d\s().\-]{6,23}\)?@c\.us", re.IGNORECASE)

#: e-mail ve volném textu (opakován z entities — unanchored regex).
_EMAIL_INLINE_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

#: platformní handle se schématem (jen známé IM schémata — bez http:/mailto:…).
_HANDLE_INLINE_RE = re.compile(
    r"\b(?:skype|telegram|viber|signal|icq|msn):[^\s\"'<>]+", re.IGNORECASE
)

#: priorita typů při překryvu (nižší číslo vyhrává — JID obsahuje telefon).
_PRIORITY = {"jid": 0, "email": 1, "handle": 2, "phone": 3}


@dataclass(frozen=True)
class PiiDetection:
    """Jeden detekovaný a zmaskovaný výskyt PII (podklad pro audit)."""

    kind: str  # phone | email | jid | handle
    raw: str  # původní text, jak se objevil v promptu
    masked: str  # maskovaný tvar, který LLM uvidí


def mask_phone(value: str) -> str:
    """Maskuje E164 telefon: drží první 4 znaky + poslední 4 číslice.

    >>> mask_phone("+420777123456")
    '+420****3456'
    """
    return value[:4] + "****" + value[-4:]


def mask_email(value: str) -> str:
    """Maskuje local part e-mailu (drží první znak + doménu).

    >>> mask_email("jan.novak@example.com")
    'j***@example.com'
    """
    local, _, domain = value.partition("@")
    return f"{local[:1]}***@{domain}"


def _mask_handle(value: str) -> str:
    """Maskuje platformní handle (drží schéma + první znak handle)."""
    scheme, _, handle = value.partition(":")
    masked = handle[:1] + "***" if len(handle) > 3 else "***"
    return f"{scheme}:{masked}"


def _mask_jid(raw: str) -> str | None:
    """WhatsApp JID → kanonický maskovaný tvar ``wa:+E164-mask``."""
    phone_part = raw.split("@", 1)[0]
    n = normalize_phone(phone_part)
    return f"wa:{mask_phone(n)}" if n else None


def _find_matches(text: str) -> list[tuple[int, int, str, str]]:
    """Všechny PII kandidáty se spany (start, end, kind, raw)."""
    out: list[tuple[int, int, str, str]] = []

    for m in _JID_INLINE_RE.finditer(text):
        tok = m.group()
        if is_whatsapp_jid(tok):  # validace přes existující anchored regex
            out.append((m.start(), m.end(), "jid", tok))

    for m in _EMAIL_INLINE_RE.finditer(text):
        if normalize_email(m.group()) is not None:
            out.append((m.start(), m.end(), "email", m.group()))

    for m in _HANDLE_INLINE_RE.finditer(text):
        out.append((m.start(), m.end(), "handle", m.group()))

    # telefony — stejné konzervativní pravidla jako entities._scan_phones;
    # koncové oddělovače (mezery/tečky/pomlčky) se z spanu oříznou, aby se
    # při nahrazení nepolykal text za číslem
    for m in _PHONE_TOKEN_RE.finditer(text):
        end = m.end()
        while end > m.start() and text[end - 1] in " .-":
            end -= 1
        tok = text[m.start():end]
        digits = re.sub(r"\D", "", tok)
        if len(digits) < 7:
            continue
        has_sep = any(c.isspace() or c in "()+-." for c in tok)
        starts_intl = tok.lstrip().startswith(("+", "00"))
        if not (has_sep or starts_intl):
            continue
        if normalize_phone(tok) is None:
            continue
        out.append((m.start(), end, "phone", tok))

    return out


def redact_text(text: str) -> tuple[str, list[PiiDetection]]:
    """Zmaskuje PII ve volném textu.

    Vrací ``(redigovaný_text, detekce)`` — detekce v pořadí výskytu (pro audit).
    Překrývající kandidáty řeší priorita: JID > e-mail > handle > telefon
    (JID obsahuje telefonní číslo — bez priority by se maskovalo dvakrát).

    >>> redact_text("Zavolejte +420 777 123 456 nebo jan.novak@example.com")
    ('Zavolejte +420****3456 nebo j***@example.com', [...])
    """
    matches = _find_matches(text)
    # seřadit podle pozice, pak priority; greedy výběr bez překryvů
    matches.sort(key=lambda t: (t[0], _PRIORITY[t[2]], -t[1]))
    kept: list[tuple[int, int, str, str]] = []
    last_end = -1
    for start, end, kind, raw in matches:
        if start >= last_end:
            kept.append((start, end, kind, raw))
            last_end = end

    dets: list[PiiDetection] = []
    out = text
    # nahrazovat od konce — spany zůstávají platné
    for start, end, kind, raw in reversed(kept):
        if kind == "jid":
            masked = _mask_jid(raw) or raw
        elif kind == "email":
            masked = mask_email(raw.lower())
        elif kind == "handle":
            masked = _mask_handle(raw)
        else:  # phone
            n = normalize_phone(raw)
            masked = mask_phone(n) if n else raw
        dets.append(PiiDetection(kind=kind, raw=raw, masked=masked))
        out = out[:start] + masked + out[end:]

    dets.reverse()  # pořadí výskytu v textu
    return out, dets


def redact_messages(
    messages: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[PiiDetection]]:
    """Zmaskuje PII ve všech prompt messages (role+content).

    Deterministický — stejný vstup → stejný výstup; detekce se spojí v pořadí.
    """
    out_msgs: list[dict[str, str]] = []
    dets: list[PiiDetection] = []
    for m in messages:
        content = str(m.get("content", ""))
        redacted, found = redact_text(content)
        out_msgs.append({"role": m.get("role", ""), "content": redacted})
        dets.extend(found)
    return out_msgs, dets
