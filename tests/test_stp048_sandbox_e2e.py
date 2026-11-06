"""STP-048 / ETAPA E vlna 3 — sandbox E2E testy + corrupt-file regression.

Pokrývají:
- umělý hangující parser PŘES CELÉ pipeline (``process_source``) →
  ``parser_error`` artifact s kategorií timeout v DB, ne visení;
- corrupt EVTX / LNK soubory (validní magic/signatura + garbage tělo) —
  poškozené binárky nepadají ani nevisí pipeline (regrese pro ostatní
  binární parsery; SQLite je pokryto STP-047);
- plný ``process_source`` E2E na corrupt EVTX+LNK evidenci → doběhne rychle,
  artifacty v DB, žádný parser_error.

Vše offline a deterministické. Sandbox cesty spouštějí reálný subprocess
(``python -m stopa.sandbox_worker``), takže jsou pomalejší než unit testy,
ale ověřují skutečný kontrakt end-to-end.
"""

from __future__ import annotations

import importlib.util
import json
import struct
import time
from pathlib import Path

import stopa.pipeline as P
from stopa.data.db import CaseDB

# ── helpery ────────────────────────────────────────────────────────────────


def _corrupt_sqlite_header(
    page_size: int = 4096, db_size_pages: int = 1_700_000_000, total: int = 920
) -> bytes:
    """Poškozený SQLite header — validní magic, garbage ``db_size_pages``."""
    buf = bytearray(total)
    buf[0:16] = b"SQLite format 3\x00"
    struct.pack_into(">H", buf, 16, page_size)
    struct.pack_into(">I", buf, 28, db_size_pages)
    return bytes(buf)


def _corrupt_evtx() -> bytes:
    """Corrupt EVTX — validní magic ``EVTX`` + garbage tělo (žádné chunky)."""
    return b"EVTX" + b"\x00\x01\x02\x03" * 64


# LNK signatura z domain/signatures.py: cbLinkHeaderSize=76 + IShellLink CLSID @4
_LNK_SIG = (
    b"\x4c\x00\x00\x00"  # cbLinkHeaderSize = 76
    b"\x01\x14\x02\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x00\x00\x00\x46"
)


def _corrupt_lnk() -> bytes:
    """Corrupt LNK — validní signatura + garbage tělo (žádné platné link info)."""
    return _LNK_SIG + b"\xff" * 200


def _load_temp_module(tmp_path: Path, name: str, source: str):
    """Dočasný importovatelný modul (soubor + PYTHONPATH pro subprocess)."""
    mod_file = tmp_path / f"{name}.py"
    mod_file.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, mod_file)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_case_db(tmp_path: Path) -> tuple[CaseDB, str]:
    """Čerstvá case DB se zdrojem (folder) — konvence test_e3.py."""
    from stopa.models import Case, EvidenceSource

    db = CaseDB(tmp_path / "case-stp048.db")
    case = Case(name="STP-048 E2E", examiner="Znalec STP-048")
    db.add_case(case)
    src = EvidenceSource(case_id=case.id, kind="folder", path="/evidence/stp048")
    db.add_source(src)
    return db, src.id


# ── umělý hangující parser přes celou pipeline (E2E process_source) ────────


