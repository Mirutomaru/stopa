"""K5.3 — Cross-chain bridge analysis (Wormhole / Binance Bridge / …).

Offline-first:

- ``bridges.json`` — ověřené bridgové kontrakty per chain + textové indikátory.
- ``analyze_cross_chain()`` — heuristika nad daty z více řetězců (K3 TxCache):
  adresa/cluster přítomný na ≥ 2 řetězcích bez přímého transferu = indikace bridge;
  shoda adresy s bridgovou smlouvou dané chainy = explicitní důkaz.

Deterministické: výstup seřazený, žádná náhoda, síť jen přes injektovaný vstup.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel


class BridgeRegistryError(Exception):
    """Chyba načtení/validace bundlovaného registru bridge."""


_DATA_DIR = Path(__file__).resolve().parent / "data"
_BRIDGES_PATH = _DATA_DIR / "bridges.json"


class BridgeInfo(BaseModel):
    """Položka registru — známý cross-chain bridge (kontrakty per chain)."""

    name: str
    chains: tuple[str, ...] = ()
    contracts: dict[str, str] = {}  # chain → adresa smlouvy
    verified: bool = False
    source: str = ""


class BridgeLink(BaseModel):
    """Detekovaný cross-chain propojení entity."""

    entity: str  # adresa (nebo cluster id)
    chains: tuple[str, ...] = ()
    evidence: str = "multi_chain_presence"  # multi_chain_presence | bridge_contract
    bridge_name: str | None = None


class BridgeFinding(BaseModel):
    """Detekce bridge indikátorů v jednom textovém dokumentu."""

    origin: str = ""
    bridges: tuple[str, ...] = ()
    score: int = 0


@lru_cache(maxsize=8)
def load_bridge_registry(path: Path | None = None) -> (
    tuple[tuple[BridgeInfo, ...], tuple[str, ...]]
):
    """Načte a validuje bundlovaný registr cross-chain bridge.

    Vrací ``(entries, text_terms)`` jako nezměnitelné struktury.
    """
    p = path or _BRIDGES_PATH
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeRegistryError(f"Registr bridges se nepodařilo načíst: {exc}") from exc

    entries: list[BridgeInfo] = []
    for i, item in enumerate(raw.get("entries", [])):
        try:
            e = BridgeInfo(
                name=str(item["name"]),
                chains=tuple(str(c).lower() for c in item.get("chains", ())),
                contracts={
                    str(k).lower(): str(v) for k, v in item.get("contracts", {}).items()
                },
                verified=bool(item.get("verified", False)),
                source=str(item.get("source", "")),
            )
        except Exception as exc:  # KeyError / pydantic atd.
            raise BridgeRegistryError(f"bridges, položka {i}: {exc}") from exc
        entries.append(e)

    terms = tuple(str(t).lower() for t in raw.get("text_terms", ()))
    return tuple(entries), terms


def analyze_cross_chain(
    per_chain: dict[str, list[str]], registry: tuple[BridgeInfo, ...] | None = None
) -> list[BridgeLink]:
    """Heuristická cross-chain analýza.

    ``per_chain`` mapuje chain (lowercase id dle K3 TxCache: btc/eth/bsc/polygon…)
    na adresy aktivní v daném řetězci. Dva typy důkazů:

    1. ``bridge_contract`` — adresa se rovná bridgové smlouvě dané chainy (explicitní).
    2. ``multi_chain_presence`` — stejná adresa (normalizace: lowercase pro 0x) je
       aktivní na ≥ 2 řetězcích bez přímého cross-chain transferu v datech.

    Výsledek seřazený podle entity; důkazy se slučují (bridge_contract má přednost).
    """
    if registry is None:
        registry, _ = load_bridge_registry()

    # adresa → set(chain) — normalizace: 0x adresy lowercase, ostatní literálně
    presence: dict[str, set[str]] = {}
    for chain, addrs in per_chain.items():
        c = str(chain).lower()
        for addr in addrs:
            a = (addr or "").strip()
            if not a:
                continue
            key = a.lower() if a.lower().startswith("0x") else a
            presence.setdefault(key, set()).add(c)

    links: dict[str, BridgeLink] = {}
    for entity in sorted(presence):
        chains = tuple(sorted(presence[entity]))
        if len(chains) >= 2:
            # explicitní bridge smlouva? (adresa == kontrakt bridge na některé chaině)
            bridge_name: str | None = None
            for b in registry:
                for c in chains:
                    known = {v.lower() for v in b.contracts.values()}
                    if entity.lower() in known and c in set(b.chains):
                        bridge_name = b.name
                        break
                if bridge_name:
                    break
            links[entity] = BridgeLink(
                entity=entity,
                chains=chains,
                evidence="bridge_contract" if bridge_name else "multi_chain_presence",
                bridge_name=bridge_name,
            )

    # adresa je bridgová smlouva i při přítomnosti na jedné chaině (explicitní důkaz)
    for b in registry:
        for c, addr in sorted(b.contracts.items()):
            key = addr.lower()
            if key not in presence or c not in presence[key]:
                continue
            existing = links.get(key)
            if existing is None:
                links[key] = BridgeLink(
                    entity=key,
                    chains=tuple(sorted(presence[key])),
                    evidence="bridge_contract",
                    bridge_name=b.name,
                )
    return [links[k] for k in sorted(links)]


def detect_bridge_in_text(text: str, origin: str = "") -> BridgeFinding | None:
    """Deterministická detekce bridge indikátorů v textu.

    Skóre = 2× unikátní termín (word-boundary, case-insensitive).
    Vrací None při score == 0. Výstup seřazený.
    """
    _, terms = load_bridge_registry()
    found: list[str] = []
    for t in sorted(terms):
        parts = [re.escape(part) for part in t.split(" ")]
        body = r"\s+".join(parts)
        if re.search(rf"(?<!\w){body}(?!\w)", text, re.IGNORECASE):
            found.append(t)
    if not found:
        return None
    return BridgeFinding(origin=origin, bridges=tuple(found), score=2 * len(found))
