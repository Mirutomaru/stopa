"""STP-077 — Android mmssms.db referenční varianta SQLite rodiny (vlna 4, design §7).

Pokrývá celek end-to-end:

* **Referenční dataset** ``tests/reference_datasets/sqlite/android_sms/`` —
  deterministická Android SMS DB (tabulka ``sms``, unix ms) s SHA-256 pinem v
  manifestu (guard testy; byte-stabilita napříč verzemi SQLite přes header
  normalizaci writer version, stejný guard jako STP-073/STP-076);
* **konvertér epoch** ``unix_ms_to_unix_s`` — celočíselná reference vs. STOPA
  float cesta ``ms / 1000.0`` + floor normalizace (shoda i s podsekundovou
  frakcí .500 s);
* **vrstva diffref** — adaptér se dvěma nezávislými cestami nad stejným souborem,
  read-only přístup k důkazu; STOPA strana rozšířena o kanonický typ
  ``sms_message`` (body z titleu, address z details);
* **NFKC ekvivalence obou cest** (§3.3) — řádek s ligaturou ﬁ (U+FB01): surové
  tělo se liší od normalizovaného tvaru, kanonické záznamy jsou shodné;
* **CLI auto-režim** ``stopa differential sqlite --raw F --manifest M`` na
  android_sms manifestu (režimová sémantika, hash-pin vstupu, exit kódy §6).

Deterministicky offline; fixture se commítuje (negace ``*.db``/.sqlite v .gitignore).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from stopa.cli.commands.differential import cmd_differential
from stopa.diffref import resolve_adapter, run_both_sides
from stopa.diffref.sqlite_ref import (
    CONVERTERS,
    load_manifest,
    read_reference_entries,
    run_stopa_sqlite,
    unix_ms_to_unix_s,
)
from stopa.domain.differential import build_report, exit_code_for, normalize_dataset

DS = Path(__file__).parent / "reference_datasets" / "sqlite" / "android_sms"
FIXTURE = DS / "mmssms.db"
MANIFEST = DS / "manifest.json"
EXPECTED = DS / "expected_records.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jk_from_manifest(manifest: dict[str, object]) -> dict[str, tuple[str, ...]]:
    raw = manifest["join_keys"]
    assert isinstance(raw, dict)
    return {k: tuple(v) for k, v in raw.items()}  # type: ignore[union-attr]


# ---------------------------------------------------------------- fixture guard


class TestFixtureGuard:
    """SHA pin + byte-determinismus buildu (guard proti driftu důkazu)."""

    def test_fixture_sha256_pinned_to_manifest(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        assert _sha256(FIXTURE) == manifest["fixture_sha256"]

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


# ---------------------------------------------------------------- manifest


class TestManifestSchema:
    """Smlouva android_sms manifestu (stejný tvar jako STP-073/STP-076)."""

    def test_schema_fields_present(self) -> None:
        m = load_manifest(MANIFEST)
        assert m["version"] == 1
        assert m["parser_id"] == "sqlite"
        assert m["schema_variant"] == "android_mmssms"
        query = m["queries"][0]
        assert query["type"] == "sms_message"
        assert query["converter"] in CONVERTERS
        assert _jk_from_manifest(m) == {"sms_message": ("address", "ts")}

    def test_load_manifest_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="No such file|nenalezen|neexistuje"):
            load_manifest(tmp_path / "absentni.json")

    def test_load_manifest_bad_version(self, tmp_path: Path) -> None:
        bad = json.loads(MANIFEST.read_text(encoding="utf-8"))
        bad["version"] = 2
        p = tmp_path / "manifest_v2.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="verze manifestu"):
            load_manifest(p)


# ---------------------------------------------------------------- konvertér epoch


class TestUnixMsConverter:
    """``unix_ms_to_unix_s`` — celočíselná reference (nezávislá na stopa.domain.times)."""

    def test_whole_seconds_exact(self) -> None:
        assert unix_ms_to_unix_s(1_735_689_600 * 1_000) == 1_735_689_600

    def test_subsecond_remainder_truncates(self) -> None:
        # .500 s frakce se zaokrouhlí dolů — stejně jako floor v normalizaci STOPA cesty
        assert unix_ms_to_unix_s(1_735_690_200 * 1_000 + 500) == 1_735_690_200

    def test_scale_is_milliseconds(self) -> None:
        # faktorová past: // 1_000_000 (µs chyba) dalo by 1_735; * 1_000 (s→ms) 1.7e9
        assert unix_ms_to_unix_s(1_735_689 * 1_000 + 500) == 1_735_689

    def test_zero_is_epoch(self) -> None:
        # 0 = platná epocha 1970-01-01 (konzistentní s from_unix; STOPA filtruje > 0 v SQL)
        assert unix_ms_to_unix_s(0) == 0

    def test_type_errors(self) -> None:
        for bad in (True, False, "1735", 1.5, None):
            with pytest.raises(TypeError):
                unix_ms_to_unix_s(bad)  # type: ignore[arg-type]

    def test_negative_value_error(self) -> None:
        with pytest.raises(ValueError, match="≥ 0"):
            unix_ms_to_unix_s(-1)


# ---------------------------------------------------------------- vrstva diffref


class TestDiffrefLayer:
    """Obě cesty nad stejným souborem + read-only důkaz (design §2/§6)."""

    def test_adapter_resolve_sqlite_still_works(self) -> None:
        # regresní: rozšíření STOPA strany nesmí porušit registr adaptérů
        adapter = resolve_adapter("sqlite")
        assert adapter.parser_id == "sqlite"

    def test_reference_entries_match_expected_golden(self) -> None:
        m = load_manifest(MANIFEST)
        entries = read_reference_entries(FIXTURE, m)
        jk = _jk_from_manifest(json.loads(MANIFEST.read_text(encoding="utf-8")))
        records = normalize_dataset(entries, join_keys=jk)
        actual = [
            {"type": r.type, "ts_epoch": r.ts_epoch, "fields": dict(r.fields)} for r in records
        ]
        expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
        assert actual == expected

    def test_reference_read_does_not_touch_evidence(self, tmp_path: Path) -> None:
        # read-only file::…?mode=ro → žádné -wal/-journal sidecar soubory
        copied = tmp_path / "mmssms.db"
        shutil.copyfile(FIXTURE, copied)
        m = load_manifest(MANIFEST)
        entries = read_reference_entries(copied, m)
        assert len(entries) == 7
        sidecars = [p for p in tmp_path.iterdir() if p.name != "mmssms.db"]
        assert sidecars == []

    def test_stopa_side_shape_sms(self) -> None:
        entries = run_stopa_sqlite(FIXTURE)
        assert len(entries) == 7  # 9 řádků sms − date=0 − NULL body
        for entry in entries:
            assert entry["type"] == "sms_message"
            assert set(entry["fields"]) == {"body", "address"}
            assert "ts" in entry

    def test_stopa_side_excludes_filtered_rows(self) -> None:
        # WHERE parity obou stran: date > 0 i body IS NOT NULL (contract_note manifestu)
        entries = run_stopa_sqlite(FIXTURE)
        addresses = {e["fields"]["address"] for e in entries}
        assert "+491512345678" not in addresses  # date = 0
        assert "+8135123456" not in addresses    # NULL body

    def test_long_body_299_chars_not_truncated(self) -> None:
        # hranice pod STOPA limitem title[:300] — reference i STOPA drží celé tělo
        entries = run_stopa_sqlite(FIXTURE)
        long_bodies = [e["fields"]["body"] for e in entries if len(e["fields"]["body"]) > 200]
        assert len(long_bodies) == 1
        assert len(long_bodies[0]) == 299

    def test_nfkc_ligature_equivalence(self) -> None:
        # ﬁ (U+FB01) v surovém těle — NFKC na obou cestách (§3.3): raw se liší od
        # normalizovaného tvaru, kanonické záznamy jsou shodné
        m = load_manifest(MANIFEST)
        stopa_entries = run_stopa_sqlite(FIXTURE)
        ref_entries = read_reference_entries(FIXTURE, m)
        raw_stopa = [e for e in stopa_entries if "\ufb01" in str(e["fields"].get("body", ""))]
        raw_ref = [e for e in ref_entries if "\ufb01" in str(e["fields"].get("body", ""))]
        assert len(raw_stopa) == 1 and len(raw_ref) == 1
        jk = _jk_from_manifest(json.loads(MANIFEST.read_text(encoding="utf-8")))
        stopa_records = normalize_dataset(stopa_entries, join_keys=jk)
        ref_records = normalize_dataset(ref_entries, join_keys=jk)
        norm_stopa = [r for r in stopa_records if "finance" in str(r.fields.get("body", ""))]
        norm_ref = [r for r in ref_records if "finance" in str(r.fields.get("body", ""))]
        assert len(norm_stopa) == 1 and len(norm_ref) == 1
        expected_body = "Meeting re: Q3 finance report"
        assert norm_stopa[0].fields["body"] == expected_body
        assert norm_ref[0].fields["body"] == expected_body


# ---------------------------------------------------------------- E2E pipeline


class TestEndToEndPipeline:
    """Dvě nezávislé cesty se na android_sms fixture shodují 100 % (design §2/§6)."""

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
        assert payload["stopa_records"] == 7 and payload["ref_records"] == 7

    def test_subsecond_row_ts_agrees_both_sides(self) -> None:
        # frakce .500 s: STOPA float ms/1000.0 drží podsekundovou frakci v surovém
        # ts; reference je celočíselná //1_000 — normalizace (floor) obě cesty
        # sjednotí na stejnou celou sekundu (E2E test hlídá 100 % shodu po ní).
        m = load_manifest(MANIFEST)
        stopa_entries, adapter = run_both_sides("sqlite", FIXTURE)
        ref_entries = adapter.read_reference(FIXTURE, m)

        def ts_of(entries: list[dict[str, object]]) -> int | float | None:
            for e in entries:
                fields = e.get("fields")
                if isinstance(fields, dict) and fields.get("address") == "12345":
                    return e.get("ts")  # type: ignore[return-value]
            return None

        stopa_ts = ts_of(stopa_entries)
        ref_ts = ts_of(ref_entries)
        assert ref_ts == 1_735_690_200
        assert stopa_ts is not None
        assert math.floor(float(stopa_ts)) == ref_ts

    def test_join_key_address_plus_ts_no_collision(self) -> None:
        # tři zprávy se stejnou address v odlišných sekundách — join key musí být
        # [address, ts] (jen ts by kolizovalo; jen address by taky)
        m = load_manifest(MANIFEST)
        stopa_entries, adapter = run_both_sides("sqlite", FIXTURE)
        ref_entries = adapter.read_reference(FIXTURE, m)
        for entries in (stopa_entries, ref_entries):
            same_address = [e for e in entries if e["fields"].get("address") == "+420777123456"]
            assert len(same_address) == 3


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
    """``stopa differential sqlite --raw F --manifest M`` na android_sms manifestu."""

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
        assert payload["stopa_records"] == 7 and payload["ref_records"] == 7
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
