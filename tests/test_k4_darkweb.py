"""STOPA — K4 testy: Dark Web & SWGDE report (K4.1–K4.6).

Pokrytí dle AK v ``docs/CRYPTO_FORENSICS_PROPOSAL.md``:
- K4.1 — ransom note detector (7 rodin, částky, deadline, adresy);
- K4.2 — marketplace data extractor (PGP, vendor/product termíny, escrow);
- K4.3 — mixer/tumbler detekce (CoinJoin heuristika + bundlované adresy);
- K4.4 — fund flow diagram (D3 JSON + self-contained HTML/SVG, determinismus,
  KPI render < 5 s pro 1000 transakcí);
- K4.5 — SWGDE krypto report generátor (10 sekcí; md|html|json; Ed25519 podpis
  + SHA-256 dle legal_docs konvencí, graceful degradation bez kryptobackendu);
- CLI E2E — ``stopa darkweb <case>`` a ``stopa crypto-report <case>``.

Offline determinismus: stejný vstup → stejný výsledek; bez sítě i LLM.
"""

from __future__ import annotations

import argparse
import hashlib
import json

import pytest

from stopa.domain.crypto.darkweb import (
    COINJOIN_MIN_INPUTS,
    MIXER_TEXT_TERMS,
    RANSOMWARE_FAMILIES,
    detect_marketplace_data,
    detect_mixer_mentions,
    detect_mixer_usage,
    detect_ransom_note,
    extract_addresses,
    known_mixer_addresses,
)
from stopa.domain.crypto.fund_flow import (
    CATEGORY_COLORS,
    FlowDiagram,
    build_fund_flow,
    category_for,
    render_html,
    to_d3_json,
)
from stopa.domain.crypto.onchain_models import SanctionEntry, TxInput, TxOutput, TxRecord
from stopa.domain.crypto.risk_scoring import RiskScore
from stopa.domain.crypto.tx_graph import build_graph

# Známé adresy z bundlovaných listů (ověřené proti primárním zdrojům):
TORNADO_ETH = "0x8589427373D6D84E98730D7795D8f6f8731FDA16"  # OFAC CYBER, mixer → critical
EU_BTC_BECH32 = "bc1qwtz3zv95x2flu4w26kgfepf529z50r2sqc5zml"  # EU 269/2014 Garantex (entry 541)
GENESIS_P2PKH = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"  # BTC genesis, validní Base58Check


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


# ── společná adresa extrakce (K1 pattern v domain vrstvě) ────────────────


class TestAddressExtraction:
    def test_bech32_valid(self):
        assert extract_addresses(f"pay to {EU_BTC_BECH32} now") == [EU_BTC_BECH32]

    def test_legacy_p2pkh_valid(self):
        assert extract_addresses(GENESIS_P2PKH) == [GENESIS_P2PKH]

    def test_eth_valid(self):
        assert extract_addresses(TORNADO_ETH) == [TORNADO_ETH]

    def test_invalid_checksum_still_ioc(self):
        """INVALID = rozpoznaný formát s chybným checksumem → v ransom note IoC."""
        out = extract_addresses("addr: 1BvBMSEYstWet5TFZ5uLPDtSrohP7LpLKx")
        assert "1BvBMSEYstWet5TFZ5uLPDtSrohP7LpLKx" in out

    def test_unique_first_occurrence_order(self):
        text = f"{EU_BTC_BECH32} again {GENESIS_P2PKH} and back to {EU_BTC_BECH32}"
        assert extract_addresses(text) == [EU_BTC_BECH32, GENESIS_P2PKH]

    def test_plain_text_no_addresses(self):
        assert extract_addresses("Just a regular invoice without any wallet data.") == []


# ── K4.1 — ransom note detector ───────────────────────────────────────────

LOCKBIT_NOTE = """Dear Victim,

All your files have been encrypted using the strongest military grade encryption AES-256.
This is a message from LockBit 3.0 Ransomware.

To get your decryption program and private key back, pay the ransom of 5.5 BTC
to this bitcoin address: bc1qwtz3zv95x2flu4w26kgfepf529z50r2sqc5zml
or $120,000 USD equivalent.

Contact us at lockbit@protonmail.com and pay within 7 days to avoid data leak.
"""


