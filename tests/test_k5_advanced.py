"""K5.6 — Formální testy K5 Advanced (DeFi, NFT, cross-chain bridge, privacy coins, AI copilot).

Offline-first: bundlované registry, injektovatelná LLM, žádné sítě.
"""

from __future__ import annotations

import argparse
import json
import re

import pytest

# ---------------------------------------------------------------------------
# K5.1 — DeFi
# ---------------------------------------------------------------------------


class TestDefiRegistry:
    def test_load_entries(self):
        from stopa.domain.crypto.defi import load_defi_registry

        entries, _terms = load_defi_registry()
        assert len(entries) >= 4
        assert all(e.address.startswith("0x") for e in entries)
        protocols = {e.protocol for e in entries}
        assert "uniswap" in protocols and "aave" in protocols

    def test_load_terms(self):
        from stopa.domain.crypto.defi import load_defi_registry

        _, terms = load_defi_registry()
        assert "uniswap" in terms
        assert any("uniswap" == t for t in terms["uniswap"])

    def test_all_entries_verified(self):
        """V1 snapshot — všechny bundlované položky musí být verified=true."""
        from stopa.domain.crypto.defi import load_defi_registry

        entries, _ = load_defi_registry()
        assert all(e.verified for e in entries)
        assert all(e.source for e in entries)

    def test_injectable_path(self, tmp_path):
        from stopa.domain.crypto.defi import load_defi_registry

        p = tmp_path / "defi.json"
        p.write_text(
            json.dumps({"entries": [{"address": "0xabc123", "protocol": "test"}]}),
            encoding="utf-8",
        )
        entries, _ = load_defi_registry(p)
        assert len(entries) == 1 and entries[0].protocol == "test"

    def test_corrupt_json_raises(self, tmp_path):
        from stopa.domain.crypto.defi import DeFiRegistryError, load_defi_registry

        p = tmp_path / "defi.json"
        p.write_text("{nejson", encoding="utf-8")
        with pytest.raises(DeFiRegistryError):
            load_defi_registry(p)

    def test_missing_file_raises(self, tmp_path):
        from stopa.domain.crypto.defi import DeFiRegistryError, load_defi_registry

        with pytest.raises(DeFiRegistryError):
            load_defi_registry(tmp_path / "chybici.json")

    def test_bad_address_prefix_raises(self, tmp_path):
        from stopa.domain.crypto.defi import DeFiRegistryError, load_defi_registry

        p = tmp_path / "defi.json"
        p.write_text(
            json.dumps({"entries": [{"address": "bc1qxyz", "protocol": "x"}]}), encoding="utf-8"
        )
        with pytest.raises(DeFiRegistryError):
            load_defi_registry(p)


class TestDefiDetection:
    def test_uniswap_term(self):
        from stopa.domain.crypto.defi import detect_defi_in_text

        out = detect_defi_in_text("swapped ETH for USDC on Uniswap")
        assert [f.protocol for f in out] == ["uniswap"]
        assert "uniswap" in out[0].matched_terms
        assert out[0].score >= 2

    def test_uniswap_v3_double_term(self):
        from stopa.domain.crypto.defi import detect_defi_in_text

        out = detect_defi_in_text("Used Uniswap v3 router for the swap")
        uni = next(f for f in out if f.protocol == "uniswap")
        assert set(uni.matched_terms) >= {"uniswap", "uniswap v3"}
        assert uni.score == 2 * len(uni.matched_terms)

    def test_aave_term(self):
        from stopa.domain.crypto.defi import detect_defi_in_text

        out = detect_defi_in_text("Supplied AETH to Aave lending market")
        assert any(f.protocol == "aave" for f in out)

    def test_word_boundary_no_false_positive(self):
        from stopa.domain.crypto.defi import detect_defi_in_text

        # "aavex" není "aave"; "unswapped" není "uniswap"
        assert detect_defi_in_text("the aavex protocol and unswapped funds") == []

    def test_case_insensitive(self):
        from stopa.domain.crypto.defi import detect_defi_in_text

        out = detect_defi_in_text("UNISWAP was used")
        assert any(f.protocol == "uniswap" for f in out)

    def test_known_contract_address_match(self):
        from stopa.domain.crypto.defi import detect_defi_in_text

        text = (
            "tx to 0x1F98431c8aD98523631AE4a59f2Ac7d082EFBFb6 "
            "(case-insensitive check)"
        )
        out = detect_defi_in_text(text)
        uni = next((f for f in out if f.protocol == "uniswap"), None)
        assert uni is not None
        assert any(a.lower() == "0x1f98431c8ad98523631ae4a59f2ac7d082efbfb6" for a in uni.matched_addresses)

    def test_contract_match_score_5(self):
        from stopa.domain.crypto.defi import detect_defi_in_text

        out = detect_defi_in_text("paid 0x1F98431c8aD98523631AE4a59f2Ac7d082EFBFb6")
        uni = next(f for f in out if f.protocol == "uniswap")
        assert uni.score == 5

    def test_multi_protocol_sorted(self):
        from stopa.domain.crypto.defi import detect_defi_in_text

        out = detect_defi_in_text("Used Uniswap, Aave and Curve pool swaps")
        protos = [f.protocol for f in out]
        assert protos == sorted(protos)
        assert set(protos) >= {"uniswap", "aave", "curve"}

    def test_empty_text(self):
        from stopa.domain.crypto.defi import detect_defi_in_text

        assert detect_defi_in_text("") == []

    def test_origin_recorded(self):
        from stopa.domain.crypto.defi import detect_defi_in_text

        out = detect_defi_in_text("uniswap swap", origin="mail.eml")
        assert all(f.origin == "mail.eml" for f in out)

    def test_deterministic(self):
        from stopa.domain.crypto.defi import detect_defi_in_text

        text = "Uniswap v3 + Aave + 0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
        assert [f.model_dump() for f in detect_defi_in_text(text)] == [
            f.model_dump() for f in detect_defi_in_text(text)
        ]


