"""P0-3 — plugin sandbox hardening (ROADMAP_2_1.md).

Pokrytí: nové SandboxLimits pole + parse sémantika (TypeError/ValueError),
izolovaný workdir per run (úklid při úspěchu / zachování při chybě / explicitní
workdir se neuklídí), strop velikosti výstupu, detekce CPU limitu (SIGXCPU),
síťová izolace (unshare obal / nedostupnost) a živý sandbox run ukázkového pluginu.

Testy offline — subprocess.run monkeypatchované kromě jednoho live E2E testu.
"""

from __future__ import annotations

import json
import os
import signal as _signal_mod
import subprocess as _subprocess_mod
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from stopa.data import plugin_loader
from stopa.domain.plugins import sandbox_limits

REPO_PLUGINS = Path(__file__).resolve().parent.parent / "plugins"


def _fake_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


# ── Doména: nové SandboxLimits pole ─────────────────────────────


class TestSandboxLimitsFields:
    def test_defaults(self):
        lim = sandbox_limits({})
        assert (lim.timeout_s, lim.max_mem_mb) == (120, 512)
        assert lim.cpu_seconds == 60
        assert lim.max_output_mb == 32
        assert lim.network_isolated is False

    def test_custom_values(self):
        lim = sandbox_limits(
            {"cpu_seconds": None, "max_output_mb": 8, "network_isolated": True}
        )
        assert lim.cpu_seconds is None
        assert lim.max_output_mb == 8
        assert lim.network_isolated is True

    @pytest.mark.parametrize(
        "data",
        [{"cpu_seconds": "x"}, {"max_output_mb": 1.5}, {"network_isolated": "yes"}],
    )
    def test_type_errors(self, data):
        with pytest.raises(TypeError):
            sandbox_limits(data)

    @pytest.mark.parametrize("data", [{"cpu_seconds": -3}, {"max_output_mb": 0}])
    def test_semantic_valueerrors(self, data):
        with pytest.raises(ValueError):
            sandbox_limits(data)


# ── rlimit factory: CPU + NOFILE (subprocess = čistý test proces) ─────────────


@pytest.mark.skipif(os.name != "posix", reason="resource modul je jen pro POSIX")
def test_rlimit_factory_sets_cpu_and_as():
    code = (
        "import resource;"
        "from stopa.data.plugin_loader import _rlimit_factory;"
        "_rlimit_factory(512, cpu_seconds=5)();"
        "assert resource.getrlimit(resource.RLIMIT_AS)[0] == 512*1024*1024;"
        "soft, hard = resource.getrlimit(resource.RLIMIT_CPU);"
        "assert (soft, hard) == (5, 5), (soft, hard);"
        'print("OK")'
    )
    proc = _subprocess_mod.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


# ── Izolovaný workdir per run ────────────────────────────────────


class TestIsolatedWorkdir:
    def _patch_run(self, monkeypatch, fake):
        monkeypatch.setattr(plugin_loader.subprocess, "run", fake)

    def test_success_creates_and_cleans_workdir(self, monkeypatch, tmp_path):
        runs = tmp_path / "runs"
        monkeypatch.setenv("STOPA_PLUGIN_RUNS_DIR", str(runs))
        seen: dict = {}

        def fake_run(cmd, **kw):
            seen["cwd"] = kw.get("cwd")
            return _fake_proc(0, stdout=json.dumps({"ok": True, "result": {"x": 1}}))

        self._patch_run(monkeypatch, fake_run)
        payload = plugin_loader.sandbox_exec(["my-plugin", "--cap", "triage_profile"])
        assert payload == {"ok": True, "result": {"x": 1}}
        cwd = Path(seen["cwd"])
        assert str(cwd).startswith(str(runs))
        assert cwd.name.startswith("my-plugin-")
        assert not cwd.exists(), "úspěšný run se musí uklidit"

    def test_failure_keeps_workdir_for_debug(self, monkeypatch, tmp_path):
        runs = tmp_path / "runs"
        monkeypatch.setenv("STOPA_PLUGIN_RUNS_DIR", str(runs))
        seen: dict = {}

        def fake_run(cmd, **kw):
            seen["cwd"] = kw.get("cwd")
            return _fake_proc(1, stdout="ne-JSON", stderr="boom")

        self._patch_run(monkeypatch, fake_run)
        with pytest.raises(ValueError, match="workdir pro debug"):
            plugin_loader.sandbox_exec(["my-plugin"])
        assert Path(seen["cwd"]).exists(), "selhání musí nechat workdir pro debug"

    def test_explicit_workdir_not_cleaned(self, monkeypatch, tmp_path):
        wd = tmp_path / "explicit"
        wd.mkdir()
        ok = json.dumps({"ok": True, "result": None})

        def fake_run(cmd, **kw):
            assert kw.get("cwd") == str(wd)
            return _fake_proc(0, stdout=ok)

        self._patch_run(monkeypatch, fake_run)
        plugin_loader.sandbox_exec(["p"], workdir=wd)
        assert wd.exists(), "explicitní workdir spravuje host — neuklízet"