class TestK41RansomNote:
    def test_lockbit_full_extraction(self):
        rn = detect_ransom_note(LOCKBIT_NOTE)
        assert rn.is_ransom_note is True
        assert rn.family == "lockbit"
        assert EU_BTC_BECH32 in rn.addresses
        assert rn.amount_btc == 5.5
        assert rn.amount_usd == 120_000
        assert rn.deadline_days == 7
        assert rn.score > 0

    @pytest.mark.parametrize(
        ("family", "marker"),
        [
            ("blackmatter", "BlackMatter ransomware family"),
            ("conti", "Conti Ransomware group is back"),
            ("darkside", "DarkSide variant detected in the wild"),
            ("lockbit", "LockBit 3.0 double extortion"),
            ("petya", "Petya (GoldenEye) strikes again"),
            ("revil", "Sodinokibi, aka REvil, hit the network"),
            ("wannacry", "WannaCry worm resurfaces via EternalBlue"),
        ],
    )
    def test_each_family_detected(self, family: str, marker: str):
        rn = detect_ransom_note(f"{marker} — your files have been encrypted. Pay ransom.")
        assert rn.is_ransom_note is True
        assert rn.family == family

    def test_seven_families_in_registry(self):
        """AK: 5+ template; implementace má 7 rodin."""
        assert len(RANSOMWARE_FAMILIES) >= 5
        assert set(RANSOMWARE_FAMILIES) == {
            "blackmatter", "conti", "darkside", "lockbit", "petya", "revil", "wannacry",
        }

    def test_more_markers_wins_family(self):
        """Dvě markery téže rodiny porazí jednu jinou."""
        text = "Sodinokibi aka REvil operators — Petya also mentioned."
        rn = detect_ransom_note(text)
        assert rn.family == "revil"

    def test_tie_break_lexicographic(self):
        """Stejný počet marker → lexikograficky první rodina (determinismus)."""
        text = "LockBit and DarkSide both claimed the victim."
        rn = detect_ransom_note(text)
        assert rn.family == "darkside"  # 'd' < 'l'

    def test_generic_only_three_indicators(self):
        text = (
            "Your files are now encrypted! You must decrypt them with our program. "
            "Keep your copy of the private key safe after payment."
        )
        rn = detect_ransom_note(text)
        assert rn.is_ransom_note is True
        assert rn.family is None

    def test_generic_two_indicators_not_enough(self):
        rn = detect_ransom_note("We demand a ransom and will decrypt your data.")
        assert rn.is_ransom_note is False
        assert rn.score == 2

    def test_invoice_negative(self):
        rn = detect_ransom_note("Invoice #4821 — total $3,900 due November 15. Thank you!")
        assert rn.is_ransom_note is False
        assert rn.family is None
        assert rn.addresses == []

    def test_btc_amount_formats(self):
        assert detect_ransom_note("pay 5.5 BTC").amount_btc == 5.5
        assert detect_ransom_note("send 0,5 btc to us").amount_btc == 0.5
        assert detect_ransom_note("2 bitcoin required").amount_btc == 2.0

    def test_usd_amount_formats(self):
        assert detect_ransom_note("$120,000 total").amount_usd == 120_000
        assert detect_ransom_note("USD 9500 fee").amount_usd == 9_500

    def test_deadline_phrases(self):
        assert detect_ransom_note("pay within 7 days").deadline_days == 7
        assert detect_ransom_note("14 days to pay before the leak").deadline_days == 14
        assert detect_ransom_note("no deadline here").deadline_days is None

    def test_indicators_sorted_unique(self):
        rn = detect_ransom_note(LOCKBIT_NOTE)
        assert rn.indicators == sorted(set(rn.indicators))
        assert "have been encrypted" in rn.indicators

    def test_deterministic_repeated(self):
        a, b = detect_ransom_note(LOCKBIT_NOTE), detect_ransom_note(LOCKBIT_NOTE)
        assert a.model_dump() == b.model_dump()


# ── K4.2 — marketplace data extractor ─────────────────────────────────────

