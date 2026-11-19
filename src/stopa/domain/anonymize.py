"""P2-7 — Anonymizace případů před exportem (čistá doména).

Kanonické entity → stabilní pseudonimy. Mapping klíč→pseudonym se do
exportního bundle **nedostává**: s klíčem je anonymizace reverzibilní
(re-derivace přes :func:`anonymize`), bez klíče jsou pseudonimy
neproniknutelné (HMAC-SHA256 nad doménově odděleným payloadem).

Konstrukce pseudonymu::

    "anon-" + HMAC-SHA256(key, "stopa-anon-v1|{kind}|{value}")[:12 hex]

Vlastnosti (AK P2-7):
- **Determinismus**: stejný klíč + stejná entity = stejný pseudonym v každém
  opakovaném běhu (různá platforma, jiný pořadí vstupů).
- **Různé klíče** = různé pseudonimy s kryptografickou pravděpodobností.
- **Kanonizace**: hodnota se stripuje; pro ``kind == "email"`` i lowercases
  (praxe e-mailových systémů — dokumentovaná zjednodušení RFC).
- **Fail-closed**: prázdný kind/value po kanonizaci, neplatné base64 klíče →
  ``ValueError``; špatný typ klíče → ``TypeError``.

Bez I/O a bez sítě — offline testovatelnost (AK P2-7).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

#: Doménová separace HMAC payloadu — verze konstrukce (změna = nová doména).
KEY_PREFIX = "stopa-anon-v1"

#: Délka pseudonymu v hex znácích (48 bitů — kolizní prostor dostatečný pro case).
PSEUDONYM_HEX_LEN = 12


@dataclass(frozen=True)
class AnonKey:
    """Klíč anonymizace — 32 B náhody jako base64.

    Klíč je jediný prostředek k re-derivaci mappingu; do exportního bundle
    se dostává maximálně jeho :func:`key_fingerprint` (odhalí shodu klíčů,
    ale neklíč samotný).
    """

    secret_b64: str


def new_key() -> AnonKey:
    """Vygeneruje nový náhodný klíč (CSPRNG 32 B → base64)."""
    return AnonKey(secret_b64=base64.b64encode(secrets.token_bytes(32)).decode("ascii"))


def _key_bytes(key: Any) -> bytes:
    """Validace + dekodování klíče (fail-closed)."""
    if not isinstance(key, AnonKey):
        raise TypeError(f"key musí být AnonKey, ne {type(key).__name__}")
    try:
        raw = base64.b64decode(key.secret_b64.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise ValueError(f"AnonKey není platné base64: {exc}") from None
    if not raw:
        raise ValueError("AnonKey je prázdný")
    return raw


def key_fingerprint(key: Any) -> str:
    """Deterministický otisk klíče pro metadata bundle (``fp-xxxxxxxx``).

    Odhalí shodu/různost použitých klíčů, ale neukáže klíč. Neplatný klíč →
    ``ValueError``/``TypeError`` jako u :func:`pseudonym`.
    """
    return "fp-" + hashlib.sha256(_key_bytes(key)).hexdigest()[:8]


def _norm_kind(kind: Any) -> str:
    if not isinstance(kind, str):
        raise TypeError(f"kind musí být str, ne {type(kind).__name__}")
    k = kind.strip().lower()
    if not k:
        raise ValueError("kind je prázdný po kanonizaci")
    return k


def _norm_value(kind: str, value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(f"value musí být str, ne {type(value).__name__}")
    v = value.strip()
    if kind == "email":
        # praxe e-mailových systémů — dokumentovaná zjednodušení RFC 1035/5321
        v = v.lower()
    if not v:
        raise ValueError(f"value je prázdná po kanonizaci (kind={kind!r})")
    return v


def pseudonym(key: Any, kind: str, value: str) -> str:
    """Stabilní pseudonym pro jednu kanonickou entity.

    Stejný klíč + stejná (kind, value) = stejný výsledek vždy a všude;
    druhá entity nebo jiný klíč → (s kryptografickou pravděpodobností)
    jiný pseudonym.
    """
    k = _norm_kind(kind)
    v = _norm_value(k, value)
    digest = hmac.new(
        _key_bytes(key), f"{KEY_PREFIX}|{k}|{v}".encode(), hashlib.sha256
    ).hexdigest()
    return "anon-" + digest[:PSEUDONYM_HEX_LEN]


@dataclass(frozen=True)
class AnonRecord:
    """Veřejná část anonymizace — bezpečná pro exportní bundle.

    Obsahuje ``kind`` (typ entity není sám o sobě PII) a pseudonym;
    originální hodnota se tu NEOBJEVUJE.
    """

    kind: str
    pseudonym: str


@dataclass(frozen=True)
class AnonResult:
    """Výsledek anonymizace — rozdělený na veřejnou a ochrannou část.

    - ``records`` — seřazená deduplikovaná veřejná sada (bez originálů);
      bundle používá POUZE tuto část.
    - ``mapping`` — ochranná část: ``"{kind}|{value}" → pseudonym``; do
      bundle se nedostává, leží u držitele klíče (re-anonymizace).
    """

    records: tuple[AnonRecord, ...] = field(default_factory=tuple)
    mapping: dict[str, str] = field(default_factory=dict)


def anonymize(key: Any, entities: Sequence[tuple[str, str]]) -> AnonResult:
    """Zanonymizuje sadu kanonických entit ``(kind, value)``.

    Duplicitní entity (stejná kind+value v libovolném pořadí) se sloučí na
    jeden záznam; ``records`` je deterministicky seřazeno podle
    ``(kind, pseudonym)`` — stejný vstup = stejný výstup v každém běhu.

    Chybová sémantika: první neplatná entity → ``ValueError``/``TypeError``
    (fail-closed); prázdná sada → prázdné ``AnonResult``.
    """
    pairs: set[tuple[str, str]] = set()
    for item in entities:
        if not isinstance(item, tuple) or len(item) != 2:
            raise TypeError(f"entity musí být dvojice (kind, value), ne {item!r}")
        k = _norm_kind(item[0])
        v = _norm_value(k, item[1])
        pairs.add((k, v))

    records = tuple(
        AnonRecord(kind=k, pseudonym=pseudonym(key, k, v)) for k, v in sorted(pairs)
    )
    # ochranná část — stavíme přímo z párů (záznamy nesou už jen pseudonym)
    mapping = {f"{k}|{v}": pseudonym(key, k, v) for k, v in sorted(pairs)}
    return AnonResult(records=records, mapping=mapping)
