"""P4-2 — Plugin sandbox hardening (ROADMAP_2_1.md / docs/P4_DESIGNS.md).

Pokrytí: nové SandboxLimits pole + parser sémantika (TypeError/ValueError),
RLIMIT_NPROC/FSIZE (factory v subprocessu + živé vynucení FSIZE → EFBIG),
strict seccomp-bpf builder (BPF layout, fail-closed na neznámé architektuře /
chybějícím CORE syscallu / chybějící tabulce, aarch64 simulace bez os.syscalls),
userns probe, CLI --sandbox povrch (JSON profil) a živý strict E2E ukázkového pluginu.

Testy offline — subprocess.run monkeypatchované kromě explicitně označených live testů.
"""

from __future__ import annotations

import json
import os
import subprocess as _subprocess_mod
import sys
from pathlib import Path

import pytest

from stopa.data import plugin_loader
from stopa.domain.plugins import sandbox_limits

REPO_PLUGINS = Path(__file__).resolve().parent.parent / "plugins"


def _strict_live_available() -> bool:
    """Probe: jde seccomp-bpf filter nainstalovat v dětském procesu (NNP + JIT)."""
    if os.name != "posix" or not sys.platform.startswith("linux"):
        return False
    try:
        insns, _ = plugin_loader._build_seccomp_strict_filter()
        fn = plugin_loader._seccomp_strict_preexec(insns)
        proc = _subprocess_mod.run(
            [sys.executable, "-c", "pass"], capture_output=True, timeout=60, preexec_fn=fn, check=False
        )
    except Exception:  # noqa: BLE001 — probe musí být tichá (fail → skip)
        return False
    return proc.returncode == 0


#: live strict testy se spouští jen tam, kde seccomp-bpf reálně funguje
STRICT_LIVE = _strict_live_available()


# ── Doména: nové SandboxLimits pole (W1) ────────────────────────


class TestSandboxLimitsP42Fields:
    def test_new_defaults(self):
        lim = sandbox_limits({})
        assert lim.max_procs == 256
        assert lim.max_file_mb == 1024
        assert lim.profile == "default"

    def test_custom_values(self):
        lim = sandbox_limits({"max_procs": 32, "max_file_mb": 8, "profile": "strict"})
        assert (lim.max_procs, lim.max_file_mb) == (32, 8)
        assert lim.profile == "strict"

    def test_null_means_no_limit(self):
        lim = sandbox_limits({"max_procs": None, "max_file_mb": None})
        assert lim.max_procs is None and lim.max_file_mb is None

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("max_procs", True),  # bool je instance int — explicitní TypeError
            ("max_procs", False),
            ("max_procs", "32"),
            ("max_procs", 1.5),
            ("max_file_mb", True),
            ("max_file_mb", "8"),
            ("max_file_mb", -0.5),
        ],
    )
    def test_type_errors(self, key: str, value: object):
        with pytest.raises(TypeError):
            sandbox_limits({key: value})

    @pytest.mark.parametrize("data", [{"max_procs": 0}, {"max_procs": -3}])
    def test_max_procs_semantic_valueerror(self, data: dict):
        with pytest.raises(ValueError, match="kladné číslo"):
            sandbox_limits(data)

    @pytest.mark.parametrize("data", [{"max_file_mb": 0}, {"max_file_mb": -8}])
    def test_max_file_mb_semantic_valueerror(self, data: dict):
        with pytest.raises(ValueError, match="kladné číslo"):
            sandbox_limits(data)

    def test_profile_type_error(self):
        with pytest.raises(TypeError, match="string"):
            sandbox_limits({"profile": 5})

    @pytest.mark.parametrize("bad", ["turbo", "Strict", "", "defaultt"])
    def test_profile_value_error(self, bad: str):
        with pytest.raises(ValueError, match="'default' nebo 'strict'"):
            sandbox_limits({"profile": bad})


# ── rlimit NPROC/FSIZE (W2) ─────────────────────────────────────