MARKETPLACE_TEXT = """Dragon's Den Marketplace — vendor feedback score 987/1000
Vendor: shadowmerchant (seller), shop owner since 2024.
Product listing: SSD 512GB — for sale, price: 0.3 BTC
Shipping via escrow service. Payment address: bc1qwtz3zv95x2flu4w26kgfepf529z50r2sqc5zml

-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: GnuPG v2
mQINBFx12345abcdefABCDEF...
-----END PGP PUBLIC KEY BLOCK-----
"""


class TestK42Marketplace:
    def test_full_sample(self):
        mp = detect_marketplace_data(MARKETPLACE_TEXT)
        assert mp.is_marketplace is True
        assert mp.pgp_keys == 1
        assert "vendor" in mp.vendor_terms and "seller" in mp.vendor_terms
        assert "for sale" in mp.product_terms and "price:" in mp.product_terms
        assert mp.escrow_mentions >= 1
        assert EU_BTC_BECH32 in mp.addresses
        assert mp.score >= 4

    def test_pgp_plus_address_rule(self):
        """PGP blok + aspoň jedna adresa → marketplace i bez skóre ≥ 4."""
        text = (
            "-----BEGIN PGP PUBLIC KEY BLOCK-----\nAAAA\n"
            f"-----END PGP PUBLIC KEY BLOCK-----\npay {GENESIS_P2PKH}"
        )
        mp = detect_marketplace_data(text)
        assert mp.is_marketplace is True
        assert mp.pgp_keys == 1

    def test_score_threshold_without_pgp(self):
        """Skóre ≥ 4 (vendor+product termíny) stačí bez PGP."""
        text = "vendor seller shop owner — for sale listing price: shipping"
        mp = detect_marketplace_data(text)
        assert mp.is_marketplace is True
        assert mp.pgp_keys == 0

    def test_plain_text_negative(self):
        mp = detect_marketplace_data("Just a regular text file with no marketplace content.")
        assert mp.is_marketplace is False
        assert mp.score < 4

    def test_multiple_pgp_blocks_counted(self):
        block = "-----BEGIN PGP PUBLIC KEY BLOCK-----\nX\n-----END PGP PUBLIC KEY BLOCK-----"
        mp = detect_marketplace_data(block + "\n\n" + block)
        assert mp.pgp_keys == 2

    def test_escrow_only_not_enough(self):
        mp = detect_marketplace_data("We use an escrow for the transfer.")
        assert mp.is_marketplace is False
        assert mp.escrow_mentions == 1

    def test_deterministic_repeated(self):
        a, b = detect_marketplace_data(MARKETPLACE_TEXT), detect_marketplace_data(MARKETPLACE_TEXT)
        assert a.model_dump() == b.model_dump()


# ── K4.3 — mixer/tumbler usage detection ─────────────────────────────────


