"""STOPA — K2.1 testy: Bitcoin Core wallet.dat parser (BDB btree).

Pokrytí:
- čistá BDB čtečka (``domain.crypto.bdb``) na libdb-5.3 fixturech (small/big):
  přesné KV obsahy, pořadí záznamů, overflow řetězec, strukturní chyby;
- doménový parser ``parse_bitcoin_core_wallet``: adresy/labely/transakce,
  detekce šifrování (crypted_key), walletversion/bestblock, heuristika CKey;
- pipeline vrstva ``extract_crypto_artifacts``: E2E artefakt, obsahová detekce
  nezávislá na názvu souboru, defenzivní chování u poškozené btree.

Fixture (``tests/data/wallet_*.dat``) generuje C program proti libdb-5.3 —
ground truth odpovídá reálnému Bitcoin Core layoutu klíčů v BDB.
"""

from __future__ import annotations

import shutil
import struct
from pathlib import Path

import pytest

from stopa.artifacts.crypto_extract import extract_crypto_artifacts
from stopa.domain.crypto.bdb import BdbError, bdb_meta, is_bdb_btree, parse_bdb_btree
from stopa.domain.crypto.wallets import parse_bitcoin_core_wallet

DATA_DIR = Path(__file__).parent / "data"
SMALL = DATA_DIR / "wallet_small.dat"
BIG = DATA_DIR / "wallet_big.dat"

# očekávané hodnoty — přesně odpovídají generátoru fixture (gen_wallet_fixture.c)
GENESIS_ADDR = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
ADDR_EMPTY_LABEL = "1BvBMSEYstWetqFn59p5aiPhTCKMydQ2hwm"
TXID_BYTES = bytes(i * 7 for i in range(32))
BESTBLOCK = bytes(0xAB ^ i for i in range(32))
CRYPTED_KEY_VAL = bytes(i * 3 for i in range(64))
WALLET_VERSION_LE = struct.pack("<I", 129900)


def _records(path: Path) -> list[tuple[bytes, bytes]]:
    return parse_bdb_btree(path.read_bytes())


# ── BDB čtečka — small fixture (jeden leaf, 6 záznamů) ───────────────


class TestBdbSmallFixture:
    def test_meta(self):
        data = SMALL.read_bytes()
        assert is_bdb_btree(data[:512])
        meta = bdb_meta(data)
        assert meta["pagesize"] == 4096
        assert meta["root_pgno"] == 1
        assert meta["encrypt_alg"] is None

    def test_record_count_and_order(self):
        recs = _records(SMALL)
        assert len(recs) == 6
        keys = [k for k, _ in recs]
        # bytové lexikografické pořadí stromu (C cursor ground truth)
        assert keys[0] == b"bestblock"
        assert keys[1] == b"crypted_key"
        assert keys[2] == b"name:" + GENESIS_ADDR.encode()
        assert keys[3] == b"name:" + ADDR_EMPTY_LABEL.encode()
        assert keys[4] == b"tx" + TXID_BYTES
        assert keys[5] == b"walletversion"

    def test_values_exact(self):
        recs = dict(_records(SMALL))
        assert recs[b"bestblock"] == BESTBLOCK
        assert recs[b"crypted_key"] == CRYPTED_KEY_VAL
        assert recs[b"name:" + GENESIS_ADDR.encode()] == b"Miner reward"
        # prázdný label — platný Bitcoin Core záznam (adresa bez popisku)
        assert recs[b"name:" + ADDR_EMPTY_LABEL.encode()] == b""
        assert recs[b"walletversion"] == WALLET_VERSION_LE

    def test_tx_value_ctxoutref(self):
        recs = dict(_records(SMALL))
        val = recs[b"tx" + TXID_BYTES]
        # CTxOutRef: prevhash(32) + n(4B) + varint sats + script_len + OP_DUP
        assert len(val) == 42
        assert val[:32] == bytes(0x5A ^ i for i in range(32))
        assert val[32:36] == b"\x00\x00\x00\x01"  # n — přesně dle fixture
        assert val[36:40] == (50_000_000).to_bytes(4, "little")


# ── BDB čtečka — big fixture (internal pages + overflow) ───────────────


class TestBdbBigFixture:
    def test_record_count(self):
        assert len(_records(BIG)) == 601

    def test_all_name_records_present(self):
        recs = dict(_records(BIG))
        for i in range(600):
            assert recs[f"name:addr{i}".encode()] == f"label-{i}".encode()

    def test_overflow_value_exact(self):
        """3 kB value přesahuje jednu stránku → overflow řetězec (tlen + next_pgno)."""
        recs = dict(_records(BIG))
        assert recs[b"bigvalue"] == bytes(i & 0xFF for i in range(3072))


# ── BDB čtečka — strukturní chyby a gate ───────────────────────────────


