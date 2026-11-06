"""STP-047 / ETAPA E vlna 2 — testy zapojení sandboxu do pipeline.

Pokrývají:
- ``_run_extractor`` přes REÁLNÝ sandbox subprocess (úspěch → artifacty);
- fallback bez sandboxu (``SANDBOX_ENABLED=False``) → přímé volání;
- selhání parseru v dceřiném procesu → ``parser_error`` artifact s kategorií;
- corrupt SQLite header (garbage ``db_size_pages``) přes celou pipeline —
  nesmí viset ani padnout (regrese audit STP-045).

Vše offline a deterministické. Sandbox cesty spouštějí reálný subprocess
(``python -m stopa.sandbox_worker``), takže jsou pomalejší než unit testy,
ale ověřují skutečný kontrakt end-to-end.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import struct
import time
from pathlib import Path

import stopa.pipeline as P

# ── helpery ────────────────────────────────────────────────────────────────


def _real_sqlite_db(tmp_path: Path, name: str = "History") -> Path:
    """Reálná SQLite DB s jednou tabulkou (pravá binární struktura)."""
    p = tmp_path / name
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
    conn.execute(
        "INSERT INTO urls VALUES (1, 'https://example.com/a', 'Stránka A')"
    )
    conn.commit()
    conn.close()
    return p


def _corrupt_header(page_size: int = 4096, db_size_pages: int = 1_700_000_000, total: int = 920) -> bytes:
    """Poškozený SQLite header — validní magic, garbage ``db_size_pages``."""
    buf = bytearray(total)
    buf[0:16] = b"SQLite format 3\x00"
    struct.pack_into(">H", buf, 16, page_size)
    struct.pack_into(">I", buf, 28, db_size_pages)
    return bytes(buf)


def _load_temp_module(tmp_path: Path, name: str, source: str):
    """Dočasný importovatelný modul (soubor + PYTHONPATH pro subprocess)."""
    mod_file = tmp_path / f"{name}.py"
    mod_file.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, mod_file)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── _run_extractor — sandbox subprocess (úspěch) ───────────────────────────


def test_run_extractor_sandbox_success(tmp_path: Path):
    """Reálná SQLite DB přes sandbox → artifacty, žádný parser_error."""
    assert P.SANDBOX_ENABLED is True  # defaultní konfigurace
    db = _real_sqlite_db(tmp_path)
    arts = P._run_extractor(P._extract_sqlite_all, db, "1.0")
    assert len(arts) >= 1
    assert all(a.artifact_type != "parser_error" for a in arts)
    # artifacty jsou plnohodnotné Pydantic modely (round-trip přes JSON funguje)
    assert all(isinstance(a, P.Artifact) for a in arts)


def test_run_extractor_sandbox_empty_result(tmp_path: Path):
    """Ne-SQLite soubor → sandbox ok + prázdný výsledek (žádný parser_error)."""
    p = tmp_path / "plain.txt"
    p.write_text("hello world", encoding="utf-8")
    arts = P._run_extractor(P._extract_sqlite_all, p, "1.0")
    assert arts == []


# ── _run_extractor — fallback bez sandboxu (přímé volání) ──────────────────


def test_run_extractor_disabled_falls_back_to_direct(tmp_path: Path, monkeypatch):
    """``SANDBOX_ENABLED=False`` → přímé volání extraktoru (původní chování)."""
    monkeypatch.setattr(P, "SANDBOX_ENABLED", False)
    db = _real_sqlite_db(tmp_path)
    arts = P._run_extractor(P._extract_sqlite_all, db, "1.0")
    assert len(arts) >= 1
    assert all(a.artifact_type != "parser_error" for a in arts)


# ── selhání parseru → parser_error artifact s kategorií ────────────────────


def test_run_extractor_crash_returns_parser_error(tmp_path: Path, monkeypatch):
    """Parser v dceřiném procesu hodí výjimku → crash + parser_error artifact."""
    assert P.SANDBOX_ENABLED is True
    mod = _load_temp_module(
        tmp_path,
        "sb_stp047_crash",
        'def boom(path):\n    raise ValueError("parser explodoval")\n',
    )
    # subprocess musí dočasný modul najít → PYTHONPATH v os.environ
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    arts = P._run_extractor(mod.boom, tmp_path / "x.db", "9.9")
    assert len(arts) == 1
    art = arts[0]
    assert art.artifact_type == "parser_error"
    assert art.details["category"] == "crash"
    assert "ValueError" in (art.details.get("error") or "")
    assert art.parser_version == "9.9"


def test_run_extractor_timeout_returns_parser_error(tmp_path: Path, monkeypatch):
    """Hangující parser → timeout + parser_error artifact s kategorií timeout."""
    assert P.SANDBOX_ENABLED is True
    mod = _load_temp_module(
        tmp_path,
        "sb_stp047_hang",
        'import time\n\ndef hang(path):\n    time.sleep(5)\n    return []\n',
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    # krátký timeout → deterministický (bez čekání 30 s)
    monkeypatch.setattr(P, "SANDBOX_CONFIG", P.SandboxConfig(timeout_s=1.5))
    t0 = time.monotonic()
    arts = P._run_extractor(mod.hang, tmp_path / "x.db", "9.9")
    elapsed = time.monotonic() - t0
    assert len(arts) == 1
    assert arts[0].artifact_type == "parser_error"
    assert arts[0].details["category"] == "timeout"
    # timeout se projeví v reálném čase (ne visí 5 s parseru)
    assert elapsed < 4.0


def test_parser_error_artifact_structure():
    """``_parser_error_artifact`` — stabilní struktura pro audit log."""
    from stopa.domain.sandbox import SandboxResult

    res = SandboxResult(ok=False, category="truncated", error="payload 99 B > limit")
    art = P._parser_error_artifact(P._extract_sqlite_all, "1.0", res)
    assert art.artifact_type == "parser_error"
    assert art.details["category"] == "truncated"
    assert art.details["error"] == "payload 99 B > limit"
    assert art.parser_version == "1.0"


# ── corrupt SQLite přes celou pipeline (regrese hang bugu) ─────────────────


def test_corrupt_sqlite_no_hang_full_pipeline(tmp_path: Path):
    """Garbage ``db_size_pages`` (1,7 mld. v 920 B) → pipeline nepadne a nevisí."""
    p = tmp_path / "corrupt.db"
    p.write_bytes(_corrupt_header())
    t0 = time.monotonic()
    arts, ver = P._extract_artifacts_for(p, "sqlite")
    elapsed = time.monotonic() - t0
    # bez carver fixu viselo >15 s; s fixem + sandboxem doběhne rychle.
    assert elapsed < 20.0, f"pipeline visela {elapsed:.1f} s na corrupt SQLite"
    assert ver == "1.0"
    # žádná výjimka; artifacty mohou být prázdné (corrupt = nic neobnovitelného)
    assert isinstance(arts, list)


def test_valid_sqlite_pipeline_unchanged(tmp_path: Path):
    """Regression: validní SQLite přes pipeline → stejné artifacty jako před sandboxem."""
    db = _real_sqlite_db(tmp_path)
    arts_sandboxed, ver1 = P._extract_artifacts_for(db, "sqlite")

    monkeypatch_disabled = P.SANDBOX_ENABLED
    try:
        P.SANDBOX_ENABLED = False
        arts_direct, ver2 = P._extract_artifacts_for(db, "sqlite")
    finally:
        P.SANDBOX_ENABLED = monkeypatch_disabled

    assert ver1 == ver2
    # stejný počet artifactů (sandbox nemění výsledek, jen izoluje běh)
    assert len(arts_sandboxed) == len(arts_direct)
    types_s = sorted(a.artifact_type for a in arts_sandboxed)
    types_d = sorted(a.artifact_type for a in arts_direct)
    assert types_s == types_d