class TestK43Mixer:
    def test_coinjoin_shape_detected(self):
        txs = [tx("cj1", [(f"u{i}", 10**6) for i in range(8)],
                  [(f"c{i}", 5 * 10**5) for i in range(4)])]
        mu = detect_mixer_usage(txs, mixer_addresses=set())
        assert mu.detected is True
        assert "coinjoin_pattern:1tx" in mu.reasons
        assert mu.coinjoin_txids == ["cj1"]

    def test_coinjoin_threshold_boundary(self):
        """Práh vstupů i výstupů (≥ 8 in a ≥ max(2, n_in//2) out)."""
        # pod prahem vstupů — dostatek výstupů, ale jen 7 in → ne CoinJoin
        below = [tx("b1", [(f"u{i}", 10**6) for i in range(COINJOIN_MIN_INPUTS - 1)],
                    [("c0", 5 * 10**5), ("c1", 5 * 10**5), ("c2", 5 * 10**5)])]
        assert detect_mixer_usage(below, mixer_addresses=set()).detected is False
        # přesně na prahu: 8 vstupů / 4 výstupy (vrácení change) → CoinJoin
        at = [tx("a1", [(f"u{i}", 10**6) for i in range(COINJOIN_MIN_INPUTS)],
                 [("c0", 5 * 10**5), ("c1", 5 * 10**5), ("c2", 5 * 10**5),
                  ("c3", 5 * 10**5)])]
        assert detect_mixer_usage(at, mixer_addresses=set()).detected is True

    def test_normal_consolidation_not_flagged(self):
        """Běžná konsolidace (málo vstupů) se CoinJoin heuristiky vyhýbá."""
        txs = [tx("n1", [("a", 5 * 10**6), ("b", 3 * 10**6)], [("c", 8 * 10**6)])]
        assert detect_mixer_usage(txs, mixer_addresses=set()).detected is False

    def test_few_outputs_not_coinjoin(self):
        """8 vstupů ale jen 1 výstup → ne CoinJoin (change-nevrácení)."""
        txs = [tx("f1", [(f"u{i}", 10**6) for i in range(8)], [("x", 8 * 10**6)])]
        assert detect_mixer_usage(txs, mixer_addresses=set()).detected is False

    def test_known_mixer_address_in_inputs(self):
        txs = [tx("h1", [(TORNADO_ETH.upper(), 5 * 10**6)], [("x", 5 * 10**6)])]
        mu = detect_mixer_usage(txs, mixer_addresses={TORNADO_ETH.lower()})
        assert mu.detected is True
        assert "known_mixer_address" in mu.reasons
        # výstupní adresa v původním tvaru z TX (IoC)
        assert TORNADO_ETH.upper() in mu.mixer_addresses

    def test_known_mixer_address_in_outputs(self):
        txs = [tx("h2", [("a", 5 * 10**6)], [(TORNADO_ETH, 5 * 10**6)])]
        mu = detect_mixer_usage(txs, mixer_addresses={TORNADO_ETH.lower()})
        assert "known_mixer_address" in mu.reasons

    def test_bundled_mixer_list_nonempty(self):
        mixers = known_mixer_addresses()
        assert len(mixers) >= 10
        assert TORNADO_ETH.lower() in mixers

    @pytest.mark.parametrize("term", MIXER_TEXT_TERMS)
    def test_text_mentions_detected(self, term: str):
        found = detect_mixer_mentions(f"we moved funds through {term.title()} last night")
        assert term in found

    def test_mentions_sorted_unique_empty_ok(self):
        text = "TUMBLER and COINJOIN via wasabi wallet + Samourai."
        assert detect_mixer_mentions(text) == sorted(MIXER_TEXT_TERMS)
        assert detect_mixer_mentions("nothing to see here") == []

    def test_deterministic_repeated(self):
        txs = [tx("cj1", [(f"u{i}", 10**6) for i in range(9)], [("c0", 5 * 10**5)])]
        a, b = detect_mixer_usage(txs), detect_mixer_usage(txs)
        assert a.model_dump() == b.model_dump()


# ── K4.4 — fund flow diagram ───────────────────────────────────────────────


def _three_node_txs():
    """A(200 out) → B, C; B(50 out) → C. Deterministický mini-graph."""
    return [
        tx("t1", [("A", 200)], [("B", 100), ("C", 100)]),
        tx("t2", [("B", 50)], [("C", 50)]),
    ]