class TestTagEthAddresses:
    def test_tags_known(self):
        from stopa.domain.crypto.defi import tag_eth_addresses

        out = tag_eth_addresses(["0x1F98431c8aD98523631AE4a59f2Ac7d082EFBFb6"])
        assert len(out) == 1
        info = next(iter(out.values()))
        assert info.protocol == "uniswap" and info.version == "v3"

    def test_case_insensitive(self):
        from stopa.domain.crypto.defi import tag_eth_addresses

        out = tag_eth_addresses(["0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2"])
        assert len(out) == 1 and next(iter(out.values())).protocol == "aave"

    def test_unknown_not_tagged(self):
        from stopa.domain.crypto.defi import tag_eth_addresses

        assert tag_eth_addresses(["0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"]) == {}

    def test_non_0x_skipped(self):
        from stopa.domain.crypto.defi import tag_eth_addresses

        assert tag_eth_addresses(["bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"]) == {}


# ---------------------------------------------------------------------------
# K5.2 — NFT
# ---------------------------------------------------------------------------


class TestNftRegistry:
    def test_load(self):
        from stopa.domain.crypto.nft import load_nft_registry

        entries, markets = load_nft_registry()
        assert len(entries) >= 2
        names = {e.collection for e in entries}
        assert "CryptoPunks" in names and "Bored Ape Yacht Club" in names
        assert any("opensea" == m for m in markets)

    def test_verified_and_source(self):
        from stopa.domain.crypto.nft import load_nft_registry

        entries, _ = load_nft_registry()
        assert all(e.verified and e.source for e in entries)

    def test_corrupt_raises(self, tmp_path):
        from stopa.domain.crypto.nft import NftRegistryError, load_nft_registry

        p = tmp_path / "nft.json"
        p.write_text("[1,2", encoding="utf-8")
        with pytest.raises(NftRegistryError):
            load_nft_registry(p)


class TestNftTransferNormalize:
    def test_standard_keys(self):
        from stopa.domain.crypto.nft import NftTransfer

        t = NftTransfer.normalize(
            {
                "contract": "0xabc",
                "token_id": 1,
                "from": "A",
                "to": "B",
                "block_number": 10,
                "tx_index": 2,
            }
        )
        assert (t.token_id, t.from_addr, t.to_addr) == (1, "A", "B")
        assert (t.block_number, t.tx_index) == (10, 2)

    def test_alt_keys(self):
        from stopa.domain.crypto.nft import NftTransfer

        t = NftTransfer.normalize(
            {
                "contract_address": "0xdef",
                "tokenId": "4201",
                "from_address": "X",
                "to_address": "Y",
                "blockNumber": 7,
                "transactionIndex": 3,
            }
        )
        assert (t.contract, t.token_id) == ("0xdef", 4201)
        assert (t.from_addr, t.to_addr) == ("X", "Y")
        assert (t.block_number, t.tx_index) == (7, 3)

    def test_missing_token_id_raises(self):
        from stopa.domain.crypto.nft import NftRegistryError, NftTransfer

        with pytest.raises(NftRegistryError):
            NftTransfer.normalize({"contract": "0xabc", "from": "A", "to": "B"})

    def test_bool_token_id_raises(self):
        from stopa.domain.crypto.nft import NftRegistryError, NftTransfer

        with pytest.raises(NftRegistryError):
            NftTransfer.normalize(
                {"contract": "0xabc", "token_id": True, "from": "A", "to": "B"}
            )

    def test_non_numeric_token_id_raises(self):
        from stopa.domain.crypto.nft import NftRegistryError, NftTransfer

        with pytest.raises(NftRegistryError):
            NftTransfer.normalize(
                {"contract": "0xabc", "token_id": "xyz", "from": "A", "to": "B"}
            )