# ── Strop velikosti výstupu ───────────────────────────────────────


class TestOutputCap:
    def test_too_large_output_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("STOPA_PLUGIN_RUNS_DIR", str(tmp_path / "runs"))

        def fake_run(cmd, **kw):
            return _fake_proc(0, stdout="x" * (2 * 1024 * 1024))

        monkeypatch.setattr(plugin_loader.subprocess, "run", fake_run)
        with pytest.raises(ValueError, match="příliš velký"):
            plugin_loader.sandbox_exec(["p"], limits=sandbox_limits({"max_output_mb": 1}))


# ── CPU limit (SIGXCPU) ───────────────────────────────────────────


class TestCpuLimit:
    def test_sigxcpu_detected_as_clear_error(self, monkeypatch, tmp_path):
        monkeypatch.setenv("STOPA_PLUGIN_RUNS_DIR", str(tmp_path / "runs"))

        def fake_run(cmd, **kw):
            return _fake_proc(-_signal_mod.SIGXCPU if hasattr(_signal_mod, "SIGXCPU") else -24)

        monkeypatch.setattr(plugin_loader.subprocess, "run", fake_run)
        with pytest.raises(ValueError, match="CPU limit"):
            plugin_loader.sandbox_exec(["p"])


# ── Síťová izolace (unshare --net) ────────────────────────────────


class TestNetworkIsolation:
    def test_unavailable_raises_explicitly(self, monkeypatch):
        monkeypatch.setattr(plugin_loader, "_unshare_net_available", lambda: False)
        with pytest.raises(ValueError, match="síťová izolace nedostupná"):
            plugin_loader.sandbox_exec(
                ["p"], limits=sandbox_limits({"network_isolated": True})
            )

    def test_wraps_cmd_with_unshare(self, monkeypatch):
        monkeypatch.setattr(plugin_loader, "_unshare_net_available", lambda: True)
        seen: dict = {}
        ok = json.dumps({"ok": True, "result": None})

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            return _fake_proc(0, stdout=ok)

        monkeypatch.setattr(plugin_loader.subprocess, "run", fake_run)
        plugin_loader.sandbox_exec(["p"], limits=sandbox_limits({"network_isolated": True}))
        assert seen["cmd"][0] == "unshare" and "--net" in seen["cmd"]

    @pytest.mark.skipif(os.name != "posix", reason="guard jen smysluplný na POSIX")
    def test_probe_false_on_non_linux(self, monkeypatch):
        monkeypatch.setattr(plugin_loader.sys, "platform", "darwin")
        assert plugin_loader._unshare_net_available() is False


# ── Live E2E: ukázkový plugin v hardenovaném sandboxu ──────────────


@pytest.fixture()
def plugins_env(monkeypatch, tmp_path):
    monkeypatch.setenv("STOPA_PLUGINS_DIR", str(REPO_PLUGINS))
    # izolované runy drží mimo home/CI workspace
    monkeypatch.setenv("STOPA_PLUGIN_RUNS_DIR", str(tmp_path / "plugin-runs"))


def test_live_sandbox_run_with_hardening(plugins_env):
    """Živý run — izolovaný workdir + nové limity nesmí změnit chování pluginu."""
    payload = plugin_loader.sandbox_exec(["example-crypto-triage", "--cap", "triage_profile"])
    assert payload.get("ok") is True
    assert "crypto_exfiltration" in json.dumps(payload["result"], ensure_ascii=False)


def test_live_sandbox_run_keeps_host_cwd_clean(plugins_env):
    """Plugin běží v izolovaném workdiru — host cwd (repo plugins/) zůstává nedotčen."""
    before = sorted(p.name for p in REPO_PLUGINS.iterdir())
    payload = plugin_loader.sandbox_exec(["example-crypto-triage", "--cap", "triage_profile"])
    assert payload.get("ok") is True
    after = sorted(p.name for p in REPO_PLUGINS.iterdir())
    assert before == after, "host cwd se musel zachovat nedotčený"


def test_live_sandbox_run_cleans_workdir(plugins_env):
    """Úspěšný live run uklidí svůj izolovaný workdir (žádné rezidy v runs kořeni)."""
    runs_root = Path(os.environ["STOPA_PLUGIN_RUNS_DIR"])
    plugin_loader.sandbox_exec(["example-crypto-triage", "--cap", "triage_profile"])
    leftovers = [p for p in runs_root.iterdir() if p.name.startswith("example-crypto-triage-")]
    assert leftovers == [], f"rezidy po úspěšném runu: {leftovers}"
