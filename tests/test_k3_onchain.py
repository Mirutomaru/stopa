"""STOPA — K3 testy: on-chain offline-first analýza (K3.1–K3.5).

Pokrytí dle AK v ``docs/CRYPTO_FORENSICS_PROPOSAL.md``:
- K3.1 — opt-in API klienti (Blockchair/Etherscan) s injektovatelným transportem,
  defenzivní normalizace wire schémat a JSON cache s atomickým zápisem;
- K3.2 — deterministické clustering (common-input + change-detection), bez ML;
- K3.3 — transakční graf, poměrný model částek hran, detekce cyklů, cesty, Mermaid;
- K3.4 — risk scoring z bundlovaných OFAC/EU listů (deterministická tabulka);
- CLI E2E — ``stopa onchain <case>`` (offline-first: cache + listy, síť jen opt-in).

Offline determinismus: stejný vstup → stejný výsledek; žádná síť bez explicitního
klienta s API klíčem.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import pytest

from stopa.domain.crypto.clustering import (
    MAX_EVIDENCE_TXIDS,
    cluster_common_input,
    detect_change_addresses,
)
from stopa.domain.crypto.onchain_api import (
    CACHE_SCHEMA_VERSION,
    BlockchairClient,
    EtherscanClient,
    OnchainApiError,
    TxCache,
)
from stopa.domain.crypto.onchain_models import SanctionEntry, TxInput, TxOutput, TxRecord
from stopa.domain.crypto.risk_scoring import load_sanction_lists, score_address, score_addresses
from stopa.domain.crypto.tx_graph import (
    build_graph,
    detect_cycles,
    expand_paths,
    graph_to_json,
    to_mermaid,
    top_recipients,
    top_senders,
)

# Známé adresy z bundlovaných listů (ověřené proti primárním zdrojům):
TORNADO_ETH = "0x8589427373D6D84E98730D7795D8f6f8731FDA16"  # OFAC CYBER, mixer → critical
EU_BTC_BECH32 = "bc1qwtz3zv95x2flu4w26kgfepf529z50r2sqc5zml"  # EU 269/2014 Garantex (entry 541)
EU_ETH_MIXED = "0x002471b8A185f9980708d0eAEC5B289714F56f8d"  # tamtéž, EIP-55 checksum tvar


def tx(txid: str, ins: list[tuple[str | None, int]], outs: list[tuple[str | None, int]],
       chain: str = "btc", ts: int = 1_700_000_000) -> TxRecord:
    """Testovací konstruktor normalizované transakce (kw-friendly)."""
    return TxRecord(
        txid=txid,
        chain=chain,
        timestamp=ts,
        inputs=[TxInput(address=a, amount=m) for a, m in ins],
        outputs=[TxOutput(address=a, amount=m, index=i) for i, (a, m) in enumerate(outs)],
    )


# ── K3.4 — bundlované sankční listy ────────────────────────────────


class TestK3BundledLists:
    def test_ofac_list(self):
        ofac, _ = load_sanction_lists()
        assert len(ofac) == 44
        assert all(e.address for e in ofac)

    def test_eu_list(self):
        _, eu = load_sanction_lists()
        assert len(eu) >= 5
        assert any("Garantex" in (e.entity or "") for e in eu)

    def test_entries_unique_within_list(self):
        for entries in load_sanction_lists():
            norm = [_norm_a(e.address) for e in entries]
            assert len(norm) == len(set(norm))


def _norm_a(addr: str) -> str:
    return addr.lower() if addr.startswith("0x") else addr


_OFAC_ADDRS = [e.address for e in load_sanction_lists()[0]]
_EU_ADDRS = [e.address for e in load_sanction_lists()[1]]


@pytest.mark.parametrize("addr", _OFAC_ADDRS, ids=lambda a: a[:12])
def test_every_ofac_entry_scores_positive(addr):
    """K3.5 — každý záznam bundlovaného OFAC listu se skóruje ≥ 95 (smoke celé databáze)."""
    assert score_address(addr).score >= 95


@pytest.mark.parametrize("addr", _EU_ADDRS, ids=lambda a: a[:12])
def test_every_eu_entry_scores_positive(addr):
    """K3.5 — každý záznam bundlovaného EU listu se skóruje ≥ 95."""
    assert score_address(addr).score >= 95


# ── K3.4 — risk scoring ────────────────────────────────────────────


class TestK3RiskScoring:
    def test_tornado_cash_critical(self):
        s = score_address(TORNADO_ETH)
        assert (s.score, s.level) == (100, "critical")
        joined = " ".join(s.reasons)
        assert "TORNADO" in joined or "tornad" in joined.lower()
        assert "tags=mixer" in joined
        assert "ofac.treasury.gov" in joined

    def test_garantex_btc_high(self):
        s = score_address(EU_BTC_BECH32)
        assert (s.score, s.level) == (95, "high")
        assert any("Garantex" in r for r in s.reasons)
        assert any("EU-269/2014" in r for r in s.reasons)

    def test_eip55_mixed_case_matches_lowercase(self):
        """EIP-55 checksum tvar se normalizuje na lowercase — stejný výsledek."""
        assert score_address(EU_ETH_MIXED).score == score_address(EU_ETH_MIXED.lower()).score
        assert score_address(EU_ETH_MIXED).level == "high"

    def test_unknown_address_none(self):
        s = score_address("1BvBMSEYstWetqFn59p5aiPhTCKMydQ2hwm")  # genesis-like, ne na listách
        assert (s.score, s.level) == (0, "none")
        assert s.reasons == []

    def test_score_addresses_sorted_and_complete(self):
        addrs = [EU_BTC_BECH32, TORNADO_ETH, "1CUnknownAddress0000000000"]
        out = score_addresses(addrs)
        assert list(out.keys()) == sorted(set(addrs))  # deterministické pořadí klíčů
        assert all(a in out for a in addrs)

    def test_injected_lists(self):
        custom = (
            (SanctionEntry(address="1CustomAddr", chain="btc", entity="X", tags=["mixer"]),),
            (),
        )
        s = score_address("1CustomAddr", lists=custom)
        assert (s.score, s.level) == (100, "critical")
        empty: tuple[tuple[SanctionEntry, ...], tuple[SanctionEntry, ...]] = ((), ())
        assert score_address("1Other", lists=empty).level == "none"

    def test_multiple_matches_max_and_all_reasons(self):
        """Adresa na obou listách → max skóre + důvody z obou zdrojů."""
        both = (
            (SanctionEntry(address="0xabc", chain="eth", entity="OFAC X", tags=["exchange"]),),
            (SanctionEntry(address="0xABC", chain="eth", entity="EU Y", tags=["mixer"]),),
        )
        s = score_address("0xAbC", lists=both)
        assert (s.score, s.level) == (100, "critical")  # mixer → critical, max(95,100)=100
        joined = " ".join(s.reasons)
        assert "OFAC X" in joined and "EU Y" in joined


# ── K3.2 — clustering (common-input) ───────────────────────────────


class TestK3Clustering:
    def test_single_input_tx_no_cluster(self):
        txs = [tx("t1", [("A", 5)], [("B", 4)])]
        assert cluster_common_input(txs) == []

    def test_two_input_consolidation(self):
        txs = [tx("t1", [("A", 5), ("B", 3)], [("C", 7)])]
        clusters = cluster_common_input(txs)
        assert len(clusters) == 1
        c = clusters[0]
        assert c.addresses == ["A", "B"]
        assert c.reason == "common_input"
        assert c.txids == ["t1"]

    def test_merge_via_shared_address(self):
        """(A,B) a (C,D) propojí tx (B,C) → jeden cluster A,B,C,D."""
        txs = [
            tx("t1", [("A", 5), ("B", 3)], [("P", 7)]),
            tx("t2", [("C", 4), ("D", 6)], [("Q", 9)]),
            tx("t3", [("B", 2), ("C", 8)], [("R", 9)]),
        ]
        clusters = cluster_common_input(txs)
        assert len(clusters) == 1
        assert clusters[0].addresses == ["A", "B", "C", "D"]
        assert set(clusters[0].txids) == {"t1", "t2", "t3"}

    def test_deterministic_output(self):
        txs = [
            tx("t1", [("Z", 1), ("Y", 1)], [("A", 2)]),
            tx("t2", [("B", 1), ("C", 1)], [("D", 2)]),
        ]
        # determinismus: stejný vstup → byte-for-byte stejný výsledek
        out1 = [c.model_dump() for c in cluster_common_input(txs)]
        out2 = [c.model_dump() for c in cluster_common_input(txs)]
        assert out1 == out2

    def test_evidence_capped(self):
        """60 konsolidačních tx se stejnou adresou → důkazy omezené na MAX_EVIDENCE_TXIDS."""
        txs = [tx(f"t{i:03d}", [("A", 1), (f"X{i:03d}", 1)], [("P", 2)]) for i in range(60)]
        clusters = cluster_common_input(txs)
        assert len(clusters) == 1
        c = clusters[0]
        assert len(c.addresses) == 61  # A + X0..X59
        assert len(c.txids) == MAX_EVIDENCE_TXIDS
        assert len(set(c.txids)) == MAX_EVIDENCE_TXIDS


# ── K3.2 — change-detection ────────────────────────────────────────


class TestK3ChangeDetection:
    def test_remainder_rule_flags_change(self):
        txs = [tx("t1", [("A", 10_000_000)], [("B", 9_000_000), ("C", 1_000_000)])]
        assert detect_change_addresses(txs, {"B"}) == {"B"}

    def test_single_output_not_flagged(self):
        """Podmínka: 2+ různé výstupní adresy."""
        txs = [tx("t1", [("A", 10)], [("B", 9)])]
        assert detect_change_addresses(txs, {"B"}) == set()

    def test_refund_input_output_not_flagged(self):
        """Vstup→výstup téže tx (refund) není change signatura."""
        txs = [tx("t1", [("A", 5), ("B", 5)], [("B", 4), ("C", 6)])]
        assert detect_change_addresses(txs, {"B"}) == set()

    def test_amount_mismatch_not_flagged(self):
        txs = [tx("t1", [("A", 10)], [("B", 8), ("C", 1)])]
        assert detect_change_addresses(txs, {"B"}) == set()


# ── K3.3 — transakční graf ─────────────────────────────────────────


class TestK3Graph:
    def test_node_stats_exact(self):
        txs = [tx("t1", [("A", 7_000_000)], [("B", 3_000_000), ("C", 2_000_000)])]
        g = build_graph(txs)
        assert g.nodes["A"].out_amount == 7_000_000
        assert g.nodes["A"].tx_out == 1
        assert g.nodes["B"].in_amount == 3_000_000
        assert g.nodes["B"].balance == 3_000_000

    def test_edge_proportional_multi_input(self):
        """Poměrný model: share = output.amount * input.amount / total_in."""
        txs = [tx("t1", [("A", 5_000), ("B", 5_000)], [("C", 8_000)])]
        g = build_graph(txs)
        by_pair = {(e.src, e.dst): e.amount for e in g.edges}
        assert by_pair[("A", "C")] == 4_000
        assert by_pair[("B", "C")] == 4_000

    def test_single_input_full_amount(self):
        txs = [tx("t1", [("A", 7_000)], [("B", 3_000), ("D", 2_000)])]
        g = build_graph(txs)
        by_pair = {(e.src, e.dst): e.amount for e in g.edges}
        assert by_pair[("A", "B")] == 3_000
        assert by_pair[("A", "D")] == 2_000

    def test_edge_aggregation_across_txs(self):
        txs = [
            tx("t1", [("A", 4)], [("B", 3)]),
            tx("t2", [("A", 6)], [("B", 5)]),
        ]
        g = build_graph(txs)
        assert len(g.edges) == 1  # agregace na (src, dst)
        assert g.edges[0].amount == 8

    def test_two_node_cycle(self):
        txs = [tx("t1", [("A", 5)], [("B", 4)]), tx("t2", [("B", 3)], [("A", 2)])]
        cycles = detect_cycles(build_graph(txs))
        assert cycles == [["A", "B"]]

    def test_self_loop(self):
        txs = [tx("t1", [("X", 5)], [("X", 4), ("Y", 1)])]
        cycles = detect_cycles(build_graph(txs))
        assert ["X"] in cycles

    def test_three_cycle_rotation_dedup(self):
        """Cyklus A→B→C→A se nalezne jen jednou (kanonizace rotací)."""
        txs = [
            tx("t1", [("A", 5)], [("B", 4)]),
            tx("t2", [("B", 3)], [("C", 2)]),
            tx("t3", [("C", 1)], [("A", 2)]),
        ]
        cycles = detect_cycles(build_graph(txs), max_len=4)
        assert cycles == [["A", "B", "C"]]

    def test_max_len_limits_search(self):
        txs = [
            tx("t1", [("A", 5)], [("B", 4)]),
            tx("t2", [("B", 3)], [("C", 2)]),
            tx("t3", [("C", 1)], [("A", 2)]),
        ]
        assert detect_cycles(build_graph(txs), max_len=2) == []

    def test_expand_paths_depth_semantics(self):
        """depth=1 → přímí příjemci; cesta obsahuje start i cíl."""
        txs = [
            tx("t1", [("A", 5)], [("B", 4)]),
            tx("t2", [("B", 3)], [("C", 2)]),
            tx("t3", [("C", 1)], [("D", 1)]),
        ]
        g = build_graph(txs)
        assert expand_paths(g, "A", depth=1) == [["A", "B"]]
        paths = expand_paths(g, "A", depth=2)
        assert ["A", "B"] in paths and ["A", "B", "C"] in paths
        assert all(len(p) <= 3 for p in paths)

    def test_expand_paths_unknown_start(self):
        g = build_graph([tx("t1", [("A", 5)], [("B", 4)])])
        assert expand_paths(g, "ZZZ", depth=2) == []

    def test_top_senders_recipients_ordering(self):
        txs = [
            tx("t1", [("A", 9_000)], [("P", 5_000), ("Q", 4_000)]),
            tx("t2", [("B", 3_000)], [("R", 2_000)]),
        ]
        g = build_graph(txs)
        assert top_senders(g)[0][0] == "A"
        assert top_recipients(g)[0][0] in ("P", "Q")

    def test_tie_break_by_address(self):
        txs = [
            tx("t1", [("B", 5)], [("X", 4)]),
            tx("t2", [("A", 5)], [("Y", 4)]),
        ]
        g = build_graph(txs)
        senders = top_senders(g, n=2)
        assert [a for a, _ in senders] == ["A", "B"]  # stejná částka → lexikograficky

    def test_mermaid_and_json_export(self):
        txs = [tx("t1", [("A", 5)], [("B", 4)])]
        g = build_graph(txs)
        m = to_mermaid(g)
        assert m.startswith("graph LR") and "-->" in m
        data = json.loads(graph_to_json(g))
        assert "nodes" in data and "edges" in data


# ── K3.1 — API klienti (injektovatelný transport, offline testy) ───


class TestK3Blockchair:
    def _canned(self):
        return {
            "result": {
                "transactions": [
                    {
                        "hash": "abc123",
                        "time": "2024-01-01T00:00:00Z",
                        "inputs": [{"address": "A", "amount": 5}],
                        "outputs": [{"address": "B", "amount": 4}],
                    }
                ]
            }
        }

    def test_empty_key_raises(self):
        with pytest.raises(OnchainApiError, match="prázdný"):
            BlockchairClient("  ")

    def test_fetch_normalizes(self):
        seen: list[str] = []

        def transport(url: str) -> dict:
            seen.append(url)
            return self._canned()

        client = BlockchairClient("KEY123", transport=transport)
        txs = client.fetch_address_txs("bc1qaddr")
        assert len(txs) == 1
        t = txs[0]
        assert (t.txid, t.chain) == ("abc123", "btc")
        assert t.timestamp == int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
        assert t.inputs[0].amount == 5 and t.outputs[0].address == "B"
        url = seen[0]
        assert "bc1qaddr" in url and "key=KEY123" in url

    def test_missing_transactions_raises(self):
        client = BlockchairClient("K", transport=lambda u: {"result": {}})
        with pytest.raises(OnchainApiError, match="transactions"):
            client.fetch_address_txs("A")

    def test_non_dict_items_skipped(self):
        data = self._canned()
        data["result"]["transactions"].insert(0, "garbage")
        client = BlockchairClient("K", transport=lambda u: data)
        assert len(client.fetch_address_txs("A")) == 1


class TestK3Etherscan:
    def test_fetch_normalizes(self):
        canned = {
            "status": "1",
            "message": "OK",
            "result": [
                {"hash": "0xdead", "from": "F", "to": "T", "value": "1000", "timeStamp": "1700000000"}
            ],
        }
        client = EtherscanClient("K", transport=lambda u: canned)
        txs = client.fetch_address_txs("0xabc")
        assert len(txs) == 1
        t = txs[0]
        assert (t.txid, t.chain) == ("0xdead", "eth")
        assert t.timestamp == 1_700_000_000
        assert t.inputs[0].address == "F" and t.outputs[0].amount == 1_000

    def test_error_status_raises(self):
        canned = {"status": "0", "message": "Not OK", "result": "Not found"}
        client = EtherscanClient("K", transport=lambda u: canned)
        with pytest.raises(OnchainApiError, match="result\\[\\]"):
            client.fetch_address_txs("0xabc")

    def test_empty_key_raises(self):
        with pytest.raises(OnchainApiError):
            EtherscanClient("")


class TestK3TxCache:
    def test_roundtrip(self, tmp_path):
        p = tmp_path / "cache.json"
        data = {"A": [tx("t1", [("A", 5)], [("B", 4)])], "B": []}
        TxCache(p).save(data)
        loaded = TxCache(p).load()
        assert set(loaded.keys()) == {"A", "B"}
        assert loaded["A"][0].txid == "t1"
        raw = json.loads(p.read_text(encoding="utf-8"))
        assert raw["schema"] == CACHE_SCHEMA_VERSION

    def test_atomic_write_no_tmp_leftover(self, tmp_path):
        p = tmp_path / "cache.json"
        TxCache(p).save({"A": [tx("t1", [("A", 5)], [("B", 4)])]})
        assert list(tmp_path.glob(".txcache-*")) == []

    def test_corrupt_json_degrades(self, tmp_path):
        p = tmp_path / "cache.json"
        p.write_text("{oops", encoding="utf-8")
        c = TxCache(p)
        assert c.load() == {}
        assert c.last_error is not None

    def test_schema_mismatch_degrades(self, tmp_path):
        p = tmp_path / "cache.json"
        p.write_text(json.dumps({"schema": 99, "addresses": {"A": []}}), encoding="utf-8")
        c = TxCache(p)
        assert c.load() == {}
        assert "99" in (c.last_error or "")

    def test_missing_file_empty(self, tmp_path):
        assert TxCache(tmp_path / "nope.json").load() == {}


# ── CLI E2E — stopa onchain <case> (offline-first) ────────────────


class TestK3Cli:
    @pytest.fixture()
    def case_env(self, tmp_path, monkeypatch):
        from stopa.data.db import CaseDB
        from stopa.models import Artifact, Case, EvidenceSource

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        case = Case(name="k3-smoke")
        db = CaseDB(tmp_path / f"{case.id}.db")
        db.add_case(case)
        src = EvidenceSource(case_id=case.id, kind="file", path="/tmp/k3.txt")
        db.add_source(src)
        art = Artifact(
            source_id=src.id,
            artifact_type="crypto_detection",
            title="K1 scan (test)",
            details={
                "addresses": [
                    {"raw_value": TORNADO_ETH, "chain": "ethereum"},
                    {"raw_value": EU_BTC_BECH32, "chain": "bitcoin"},
                ]
            },
        )
        db.artifact_repo.upsert_artifact(art)

        # seed cache: konsolidace s bech32 adresou (offline clustering E2E)
        TxCache(tmp_path / f"{case.id}.txcache.json").save({
            TORNADO_ETH: [
                tx("seed01", [(EU_BTC_BECH32, 5_000_000), ("bc1qotheraddr", 3_000_000)],
                   [("bc1qpool", 7_900_000)]),
            ]
        })
        yield case.id
        db.close()

    @staticmethod
    def _ns(case_id: str, json_mode: bool = False) -> argparse.Namespace:
        return argparse.Namespace(
            case_id=case_id,
            api_key=None,
            etherscan_key=None,
            no_network=True,
            depth=2,
            json=json_mode,
        )

    def test_human_output(self, case_env, capsys):
        from stopa.cli import cmd_onchain

        rc = cmd_onchain(self._ns(case_env))
        out = capsys.readouterr().out
        assert rc == 0
        assert TORNADO_ETH in out and "[critical]" in out
        assert EU_BTC_BECH32 in out and "[high]" in out
        assert "clusterů: 1" in out

    def test_json_output(self, case_env, capsys):
        from stopa.cli import cmd_onchain

        rc = cmd_onchain(self._ns(case_env, json_mode=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["addresses_total"] == 2
        assert data["high_risk_count"] == 2
        assert len(data["clusters"]) == 1
        cluster_addrs = set(data["clusters"][0]["addresses"])
        assert EU_BTC_BECH32 in cluster_addrs and "bc1qotheraddr" in cluster_addrs
        assert data["graph"]["nodes_total"] >= 3
        assert TORNADO_ETH in data["paths_from_risk"]
        # cesta z high-risk bech32 adresy do poolu (poměrný model hran)
        assert any("bc1qpool" in p for p in data["paths_from_risk"][EU_BTC_BECH32])

    def test_no_artifacts_graceful(self, tmp_path, monkeypatch):
        import contextlib
        import io

        from stopa.cli import cmd_onchain
        from stopa.data.db import CaseDB
        from stopa.models import Case

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        case = Case(name="prazdny")
        db = CaseDB(tmp_path / f"{case.id}.db")
        db.add_case(case)
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cmd_onchain(self._ns(case.id, json_mode=True))
            assert rc == 0
            data = json.loads(buf.getvalue())
            assert data["addresses_total"] == 0
        finally:
            db.close()