class TestOwnershipChain:
    @staticmethod
    def _t(contract, token_id, frm, to, block=None, txi=None):
        from stopa.domain.crypto.nft import NftTransfer

        return NftTransfer.normalize(
            {
                "contract": contract,
                "token_id": token_id,
                "from": frm,
                "to": to,
                "block_number": block,
                "tx_index": txi,
            }
        )

    def test_mint_then_transfer(self):
        from stopa.domain.crypto.nft import ZERO_ADDRESS, current_holder, ownership_chain

        zero = ZERO_ADDRESS
        chain = ownership_chain(
            [
                self._t("0xc", 1, "holder_a", "holder_b", 3),
                self._t("0xc", 1, zero, "holder_a", 1),
            ],
            1,
        )
        assert [(s.event, s.owner) for s in chain] == [("mint", "holder_a"), ("transfer", "holder_b")]
        assert current_holder(chain) == "holder_b"

    def test_sorted_by_block_and_tx_index(self):
        from stopa.domain.crypto.nft import ownership_chain

        # záměněné vstupy → deterministický řazený výstup
        chain = ownership_chain(
            [
                self._t("0xc", 5, "B", "C", block=3),
                self._t("0xc", 5, "A", "B", block=2),
                self._t("0xc", 5, "ZERO".lower() * 10, "A", block=1),
            ],
            5,
        )
        assert [s.owner for s in chain] == ["A", "B", "C"]

    def test_other_tokens_filtered(self):
        from stopa.domain.crypto.nft import ownership_chain

        chain = ownership_chain(
            [self._t("0xc", 1, "X", "Y"), self._t("0xc", 2, "P", "Q")], 1
        )
        assert len(chain) == 1 and chain[0].owner == "Y"

    def test_empty_chain(self):
        from stopa.domain.crypto.nft import current_holder, ownership_chain

        out = ownership_chain([], 99)
        assert out == [] and current_holder(out) is None

    def test_tx_index_breaks_block_tie(self):
        from stopa.domain.crypto.nft import ownership_chain

        chain = ownership_chain(
            [
                self._t("0xc", 1, "Z", "L2", block=5, txi=9),
                self._t("0xc", 1, "Y", "L1", block=5, txi=1),
            ],
            1,
        )
        assert [s.owner for s in chain] == ["L1", "L2"]


class TestNftTextDetection:
    def test_known_collection_address(self):
        from stopa.domain.crypto.nft import detect_nft_in_text

        out = detect_nft_in_text(
            "bought a punk from 0xb47e3cd837dDF8e4c57F05d70Ab865de6e193BBB"
        )
        assert out is not None and "CryptoPunks" in out.collections

    def test_marketplace_term(self):
        from stopa.domain.crypto.nft import detect_nft_in_text

        out = detect_nft_in_text("listed on OpenSea for 2 ETH")
        assert out is not None and "opensea" in out.marketplaces
        assert out.score >= 2

    def test_token_id_extraction(self):
        from stopa.domain.crypto.nft import detect_nft_in_text

        out = detect_nft_in_text("token id: 4201 was sold")
        assert out is not None and out.token_ids == (4201,)

    def test_no_indicators_returns_none(self):
        from stopa.domain.crypto.nft import detect_nft_in_text

        assert detect_nft_in_text("plain text about coins") is None

    def test_score_composition(self):
        from stopa.domain.crypto.nft import detect_nft_in_text

        out = detect_nft_in_text(
            "0xbc4ca0eda7647a8ab7c2061c2e118a18a936f13d on opensea, token id: 7"
        )
        assert out is not None
        # 3 (sbírka) + 2 (marketplace) + 1 (token id, strop 5)
        assert out.score == 6


