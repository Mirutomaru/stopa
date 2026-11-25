"""H2 — Čistota domain vrstvy: izolace lazy ``domain→data`` vazeb.

A. **AST guard (statický)**: žádný modul v ``src/stopa/domain/**`` nesmí
   importovat (ani lazy, ani relativní) z ``stopa.data.*`` — mosty na volitelné
   runtime capability žijí v neutrální vrstvě ``stopa.core``. Pinuje stav auditu
   (PLAN_BACKLOG H2 F-1..F-3) a brzdí nové vazby proti regresím.
B. **Shim identity pin**: ``stopa.data.rust_core is stopa.core.rust_core`` a
   likewise diagnostics — stará import cesta je alias stejného modulového
   objektu, takže monkeypatch atributů (F21/F23) funguje přes obě cesty.
C. **Behavior pin fallback cest přes core**: Rust facade nedostupná → domain
   ``carve()``/``hash_file()`` běží referenční Python cestou s platným výstupem;
   report sekce 11 degraduje bez výjimky.

Offline a deterministické (monkeypatch, bez sítě).
"""

from __future__ import annotations

import ast
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "stopa"
DOMAIN_DIR = SRC / "domain"


# ── A. AST guard: domain nesmí importovat stopa.data.* ────────────────────────


def _resolved_from(node: ast.ImportFrom, rel_parts: list[str]) -> str | None:
    """Dotted modul pro ImportFrom (relativní i absolutní), nebo None."""
    if node.level > 0:
        up = node.level - 1
        parts = list(rel_parts)  # cesty modulu bez souboru, např. ['domain', 'crypto']
        if up > len(parts):
            return None  # vyšší než stopa — jinak by nebyl platný import
        base_parts = parts[: len(parts) - up]
        prefix = "stopa." + ".".join(base_parts) + ("." if base_parts else "")
    else:
        prefix = ""  # absolutní modul je už plně kvalifikovaný
    if not node.module:
        return None  # holý `from .. import x` — jména bez modulu (viz names_hit)
    return prefix + node.module


def _data_imports(tree: ast.AST, rel_parts: list[str]) -> list[tuple[int, str]]:
    """Lokace importů do stopa.data.* (řádek, popis)."""

    def _hit(mod: str | None) -> bool:
        return mod is not None and (mod == "stopa.data" or mod.startswith("stopa.data."))

    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = _resolved_from(node, rel_parts)
            # `from stopa import data` → modul 'stopa', jméno 'data'
            names_hit = mod == "stopa" and any(a.name == "data" for a in node.names)
            if _hit(mod) or names_hit:
                what = f"{mod or '?'} ({', '.join(a.name for a in node.names)})"
                hits.append((node.lineno, what))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if _hit(alias.name):
                    hits.append((node.lineno, alias.name))
    return hits


def test_domain_has_no_data_imports() -> None:
    """Žádný modul domain/** nesmí importovat stopa.data.* (H2 F-1)."""
    violations: list[str] = []
    for py in sorted(DOMAIN_DIR.rglob("*.py")):
        rel_parts = py.relative_to(SRC).parts[:-1]  # např. ('domain', 'crypto')
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for lineno, what in _data_imports(tree, list(rel_parts)):
            violations.append(f"{py.relative_to(SRC)}:{lineno}: import {what}")
    assert not violations, "domain→data vazby:\n" + "\n".join(violations)


def test_guard_catches_synthetic_data_import(tmp_path: Path) -> None:
    """Mutace check: všechny formy data importů musí být chyceny."""

    def hits(code: str) -> list[tuple[int, str]]:
        return _data_imports(ast.parse(code), ["domain"])  # hloubka domain/x.py

    assert hits("from stopa.data import rust_core\n") != []
    assert hits("from ..data import rust_core\n") != []
    assert hits("import stopa.data.diagnostics\n") != []
    assert hits("from stopa import data\n") != []
    # čistý modul — bez vazby:
    assert hits("from pathlib import Path\nX = 1\n") == []


# ── B. Shim identity pin ──────────────────────────────────────────────────────


def test_data_shims_are_core_aliases() -> None:
    """Staré cesty data.* jsou alias stejného objektu jako core.* (H2 F-2)."""
    import stopa.core.diagnostics as core_diag
    import stopa.core.rust_core as core_rc
    import stopa.data.diagnostics as data_diag
    import stopa.data.rust_core as data_rc

    assert data_rc is core_rc, "data.rust_core musí být alias core.rust_core"
    assert data_diag is core_diag, "data.diagnostics musí být alias core.diagnostics"


