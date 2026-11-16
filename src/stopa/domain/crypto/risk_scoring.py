"""K3.4 — Risk scoring na bázi veřejných blacklists (OFAC, EU sankce).

Bundlovaná data v ``data/sanctions_ofac.json`` a ``data/sanctions_eu.json``
(snapshot ověřený proti primárním zdrojům — viz metadatabox 'source' u
každé položky). Lazy load + module-level cache, pattern jako BIP39 wordlist.

Deterministické skórování (AK: *bez sítě*, stejný vstup → stejný výsledek):

============================  ======================
podmínka                      score / level
============================  ======================
žádná shoda                   0 / none
shoda, tag exchange/individual 95 / high
shoda, tag mixer/darknet_market 100 / critical
více shod                     max + doplněné důvody
============================  ======================

Normalizace: ETH/BSC hex adresy (``0x…``) lowercase — EIP-55 je jen
checksum, ne identita; base58/bech32 se porovnávají literálně.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from stopa.domain.crypto.onchain_models import RiskScore, SanctionEntry

_DATA_DIR = Path(__file__).resolve().parent / "data"
_OFAC_PATH = _DATA_DIR / "sanctions_ofac.json"
_EU_PATH = _DATA_DIR / "sanctions_eu.json"

#: Tags, které zvednou skóre na critical (aktivní míchačky / darknet markety).
_CRITICAL_TAGS = {"mixer", "darknet_market"}


class SanctionListError(ValueError):
    """Chybný formát bundlovaného seznamu."""


def _normalize(address: str) -> str:
    a = address.strip()
    return a.lower() if a.lower().startswith("0x") else a


@lru_cache(maxsize=8)
def load_sanction_lists(
    ofac_path: Path | None = None,
    eu_path: Path | None = None,
) -> tuple[tuple[SanctionEntry, ...], tuple[SanctionEntry, ...]]:
    """Načte a validuje bundlované seznamy (OFAC + EU). Vrací nezměnitelné n-troje."""

    def _load(path: Path, name: str) -> tuple[SanctionEntry, ...]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SanctionListError(f"Seznam {name} se nepodařilo načíst: {exc}") from exc
        entries = []
        for i, item in enumerate(raw.get("entries", [])):
            try:
                e = SanctionEntry(**item)
            except Exception as exc:  # pydantic ValidationError atd.
                raise SanctionListError(f"Seznam {name}, položka {i}: {exc}") from exc
            if not e.address:
                raise SanctionListError(f"Seznam {name}, položka {i}: prázdná adresa")
            entries.append(e)
        return tuple(entries)

    ofac = _load(ofac_path or _OFAC_PATH, "ofac_sdn")
    eu = _load(eu_path or _EU_PATH, "eu_sanctions")
    return ofac, eu


def score_address(
    address: str,
    lists: tuple[tuple[SanctionEntry, ...], tuple[SanctionEntry, ...]] | None = None,
) -> RiskScore:
    """Deterministické risk skóre jedné adresy (0–100).

    ``lists`` lze injektovat pro testy; default = bundlované OFAC + EU.
    """
    if lists is None:
        lists = load_sanction_lists()
    target = _normalize(address)
    matches: list[SanctionEntry] = []
    for source_name, entries in (("ofac", lists[0]), ("eu", lists[1])):
        for e in entries:
            if _normalize(e.address) == target:
                # zdrojová metrika pro důvody — nezměňujeme entry samotné
                matches.append(e)

    reasons: list[str] = []
    score = 0
    if matches:
        critical_tag = any(set(m.tags) & _CRITICAL_TAGS for m in matches)
        score = 100 if critical_tag else 95
        for m in matches:
            bits = [f"sanctioned: {m.entity or 'unknown entity'}"]
            if m.program:
                bits.append(f"program={m.program}")
            if m.listed_date:
                bits.append(f"listed={m.listed_date}")
            if m.tags:
                bits.append("tags=" + ",".join(m.tags))
            reasons.append("; ".join(bits) + (f" [source: {m.source}]" if m.source else ""))

    level = "none"
    if score >= 100:
        level = "critical"
    elif score >= 95:
        level = "high"
    elif score >= 70:
        level = "medium"
    elif score > 0:
        level = "low"

    return RiskScore(address=address, score=score, level=level, reasons=reasons, entries=matches)


def score_addresses(
    addresses: list[str] | set[str],
    lists: tuple[tuple[SanctionEntry, ...], tuple[SanctionEntry, ...]] | None = None,
) -> dict[str, RiskScore]:
    """Hromadné skórování; klíč = adresa v původním tvaru."""
    if lists is None:
        lists = load_sanction_lists()
    return {a: score_address(a, lists) for a in sorted(set(addresses))}
