"""STOPA — K2 testy: pipeline integrace crypto extraktoru.

Pokrytí: name-based dispatch (``is_crypto_candidate_file`` + registry),
fallback content scan, profile flag ``crypto_scan``, artefakty z souborů
(Electrum/MetaMask/exchange CSV/K1 sken), limity velikostí a počtu záznamů.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from stopa.artifacts.crypto_extract import (
    CRYPTO_EXTRACT_VERSION,
    extract_crypto_artifacts,
    is_crypto_candidate_file,
)
from stopa.domain.profiles import get_profile
from stopa.domain.validation_registry import PARSER_VALIDATIONS, build_registry
from stopa.models import ProcessingProfile
from stopa.pipeline import (
    NAME_BASED_EXTRACTORS,
    _extract_artifacts_for,
    _name_based_match,
)

# ── vzorová data ─────────────────────────────────────────────────────────

WIF_KEY = "KwDiBf89QgGbjEhKnhXJuH7LrciVrZi3qYjgd9M7rU76FA5"
BTC_ADDR = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"  # BIP-173 P2WPKH
ETH_ADDR = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"  # ERC-55 kanonický

MODERN_WALLET: dict[str, Any] = {
    "keystore": {
        "type": "bip32",
        "xprv": "L4rK1yDtCWekvXuE6oXD9exCYwF5ERcQxkDnJxhxfmGVUW5aPJuM",
        "derivation_path": "m/44'/60'/0'",
    },
    "addresses": {"0xAbC123": 0},
}

LEGACY_WALLET: dict[str, Any] = {
    "seed": (
        "abandon abandon abandon abandon abandon abandon abandon abandon "
        "abandon abandon about"
    ),
    "addresses": {"1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa": ""},
}

BINANCE_CSV = (
    "Time,Asset,Amount,Address,TxHash\n"
    "2016-06-03T12:04:39Z,BTC,0.5,1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa," + "a" * 64 + "\n"
    "2016-07-01T08:30:00Z,ETH,1.25,0xAbCdef0123456789abcdef0123456789ABCDEF01," + "b" * 64 + "\n"
)

METAMASK_VAULT: dict[str, Any] = {
    # struktura bez platného ciphertextu stačí pro strukturální detekci (bez hesla)
    "dat": "A" * 80,
    "dkty": "scrypt",
    "kdfparams": {"dklen": 32, "n": 1024},
    "salt": "c2FsdC0xMjM0NTY3ODkw",
}

K1_SCAN_TEXT = (
    f"notes with secrets: {WIF_KEY}\n"
    f"btc: {BTC_ADDR}\n"
    f"eth: {ETH_ADDR}\n"
    f"txids: {'c' * 64} and 0x{'d' * 64}\n"
)


# ── name-based gate ─────────────────────────────────────────────────────

class TestIsCryptoCandidateFile:
    @pytest.mark.parametrize(
        "name",
        [
            "deposits.csv",
            "withdrawals.csv",
            "trades_export.json",
            "default_wallet",  # bez přípony — klíčové slovo
            "metamask_vault.json",
            "electrum_backup",
            ".electrum/wallets/default_wallet",  # cesta s .electrum segmentem
        ],
    )
    def test_positive(self, name: str) -> None:
        assert is_crypto_candidate_file(name)

    @pytest.mark.parametrize(
        "name", ["notes.txt", "photo.jpg", "contacts.cpbr", "", "random.bin"]
    )
    def test_negative(self, name: str) -> None:
        assert not is_crypto_candidate_file(name)


class TestNameBasedMatchDispatch:
    @pytest.mark.parametrize(
        "name", ["deposits.csv", "default_wallet", ".electrum/wallets/default_wallet"]
    )
    def test_routes_to_crypto_extract(self, name: str) -> None:
        assert _name_based_match(name) == NAME_BASED_EXTRACTORS["crypto_extract"]

    def test_existing_rules_take_priority(self) -> None:
        # sim_tpdu má vlastní pravidlo — nesmí ho crypto gate přepsat
        match = _name_based_match("contacts.cpbr")
        assert match is not None and match != NAME_BASED_EXTRACTORS["crypto_extract"]

    def test_unknown_name_no_match(self) -> None:
        assert _name_based_match("notes.txt") is None


# ── artefakty přímo z extraktoru (bez pipeline sandboxu) ────────────────

class TestExtractElectrumFile:
    def test_modern_wallet_artifact(self, tmp_path: Path) -> None:
        f = tmp_path / "default_wallet"
        f.write_text(json.dumps(MODERN_WALLET), encoding="utf-8")
        arts = extract_crypto_artifacts(f)
        assert len(arts) == 1
        art = arts[0]
        assert art.artifact_type == "crypto_wallet"
        assert art.parser_version == CRYPTO_EXTRACT_VERSION
        assert art.title is not None and "Electrum wallet (1 adres)" in art.title
        det = art.details["electrum"]
        assert det["format_version"] == "modern"
        assert det["derivation_path"] == "m/44'/60'/0'"
        wallets = art.details["wallets"]
        assert len(wallets) == 1 and wallets[0]["public_addresses"] == ["0xAbC123"]

    def test_legacy_wallet_seed_fingerprint(self, tmp_path: Path) -> None:
        f = tmp_path / "legacy_wallet"
        f.write_text(json.dumps(LEGACY_WALLET), encoding="utf-8")
        arts = extract_crypto_artifacts(f)
        assert len(arts) == 1
        det = arts[0].details["electrum"]
        assert det["format_version"] == "legacy"
        assert det.get("seed_fingerprint")

    def test_non_wallet_json_no_structure(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text('{"x": 1}', encoding="utf-8")  # bez čárek → žádný CSV ani K1 nálezy
        assert extract_crypto_artifacts(f) == []


class TestExtractMetaMaskFile:
    def test_encrypted_structure_only(self, tmp_path: Path) -> None:
        f = tmp_path / "vault.json"
        f.write_text(json.dumps(METAMASK_VAULT), encoding="utf-8")
        arts = extract_crypto_artifacts(f)
        assert len(arts) == 1
        art = arts[0]
        assert art.title is not None and "(šifrován)" in art.title
        det = art.details["metamask"]
        assert det["decrypted"] is False and det["kdf"] == "scrypt"


class TestExtractExchangeCsvFile:
    def test_binance_deposits_artifacts(self, tmp_path: Path) -> None:
        f = tmp_path / "deposits.csv"
        f.write_text(BINANCE_CSV, encoding="utf-8")
        arts = extract_crypto_artifacts(f)
        assert len(arts) == 2
        art = arts[0]
        assert art.artifact_type == "crypto_exchange_record"
        assert art.parser_version == CRYPTO_EXTRACT_VERSION
        det = art.details
        assert det["exchange"] == "binance"
        assert det["kind"] == "binance_deposits"
        assert det["record_type"] == "deposit"
        assert det["asset"] == "BTC"
        assert det["amount"] == pytest.approx(0.5)
        assert art.timestamp is not None
        assert art.confidence == 0.9

    def test_tsv_variant(self, tmp_path: Path) -> None:
        f = tmp_path / "funds.tsv"
        f.write_text("Time\tAsset\tAmount\n2016-06-03T12:04:39Z\tBTC\t0.5\n", encoding="utf-8")
        arts = extract_crypto_artifacts(f)
        assert len(arts) == 1 and arts[0].details["amount"] == pytest.approx(0.5)

    def test_max_records_truncation(self, tmp_path: Path) -> None:
        rows = "".join(
            f"2016-06-03T{i % 24:02d}:00:00Z,BTC,0.5,addr,{i:064x}\n" for i in range(20_001)
        )
        f = tmp_path / "big.csv"
        f.write_text("Time,Asset,Amount,Address,TxHash\n" + rows, encoding="utf-8")
        arts = extract_crypto_artifacts(f)
        assert len(arts) == 20_000
        assert arts[0].details.get("truncated") is True
        assert arts[0].details.get("total_records") == 20_001


# ── K1 content scan fallback ───────────────────────────────────────────

class TestK1ContentScan:
    def test_secrets_and_addresses_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.txt"
        f.write_text(K1_SCAN_TEXT, encoding="utf-8")
        arts = extract_crypto_artifacts(f)
        assert len(arts) == 1
        art = arts[0]
        assert art.artifact_type == "crypto_detection"
        det = art.details
        assert det["sensitive_material_count"] >= 1  # WIF klíč
        assert det["address_count"] >= 2  # BTC + ETH adresa
        refs = {r["raw_value"] for r in det["transaction_refs"]}
        assert "c" * 64 in refs and f"0x{'d' * 64}" in refs

    def test_binary_file_no_artifacts(self, tmp_path: Path) -> None:
        f = tmp_path / "blob.bin"
        f.write_bytes(b"\x00\x01\x02" + b"WIFkeyhere" + b"\x00" * 50)
        assert extract_crypto_artifacts(f) == []

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        assert extract_crypto_artifacts(f) == []

    def test_oversized_unstructured_skips_k1_scan(self, tmp_path: Path) -> None:
        # 5 MiB bez čárek — přes CRYPTO_TEXT_SCAN_MAX (4 MiB) → K1 sken vynechán
        f = tmp_path / "big.txt"
        with f.open("w", encoding="utf-8") as fh:
            fh.write("x" * (5 * 1024 * 1024))
        assert extract_crypto_artifacts(f) == []

    def test_key_in_head_but_file_oversized(self, tmp_path: Path) -> None:
        # dokumentované omezení: limit se kontroluje na celé velikosti souboru
        f = tmp_path / "big2.txt"
        with f.open("w", encoding="utf-8") as fh:
            fh.write(WIF_KEY + "\n")
            fh.write("y" * (5 * 1024 * 1024))
        assert extract_crypto_artifacts(f) == []


# ── pipeline dispatch (signatura → name-based → fallback) ───────────────

class TestExtractArtifactsForDispatch:
    def test_name_based_csv_uses_crypto_extractor(self, tmp_path: Path) -> None:
        f = tmp_path / "deposits.csv"
        f.write_text(BINANCE_CSV, encoding="utf-8")
        arts, version = _extract_artifacts_for(f, None)
        assert len(arts) == 2 and version == CRYPTO_EXTRACT_VERSION

    def test_fallback_content_scan(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.txt"
        f.write_text(K1_SCAN_TEXT, encoding="utf-8")
        arts, version = _extract_artifacts_for(f, None)
        assert len(arts) >= 1 and version == CRYPTO_EXTRACT_VERSION

    def test_crypto_scan_flag_off(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.txt"
        f.write_text(K1_SCAN_TEXT, encoding="utf-8")
        arts, version = _extract_artifacts_for(f, None, crypto_scan=False)
        assert arts == [] and version is None

    def test_unknown_binary_fallback_returns_version(self, tmp_path: Path) -> None:
        # fallback běží i na binárce (→ []) — verze se eviduje stejně jako u
        # ostatních cizích souborů v name-based režimu
        f = tmp_path / "random.bin"
        f.write_bytes(b"\x00" * 64)
        arts, version = _extract_artifacts_for(f, None)
        assert arts == [] and version == CRYPTO_EXTRACT_VERSION


# ── registry + profily ─────────────────────────────────────────────────

class TestRegistryAndProfiles:
    def test_parser_validations_contains_crypto_extract(self) -> None:
        entry = PARSER_VALIDATIONS["crypto_extract"]
        assert "Electrum" in " ".join(entry.formats)
        assert any("PII" in limitation or "fingerprint" in limitation for limitation in entry.limitations)

    def test_build_registry_version_synced(self) -> None:
        reg = build_registry()
        assert "crypto_extract" in reg
        assert reg["crypto_extract"].version == CRYPTO_EXTRACT_VERSION

    def test_profile_defaults_crypto_scan_on(self) -> None:
        profile = ProcessingProfile(name="test")
        assert profile.crypto_scan is True

    @pytest.mark.parametrize("name", ["forensic", "ediscovery", "quick"])
    def test_builtin_profiles_have_crypto_scan(self, name: str) -> None:
        # flag má default True — všechny vestavěné profily ho dědí
        assert get_profile(name).crypto_scan is True