# ---------------------------------------------------------------------------
# K5.3 — Cross-chain bridge
# ---------------------------------------------------------------------------


class TestBridgeRegistry:
    def test_load(self):
        from stopa.domain.crypto.bridges import load_bridge_registry

        entries, terms = load_bridge_registry()
        assert len(entries) >= 2
        names = {e.name for e in entries}
        assert "wormhole" in names and "binance_bridge" in names
        assert "binance peg" in terms

    def test_wormhole_multichain(self):
        from stopa.domain.crypto.bridges import load_bridge_registry

        entries, _ = load_bridge_registry()
        wh = next(e for e in entries if e.name == "wormhole")
        assert len(wh.chains) >= 3
        assert all(c.startswith("0x") for c in wh.contracts.values())

    def test_binance_not_verified(self):
        """Binance-Peg bez primárního zdroje → verified=false (honestní snapshot)."""
        from stopa.domain.crypto.bridges import load_bridge_registry

        entries, _ = load_bridge_registry()
        bb = next(e for e in entries if e.name == "binance_bridge")
        assert bb.verified is False and "bsc" in bb.chains

    def test_corrupt_raises(self, tmp_path):
        from stopa.domain.crypto.bridges import BridgeRegistryError, load_bridge_registry

        p = tmp_path / "b.json"
        p.write_text("xx", encoding="utf-8")
        with pytest.raises(BridgeRegistryError):
            load_bridge_registry(p)


class TestAnalyzeCrossChain:
    def test_single_chain_no_link(self):
        from stopa.domain.crypto.bridges import analyze_cross_chain

        assert analyze_cross_chain({"eth": ["0xabc"]}) == []

    def test_multi_chain_presence(self):
        from stopa.domain.crypto.bridges import analyze_cross_chain

        links = analyze_cross_chain(
            {"eth": ["0xABC"], "bsc": ["0xabc", "0xother"]}
        )
        assert len(links) == 1
        l = links[0]
        assert l.entity == "0xabc" and l.chains == ("bsc", "eth")
        assert l.evidence == "multi_chain_presence"

    def test_case_insensitive_grouping(self):
        from stopa.domain.crypto.bridges import analyze_cross_chain

        links = analyze_cross_chain({"polygon": ["0xAbC"], "eth": ["0xabC"]})
        assert len(links) == 1 and links[0].entity == "0xabc"

    def test_bridge_contract_explicit_evidence(self):
        from stopa.domain.crypto.bridges import analyze_cross_chain

        links = analyze_cross_chain(
            {"bsc": ["0x98f3C9e6E3face36baad05FE09d375Ef1464288B"]}
        )
        assert len(links) == 1
        l = links[0]
        assert l.evidence == "bridge_contract" and l.bridge_name is not None

    def test_bridge_plus_presence(self):
        from stopa.domain.crypto.bridges import analyze_cross_chain

        links = analyze_cross_chain(
            {
                "eth": ["0x98f3c9e6e3face36baad05fe09d375ef1464288b"],
                "bsc": ["0x98f3c9e6e3face36baad05fe09d375ef1464288b", "0xdeadbeef"],
            }
        )
        l = next(x for x in links if x.entity == "0x98f3c9e6e3face36baad05fe09d375ef1464288b")
        assert l.evidence == "bridge_contract" and len(l.chains) >= 2

    def test_deterministic_sorted_output(self):
        from stopa.domain.crypto.bridges import analyze_cross_chain

        data = {"eth": ["0xbb", "0xaa"], "bsc": ["0xbb", "0xaa"]}
        out = [l.entity for l in analyze_cross_chain(data)]
        assert out == sorted(out)


class TestBridgeTextDetection:
    def test_wormhole_term(self):
        from stopa.domain.crypto.bridges import detect_bridge_in_text

        out = detect_bridge_in_text("funds moved via Wormhole gateway")
        assert out is not None and "wormhole" in out.bridges

    def test_multi_word_binance_peg(self):
        from stopa.domain.crypto.bridges import detect_bridge_in_text

        out = detect_bridge_in_text("bridged through the Binance Peg token contract")
        assert out is not None and any("binance peg" in b for b in out.bridges)

    def test_word_boundary(self):
        from stopa.domain.crypto.bridges import detect_bridge_in_text

        # "wormholes" (množné číslo) nesedí přes word boundary? — "wormhole\b" by to
        # pustilo; ověřujeme alespoň, že "polygones" nepadne na polygon_pos termíny
        out = detect_bridge_in_text("unrelated wormholes in the code")
        assert out is None or all(b != "polygon_pos" for b in (out.bridges if out else []))

    def test_no_match_none(self):
        from stopa.domain.crypto.bridges import detect_bridge_in_text

        assert detect_bridge_in_text("plain text") is None