class TestK44FundFlow:
    def test_nodes_and_links(self):
        diagram = build_fund_flow(build_graph(_three_node_txs()))
        assert {n.id for n in diagram.nodes} == {"A", "B", "C"}
        assert {(l.source, l.target) for l in diagram.links} == {("A", "B"), ("A", "C"), ("B", "C")}
        assert all(l.value > 0 for l in diagram.links)

    def test_parallel_edges_aggregated(self):
        txs = [tx(f"p{i}", [("X", 100)], [("Y", 100)]) for i in range(3)]
        diagram = build_fund_flow(build_graph(txs))
        assert len(diagram.links) == 1
        assert diagram.links[0].value == 300

    def test_node_order_out_amount_desc_then_id(self):
        diagram = build_fund_flow(build_graph(_three_node_txs()))
        assert diagram.nodes[0].id == "A"      # max out_amount (200)
        rest = [n.id for n in diagram.nodes[1:]]
        assert sorted(rest) == ["B", "C"]

    def test_circle_layout_constant_radius(self):
        import math

        diagram = build_fund_flow(build_graph(_three_node_txs()))
        dists = [math.hypot(n.x or 0, n.y or 0) for n in diagram.nodes]
        assert all(d > 0 for d in dists)
        assert max(dists) - min(dists) < 0.05  # kruh — konstantní poloměr (rounding 2 des.)

    def test_single_node_center(self):
        """Jediný uzel (self-loop) → poloha v centru kruhu (0, 0)."""
        g = build_graph([tx("s1", [("A", 500)], [("A", 500)])])
        diagram = build_fund_flow(g)
        assert len(diagram.nodes) == 1 and (diagram.nodes[0].x or 0.0) == 0.0
        out = render_html(diagram)
        assert out.count("<circle") == 1

    def test_empty_diagram_renders(self):
        out = render_html(FlowDiagram())
        assert "<svg" in out and "</html>" in out

    def test_d3_json_shape_and_content(self):
        diagram = build_fund_flow(build_graph(_three_node_txs()))
        d3 = to_d3_json(diagram)
        assert set(d3.keys()) == {"nodes", "links"}
        node_ids = {n["id"] for n in d3["nodes"]}
        assert node_ids == {"A", "B", "C"}
        link_keys = {(l["source"], l["target"]) for l in d3["links"]}
        assert len(link_keys) == 3
        assert all(set(n.keys()) >= {"id", "category", "risk_score", "in_amount", "out_amount"}
                   for n in d3["nodes"])

    def test_html_self_contained_no_cdn(self):
        diagram = build_fund_flow(build_graph(_three_node_txs()))
        out = render_html(diagram)
        assert "<svg" in out and "</html>" in out
        # žádný externí zdroj — jediná http reference = SVG xmlns
        assert out.count("http://") == 1
        assert "https://" not in out
        assert 'src=' not in out and "<link" not in out.lower()
        for color in CATEGORY_COLORS.values():
            assert color in out  # legenda

    def test_deterministic_repeated(self):
        g = build_graph(_three_node_txs())
        d1, d2 = to_d3_json(build_fund_flow(g)), to_d3_json(build_fund_flow(g))
        h1, h2 = render_html(build_fund_flow(g)), render_html(build_fund_flow(g))
        assert d1 == d2 and h1 == h2

    @pytest.mark.parametrize(
        ("tags", "expected"),
        [
            (["mixer"], "mixer"),
            (["darknet_market"], "darknet"),
            (["exchange"], "exchange"),
            ([], "unknown"),
            # priorita: více tagů → první v _CATEGORY_PRIORITY
            (["exchange", "mixer"], "mixer"),
            (["darknet_market", "exchange"], "darknet"),
        ],
    )
    def test_category_priority(self, tags: list[str], expected: str):
        risk = RiskScore(address="x", score=95, level="high",
                         entries=[SanctionEntry(address="x", tags=tags)])
        assert category_for(risk) == expected

    def test_injected_risks_used(self):
        diagram = build_fund_flow(
            build_graph(_three_node_txs()),
            risks={"A": RiskScore(address="A", score=100, level="critical",
                                  entries=[SanctionEntry(address="A", tags=["mixer"])]),
                   "B": RiskScore(address="B", score=95, level="high",
                                  entries=[SanctionEntry(address="B", tags=["exchange"])])},
        )
        by_id = {n.id: n for n in diagram.nodes}
        assert by_id["A"].category == "mixer" and by_id["A"].risk_level == "critical"
        assert by_id["B"].category == "exchange"
        assert by_id["C"].category == "unknown"

    def test_node_stats_match_graph(self):
        g = build_graph(_three_node_txs())
        diagram = build_fund_flow(g)
        by_id = {n.id: n for n in diagram.nodes}
        assert by_id["A"].out_amount == 200 and by_id["B"].in_amount == 100
        assert by_id["C"].in_amount == 150


class TestK46Perf:
    def test_render_under_5s_for_1000_txs(self):
        """AK KPI: render < 5 s pro 1000 transakcí."""
        import time

        txs = [
            tx(f"t{i:04d}", [(f"a{i % 50}", 10**6), (f"b{i % 73}", 5 * 10**5)],
               [("c", 10**6) for _ in range(2)], ts=i)
            for i in range(1000)
        ]
        t0 = time.perf_counter()
        diagram = build_fund_flow(build_graph(txs))
        html_out = render_html(diagram)
        dt = time.perf_counter() - t0
        assert diagram.link_count > 0 and len(html_out) > 10_000
        assert dt < 5.0, f"KPI miss: {dt:.2f}s ≥ 5s pro 1000 TX"


# ── K4.5 — SWGDE report generátor ──────────────────────────────────────────


