"""STP-079 — Android calllog.db reference varianta (§7, vlna 6).

Pátá schémová varianta SQLite rodiny nad existujícím generic adaptérem:
tabulka ``calls`` (unix ms; volitelné sloupce duration/type) + kanonický typ
``call_log`` s poli number/duration_s/direction. STOPA extraktor dává číslo do
titleu formátu f"Hovor — {number}" → diffref ho rekonstruuje removeprefixem
(stejný princip jako body z titleu u STP-076/077/078). Deterministická offline
fixtura je commitnuta v ``reference_datasets/sqlite/android_calllog/`` (SHA pin
+ writer-version byte-stabilita).

Pokrytí:

* SHA-pin fixtury + byte-determinismus rebuildu (guard proti driftu důkazu)
* manifestová smlouva (stejný tvar jako STP-073/076/077/078)
* konvertér ``unix_ms_to_unix_s`` — frakce .500 s se flooruje na obou cestách
  (STOPA float ms/1000.0 + floor normalizace ≡ reference celočíselné //1_000)
* diffref vrstva: reference vs. STOPA strana nad stejným souborem (read-only),
  WHERE parita ``date > 0`` obou stran, NFKC NBSP→mezera v čísle (§3.3),
  explicitní None == None pro NULL duration/type (§3.3)
* duplicitní join key [number, ts] po floor normalizaci (řádky 1+2, frakce .5 s)
  párován deterministicky stabilním klíčem (§3.2)
* E2E pipeline: dvě nezávislé cesty se shodují 100 % (DIFFS=0)
* CLI auto-režim ``stopa differential sqlite --raw F --manifest M`` + exit kódy §6
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sqlite3
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

DS = Path(__file__).parent / "reference_datasets" / "sqlite" / "android_calllog"
FIXTURE = DS / "calllog.db"
MANIFEST = DS / "manifest.json"
EXPECTED = DS / "expected_records.json"

# Základní sekunda fixtury (unix) — řádky 1/2 sdílejí po flooru [number, ts]
BASE_TS = 1_750_000_000
NUMBER_PLUS = "+420777123456"  # řádky 1/2/8 (stejné číslo, tři sekundy + duplicitní)
NUMBER_BARE = "420777123456"  # řádky 5/6 (číslo bez "+" prefixu, dvě sekundy)
NUMBER_NBSP_RAW = "+420\u00a0777 123 456"  # řádek 4 — surové NBSP v čísle


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

    def test_fixture_row_count_pinned(self) -> None:
        # read-only dotaz na důkaz: přesně 8 řádků (řádek s date=0 je v DB, ale
        # WHERE paritu vynechává; NULL number se fixture záměrně neobjevuje —
        # make_join_key fail-fast §3.4, viz manifest contract_note)
        conn = sqlite3.connect(f"file:{FIXTURE}?mode=ro", uri=True)
        try:
            total = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
            excluded = conn.execute("SELECT COUNT(*) FROM calls WHERE date <= 0").fetchone()[0]
            null_number = conn.execute(
                "SELECT COUNT(*) FROM calls WHERE number IS NULL"
            ).fetchone()[0]
        finally:
            conn.close()
        assert total == 8
        assert excluded == 1  # řádek s date = 0
        assert null_number == 0


# ---------------------------------------------------------------- manifest


class TestManifestSchema:
    """Smlouva android_calllog manifestu (stejný tvar jako STP-073/076/077/078)."""

    def test_schema_fields_present(self) -> None:
        m = load_manifest(MANIFEST)
        assert m["version"] == 1
        assert m["parser_id"] == "sqlite"
        assert m["schema_variant"] == "android_calllog"
        query = m["queries"][0]
        assert query["type"] == "call_log"
        assert query["converter"] in CONVERTERS
        assert _jk_from_manifest(m) == {"call_log": ("number", "ts")}

    def test_converter_registered_and_floors_subsecond(self) -> None:
        # unix ms → s celočíselně; frakce .500 s se flooruje (stejná cesta jako
        # STP-076/077 — konvertér je sdílený, pinujeme jen fixturální hodnotu)
        assert "unix_ms_to_unix_s" in CONVERTERS
        assert unix_ms_to_unix_s(BASE_TS * 1_000 + 500) == BASE_TS

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


# ---------------------------------------------------------------- diffref vrstva


class TestDiffrefLayer:
    """Dvě nezávislé cesty nad calllog.db fixturou — sémantické parity (§2)."""

    def test_adapter_resolve_sqlite_still_works(self) -> None:
        adapter = resolve_adapter("sqlite")
        assert adapter is not None

    def test_reference_entries_match_expected_golden(self) -> None:
        # Golden je deterministický snapshot KANONICKÉ referenční cesty (stejný
        # formát i pořadí jako STP-076/077/078 — normalize_dataset řadí záznamy;
        # duplicitní [number, ts] řádky 1+2 se řadí stabilním klíčem §3.2).
        m = load_manifest(MANIFEST)
        jk = _jk_from_manifest(json.loads(MANIFEST.read_text(encoding="utf-8")))
        entries = read_reference_entries(FIXTURE, m)
        norm = normalize_dataset(entries, join_keys=jk)
        got = [
            {"type": r.type, "ts_epoch": r.ts_epoch, "fields": dict(r.fields)} for r in norm
        ]
        expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
        assert len(got) == len(expected) == 7
        # pořadí i obsah — drift v fixtuře/konvertéru/ORDER BY promítne do diffu
        assert got == expected

    def test_reference_read_does_not_touch_evidence(self, tmp_path: Path) -> None:
        # read-only otevření (file::…?mode=ro) — SHA důkazu se nemění
        m = load_manifest(MANIFEST)
        before = _sha256(FIXTURE)
        read_reference_entries(FIXTURE, m)
        assert _sha256(FIXTURE) == before

    def test_stopa_side_shape_call_log(self) -> None:
        entries = run_stopa_sqlite(FIXTURE)
        assert len(entries) == 7
        for e in entries:
            assert e["type"] == "call_log"
            fields = e["fields"]
            assert set(fields.keys()) == {"number", "duration_s", "direction"}
            assert isinstance(e.get("ts"), float)

    def test_stopa_title_format_pinned(self) -> None:
        # diffref rekonstruuje number removeprefixem z titleu — pinujeme, že STOPA
        # extraktor drží formát f"Hovor — {number}" (prefix + nenulové číslo) pro
        # všechny call_log artifacty; bez tohoto kontraktu by removeprefix tichě
        # vrátil celý title a komparace se reference rozpadla.
        from stopa.artifacts.sqlite_extract import extract_sqlite_artifacts

        arts = [a for a in extract_sqlite_artifacts(FIXTURE)]
        assert len(arts) == 7
        prefix = "Hovor — "
        for a in arts:
            assert a.title is not None and a.title.startswith(prefix)
            number = a.title[len(prefix):]
            assert number  # NULL number by title vykreslil jako "None" → fixture nenulové

    def test_where_parity_both_sides(self) -> None:
        # WHERE parita ``date > 0``: fixtura má 8 řádků, řádek s date=0 se na obou
        # stranách nedostane do výstupu (STOPA extraktor i referenční dotaz)
        stopa_entries = run_stopa_sqlite(FIXTURE)
        ref_entries = read_reference_entries(FIXTURE, load_manifest(MANIFEST))
        assert len(stopa_entries) == 7
        assert len(ref_entries) == 7

    def test_null_duration_direction_explicit_none_both_sides(self) -> None:
        # řádek 4 — NULL duration/type: explicitní None na obou stranách (§3.3:
        # None ≠ chybějící pole); klíč se v fields objeví, hodnota je None
        jk = _jk_from_manifest(json.loads(MANIFEST.read_text(encoding="utf-8")))
        for entries in (run_stopa_sqlite(FIXTURE), read_reference_entries(FIXTURE, load_manifest(MANIFEST))):
            norm = normalize_dataset(entries, join_keys=jk)
            null_rows = [r for r in norm if r.fields.get("duration_s") is None]
            assert len(null_rows) == 1
            row = null_rows[0]
            assert row.ts_epoch == BASE_TS + 123
            assert "duration_s" in dict(row.fields) and "direction" in dict(row.fields)
            assert row.fields["direction"] is None

    def test_subsecond_row_ts_agrees_both_sides(self) -> None:
        # řádek 2 (frakce .500 s, NUMBER_PLUS): STOPA float ts drží podsekundovou
        # frakci; reference je celočíselná floor — normalizace sjednotí obě cesty.
        stopa_entries = run_stopa_sqlite(FIXTURE)
        ref_entries = read_reference_entries(FIXTURE, load_manifest(MANIFEST))

        def subsecond_ts(entries: list[dict[str, object]]) -> int | float | None:
            for e in entries:
                fields = e.get("fields")
                if not isinstance(fields, dict):
                    continue
                # řádek 2 (frakce .5 s) je odlišitelný duration_s=456 — řádek 1 má 123
                if (
                    fields.get("number") == NUMBER_PLUS
                    and fields.get("duration_s") == 456
                    and isinstance(e.get("ts"), (int, float))
                    and math.floor(float(e["ts"])) == BASE_TS
                ):
                    return e["ts"]  # type: ignore[return-value]
            return None

        stopa_ts = subsecond_ts(stopa_entries)
        ref_ts = subsecond_ts(ref_entries)
        assert ref_ts == BASE_TS
        assert stopa_ts is not None
        assert float(stopa_ts) > BASE_TS  # STOPA drží frakci .5 s
        assert math.floor(float(stopa_ts)) == ref_ts

    def test_nfkc_nbsp_number_equivalence(self) -> None:
        # řádek 4 — NBSP (U+00A0) v čísle: surové cesty drží NBSP, kanonická
        # normalizace NFKC ho sjednotí na běžnou mezeru shodně na obou stranách (§3.3)
        jk = _jk_from_manifest(json.loads(MANIFEST.read_text(encoding="utf-8")))

        stopa_raw = run_stopa_sqlite(FIXTURE)
        ref_raw = read_reference_entries(FIXTURE, load_manifest(MANIFEST))
        for entries in (stopa_raw, ref_raw):
            raw_with_nbsp = [
                e for e in entries
                if isinstance(e.get("fields"), dict)
                and "\u00a0" in str(e["fields"].get("number", ""))  # type: ignore[union-attr]
            ]
            assert len(raw_with_nbsp) == 1

        for norm in (normalize_dataset(stopa_raw, join_keys=jk), normalize_dataset(ref_raw, join_keys=jk)):
            numbers = [r.fields.get("number") for r in norm]
            assert "+420 777 123 456" in numbers  # NBSP → mezera
            assert not any("\u00a0" in str(n) for n in numbers if n is not None)


# ---------------------------------------------------------------- E2E pipeline


class TestEndToEndPipeline:
    """Dvě nezávislé cesty se na calllog.db fixture shodují 100 % (design §2/§6)."""

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

    def test_duplicate_join_key_pairing_deterministic(self) -> None:
        # řádky 1+2 sdílejí [number, ts] po floor normalizaci (.5 s frakce) —
        # duplicitní key se páruje pořadově deterministicky (sort_records obsahuje
        # pole v klíči §3.2); oba hovory od NUMBER_PLUS ve stejné sekundě musí
        # projít komparací bez DIFFS i při libovolném zdrojovém pořadí řádků.
        m = load_manifest(MANIFEST)
        jk = _jk_from_manifest(json.loads(MANIFEST.read_text(encoding="utf-8")))
        stopa_entries, adapter = run_both_sides("sqlite", FIXTURE)
        ref_entries = adapter.read_reference(FIXTURE, m)

        for entries in (stopa_entries, ref_entries):
            same_key = [
                e for e in entries
                if isinstance(e.get("fields"), dict)
                and e["fields"].get("number") == NUMBER_PLUS  # type: ignore[union-attr]
                and math.floor(float(e.get("ts", 0))) == BASE_TS
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
    """``stopa differential sqlite --raw F --manifest M`` na android_calllog manifestu."""

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
