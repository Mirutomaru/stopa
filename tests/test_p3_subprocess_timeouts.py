"""P3-B — timeouty procesů/spouštěných parserů: AST guard + chování installeru.

Kontext (audit §10): „jednotlivé artifact parcery nemají globální watchdog".
Analýza uzavřela položku takto:

* **subprocess parsery** (TSK, volatility, LUKS, sandbox, plugin_loader) už mají
  explicitní ``timeout=`` — chyběly jen v installeru (venv/pip/apt), doplněno P3-B;
* **síťová volání** (integrity checksums, onchain API, LM Studio, Timesketch)
  mají timeouty přes ``urlopen(timeout=)`` / ``httpx.Client(timeout=)``;
* **čistě pythonové parserte v paměti** jsou omezené vstupními limity — velikost
  (P1/P2 archive budget) + hloubka (P3-A json_bounded, P1 xml_bounded). Hard
  watchdog přes GIL worker vlákna by byl architektonicky nebezpečnější než
  samotné parsování, proto se nepoužívá.

Tento soubor drží invarianty: žádné ``subprocess.run/Popen/call/check_output``
v ``src/stopa`` bez explicitního timeoutu (AST sken = regrese) + deterministické
chování installeru při Timeoutu.
"""

from __future__ import annotations

import ast
import subprocess as _sp
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "stopa"

#: Metody subprocess, které blokují → vyžadují explicitní timeout= kwarg.
_BLOCKING = {"run", "Popen", "call", "check_output"}


def _iter_python_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


# ---------------------------------------------------------------- AST guard

def test_all_subprocess_calls_have_timeout() -> None:
    """Každá blokovací volání subprocessu v src/stopa má explicitní timeout.

    AST sken (ne grep) — chytí i víceřádková volání a přejmenované proměnné.
    Regrese: nová volající místa, která zapomenou timeout=, spadnou tady.
    """
    missing: list[str] = []
    for f in _iter_python_files():
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if (
                isinstance(fn, ast.Attribute)
                and fn.attr in _BLOCKING
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "subprocess"
            ):
                kw_names = {kw.arg for kw in node.keywords}  # type: ignore[arg-type]
                if "timeout" not in kw_names:
                    missing.append(f"{f.relative_to(SRC.parent)}:{node.lineno}")
    assert not missing, f"subprocess bez timeout=: {missing}"


def test_no_popen_or_os_system_anywhere() -> None:
    """Žádné Popen/os.system/os.popen (jiný režim správy — viz audit)."""
    bad: list[str] = []
    for f in _iter_python_files():
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if (
                isinstance(fn, ast.Attribute)
                and isinstance(fn.value, ast.Name)
                and (
                    (fn.value.id == "os" and fn.attr in ("system", "popen"))
                    or (fn.value.id == "subprocess" and fn.attr == "Popen")
                )
            ):
                bad.append(f"{f.name}:{node.lineno} {fn.attr}")
    assert not bad, f"Popen/os.system/os.popen bez zvláštního posouzení: {bad}"


# ------------------------------------------------------------ installer chování

class TestInstallerTimeouts:
    def test_subprocess_passes_default_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from stopa import installer

        calls: list[dict] = []

        def fake_run(cmd, **kw):
            calls.append({"cmd": cmd, "kw": kw})
            return _sp.CompletedProcess(args=cmd, returncode=0)

        monkeypatch.setattr(installer.subprocess, "run", fake_run)
        rc = installer._subprocess(["true"])
        assert rc == 0
        assert calls[0]["kw"].get("timeout") == 900

    def test_subprocess_explicit_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from stopa import installer

        calls: list[dict] = []

        def fake_run(cmd, **kw):
            calls.append({"cmd": cmd, "kw": kw})
            return _sp.CompletedProcess(args=cmd, returncode=0)

        monkeypatch.setattr(installer.subprocess, "run", fake_run)
        installer._subprocess(["true"], timeout_s=42)
        assert calls[0]["kw"].get("timeout") == 42

    def test_subprocess_timeout_returns_124_no_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from stopa import installer

        def fake_run(cmd, **kw):
            raise _sp.TimeoutExpired(cmd=cmd, timeout=900)

        monkeypatch.setattr(installer.subprocess, "run", fake_run)
        # kontrakt: chyba = warning (tisk), ne výjimka — timeout vrátí 124
        assert installer._subprocess(["apt-get", "install"]) == 124

    def test_subprocess_file_not_found_still_127(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # původní chování zachováno (P3 mění jen timeout, ne semantiku)
        from stopa import installer

        def fake_run(cmd, **kw):
            raise FileNotFoundError(cmd[0])

        monkeypatch.setattr(installer.subprocess, "run", fake_run)
        assert installer._subprocess(["nehodlasec"]) == 127

    def test_setup_venv_timeout_returns_124(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from stopa import installer

        calls: list[dict] = []

        def fake_run(cmd, **kw):
            calls.append({"cmd": cmd, "kw": kw})
            raise _sp.TimeoutExpired(cmd=cmd, timeout=float(kw["timeout"]))

        monkeypatch.setattr(installer.subprocess, "run", fake_run)
        monkeypatch.setattr(installer, "_in_venv", lambda: False)
        rc = installer._setup_venv(tmp_path / "venv")
        assert rc == 124
        # venv creation dostává vlastní limit (300 s), ne pip default
        assert calls[0]["kw"].get("timeout") == 300

    def test_setup_venv_inactive_venv_path_passes_pip_timeout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # aktivní venv → pip instalace přes _subprocess s defaultním limitem 900 s
        from stopa import installer

        calls: list[dict] = []

        def fake_run(cmd, **kw):
            calls.append({"cmd": cmd, "kw": kw})
            return _sp.CompletedProcess(args=cmd, returncode=0)

        monkeypatch.setattr(installer.subprocess, "run", fake_run)
        monkeypatch.setattr(installer, "_in_venv", lambda: True)
        rc = installer._setup_venv(tmp_path / "venv")
        assert rc == 0
        pip_call = next(c for c in calls if "pip" in c["cmd"])
        assert pip_call["kw"].get("timeout") == 900