@pytest.fixture()
def case_env(tmp_path, monkeypatch):
    from stopa.data.db import CaseDB
    from stopa.models import Artifact, Case, EvidenceSource

    monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
    case = Case(name="k4-smoke")
    db = CaseDB(tmp_path / f"{case.id}.db")
    db.add_case(case)
    src = EvidenceSource(case_id=case.id, kind="file", path=str(tmp_path), size_bytes=10)
    db.add_source(src)
    art = Artifact(
        source_id=src.id,
        artifact_type="crypto_detection",
        title="[detected] 2 crypto addresses",
        details={
            "addresses": [
                {"raw_value": TORNADO_ETH, "chain": "ethereum"},
                {"raw_value": EU_BTC_BECH32, "chain": "bitcoin"},
            ]
        },
    )
    db.artifact_repo.upsert_artifact(art)
    yield case.id, db
    db.close()


class TestK45Report:
    def test_all_ten_sections_present_and_nonempty(self, case_env):
        from stopa.presentation.crypto_report import REPORT_SECTIONS, build_crypto_report_data

        case_id, db = case_env
        data = build_crypto_report_data(db, case_id)
        expected_keys = {k for k, _ in REPORT_SECTIONS}
        assert set(data.sections.keys()) == expected_keys and len(expected_keys) == 10
        for key in expected_keys:
            assert data.sections[key].strip(), f"prázdná sekce: {key}"

    def test_stats_counts(self, case_env):
        from stopa.presentation.crypto_report import build_crypto_report_data

        case_id, db = case_env
        data = build_crypto_report_data(db, case_id)
        assert data.stats["addresses_total"] == 2
        # Tornado (mixer → critical) + Garantex bech32 (exchange → high)
        assert data.stats["critical_risk_count"] >= 1
        assert data.stats["high_risk_count"] >= 1

    def test_markdown_section_order(self, case_env):
        from stopa.presentation.crypto_report import (
            REPORT_SECTIONS,
            build_crypto_report_data,
            render_markdown,
        )

        case_id, db = case_env
        md = render_markdown(build_crypto_report_data(db, case_id))
        positions = []
        for i, (_key, title) in enumerate(REPORT_SECTIONS, 1):
            heading = f"## {i}. {title}"
            assert heading in md, f"chybí nadpis: {heading}"
            positions.append(md.index(heading))
        assert positions == sorted(positions), "sekce nejsou v pořadí REPORT_SECTIONS"

    def test_html_self_contained(self, case_env):
        from stopa.presentation.crypto_report import REPORT_SECTIONS, generate_crypto_report

        case_id, db = case_env
        res = generate_crypto_report(db, case_id, "html")
        assert "<!DOCTYPE html>" in res.content and "</html>" in res.content
        for _key, title in REPORT_SECTIONS:
            assert title in res.content

    def test_json_parseable_sections_match(self, case_env):
        from stopa.presentation.crypto_report import REPORT_SECTIONS, generate_crypto_report

        case_id, db = case_env
        parsed = json.loads(generate_crypto_report(db, case_id, "json").content)
        assert set(parsed["sections"].keys()) == {k for k, _ in REPORT_SECTIONS}
        assert parsed["case_id"] == case_id
        assert parsed["stats"]["addresses_total"] == 2

    @pytest.mark.parametrize("fmt", ["md", "html", "json"])
    def test_sha256_digest_matches_content(self, case_env, fmt):
        from stopa.presentation.crypto_report import generate_crypto_report

        case_id, db = case_env
        res = generate_crypto_report(db, case_id, fmt)
        assert len(res.sha256_hex or "") == 64
        assert hashlib.sha256(res.content.encode()).hexdigest() == res.sha256_hex

    def test_ed25519_signature_roundtrip(self, case_env):
        from stopa.domain import integrity
        from stopa.presentation.crypto_report import generate_crypto_report

        case_id, db = case_env
        res = generate_crypto_report(db, case_id, "md")
        assert res.signature_b64 and res.public_key_b64
        assert integrity.verify_signature(res.public_key_b64, res.sha256_hex, res.signature_b64)

    def test_tampered_digest_rejected(self, case_env):
        from stopa.domain import integrity
        from stopa.presentation.crypto_report import generate_crypto_report

        case_id, db = case_env
        res = generate_crypto_report(db, case_id, "md")
        other_digest = hashlib.sha256(b"tampered content").hexdigest()
        bad_sig = integrity.sign_hash(db.ensure_integrity_key()[0], other_digest)
        assert not integrity.verify_signature(res.public_key_b64, res.sha256_hex, bad_sig)

    def test_graceful_degradation_without_crypto_backend(self, case_env, monkeypatch):
        """Bez kryptobackendu (RuntimeError z ensure_integrity_key) → podpis None, digest zůstává."""
        from stopa.presentation.crypto_report import generate_crypto_report

        case_id, db = case_env
        monkeypatch.setattr(db, "ensure_integrity_key", lambda: (_ for _ in ()).throw(RuntimeError("no cryptography")))
        res = generate_crypto_report(db, case_id, "md")
        assert res.signature_b64 is None
        assert len(res.sha256_hex or "") == 64

    def test_out_path_written(self, case_env, tmp_path):
        from stopa.presentation.crypto_report import generate_crypto_report

        case_id, db = case_env
        out = tmp_path / "custom" / "report.md"
        res = generate_crypto_report(db, case_id, "md", out=out)
        assert out.exists() and out.read_text(encoding="utf-8") == res.content

    def test_timeline_with_injected_txs(self, case_env):
        from stopa.presentation.crypto_report import build_crypto_report_data

        case_id, db = case_env
        data = build_crypto_report_data(
            db, case_id, txs_by_addr={TORNADO_ETH: [tx("seed01", [(EU_BTC_BECH32, 5_000_000)],
                                                        [("bc1qpool", 7_900_000)])]}
        )
        assert "seed01" in data.sections["transaction_timeline"]
        assert "2023-11-14" in data.sections["transaction_timeline"]  # ts=1.7e9 epoch s

    def test_empty_case_graceful(self, tmp_path, monkeypatch):
        from stopa.data.db import CaseDB
        from stopa.models import Case
        from stopa.presentation.crypto_report import build_crypto_report_data

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        case = Case(name="k4-prazdny")
        db = CaseDB(tmp_path / f"{case.id}.db")
        db.add_case(case)
        try:
            data = build_crypto_report_data(db, case.id)
            assert data.stats["addresses_total"] == 0
            assert "No wallet artifacts found" in data.sections["wallet_discovery"]
        finally:
            db.close()