@pytest.mark.skipif(os.name != "posix", reason="resource modul je jen pro POSIX")
def test_rlimit_factory_sets_nproc_and_fsize(tmp_path):
    """Factory nastaví RLIMIT_NPROC i RLIMIT_FSIZE (tichá degradace jen nížší limit)."""
    code = (
        "import resource;"
        "from stopa.data.plugin_loader import _rlimit_factory;"
        "inf = -1;"
        "b_soft, b_hard = resource.getrlimit(resource.RLIMIT_NPROC);"
        # požadavek nikdy nepřekročí aktuální hard limit (bez CAP_SYS_RESOURCE)
        "req = 512 if (b_hard == inf or b_hard >= 512) else max(4, b_soft // 2);"
        "_rlimit_factory(512, max_procs=req, max_file_mb=1)();"
        "nproc = resource.getrlimit(resource.RLIMIT_NPROC);"
        "assert nproc == (req, req), (nproc, req);"
        "fsize = resource.getrlimit(resource.RLIMIT_FSIZE);"
        "assert fsize == (1048576, 1048576), fsize;"
        'print("OK")'
    )
    proc = _subprocess_mod.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


@pytest.mark.skipif(os.name != "posix", reason="resource modul je jen pro POSIX")
def test_fsize_enforced_efbig(tmp_path):
    """Živé vynucení: zápis 3 MB pod RLIMIT_FSIZE=1 MB → EFBIG (errno 28)."""
    target = tmp_path / "fsize_probe.bin"
    code = (
        "import sys\n"
        "from stopa.data.plugin_loader import _rlimit_factory\n"
        "_rlimit_factory(512, max_file_mb=1)()\n"
        "try:\n"
        f"    with open({str(target)!r}, 'wb') as f: f.write(b'x' * (3*1024*1024))\n"
        "except OSError as e:\n"
        "    print(f'EFBIG:{e.errno}')\n"
        "    sys.exit(0)\n"
        'print("NO-LIMIT")  # dosaženo jen tehdy, když limit nefungoval\n'
        "sys.exit(3)\n"
    )
    proc = _subprocess_mod.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )
    assert proc.returncode == 0, f"exit={proc.returncode} stderr={proc.stderr}"
    # Linux: EFBIG=27 (jen BSD/macOS sdílejí s ENOSPC hodnotu 28); bez limitu by zápis prošel (NO-LIMIT)
    assert "EFBIG:27" in proc.stdout, proc.stdout


# ── Strict seccomp-bpf builder (W2) ─────────────────────────────


def _resolve_table(arch: str) -> dict[str, int] | None:
    """Stejná volba tabulky jako v `_build_seccomp_strict_filter`."""
    table = getattr(os, "syscalls", None)
    if not isinstance(table, dict):  # některé CPython buildy nemají os.syscalls
        table = plugin_loader._STRICT_FALLBACK_SYSCALLS.get(arch)
    return table


def _host_arch() -> str:
    import platform

    return platform.machine()


