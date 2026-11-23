"""STOPA — K2 pipeline extraktor: crypto wallets + exchange CSV + K1 content scan.

IO vrstva (AXIOM-style): čte soubor, volá čisté doménové parsery
(``domain.crypto.wallets`` / ``domain.crypto.exchanges``) a K1 detektory, vrací
``list[Artifact]`` pro pipeline.

Strategie:
- strukturované formáty mají přednost (Electrum JSON → MetaMask vault → exchange CSV);
- Bitcoin Core ``wallet.dat`` — BDB btree kontejner, čistě pythonová čtečka
  (``domain.crypto.bdb``, bez nových závislostí) — adresy/labely/transakce + detekce šifrování;
- nestrukturovaný text → K1 content scan (seedy/klíče/adresy/transakční refy) —
  jen u souborů, které se dají dekodovat jako text a jsou do ``CRYPTO_TEXT_SCAN_MAX``.

PII guard: citlivé materiály nesou fingerprint SHA-256, ne raw hodnotu (spec §7).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from stopa.domain.crypto.addresses import validate_address
from stopa.domain.crypto.bdb import BdbError, is_bdb_btree
from stopa.domain.crypto.enums import AddressStatus
from stopa.domain.crypto.exchanges import ExchangeRecord, parse_exchange_csv
from stopa.domain.crypto.models import (
    CryptoDetectionResult,
    TransactionReference,
    WalletDetection,
    make_detection_artifact,
)
from stopa.domain.crypto.wallets import (
    BitcoinCoreWallet,
    ElectrumWallet,
    MetaMaskVaultData,
    is_electrum_wallet,
    is_metamask_vault,
    parse_bitcoin_core_wallet,
    parse_electrum_wallet,
    parse_metamask_vault,
)
from stopa.domain.json_bounded import bounded_json_loads
from stopa.models import Artifact

CRYPTO_EXTRACT_VERSION = "1.0"

# limity — velká binárka nesmí zpomalit ingest
CRYPTO_MAX_BYTES = 16 * 1024 * 1024  # strukturované parsery (JSON/CSV)
CRYPTO_TEXT_SCAN_MAX = 4 * 1024 * 1024  # K1 regex scan
CRYPTO_BDB_MAX_BYTES = 64 * 1024 * 1024  # wallet.dat — BDB potřebuje celý soubor (stránky od 0)
CRYPTO_MAX_RECORDS = 20_000  # strop počtu exchange záznamů na soubor

# K1 content scan — kandidáti na adresy (tokeny, které formátovými pravidly sedí)
_ADDR_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{7,}")
_ETH_ADDR_RE = re.compile(r"0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")
_BTC_TXID_RE = re.compile(r"(?<![\w.])(?:[a-fA-F0-9]{64})(?![\w.])")
_ETH_TXID_RE = re.compile(r"0x[a-fA-F0-9]{64}(?![a-fA-F0-9])")


def is_crypto_candidate_file(name_or_path: str) -> bool:
    """Gate pro name-based dispatch: CSV/JSON + wallet/vault klíčová slova.

    Akceptuje i cestu (full-path retry v pipeline) — ``default_wallet`` bez
    přípony se pozná podle ``.electrum/wallets/`` segmentu.
    """

    p = str(name_or_path)
    name = Path(p).name.lower()
    if name.endswith((".csv", ".json")):
        return True
    if any(k in name for k in ("wallet", "vault", "electrum", "metamask")):
        return True
    low = p.replace("\\", "/").lower()
    return bool(".electrum" in low and "wallets" in low)


# ── dekodování ───────────────────────────────────────────────────────────


def _decode(data: bytes) -> str | None:
    """UTF-8 (případně s BOM); binárka (NUL v hlavičce) → None."""

    if b"\x00" in data[:4096]:
        return None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("latin-1")
        except Exception:  # noqa: BLE001 — defenzivní
            return None
    if "\x00" in text[:4096]:
        return None
    return text


def _looks_like_json(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith(("{", "["))


# ── strukturované parsery → artefakty ────────────────────────────────────


def _electrum_artifact(w: ElectrumWallet, rel_path: str | None) -> Artifact:
    """Electrum wallet → 1 artefakt (WalletDetection model, PII-safe payload)."""

    wd = WalletDetection(
        wallet_type="electrum",
        detection_basis="content_marker",
        confidence=0.95,
        encrypted=w.encrypted or None,
        version_hint=f"format={w.format_version}" + (f"/{w.keystore_type}" if w.keystore_type else ""),
        public_addresses=list(w.addresses),
    )
    details = make_detection_artifact(
        CryptoDetectionResult(wallets=[wd]), rel_path, artifact_type="crypto_wallet"
    )
    # rozšíření o K2 detaily (labely, seed/klíč metadata — bez raw hodnot)
    details["electrum"] = {
        "format_version": w.format_version,
        "keystore_type": w.keystore_type,
        "derivation_path": w.derivation_path,
        "encrypted": w.encrypted,
        "labels": dict(list(w.labels.items())[:200]),
        "seed_words_count": w.seed_words_count,
        "seed_fingerprint": w.seed_fingerprint,
        "xprv_fingerprint": w.xprv_fingerprint,
        "xpubs": list(w.xpubs),
        "seed_version_hint": w.seed_version_hint,
        "warnings": list(w.warnings),
    }
    title = f"Electrum wallet ({len(w.addresses)} adres)" + (" [šifrován]" if w.encrypted else "")
    return Artifact(
        artifact_type="crypto_wallet",
        title=title[:200],
        details=details,
        confidence=0.95,
        parser_version=CRYPTO_EXTRACT_VERSION,
    )


def _metamask_artifact(v: MetaMaskVaultData, rel_path: str | None) -> Artifact:
    """MetaMask vault → 1 artefakt (účty + KDF metadata, PII-safe)."""

    wd = WalletDetection(
        wallet_type="metamask",
        detection_basis="content_marker",
        confidence=0.95 if v.decrypted else 0.85,
        encrypted=None if v.decrypted else True,
        public_addresses=[a.address for a in v.accounts],
    )
    details = make_detection_artifact(
        CryptoDetectionResult(wallets=[wd]), rel_path, artifact_type="crypto_wallet"
    )
    details["metamask"] = {
        "kdf": v.kdf,
        "decrypted": v.decrypted,
        "accounts": [a.model_dump() for a in v.accounts[:500]],
        "warnings": list(v.warnings),
    }
    title = (
        f"MetaMask vault ({len(v.accounts)} účtů)" if v.decrypted else "MetaMask vault (šifrován)"
    )
    return Artifact(
        artifact_type="crypto_wallet",
        title=title[:200],
        details=details,
        confidence=0.95 if v.decrypted else 0.85,
        parser_version=CRYPTO_EXTRACT_VERSION,
    )


def _bitcoin_core_artifact(w: BitcoinCoreWallet, rel_path: str | None) -> Artifact:
    """Bitcoin Core wallet.dat → 1 artefakt (metadata bez raw klíčů, PII-safe)."""

    wd = WalletDetection(
        wallet_type="bitcoin_core",
        detection_basis="content_marker",
        confidence=0.95,
        encrypted=w.encrypted,  # BDB: přítomnost/absence crypted_key je definitivní
        version_hint=(
            f"bdb btree; walletversion={w.wallet_version}"
            if w.wallet_version is not None
            else "bdb btree"
        ),
        public_addresses=list(w.addresses),
    )
    details = make_detection_artifact(
        CryptoDetectionResult(wallets=[wd]), rel_path, artifact_type="crypto_wallet"
    )
    # K2.1 detaily — adresy/txid jsou on-chain (veřejná) data; labely mohou být PII → strop 200
    details["bitcoin_core"] = {
        "encrypted": w.encrypted,
        "wallet_version": w.wallet_version,
        "best_block_hash": w.best_block_hash_hex,
        "private_key_count": w.private_key_count,
        "record_count": w.record_count,
        "labels": dict(list(w.labels.items())[:200]),
        "transaction_ids": [t.hex() for t in w.transaction_ids[:500]],
        "warnings": list(w.warnings),
    }
    title = (
        f"Bitcoin Core wallet ({len(w.addresses)} adres, {len(w.transaction_ids)} transakcí)"
        + (" [šifrován]" if w.encrypted else "")
    )
    return Artifact(
        artifact_type="crypto_wallet",
        title=title[:200],
        details=details,
        confidence=0.95,
        parser_version=CRYPTO_EXTRACT_VERSION,
    )


def _exchange_artifacts(records: list[ExchangeRecord], rel_path: str | None) -> list[Artifact]:
    """Exchange záznamy → artefakty (1/record, strop CRYPTO_MAX_RECORDS)."""

    out: list[Artifact] = []
    truncated = len(records) > CRYPTO_MAX_RECORDS
    for i, rec in enumerate(records[:CRYPTO_MAX_RECORDS]):
        amt = f" {rec.amount}" if rec.amount is not None else ""
        asset = f" {rec.asset}" if rec.asset else ""
        title = f"[{rec.exchange}] {rec.record_type}{asset}{amt}".strip()[:200]
        details: dict[str, Any] = rec.model_dump(mode="json")
        if i == 0 and truncated:
            details["truncated"] = True
            details["total_records"] = len(records)
        out.append(
            Artifact(
                artifact_type="crypto_exchange_record",
                title=title or f"[{rec.exchange}] {rec.record_type}",
                timestamp=rec.timestamp,
                details=details,
                confidence=0.9 if rec.timestamp is not None else 0.6,
                parser_version=CRYPTO_EXTRACT_VERSION,
            )
        )
    return out


# ── K1 content scan (nestrukturovaný text) ───────────────────────────────


def _k1_scan(text: str) -> CryptoDetectionResult | None:
    """K1 detektory nad libovolným textem; nic nenalezeno → ``None``."""

    from stopa.domain.crypto.keys import detect_keys
    from stopa.domain.crypto.seeds import detect_in_text

    result = CryptoDetectionResult()

    # seedy + klíče → citlivý materiál (počet; raw jen jako fingerprint v K1 matchích)
    result.sensitive_materials += len(detect_keys(text))
    result.sensitive_materials += len(detect_in_text(text))

    # adresy — kandidáti tokeny, validace přes K1
    seen: set[str] = set()
    candidates: list[str] = []
    for m in _ADDR_TOKEN_RE.finditer(text):
        tok = m.group(0)
        if tok not in seen:
            seen.add(tok)
            candidates.append(tok)
    for m in _ETH_ADDR_RE.finditer(text):
        tok = m.group(0)
        if tok not in seen:
            seen.add(tok)
            candidates.append(tok)
    for cand in candidates:
        v = validate_address(cand)
        if v.status in (AddressStatus.VALID, AddressStatus.INVALID):
            result.addresses.append(v)

    # transakční reference — 64hex (BTC) / 0x+64hex (ETH txid)
    for m in _BTC_TXID_RE.finditer(text):
        result.transaction_refs.append(
            TransactionReference(raw_value=m.group(0), chain="bitcoin", is_valid_format=True)
        )
    for m in _ETH_TXID_RE.finditer(text):
        result.transaction_refs.append(
            TransactionReference(raw_value=m.group(0), chain="ethereum", is_valid_format=True)
        )

    if not (result.addresses or result.transaction_refs or result.sensitive_materials):
        return None
    return result


def _k1_artifact(result: CryptoDetectionResult, rel_path: str | None) -> Artifact:
    details = make_detection_artifact(result, rel_path)
    n_addr = len(result.addresses)
    n_mat = result.sensitive_materials
    title = f"Crypto detekce ({n_addr} adres, {n_mat} citl. materiálů)".strip()[:200]
    return Artifact(
        artifact_type="crypto_detection",
        title=title,
        details=details,
        confidence=0.85,
        parser_version=CRYPTO_EXTRACT_VERSION,
    )


# ── hlavní entry point (pipeline) ────────────────────────────────────────


def extract_crypto_artifacts(path: Path | str) -> list[Artifact]:
    """Extrahuje crypto artefakty ze souboru; žádné → ``[]``.

    Řád: Electrum JSON → MetaMask vault → exchange CSV → Bitcoin Core BDB (wallet.dat)
    → K1 text scan.
    Chyby I/O / parsování se logicky hlásí jako prázdný výsledek (defenzivní —
    crypto scan nesmí rozbít hlavní ingest).
    """

    p = Path(path)
    rel_path = str(p)
    try:
        with p.open("rb") as fh:  # bounded read — velká binárka nesmí celá do RAM
            data = fh.read(CRYPTO_MAX_BYTES)
    except OSError:
        return []
    if not data:
        return []

    text = _decode(data)

    # 1) JSON strukturované formáty (Electrum / MetaMask vault)
    if text is not None and _looks_like_json(text):
        try:
            obj = bounded_json_loads(text)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            if is_electrum_wallet(obj):
                w = parse_electrum_wallet(obj)
                if w is not None:
                    return [_electrum_artifact(w, rel_path)]
            elif is_metamask_vault(obj):
                v = parse_metamask_vault(obj)  # bez hesla — jen struktura
                if v is not None:
                    return [_metamask_artifact(v, rel_path)]

    # 2) exchange CSV (detekce podle hlavičky; bez hesla = nešifrovaný export)
    if text is not None and ("," in text[:65536] or "\t" in text[:65536]):
        parsed = parse_exchange_csv(text)
        if parsed is not None and parsed.records:
            return _exchange_artifacts(parsed.records, rel_path)

    # 2b) Bitcoin Core wallet.dat — BDB btree kontejner (binárka, magic @12 meta stránky)
    if is_bdb_btree(data):
        full = data
        try:
            size = p.stat().st_size
        except OSError:
            return []
        if CRYPTO_MAX_BYTES < size <= CRYPTO_BDB_MAX_BYTES:
            # BDB indexuje stránky od offsetu 0 — potřebujeme celý soubor, ne jen 16 MB
            try:
                with p.open("rb") as fh:
                    full = fh.read(size + 1)
            except OSError:
                return []
        elif size > CRYPTO_BDB_MAX_BYTES:
            return []  # obří soubor — nenačítat do RAM (defenzivní)
        try:
            w = parse_bitcoin_core_wallet(full)
        except BdbError:
            return []  # poškozená btree → nezařadit jako wallet artefakt
        if w is not None:
            return [_bitcoin_core_artifact(w, rel_path)]

    # 3) K1 content scan — jen reálný text do CRYPTO_TEXT_SCAN_MAX
    #    (JSON/CSV bez strukturovaného matche může obsahovat adresy v hodnotách)
    if text is not None and len(data) <= CRYPTO_TEXT_SCAN_MAX:
        result = _k1_scan(text)
        if result is not None:
            return [_k1_artifact(result, rel_path)]

    return []
