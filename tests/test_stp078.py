"""STP-078 — Apple iMessage chat.db reference varianta (§7, vlna 5).

Čtvrtá schémová varianta SQLite rodiny nad existujícím generic adaptérem:
nová epocha **CFAbsoluteTime** (REAL s od roku 2001) + duplicitní join key
[handle, ts] po floor normalizaci. Deterministická offline fixtura je
commitnuta v ``reference_datasets/sqlite/imessage_chat/`` (SHA pin +
writer-version byte-stabilita).

Pokrytí:

* SHA-pin fixtury + byte-determinismus rebuildu (guard proti driftu důkazu)
* manifestová smlouva (stejný tvar jako STP-073/076/077)
* konvertér ``cfabsolute_to_unix_s`` — přesná aritmetika, int i float vstup,
  TypeError/ValueError hranice, nezávislost na stopa.domain.times (§2)
* diffref vrstva: reference vs. STOPA strana nad stejným souborem (read-only),
  WHERE parita obou stran, truncace [:300], NFKC ligatura ﬁ→fi, fallback
  "(prázdná zpráva)" pro whitespace-only text
* E2E pipeline: dvě nezávislé cesty se shodují 100 % (DIFFS=0), duplicitní
  join key [handle, ts] (řádky m1+m3, frakce .5 s) párován deterministicky
* CLI auto-režim ``stopa differential sqlite --raw F --manifest M`` + exit kódy §6
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.cli.commands.differential import cmd_differential
from stopa.diffref import resolve_adapter, run_both_sides
from stopa.diffref.sqlite_ref import (
    CFABSOLUTE_UNIX_OFFSET_S,
    CONVERTERS,
    cfabsolute_to_unix_s,
    load_manifest,
    read_reference_entries,
    run_stopa_sqlite,
)
from stopa.domain.differential import build_report, exit_code_for, normalize_dataset

DS = Path(__file__).parent / "reference_datasets" / "sqlite" / "imessage_chat"
FIXTURE = DS / "chat.db"
MANIFEST = DS / "manifest.json"
EXPECTED = DS / "expected_records.json"

# CFAbsoluteTime základ fixtury — unix 1_750_000_000 (2025-06-15T15:06:40Z)
BASE_CF = 771_692_800.0
PHONE_HANDLE = "+420777123456"
EMAIL_HANDLE = "jano.novak@example.cz"


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
    """Smlouva apple_imessage_chatdb manifestu (stejný tvar jako STP-073/076/077)."""

    def test_schema_fields_present(self) -> None:
        m = load_manifest(MANIFEST)
        assert m["version"] == 1
        assert m["parser_id"] == "sqlite"
        assert m["schema_variant"] == "apple_imessage_chatdb"
        query = m["queries"][0]
        assert query["type"] == "imessage"
        assert query["converter"] in CONVERTERS
        assert _jk_from_manifest(m) == {"imessage": ("handle", "ts")}

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


class TestCfabsoluteConverter:
    """``cfabsolute_to_unix_s`` — přesná reference (nezávislá na stopa.domain.times)."""

    def test_whole_seconds_exact(self) -> None:
        assert cfabsolute_to_unix_s(BASE_CF) == 1_750_000_000

    def test_subsecond_fraction_floors(self) -> None:
        # frakce .5 s se flooruje dolů — stejně jako floor v normalizaci STOPA cesty
        assert cfabsolute_to_unix_s(BASE_CF + 0.5) == 1_750_000_000
        assert cfabsolute_to_unix_s(BASE_CF + 0.999) == 1_750_000_000

    def test_zero_is_apple_epoch(self) -> None:
        # CFAbsoluteTime 0 = 2001-01-01T00:00Z (na rozdíl od unix ms, kde je
        # 0 epocha 1970 — jiná epocha = jiný kontrakt pro hodnotu nula)
        assert cfabsolute_to_unix_s(0) == CFABSOLUTE_UNIX_OFFSET_S

    def test_offset_constant_value(self) -> None:
        # počet sekund z 1970-01-01T00:00Z do 2001-01-01T00:00Z (nezávislá kontrola)
        dt = datetime.fromtimestamp(CFABSOLUTE_UNIX_OFFSET_S, tz=timezone.utc)
        assert (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second) == (2001, 1, 1, 0, 0, 0)

    def test_int_input_accepted(self) -> None:
        # SQLite dynamické typování: REAL sloupec může vrátit int — vstup int je platný
        assert cfabsolute_to_unix_s(100) == CFABSOLUTE_UNIX_OFFSET_S + 100

    def test_known_calendar_date(self) -> None:
        # nezávislý kalendářní cross-check offsetu (bez stopa.domain.times)
        ts = cfabsolute_to_unix_s(BASE_CF)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        assert (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second) == (2025, 6, 15, 15, 6, 40)

    def test_type_errors(self) -> None:
        for bad in ("7.5", True, False, None, [1.0], {"v": 1.0}):
            with pytest.raises(TypeError):
                cfabsolute_to_unix_s(bad)  # type: ignore[arg-type]

    def test_negative_value_error(self) -> None:
        with pytest.raises(ValueError):
            cfabsolute_to_unix_s(-0.5)

    def test_non_finite_value_errors(self) -> None:
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError):
                cfabsolute_to_unix_s(bad)


# ---------------------------------------------------------------- diffref vrstva


class TestDiffrefLayer:
    """Dvě nezávislé cesty nad chat.db fixturou — sémantické parity (§2)."""

    def test_adapter_resolve_sqlite_still_works(self) -> None:
        adapter = resolve_adapter("sqlite")
        assert adapter is not None

    def test_reference_entries_match_expected_golden(self) -> None:
        # Golden je deterministický snapshot KANONICKÉ referenční cesty (stejný
        # formát i pořadí jako STP-076/077 — normalize_dataset řadí záznamy).
        m = load_manifest(MANIFEST)
        jk = _jk_from_manifest(json.loads(MANIFEST.read_text(encoding="utf-8")))
        entries = read_reference_entries(FIXTURE, m)
        norm = normalize_dataset(entries, join_keys=jk)
        got = [
            {"type": r.type, "ts_epoch": r.ts_epoch, "fields": dict(r.fields)} for r in norm
        ]
        expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
        assert len(got) == len(expected) == 7
        # pořadí i obsah — drift v fixtuře/konvertéru/SUBSTR sémantice promítne do diffu
        assert got == expected

    def test_reference_read_does_not_touch_evidence(self, tmp_path: Path) -> None:
        # read-only otevření (file::…?mode=ro) — SHA důkazu se nemění
        m = load_manifest(MANIFEST)
        before = _sha256(FIXTURE)
        read_reference_entries(FIXTURE, m)
        assert _sha256(FIXTURE) == before

    def test_stopa_side_shape_imessage(self) -> None:
        entries = run_stopa_sqlite(FIXTURE)
        assert len(entries) == 7
        for e in entries:
            assert e["type"] == "imessage"
            fields = e["fields"]
            assert set(fields.keys()) == {"body", "handle"}
            assert isinstance(e.get("ts"), float)

    def test_stopa_side_excludes_where_filtered_rows(self) -> None:
        # WHERE parita: text IS NOT NULL AND date > 0 — fixtura má 9 řádků,
        # m8 (date=0) a m9 (NULL text) se na obou stranách nedostanou do výstupu
        for entries in (run_stopa_sqlite(FIXTURE), read_reference_entries(FIXTURE, load_manifest(MANIFEST))):
            assert len(entries) == 7

    def test_whitespace_only_fallback_both_sides(self) -> None:
        # m5 "   " → strip→[:300] or fallback na obou cestách = "(prázdná zpráva)"
        stopa_entries = run_stopa_sqlite(FIXTURE)
        ref_entries = read_reference_entries(FIXTURE, load_manifest(MANIFEST))
        for entries in (stopa_entries, ref_entries):
            bodies = [e["fields"]["body"] for e in entries]  # type: ignore[index]
            assert bodies.count("(prázdná zpráva)") == 1

    def test_long_body_350_chars_truncated_to_300(self) -> None:
        # m6 — 350 znaků ASCII: parita truncace STOPA title[:300] vs. SQL SUBSTR(…,1,300)
        stopa_entries = run_stopa_sqlite(FIXTURE)
        ref_entries = read_reference_entries(FIXTURE, load_manifest(MANIFEST))
        for entries in (stopa_entries, ref_entries):
            long_bodies = [e["fields"]["body"] for e in entries if len(e["fields"]["body"]) > 100]  # type: ignore[index]
            assert len(long_bodies) == 1
            assert len(long_bodies[0]) == 300

    def test_nfkc_ligature_equivalence(self) -> None:
        # m4 — ligatura ﬁ (U+FB01): surová reference drží ligaturu, kanonická
        # normalizace NFKC ji rozloží na "fi" shodně s STOPA cestou (§3.3)
        ref_raw = read_reference_entries(FIXTURE, load_manifest(MANIFEST))
        raw_with_ligature = [e for e in ref_raw if "\ufb01" in str(e["fields"].get("body", ""))]  # type: ignore[union-attr]
        assert len(raw_with_ligature) == 1

        jk = _jk_from_manifest(json.loads(MANIFEST.read_text(encoding="utf-8")))
        ref_norm = normalize_dataset(ref_raw, join_keys=jk)
        normalized_bodies = [r.fields.get("body") for r in ref_norm]  # type: ignore[union-attr]
        assert "Meeting re: Q3 finance report" in normalized_bodies
        assert not any("\ufb01" in str(b) for b in normalized_bodies if b is not None)


# ---------------------------------------------------------------- E2E pipeline


class TestEndToEndPipeline:
    """Dvě nezávislé cesty se na chat.db fixture shodují 100 % (design §2/§6)."""

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
        # m3 frakce .5 s (handle PHONE_HANDLE): STOPA float ts drží podsekundovou
        # frakci; reference je celočíselná floor — normalizace sjednotí obě cesty.
        stopa_entries, adapter = run_both_sides("sqlite", FIXTURE)
        ref_entries = adapter.read_reference(FIXTURE, load_manifest(MANIFEST))

        def ts_of(entries: list[dict[str, object]]) -> int | float | None:
            for e in entries:
                fields = e.get("fields")
                if isinstance(fields, dict) and fields.get("handle") == PHONE_HANDLE:
                    body = str(fields.get("body", ""))
                    if body.startswith("Dobře"):  # m3 — duplicitní sekunda s m1
                        return e.get("ts")  # type: ignore[return-value]
            return None

        stopa_ts = ts_of(stopa_entries)
        ref_ts = ts_of(ref_entries)
        assert ref_ts == 1_750_000_000
        assert stopa_ts is not None
        assert math.floor(float(stopa_ts)) == ref_ts

    def test_duplicate_join_key_pairing_deterministic(self) -> None:
        # m1+m3 sdílejí [handle, ts] po floor normalizaci (.5 s frakce) — duplicitní
        # key se páruje pořadově deterministicky (sort_records obsahuje pole v klíči);
        # obě zprávy od PHONE_HANDLE ve stejně sekundě musí projít komparací bez DIFFS.
        m = load_manifest(MANIFEST)
        jk = _jk_from_manifest(json.loads(MANIFEST.read_text(encoding="utf-8")))
        stopa_entries, adapter = run_both_sides("sqlite", FIXTURE)
        ref_entries = adapter.read_reference(FIXTURE, m)

        for entries in (stopa_entries, ref_entries):
            same_key = [
                e for e in entries
                if isinstance(e.get("fields"), dict)
                and e["fields"].get("handle") == PHONE_HANDLE  # type: ignore[union-attr]
                and math.floor(float(e.get("ts", 0))) == 1_750_000_000
            ]
            assert len(same_key) == 2

        report = build_report(
            parser="sqlite",
            stopa_records=normalize_dataset(stopa_entries, join_keys=jk),
            ref_records=normalize_dataset(ref_entries, join_keys=jk),
            join_keys=jk,
        )
        assert report.differences == ()


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
    """``stopa differential sqlite --raw F --manifest M`` na apple_imessage_chatdb manifestu."""

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
