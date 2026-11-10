"""R0.2 — testy ``stopa install`` bootstrap instalátoru.

Čisté funkce (detect_os, plan_install) → plně offline, žádné root/síť/subprocess.
run_plan se testuje jen v dry_run režimu (žádné side effecty).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from stopa.installer import InstallPlan, OsInfo, detect_os, plan_install, run_plan

# --- detekce OS ---------------------------------------------------------------


def _write_os_release(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "os-release"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_detect_ubuntu(tmp_path):
    rel = _write_os_release(
        tmp_path, 'NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="24.04"\n'
    )
    info = detect_os(rel)
    assert info.id == "ubuntu"
    assert info.version == "24.04"


def test_detect_fedora(tmp_path):
    rel = _write_os_release(tmp_path, 'ID=fedora\nVERSION_ID="39"\n')
    assert detect_os(rel).id == "fedora"


def test_detect_alpine(tmp_path):
    rel = _write_os_release(tmp_path, 'ID=alpine\nVERSION_ID="3.19.0"\n')
    info = detect_os(rel)
    assert info.id == "alpine"


def test_detect_missing_falls_back_to_platform():
    # Chybějící soubor → fallback podle platform.system() (na CI/loci = linux→unknown id).
    # Klíčové: nevyhodí výjimku a vrací OsInfo.
    info = detect_os(Path("/nonexistent/os-release-xyz"))
    assert isinstance(info, OsInfo)
    assert info.id in {"linux", "ubuntu", "fedora", "alpine", "unknown", "macos", "windows"}


# --- plán ---------------------------------------------------------------------


def test_plan_ubuntu_uses_apt_with_sudo():
    plan = plan_install(OsInfo("ubuntu", "24.04"), euid=1000)
    assert plan.package_manager == "apt-get"
    assert "sleuthkit" in plan.system_packages
    assert "libewf2" in plan.system_packages and "libafflib0" in plan.system_packages
    assert plan.needs_sudo is True  # euid != 0


def test_plan_ubuntu_root_no_sudo():
    plan = plan_install(OsInfo("ubuntu", "24.04"), euid=0)
    assert plan.needs_sudo is False


def test_plan_fedora_uses_dnf():
    plan = plan_install(OsInfo("fedora", "39"), euid=1000)
    assert plan.package_manager == "dnf"
    assert "sleuthkit" in plan.system_packages


def test_plan_alpine_uses_apk_sleuthkit_only():
    plan = plan_install(OsInfo("alpine", "3.19"), euid=0)
    assert plan.package_manager == "apk"
    # Alpine nemá libewf2/libafflib0 → jen sleuthkit, EWF přes STOPA_EWF_LIB.
    assert plan.system_packages == ("sleuthkit",)


def test_plan_skip_system_no_pkgs():
    plan = plan_install(OsInfo("ubuntu", "24.04"), euid=1000, skip_system=True)
    assert plan.package_manager is None
    assert plan.system_packages == ()
    assert plan.needs_sudo is False
    # krok o přeskočení je v plánu
    assert any("PROSKOČENO" in s for s in plan.steps)


def test_plan_unknown_os_pip_only():
    plan = plan_install(OsInfo("unknown", ""), euid=1000)
    assert plan.package_manager is None
    assert plan.system_packages == ()
    # i tak se plánuje venv + pip krok
    assert any("pip install" in s for s in plan.steps)


def test_plan_steps_not_empty():
    plan = plan_install(OsInfo("ubuntu", "24.04"), euid=1000)
    assert len(plan.steps) >= 2
    assert all(isinstance(s, str) and s for s in plan.steps)


# --- run_plan (dry_run jen) ---------------------------------------------------


def test_run_plan_dry_run_no_side_effects():
    plan = InstallPlan(
        os_info=OsInfo("ubuntu", "24.04"),
        package_manager="apt-get",
        system_packages=("sleuthkit",),
        needs_sudo=True,
        venv_dir=Path("/tmp/never"),
        ewf_symlink_dir=Path("/tmp/never-lib"),
        steps=("sudo apt-get install sleuthkit", "python -m venv /tmp/never"),
    )
    assert run_plan(plan, dry_run=True) == 0
    # dry-run nesmí vytvořit žádné adresáře
    assert not Path("/tmp/never").exists()


def test_run_plan_dry_run_json_shape():
    plan = InstallPlan(
        os_info=OsInfo("fedora", "39"),
        package_manager="dnf",
        system_packages=("sleuthkit",),
        needs_sudo=False,
        venv_dir=Path("/tmp/never2"),
        ewf_symlink_dir=Path("/tmp/never2-lib"),
        steps=("dnf install sleuthkit",),
    )
    assert run_plan(plan, dry_run=True) == 0


# --- CLI (main → cmd_install, dry-run + --json = bezpečné) --------------------


def test_cli_install_dry_run_json(capsys):
    import json

    from stopa.cli import main

    rc = main(["install", "--dry-run", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    # JSON větev tiskne jediný JSON objekt na stdout (plain text gateován).
    obj = json.loads(out[out.index("{"):])
    assert obj["ok"] is True
    assert obj["dry_run"] is True
    assert obj["os"] in {"ubuntu", "fedora", "alpine", "unknown", "macos"}
    assert isinstance(obj["system_packages"], list)


def test_cli_install_dry_run_plain(capsys):
    from stopa.cli import main

    rc = main(["install", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    # plain režim: detekce + kroky, bez JSON objektu na začátku.
    assert "Detekováno:" in out
    assert "(dry-run" in out


def test_cli_install_help_has_example():
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "-m", "stopa.cli", "install", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert r.returncode == 0
    assert "Příklad:" in r.stdout


# --- run_plan: venv + pip install (AK R0.2 — offline funkčnost) --------------

def test_run_plan_calls_system_packages_and_setup_venv(tmp_path, monkeypatch):
    """Ne-dry-run provede oba kroky: systémové balíčky i _setup_venv."""
    from stopa import installer as inst

    calls = []
    monkeypatch.setattr(inst, "_run_system_packages", lambda p: calls.append("sys"))
    monkeypatch.setattr(
        inst, "_setup_venv", lambda v: (calls.append(f"venv:{v}"), 0)[1]
    )
    plan = InstallPlan(
        os_info=OsInfo("ubuntu", "24.04"),
        package_manager="apt-get",
        system_packages=("sleuthkit",),
        needs_sudo=True,
        venv_dir=tmp_path / "venv",
        ewf_symlink_dir=tmp_path / "lib",
        steps=("a",),
    )
    assert inst.run_plan(plan) == 0
    assert calls[0] == "sys"
    assert calls[1].startswith("venv:") and str(tmp_path) in calls[1]


def test_setup_venv_active_venv_installs_into_it(monkeypatch, capsys):
    """Aktivní venv (dev režim) → pip install přímo do něj, bez druhého venvu."""
    from stopa import installer as inst

    monkeypatch.setattr(inst, "_in_venv", lambda: True)
    cmds = []
    monkeypatch.setattr(
        inst, "_subprocess", lambda c: (cmds.append(c), 0)[1]
    )
    rc = inst._setup_venv(Path("/tmp/nikdy-nebude"))
    assert rc == 0
    assert len(cmds) == 1
    assert cmds[0][-2:] == ["install", ".[web]"] or cmds[0][-1] == ".[web]"


def test_setup_venv_new_venv_failure_returns_nonzero(tmp_path, monkeypatch):
    """Selhání python -m venv → run_plan vrátí ≠0 (ne tichý 0)."""
    from stopa import installer as inst

    monkeypatch.setattr(inst, "_in_venv", lambda: False)

    class _FakeR:
        returncode = 1

    def _fake_run(*a, **k):
        # python -m venv selže; pip už nespustí.
        assert "venv" in a[0]
        return _FakeR()

    monkeypatch.setattr(inst.subprocess, "run", _fake_run)
    rc = inst._setup_venv(tmp_path / "novy-venv")
    assert rc != 0


def test_setup_venv_new_venv_success_installs_stopa_web(tmp_path, monkeypatch):
    """Úspěšný venv → pip install <repo_root>[web] z vendored zdroje."""
    from stopa import installer as inst

    monkeypatch.setattr(inst, "_in_venv", lambda: False)

    class _FakeR:
        returncode = 0

    cmds = []

    def _fake_run(cmd, *a, **k):
        cmds.append(cmd)
        return _FakeR()

    monkeypatch.setattr(inst.subprocess, "run", _fake_run)
    rc = inst._setup_venv(tmp_path / "venv-ok")
    assert rc == 0
    # krok 1: venv; krok 2: pip install s [web] extra a cestou do repo rootu.
    assert len(cmds) == 2
    assert "venv" in cmds[0][2]
    assert cmds[1][-1].endswith("[web]")

