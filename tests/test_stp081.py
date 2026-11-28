"""STP-081 / vlna 37 — E2E diferenciální validace Apache/Nginx combined access log parseru (§7).

STOPA cesta (``extract_access_log_artifacts``) vs. nezávislá referenční cesta
(``text_ref._ref_apache_combined``, stdlib only) nad stejnou fixturou
``tests/reference_datasets/access_log/access_sample.log`` (SHA-256 pin v manifestu).

Kontrakt normalizace (smlouva manifestu, obě cesty stejný tvar): ``user``,
``referer``, ``user_agent`` a ``bytes`` = explicitní None pro ``-``, status/bytes
int, protocol jen ve formě ``HTTP/x[.y]`` jinak None; epoch sekundy (int) spočítá
každá cesta nezávisle (STOPA calendar.timegm / reference Hinnant).

Duplicitní join klíč ip+timestamp+method+path se páruje po sobě deterministicky
(§3.2) — fixture obsahuje jeden takový pár (alice GET /index.html, řádek 1 a 8).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stopa.artifacts.access_log_extract import extract_access_log_artifacts
from stopa.diffref import DIFFREF_ADAPTERS, run_both_sides
from stopa.diffref.text_ref import (
    ACCESS_LOG_FIELD_KEYS,
    _ref_apache_combined,
    load_text_manifest,
    read_reference_entries,
    run_stopa_access_log,
)
from stopa.domain.differential import build_report, normalize_dataset

DS = Path(__file__).parent / "reference_datasets" / "access_log"
FIXTURE = DS / "access_sample.log"
MANIFEST = DS / "manifest.json"
GOLDEN = DS / "expected_access_sample.json"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def join_keys(manifest: dict) -> dict[str, tuple[str, ...]]:
    return {k: tuple(v) for k, v in manifest["join_keys"].items()}  # type: ignore[union-attr]


@pytest.fixture(scope="module")
def both_sides(join_keys):
    stopa_entries, adapter = run_both_sides("access_log", FIXTURE)
    ref_entries = adapter.read_reference(FIXTURE, json.loads(MANIFEST.read_text(encoding="utf-8")))
    return (
        normalize_dataset(stopa_entries, join_keys=join_keys),
        normalize_dataset(ref_entries, join_keys=join_keys),
    )


class TestManifest:
    def test_valid(self, manifest):
        assert manifest["version"] == 1
        assert manifest["parser_id"] == "access_log"
        assert set(manifest["fixtures"][0]) == {"file", "sha256", "variant"}
        assert manifest["join_keys"]["access_log_entry"] == ["ip", "timestamp", "method", "path"]

    def test_load_text_manifest_ok(self):
        m = load_text_manifest(MANIFEST)
        assert m["parser_id"] == "access_log"  # type: ignore[index]

    @pytest.mark.parametrize(
        ("mutate", "match"),
        [
            (lambda d: d.update(version=2), "verze manifestu"),
            (lambda d: d.pop("parser_id"), "parser_id"),
            (lambda d: d.pop("reference_tool"), "reference_tool"),
            (lambda d: d.update(join_keys={}), "join_keys"),
            (lambda d: d.update(fixtures=[]), "fixtures"),
        ],
    )
    def test_invalid_manifests(self, tmp_path: Path, mutate, match):
        base = json.loads(MANIFEST.read_text(encoding="utf-8"))
        mutate(base)
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps(base), encoding="utf-8")
        with pytest.raises(ValueError, match=match):
            load_text_manifest(p)

    def test_unknown_variant_rejected(self, tmp_path: Path):
        base = json.loads(MANIFEST.read_text(encoding="utf-8"))
        base["fixtures"][0]["variant"] = "windows_apache"  # neexistující varianta
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps(base), encoding="utf-8")
        with pytest.raises(ValueError, match="varianta"):
            load_text_manifest(p)


class TestReferenceSide:
    def test_count_8_events(self):
        text = FIXTURE.read_text(encoding="utf-8")
        assert len(_ref_apache_combined(text)) == 8

    def test_raw_lines_vs_events(self):
        # 14 raw řádků, z toho 6 se přeskočí (pokračování, neplatný měsíc, krátký
        # status, jednocyfrový den, nezavřený uvozovka, prázdný) → 8 událostí
        lines = FIXTURE.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 14
        assert sum(1 for l in lines if not l.strip()) == 1

    def test_dash_normalization_explicit_none(self):
        text = FIXTURE.read_text(encoding="utf-8")
        records = _ref_apache_combined(text)
        by_path = {r["fields"]["path"]: r for r in records}
        # HEAD /health: user (%u), referer, ua, bytes = "-" → explicitní None.
        # "bob" je ident v poli %l — parsuje se, ale do detailů neukládá (smlouva).
        health = by_path["/health"]["fields"]
        assert (health["user"], health["referer"], health["user_agent"], health["bytes"]) == (
            None,
            None,
            None,
            None,
        )
        # alice GET /index.html: referer URL verbatim
        index = by_path["/index.html"]["fields"]
        assert index["referer"] == "http://www.example.com/start.html"
        assert index["user_agent"].startswith("Mozilla/4.08")

    def test_size_zero_and_leading_zeros(self):
        text = FIXTURE.read_text(encoding="utf-8")
        by_path = {r["fields"]["path"]: r for r in _ref_apache_combined(text)}
        assert by_path["/submit.php?next=1"]["fields"]["bytes"] == 0  # "0" zůstává 0
        assert by_path["/leading-zero.html"]["fields"]["bytes"] == 461  # "0461" → int

    def test_protocol_none_when_missing_form(self):
        text = FIXTURE.read_text(encoding="utf-8")
        records = _ref_apache_combined(text)
        by_path = {r["fields"]["path"]: r for r in records}
        assert by_path["/no-protocol"]["fields"]["protocol"] is None  # request bez HTTP/x[.y]
        assert all(
            r["fields"]["protocol"] is not None
            for r in records
            if r["fields"]["path"] != "/no-protocol"
        )

    def test_epoch_oracle_independent(self):
        # nezávislý oracle (platformní datetime — třetí implementace vedle
        # calendar.timegm a Hinnant) + ostrá regrese na minutový slice offsetu:
        # -0530 stěna 14:18:56 == +0000 stěna 19:48:56 → stejná epocha
        text = FIXTURE.read_text(encoding="utf-8")
        by_path = {r["fields"]["path"]: r for r in _ref_apache_combined(text)}
        oracle = int(
            datetime(2003, 8, 7, 14, 18, 56, tzinfo=timezone(timedelta(hours=-5, minutes=-30))).timestamp()
        )
        assert by_path["/tz-negative.html?q=a+b&x=1"]["ts"] == oracle
        assert by_path["/tz-zero.html"]["ts"] == oracle

    def test_query_verbatim_no_unescape(self):
        text = FIXTURE.read_text(encoding="utf-8")
        records = _ref_apache_combined(text)
        rec = next(r for r in records if "/tz-negative" in r["fields"]["path"])
        assert rec["fields"]["path"] == "/tz-negative.html?q=a+b&x=1"  # "+" verbatim


class TestStopaSide:
    def test_count_8_artifacts(self):
        arts = extract_access_log_artifacts(FIXTURE)
        assert len(arts) == 8

    def test_artifact_contract(self):
        arts = {a.details["path"]: a for a in extract_access_log_artifacts(FIXTURE)}
        index = arts["/index.html"]
        assert index.artifact_type == "access_log_entry"
        # Apache %t nese rok + TZ → přesný UTC čas (na rozdíl od syslogu)
        assert index.timestamp == datetime(2003, 8, 7, 17, 48, 56, tzinfo=timezone.utc)
        assert index.title == "GET /index.html"
        assert index.confidence == 0.8
        d = index.details
        assert (d["ip"], d["user"]) == ("192.168.1.10", "alice")
        assert d["status"] == 200 and d["bytes"] == 1461
        assert d["referer"] == "http://www.example.com/start.html"

    def test_explicit_none_details_present(self):
        arts = {a.details["path"]: a for a in extract_access_log_artifacts(FIXTURE)}
        health = arts["/health"].details
        # klíče se dodávají explicitně (§3.3) — None ≠ chybějící klíč
        for key in ("user", "referer", "bytes"):
            assert key in health and health[key] is None

    def test_run_stopa_access_log_shape(self):
        entries = run_stopa_access_log(FIXTURE)
        assert len(entries) == 8
        assert all(e["type"] == "access_log_entry" for e in entries)
        # epoch int (ne datetime — normalize_ts akceptuje čísla), pevná množina klíčů
        assert all(isinstance(e["ts"], int) for e in entries)
        assert all(
            tuple(sorted(e["fields"])) == tuple(sorted(ACCESS_LOG_FIELD_KEYS)) for e in entries
        )


class TestE2EParity:
    def test_no_diffs(self, both_sides):
        stopa_norm, ref_norm = both_sides
        report = build_report(
            parser="access_log",
            stopa_records=stopa_norm,
            ref_records=ref_norm,
            join_keys={"access_log_entry": ("ip", "timestamp", "method", "path")},
        )
        assert report.differences == ()

    def test_identical_pct_100(self, both_sides):
        stopa_norm, ref_norm = both_sides
        payload = json.loads(
            build_report(
                parser="access_log",
                stopa_records=stopa_norm,
                ref_records=ref_norm,
                join_keys={"access_log_entry": ("ip", "timestamp", "method", "path")},
            ).to_json()
        )
        assert payload["identical_pct"] == 100.0
        assert payload["stopa_records"] == 8
        assert payload["ref_records"] == 8

    def test_duplicate_join_key_pairing_sequential(self, both_sides):
        # §3.2: dva záznamy se stejným join klíčem (alice GET /index.html) se párují po sobě
        stopa_norm, ref_norm = both_sides
        dup_stopa = [r for r in stopa_norm if r.fields.get("path") == "/index.html"]
        dup_ref = [r for r in ref_norm if r.fields.get("path") == "/index.html"]
        assert len(dup_stopa) == 2 and len(dup_ref) == 2
        # byte-identické řádky → pole se shodují na obou cestách v pořadí fixtury
        for rec in (*dup_stopa, *dup_ref):
            assert rec.fields["user"] == "alice"
            assert rec.ts_epoch is not None


class TestGolden:
    def test_golden_count(self):
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        assert len(golden) == 8

    def test_golden_matches_reference_side(self, join_keys):
        # byte-stejný tvar po JSON serializaci (E2E smlouva §4)
        ref_entries = read_reference_entries(FIXTURE, json.loads(MANIFEST.read_text(encoding="utf-8")))
        norm = normalize_dataset(ref_entries, join_keys=join_keys)
        actual = [{"type": r.type, "ts_epoch": r.ts_epoch, "fields": dict(r.fields)} for r in norm]
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        assert actual == golden


class TestShaPin:
    def test_sha_pin_matches_fixture(self):
        import hashlib

        base = json.loads(MANIFEST.read_text(encoding="utf-8"))
        pinned = base["fixtures"][0]["sha256"]
        actual = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        assert actual == pinned

    def test_sha_drift_rejected(self, tmp_path: Path):
        base = json.loads(MANIFEST.read_text(encoding="utf-8"))
        base["fixtures"][0]["sha256"] = "0" * 64
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps(base), encoding="utf-8")
        m = load_text_manifest(p)
        with pytest.raises(ValueError, match="neshoduje s pinem"):
            read_reference_entries(FIXTURE, m)


class TestAdapter:
    def test_registered(self):
        assert "access_log" in DIFFREF_ADAPTERS
        adapter = DIFFREF_ADAPTERS["access_log"]
        assert adapter.parser_id == "access_log"

    def test_run_both_sides_access_log(self):
        stopa_entries, adapter = run_both_sides("access_log", FIXTURE)
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
        ref_entries = adapter.read_reference(FIXTURE, m)
        assert len(stopa_entries) == 8 and len(ref_entries) == 8

    def test_unknown_parser_error_lists_access_log(self):
        from stopa.diffref import resolve_adapter

        with pytest.raises(ValueError, match="access_log"):
            resolve_adapter("bogus")


class TestDetection:
    def test_name_based_match_routes_to_access_log(self):
        from stopa.pipeline.matching import _name_based_match
        from stopa.pipeline.registry import NAME_BASED_EXTRACTORS

        for name in ("access.log", "/var/log/apache2/access.log", "nginx_access_log.txt"):
            m = _name_based_match(name)
            assert m is not None and m == NAME_BASED_EXTRACTORS["access_log"]

    def test_name_based_match_not_hijacked(self):
        # běžné soubory zůstávají v původních detektorech (regrese §7);
        # souvislé "accesslog" bez oddělovače vyhrazeno Google WR pre-passu
        from stopa.pipeline.matching import _name_based_match
        from stopa.pipeline.registry import NAME_BASED_EXTRACTORS

        for name in ("app.log", "notes.txt", "AccessLogDevices-2025.json"):
            m = _name_based_match(name)
            assert m is None or m != NAME_BASED_EXTRACTORS["access_log"]