class TestStrictBuilder:
    def test_builder_layout_and_allowlist(self):
        """Layout BPF programu + allowlist = přesná unie CORE/OPTIONAL pro host arch."""
        arch = _host_arch()
        if arch not in ("x86_64", "aarch64"):
            pytest.skip(f"strict profil podporuje jen x86_64/aarch64 (host {arch})")
        insns, audit_arch = plugin_loader._build_seccomp_strict_filter()
        assert audit_arch == plugin_loader._AUDIT_ARCHS[arch]

        # [0]=load arch word, [1]=arch EQ (jt=0 → dál), [2]=load syscall nr
        assert insns[0] == (plugin_loader._BPF_LD_ABS_W, 0, 0, 4)
        assert insns[1][0] == plugin_loader._BPF_JMP_EQ_K and insns[1][3] == audit_arch
        assert insns[2] == (plugin_loader._BPF_LD_ABS_W, 0, 0, 0)

        # allow chain: jen EQ s jt→RET ALLOW a jf=0 (fall-through na další EQ)
        chain = insns[3:-2]
        assert len(chain) > 10, "allowlist musí být ne-triviální"
        for i in chain:
            assert i[0] == plugin_loader._BPF_JMP_EQ_K and i[1] > 0 and i[2] == 0, i

        # závěr: default RET ERRNO|EPERM (uapi SECCOMP_RET_ERRNO=0x50000), pak ALLOW
        assert insns[-2] == (plugin_loader._BPF_RET_K, 0, 0, 0x00050001)
        assert insns[-1] == (plugin_loader._BPF_RET_K, 0, 0, 0x7FFF0000)

        table = _resolve_table(arch)
        assert table is not None  # host arch ∈ {x86_64, aarch64} → fallback tabulka vždy existuje
        core = (
            plugin_loader._STRICT_AARCH64_CORE
            if arch == "aarch64"
            else plugin_loader._STRICT_CORE_SYSCALLS
        )
        expected = {
            table[n]
            for n in list(core) + [n for n in plugin_loader._STRICT_OPTIONAL_SYSCALLS if n in table]
        }
        got = {i[3] for i in chain}
        assert got == expected, (
            f"allowlist se liší: chybí={sorted(expected - got)} navíc={sorted(got - expected)}"
        )

    def test_builder_fail_closed_unknown_arch(self, monkeypatch):
        """Nepodporovaná architektura → ValueError, ne tichý allow-all."""
        monkeypatch.setattr("platform.machine", lambda: "riscv64")
        with pytest.raises(ValueError, match="podporuje jen"):
            plugin_loader._build_seccomp_strict_filter()

    def test_builder_fail_closed_missing_core_syscall(self, monkeypatch):
        """Chybí-li CORE syscall v tabulce → fail-closed ValueError."""
        arch = _host_arch()
        if arch not in ("x86_64", "aarch64"):
            pytest.skip(f"strict profil podporuje jen x86_64/aarch64 (host {arch})")
        monkeypatch.setattr(plugin_loader.os, "syscalls", None, raising=False)  # nutí fallback tabulku
        core = (
            plugin_loader._STRICT_AARCH64_CORE
            if arch == "aarch64"
            else plugin_loader._STRICT_CORE_SYSCALLS
        )
        monkeypatch.delitem(plugin_loader._STRICT_FALLBACK_SYSCALLS[arch], core[0])
        with pytest.raises(ValueError, match="chybějící CORE"):
            plugin_loader._build_seccomp_strict_filter()

    def test_builder_fail_closed_no_table(self, monkeypatch):
        """Ni os.syscalls ani fallback tabulka → ValueError."""
        arch = _host_arch()
        if arch not in ("x86_64", "aarch64"):
            pytest.skip(f"strict profil podporuje jen x86_64/aarch64 (host {arch})")
        monkeypatch.setattr(plugin_loader.os, "syscalls", None, raising=False)
        monkeypatch.setattr(plugin_loader, "_STRICT_FALLBACK_SYSCALLS", {})
        with pytest.raises(ValueError, match="žádná tabulka syscallů"):
            plugin_loader._build_seccomp_strict_filter()

    def test_aarch64_simulation_without_os_syscalls(self, monkeypatch):
        """Deterministická aarch64 simulace přes fallback tabulku (bez os.syscalls)."""
        monkeypatch.setattr("platform.machine", lambda: "aarch64")
        monkeypatch.setattr(plugin_loader.os, "syscalls", None, raising=False)  # nutí fallback tabulku
        insns, audit_arch = plugin_loader._build_seccomp_strict_filter()
        assert audit_arch == 0xC00000B7

        chain = insns[3:-2]
        got = {i[3] for i in chain}
        tbl = plugin_loader._STRICT_FALLBACK_SYSCALLS["aarch64"]
        core = plugin_loader._STRICT_AARCH64_CORE
        expected = {
            tbl[n]
            for n in list(core) + [n for n in plugin_loader._STRICT_OPTIONAL_SYSCALLS if n in tbl]
        }
        assert got == expected

        # ARM64 ABI: bez samostatných stat/lstat/pipe/access/mkdir (glibc alternativy);
        # pipe2 a newfstatat/faccessat musí být v allowlistu.
        for absent in ("stat", "lstat", "pipe", "access", "mkdir"):
            assert absent not in core, f"{absent} nemůže patřit do AARCH64_CORE"
        assert "pipe2" in core and tbl["pipe2"] in got
        assert tbl["newfstatat"] in got and tbl["faccessat"] in got


