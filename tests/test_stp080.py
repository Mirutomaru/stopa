"""STP-080 / vlna 36 — E2E diferenciální validace Unix BSD syslog parseru (§7).

STOPA cesta (``extract_syslog_artifacts``) vs. nezávislá referenční cesta
(``text_ref._ref_unix_syslog``, stdlib only) nad stejnou fixturou
``tests/reference_datasets/syslog/syslog_sample.log`` (SHA-256 pin v manifestu).

Kontrakt normalizace (smlouva manifestu, obě cesty stejný tvar): den nulově
doplněn, ``pid`` int nebo explicitní None, zpráva verbatim za prvním ``": "``,
``ts=None`` (syslog timestamp nemá rok/TZ — limitace parseru).

Duplicitní join klíč host+process+date+time se páruje po sobě deterministicky
(§3.2) — fixture obsahuje jeden takový pár (nginx 09:20:00).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stopa.artifacts.syslog_extract import extract_syslog_artifacts
from stopa.diffref import DIFFREF_ADAPTERS, run_both_sides
from stopa.diffref.text_ref import (
    SYSLOG_FIELD_KEYS,
    _ref_unix_syslog,
    load_text_manifest,
    read_reference_entries,
    run_stopa_syslog,
)
from stopa.domain.differential import build_report, normalize_dataset

DS = Path(__file__).parent / "reference_datasets" / "syslog"
FIXTURE = DS / "syslog_sample.log"
MANIFEST = DS / "manifest.json"
GOLDEN = DS / "expected_syslog_sample.json"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def join_keys(manifest: dict) -> dict[str, tuple[str, ...]]:
    return {k: tuple(v) for k, v in manifest["join_keys"].items()}  # type: ignore[union-attr]


@pytest.fixture(scope="module")
def both_sides(join_keys):
    stopa_entries, adapter = run_both_sides("syslog", FIXTURE)
    ref_entries = adapter.read_reference(FIXTURE, json.loads(MANIFEST.read_text(encoding="utf-8")))
    return (
        normalize_dataset(stopa_entries, join_keys=join_keys),
        normalize_dataset(ref_entries, join_keys=join_keys),
    )


class TestManifest:
    def test_valid(self, manifest):
        assert manifest["version"] == 1
        assert manifest["parser_id"] == "syslog"
        assert set(manifest["fixtures"][0]) == {"file", "sha256", "variant"}
        assert manifest["join_keys"]["syslog_event"] == ["host", "process", "date", "time"]

    def test_load_text_manifest_ok(self):
        m = load_text_manifest(MANIFEST)
        assert m["parser_id"] == "syslog"  # type: ignore[index]

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
        base["fixtures"][0]["variant"] = "windows_syslog"  # neexistující varianta
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps(base), encoding="utf-8")
        with pytest.raises(ValueError, match="varianta"):
            load_text_manifest(p)


class TestReferenceSide:
    def test_count_11_events(self):
        text = FIXTURE.read_text(encoding="utf-8")
        assert len(_ref_unix_syslog(text)) == 11

    def test_raw_lines_vs_events(self):
        # 13 raw řádků, z toho 2 se přeskočí (pokračování + prázdný) → 11 událostí
        lines = FIXTURE.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 13
        assert sum(1 for l in lines if not l.strip()) == 1

    def test_day_normalization_zero_pad(self):
        text = FIXTURE.read_text(encoding="utf-8")
        records = _ref_unix_syslog(text)
        dates = {r["fields"]["date"] for r in records}
        # "Nov  7" (mezera) i "Nov 07" (nula) → jediný tvar "Nov 07"
        assert "Nov 07" in dates and "Nov  7" not in dates

    def test_pid_none_vs_int(self):
        text = FIXTURE.read_text(encoding="utf-8")
        records = _ref_unix_syslog(text)
        by_process = {r["fields"]["process"]: r for r in records}
        assert by_process["kernel"]["fields"]["pid"] is None
        assert by_process["systemd-logind"]["fields"]["pid"] is None
        assert by_process["app-server"]["fields"]["pid"] is None
        assert by_process["sshd"]["fields"]["pid"] == 2481
        assert by_process["systemd"]["fields"]["pid"] == 1

    def test_message_verbatim_with_colons(self):
        text = FIXTURE.read_text(encoding="utf-8")
        records = _ref_unix_syslog(text)
        sudo = next(r for r in records if r["fields"]["process"] == "sudo")
        assert (
            sudo["fields"]["message"]
            == "deploy : TTY=pts/0 ; PWD=/home/deploy ; USER=root ; COMMAND=/usr/bin/systemctl restart nginx"
        )

    def test_utf8_message_verbatim(self):
        text = FIXTURE.read_text(encoding="utf-8")
        records = _ref_unix_syslog(text)
        app = next(r for r in records if r["fields"]["process"] == "app-server")
        assert app["fields"]["message"] == "připojení k databázi navázáno (latence 42 ms)"

    def test_ts_none_everywhere(self):
        text = FIXTURE.read_text(encoding="utf-8")
        assert all(r["ts"] is None for r in _ref_unix_syslog(text))


class TestStopaSide:
    def test_count_11_artifacts(self):
        arts = extract_syslog_artifacts(FIXTURE)
        assert len(arts) == 11

    def test_artifact_contract(self):
        arts = {a.details["process"]: a for a in extract_syslog_artifacts(FIXTURE)}
        sshd = arts["sshd"]
        assert sshd.artifact_type == "syslog_event"
        # syslog timestamp nemá rok/TZ → None (limitace parseru, registry §C3)
        assert sshd.timestamp is None
        assert sshd.title == "Syslog — sshd"
        assert sshd.confidence == 0.8
        assert sshd.details["date"] == "Nov 17"
        assert sshd.details["time"] == "09:15:32"
        assert sshd.details["host"] == "web-01"
        assert sshd.details["pid"] == 2481

    def test_pid_absent_from_details_when_missing(self):
        arts = {a.details["process"]: a for a in extract_syslog_artifacts(FIXTURE)}
        for proc in ("kernel", "systemd-logind", "app-server"):
            assert "pid" not in arts[proc].details

    def test_run_stopa_syslog_shape(self):
        entries = run_stopa_syslog(FIXTURE)
        assert len(entries) == 11
        assert all(e["type"] == "syslog_event" and e["ts"] is None for e in entries)
        # pevná množina klíčů — smlouva manifestu (chybějící pole = explicitní None)
        assert all(tuple(sorted(e["fields"])) == tuple(sorted(SYSLOG_FIELD_KEYS)) for e in entries)


class TestE2EParity:
    def test_no_diffs(self, both_sides):
        stopa_norm, ref_norm = both_sides
        report = build_report(
            parser="syslog",
            stopa_records=stopa_norm,
            ref_records=ref_norm,
            join_keys={"syslog_event": ("host", "process", "date", "time")},
        )
        assert report.differences == ()

    def test_identical_pct_100(self, both_sides):
        stopa_norm, ref_norm = both_sides
        payload = json.loads(
            build_report(
                parser="syslog",
                stopa_records=stopa_norm,
                ref_records=ref_norm,
                join_keys={"syslog_event": ("host", "process", "date", "time")},
            ).to_json()
        )
        assert payload["identical_pct"] == 100.0
        assert payload["stopa_records"] == 11
        assert payload["ref_records"] == 11

    def test_duplicate_join_key_pairing_sequential(self, both_sides):
        # §3.2: dva záznamy se stejným join klíčem (nginx 09:20:00) se párují po sobě
        stopa_norm, ref_norm = both_sides
        nginx_stopa = [r for r in stopa_norm if r.fields.get("process") == "nginx"]
        nginx_ref = [r for r in ref_norm if r.fields.get("process") == "nginx"]
        assert len(nginx_stopa) == 2 and len(nginx_ref) == 2
        # pořadí záznamů v fixtuře (error → upstream) drží na obou cestách
        assert nginx_stopa[0].fields["message"].startswith("2026/11/17")
        assert nginx_stopa[1].fields["message"] == "upstream server temporarily disabled"


class TestGolden:
    def test_golden_count(self):
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        assert len(golden) == 11

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
        assert "syslog" in DIFFREF_ADAPTERS
        adapter = DIFFREF_ADAPTERS["syslog"]
        assert adapter.parser_id == "syslog"

    def test_run_both_sides_syslog(self):
        stopa_entries, adapter = run_both_sides("syslog", FIXTURE)
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
        ref_entries = adapter.read_reference(FIXTURE, m)
        assert len(stopa_entries) == 11 and len(ref_entries) == 11

    def test_unknown_parser_error_lists_syslog(self):
        from stopa.diffref import resolve_adapter

        with pytest.raises(ValueError, match="syslog"):
            resolve_adapter("bogus")


class TestDetection:
    def test_name_based_match_routes_to_syslog(self):
        from stopa.pipeline.matching import _name_based_match
        from stopa.pipeline.registry import NAME_BASED_EXTRACTORS

        for name in ("syslog", "/var/log/syslog", "messages", "system.log"):
            m = _name_based_match(name)
            assert m is not None and m == NAME_BASED_EXTRACTORS["syslog"]

    def test_name_based_match_not_hijacked(self):
        # běžné soubory zůstávají v původních detektorech (regrese §7)
        from stopa.pipeline.matching import _name_based_match
        from stopa.pipeline.registry import NAME_BASED_EXTRACTORS

        for name in ("app.log", "notes.txt"):
            m = _name_based_match(name)
            assert m is None or m != NAME_BASED_EXTRACTORS["syslog"]
