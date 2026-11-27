"""STP-072 — ``stopa differential`` CLI (design §6) — funkční testy.

Offline a deterministické: JSON soubory v ``tmp_path`` + zavedený vzor
``main([...])`` + capsys (viz test_r04_cli_ux.py). Exit kódy dle designu §6:

- **0** — shoda, žádné rozdíly
- **3** — pouze adjudikované SEMANTIC_DIFF
- **1** — neadjudikovaný / STOPA_WRONG / REF_WRONG / AMBIGUOUS rozdíl
- **2** — vstupní chyba (soubor, JSON, deklarace join keyů)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from stopa.cli import main


def _write(tmp_path: Path, name: str, entries: object) -> str:
    p = tmp_path / name
    if isinstance(entries, (list, dict)):
        p.write_text(json.dumps(entries), encoding="utf-8")
    else:  # raw text pro testy neplatného JSONu
        p.write_text(str(entries), encoding="utf-8")
    return str(p)


_IDENTICAL = [
    {"type": "visit", "ts": 1_700_000_000, "fields": {"url": "https://a"}},
    {"type": "visit", "ts": 1_700_000_001, "fields": {"url": "https://b"}},
]


def _run_diff(
    capsys,
    tmp_path: Path,
    *,
    stopa_entries: object = _IDENTICAL,
    ref_entries: object | None = None,
    extra: tuple[str, ...] = (),
) -> tuple[int, str, str]:
    """Spustí ``main(["differential", ...])`` a vrátí (rc, stdout, stderr).

    Vždy se přidá výchozí deklarace join keyu ``visit=url`` (§3.4 — bez ní
    komparace selže fail-fast); ``ref_entries=None`` = reference identická STOPA.
    """
    inp = _write(tmp_path, "stopa.json", stopa_entries)
    ref = _write(tmp_path, "ref.json", ref_entries if ref_entries is not None else stopa_entries)
    argv = ["differential", "sqlite", "--input", inp, "--ref", ref, *extra, "--join-key", "visit=url"]
    rc = main(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _write_pair(tmp_path: Path, stopa_entries: object = _IDENTICAL, ref_entries: object | None = None) -> tuple[str, str]:
    """Napíše oba soubory a vrátí (input, ref) cesty — pro ruční argv bez výchozího join keyu."""
    inp = _write(tmp_path, "stopa.json", stopa_entries)
    ref = _write(tmp_path, "ref.json", ref_entries if ref_entries is not None else stopa_entries)
    return inp, ref


def test_help_has_example_and_options(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["differential", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "Příklad:" in out  # R0.4 kontrakt
    for opt in ("--input", "--ref", "--tool", "--join-key", "--adjudications", "--run-id"):
        assert opt in out


def test_exit_0_identical_text_report(capsys, tmp_path):
    rc, out, _ = _run_diff(capsys, tmp_path)
    assert rc == 0
    assert "Diferenciální komparace: parser=sqlite reference=(nedeklarováno)" in out
    assert "STOPA záznamy: 2 | reference: 2 | identické: 100.0 %" in out
    assert "Rozdíly: žádné — výstupy se shodují." in out


def test_exit_0_json_report_shape(capsys, tmp_path):
    rc, out, _ = _run_diff(capsys, tmp_path, extra=("--format", "json"))
    assert rc == 0
    data = json.loads(out)
    assert data["parser"] == "sqlite"
    assert data["differences"] == []
    assert data["stopa_records"] == 2 and data["ref_records"] == 2
    assert data["identical_pct"] == 100.0
    # determinismus: sha256 vstupního souboru je v reportu (§4)
    expected = hashlib.sha256((tmp_path / "stopa.json").read_bytes()).hexdigest()
    assert data["input_sha256"] == expected


def test_exit_1_unadjudicated_extra_in_stopa(capsys, tmp_path):
    stopa = _IDENTICAL + [{"type": "visit", "ts": 9, "fields": {"url": "https://x"}}]
    rc, out, _ = _run_diff(capsys, tmp_path, stopa_entries=stopa, ref_entries=_IDENTICAL)
    assert rc == 1
    assert "[extra_in_stopa] visit:https://x" in out


def test_exit_3_semantic_diff_via_adjudications(capsys, tmp_path):
    stopa = [{"type": "visit", "ts": 5, "fields": {"url": "https://x"}}]
    ref = [{"type": "visit", "ts": 6, "fields": {"url": "https://x"}}]
    adjudications = _write(
        tmp_path,
        "adjud.json",
        {
            "field_differs:visit:https://x:ts_epoch": {
                "status": "SEMANTIC_DIFF",
                "reason": "odlišná reprezentace času",
            }
        },
    )
    rc, out, _ = _run_diff(
        capsys, tmp_path, stopa_entries=stopa, ref_entries=ref, extra=("--adjudications", adjudications)
    )
    assert rc == 3
    assert "[field_differs] visit:https://x ts_epoch" in out
    assert "SEMANTIC_DIFF (odlišná reprezentace času)" in out


def test_exit_1_stopa_wrong_verdict_in_json(capsys, tmp_path):
    stopa = [{"type": "visit", "ts": 5, "fields": {"url": "https://x"}}]
    ref = [{"type": "visit", "ts": 6, "fields": {"url": "https://x"}}]
    adjudications = _write(
        tmp_path, "adjud.json", {"field_differs:visit:https://x:ts_epoch": "STOPA_WRONG"}
    )
    rc, out, _ = _run_diff(
        capsys,
        tmp_path,
        stopa_entries=stopa,
        ref_entries=ref,
        extra=("--adjudications", adjudications, "--format", "json"),
    )
    assert rc == 1
    data = json.loads(out)
    assert len(data["differences"]) == 1
    assert data["differences"][0]["status"] == "STOPA_WRONG"


def test_adjudication_unknown_id_is_input_error(capsys, tmp_path):
    stopa = _IDENTICAL + [{"type": "visit", "ts": 9, "fields": {"url": "https://x"}}]
    adjudications = _write(tmp_path, "adjud.json", {"neznámé-id": "AMBIGUOUS"})
    rc, _, err = _run_diff(capsys, tmp_path, stopa_entries=stopa, extra=("--adjudications", adjudications))
    assert rc == 2
    assert "neznámé ID rozdílu" in err


def test_missing_input_file_rc2(capsys, tmp_path):
    ref = _write(tmp_path, "ref.json", _IDENTICAL)
    rc = main(["differential", "sqlite", "--input", str(tmp_path / "chybí.json"), "--ref", ref])
    assert rc == 2
    assert "chybí.json" in capsys.readouterr().err


def test_invalid_json_rc2(capsys, tmp_path):
    stopa = _write(tmp_path, "stopa.json", "{neplatný JSON")
    ref = _write(tmp_path, "ref.json", _IDENTICAL)
    rc = main(["differential", "sqlite", "--input", stopa, "--ref", ref])
    assert rc == 2
    assert "neplatný JSON" in capsys.readouterr().err


def test_non_list_json_rc2(capsys, tmp_path):
    stopa = _write(tmp_path, "stopa.json", {"type": "visit"})
    ref = _write(tmp_path, "ref.json", _IDENTICAL)
    rc = main(["differential", "sqlite", "--input", stopa, "--ref", ref])
    assert rc == 2
    assert "očekáváno JSON list" in capsys.readouterr().err


def test_missing_ref_is_mode_validation_exit2(capsys, tmp_path):
    # STP-073: --ref už není argparse-required (režimy jsou mutually exclusive);
    # chybějící --ref v JSON režimu → vstupní chyba exit 2 z validace režimů
    inp = _write(tmp_path, "stopa.json", _IDENTICAL)
    rc = main(["differential", "sqlite", "--input", inp])
    assert rc == 2
    assert "--input i --ref" in capsys.readouterr().err


def test_join_key_not_declared_rc2(capsys, tmp_path):
    # typ 'visit' bez --join-key → fail-fast (§3.4), ne tiché srovnání po sobě
    stopa = _write(tmp_path, "stopa.json", _IDENTICAL)
    ref = _write(tmp_path, "ref.json", _IDENTICAL)
    rc = main(["differential", "sqlite", "--input", stopa, "--ref", ref])
    assert rc == 2
    assert "join key" in capsys.readouterr().err


def test_join_key_bad_format_rc2(capsys, tmp_path):
    inp, ref = _write_pair(tmp_path)
    rc = main(["differential", "sqlite", "--input", inp, "--ref", ref, "--join-key", "visit"])
    assert rc == 2
    assert "očekáváno TYPE=POLE" in capsys.readouterr().err


def test_join_key_duplicate_type_rc2(capsys, tmp_path):
    inp, ref = _write_pair(tmp_path)
    rc = main(
        ["differential", "sqlite", "--input", inp, "--ref", ref,
         "--join-key", "visit=url", "--join-key", "visit=path"]
    )
    assert rc == 2
    assert "deklarován dvakrát" in capsys.readouterr().err


def test_run_id_and_reference_tool_metadata(capsys, tmp_path):
    rc, out, _ = _run_diff(
        capsys, tmp_path, extra=("--tool", "sqlite3-dump", "--run-id", "run-42", "--format", "json")
    )
    assert rc == 0
    data = json.loads(out)
    assert data["reference_tool"] == "sqlite3-dump"
    assert data["run_id"] == "run-42"


def test_text_report_counts_and_duplicates_suffix(capsys, tmp_path):
    # ×N agregace kopií + výčet rozdílů v textovém reportu (design §4)
    stopa = [
        {"type": "visit", "ts": 1, "fields": {"url": "https://dup"}},
        {"type": "visit", "ts": 2, "fields": {"url": "https://dup"}},
        {"type": "visit", "ts": 3, "fields": {"url": "https://jen-stopa"}},
    ]
    rc, out, _ = _run_diff(capsys, tmp_path, stopa_entries=stopa, ref_entries=[])
    assert rc == 1
    assert "[extra_in_stopa] visit:https://dup ×2" in out
    assert "[extra_in_stopa] visit:https://jen-stopa" in out
    assert "Rozdíly (2):" in out