class TestBdbErrors:
    def test_gate_rejects_short_data(self):
        assert not is_bdb_btree(b"")
        assert not is_bdb_btree(b"\x00" * 100)

    def test_gate_rejects_non_btree(self):
        data = SMALL.read_bytes()
        bad_magic = bytearray(data[:512])
        bad_magic[12:16] = b"XXXX"
        assert not is_bdb_btree(bytes(bad_magic))
        bad_version = bytearray(data[:512])
        struct.pack_into("<I", bad_version, 16, 8)  # jiná verze
        assert not is_bdb_btree(bytes(bad_version))

    def test_truncated_to_one_page(self):
        with pytest.raises(BdbError):
            parse_bdb_btree(SMALL.read_bytes()[:4096])

    def test_length_not_multiple_of_pagesize(self):
        with pytest.raises(BdbError):
            parse_bdb_btree(SMALL.read_bytes()[:5000])

    def test_root_out_of_range(self):
        data = bytearray(SMALL.read_bytes())
        struct.pack_into("<I", data, 88, 7)  # root pgno mimo rozsah
        with pytest.raises(BdbError, match="root"):
            parse_bdb_btree(bytes(data))

    def test_unexpected_page_type(self):
        data = bytearray(SMALL.read_bytes())
        data[4096 + 25] = 7  # leaf → overflow typ
        with pytest.raises(BdbError, match="typ stránky"):
            parse_bdb_btree(bytes(data))


# ── doménový parser BitcoinCoreWallet ───────────────────────────────────


class TestParseBitcoinCoreWallet:
    def test_small_encrypted_wallet(self):
        w = parse_bitcoin_core_wallet(SMALL.read_bytes())
        assert w is not None
        assert w.encrypted is True  # crypted_key přítomen
        assert w.addresses == [GENESIS_ADDR, ADDR_EMPTY_LABEL]
        assert w.labels == {GENESIS_ADDR: "Miner reward", ADDR_EMPTY_LABEL: ""}
        assert w.transaction_ids == [TXID_BYTES]
        assert w.wallet_version == 129900
        assert w.best_block_hash_hex == BESTBLOCK.hex()
        assert w.private_key_count == 0
        assert w.record_count == 6
        assert any("crypted_key" in x for x in w.warnings)

    def test_big_unencrypted_wallet(self):
        w = parse_bitcoin_core_wallet(BIG.read_bytes())
        assert w is not None
        assert w.encrypted is False
        assert len(w.addresses) == 600
        assert set(w.labels) == {f"addr{i}" for i in range(600)}
        for name, label in w.labels.items():
            assert label == f"label-{int(name[4:])}"
        assert w.transaction_ids == []
        assert w.wallet_version is None
        assert w.record_count == 601

    def test_non_bitcoin_btree_returns_none(self, monkeypatch):
        import stopa.domain.crypto.wallets as wallets_mod

        monkeypatch.setattr(wallets_mod, "parse_bdb_btree", lambda data: [(b"foo", b"bar")])
        assert parse_bitcoin_core_wallet(b"\x00" * 4096) is None

    def test_structural_error_propagates(self, monkeypatch):
        import stopa.domain.crypto.wallets as wallets_mod

        def boom(data: bytes) -> list[tuple[bytes, bytes]]:
            raise BdbError("poškozená stránka")

        monkeypatch.setattr(wallets_mod, "parse_bdb_btree", boom)
        with pytest.raises(BdbError):
            parse_bitcoin_core_wallet(SMALL.read_bytes())


# ── pipeline E2E (extract_crypto_artifacts) ─────────────────────────────


class TestPipelineE2E:
    def test_small_wallet_dat(self, tmp_path: Path):
        target = tmp_path / "wallet.dat"
        shutil.copy(SMALL, target)
        arts = extract_crypto_artifacts(target)
        assert len(arts) == 1
        a = arts[0]
        assert a.artifact_type == "crypto_wallet"
        assert a.title == "Bitcoin Core wallet (2 adres, 1 transakcí) [šifrován]"
        bc = a.details["bitcoin_core"]
        assert bc["encrypted"] is True
        assert bc["wallet_version"] == 129900
        assert bc["best_block_hash"] == BESTBLOCK.hex()
        assert bc["labels"] == {GENESIS_ADDR: "Miner reward", ADDR_EMPTY_LABEL: ""}
        assert bc["transaction_ids"] == [TXID_BYTES.hex()]
        assert bc["record_count"] == 6
        # detekční model nese veřejné adresy + verzi
        wallet = a.details["wallets"][0]
        assert wallet["wallet_type"] == "bitcoin_core"
        assert wallet["encrypted"] is True
        assert set(wallet["public_addresses"]) == {GENESIS_ADDR, ADDR_EMPTY_LABEL}
        assert "129900" in (wallet["version_hint"] or "")

    def test_big_wallet_content_based_detection(self, tmp_path: Path):
        """Jméno souboru není wallet.dat — detekce čistě podle obsahu (BDB magic)."""
        target = tmp_path / "mydata.bin"
        shutil.copy(BIG, target)
        arts = extract_crypto_artifacts(target)
        assert len(arts) == 1
        bc = arts[0].details["bitcoin_core"]
        assert bc["encrypted"] is False
        assert bc["record_count"] == 601
        assert "šifrován" not in (arts[0].title or "")

    def test_non_bdb_binary_returns_empty(self, tmp_path: Path):
        target = tmp_path / "wallet.dat"
        target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 600)
        assert extract_crypto_artifacts(target) == []

    def test_corrupted_btree_returns_empty(self, tmp_path: Path):
        """Poškozená btree → BdbError zachycena → crypto scan nerozbije ingest."""
        target = tmp_path / "wallet.dat"
        data = bytearray(SMALL.read_bytes())
        struct.pack_into("<I", data, 88, 99)  # root mimo rozsah
        target.write_bytes(bytes(data))
        assert extract_crypto_artifacts(target) == []
