"""K3.1 — On-chain data sources (Blockchair / Etherscan) — opt-in, offline-first.

Zásada AK: *opt-in* — bez explicitně vytvořeného klienta se žádná síť
nevolá. Transport je injektovatelný (``transport(url) -> dict``), takže
testy běží plně offline s canned odpověďmi; produkce používá urllib.

Cache: ``TxCache`` ukládá normalizované záznamy do JSON souboru
(``{"schema": 1, "addresses": {addr: [txs]}}``) — deterministické klíče,
atomický zápis (tmp + rename). Poškozený cache = prázdný výsledek +
poslední chyba v ``last_error`` (graceful degradation).

Očekávané wire schéma (defenzivní normalizace — chybějící pole → default):

* Blockchair v2: ``result.transactions[]`` s poli ``hash``, ``time``
  (ISO-8601), ``inputs[{address, amount}]``, ``outputs[{address, amount}]``.
* Etherscan v1 txlist: položky ``hash``, ``timeStamp`` (epoch string),
  ``from``, ``to``, ``value`` (wei) — account-level transfers bez UTXO detailu.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from stopa.domain.crypto.onchain_models import TxInput, TxOutput, TxRecord

CACHE_SCHEMA_VERSION = 1

#: transport: url → parsed JSON (dict). Injektovatelný pro offline testy.
Transport = Callable[[str], dict[str, Any]]


class OnchainApiError(Exception):
    """Síť / HTTP / JSON chyba on-chain provideru."""


def _urllib_transport(url: str) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": "stopa-forensics/1.0 (K3 onchain)"})
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raise OnchainApiError(f"HTTP {exc.code} pro {url}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise OnchainApiError(f"Chyba požadavku {url}: {exc}") from exc


def _iso_to_epoch(value: str | None) -> int | None:
    if not value:
        return None
    try:
        v = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return None


class BlockchairClient:
    """Blockchair v2 BTC adresa→transakce. Opt-in (vyžaduje API key)."""

    BASE = "https://api.blockchair.com/v2/btc/address"

    def __init__(self, api_key: str, transport: Transport | None = None) -> None:
        if not api_key or not api_key.strip():
            raise OnchainApiError("Blockchair API key je prázdný")
        self._key = api_key.strip()
        self._transport = transport or _urllib_transport

    def fetch_address_txs(self, address: str, limit: int = 100) -> list[TxRecord]:
        url = f"{self.BASE}/{quote(address)}?limit={int(limit)}&key={quote(self._key)}"
        data = self._transport(url)
        result = data.get("result") or {}
        raw_txs = result.get("transactions")
        if not isinstance(raw_txs, list):
            raise OnchainApiError("Blockchair odpověď: chybí result.transactions[]")
        out: list[TxRecord] = []
        for item in raw_txs:
            rec = _normalize_blockchair(item)
            if rec is not None:
                out.append(rec)
        return out


def _normalize_blockchair(item: Any) -> TxRecord | None:
    """Defenzivní normalizace jedné Blockchair transakce (None = skip)."""
    if not isinstance(item, dict):
        return None
    txid = item.get("hash") or item.get("tx_hash")
    if not txid:
        return None

    ins: list[tuple[str | None, int]] = _pairs(item.get("inputs"))
    outs: list[tuple[str | None, int]] = _pairs(item.get("outputs"))
    inputs_raw = [TxInput(address=a, amount=m) for a, m in ins]
    outputs_raw = [TxOutput(address=a, amount=m, index=i) for i, (a, m) in enumerate(outs)]
    return TxRecord(
        txid=str(txid),
        chain="btc",
        timestamp=_iso_to_epoch(item.get("time")),
        inputs=inputs_raw,
        outputs=outputs_raw,
    )


def _pairs(raw: Any) -> list[tuple[str | None, int]]:
    if not isinstance(raw, list):
        return []
    out: list[tuple[str | None, int]] = []
    for e in raw[:100]:
        if not isinstance(e, dict):
            continue
        addr = e.get("address") or None
        out.append((addr, _int_or_zero(e.get("amount"))))
    return out


def _int_or_zero(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


class EtherscanClient:
    """Etherscan v1 account txlist (ETH transfers). Opt-in (vyžaduje API key)."""

    BASE = "https://api.etherscan.io/api"

    def __init__(self, api_key: str, transport: Transport | None = None) -> None:
        if not api_key or not api_key.strip():
            raise OnchainApiError("Etherscan API key je prázdný")
        self._key = api_key.strip()
        self._transport = transport or _urllib_transport

    def fetch_address_txs(self, address: str) -> list[TxRecord]:
        url = (
            f"{self.BASE}?module=account&action=txlist"
            f"&address={quote(address)}&startblock=0&endblock=99999999"
            f"&sort=asc&page=1&offset=100&apikey={quote(self._key)}"
        )
        data = self._transport(url)
        if not isinstance(data, dict):
            raise OnchainApiError("Etherscan odpověď: očekáván JSON objekt")
        status = str(data.get("status", ""))
        message = str(data.get("message", ""))
        raw_txs = data.get("result")
        if not isinstance(raw_txs, list):
            raise OnchainApiError(f"Etherscan odpověď: chybí result[] ({status} {message})")
        out: list[TxRecord] = []
        for item in raw_txs:
            rec = _normalize_etherscan(item)
            if rec is not None:
                out.append(rec)
        return out


def _normalize_etherscan(item: Any) -> TxRecord | None:
    if not isinstance(item, dict):
        return None
    txid = item.get("hash")
    if not txid:
        return None
    frm = item.get("from") or None
    to = item.get("to") or None
    value_wei = _int_or_zero(item.get("value"))
    ts_raw = item.get("timeStamp")
    try:
        ts = int(ts_raw) if ts_raw else None
    except (TypeError, ValueError):
        ts = None
    return TxRecord(
        txid=str(txid),
        chain="eth",
        timestamp=ts,
        inputs=[TxInput(address=frm, amount=value_wei)] if frm else [],
        outputs=[TxOutput(address=to, amount=value_wei, index=0)] if to else [],
    )


class TxCache:
    """JSON cache normalizovaných transakcí (offline-first)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.last_error: str | None = None

    def load(self) -> dict[str, list[TxRecord]]:
        """Načte cache; chybějící/poškozený soubor → ``{}`` (+ last_error)."""
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            version = raw.get("schema")
            addrs = raw.get("addresses") or {}
            if version != CACHE_SCHEMA_VERSION or not isinstance(addrs, dict):
                self.last_error = f"cache schema={version!r} (očekáváno {CACHE_SCHEMA_VERSION})"
                return {}
            out: dict[str, list[TxRecord]] = {}
            for addr, txs in addrs.items():
                if not isinstance(txs, list):
                    continue
                recs = []
                for t in txs:
                    try:
                        recs.append(TxRecord.model_validate(t))
                    except ValueError as exc:  # pydantic ValidationError ⊂ ValueError
                        self.last_error = f"cache {addr}: {exc}"
                out[str(addr)] = recs
            return out
        except (OSError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            return {}

    def save(self, data: dict[str, list[TxRecord]]) -> None:
        """Atomický zápis cache (tmp + rename), deterministické klíče."""
        payload = {
            "schema": CACHE_SCHEMA_VERSION,
            "addresses": {
                str(addr): [t.model_dump() for t in txs]
                for addr, txs in sorted(data.items())
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".txcache-")
        try:
            with open(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
            Path(tmp).replace(self.path)
            self.last_error = None
        except OSError as exc:
            self.last_error = str(exc)
            raise OnchainApiError(f"Zápis cache selhal: {exc}") from exc
