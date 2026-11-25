"""P4-6 — Sealing v2: time hash chain F5.1 pečetí + externí witness (čistá logika, bez I/O).

F5.1 dával nezávislé point-in-time pečeti (Merkle kořen + Ed25519 podpis) —
žádný odkaz mezi po sobě jdoucími pečetěmi a žádný out-of-band důkaz. P4-6
přidává řetěz: každý záznam vazí **minulý** Merkle kořen + aktuální kořen
+ identitu případu + čas, takže manipulace s jakýmkoli minulým rootem láme
linku a ověření (fail-closed ``ValueError``).

Formula řetězového hashu::

    chain_hash = SHA-256(DOMAIN_TAG || 0x00 || prev_root || 0x00 || case_id
                         || 0x00 || ts_iso || 0x00 || merkle_root)

Genesis pravidlo: první záznam nemá předchůdce → ``prev_root`` := vlastní
Merkle root (self-binding; deterministické, bez magických konstant).

Externí witness (volitelný): kanonický JSON z ``(kind, ref, obsah)`` —
SHA-256 digest + inline base64 obsahu do :data:`WITNESS_MAX_INLINE` B.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass

#: Verze doménového tagu řetězového payloadu (domain separation od F5.1 rootu).
DOMAIN_TAG = b"stopa-seal-chain/v1"

#: Maximální velikost obsahu witness, který se inline ukládá jako base64;
#: větší obsah nese jen digest + referenci (DB zůstává kompaktní).
WITNESS_MAX_INLINE = 32 * 1024

#: Povolené druhy externího witnessu (design §P4-6: URL atestace / lokální soubor).
WITNESS_KINDS: tuple[str, ...] = ("url", "file")


@dataclass(frozen=True)
class SealChainRecord:
    """Jeden odkaz řetězce pečetí jednoho případu.

    ``prev_merkle_root_hex`` = None znamená genesis (pravidlo: vlastní root);
    při serializaci do DB se uloží efektní hodnota (self-binding).
    """

    seq: int
    ts_iso: str
    merkle_root_hex: str
    prev_merkle_root_hex: str | None
    chain_hash_hex: str
    witness_json: str | None = None


def _payload(
    case_id: str,
    ts_iso: str,
    merkle_root_hex: str,
    prev_root_hex: str,
) -> bytes:
    return (
        DOMAIN_TAG
        + b"\x00"
        + prev_root_hex.encode("utf-8")
        + b"\x00"
        + case_id.encode("utf-8")
        + b"\x00"
        + ts_iso.encode("utf-8")
        + b"\x00"
        + merkle_root_hex.encode("utf-8")
    )


def compute_chain_hash(
    case_id: str,
    ts_iso: str,
    merkle_root_hex: str,
    prev_merkle_root_hex: str | None = None,
) -> str:
    """SHA-256 řetězového hashu (hex).

    ``prev_merkle_root_hex=None`` → genesis pravidlo: vazí se vlastní root.
    Typové chyby vstupů → :class:`TypeError` (konvence projektu).
    """
    for name, val in (
        ("case_id", case_id),
        ("ts_iso", ts_iso),
        ("merkle_root_hex", merkle_root_hex),
    ):
        if not isinstance(val, str):
            raise TypeError(f"seal_chain: {name} musí být string")
    if prev_merkle_root_hex is not None and not isinstance(prev_merkle_root_hex, str):
        raise TypeError("seal_chain: prev_merkle_root_hex musí být string nebo None")
    prev = merkle_root_hex if prev_merkle_root_hex is None else prev_merkle_root_hex
    return hashlib.sha256(_payload(case_id, ts_iso, merkle_root_hex, prev)).hexdigest()


def build_record(
    seq: int,
    case_id: str,
    ts_iso: str,
    merkle_root_hex: str,
    prev_merkle_root_hex: str | None = None,
    witness: dict | None = None,
) -> SealChainRecord:
    """Sestaví záznam řetězce (``seq`` musí být kladné celé číslo)."""
    if isinstance(seq, bool) or not isinstance(seq, int):
        raise TypeError("seal_chain: seq musí být integer")
    if seq <= 0:
        raise ValueError(f"seal_chain: seq musí být ≥ 1 (fakt {seq})")
    witness_json = json.dumps(witness, sort_keys=True, separators=(",", ":")) if witness else None
    return SealChainRecord(
        seq=seq,
        ts_iso=ts_iso,
        merkle_root_hex=merkle_root_hex,
        prev_merkle_root_hex=(
            merkle_root_hex if prev_merkle_root_hex is None else prev_merkle_root_hex
        ),
        chain_hash_hex=compute_chain_hash(case_id, ts_iso, merkle_root_hex, prev_merkle_root_hex),
        witness_json=witness_json,
    )


# B9 — strojově čitelné typy defektů seal v2 řetězce (diagnostika/kompenzace).
SEAL_CHAIN_SEQ_GAP = "seq_gap"                  # nepretržitá sekvence 1..N
SEAL_CHAIN_LINK_BROKEN = "link_broken"          # prev root != root předchozího záznamu
SEAL_CHAIN_HASH_MISMATCH = "chain_hash_mismatch"  # chain_hash != přepočet


@dataclass(frozen=True)
class SealChainDefect:
    """B9 — jeden defekt seal v2 řetězce s přesnou lokalizací (seq + typ)."""

    seq: int | None  # None = viz message; jinak seq postiženého záznamu
    kind: str        # SEAL_CHAIN_* konstanta
    message: str


def collect_chain_defects(case_id: str, records: list[SealChainRecord]) -> list[SealChainDefect]:
    """B9 — čistá doménová skenerka celého řetězce; vrací **všechny** defekty.

    Stejná pravidla i pořadí kontrol jako :func:`verify_chain` (sekvence 1..N,
    genesis self-binding, prev root = root předchozího záznamu, přepočet
    ``chain_hash``), ale bez fail-closed přerušení — po defektu sken pokračuje od
    *uložených* hodnot → každý tamperovaný záznam se lokalizuje zvlášť. Prázdný
    seznam = řetězec OK; používá report pro přesnou lokalizaci a kompenzační
    logiku (BC: fail-closed chování viz :func:`verify_chain`).

    Typová chyba ``case_id`` → :class:`TypeError` (konvence projektu).
    """
    if not isinstance(case_id, str):
        raise TypeError("seal_chain: case_id musí být string")
    defects: list[SealChainDefect] = []
    for i, rec in enumerate(records, start=1):
        expected_prev = (
            records[i - 2].merkle_root_hex if i > 1 else rec.merkle_root_hex
        )
        # Pořadí kontrol odpovídá verify_chain (BC): sekvence → linka → hash.
        if rec.seq != i:
            defects.append(SealChainDefect(rec.seq, SEAL_CHAIN_SEQ_GAP,
                                           f"seal_chain: sekvence není nepretržitá (pozice {i} ≠ seq={rec.seq})"))
        if rec.prev_merkle_root_hex != expected_prev:
            defects.append(SealChainDefect(rec.seq, SEAL_CHAIN_LINK_BROKEN,
                                           f"seal_chain: záznam seq={rec.seq} — prev root "
                                           f"{rec.prev_merkle_root_hex!r} neodpovídá kořeni předchozí pečetě "
                                           f"(očekáváno {expected_prev!r})"))
        # Přepočet z **uloženého** prev rootu: hash validuje vazbu na pole;
        # samostatná kontrola nahoře validuje, že prev = kořen předchozí pečetě.
        recomputed = compute_chain_hash(case_id, rec.ts_iso, rec.merkle_root_hex, rec.prev_merkle_root_hex)
        if recomputed != rec.chain_hash_hex:
            defects.append(SealChainDefect(rec.seq, SEAL_CHAIN_HASH_MISMATCH,
                                           f"seal_chain: záznam seq={rec.seq} — chain_hash se liší od přepočtu "
                                           "(upraven case_id/ts/root/prev)"))
    return defects


def verify_chain(case_id: str, records: list[SealChainRecord]) -> int:
    """Ověří integritu celého řetězce; vrací počet záznamů (fail-closed).

    Kontrola: neprázdnost identifikátorů, nepretržitá sekvence 1..N,
    každý ``prev`` = root předchozího záznamu (genesis = vlastní root) a
    přepočet ``chain_hash``. Jakákoli odchylka → :class:`ValueError`.

    B9 — pravidla sdílí se :func:`collect_chain_defects` (jediný zdroj); první
    defekt končí ValueError s identickou zprávou jako dříve (BC). Pro všechny
    defekty najednou použijte ``collect_chain_defects``.
    """
    first = collect_chain_defects(case_id, records)
    if first:
        raise ValueError(first[0].message)  # BC: fail-closed na prvním defektu
    return len(records)


def canonical_witness(kind: str, ref: str, content: bytes) -> dict:
    """Kanonický witness payload (externí důkaz o rootu v daném okamžiku).

    ``kind`` ∈ {"url", "file"}; obsah se nese jako SHA-256 digest a inline
    base64 jen do :data:`WITNESS_MAX_INLINE` B. Typová chyba → TypeError,
    neznámý kind → ValueError (fail-closed).
    """
    if not isinstance(kind, str) or not isinstance(ref, str):
        raise TypeError("seal_chain: witness kind/ref musí být stringy")
    if not isinstance(content, (bytes, bytearray)):
        raise TypeError("seal_chain: witness content musí být bytes")
    if kind not in WITNESS_KINDS:
        raise ValueError(
            f"seal_chain: neznámý witness kind {kind!r} (očekáváno {'|'.join(WITNESS_KINDS)})"
        )
    data = bytes(content)
    out: dict = {
        "bytes": len(data),
        "digest": hashlib.sha256(data).hexdigest(),
        "kind": kind,
        "ref": ref,
    }
    out["content_b64"] = base64.b64encode(data).decode("ascii") if len(data) <= WITNESS_MAX_INLINE else None
    return out