# ── User namespace probe (W2) ───────────────────────────────────


def test_userns_probe_false_on_non_linux(monkeypatch):
    monkeypatch.setattr(plugin_loader.sys, "platform", "darwin")
    assert plugin_loader._unshare_userns_available() is False


def test_userns_probe_returns_bool():
    """Na Linuxu probe vrátí bool bez výjimky (EPERM → graceful degradace)."""
    if not sys.platform.startswith("linux"):
        pytest.skip("probe je smysluplná jen na Linuxu")
    assert isinstance(plugin_loader._unshare_userns_available(), bool)


# ── CLI --sandbox povrch + živý strict E2E (W3) ─────────────────


@pytest.fixture()
def cli_env(monkeypatch, tmp_path):
    monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
    monkeypatch.setenv("STOPA_PLUGINS_DIR", str(REPO_PLUGINS))
    monkeypatch.setenv("STOPA_PLUGIN_RUNS_DIR", str(tmp_path / "plugin-runs"))
    return tmp_path


def test_cli_plugin_run_default_profile_in_json(cli_env, capsys):
    """Neověřený plugin → sandbox + JSON payload nese aktivní profil (default)."""
    from stopa.cli import main

    rc = main(["plugin", "run", "example-crypto-triage", "--cap", "triage_profile", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True and data["sandboxed"] is True
    assert data["profile"] == "default"


@pytest.mark.skipif(not STRICT_LIVE, reason="seccomp-bpf není v tomto prostředí dostupné")
def test_cli_plugin_run_strict_profile_json(cli_env, capsys):
    """CLI --sandbox strict → živý run přes seccomp-bpf + profile='strict' v JSONu."""
    from stopa.cli import main

    rc = main(
        [
            "plugin", "run", "example-crypto-triage", "--cap", "triage_profile",
            "--sandbox", "strict", "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True and data["sandboxed"] is True
    assert data["profile"] == "strict"
    assert "crypto_exfiltration" in json.dumps(data["result"], ensure_ascii=False)


def test_cli_sandbox_flag_rejects_unknown_value(cli_env):
    """--sandbox s neznámou hodnotou → argparse choices (SystemExit 2)."""
    from stopa.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "plugin", "run", "example-crypto-triage", "--cap", "triage_profile",
                "--sandbox", "turbo",
            ]
        )
    assert exc_info.value.code == 2


@pytest.fixture()
def plugins_env(monkeypatch, tmp_path):
    monkeypatch.setenv("STOPA_PLUGINS_DIR", str(REPO_PLUGINS))
    monkeypatch.setenv("STOPA_PLUGIN_RUNS_DIR", str(tmp_path / "plugin-runs"))


@pytest.mark.skipif(not STRICT_LIVE, reason="seccomp-bpf není v tomto prostředí dostupné")
def test_live_strict_sandbox_run(plugins_env):
    """Živý strict run ukázkového pluginu — seccomp allowlist neporuší chování."""
    payload = plugin_loader.sandbox_exec(
        ["example-crypto-triage", "--cap", "triage_profile"],
        limits=sandbox_limits({"profile": "strict"}),
    )
    assert payload.get("ok") is True
    assert "crypto_exfiltration" in json.dumps(payload["result"], ensure_ascii=False)


@pytest.mark.skipif(not STRICT_LIVE, reason="seccomp-bpf není v tomto prostředí dostupné")
def test_live_strict_run_cleans_workdir(plugins_env):
    """Úspěšný strict run uklidí svůj izolovaný workdir (žádné rezidy)."""
    runs_root = Path(os.environ["STOPA_PLUGIN_RUNS_DIR"])
    plugin_loader.sandbox_exec(
        ["example-crypto-triage", "--cap", "triage_profile"],
        limits=sandbox_limits({"profile": "strict"}),
    )
    leftovers = [p for p in runs_root.iterdir() if p.name.startswith("example-crypto-triage-")]
    assert leftovers == [], f"rezidy po úspěšném strict runu: {leftovers}"