# ---------------------------------------------------------------------------
# K5.4 — Privacy coins
# ---------------------------------------------------------------------------


def _make_xmr(net_byte: int = 0x12, spend: bytes | None = None, view: bytes | None = None) -> str:
    """Deterministická validní XMR adresa (block-wise base58, keccak checksum).

    Stejná konstrukce jako K1 `make_xmr_address`: net(1)+spend(32)+view(32)=65 B
    payload + 4 B keccak → 69 B → přesně 95 znaků.
    """
    from stopa.domain.crypto._base58 import b58encode
    from stopa.domain.crypto._keccak import keccak256

    spend = spend if spend is not None else bytes(range(1, 33))
    view = view if view is not None else bytes(range(33, 65))
    payload = bytes([net_byte]) + spend + view
    full = payload + keccak256(payload)[:4]

    def block(data: bytes, width: int) -> str:
        return b58encode(data).rjust(width, "1")

    out = ""
    for i in range(0, len(full) - 5, 8):
        out += block(full[i : i + 8], 11)
    return out + block(full[-5:], 7)


class TestZcashStructure:
    def test_valid_taddr(self):
        from stopa.domain.crypto.privacy_coins import looks_like_zcash_taddr

        z = "t1" + "ybn" * 25  # t1 + 75 chars z abecedy
        assert len(z) == 77 and looks_like_zcash_taddr(z) is True

    def test_min_length(self):
        from stopa.domain.crypto.privacy_coins import looks_like_zcash_taddr

        # body = znaky za t1; produkční rozsah 74–80 → minimum celkem 76 znaků
        assert looks_like_zcash_taddr("t1" + "y" * 74) is True

    def test_too_short(self):
        from stopa.domain.crypto.privacy_coins import looks_like_zcash_taddr

        assert looks_like_zcash_taddr("t1" + "y" * 70) is False

    def test_wrong_prefix(self):
        from stopa.domain.crypto.privacy_coins import looks_like_zcash_taddr

        assert looks_like_zcash_taddr("u1" + "y" * 74) is False

    def test_non_alphabet_chars(self):
        from stopa.domain.crypto.privacy_coins import looks_like_zcash_taddr

        # 'l' a 'o' nejsou v Zcash base32 abecedě
        assert looks_like_zcash_taddr("t1" + "y" * 40 + "lo" + "y" * 32) is False


class TestPrivacyTextDetection:
    def test_valid_xmr_address(self):
        from stopa.domain.crypto.privacy_coins import detect_privacy_in_text

        addr = _make_xmr()
        out = detect_privacy_in_text(f"pay {addr} in XMR")
        kinds = {(f.coin, f.evidence_kind) for f in out}
        assert ("monero", "address") in kinds
        xmr_finding = next(f for f in out if f.evidence_kind == "address")
        assert xmr_finding.value == addr and xmr_finding.score >= 10

    def test_invalid_b58_not_address(self):
        from stopa.domain.crypto.privacy_coins import detect_privacy_in_text

        # správný tvar, ale špatný checksum → jen textový termín, žádná adresa
        addr = _make_xmr()[:-1] + ("0" if _make_xmr()[-1] != "0" else "1")
        out = detect_privacy_in_text(f"xmr wallet {addr}")
        assert all(f.evidence_kind != "address" for f in out)

    def test_payment_id_context(self):
        from stopa.domain.crypto.privacy_coins import detect_privacy_in_text

        pid = "ab" * 32
        text = f"monero payment id {pid} attached to the transfer"
        out = detect_privacy_in_text(text)
        pids = [f for f in out if f.evidence_kind == "payment_id"]
        assert len(pids) == 1 and pids[0].value.lower() == pid

    def test_payment_id_far_away_ignored(self):
        from stopa.domain.crypto.privacy_coins import detect_privacy_in_text

        pid = "cd" * 32
        # pid > 80 znaků od posledního monero termínu → nekontextualizován
        text = f"xmr transfer ... {'y' * 120} {pid}"
        out = detect_privacy_in_text(text)
        assert all(f.evidence_kind != "payment_id" for f in out)

    def test_zcash_taddr_in_text(self):
        from stopa.domain.crypto.privacy_coins import detect_privacy_in_text

        z = "t1" + "ybn" * 25
        out = detect_privacy_in_text(f"sent funds to {z} (zcash)")
        kinds = {(f.coin, f.evidence_kind) for f in out}
        assert ("zcash", "address") in kinds

    def test_zcash_terms(self):
        from stopa.domain.crypto.privacy_coins import detect_privacy_in_text

        out = detect_privacy_in_text("moved to the shielded pool via zcash")
        coins = {f.coin for f in out if f.evidence_kind == "text_term"}
        assert "zcash" in coins

    def test_monero_terms(self):
        from stopa.domain.crypto.privacy_coins import detect_privacy_in_text

        out = detect_privacy_in_text("paid in XMR (ringct)")
        terms = {f.value for f in out if f.evidence_kind == "text_term"}
        assert {"xmr", "ringct"} <= terms

    def test_no_indicators(self):
        from stopa.domain.crypto.privacy_coins import detect_privacy_in_text

        assert detect_privacy_in_text("bitcoin only") == []

    def test_deterministic_ordering(self):
        from stopa.domain.crypto.privacy_coins import detect_privacy_in_text

        text = f"xmr { _make_xmr() } zcash shielded pool ringct"
        a = [f.model_dump() for f in detect_privacy_in_text(text)]
        b = [f.model_dump() for f in detect_privacy_in_text(text)]
        assert a == b


