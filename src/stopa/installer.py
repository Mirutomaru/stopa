"""R0.2 — ``stopa install``: bootstrap installer s detekcí OS.

Cíl: na čistém Ubuntu 22.04 / Fedora 39 / Alpine 3.19 (AK) připraví systémové
závislosti + Python venv tak, aby ``stopa`` fungovalo offline.

Architektura (SOLID — Dependency Inversion):
- :func:`detect_os` a :func:`plan_install` jsou **čisté funkce** bez I/O
  kromě čtení /etc/os-release → plně testovatelné bez rootu/sítě.
- :func:`run_plan` teprve provede subprocessy (apt/dnf/pacman/apk/brew + pip).

Nativní závislosti (map z R0.2):
- ``sleuthkit`` — TSK CLI fallback pro pytsk3 backend (všechny distro repos)
- ``libewf2``/``libafflib0`` — EWF přes ctypes; installer symlinkuje do
  ``~/ewf-install/lib``, což je defaultní search path ``ewf_container._lib_dir()``
  → STOPA najde knihovny bez nutnosti nastavovat STOPA_EWF_LIB.
- libbde se STOPA nepoužívá (ověřeno grepem) → neinstaluje se.

Bezpečnost: žádné shell=True, žádné string interpolace do příkazů; sudo jen
když euid != 0 a systémový balíček je potřeba.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# --- detekce OS ---------------------------------------------------------------


@dataclass(frozen=True)
class OsInfo:
    """Identita distribuce (id + verze). ``id`` = pole ID z /etc/os-release."""

    id: str  # "ubuntu", "fedora", "alpine", "macos", "windows", "unknown"
    version: str


def _read_os_release(path: Path | None = None) -> dict[str, str]:
    """Načte KEY=VALUE páry z /etc/os-release (injected path pro testy)."""
    p = path or Path("/etc/os-release")
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"')
    return out


def detect_os(os_release_path: Path | None = None) -> OsInfo:
    """Detekce OS z /etc/os-release; fallback podle ``platform.system()``.

    Neznamená to, že je instalace na daném OS podporována — jen identifikuje
    prostředí pro :func:`plan_install`.
    """
    rel = _read_os_release(os_release_path)
    if rel:
        return OsInfo(id=rel.get("ID", "unknown").lower(), version=rel.get("VERSION_ID", ""))
    sysname = platform.system().lower()
    if sysname == "darwin":
        return OsInfo(id="macos", version=platform.mac_ver()[0])
    if sysname == "windows":
        return OsInfo(id="windows", version="")
    return OsInfo(id="unknown", version="")


# --- plán ---------------------------------------------------------------------

#: distro ID → (package manager, systémové balíčky)
_DISTRO_PKGS: dict[str, tuple[str, tuple[str, ...]]] = {
    "ubuntu": ("apt-get", ("sleuthkit", "libewf2", "libafflib0")),
    "debian": ("apt-get", ("sleuthkit", "libewf2", "libafflib0")),
    "fedora": ("dnf", ("sleuthkit", "libewf")),
    "rhel": ("dnf", ("sleuthkit",)),
    "centos": ("dnf", ("sleuthkit",)),
    "rocky": ("dnf", ("sleuthkit",)),
    "alma": ("dnf", ("sleuthkit",)),
    "alpine": ("apk", ("sleuthkit",)),
    "arch": ("pacman", ("sleuthkit",)),
    "macos": ("brew", ("sleuthkit", "libewf")),
}

#: apt balíčky, které poskytují libewf/libafflib .so (pro symlink krok)
_EWF_APT_PKGS = ("libewf2", "libafflib0")


@dataclass(frozen=True)
class InstallPlan:
    """Deterministický plán instalace — čisté data, žádné akce."""

    os_info: OsInfo
    package_manager: str | None  # None → pip-only fallback (bez systémových pkg)
    system_packages: tuple[str, ...]
    needs_sudo: bool
    venv_dir: Path
    ewf_symlink_dir: Path  # defaultní search path ewf_container._lib_dir()
    steps: tuple[str, ...]  # lidsky čitelný popis kroků (pro --dry-run / help)


def plan_install(
    os_info: OsInfo | None = None,
    *,
    venv_dir: Path | None = None,
    euid: int | None = None,
    skip_system: bool = False,
) -> InstallPlan:
    """Vyrobí plán instalace pro dané OS. Čistá funkce (bez I/O).

    - ``skip_system=True`` → přeskočí systémové balíčky (jen venv + pip),
      užitečné kdyby uživatel neměl sudo, ale chce aspoň Python část.
    """
    info = os_info or detect_os()
    uid = euid if euid is not None else os.geteuid()
    pm_map = _DISTRO_PKGS.get(info.id)
    venv = venv_dir or Path.home() / ".stopa" / "venv"
    ewf_dir = Path.home() / "ewf-install" / "lib"

    steps: list[str] = []
    if pm_map is None:
        pm, pkgs = None, ()
    elif skip_system:
        pm, pkgs = None, ()
        steps.append(f"PROSKOČENO systémové balíčky ({', '.join(pm_map[1])}) — --skip-system")
    else:
        pm, pkgs = pm_map

    needs_sudo = bool(pkgs and uid != 0)

    if pm is not None and pkgs:
        suffix = (
            " (sleuthkit = TSK fallback; libewf/libafflib = EWF přes ctypes)"
            if info.id in ("ubuntu", "debian")
            else ""
        )
        steps.append(f"{('sudo ' if needs_sudo else '')}{pm} install {' '.join(pkgs)}{suffix}")
        if any(p in _EWF_APT_PKGS for p in pkgs):
            steps.append(f"symlink libewf.so + libafflib.so → {ewf_dir} (defaultní search path STOPA)")

    venv_step = f"python -m venv {venv}" if not _in_venv() else "aktivní venv (bez nového)"
    steps.append(f"{venv_step} → pip install 'stopa[web]' do {venv}")

    return InstallPlan(
        os_info=info,
        package_manager=pm if (not skip_system and pkgs) else None,
        system_packages=pkgs if not skip_system else (),
        needs_sudo=bool(pkgs and uid != 0 and not skip_system),
        venv_dir=venv,
        ewf_symlink_dir=ewf_dir,
        steps=tuple(steps),
    )


def _in_venv() -> bool:
    return sys.prefix != sys.base_prefix or os.environ.get("VIRTUAL_ENV") is not None


# --- provedení -----------------------------------------------------------------


def run_plan(plan: InstallPlan, *, dry_run: bool = False) -> int:
    """Provede plán; ``dry_run`` jen vytiskne kroky. Vrací exit code.

    Pořadí (AK R0.2 — na čistém Ubuntu → ``stopa`` funguje offline):
      1) systémové balíčky + symlink EWF knihoven (best-effort),
      2) venv + ``pip install 'stopa[web]'`` do ``plan.venv_dir``.

    Vrací 0 jen když se podařila i Python část; selhání systémových balíčků
    je warning (STOPA běží i bez TSK/EWF, s omezeným pokrytím).
    """
    for step in plan.steps:
        print(f"[install] {step}")
        if dry_run:
            continue

    # 1) Systémové balíčky (best-effort; warning při selhání, ne exit).
    if not dry_run and plan.package_manager and plan.system_packages:
        _run_system_packages(plan)

    # 2) venv + pip install stopa[web] — kritická část pro offline funkčnost.
    if dry_run:
        return 0
    return _setup_venv(plan.venv_dir)


def _setup_venv(venv_dir: Path) -> int:
    """Vytvoří venv (pokud neexistuje) a nainstaluje ``stopa[web]``.

    Vrací 0 při úspěchu, jinak ≠0. Pokud je aktivní venv, instaluje přímo do
    něj — installer se běžně spouští z dev venvu, kde nemá smysl druhý.
    """
    if _in_venv():
        print(f"[install] aktivní venv → pip install 'stopa[web]' do {sys.prefix}")
        rc = _subprocess([sys.executable, "-m", "pip", "install", "--quiet", ".[web]"])
        return 0 if rc == 0 else 1

    bin_name = "Scripts" if os.name == "nt" else "bin"
    venv_dir.mkdir(parents=True, exist_ok=True)
    print(f"[install] python -m venv {venv_dir}")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)], check=False, timeout=300
        )
    except subprocess.TimeoutExpired:
        print("[install] ERROR: vytvoření venvu přerušeno (timeout 300 s)", file=sys.stderr)
        return 124
    if r.returncode != 0:
        print("[install] ERROR: vytvoření venvu selhalo", file=sys.stderr)
        return 1

    pip_bin = venv_dir / bin_name / ("pip.exe" if os.name == "nt" else "pip")
    # instalace z aktuálního zdroje (repo root = rodič src/stopa) — .[web] extra.
    repo_root = Path(__file__).resolve().parent.parent.parent
    rc = _subprocess([str(pip_bin), "install", "--quiet", f"{repo_root}[web]"])
    if rc != 0:
        print("[install] ERROR: pip install stopa[web] selhalo", file=sys.stderr)
        return 1

    console = venv_dir / bin_name / ("stopa.exe" if os.name == "nt" else "stopa")
    print(f"[install] hotovo — spustit: {console}")
    return 0


def _run_system_packages(plan: InstallPlan) -> None:
    """apt/dnf/pacman/apk install + symlink EWF knihoven (best-effort)."""
    pm = plan.package_manager or ""
    if pm == "apk":
        cmd = ["apk", "add"]
    elif pm == "pacman":
        cmd = ["pacman", "-S", "--noconfirm"]
    else:  # apt-get / dnf
        cmd = [pm, "install", "-y"]
    if plan.needs_sudo:
        cmd.insert(0, "sudo")
    cmd.extend(plan.system_packages)
    _subprocess(cmd)

    # Symlink EWF knihoven do defaultního search pathu (jen kde balíčky existují).
    if any(p in _EWF_APT_PKGS for p in plan.system_packages):
        _symlink_ewf_libs(plan.ewf_symlink_dir)


def _subprocess(cmd: list[str], *, timeout_s: int = 900) -> int:
    """Spustí příkaz (bez shell); vrací return code. Chyba = warning, ne výjimka.

    ``timeout_s``: maximální doba běhu — bez limitu by mrtvá síť/apt repo
    viselo installer navždy (P3-B). Timeout → 124 (standardní exit pro timeout).
    """
    try:
        r = subprocess.run(cmd, check=False, timeout=timeout_s)
        if r.returncode != 0:
            print(f"[install] WARNING: {' '.join(cmd)} vrátilo {r.returncode} (pokračuji)", file=sys.stderr)
        return r.returncode
    except subprocess.TimeoutExpired:
        print(
            f"[install] WARNING: {' '.join(cmd[:3])}… přerušeno po {timeout_s}s",
            file=sys.stderr,
        )
        return 124
    except FileNotFoundError as e:
        print(f"[install] WARNING: příkaz nenalezen ({e}) — přeskočeno", file=sys.stderr)
        return 127


def _symlink_ewf_libs(target_dir: Path) -> None:
    """Symlinkuje libewf.so/libafflib.so z systémových lokací do target_dir."""

    candidates = (
        "/usr/lib/x86_64-linux-gnu",
        "/usr/lib/aarch64-linux-gnu",
        "/usr/lib64",
        "/usr/lib",
    )
    wanted = {
        "libewf.so": ("libewf.so", "libewf.so.2.0.0"),
        "libafflib.so": ("libafflib.so", "libafflib.so.0.0.0"),
    }
    target_dir.mkdir(parents=True, exist_ok=True)
    for link_name, sources in wanted.items():
        dest = target_dir / link_name
        if dest.exists() or dest.is_symlink():
            continue
        for cdir in candidates:
            for sname in sources:
                src = Path(cdir) / sname
                if src.exists():
                    try:
                        dest.symlink_to(src)
                        print(f"[install] symlink {link_name} → {src}")
                    except OSError as e:
                        print(f"[install] WARNING: symlink selhal ({e})", file=sys.stderr)
                    break
            else:
                continue
            break
