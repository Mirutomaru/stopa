"""STOPA P2-5 Wave 1 — Threat Intelligence Workspace: doménová sada.

Pokrývá AK návrhu (docs/P2_DESIGNS.md §P2-5):

- deterministický matching na syntetickém case → přesné hit seznamy;
- stáří klasifikace správně po hranicích prahů (boundary testy);
- STIX roundtrip: import → export = identický kanonický bundle.

Data vrstva (tabulky ioc_feed_items/intel_matches) + CLI/Web = Wave 2.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from stopa.domain.entities import EntityOccurrence
from stopa.domain.threat_intel import (
    DEFAULT_FRESH_DAYS,
    DEFAULT_STALE_DAYS,
    MAX_EVIDENCE,
    IoC,
    classify_age,
    export_bundle,
    feed_summary,
    ioc_id,
    match_iocs,
)
from stopa.models import Artifact, FileRecord

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64


def _ioc(kind: str, value: str, **kw) -> IoC:
    return IoC(kind=kind, value=value, acquired_at=T0, **kw)


# ── kanonizace + validace IoC ────────────────────────────────────


class TestIoCCanonicalization:
    def test_ip_v4_strips_whitespace(self):
        assert _ioc("ip", " 10.0.0.1 ").value == "10.0.0.1"

    def test_ip_v6_lowercase_compressed(self):
        assert _ioc("ip", "2001:DB8::0001").value == "2001:db8::1"

    @pytest.mark.parametrize(
        "bad", ["999.1.1.1", "", "not-an-ip", "010.0.0.1"]  # vedoucí nula = ambiguita (Python ≥3.9.5)
    )
    def test_ip_invalid(self, bad):
        with pytest.raises(ValueError, match="Neplatná IP adresa IoC"):
            _ioc("ip", bad)

    def test_domain_lowercase_canonical(self):
        assert _ioc("domain", "Example.COM.").value == "example.com"

    def test_url_host_only(self):
        # cesta/port/schéma se normalizují na hostname (E4 kanonika)
        assert _ioc("url", "https://Example.COM:8443/path?q=1").value == "example.com"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (SHA_A.upper(), SHA_A),  # hex → lowercase
            (f"sha256:{SHA_B}", SHA_B),  # prefix sha256:
            (f"md5={'c' * 32}", "c" * 32),  # prefix md5=
        ],
    )
    def test_hash_canonical_forms(self, raw, expected):
        assert _ioc("hash", raw).value == expected

    @pytest.mark.parametrize("bad", ["d" * 65, "xyz", ""])  # délka mimo 32/40/64
    def test_hash_invalid_length(self, bad):
        with pytest.raises(ValueError, match="Neplatný hash IoC"):
            _ioc("hash", bad)

    def test_unknown_kind_rejected(self):
        with pytest.raises(ValueError, match="Neznámý druh IoC"):
            _ioc("ftp", "ftp.example.com")

    @pytest.mark.parametrize("tlp", ["WHITE", "GREEN", "AMBER", "RED"])
    def test_all_tlp_levels_accepted(self, tlp):
        assert _ioc("domain", "example.com", tlp=tlp).tlp == tlp

    def test_invalid_tlp_rejected_case_sensitive(self):
        with pytest.raises(ValueError, match="Neplatná TLP úroveň"):
            _ioc("domain", "example.com", tlp="blue")


# ── stáří intel dat (boundary AK) ────────────────────────────────


class TestClassifyAge:
    def test_fresh_below_threshold(self):
        assert classify_age(T0, T0 + timedelta(days=29)) == "fresh"

    def test_zero_age_is_fresh(self):
        assert classify_age(T0, T0) == "fresh"

    def test_exactly_30_days_is_stale(self):
        # hranice striktní: věk == fresh_days → starší třída
        assert classify_age(T0, T0 + timedelta(days=DEFAULT_FRESH_DAYS)) == "stale"

    def test_between_thresholds_is_stale(self):
        assert classify_age(T0, T0 + timedelta(days=45)) == "stale"

    def test_exactly_90_days_is_old(self):
        assert classify_age(T0, T0 + timedelta(days=DEFAULT_STALE_DAYS)) == "old"

    def test_beyond_stale_is_old(self):
        assert classify_age(T0, T0 + timedelta(days=365)) == "old"

    def test_custom_thresholds_configurable(self):
        assert classify_age(T0, T0 + timedelta(days=8), fresh_days=7, stale_days=14) == "stale"
        assert classify_age(T0, T0 + timedelta(days=3), fresh_days=7, stale_days=14) == "fresh"

    def test_naive_datetimes_treated_as_utc(self):
        naive0 = datetime(2026, 1, 1)
        assert classify_age(naive0, naive0 + timedelta(days=5)) == "fresh"


# ── STIX 2.1 bundle (roundtrip AK) ───────────────────────────────

MIXED: list[IoC] = [
    _ioc("ip", "10.0.0.1", tlp="AMBER", source="feed-a"),
    _ioc("ip", "2001:db8::1", tlp="RED"),
    _ioc("domain", "c2.example.net", tlp="GREEN", source="manual"),
    _ioc("url", "https://evil.example.org/payload?x=1#frag", tlp="WHITE"),
    _ioc("hash", SHA_A, source="malware-sig"),
    _ioc("hash", "c" * 32),  # MD5 délka
]


class TestStixBundle:
    def test_export_deterministic_input_order_independent(self):
        assert export_bundle(MIXED) == export_bundle(list(reversed(MIXED)))

    def test_objects_sorted_by_id_in_json(self):
        doc = json.loads(export_bundle(MIXED))
        ids = [o["id"] for o in doc["objects"]]
        assert ids == sorted(ids)

    def test_roundtrip_identity_full_mixed_kinds(self):
        # AK: import → export = identický kanonický bundle
        once = export_bundle(MIXED)
        again = export_bundle(self._import(once))
        assert again == once

    def _import(self, text):
        from stopa.domain.threat_intel import import_bundle

        return import_bundle(text)

    def test_import_sorted_by_id_and_metadata_preserved(self):
        from stopa.domain.threat_intel import import_bundle

        got = import_bundle(export_bundle(MIXED))
        assert [ioc_id(i) for i in got] == sorted(ioc_id(i) for i in got)
        by_val = {i.value: i for i in got}
        assert by_val["10.0.0.1"].tlp == "AMBER"
        assert by_val["10.0.0.1"].source == "feed-a"
        assert by_val["c2.example.net"].acquired_at == T0

    def test_url_roundtrips_as_domain_same_identity(self):
        from stopa.domain.threat_intel import import_bundle

        url_ioc = _ioc("url", "https://evil.example.org/payload")
        got = import_bundle(export_bundle([url_ioc]))
        assert len(got) == 1
        assert got[0].kind == "domain"  # STIX třída host — dokumentovaný ztrátový krok
        assert got[0].value == url_ioc.value
        assert ioc_id(got[0]) == ioc_id(url_ioc)

    def test_pattern_per_kind(self):
        doc = json.loads(export_bundle(MIXED))
        patterns = {o["pattern"] for o in doc["objects"]}
        assert "[ipv4-addr:value = '10.0.0.1']" in patterns
        assert "[ipv6-addr:value = '2001:db8::1']" in patterns
        assert "[domain-name:value = 'c2.example.net']" in patterns
        assert f"[file:hashes.'SHA-256' = '{SHA_A}']" in patterns
        assert "[file:hashes.'MD5' = '" + "c" * 32 + "']" in patterns

    def test_bundle_id_deterministic_and_set_dependent(self):
        full = json.loads(export_bundle(MIXED))["id"]
        partial = json.loads(export_bundle(MIXED[:1]))["id"]
        assert full != partial
        assert full == json.loads(export_bundle(list(reversed(MIXED))))["id"]

    @pytest.mark.parametrize(
        ("text", "exc"),
        [
            ("{neplatné JSON", ValueError),  # ne-JSON
            ('{"type": "report", "objects": []}', ValueError),  # špatný kořen
            ('{"type": "bundle"}', TypeError),  # chybí objects (seznam)
            (
                '{"type": "bundle", "objects": [{"type": "indicator", "pattern": "[cizí-tvar = 1]"}]}',
                ValueError,
            ),  # neznámý pattern dialektu
        ],
    )
    def test_import_fail_closed(self, text, exc):
        from stopa.domain.threat_intel import import_bundle

        with pytest.raises(exc):
            import_bundle(text)

    def test_hash_algo_length_mismatch_rejected(self):
        from stopa.domain.threat_intel import import_bundle

        hexval = "d" * 32
        pattern = "[file:hashes.'SHA-256' = '" + hexval + "']"
        bad = json.dumps({"type": "bundle", "objects": [{"type": "indicator", "pattern": pattern}]})
        with pytest.raises(ValueError, match="délka"):
            import_bundle(bad)

    def test_created_roundtrip_acquired_at_exact(self):
        from stopa.domain.threat_intel import import_bundle

        got = import_bundle(export_bundle([_ioc("domain", "x.example.com")]))[0]
        assert got.acquired_at == T0


# ── matching IoC × case artefakty/entity (AK) ────────────────────


def _occ(kind: str, value: str, artifact_id: str = "art-1", ts=None) -> EntityOccurrence:
    return EntityOccurrence(
        kind=kind,
        value=value,
        source_id="src-1",
        artifact_id=artifact_id,
        file_id=None,
        rel_path=f"/{artifact_id}.txt",
        ts_utc=ts,
        raw_value="",
    )


def _file(rel_path: str, sha256: str | None, mtime=None) -> FileRecord:
    return FileRecord(
        source_id="src-1",
        rel_path=rel_path,
        name=rel_path.rsplit("/", 1)[-1],
        size_bytes=100,
        sha256=sha256,
        mtime=mtime,
    )


def _artifact(artifact_id: str, title: str = "", **details) -> Artifact:
    return Artifact(id=artifact_id, artifact_type="generic_log", title=title, details=details)


class TestMatchIocs:
    def test_hash_matches_entity_and_file(self):
        occs = [_occ("hash", SHA_A, "art-1"), _occ("email", "a@b.c")]
        files = [_file("/docs/a.pdf", SHA_A.upper(), T0), _file("/docs/b.pdf", SHA_B)]
        m = match_iocs([_ioc("hash", SHA_A)], occs, files)
        kinds = sorted(x.match_kind for x in m)
        assert kinds == ["entity", "file_hash"]  # přesné hit seznamy — jen tato dvě
        ent = next(x for x in m if x.match_kind == "entity")
        fh = next(x for x in m if x.match_kind == "file_hash")
        assert [e["artifact_id"] for e in ent.evidence] == ["art-1"]
        assert [e["rel_path"] for e in fh.evidence] == ["/docs/a.pdf"]
        assert fh.first_seen is not None  # mtime souboru

    def test_hash_no_match_for_other_hashes(self):
        occs = [_occ("hash", SHA_B)]
        files = [_file("/x.bin", SHA_A)]
        assert match_iocs([_ioc("hash", "e" * 64)], occs, files) == []

    def test_domain_matches_url_host_canonical_only(self):
        # přesný kanonický tvar: www.example.com ≠ example.com (jiný host)
        occs = [_occ("url_host", "example.com"), _occ("url_host", "www.example.com")]
        m = match_iocs([_ioc("domain", "EXAMPLE.COM")], occs)
        assert len(m) == 1
        assert [e["artifact_id"] for e in m[0].evidence] == ["art-1"]

    def test_url_ioc_matches_same_hosts_as_domain(self):
        # URL s cestou/portem → hostname; stejný hit jako domain IoC
        occs = [_occ("url_host", "evil.example.org")]
        url_m = match_iocs([_ioc("url", "https://evil.example.org:443/x")], occs)
        dom_m = match_iocs([_ioc("domain", "evil.example.org")], occs)
        assert len(url_m) == 1 and url_m[0].match_kind == "entity"
        # shoda všech polí kromě deklarovaného druhu (url vs domain — STIX třída host)
        for u, d in zip(url_m, dom_m):
            assert u.ioc_id == d.ioc_id  # ID prostor sdílený přes _stix_class
            assert (u.value, u.match_kind, u.evidence, u.first_seen, u.last_seen) == (
                d.value,
                d.match_kind,
                d.evidence,
                d.first_seen,
                d.last_seen,
            )

    def test_ip_match_in_artifact_text(self):
        arts = [
            _artifact("art-1", title="connect to 10.0.0.1 port 443"),
            _artifact("art-2", payload_url="http://10.0.0.1/x"),
            _artifact("art-3", note="subnet 172.16.0.0/12"),
        ]
        m = match_iocs([_ioc("ip", "10.0.0.1")], [], [], arts)
        assert len(m) == 1
        assert m[0].match_kind == "artifact_text"
        assert [e["artifact_id"] for e in m[0].evidence] == ["art-1", "art-2"]

    def test_ip_token_boundary_no_substring_hit(self):
        # „10.0.0.1“ neshodne uvnitř „110.0.0.15“ ani „10.0.0.15“
        arts = [_artifact("art-1", note="see 110.0.0.15 and 10.0.0.15")]
        assert match_iocs([_ioc("ip", "10.0.0.1")], [], [], arts) == []

    def test_ip_requires_artifacts_argument(self):
        # bez artifacts=None IP deterministicky nevystihne nic; ostatní druhy nezávislé
        occs = [_occ("hash", SHA_A)]
        m = match_iocs([_ioc("ip", "10.0.0.1"), _ioc("hash", SHA_A)], occs, [])
        assert len(m) == 1 and m[0].match_kind == "entity"

    def test_empty_case_no_matches(self):
        iocs = [_ioc("ip", "10.0.0.1"), _ioc("domain", "a.b.c"), _ioc("hash", SHA_A)]
        assert match_iocs(iocs, [], [], []) == []

    def test_deterministic_order_independent_of_inputs(self):
        occs = [_occ("url_host", "example.com", "art-b"), _occ("hash", SHA_A, "art-a")]
        files = [_file("/a.pdf", SHA_A)]
        iocs = [_ioc("domain", "example.com"), _ioc("hash", SHA_A), _ioc("ip", "1.2.3.4")]
        base = match_iocs(iocs, occs, files)
        shuffled = match_iocs(list(reversed(iocs)), list(reversed(occs)), list(reversed(files)))
        assert base == shuffled  # dataclass rovnost — plná determinita

    def test_evidence_cap_and_sorting(self):
        many = [_occ("hash", SHA_A, f"art-{i:03d}", T0 + timedelta(hours=i)) for i in range(30)]
        m = match_iocs([_ioc("hash", SHA_A)], many)
        assert len(m[0].evidence) == MAX_EVIDENCE  # strop 25 (konzistentní s E4)
        ids = [e["artifact_id"] for e in m[0].evidence]
        assert ids == sorted(ids)[:MAX_EVIDENCE]
        assert m[0].first_seen == T0.isoformat()
        assert m[0].last_seen == (T0 + timedelta(hours=29)).isoformat()

    def test_match_kind_values_in_check_set(self):
        # odpovídá CHECK constraintu tabulky intel_matches (v24)
        occs = [_occ("hash", SHA_A), _occ("url_host", "a.b.c")]
        arts = [_artifact("art-1", note="ip 9.8.7.6 here")]
        m = match_iocs(
            [_ioc("hash", SHA_A), _ioc("domain", "A.B.C"), _ioc("ip", "9.8.7.6")], occs, [], arts
        )
        assert {x.match_kind for x in m} <= {"entity", "file_hash", "artifact_text"}

    def test_ioc_metadata_propagated_to_match(self):
        ioc = _ioc("domain", "c2.example.net", tlp="RED", source="manual")
        occs = [_occ("url_host", "c2.example.net")]
        m = match_iocs([ioc], occs)
        assert (m[0].tlp, m[0].source, m[0].value) == ("RED", "manual", "c2.example.net")


# ── feed shrnutí + schéma v24 ────────────────────────────────────


class TestFeedSummary:
    def test_counts_and_age_with_injected_now(self):
        iocs = [
            _ioc("domain", "a.b.c"),  # věk 0 → fresh (acquired T0, now T0)
            IoC(kind="ip", value="1.1.1.1", acquired_at=T0 - timedelta(days=45)),  # stale
            IoC(kind="hash", value=SHA_A, acquired_at=T0 - timedelta(days=200)),  # old
        ]
        s = feed_summary(iocs, now=T0)
        assert s["total"] == 3
        assert s["by_age"] == {"fresh": 1, "stale": 1, "old": 1}
        assert s["by_kind"] == {"domain": 1, "hash": 1, "ip": 1}
        assert s["tlp_levels"] == ["GREEN"]

    def test_deterministic_sorted_by_kind(self):
        iocs = [_ioc("ip", "2.2.2.2"), _ioc("domain", "x.y.z")]
        s = feed_summary(iocs, now=T0)
        assert list(s["by_kind"].keys()) == sorted(s["by_kind"])


class TestSchemaV24:
    def test_version_bumped_and_intel_tables_in_schema(self):
        from stopa.data.schema import SCHEMA, SCHEMA_VERSION

        assert SCHEMA_VERSION == 26  # v24 = P2-5 intel; v25 = P3-5 rule matching; v26 = P3-3 klasifikace souborů
        assert "CREATE TABLE IF NOT EXISTS ioc_feed_items" in SCHEMA
        assert "CREATE TABLE IF NOT EXISTS intel_matches" in SCHEMA
        assert "CHECK (kind IN ('ip', 'domain', 'hash', 'url'," in SCHEMA  # v25 += yara_rule/sigma_tpl
        assert "'yara_rule', 'sigma_tpl'))" in SCHEMA