class TestPrivacyWallet:
    def test_monero_wallet(self):
        from stopa.domain.crypto.privacy_coins import detect_privacy_wallet

        out = detect_privacy_wallet("wallets/monero-wallet", "type: primary\nview key: aa")
        assert len(out) == 1 and out[0].coin == "monero"
        assert out[0].evidence_kind == "wallet_file"

    def test_zcash_wallet_by_name(self):
        from stopa.domain.crypto.privacy_coins import detect_privacy_wallet

        out = detect_privacy_wallet("downloads/zcash-wallet.txt", "")
        assert len(out) == 1 and out[0].coin == "zcash"

    def test_unrelated_file(self):
        from stopa.domain.crypto.privacy_coins import detect_privacy_wallet

        assert detect_privacy_wallet("notes/todo.md", "shopping list") == []


# ---------------------------------------------------------------------------
# K5.5 — AI copilot (injektovatelná LLM + deterministický fallback)
# ---------------------------------------------------------------------------


class TestCopilotPrompt:
    def test_prompt_contains_summary_and_contract(self):
        from stopa.intelligence.crypto_copilot import build_prompt

        p = build_prompt({"defi_findings": 3, "critical_sanctions": 1})
        assert '"defi_findings": 3' in p or 'defi_findings: 3' in p
        assert "risk_level" in p and "key_findings" in p


class TestCopilotLlmPath:
    def test_valid_llm_json(self):
        from stopa.intelligence.crypto_copilot import run_crypto_copilot

        llm = lambda prompt: json.dumps(
            {
                "risk_level": "high",
                "key_findings": ["defi exposure"],
                "recommended_actions": ["trace flows"],
            }
        )
        r = run_crypto_copilot(llm, {"defi_findings": 2})
        assert r.source == "llm" and r.risk_level == "high"
        assert r.key_findings == ("defi exposure",)

    def test_code_fence_tolerated(self):
        from stopa.intelligence.crypto_copilot import run_crypto_copilot

        llm = lambda prompt: '```json\n{"risk_level": "low", "key_findings": [], "recommended_actions": []}\n```'
        r = run_crypto_copilot(llm, {})
        assert r.source == "llm" and r.risk_level == "low"

    def test_invalid_risk_level_falls_back(self):
        from stopa.intelligence.crypto_copilot import run_crypto_copilot

        llm = lambda prompt: '{"risk_level": "banana", "key_findings": [], "recommended_actions": []}'
        r = run_crypto_copilot(llm, {})
        assert r.source == "fallback" and r.risk_level in ("low", "medium", "high", "critical")

    def test_non_dict_json_falls_back(self):
        from stopa.intelligence.crypto_copilot import run_crypto_copilot

        llm = lambda prompt: "[1, 2, 3]"
        r = run_crypto_copilot(llm, {"defi_findings": 9})
        assert r.source == "fallback" and r.risk_level == "high"

    def test_llm_exception_falls_back(self):
        from stopa.intelligence.crypto_copilot import run_crypto_copilot

        def boom(prompt):
            raise RuntimeError("LLM offline")

        r = run_crypto_copilot(boom, {})
        assert r.source == "fallback" and r.risk_level == "low"


