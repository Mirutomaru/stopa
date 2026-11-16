"""K5.1 — DeFi protocol detection (Uniswap / Aave / Curve / Maker / Lido, …).

Offline-first registry bundlovaných smluv + textové indikátory (deterministické):

- ``defi_protocols.json`` — ověřené kontrakty protokolů (verified=true) +
  termínová slovníková pole per protokol.
- Detekce v textu: word-boundary shody termínů (case-insensitive) a známé
  adresy z registru; skóre = 2× unikátní termíny + 5× známá adresa.

Adresové porovnání je case-insensitive (EIP-55 checksum se nevyžaduje).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

_DATA_DIR = Path(__file__).resolve().parent / "data"
_DEFI_PATH = _DATA_DIR / "defi_protocols.json"


class DeFiRegistryError(Exception):
    """Chyba načtení/validace bundlovaného registru DeFi protokolů."""


class DefiProtocolInfo(BaseModel):
    """Položka registru — ověřená smlouva známého DeFi protokolu."""

    address: str
    chain: str = "eth"
    protocol: str
    version: str | None = None
    kind: str | None = None  # amm_factory | router | lending_pool | …
    verified: bool = False
    source: str = ""


class DefiFinding(BaseModel):
    """Detekce DeFi aktivity v jednom textovém dokumentu."""

    protocol: str
    origin: str = ""
    matched_terms: tuple[str, ...] = ()
    matched_addresses: tuple[str, ...] = ()
    score: int = 0


@lru_cache(maxsize=8)
def load_defi_registry(path: Path | None = None) -> (
    tuple[tuple[DefiProtocolInfo, ...], dict[str, tuple[str, ...]]]
):
    """Načte a validuje bundlovaný registr DeFi protokolů.

    Vrací ``(entries, text_terms)`` jako nezměnitelné struktury; ``text_terms``
    mapuje protokol → n-trojice termínů. Chyba souboru/validace → :class:`DeFiRegistryError`.
    """
    p = path or _DEFI_PATH
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeFiRegistryError(f"Registr defi_protocols se nepodařilo načíst: {exc}") from exc

    entries: list[DefiProtocolInfo] = []
    for i, item in enumerate(raw.get("entries", [])):
        try:
            e = DefiProtocolInfo(**item)
        except Exception as exc:  # pydantic ValidationError atd.
            raise DeFiRegistryError(f"defi_protocols, položka {i}: {exc}") from exc
        if not e.address.startswith("0x"):
            raise DeFiRegistryError(
                f"defi_protocols, položka {i}: adresa bez 0x prefixu: {e.address!r}"
            )
        entries.append(e)

    terms: dict[str, tuple[str, ...]] = {}
    for proto in raw.get("text_terms", {}):
        words = [str(w).lower() for w in raw["text_terms"][proto] if str(w).strip()]
        if words:
            terms[proto.lower()] = tuple(words)
    return tuple(entries), terms


def _term_pattern(term: str) -> re.Pattern[str]:
    """Word-boundary regex pro termín (podporuje mezeru a tečky ve slově)."""
    parts = [re.escape(part) for part in term.split(" ")]
    body = r"\s+".join(parts)
    # word boundary na začátku i konci; u slov s číslicemi/tečkami funguje \b
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def detect_defi_in_text(text: str, origin: str = "") -> list[DefiFinding]:
    """Deterministická detekce DeFi indikátorů v textu.

    Pro každý protokol ze slovníku sbírá unikátní shody termínů; známé adresy
    z registru se přiřazují protokolu vlastnímu adrese (case-insensitive).
    Výsledek je seřazený abecedně podle protokolu.
    """
    entries, terms = load_defi_registry()

    hits: dict[str, set[str]] = {proto: set() for proto in terms}
    addrs_by_proto: dict[str, list[str]] = {}
    for e in entries:
        if re.search(rf"(?<!\w){re.escape(e.address.lower())}(?!\w)", text, re.IGNORECASE):
            addrs_by_proto.setdefault(e.protocol, []).append(e.address)

    findings: list[DefiFinding] = []
    for proto in sorted(hits):
        matched_terms: set[str] = set()
        for word in terms[proto]:
            if _term_pattern(word).search(text):
                matched_terms.add(word)
        matched_addrs = tuple(sorted(set(addrs_by_proto.get(proto, []))))
        score = 2 * len(matched_terms) + 5 * len(matched_addrs)
        if score > 0:
            findings.append(
                DefiFinding(
                    protocol=proto,
                    origin=origin,
                    matched_terms=tuple(sorted(matched_terms)),
                    matched_addresses=matched_addrs,
                    score=score,
                )
            )
    return findings


def tag_eth_addresses(addresses: list[str]) -> dict[str, DefiProtocolInfo]:
    """Přiřadí známým adresám (0x…) jejich DeFi protokol z registru.

    Vrací mapping normalizovaná adresa → info; neznámé adresy se nepočítají.
    """
    entries, _ = load_defi_registry()
    out: dict[str, DefiProtocolInfo] = {}
    for addr in addresses:
        a = (addr or "").strip().lower()
        if not a.startswith("0x"):
            continue
        for e in entries:
            if e.address.lower() == a:
                out[a] = e
                break
    return out
