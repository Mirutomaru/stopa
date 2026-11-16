"""K5.2 — NFT analysis (ownership chain, marketplaces, known collections).

Offline-first:

- ``nft_contracts.json`` — ověřené sbírky (CryptoPunks, BAYC) + marketplace termíny.
- ``NftTransfer.normalize()`` akceptuje flexibilní klíče (contract/contract_address,
  from/to/from_address/to_address, tokenId/token_id) — EVM trace exporty mají různé formáty.
- ``ownership_chain()`` — deterministický řetězec vlastnictví pro daný token_id:
  mint → transfers seřazené podle (block_number, tx_index); první držitel = mint
  (from == ZERO_ADDRESS).

Bez sítě a LLM; vstupem jsou extrahované transfer záznamy (např. z EVM trace artefaktů).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

_DATA_DIR = Path(__file__).resolve().parent / "data"
_NFT_PATH = _DATA_DIR / "nft_contracts.json"

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


class NftRegistryError(Exception):
    """Chyba načtení/validace bundlovaného registru NFT sbírek."""


class NftContractInfo(BaseModel):
    """Položka registru — ověřená smlouva známé NFT sbírky."""

    address: str
    chain: str = "eth"
    collection: str
    standard: str = "erc721"  # erc721 | erc1155
    verified: bool = False
    source: str = ""


class NftTransfer(BaseModel):
    """Normalizovaný záznam o transferu NFT (jedna událost Transfer)."""

    contract: str
    token_id: int
    from_addr: str
    to_addr: str
    block_number: int | None = None
    tx_index: int | None = None
    timestamp: int | None = None  # epoch sekundy, None = neznámá

    @classmethod
    def normalize(cls, raw: dict) -> NftTransfer:
        """Tolerantní normalizace slovníku s rozdílnými klíči (EVM trace exporty)."""
        contract = str(
            raw.get("contract") or raw.get("contract_address") or raw.get("address") or ""
        ).strip()
        token_id_raw = raw.get("token_id", raw.get("tokenId", raw.get("id")))
        if token_id_raw is None or isinstance(token_id_raw, bool):
            raise NftRegistryError(f"NFT transfer: chybějící token_id: {token_id_raw!r}")
        try:
            token_id = int(token_id_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise NftRegistryError(f"NFT transfer: token_id není číslo: {token_id_raw!r}") from exc
        return cls(
            contract=contract,
            token_id=token_id,
            from_addr=str(raw.get("from", raw.get("from_address", ""))).strip(),
            to_addr=str(raw.get("to", raw.get("to_address", ""))).strip(),
            block_number=_opt_int(raw.get("block_number", raw.get("blockNumber"))),
            tx_index=_opt_int(raw.get("tx_index", raw.get("transactionIndex", raw.get("index")))),
            timestamp=_opt_int(raw.get("timestamp")),
        )


def _opt_int(v: object) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class OwnerStep(BaseModel):
    """Krok v řetězci vlastnictví NFT."""

    order: int  # 1 = první držitel (mint)
    owner: str
    event: str  # mint | transfer
    block_number: int | None = None
    tx_index: int | None = None


class NftFinding(BaseModel):
    """Detekce NFT indikátorů v jednom textovém dokumentu."""

    origin: str = ""
    collections: tuple[str, ...] = ()  # známé sbírky (adresa z registru)
    marketplaces: tuple[str, ...] = ()
    token_ids: tuple[int, ...] = ()
    score: int = 0


@lru_cache(maxsize=8)
def load_nft_registry(path: Path | None = None) -> (
    tuple[tuple[NftContractInfo, ...], tuple[str, ...]]
):
    """Načte a validuje bundlovaný registr NFT sbírek.

    Vrací ``(entries, marketplaces)`` jako nezměnitelné struktury.
    """
    p = path or _NFT_PATH
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NftRegistryError(f"Registr nft_contracts se nepodařilo načíst: {exc}") from exc

    entries: list[NftContractInfo] = []
    for i, item in enumerate(raw.get("entries", [])):
        try:
            e = NftContractInfo(**item)
        except Exception as exc:  # pydantic ValidationError atd.
            raise NftRegistryError(f"nft_contracts, položka {i}: {exc}") from exc
        if not e.address.startswith("0x"):
            raise NftRegistryError(
                f"nft_contracts, položka {i}: adresa bez 0x prefixu: {e.address!r}"
            )
        entries.append(e)

    markets = tuple(str(m).lower() for m in raw.get("marketplaces", []))
    return tuple(entries), markets


def ownership_chain(
    transfers: list[NftTransfer], token_id: int
) -> list[OwnerStep]:
    """Deterministický řetězec vlastnictví pro ``token_id``.

    Transfery se filtrují podle token_id a řadí (block_number, tx_index);
    záznamy bez bloku jdou na konec (stabilně). První krok = mint
    (from == ZERO_ADDRESS) nebo první držitel; další kroky = to_addr transferů.
    """
    rel = [t for t in transfers if t.token_id == token_id]

    def _key(t: NftTransfer) -> tuple[int, int]:
        return (t.block_number or 0, t.tx_index or 0)

    rel.sort(key=_key)
    steps: list[OwnerStep] = []
    order = 1
    for i, t in enumerate(rel):
        if not t.to_addr:
            continue
        is_mint = (t.from_addr or "").lower() == ZERO_ADDRESS.lower() and i == 0
        event = "mint" if is_mint else "transfer"
        steps.append(
            OwnerStep(
                order=order,
                owner=t.to_addr,
                event=event,
                block_number=t.block_number,
                tx_index=t.tx_index,
            )
        )
        order += 1
    return steps


def current_holder(chain: list[OwnerStep]) -> str | None:
    """Aktuální držitel = poslední krok řetězce (None = prázdný řetězec)."""
    if not chain:
        return None
    return chain[-1].owner


_TOKEN_ID_RE = re.compile(
    r"(?:token\s*id|tokenId|#)\s*:?\s*(\d{1,20})\b", re.IGNORECASE
)


def detect_nft_in_text(text: str, origin: str = "") -> NftFinding | None:
    """Deterministická detekce NFT indikátorů v textu.

    Skóre = 3× známá sbírka (adresa z registru) + 2× marketplace + 1× token_id.
    Vrací None, pokud není žádný indikátor (score == 0).
    """
    entries, markets = load_nft_registry()

    collections: list[str] = []
    for e in entries:
        if re.search(rf"(?<!\w){re.escape(e.address.lower())}(?!\w)", text, re.IGNORECASE):
            collections.append(e.collection)

    found_markets = [m for m in markets if _word_re(m).search(text)]
    token_ids = sorted({int(m.group(1)) for m in _TOKEN_ID_RE.finditer(text)})

    score = 3 * len(collections) + 2 * len(found_markets) + min(len(token_ids), 5)
    if score == 0:
        return None
    return NftFinding(
        origin=origin,
        collections=tuple(sorted(set(collections))),
        marketplaces=tuple(found_markets),
        token_ids=tuple(token_ids),
        score=score,
    )


def _word_re(term: str) -> re.Pattern[str]:
    parts = [re.escape(part) for part in term.split(" ")]
    body = r"\s+".join(parts)
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)