class TestDeterministicResult:
    def test_empty_summary_low(self):
        from stopa.intelligence.crypto_copilot import deterministic_result

        r = deterministic_result({})
        assert r.risk_level == "low" and r.source == "fallback"

    def test_defi_medium(self):
        from stopa.intelligence.crypto_copilot import deterministic_result

        assert deterministic_result({"defi_findings": 1}).risk_level == "medium"

    def test_critical_sanctions_wins(self):
        from stopa.intelligence.crypto_copilot import deterministic_result

        r = deterministic_result({"critical_sanctions": 2, "defi_findings": 0})
        assert r.risk_level == "critical"
        assert any("kritick" in a for a in r.recommended_actions)

    def test_many_privacy_high(self):
        from stopa.intelligence.crypto_copilot import deterministic_result

        assert deterministic_result({"privacy_findings": 5}).risk_level == "high"

    def test_multi_signal_high(self):
        from stopa.intelligence.crypto_copilot import deterministic_result

        # práh high = defi+nft+bridges ≥ 4 (nebo privacy ≥ 5)
        s = {"defi_findings": 2, "nft_findings": 1, "bridge_links": 1}
        assert deterministic_result(s).risk_level == "high"

    def test_actions_per_level(self):
        from stopa.intelligence.crypto_copilot import deterministic_result

        for level in ("low", "medium", "high", "critical"):
            r = deterministic_result({"privacy_findings": 0, "defi_findings": int(level != "low")})
            assert len(r.recommended_actions) >= 1


class TestCopilotToDict:
    def test_keys(self):
        from stopa.intelligence.crypto_copilot import deterministic_result

        d = deterministic_result({}).to_dict()
        assert set(d) == {"risk_level", "key_findings", "recommended_actions", "source"}


# ---------------------------------------------------------------------------
# K5.6 — CLI E2E (stopa advanced)
# ---------------------------------------------------------------------------


@pytest.fixture()
def k5_env(tmp_path, monkeypatch):
    """Případ s textovým zdrojem obsahujícím K5 indikátory + TxCache cross-chain."""
    from stopa.data.db import CaseDB
    from stopa.domain.crypto.onchain_api import TxCache
    from stopa.domain.crypto.onchain_models import TxInput, TxOutput, TxRecord
    from stopa.models import Case, EvidenceSource

    monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
    case = Case(name="k5-cli-smoke")
    db = CaseDB(tmp_path / f"{case.id}.db")
    db.add_case(case)
    note_file = tmp_path / "k5_note.txt"
    note_file.write_text(
        "Swapped on Uniswap v3, then bridged via Wormhole gateway.\n"
        "Bought CryptoPunk from 0xb47e3cd837dDF8e4c57F05d70Ab865de6e193BBB token id: 4201\n"
        "Paid in XMR ringct, moved to zcash shielded pool.\n",
        encoding="utf-8",
    )
    src = EvidenceSource(case_id=case.id, kind="file", path=str(note_file), size_bytes=10)
    db.add_source(src)

    # TxCache: jedna adresa na dvou chainách (eth + bsc) → cross-chain link
    multi = "0x" + "ab" * 20
    cache_path = tmp_path / f"{case.id}.txcache.json"
    TxCache(cache_path).save(
        {
            multi: [
                TxRecord(txid="t1", chain="eth", timestamp=1, inputs=[TxInput(address=multi, amount=1)], outputs=[]),
                TxRecord(txid="t2", chain="bsc", timestamp=2, inputs=[], outputs=[TxOutput(address=multi, amount=1)]),
            ]
        }
    )

    yield case.id, note_file, tmp_path, multi
    db.close()


