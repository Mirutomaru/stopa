"""B1 — pin stopa_core wheels: offline konzistence pyproject ↔ manifest ↔ lockfile.

Jednotkové testy běží **offline** (bez sítě): struktura manifestu, obousobní shoda
URL a verze/pin/markery. Plná SHA-256 kontrola reálných release assetů běží v CI
jobu ``lockfile-rust-pin`` přes ``scripts/verify_rust_wheel.py``.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import tomllib

REPO = Path(__file__).resolve().parent.parent
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _carving_urls() -> list[str]:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["optional-dependencies"].get("carving", [])
    return [d.split("@ ", 1)[1].split(" ;")[0].strip() for d in deps if "@" in d]


def _manifest() -> dict:
    return json.loads((REPO / ".github" / "wheel_pins.json").read_text(encoding="utf-8"))


def test_manifest_structure() -> None:
    m = _manifest()
    assert isinstance(m.get("version"), str) and m["version"]
    assert isinstance(m.get("core_version"), str) and m["core_version"]
    wheels = m.get("wheels", {})
    assert set(wheels) == {"x86_64", "aarch64"}
    for name, entry in wheels.items():
        assert entry.get("url", "").startswith("https://"), f"{name}: URL"
        assert _SHA256_RE.match(entry.get("sha256", "")), f"{name}: SHA-256 formát"
        assert isinstance(entry.get("size_bytes"), int) and entry["size_bytes"] > 0, f"{name}: size"


def test_pyproject_manifest_urls_bidirectional() -> None:
    """pyproject (zdroj pravdy pro URL/verzi) a manifest musí sedět obousobně."""
    m = _manifest()
    urls = _carving_urls()
    assert len(urls) == 2, f"očekávám 2 carving URL, mám {len(urls)}"
    man_urls = [w["url"] for w in m["wheels"].values()]
    assert sorted(man_urls) == sorted(urls), "URL se neshodují pyproject↔manifest"
    for url in urls:
        assert f"/v{m['version']}/" in url, f"chybí pin v{m['version']} v {url}"
        for marker in ("cp310-abi3", "manylinux_2_28"):
            assert marker in url, f"chybí marker {marker} v {url}"


def test_lockfile_contains_both_wheels() -> None:
    """requirements.lock musí obsahovat oba stopa_core wheels (reprodukovatelnost)."""
    lock = REPO / "requirements.lock"
    assert lock.exists(), "chybí requirements.lock"
    text = lock.read_text(encoding="utf-8")
    for url in _carving_urls():
        assert url in text, f"lock neobsahuje {url}"


def test_lockfile_has_hashes() -> None:
    """Lock s hashi — reprodukovatelná instalace (W1)."""
    text = (REPO / "requirements.lock").read_text(encoding="utf-8")
    assert "--hash=sha256:" in text, "lock neobsahuje SHA-256 hase"


# ── B4 — scripts/verify_rust_wheel.py --installed (fail-closed kontrola aktivního core) ────────


def _run_installed() -> tuple[int, str]:
    """Spusť ``verify_rust_wheel.py --installed`` jako subprocess (skutečný CLI entry point)."""
    r = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "verify_rust_wheel.py"), "--installed"],
        capture_output=True, text=True, timeout=120, check=False,  # returncode čtu v asercích
    )
    return r.returncode, r.stdout + r.stderr


def test_installed_mode_passes_with_active_core() -> None:
    """B4 — aktivní core nainstalován → --installed exit 0 (verze odpovídá manifestu)."""
    from stopa.data import rust_core

    if not rust_core.is_available():
        pytest.skip("Rust wheel v prostředí chybí (čisté-Python fallback)")
    code, out = _run_installed()
    assert code == 0, f"--installed selhalo: {out}"


def test_installed_mode_fails_without_core() -> None:
    """B4 — core chybí → --installed fail-closed (exit ≠ 0)."""
    from stopa.data import rust_core

    if rust_core.is_available():
        pytest.skip("core v prostředí přítomen — nepřítomnost nedá reprodukovat")
    code, out = _run_installed()
    assert code != 0, f"očekávám selhání bez core: {out}"
    assert "stopa_core" in out, f"--installed má jmenovat stopa_core: {out}"
