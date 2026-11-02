"""STOPA P0 Intelligence I3 — Entity Resolution 2.0 (čistá doménová logika).

Rozšíření E4 Entity + Correlation Engine podle STOPA_TARGET_ARCHITECTURE §3.2:

1. **Čtyři úrovně confidence vztahů** (místo verified/inferred):
   - ``confirmed``          — deterministicky ověřeno (stejná hodnota napříč
     důkazy / identický hash)
   - ``strong_candidate``   — silná indikace, chybí jeden krok potvrzení
   - ``possible``           — analytickká hypotéza (např. časový překryv)
   - ``unverified``         — neověřená / ručně zadaná vazba

   Staré hodnoty se mapují při migraci DB: verified→confirmed, inferred→possible.

2. **Nový druh entity ``user_account``** — platformní identifikátory, které
   nejsou čistým telefonem/e-mailem (WhatsApp JID ``+420…@c.us``, Skype/Telegram
   handle). Normalizace: WhatsApp JID → ``wa:+E164`` (telefon se normalizuje,
   doména @c.us se odřízne), ostatní hodnoty lowercase.

3. **Detekce duplicitních entit** (merge candidates) — heuristické páry, které
   pravděpodobně označují totéž reálné kontakty v různých kanonických tvarech:
   - telefony se stejným národním číslem (posledních 7 číslic),
   - e-maily se stejným local-partem na různých doménách.

4. **Časové rozmezí vztahů** — každé propojení nese first_seen/last_seen
   (z timestampů podkladových výskytů) → časově závislé vztahy.

Vše je deterministické a bez IO — vstupem jsou entity/výskyty, výstupem struktury.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

# ── 1) čtyři úrovně confidence vztahů ───────────────────────────

CONFIDENCE_LEVELS = ("confirmed", "strong_candidate", "possible", "unverified")

#: Staré hodnoty (schéma ≤ v10) → nové (spec TARGET_ARCHITECTURE §3.2).
LEGACY_CONFIDENCE_MAP = {"verified": "confirmed", "inferred": "possible"}


def map_legacy_confidence(value: str | None) -> str:
    """Mapuje confidence hodnotu na aktuální škálu (idempotentní).

    Nové hodnoty projdou beze změny; staré verified/inferred se přemapují.
    Neznámá hodnota → ``unverified`` (nejkonzervativnější úroveň).

    >>> map_legacy_confidence("verified")
    'confirmed'
    >>> map_legacy_confidence("inferred")
    'possible'
    >>> map_legacy_confidence("strong_candidate")
    'strong_candidate'
    """
    if value in CONFIDENCE_LEVELS:
        return value
    mapped = LEGACY_CONFIDENCE_MAP.get(value or "")
    if mapped is not None:
        return mapped
    return "unverified"


# ── 2) normalizace platformních účtů (kind=user_account) ───────

#: WhatsApp JID — telefonní číslo (s oddělovači, volně i v závorkách) + doména @c.us.
_WA_JID_RE = re.compile(r"^\(?[\d\s().+\-]{7,24}\)?@c\.us$", re.IGNORECASE)

#: platformní handle se schématem (skype:…, telegram:…) — ne čistý telefon/e-mail
_SCHEME_HANDLE_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def is_whatsapp_jid(raw: str | None) -> bool:
    """Je hodnota WhatsApp JID (telefon + doména @c.us)?

    >>> is_whatsapp_jid("+420 777 123 456@c.us")
    True
    >>> is_whatsapp_jid("jan.novak@gmail.com")
    False
    """
    return bool(_WA_JID_RE.match((raw or "").strip()))


def is_platform_account(raw: str | None) -> bool:
    """Je hodnota platformním účtem (ne čistým telefonem/e-mailem)?

    WhatsApp JID nebo handle se schématovým prefixem (``skype:``, ``telegram:``).
    Čistá telefonní čísla a e-maily vracejí False — ty řeší normalize_phone/
    normalize_email.
    """
    s = (raw or "").strip()
    return is_whatsapp_jid(s) or bool(_SCHEME_HANDLE_RE.match(s))


def normalize_user_account(raw: str | None) -> str | None:
    """Kanonický tvar platformního účtu (kind=user_account).

    Pravidla:
    - WhatsApp JID ``+420 777 123 456@c.us`` → ``wa:+E164`` — telefon se
      normalizuje přes :func:`stopa.domain.entities.normalize_phone`, doména
      @c.us se odřízne (stejný účet = stejná entita bez ohledu na tvar);
    - ostatní hodnoty: lowercase + trim; méně než 2 znaky → šum (None).

    >>> normalize_user_account("+420 777 123 456@c.us")
    'wa:+420****3456'
    >>> normalize_user_account("00420777123456@c.US")
    'wa:+420****3456'
    >>> normalize_user_account("Skype:Jan.Novak")
    'skype:jan.novak'
    """
    from stopa.domain.entities import normalize_phone  # lazy — bez cyklu

    s = (raw or "").strip()
    if not s:
        return None
    m = _WA_JID_RE.match(s)
    if m:
        phone_part = s.split("@", 1)[0]  # odříznout doménu @c.us
        n = normalize_phone(phone_part)
        return f"wa:{n}" if n else None
    low = s.lower()
    if len(low) < 2:
        return None
    return low


# ── 3) detekce duplicitních entit (merge candidates) ───────────

#: minimální délka národního čísla pro párování telefonů (posledních N číslic)
_PHONE_SUFFIX_LEN = 7


@dataclass(frozen=True)
class MergeCandidate:
    """Pár entit, které pravděpodobně označují totéž reálné kontakty.

    ``reason`` je lidsky čitelné vysvětlení (dohledatelnost heuristiky);
    páry jsou deterministicky seřazené podle (value_a, value_b).
    """

    kind: str  # phone | email — druh, ve kterém byla duplicita detekována
    value_a: str
    value_b: str
    reason: str


def _phone_suffix(value: str) -> str:
    """Národní číslo = posledních ``_PHONE_SUFFIX_LEN`` číslic (bez +)."""
    digits = re.sub(r"\D", "", value)
    return digits[-_PHONE_SUFFIX_LEN:] if len(digits) >= _PHONE_SUFFIX_LEN else ""


def find_merge_candidates(entities: Iterable[Mapping[str, object]]) -> list[MergeCandidate]:
    """Heuristická detekce duplicitních entit (čistá funkce, deterministická).

    ``entities`` = řádky ve formátu :meth:`CaseDB.list_entities`
    (dict s klíči ``kind``/``value``). Heuristiky:

    - **phone** — stejný národní číslo (posledních 7 číslic) u dvou různých
      kanonických hodnot → např. +420777123456 a +4207771234567 (chybějící
      koncovka / jiná předvolba).
    - **email** — stejný local-part na dvou různých doménách → např.
      jan.novak@gmail.com a jan.novak@outlook.com.

    Výsledek je seřazený podle (kind, value_a, value_b) — nezávislý na pořadí
    vstupních řádků.
    """
    phones: dict[str, list[str]] = {}
    emails: dict[str, list[str]] = {}
    for row in entities:
        kind = str(row.get("kind") or "")
        value = str(row.get("value") or "")
        if not value:
            continue
        if kind == "phone":
            suffix = _phone_suffix(value)
            if suffix:
                phones.setdefault(suffix, []).append(value)
        elif kind == "email" and "@" in value:
            local = value.split("@", 1)[0]
            if local:
                emails.setdefault(local, []).append(value)

    out: list[MergeCandidate] = []
    for suffix, values in phones.items():
        uniq = sorted(set(values))
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                out.append(
                    MergeCandidate(
                        kind="phone",
                        value_a=uniq[i],
                        value_b=uniq[j],
                        reason=f"stejné národní číslo (posledních {_PHONE_SUFFIX_LEN} číslic: …{suffix})",
                    )
                )
    for local, values in emails.items():
        uniq = sorted(set(values))
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                out.append(
                    MergeCandidate(
                        kind="email",
                        value_a=uniq[i],
                        value_b=uniq[j],
                        reason=f"stejný local-part e-mailu ({local!r}) na různých doménách",
                    )
                )
    return sorted(out, key=lambda m: (m.kind, m.value_a, m.value_b))
