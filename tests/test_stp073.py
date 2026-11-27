"""STP-073 — SQLite referenční dataset + vrstva ``stopa.diffref`` (pilot vlna 1, design §6.1/§7).

Pokrývá celý pilotní celek end-to-end:

* **Referenční dataset** ``tests/reference_datasets/sqlite/chrome_history/`` —
  deterministická Chrome/Edge History DB s SHA-256 pinem v manifestu (guard testy);
* **vrstva diffref** — adaptér se dvěma nezávislými cestami nad stejným souborem
  (STOPA extraktor vs. referenční čtení z manifestu), celočíselná konverze
  Chrome µs epoch, read-only přístup k důkazu;
* **CLI auto-režim** ``stopa differential sqlite --raw F --manifest M`` —
  režimová sémantika, hash-pin vstupu, exit kódy (§6).

Deterministicky offline; fixture se commítuje (negace ``*.db`` v .gitignore).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from stopa.cli.commands.differential import cmd_differential
from stopa.diffref import resolve_adapter, run_both_sides
from stopa.diffref.sqlite_ref import (
    CHROME_UNIX_OFFSET_S,
    chrome_micros_to_unix_s,
    load_manifest,
    read_reference_entries,
    run_stopa_sqlite,
)
from stopa.domain.differential import build_report, exit_code_for, normalize_dataset

DS = Path(__file__).parent / "reference_datasets" / "sqlite" / "chrome_history"
FIXTURE = DS / "chrome_history.db"
MANIFEST = DS / "manifest.json"
EXPECTED = DS / "expected_records.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jk_from_manifest(manifest: dict[str, object]) -> dict[str, tuple[str, ...]]:
    raw = manifest["join_keys"]
    assert isinstance(raw, dict)
    return {k: tuple(v) for k, v in raw.items()}  # type: ignore[union-attr]


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- fixture guard


class TestFixtureGuard:
    """Determinismus reference datasetu — pin hash + byte-stability rebuildu."""

    def test_fixture_sha256_pinned_to_manifest(self) -> None:
        assert _sha256(FIXTURE) == str(_manifest()["fixture_sha256"])

    def test_build_fixture_rebuilds_identical_bytes(self, tmp_path: Path) -> None:
        # Rebuild = byte-identická DB (SHA-pin v manifestu drží). Headerové pole
        # „SQLite Library Version Number“ normalizuje build_fixture.py na nulu →
        # stabilní i při rebuildu jinou verzí SQLite (CI má odlišné libsqlite3).
        out_db = tmp_path / "rebuilt.db"
        proc = subprocess.run(
            [sys.executable, str(DS / "build_fixture.py"), str(out_db)],
            capture_output=True, text=True, check=False, cwd=str(DS),
        )
        assert proc.returncode == 0, f"rebuild selhal: {proc.stderr[:300]}"
        assert _sha256(out_db) == _sha256(FIXTURE)


class TestManifestSchema:
    """Manifest = smlouva referenční cesty (dotazy, join keys, pin)."""

    def test_schema_fields_present(self) -> None:
        m = _manifest()
        assert m["version"] == 1
        assert m["parser_id"] == "sqlite"
        assert isinstance(m["schema_variant"], str) and m["schema_variant"]
        queries = m["queries"]
        assert isinstance(queries, list) and queries
        for q in queries:
            for key in ("type", "sql", "ts_column", "converter", "fields"):
                assert key in q, f"query chybí {key}"
            assert isinstance(q["fields"], dict) and q["fields"]
        jk = m["join_keys"]
        assert isinstance(jk, dict) and jk
        for fields in jk.values():
            assert isinstance(fields, list) and all(isinstance(f, str) for f in fields)

    def test_load_manifest_missing_file(self, tmp_path: Path) -> None:
        # OSError se balí do ValueError (smlouva load_manifest — souborová chyba je vstupní)
        with pytest.raises(ValueError, match="chybi.json"):
            load_manifest(tmp_path / "chybi.json")

    def test_load_manifest_bad_version(self, tmp_path: Path) -> None:
        bad = json.loads(MANIFEST.read_text(encoding="utf-8"))
        bad["version"] = 99
        p = tmp_path / "m.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="verze"):
            load_manifest(p)

    def test_load_manifest_join_keys_not_list(self, tmp_path: Path) -> None:
        bad = json.loads(MANIFEST.read_text(encoding="utf-8"))
        bad["join_keys"] = {"browser_history": "url"}
        p = tmp_path / "m.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="join_keys"):
            load_manifest(p)


# ---------------------------------------------------------------- konverze epoch


class TestChromeMicrosConverter:
    """Přesná celočíselná konverze Chrome µs → unix s (vlastní konstanta)."""

    def test_roundtrip_whole_seconds(self) -> None:
        for unix_s in (0, 1_700_000_000, 4_294_967_295):
            micros = (unix_s + CHROME_UNIX_OFFSET_S) * 1_000_000
            assert chrome_micros_to_unix_s(micros) == unix_s

    def test_subsecond_remainder_truncates(self) -> None:
        # Chrome µs granularity — zlomky sekundy se ořezávají (floor na µs hranici)
        base = 1_700_000_000 + CHROME_UNIX_OFFSET_S
        assert chrome_micros_to_unix_s(base * 1_000_000 + 999) == 1_700_000_000

    def test_not_filetime_ticks(self) -> None:
        # µs ne FILETIME 100ns ticks — špatné dělení by dalo faktor 10 (odchylka ~20859 dní)
        unix_s = 1_700_000_000
        micros = (unix_s + CHROME_UNIX_OFFSET_S) * 1_000_000
        assert chrome_micros_to_unix_s(micros) == unix_s
        wrong_filetime = micros // 10_000_000 - CHROME_UNIX_OFFSET_S
        assert chrome_micros_to_unix_s(micros) != wrong_filetime

    def test_type_errors(self) -> None:
        for bad in (1.5, "1700000000", True):
            with pytest.raises(TypeError, match="int"):
                chrome_micros_to_unix_s(bad)  # type: ignore[arg-type]

    def test_value_errors(self) -> None:
        for bad in (0, -5):
            with pytest.raises(ValueError, match="kladné"):
                chrome_micros_to_unix_s(bad)


# ---------------------------------------------------------------- vrstva diffref


class TestDiffrefLayer:
    """Adaptéry a dvě nezávislé cesty nad stejným souborem."""

    def test_registry_has_sqlite_adapter(self) -> None:
        adapter = resolve_adapter("sqlite")
        assert adapter.parser_id == "sqlite"
        assert callable(adapter.run_stopa) and callable(adapter.read_reference)

    def test_resolve_unknown_parser_raises(self) -> None:
        # pilot scope = sqlite + net_connections (STP-074); ostatní formáty = další vlny (§7)
        with pytest.raises(ValueError, match="evtx"):
            resolve_adapter("evtx")

    def test_reference_read_unknown_converter(self) -> None:
        # konvertéry validuje referenční čtení (v momentě použití z manifestu)
        bad = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for q in bad["queries"]:
            q["converter"] = "unix_ms"
        with pytest.raises(ValueError, match="konvertér"):
            read_reference_entries(FIXTURE, bad)

    def test_run_stopa_sqlite_browser_history_shape(self) -> None:
        entries = run_stopa_sqlite(FIXTURE)
        assert len(entries) == 5
        for e in entries:
            assert set(e.keys()) >= {"type", "ts", "fields"}
            assert e["type"] == "browser_history"
            # ts = timestamp datetimeu (float s µs přesností; §3 normalizace ořízne)
            assert isinstance(e["ts"], (int, float)) and not isinstance(e["ts"], bool)
            fields = e["fields"]
            assert isinstance(fields, dict)
            assert "url" in fields and "page_title" in fields

    def test_run_stopa_sqlite_search_terms_cleanly_zero(self) -> None:
        # prázdná search_terms → bonus GoogleBarArtifact se čistě vyhodnotí na nulu
        types = {e["type"] for e in run_stopa_sqlite(FIXTURE)}
        assert types == {"browser_history"}

    def test_reference_entries_match_expected_golden(self) -> None:
        m = load_manifest(MANIFEST)
        raw = read_reference_entries(FIXTURE, m)
        assert len(raw) == 5
        jk = _jk_from_manifest(json.loads(MANIFEST.read_text(encoding="utf-8")))
        normalized = normalize_dataset(raw, join_keys=jk)
        golden = json.loads(EXPECTED.read_text(encoding="utf-8"))
        assert [ (r.type, r.ts_epoch, r.fields) for r in normalized ] == [
            (g["type"], g["ts_epoch"], g["fields"]) for g in golden
        ]

    def test_reference_read_does_not_touch_evidence(self, tmp_path: Path) -> None:
        # read-only URI: byte obsah i absence -wal/-journal sidecarů zůstává nedotčeno
        copy = tmp_path / "evidence.db"
        shutil.copyfile(FIXTURE, copy)
        before = _sha256(copy)
        m = load_manifest(MANIFEST)
        assert len(read_reference_entries(copy, m)) == 5
        assert _sha256(copy) == before
        for suffix in ("-wal", "-journal", "-shm"):
            assert not copy.with_name(copy.name + suffix).exists(), f"sidecar {suffix} vznikl"


# ---------------------------------------------------------------- end-to-end


class TestEndToEndPipeline:
    """Dvě nezávislé cesty se na fixture shodují 100 % (design §2/§6)."""

    def test_full_pipeline_identical_100pct(self) -> None:
        m = load_manifest(MANIFEST)
        jk = _jk_from_manifest(json.loads(MANIFEST.read_text(encoding="utf-8")))
        stopa_entries, adapter = run_both_sides("sqlite", FIXTURE)
        ref_entries = adapter.read_reference(FIXTURE, m)

        report = build_report(
            parser="sqlite",
            stopa_records=normalize_dataset(stopa_entries, join_keys=jk),
            ref_records=normalize_dataset(ref_entries, join_keys=jk),
            join_keys=jk,
            input_sha256=_sha256(FIXTURE),
            reference_tool=str(m["reference_tool"]),
        )
        assert report.differences == ()
        assert exit_code_for(report.differences) == 0
        payload = json.loads(report.to_json())
        assert payload["identical_pct"] == 100.0
        assert payload["stopa_records"] == 5 and payload["ref_records"] == 5


# ---------------------------------------------------------------- CLI auto-režim


def _ns(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "parser": "sqlite",
        "input": None,
        "ref": None,
        "raw": str(FIXTURE),
        "manifest": str(MANIFEST),
        "tool": None,
        "join_key": [],
        "adjudications": None,
        "run_id": None,
        "format": "text",
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestCliAutoMode:
    """``stopa differential sqlite --raw F --manifest M`` (pilot §7)."""

    def test_auto_mode_text_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_differential(_ns())
        assert rc == 0
        out = capsys.readouterr().out
        assert "parser=sqlite" in out
        assert "identické: 100.0 %" in out
        assert "Rozdíly: žádné" in out

    def test_auto_mode_json_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_differential(_ns(format="json"))
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["parser"] == "sqlite"
        assert payload["identical_pct"] == 100.0
        assert payload["differences"] == []
        assert payload["stopa_records"] == 5 and payload["ref_records"] == 5
        # reference_tool bez --tool = identita z manifestu (design §10.2)
        assert str(payload["reference_tool"]).startswith("diffref-sqlite-stdlib/1.0")

    def test_raw_without_manifest_exit2(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_differential(_ns(manifest=None))
        assert rc == 2
        assert "--raw vyžaduje --manifest" in capsys.readouterr().err

    def test_manifest_without_raw_exit2(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_differential(_ns(raw=None))
        assert rc == 2
        assert "patří do režimu --raw" in capsys.readouterr().err

    def test_json_mode_still_requires_input_and_ref_exit2(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # regresní kontrakt vlny 28 — JSON režim bez --input/--ref
        rc = cmd_differential(_ns(raw=None, manifest=None))
        assert rc == 2
        assert "--input i --ref" in capsys.readouterr().err

    def test_hash_pin_mismatch_exit2(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        # poškozený/doplněný soubor = jiný hash → fail-fast proti tichému driftu důkazu
        broken = tmp_path / "broken.db"
        shutil.copyfile(FIXTURE, broken)
        with open(broken, "ab") as f:
            f.write(b"\x00\x00\x00\x00")  # SQLite toleruje trailing junk → dojde až k pinu
        rc = cmd_differential(_ns(raw=str(broken)))
        assert rc == 2
        err = capsys.readouterr().err
        assert "hash vstupu se neshoduje s pinem" in err

    def test_missing_raw_file_exit2(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_differential(_ns(raw=str(tmp_path / "nenalezen.db")))
        assert rc == 2
        assert "soubor nenalezen" in capsys.readouterr().err
