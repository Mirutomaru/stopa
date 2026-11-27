"""STP-074 — netstat/text reference dataset + aditivní stav (pilot vlna 1 část B, design §6/§7).

Pokrývá celý celek end-to-end:

* **Referenční dataset** ``tests/reference_datasets/netstat/`` — dvě textové
  fixtury (Windows ``netstat -ano``, Unix ``ss``) s SHA-256 pinem per fixture v
  manifestu (guard testy);
* **vrstva diffref, textová reference** — adaptér se dvěma nezávislými cestami
  nad stejným souborem (STOPA extraktor vs. ručně psané referenční čtení),
  sémantika pole ``local``/``remote``/``state``/``pid``, fail-fast pin;
* **CLI auto-režim** ``stopa differential net_connections --raw F --manifest M``;
* **aditivní stav** ``differentially_validated`` (§6 krok 8) — validovaný parser
  s pincovaným reference datasetem; kompatibilita reportu (klíč ``validated``
  počítá oba stavy, nový klíč je explicitní).

Deterministicky offline; fixtury se commítují.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from stopa.cli.commands.differential import cmd_differential
from stopa.diffref.text_ref import (
    load_text_manifest,
    read_reference_entries,
    run_stopa_netstat,
)
from stopa.domain.differential import build_report, exit_code_for, normalize_dataset
from stopa.domain.parser_status import (
    DIFFERENTIALLY_VALIDATED,
    UNVALIDATED,
    VALIDATED,
    build_parser_status,
    parser_status_report,
)
from stopa.domain.validation_registry import ParserValidation

DS = Path(__file__).parent / "reference_datasets" / "netstat"
MANIFEST = DS / "manifest.json"
FIXTURE_NAMES = ("netstat_ano.txt", "ss_an.txt")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _pin(name: str) -> str:
    for fx in _manifest()["fixtures"]:  # type: ignore[union-attr]
        if isinstance(fx, dict) and fx.get("file") == name:
            return str(fx["sha256"])
    raise AssertionError(f"fixture {name!r} není v manifestu")


def _join_spec() -> dict[str, tuple[str, ...]]:
    raw = _manifest()["join_keys"]
    assert isinstance(raw, dict)
    return {k: tuple(v) for k, v in raw.items()}  # type: ignore[union-attr]


# ---------------------------------------------------------------- fixture guard


class TestFixtureGuard:
    """Determinismus reference datasetu — pin per fixture + byte-stability rebuildu."""

    def test_fixtures_sha256_pinned_to_manifest(self) -> None:
        for name in FIXTURE_NAMES:
            assert _sha256(DS / name) == _pin(name), f"drift fixtury {name}"

    def test_build_fixture_rebuilds_identical_bytes(self, tmp_path: Path) -> None:
        # Rebuild do jiného adresáře = byte-identické fixtury + manifest (SHA-piny drží).
        proc = subprocess.run(
            [sys.executable, str(DS / "build_fixture.py"), str(tmp_path)],
            capture_output=True, text=True, check=False, cwd=str(DS),
        )
        assert proc.returncode == 0, f"rebuild selhal: {proc.stderr[:300]}"
        for name in FIXTURE_NAMES:
            assert _sha256(tmp_path / name) == _pin(name), f"drift rebuildu {name}"
        # manifest je deterministická funkce fixtur (piny + konstantní meta)
        rebuilt = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        original = _manifest()
        assert rebuilt["fixtures"] == original["fixtures"]


# ---------------------------------------------------------------- manifest smlouva


class TestTextManifestSchema:
    """Manifest textového datasetu = smlouva referenční cesty."""

    def test_schema_fields_present(self) -> None:
        m = _manifest()
        assert m["version"] == 1
        assert m["parser_id"] == "net_connections"
        assert isinstance(m["reference_tool"], str) and m["reference_tool"]
        jk = m["join_keys"]
        assert isinstance(jk, dict) and jk
        for fields in jk.values():
            assert isinstance(fields, list) and all(isinstance(f, str) for f in fields)
        fixtures = m["fixtures"]
        assert isinstance(fixtures, list) and len(fixtures) == 2
        declared = {fx["file"] for fx in fixtures}  # type: ignore[index]
        assert declared == set(FIXTURE_NAMES)

    def test_load_manifest_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="chybi.json"):
            load_text_manifest(tmp_path / "chybi.json")

    def test_load_manifest_bad_version(self, tmp_path: Path) -> None:
        bad = _manifest()
        bad["version"] = 99
        p = tmp_path / "m.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="verze"):
            load_text_manifest(p)

    def test_load_manifest_unknown_variant(self, tmp_path: Path) -> None:
        bad = _manifest()
        for fx in bad["fixtures"]:  # type: ignore[union-attr]
            if isinstance(fx, dict):
                fx["variant"] = "syslog"
        p = tmp_path / "m.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="neznámá reference varianta"):
            load_text_manifest(p)

    def test_load_manifest_bad_sha_length(self, tmp_path: Path) -> None:
        bad = _manifest()
        for fx in bad["fixtures"]:  # type: ignore[union-attr]
            if isinstance(fx, dict):
                fx["sha256"] = "abc"
        p = tmp_path / "m.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="sha256"):
            load_text_manifest(p)


# ---------------------------------------------------------------- referenční čtecí


class TestTextRefParsers:
    """Nezávislé textové parseři — sémantika pole (smlouva manifestu)."""

    @staticmethod
    def _probe(tmp_path: Path, name: str, variant: str, text: str) -> list[dict]:
        p = tmp_path / name
        p.write_text(text, encoding="utf-8")
        m = {
            "version": 1,
            "parser_id": "net_connections",
            "reference_tool": "probe",
            "join_keys": {"network_connection": ["proto", "local", "remote"]},
            "fixtures": [
                {"file": name, "sha256": _sha256(p), "variant": variant}
            ],
        }
        manifest_path = tmp_path / "m.json"
        manifest_path.write_text(json.dumps(m), encoding="utf-8")
        return read_reference_entries(p, load_text_manifest(manifest_path))

    def test_windows_netstat_lines(self, tmp_path: Path) -> None:
        text = (
            "Active Connections\n\n\n"
            "  Proto  Local Address          Foreign Address        State           PID\n"
            "  TCP    0.0.0.0:135            0.0.0.0:*              LISTENING       792\n"
            "  UDP    0.0.0.0:68             0.0.0.0:*                               4\n"
        )
        entries = self._probe(tmp_path, "w.txt", "windows_netstat_ano", text)
        assert len(entries) == 2
        tcp, udp = entries
        # UDP bez stavu → explicitní None (chybějící ≠ prázdný, §3.3)
        assert tcp["fields"] == {
            "proto": "TCP", "local": "0.0.0.0:135", "remote": "0.0.0.0",
            "state": "LISTENING", "pid": 792,
        }
        assert udp["fields"]["state"] is None and udp["fields"]["pid"] == 4
        # port '*' bez adresy → jen adresa; ts vždy None (snapshot)
        for e in entries:
            assert e["ts"] is None and e["type"] == "network_connection"

    def test_windows_netstat_ipv6_and_wildcard(self, tmp_path: Path) -> None:
        text = (
            "  Proto  Local Address          Foreign Address        State           PID\n"
            "  TCP    [::]:3389              [::]:*                     LISTENING       512\n"
        )
        entries = self._probe(tmp_path, "w6.txt", "windows_netstat_ano", text)
        assert len(entries) == 1
        # IPv6 drží hranaté závorky; remote [::]:* → jen adresa
        assert entries[0]["fields"]["local"] == "[::]:3389"
        assert entries[0]["fields"]["remote"] == "[::]"

    def test_unix_ss_lines(self, tmp_path: Path) -> None:
        text = (
            "Netid State   Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
            'tcp   LISTEN  0      4096   *:22             *:*                     users:(("sshd",pid=2001,fd=3))\n'
            "udp   UNCONN  0      0      0.0.0.0:68       0.0.0.0:*\n"
        )
        entries = self._probe(tmp_path, "s.txt", "unix_ss", text)
        assert len(entries) == 2
        tcp, udp = entries
        # wildcard local *:22; remote *:* → "*"; PID ze sloupce Process
        assert tcp["fields"] == {
            "proto": "TCP", "local": "*:22", "remote": "*",
            "state": "LISTEN", "pid": 2001,
        }
        # bez sloupce Process → explicitní None
        assert udp["fields"]["pid"] is None and udp["fields"]["state"] == "UNCONN"

    def test_fixture_not_declared_in_manifest(self, tmp_path: Path) -> None:
        p = tmp_path / "inaj.txt"
        p.write_text("TCP 1.2.3.4:5 6.7.8.9:10 LISTENING 1\n", encoding="utf-8")
        m = load_text_manifest(MANIFEST)
        with pytest.raises(ValueError, match="deklarovaná"):
            read_reference_entries(p, m)

    def test_hash_pin_mismatch_fail_fast(self, tmp_path: Path) -> None:
        # poškozený/doplněný soubor = jiný hash → fail-fast proti tichému driftu důkazu
        broken = tmp_path / "ss_an.txt"
        shutil.copyfile(DS / "ss_an.txt", broken)
        with open(broken, "ab") as f:
            f.write(b"\n")
        m = load_text_manifest(MANIFEST)
        with pytest.raises(ValueError, match="hash fixtury se neshoduje s pinem"):
            read_reference_entries(broken, m)


# ---------------------------------------------------------------- end-to-end


class TestEndToEndPipeline:
    """Dvě nezávislé cesty se na obou fixturách shodují 100 % (design §2/§6)."""

    @pytest.mark.parametrize("name", FIXTURE_NAMES)
    def test_full_pipeline_identical_100pct(self, name: str) -> None:
        fixture = DS / name
        m = load_text_manifest(MANIFEST)
        jk = _join_spec()
        stopa_entries = run_stopa_netstat(fixture)
        ref_entries = read_reference_entries(fixture, m)

        # entry-level identity obou cest (pre-normalizace)
        assert stopa_entries == ref_entries

        report = build_report(
            parser="net_connections",
            stopa_records=normalize_dataset(stopa_entries, join_keys=jk),
            ref_records=normalize_dataset(ref_entries, join_keys=jk),
            join_keys=jk,
            input_sha256=_sha256(fixture),
            reference_tool=str(m["reference_tool"]),
        )
        assert report.differences == ()
        assert exit_code_for(report.differences) == 0
        payload = json.loads(report.to_json())
        assert payload["identical_pct"] == 100.0

    @pytest.mark.parametrize("name", FIXTURE_NAMES)
    def test_reference_matches_expected_golden(self, name: str) -> None:
        # golden = normalizované záznamy referenční cesty (build_fixture.py)
        m = load_text_manifest(MANIFEST)
        jk = _join_spec()
        normalized = normalize_dataset(
            read_reference_entries(DS / name, m), join_keys=jk
        )
        golden_path = DS / f"expected_{name.removesuffix('.txt')}.json"
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
        assert [(r.type, r.ts_epoch, dict(r.fields)) for r in normalized] == [
            (g["type"], g["ts_epoch"], g["fields"]) for g in golden
        ]


# ---------------------------------------------------------------- CLI auto-režim


def _ns(name: str = "netstat_ano.txt", **overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "parser": "net_connections",
        "input": None,
        "ref": None,
        "raw": str(DS / name),
        "manifest": str(MANIFEST),
        "tool": None,
        "join_key": [],
        "adjudications": None,
        "run_id": None,
        "format": "text",
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestCliAutoModeNetstat:
    """``stopa differential net_connections --raw F --manifest M`` (§7)."""

    @pytest.mark.parametrize("name", FIXTURE_NAMES)
    def test_auto_mode_text_success(self, name: str, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_differential(_ns(name=name))
        assert rc == 0
        out = capsys.readouterr().out
        assert "parser=net_connections" in out
        assert "identické: 100.0 %" in out
        assert "Rozdíly: žádné" in out

    def test_auto_mode_json_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_differential(_ns(format="json"))
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["parser"] == "net_connections"
        assert payload["identical_pct"] == 100.0
        assert payload["differences"] == []
        # reference_tool bez --tool = identita z manifestu (design §10.2)
        assert str(payload["reference_tool"]).startswith("diffref-text-stdlib/1.0")

    def test_hash_pin_mismatch_exit2(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        # textový pin = per fixture ve read_reference (manifest bez top-level pinu)
        broken = tmp_path / "ss_an.txt"
        shutil.copyfile(DS / "ss_an.txt", broken)
        with open(broken, "ab") as f:
            f.write(b"\n")
        rc = cmd_differential(_ns(name="ss_an.txt", raw=str(broken)))
        assert rc == 2
        assert "hash fixtury se neshoduje s pinem" in capsys.readouterr().err

    def test_missing_raw_file_exit2(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_differential(_ns(raw=str(tmp_path / "nenalezen.txt")))
        assert rc == 2
        assert "soubor nenalezen" in capsys.readouterr().err


# ---------------------------------------------------------------- aditivní stav (§6 krok 8)


def _pv(pid: str, files: tuple[str, ...] = ("tests/t_x.py",), dataset: str | None = None):
    return ParserValidation(
        parser_id=pid,
        version="",
        reference_dataset=dataset,
        formats=("f1",),
        limitations=("l1",),
        test_files=files,
    )


def _loader(files: dict[str, str]) -> Callable[[str], str | None]:
    def load(rel: str) -> str | None:
        return files.get(rel)

    return load


class TestDifferentiallyValidatedState:
    """Aditivní stav — validated + pincovaný reference dataset (design §6 krok 8)."""

    def test_promotion_requires_validated_and_dataset(self) -> None:
        registry = {
            "with_ds": _pv("with_ds", dataset="netstat/"),          # promoted
            "plain": _pv("plain"),                                  # validated
            "unvalidated_with_ds": _pv(  # soubor chybí → unvalidated, bez promotionu
                "unvalidated_with_ds", files=("tests/chybi.py",), dataset="x/"
            ),
        }
        records = build_parser_status(registry, _loader({"tests/t_x.py": "def test_a():\n    pass\n"}))
        by_id = {r.parser_id: r for r in records}
        assert by_id["with_ds"].validation_status == DIFFERENTIALLY_VALIDATED
        assert by_id["plain"].validation_status == VALIDATED
        assert by_id["unvalidated_with_ds"].validation_status == UNVALIDATED

    def test_report_compatibility_and_new_key(self) -> None:
        registry = {
            "b_ds": _pv("b_ds", dataset="netstat/"),
            "a_plain": _pv("a_plain"),
            "c_unvalidated": _pv("c_unvalidated", files=("tests/chybi.py",)),
        }
        report = parser_status_report(
            build_parser_status(registry, _loader({"tests/t_x.py": "def test_a():\n    pass\n"}))
        )
        # kompatibilita: validated počítá i differentially_validated (aditivita)
        assert report["validated"] == 2
        assert report["unvalidated_count"] == 1
        assert report["count"] == report["validated"] + report["unvalidated_count"]
        # nový explicitní klíč, seřazené ID
        assert report["differentially_validated"] == ["b_ds"]
        assert report["unvalidated"] == ["c_unvalidated"]

    def test_empty_report_has_new_key(self) -> None:
        report = parser_status_report([])
        assert report["differentially_validated"] == []

    def test_real_registry_netstat_and_sqlite_promoted(self) -> None:
        # reálný C3 registry + reálné test soubory (data vrstva = I/O)
        from stopa.data.parser_status_service import load_parser_status

        report = load_parser_status()
        by_id = {p["parser_id"]: p for p in report["parsers"]}
        assert by_id["net_connections"]["validation_status"] == DIFFERENTIALLY_VALIDATED
        assert by_id["sqlite"]["validation_status"] == DIFFERENTIALLY_VALIDATED
        # aditivita: nový klíč přesně odpovídá stavům v záznamech
        assert set(report["differentially_validated"]) == {
            p["parser_id"] for p in report["parsers"]
            if p["validation_status"] == DIFFERENTIALLY_VALIDATED
        }
