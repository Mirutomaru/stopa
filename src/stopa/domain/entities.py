"""STOPA E4 — Entity extraction a normalizace (Entity + Correlation Engine).

Čistá doménová logika bez IO: kanonické tvary kontaktních hodnot, aby se
"+420 777 123 456", "00420777123456" a "+420777123456" propojily do JEDNÉ entity.

Druhy entit (ROADMAP E4 bod 1):
- ``phone``    → tel:+E164 — jen číslice s vedoucím + (předpona 00 → +)
- ``email``    → lowercase
- ``url_host`` → hostname bez portu, lowercase
- ``hash``     → hex lowercase (32/40/64 znaků = MD5/SHA1/SHA-256)

Extrakce běží nad `Artifact` objekty: typově specifická pole (handle/adresa
zprávy, URL v browser history, hodnota kontaktu + mimetype) + generický sken
volného textu (e-maily, telefony s oddělovači/+00, hex hash). Výsledek je
deterministický — stejný artifact vždy dá stejné entity ve stejném pořadí.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from stopa.models import Artifact

# ── kanonické tvary (normalizace) ────────────────────────────────


def normalize_phone(raw: str) -> str | None:
    """tel:+E164 — jen číslice s vedoucím ``+``.

    Pravidla:
    - oddělovače (mezery, pomlčky, závorky, tečky) se odstraní;
    - předpona ``00`` (mezinárodní volací kód bez +) → ``+``;
    - číslo bez + a bez 00 se doplní o ``+`` (předpoklad: čísla jsou
      uložena v kompletním mezinárodním tvaru — dokumentovaná konvence);
    - méně než 7 číslic → šum (vratí None).

    >>> normalize_phone("+420 777 123 456")
    '+420777123456'
    >>> normalize_phone("00420777123456")
    '+420777123456'
    """
    s = (raw or "").strip()
    if not s or "@" in s:  # e-mail řeší normalize_email
        return None
    digits = re.sub(r"\D", "", s)
    if len(digits) < 7:
        return None
    if not s.startswith("+") and digits.startswith("00"):
        digits = digits[2:]
    return "+" + digits


def normalize_email(raw: str) -> str | None:
    """E-mail lowercase (RFC-ish validace — bez whitespace, s TLD)."""
    s = (raw or "").strip().lower()
    if re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", s):
        return s
    return None


def normalize_url_host(raw: str) -> str | None:
    """Hostname bez portu a bez cesty, lowercase (schéma volitelné).

    >>> normalize_url_host("https://Example.COM/path?q=1")
    'example.com'
    >>> normalize_url_host("www.example.com:8443/x")
    'www.example.com'
    """
    s = (raw or "").strip()
    if not s:
        return None
    if "://" in s:
        host = urlparse(s).hostname or ""
    else:
        # bez schématu — vezmi první segment cesty a odřízně port
        host = s.split("/", 1)[0].split("?", 1)[0]
        if ":" in host:
            host = host.split(":", 1)[0]
    host = host.lower().strip(".")
    if re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host):
        return host
    return None


def normalize_hash(raw: str) -> str | None:
    """Hex hash lowercase (32 = MD5, 40 = SHA1, 64 = SHA-256).

    Snese prefixy typu ``sha256:<hex>`` / ``md5=<hex>``.
    """
    s = (raw or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]+", s):
        # zkus odříznout "prefix:" nebo "prefix=" před hex částí
        m = re.match(r"^[a-z0-9_]*[=:]\s*([0-9a-f]{32,64})$", s)
        if not m:
            return None
        s = m.group(1)
    if len(s) in (32, 40, 64):
        return s
    return None


def classify_value(raw: str) -> Entity | None:
    """Heuristická klasifikace volné hodnoty (e-mail má přednost před telefonem)."""
    e = normalize_email(raw)
    if e is not None:
        return Entity("email", e, raw.strip())
    p = normalize_phone(raw)
    if p is not None:
        return Entity("phone", p, raw.strip())
    return None


# ── entity + výskyty ─────────────────────────────────────────────


@dataclass(frozen=True)
class Entity:
    """Kanonická entita — ``value`` je klíč pro propojování (matching)."""

    kind: str  # phone | email | url_host | hash
    value: str  # normalizovaný kanonický tvar
    raw_value: str = ""  # původní tvar, jak se objevil v artifactu


@dataclass(frozen=True)
class EntityOccurrence:
    """Výskyt entity v konkrétním artifactu (podklad pro korelační pravidla)."""

    kind: str
    value: str  # normalizovaný tvar
    source_id: str | None
    artifact_id: str
    rel_path: str | None = None
    ts_utc: datetime | None = None
    raw_value: str = ""  # původní tvar (pro entities.raw_value)


# ── extrakce z artifactů ─────────────────────────────────────────

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_HASH_RE = re.compile(r"\b[0-9a-fA-F]{32}\b|\b[0-9a-fA-F]{40}\b|\b[0-9a-fA-F]{64}\b")
# kandidátský telefon: číslice + oddělovače, minimálně 7 číslic uvnitř
_PHONE_TOKEN_RE = re.compile(r"[\d+][\d+().\- ]{5,24}")

# artifact typy s kontaktní hodnotou v `details` (handle/adresa zprávy)
_MESSAGE_TYPES = ("imessage", "sms_message", "whatsapp_message")


def _scan_phones(text: str) -> list[str]:
    """Telefony ve volném textu — konzervativně, aby se neschytly data/ID.

    Akceptuje tokeny s oddělovači (mezery/pomlčky/závorky) nebo mezinárodní
    předponou (+ / 00). Čisté řetězce číslic bez oddělovačů (např. datum
    20261101) se ignorují — v kontaktních polích je normalizace přísnější.
    """
    out: list[str] = []
    for m in _PHONE_TOKEN_RE.finditer(text):
        tok = m.group()
        digits = re.sub(r"\D", "", tok)
        if len(digits) < 7:
            continue
        has_sep = any(c.isspace() or c in "()+-." for c in tok)
        starts_intl = tok.lstrip().startswith(("+", "00"))
        if not (has_sep or starts_intl):
            continue
        n = normalize_phone(tok)
        if n is not None:
            out.append(n)
    return out


def extract_entities(artifact: Artifact) -> list[Entity]:
    """Extrahuje entity z jednoho artifactu (deterministické pořadí).

    Typově specifická pole mají přednost; generický sken doplní e-maily,
    telefony a hash ze volného textu (title + stringové hodnoty details).
    Duplikáty (kind, value) se odstraňují — první výskyt vyhrává.
    """
    out: list[Entity] = []
    seen: set[tuple[str, str]] = set()

    def add(e: Entity | None) -> None:
        if e is not None and (e.kind, e.value) not in seen:
            seen.add((e.kind, e.value))
            out.append(e)

    details = artifact.details or {}
    title = (artifact.title or "").strip()
    t = artifact.artifact_type

    # ── typově specifická extrakce ───────────────────────────────
    if t == "contact":
        value = title
        mime = str(details.get("mimetype") or "")
        if value:
            if "phone" in mime:
                n = normalize_phone(value)
                add(Entity("phone", n, value) if n else None)
            elif "email" in mime:
                n = normalize_email(value)
                add(Entity("email", n, value) if n else None)
            else:
                # iOS AddressBook / neznámý mimetype — heuristika podle obsahu
                add(classify_value(value))
    elif t in _MESSAGE_TYPES:
        for key in ("handle", "address"):
            v = details.get(key)
            if isinstance(v, str) and v.strip():
                add(classify_value(v))
    elif t == "browser_history":
        n = normalize_url_host(title)
        add(Entity("url_host", n, title) if n else None)

    # ── generický sken volného textu ──────────────────────────────
    texts: list[str] = []
    if t not in ("contact", "browser_history"):
        texts.append(artifact.title or "")  # obsah zprávy může obsahovat kontakty
    for v in details.values():
        if isinstance(v, str):
            texts.append(v)

    for text in texts:
        for m in _EMAIL_RE.finditer(text):
            n = normalize_email(m.group())
            add(Entity("email", n, m.group()) if n else None)
        for n in _scan_phones(text):
            add(Entity("phone", n, ""))
        for m in _HASH_RE.finditer(text):
            n = normalize_hash(m.group())
            add(Entity("hash", n, m.group()) if n else None)

    return out


def collect_occurrences(artifacts: list[Artifact]) -> list[EntityOccurrence]:
    """Všechny výskyty entit napříč artifacty (podklad pro korelační pravidla)."""
    out: list[EntityOccurrence] = []
    for a in artifacts:
        for e in extract_entities(a):
            out.append(
                EntityOccurrence(
                    kind=e.kind,
                    value=e.value,
                    source_id=a.source_id,
                    artifact_id=a.id,
                    rel_path=a.rel_path,
                    ts_utc=a.timestamp,
                    raw_value=e.raw_value,
                )
            )
    return out