def test_shim_public_names_available() -> None:
    """Veškeré public jmeny dostupné přes starou i novou cestu."""
    import stopa.data.diagnostics as data_diag
    import stopa.data.rust_core as data_rc

    for name in ("is_available", "rust_version", "hash_file", "find_offsets",
                 "block_dedupe_file", "block_dedupe_files", "reset_cache"):
        assert hasattr(data_rc, name), f"chybí {name}"
    for name in ("collect_diagnostics", "_try_version"):
        assert hasattr(data_diag, name), f"chybí {name}"


# ── C. Behavior pin fallback cest přes core ───────────────────────────────────

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_carve_fallback_when_rust_unavailable(monkeypatch) -> None:
    """Rust find_offsets→None → referenční Python carve najde PNG kandidáta."""
    import stopa.core.rust_core as core_rc
    from stopa.domain.carving import carve

    monkeypatch.setattr(core_rc, "find_offsets", lambda *a, **k: None)
    payload = b"\x00" * 32 + PNG_MAGIC + b"\xff" * 80
    out = carve(payload)
    assert len(out) >= 1, "referenční cesta neměla nic najít"
    pngs = [c for c in out if c.sig_type == "png"]
    assert pngs and pngs[0].offset == 32


def test_hash_file_fallback_when_rust_unavailable(tmp_path: Path, monkeypatch) -> None:
    """Rust hash_file→None → domain hash_file spočítá hashlib digest."""
    import stopa.core.rust_core as core_rc
    from stopa.domain.hashing import hash_file

    monkeypatch.setattr(core_rc, "hash_file", lambda *a, **k: None)
    content = b"forenzni obsah H2 " * 1000
    f = tmp_path / "h2.bin"
    f.write_bytes(content)
    result = hash_file(f, ("sha256",))
    assert result == {"sha256": hashlib.sha256(content).hexdigest()}


def _minimal_report_data():
    """Minimální ReportData pro build_html (tvar jako test_report.sample_data)."""
    from stopa.domain.report import CustodyItem, FlaggedFile, ReportData, SourceInfo

    ts = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
    return ReportData(
        case_id="h2-case",
        case_name="H2 purity case",
        examiner="Test Examiner",
        created_at=ts,
        sources=(SourceInfo(id="src-1", kind="folder", path="/evidence/h2", added_at=ts),),
        per_source_stats={"src-1": {"files": 1, "bytes": 10, "bad_ext": 0, "dups": 0, "signed": 0}},
        totals={"files": 1, "bytes": 10, "bad_ext": 0, "dups": 0, "signed": 0},
        artifact_counts={},
        custody_items=(CustodyItem(source_id="src-1", rel_path="a.txt", size_bytes=10, sha256=None),),
        flagged_files=(FlaggedFile(rel_path="a.txt", flags=("BAD-EXT",)),),
    )


def test_report_section11_degrades_when_core_missing(monkeypatch) -> None:
    """Sekce 11 reportu: core diagnostics nedostupná → build_html bez výjimky."""
    import stopa.core.diagnostics as core_diag

    def _boom() -> dict:
        raise ImportError("simulovaná nedostupnost")

    monkeypatch.setattr(core_diag, "collect_diagnostics", _boom)
    from stopa.domain.report import build_html

    html_doc = build_html(_minimal_report_data())
    assert isinstance(html_doc, str) and len(html_doc) > 100


def test_report_section11_uses_core_path(monkeypatch) -> None:
    """Sekce 11 reportu čte přes stopa.core.diagnostics (ne data)."""
    import stopa.core.diagnostics as core_diag

    calls: list[str] = []

    def _fake() -> dict:
        calls.append("called")
        return {"components": {"tsk_py": True, "ewf_container": False}}

    monkeypatch.setattr(core_diag, "collect_diagnostics", _fake)
    from stopa.domain.report import build_html

    html_doc = build_html(_minimal_report_data())
    assert calls == ["called"], "report musí volat collect_diagnostics"
    assert isinstance(html_doc, str) and len(html_doc) > 100


if __name__ == "__main__":  # pragma: no cover — rychlý sanity launch
    pytest.main([__file__, "-q"])
