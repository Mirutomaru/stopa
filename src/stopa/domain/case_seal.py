"""STOPA — F5.1 Merkle Tree Case Sealing (Compliance & Court-Readiness).

Zamknutí stavu případu jedním kryptografickým kořenem: každý artifact,
timeline event a audit záznam je leaf v Merkle stromě; root hash se podepíše
Ed25519 klíčem případu (C4 integrity vrstva). Ověření jedním příkazem
(``stopa verify <case>``) — změna 1 bitu v jakémkoli zamčeném řádku změní
root → FAIL.

Čistá logika bez I/O: data vrstva (:mod:`stopa.data.seal_repository`)
přepočte leafy ze SQLite a volá :func:`build_merkle_root`. Ed25519 zůstává
v :mod:`stopa.domain.integrity` (lazy ``cryptography``).

Kanonizace a determinismus
--------------------------
- **Globální pořadí leafů** je pevné: ``artifacts`` (pořadí vložení = rowid)
  → ``timeline_events`` (rowid) → ``audit_log`` (id). Stejný stav tabulek =
  stejný root nezávisle na strojovém porovnání řetězců.
- **Leaf payload** neseme domain tag ``stopa-case-seal/v1`` + jméno tabulky,
  takže totéž datum v jiné tabulce nikdy nedá stejný leaf (oddělení
  domén — analogie per-algorithm genesis u audit chainu). Hodnoty sloupců se
  serializují ``json.dumps(value)`` (deterministické pro str/int/float/None;
  control znaky json escapuje → oddělovač ``\\x1f`` je bezkolizní).
- **Merkle strom**: binární, párové SHA-256; lichý uzel se propaguje
  beze změny (left promotion — standardní konvence). Prázdná množina leafů
  → konstanta :data:`EMPTY_ROOT` (deterministická, ne None). Jeden leaf =
  root je jeho digest.

Semantika zamčení (snapshot s předponou)
----------------------------------------
Pečeť fixuje **první N řádků každé tabulky v pořadí vložení** (N = stav
v okamžiku pečetí). Důsledek: pozdější *append* nových artifactů/timeline
událostí/audit záznamů pečeť neruší (druhý disk dorazil po zamčení — stará
pečeť na prvním disku zůstává platná), ale jakákoli *změna nebo smazání*
fixovaného řádku root změní → FAIL. Opakované pečeti spolu koexistují;
každá ověřuje svůj fixovaný rozsah.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

#: Verze formátu pečetí (formát leaf payload + stromu) — do meta_json pečetě.
SEAL_FORMAT_VERSION = 1

#: Domain tag leafů — oddělení od jiných hash domén (audit chain, manifesty).
DOMAIN_TAG = b"stopa-case-seal/v1"

#: Deterministický root prázdné množiny leafů (prázdný případ je zamknutelný).
EMPTY_ROOT: bytes = hashlib.sha256(DOMAIN_TAG + b"\x00empty").digest()


def canonical_row_payload(table: str, values: Iterable[object]) -> bytes:
    """Kanonický payload jednoho řádku pro leaf hash.

    ``values`` — pořadí hodnot sloupců dle schématu (tupl/seznam). Každá
    hodnota se serializuje ``json.dumps(ensure_ascii=False)`` a řetězí se s
    oddělovačem ``\\x1f`` (unit separator); json escapuje všechny control
    znaky → v payloadu se nikdy neobjeví surový ``\\x1f`` uvnitř hodnoty.

    Payload = DOMAIN_TAG || b"\\x00" || jméno tabulky || b"\\x00" || body.
    Stejné datum ve dvou tabulkách → různé leafy (jméno tabulky v payloadu).
    """
    parts: list[bytes] = [DOMAIN_TAG, b"\x00", table.encode("utf-8"), b"\x00"]
    for v in values:
        # sort_keys=True → determinismus nezávislý na pořadí klíčů dictu v Pythonu
        parts.append(json.dumps(v, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        parts.append(b"\x1f")
    return b"".join(parts)


def leaf_hash(table: str, values: Iterable[object]) -> bytes:
    """SHA-256 kanonického payloadu řádku (32 B digest)."""
    return hashlib.sha256(canonical_row_payload(table, values)).digest()


def build_merkle_root(leaves: list[bytes]) -> bytes:
    """Kořen binárního Merkle stromu nad leaf digesty.

    - prázdný vstup → :data:`EMPTY_ROOT` (deterministická konstanta)
    - jeden leaf → root = ten leaf (již je digest)
    - jinak párové SHA-256(left || right); lichý uzel se propaguje beze změny
      (left promotion). Pořadí leafů je významné.
    """
    if not leaves:
        return EMPTY_ROOT
    level = list(leaves)
    while len(level) > 1:
        nxt: list[bytes] = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                nxt.append(hashlib.sha256(level[i] + level[i + 1]).digest())
            else:  # lichý uzel — left promotion (standardní konvence)
                nxt.append(level[i])
        level = nxt
    return level[0]


def root_hex(root: bytes) -> str:
    """Hex reprezentace kořene (64 znaků pro SHA-256)."""
    return root.hex()