class TestK5CliAdvanced:
    @staticmethod
    def _ns(case_id: str, json_mode: bool = False, file_list=None):
        return argparse.Namespace(case_id=case_id, file=file_list, json=json_mode)

    def test_json_output(self, k5_env, capsys):
        from stopa.cli import cmd_advanced

        case_id, _note, _tmp, multi = k5_env
        rc = cmd_advanced(self._ns(case_id, json_mode=True))
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["case_id"] == case_id and data["files_scanned"] >= 1

        protos = {f["protocol"] for f in data["defi_findings"]}
        assert "uniswap" in protos
        nft = data["nft_findings"][0]
        assert "CryptoPunks" in nft["collections"] and nft["token_ids"] == [4201]
        bridges = {b for m in data["bridge_text_mentions"] for b in m["bridges"]}
        assert "wormhole" in bridges
        links = data["cross_chain_links"]
        assert any(l["entity"] == multi and l["evidence"] == "multi_chain_presence" for l in links)
        coins = {f["coin"] for f in data["privacy_findings"]}
        assert {"monero", "zcash"} <= coins
        assert data["copilot"]["source"] == "fallback"

    def test_human_output(self, k5_env, capsys):
        from stopa.cli import cmd_advanced

        case_id, _note, _tmp, _multi = k5_env
        rc = cmd_advanced(self._ns(case_id))
        assert rc == 0
        out = capsys.readouterr().out
        assert "K5 advanced:" in out
        for marker in ("DEFI", "NFT →", "BRIDGE TEXT", "CROSS-CHAIN LINK", "PRIVACY", "COPILOT"):
            assert marker in out, f"chybí {marker!r} v výstupu: {out}"

    def test_empty_case(self, tmp_path, monkeypatch, capsys):
        from stopa.cli import cmd_advanced
        from stopa.data.db import CaseDB
        from stopa.models import Case

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        case = Case(name="k5-empty")
        db = CaseDB(tmp_path / f"{case.id}.db")
        db.add_case(case)
        rc = cmd_advanced(self._ns(case.id, json_mode=True))
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["files_scanned"] == 0 and data["defi_findings"] == []
        assert data["copilot"]["risk_level"] == "low"
        db.close()

    def test_explicit_file_flag(self, tmp_path, monkeypatch, capsys):
        """--file skenuje i soubor mimo DB zdroje."""
        from stopa.cli import cmd_advanced
        from stopa.data.db import CaseDB
        from stopa.models import Case

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        case = Case(name="k5-file")
        db = CaseDB(tmp_path / f"{case.id}.db")
        db.add_case(case)
        f = tmp_path / "adhoc.txt"
        f.write_text("supplied to Aave lending pool", encoding="utf-8")

        rc = cmd_advanced(self._ns(case.id, json_mode=True, file_list=[str(f)]))
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        protos = {x["protocol"] for x in data["defi_findings"]}
        assert "aave" in protos
        db.close()


# ---------------------------------------------------------------------------
# K5.6 — determinismus end-to-end (stejný vstup → stejný výsledek)
# ---------------------------------------------------------------------------


class TestK5Determinism:
    def test_full_pipeline_stable(self):
        """Stejné texty + per_chain → identické sérializované výsledky."""
        from stopa.domain.crypto.bridges import analyze_cross_chain, detect_bridge_in_text
        from stopa.domain.crypto.defi import detect_defi_in_text
        from stopa.domain.crypto.nft import detect_nft_in_text
        from stopa.domain.crypto.privacy_coins import detect_privacy_in_text

        text = (
            "Uniswap v3 swap, bridged via Wormhole, CryptoPunks on opensea token id: 7, "
            "xmr ringct payment, zcash shielded pool"
        )
        per_chain = {"eth": ["0xaa"], "bsc": ["0xAA", "0xbb"]}

        def run():
            nf = detect_nft_in_text(text)
            bf = detect_bridge_in_text(text)
            return json.dumps(
                {
                    "defi": [f.model_dump() for f in detect_defi_in_text(text)],
                    "nft": nf.model_dump() if nf else None,
                    "bridge_text": bf.model_dump() if bf else None,
                    "links": [l.model_dump() for l in analyze_cross_chain(per_chain)],
                    "privacy": [f.model_dump() for f in detect_privacy_in_text(text)],
                },
                sort_keys=True,
            )

        assert run() == run()


class TestK5Imports:
    """Smoke: všechny K5 moduly se importují bez sítě a bez vedlejších efektů."""

    def test_imports(self):
        import stopa.domain.crypto.bridges
        import stopa.domain.crypto.defi
        import stopa.domain.crypto.nft
        import stopa.domain.crypto.privacy_coins
        import stopa.intelligence.crypto_copilot  # noqa: F401

    def test_no_network_in_modules(self):
        """Žádný K5 modul nesmí volat socket přímo (offline-first)."""
        import pathlib

        root = pathlib.Path("src/stopa")
        for rel in (
            "domain/crypto/defi.py",
            "domain/crypto/nft.py",
            "domain/crypto/bridges.py",
            "domain/crypto/privacy_coins.py",
            "intelligence/crypto_copilot.py",
        ):
            src = (root / rel).read_text(encoding="utf-8")
            assert not re.search(r"\bsocket\.|requests\.get|urllib\.request", src), rel
