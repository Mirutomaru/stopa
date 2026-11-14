"""STOPA — K2.4 exchange CSV parsery (Binance, Coinbase, Kraken) — čistá doménová vrstva.

Defenzivní parsování header-driven: sloupce se rozpoznávají aliasy (skutečné exporty
se liší verzí a lokalizací UI), neznámé sloupce se ignorují, chybějící hodnoty →
``None`` v záznamu. Časové formáty: ISO-8601 (Z/offset), unix epoch s/ms, Kraken float
epoch — normalizace na aware UTC ``datetime``.

Normalizovaný záznam zachovává i raw řádek (audit) a analytika (gaps v timeline).
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

# ── modely ───────────────────────────────────────────────────────────────


class ExchangeRecord(BaseModel):
    """Normalizovaný záznam z exchange exportu."""

    exchange: str  # "binance" | "coinbase" | "kraken"
    kind: str  # binance_deposits | … (konkrétní typ exportu)
    record_type: str  # deposit | withdrawal | trade | balance | transfer | other
    timestamp: datetime | None = None  # aware UTC; None = neanalyzovatelný čas
    asset: str | None = None
    amount: float | None = None
    price: float | None = None
    fee: float | None = None
    side: str | None = None  # buy/sell (trades) / raw Type hodnota
    address_or_counterparty: str | None = None
    txid_reference: str | None = None
    raw: dict[str, str] = Field(default_factory=dict)  # původní řádek (audit)


class ExchangeParse(BaseModel):
    """Výsledek parsování jednoho CSV exportu."""

    exchange: str
    kind: str
    records: list[ExchangeRecord] = Field(default_factory=list)
    skipped_rows: int = 0
    warnings: list[str] = Field(default_factory=list)


# ── pomocné funkce ───────────────────────────────────────────────────────

_TIME_ALIASES = ("time", "timestamp", "date/time", "date", "balance time")
_ASSET_ALIASES = ("asset", "currency", "pair", "symbol")
_AMOUNT_ALIASES = ("amount", "volume", "quantity", "total")
_FEE_ALIASES = ("fee",)
_ADDRESS_ALIASES = ("address", "counterparty", "pay to", "to")
_TXID_ALIASES = ("txhash", "transaction id", "reference", "client order id")


def _norm_header(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _resolve(header_norm: dict[str, str], aliases: tuple[str, ...]) -> str | None:
    """Vrátí skutečný (původní) název sloupce pro první sednoucí alias."""

    for alias in aliases:
        if alias in header_norm:
            return header_norm[alias]
    return None


def _parse_ts(value: str | None) -> datetime | None:
    """Normalizace časových formátů na aware UTC; neanalyzovatelné → ``None``."""

    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    # ISO-8601 (Python ≥3.11 umí i „Z")
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    # unix epoch (s i ms — Kraken float epoch, Binance/Coinbase někdy numeric)
    try:
        f = float(v)
    except ValueError:
        return None
    if f < 0:
        return None
    if abs(f) >= 1e12:  # milisekundy
        f /= 1000.0
    return datetime.fromtimestamp(f, tz=timezone.utc)


def _parse_amount(value: str | None) -> float | None:
    """Číslo s volitelnými $ / tisíčními oddělovači; neanalyzovatelné → ``None``."""

    if value is None:
        return None
    v = value.strip().replace("$", "").replace(",", "").replace(" ", "")
    if not v or v == "-":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _clean(value: str | None) -> str | None:
    """Prázdné/None → None, jinak stripnutý string."""

    if value is None:
        return None
    v = value.strip()
    return v or None


# ── detekce typu exportu podle hlavičky ──────────────────────────────────

_KNOWN_KINDS = (
    "binance_deposits",
    "binance_withdrawals",
    "binance_trades",
    "coinbase_transactions",
    "coinbase_balance_history",
    "kraken_trades",
    "kraken_funds",
)


def _header_set(text: str, limit_bytes: int = 65536) -> dict[str, str] | None:
    """První řádek jako {norm_název: původní_název}; prázdné/žádné → None."""

    head = text[:limit_bytes].splitlines()
    if not head or not head[0].strip():
        return None
    first = head[0]
    if "\t" in first and "," not in first:  # TSV fallback (některé exporty)
        cols = [c.strip() for c in first.split("\t")]
    else:
        try:
            row = next(csv.reader(io.StringIO(first)))
        except csv.Error:
            return None
        cols = [c.strip() for c in row]
    if not any(c for c in cols):
        return None
    out: dict[str, str] = {}
    for col in cols:
        n = _norm_header(col)
        if n and n not in out:
            out[n] = col
    return out


def detect_exchange_csv(text: str, exchange_hint: str | None = None) -> str | None:
    """Rozpozná typ exchange CSV podle hlavičky; neexchange → ``None``.

    ``exchange_hint`` rozlišuje dvousmyslné případy (např. kraken funds bez
    „pair" sloupce).
    """

    hdr = _header_set(text)
    if not hdr:
        return None
    has = lambda *names: any(n in hdr for n in names)
    time_col = has(*_TIME_ALIASES)
    amount_col = has("amount", "volume")

    # Coinbase balance history — přesná dvojice sloupců
    if "balance time" in hdr and "balance" in hdr:
        return "coinbase_balance_history"

    # Binance funds (deposits/withdrawals) — Time/Asset/Amount; fee → withdrawal
    if has("asset") and amount_col and has(*_TIME_ALIASES):
        if exchange_hint == "binance":
            return "binance_withdrawals" if has("fee", "withdraw order id") else "binance_deposits"
        # bez hintu: fee sloupec rozhoduje, jinak deposits (depozity jsou častější)
        return "binance_withdrawals" if has("fee", "withdraw order id") else "binance_deposits"

    # Binance trades — Symbol/Side/Price
    if has("symbol") and has("side") and has("price", "quantity"):
        return "binance_trades"

    # Coinbase transactions — Type + Amount (+ Currency/Counterparty) + čas
    if (
        "type" in hdr
        and amount_col
        and time_col
        and ("currency" in hdr or "counterparty" in hdr or exchange_hint == "coinbase")
    ):
        return "coinbase_transactions"

    # Kraken trades — malá písmena: time/pair/side/volume/price
    if all(c in hdr for c in ("time", "pair", "side", "volume", "price")):
        return "kraken_trades"

    # Kraken funds (deposits+withdrawals) — Type + Amount + čas (+ pair)
    if "type" in hdr and amount_col and time_col and ("pair" in hdr or exchange_hint == "kraken"):
        return "kraken_funds"

    return None


# ── parsery jednotlivých typů ────────────────────────────────────────────


def _delim(text: str) -> str:
    """Sniffing oddělovače prvního řádku (TSV exporty některých exchange)."""

    first = text.splitlines()[0] if text else ""
    return "\t" if ("\t" in first and "," not in first) else ","


def _rows(text: str) -> list[dict[str, str]]:
    try:
        reader = csv.DictReader(io.StringIO(text), delimiter=_delim(text))
        out = []
        for row in reader:
            clean_row = {
                (k or "").strip(): (v if isinstance(v, str) else "")
                for k, v in row.items()
                if k is not None and (v is None or len(v) == 0 or v.strip())
            }
            # vynechat zcela prázdné řádky
            if any(val.strip() for val in clean_row.values()):
                out.append(clean_row)
        return out
    except csv.Error:
        return []


def _pick(row: dict[str, str], hdr: dict[str, str], aliases: tuple[str, ...]) -> str | None:
    col = _resolve(hdr, aliases)
    if col is None or col not in row:
        return None
    return _clean(row.get(col))


def parse_exchange_csv(text: str, exchange_hint: str | None = None) -> ExchangeParse | None:
    """Parsoval CSV export → normalizované záznamy; neexchange → ``None``."""

    kind = detect_exchange_csv(text, exchange_hint=exchange_hint)
    if kind is None:
        return None
    hdr = _header_set(text)
    assert hdr is not None  # detekce už hlavičku ověřila
    rows = _rows(text)

    p = ExchangeParse(exchange=kind.split("_")[0], kind=kind)
    for row in rows:
        raw_audit = {k: (v or "") for k, v in row.items() if isinstance(k, str)}
        rec = ExchangeRecord(
            exchange=p.exchange, kind=kind, record_type="other", raw=raw_audit
        )

        ts_raw = _pick(row, hdr, _TIME_ALIASES)
        rec.timestamp = _parse_ts(ts_raw)

        if kind in ("binance_deposits", "binance_withdrawals"):
            rec.record_type = "deposit" if kind == "binance_deposits" else "withdrawal"
            rec.asset = _pick(row, hdr, ("asset",))
            rec.amount = _parse_amount(_pick(row, hdr, ("amount",)))
            rec.fee = _parse_amount(_pick(row, hdr, _FEE_ALIASES))
            rec.address_or_counterparty = _pick(row, hdr, _ADDRESS_ALIASES)
            txid = _pick(row, hdr, _TXID_ALIASES) or _pick(row, hdr, ("transaction id",))
            rec.txid_reference = txid

        elif kind == "binance_trades":
            rec.record_type = "trade"
            rec.asset = _pick(row, hdr, ("symbol",))
            rec.side = _clean(_pick(row, hdr, ("side",)))
            rec.price = _parse_amount(_pick(row, hdr, ("price",)))
            rec.amount = _parse_amount(_pick(row, hdr, ("quantity", "volume")))
            rec.fee = _parse_amount(_pick(row, hdr, _FEE_ALIASES))
            rec.txid_reference = _pick(row, hdr, _TXID_ALIASES)

        elif kind == "coinbase_transactions":
            type_val = _clean(_pick(row, hdr, ("type",))) or ""
            tl = type_val.lower()
            if any(t in tl for t in ("deposit",)):
                rec.record_type = "deposit"
            elif any(t in tl for t in ("withdrawal", "withdraw")):
                rec.record_type = "withdrawal"
            elif tl in ("buy", "sell"):
                rec.record_type = "trade"
                rec.side = tl
            elif any(t in tl for t in ("send",)):
                rec.record_type = "transfer"
                rec.side = "out"
            elif any(t in tl for t in ("receive",)):
                rec.record_type = "transfer"
                rec.side = "in"
            else:
                rec.record_type = "other"
            rec.side = rec.side or (tl if tl in ("buy", "sell") else None)
            rec.asset = _pick(row, hdr, ("currency", "asset"))
            rec.amount = _parse_amount(_pick(row, hdr, ("amount",)))
            rec.fee = _parse_amount(_pick(row, hdr, _FEE_ALIASES))
            rec.address_or_counterparty = _pick(row, hdr, _ADDRESS_ALIASES) or type_val or None
            rec.txid_reference = _pick(row, hdr, ("transaction id", "reference"))

        elif kind == "coinbase_balance_history":
            rec.record_type = "balance"
            rec.amount = _parse_amount(_pick(row, hdr, ("balance",)))
            asset = _pick(row, hdr, ("currency", "asset"))
            if asset:
                rec.asset = asset

        elif kind == "kraken_trades":
            rec.record_type = "trade"
            rec.asset = _pick(row, hdr, ("pair",))
            rec.side = _clean(_pick(row, hdr, ("side",)))
            rec.amount = _parse_amount(_pick(row, hdr, ("volume",)))
            rec.price = _parse_amount(_pick(row, hdr, ("price",)))
            rec.fee = _parse_amount(_pick(row, hdr, _FEE_ALIASES))

        elif kind == "kraken_funds":
            type_val = (_clean(_pick(row, hdr, ("type",))) or "").lower()
            if "deposit" in type_val:
                rec.record_type = "deposit"
            elif "withdraw" in type_val:
                rec.record_type = "withdrawal"
            else:
                rec.record_type = "other"
            rec.asset = _pick(row, hdr, ("pair", "asset"))
            rec.amount = _parse_amount(_pick(row, hdr, ("amount",)))
            rec.fee = _parse_amount(_pick(row, hdr, _FEE_ALIASES))
            rec.txid_reference = _pick(row, hdr, _TXID_ALIASES)

        # validita: bez času i částky → řádek nepoužitelný
        if rec.timestamp is None and rec.amount is None and rec.record_type == "other":
            p.skipped_rows += 1
        else:
            p.records.append(rec)

    return p


# ── analytika (spec AK: gaps v timeline) ─────────────────────────────────


def find_timeline_gaps(
    records: list[ExchangeRecord], min_gap_days: float = 14.0
) -> list[dict[str, Any]]:
    """Gapy > ``min_gap_days`` mezi po sobě následujícími záznamy (podle času).

    Záznamy bez timestampu se ignorují; výsledek je řazený seznam
    ``{"from", "to", "gap_days"}`` (ISO stringy + počet dní, 2 desetinná místa).
    """

    timed = [(r.timestamp, r) for r in records if r.timestamp is not None]
    timed.sort(key=lambda pair: pair[0])
    gaps: list[dict[str, Any]] = []
    prev: datetime | None = None
    for ts, rec in timed:
        assert ts is not None  # filtr výše
        if prev is not None:
            delta_days = (ts - prev).total_seconds() / 86400.0
            if delta_days > min_gap_days:
                gaps.append(
                    {
                        "from": prev.isoformat(),
                        "to": ts.isoformat(),
                        "gap_days": round(delta_days, 2),
                    }
                )
        prev = ts
    return gaps