def test_hanging_parser_full_pipeline_parser_error_in_db(tmp_path: Path, monkeypatch):
    """Hangující parser registrovaný pod signaturu ``sqlite`` → ``process_source``

    doběhne (ne visí), v DB je ``parser_error`` artifact s kategorií timeout.
    Regrese audit STP-045: bez sandboxu by pipeline visela na parseru navěky.
    """
    assert P.SANDBOX_ENABLED is True  # defaultní konfigurace

    mod = _load_temp_module(
        tmp_path,
        "sb_stp048_hang",
        'import time\n\ndef hang(path):\n    time.sleep(5)\n    return []\n',
    )
    # subprocess musí dočasný modul najít → PYTHONPATH v os.environ
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    # hangující parser pod signaturou sqlite (corrupt header ho spustí)
    monkeypatch.setitem(P.ARTIFACT_EXTRACTORS, "sqlite", (mod.hang, "9.9"))
    # krátký timeout → deterministický (bez čekání 30 s)
    monkeypatch.setattr(P, "SANDBOX_CONFIG", P.SandboxConfig(timeout_s=1.5))

    root = tmp_path / "evidence"
    root.mkdir()
    (root / "corrupt.db").write_bytes(_corrupt_sqlite_header())

    db, src_id = _make_case_db(tmp_path)
    t0 = time.monotonic()
    result = P.process_source(db, src_id, root, "forensic", max_workers=1)
    elapsed = time.monotonic() - t0

    # pipeline doběhla — bez sandboxu by visela na parseru (sleep 5 s + spawn)
    assert elapsed < 20.0, f"pipeline visela {elapsed:.1f} s na hangujícím parseru"
    assert result.files_total == 1
    # parser_error artifact se počítá jako extrahovaný nález
    assert result.artifacts_extracted >= 1

    rows = db.conn.execute(
        "SELECT artifact_type, details_json FROM artifacts WHERE source_id = ?",
        (src_id,),
    ).fetchall()
    errors = [r for r in rows if r["artifact_type"] == "parser_error"]
    assert len(errors) == 1, f"očekáván 1 parser_error řádek, dostal {len(rows)}: {rows}"
    details = json.loads(errors[0]["details_json"])
    assert details["category"] == "timeout"
    # audit log — který parser selhal (reprodukovatelnost)
    assert "sb_stp048_hang.hang" in details.get("parser", "")
    db.close()


# ── corrupt EVTX / LNK přes extrakční cestu (regrese binárních parserů) ────


def test_corrupt_evtx_pipeline_no_crash(tmp_path: Path):
    """Corrupt EVTX (validní magic + garbage tělo) → pipeline nepadne a nevisí."""
    assert P.SANDBOX_ENABLED is True  # reálný sandbox subprocess
    p = tmp_path / "corrupt.evtx"
    p.write_bytes(_corrupt_evtx())
    t0 = time.monotonic()
    arts, _ver = P._extract_artifacts_for(p, "evtx")
    elapsed = time.monotonic() - t0
    assert isinstance(arts, list)  # žádná výjimka z dceřiného procesu
    assert elapsed < 20.0, f"pipeline visela {elapsed:.1f} s na corrupt EVTX"
    # parser je defenzivní — garbage tělo = žádné chunky = prázdný výsledek
    assert arts == []


def test_corrupt_lnk_pipeline_no_crash(tmp_path: Path):
    """Corrupt LNK (validní signatura + garbage tělo) → pipeline nepadne a nevisí."""
    assert P.SANDBOX_ENABLED is True  # reálný sandbox subprocess
    p = tmp_path / "corrupt.lnk"
    p.write_bytes(_corrupt_lnk())
    t0 = time.monotonic()
    arts, _ver = P._extract_artifacts_for(p, "lnk")
    elapsed = time.monotonic() - t0
    assert isinstance(arts, list)  # žádná výjimka z dceřiného procesu
    assert elapsed < 20.0, f"pipeline visela {elapsed:.1f} s na corrupt LNK"
    # parser extrahuje co umí (header CLSID) — důležité je, že nepadl sandboxem
    assert all(isinstance(a, P.Artifact) for a in arts)


# ── plný process_source E2E na corrupt EVTX+LNK evidenci ───────────────────


def test_process_source_corrupt_evtx_lnk_e2e(tmp_path: Path):
    """Corrupt EVTX + LNK v evidenci → ``process_source`` doběhne rychle,

    artifacty jsou v DB a žádný parser_error (parsery zvládají garbage).
    """
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "System.evtx").write_bytes(_corrupt_evtx())
    (root / "shortcut.lnk").write_bytes(_corrupt_lnk())

    db, src_id = _make_case_db(tmp_path)
    t0 = time.monotonic()
    result = P.process_source(db, src_id, root, "forensic", max_workers=1)
    elapsed = time.monotonic() - t0

    assert elapsed < 30.0, f"pipeline visela {elapsed:.1f} s na corrupt evidenci"
    assert result.files_total == 2

    rows = db.conn.execute(
        "SELECT artifact_type FROM artifacts WHERE source_id = ?", (src_id,)
    ).fetchall()
    types = [r["artifact_type"] for r in rows]
    # LNK parser extrahuje header i z garbage těla; EVTX vrací [] — žádný crash
    assert "parser_error" not in types, f"corrupt binárky způsobily parser_error: {types}"
    db.close()