# ── CLI E2E — stopa darkweb <case> / stopa crypto-report <case> ───────────


@pytest.fixture()
def darkweb_env(tmp_path, monkeypatch):
    """Případ s textovým zdrojem obsahujícím ransom note + mixer zmínku."""
    from stopa.data.db import CaseDB
    from stopa.models import Case, EvidenceSource

    monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
    case = Case(name="k4-cli-smoke")
    db = CaseDB(tmp_path / f"{case.id}.db")
    db.add_case(case)
    note_file = tmp_path / "ransom_note.txt"
    note_file.write_text(
        "Dear Victim, all your files have been encrypted!\n"
        "This is LockBit 3.0 ransomware. Pay 2 BTC to bc1qwtz3zv95x2flu4w26kgfepf529z50r2sqc5zml.\n"
        "We used coinjoin tumbler for the exit wallet.\n",
        encoding="utf-8",
    )
    src = EvidenceSource(case_id=case.id, kind="file", path=str(note_file), size_bytes=10)
    db.add_source(src)
    yield case.id, note_file, tmp_path
    db.close()


class TestK4CliDarkweb:
    @staticmethod
    def _ns(case_id: str, json_mode: bool = False, file_list=None):
        return argparse.Namespace(case_id=case_id, file=file_list, json=json_mode)

    def test_human_output(self, darkweb_env, capsys):
        from stopa.cli import cmd_darkweb

        case_id, _note, _tmp = darkweb_env
        rc = cmd_darkweb(self._ns(case_id))
        out = capsys.readouterr().out
        assert rc == 0
        assert "RANSOM NOTE" in out and "lockbit" in out.lower()
        assert EU_BTC_BECH32 in out
        assert "MIXER ZMÍNKY" in out and "coinjoin" in out

    def test_json_output(self, darkweb_env, capsys):
        from stopa.cli import cmd_darkweb

        case_id, _note, _tmp = darkweb_env
        rc = cmd_darkweb(self._ns(case_id, json_mode=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["files_scanned"] >= 1
        assert len(data["ransom_notes"]) == 1
        note = data["ransom_notes"][0]
        assert note["family"] == "lockbit" and note["is_ransom_note"] is True
        assert EU_BTC_BECH32 in note["addresses"]
        assert "coinjoin" in data["mixer_mentions"]

    def test_explicit_file_flag(self, darkweb_env, capsys):
        """--file skenuje soubor mimo zdroje případu."""
        from stopa.cli import cmd_darkweb

        case_id, _note, tmp = darkweb_env
        mp_file = tmp / "mp.txt"
        mp_file.write_text(
            "-----BEGIN PGP PUBLIC KEY BLOCK-----\nX\n"
            "-----END PGP PUBLIC KEY BLOCK-----\n"
            f"vendor seller for sale price: shipping escrow pay {EU_BTC_BECH32}\n",
            encoding="utf-8",
        )
        rc = cmd_darkweb(self._ns(case_id, json_mode=True, file_list=[str(mp_file)]))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0 and len(data["marketplace_evidence"]) == 1
        mp = data["marketplace_evidence"][0]
        assert mp["pgp_keys"] == 1 and EU_BTC_BECH32 in mp["addresses"]

    def test_empty_case_graceful(self, tmp_path, monkeypatch):
        import contextlib
        import io

        from stopa.cli import cmd_darkweb
        from stopa.data.db import CaseDB
        from stopa.models import Case

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        case = Case(name="k4-cli-prazdny")
        db = CaseDB(tmp_path / f"{case.id}.db")
        db.add_case(case)
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cmd_darkweb(self._ns(case.id, json_mode=True))
            assert rc == 0
            data = json.loads(buf.getvalue())
            assert data["files_scanned"] == 0 and data["ransom_notes"] == []
        finally:
            db.close()


class TestK4CliCryptoReport:
    @staticmethod
    def _ns(case_id: str, fmt: str = "md", json_mode: bool = False, out=None):
        return argparse.Namespace(case_id=case_id, format=fmt, out=out, json=json_mode)

    def test_md_human_output_and_file(self, case_env, capsys):
        from stopa.cli import cmd_crypto_report

        case_id, _db = case_env
        rc = cmd_crypto_report(self._ns(case_id))
        out = capsys.readouterr().out
        assert rc == 0
        assert "K4.5 SWGDE report" in out and "[md]" in out
        assert "addresses_total: 2" in out
        # výchozí cesta: <db_dir>/reports/<case>.crypto_report.md
        from stopa.cli import _db_dir

        expected = _db_dir() / "reports" / f"{case_id}.crypto_report.md"
        assert expected.exists() and "Executive Summary" in expected.read_text(encoding="utf-8")

    def test_json_payload(self, case_env, capsys):
        from stopa.cli import cmd_crypto_report

        case_id, _db = case_env
        rc = cmd_crypto_report(self._ns(case_id, fmt="json", json_mode=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert "content" not in data and "out" in data
        assert len(data["sha256_hex"] or "") == 64
        assert data["stats"]["addresses_total"] == 2

    def test_html_format_file(self, case_env):
        from stopa.cli import cmd_crypto_report

        case_id, _db = case_env
        rc = cmd_crypto_report(self._ns(case_id, fmt="html"))
        assert rc == 0
        from stopa.cli import _db_dir

        expected = _db_dir() / "reports" / f"{case_id}.crypto_report.html"
        body = expected.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in body and "</html>" in body

    def test_txcache_picked_up(self, case_env, capsys):
        """Seeded K3 TxCache → timeline sekce + transactions_cached stat."""
        from stopa.cli import _db_dir, cmd_crypto_report
        from stopa.domain.crypto.onchain_api import TxCache

        case_id, _db = case_env
        TxCache(_db_dir() / f"{case_id}.txcache.json").save({
            TORNADO_ETH: [tx("seed01", [(EU_BTC_BECH32, 5_000_000)], [("bc1qpool", 7_900_000)])]
        })
        rc = cmd_crypto_report(self._ns(case_id, fmt="json", json_mode=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["stats"]["transactions_cached"] >= 1
