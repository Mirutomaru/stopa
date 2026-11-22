"""F6.4 — Plugin loader (data vrstva: I/O + import; doména = ``domain.plugins``).

Zdroje adresářů pluginů (řazení, první výhra při kolizi jména):
1. settings klíč ``plugins_dirs`` (seznam absolutních cest)
2. environment ``STOPA_PLUGINS_DIR`` (oddělovač ``os.pathsep``)
3. defaultní ``~/.stopa/plugins/``

Import plugin modulů běží přes ``importlib.util.spec_from_file_location``
pod unikátním aliasem ``stopa_plugin_<name>_<module>`` — bez zásahů do
sys.path (odolné proti kolizím jmén mezi pluginy). Moduly pluginu musí být
samostatné (bez relativních importů uvnitř pluginu), viz PLUGINS_API.md.

Sandbox neověřených pluginů: subprocess ``stopa.cli plugin-run`` s limity
(RLIMIT_AS + timeout); výsledek jako JSON. Ověření = settings klíč
``plugins_verified`` (allowlist jmén).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from stopa.domain.plugins import (
    API_VERSION_DEFAULT,
    ExtractorSpec,
    PluginManifest,
    SandboxLimits,
    TriageProfileSpec,
    parse_manifest,
    sandbox_limits,
    validate_manifest,
)
from stopa.domain.plugins import (
    AiToolSpec as _AiToolSpec,
)

MANIFEST_NAME = "plugin.json"


@dataclass(frozen=True)
class LoadedPlugin:
    """Zobrazený plugin: manifest + poloha + stav ověření + chyby kapacit."""

    name: str
    version: str
    path: Path
    verified: bool
    description: str = ""
    author: str = ""
    min_stopa_version: str = "2.0.0"
    api_version: str = API_VERSION_DEFAULT  # P4-3: verze plugin API z manifestu
    capabilities: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedExtractor:
    """Extractory pluginu po importu (ověřená cesta — in-process)."""

    spec: ExtractorSpec
    detect_fn: Callable[[Path], bool] | None
    extract_fn: Callable[[Path], list[Any]]


def resolve_plugin_dirs(settings: dict[str, Any] | None = None) -> list[Path]:
    """Sekvenční zdroj adresářů pluginů (viz modul docstring)."""
    dirs: list[Path] = []
    if settings and isinstance(settings.get("plugins_dirs"), list):
        for raw in settings["plugins_dirs"]:
            if isinstance(raw, str) and raw.strip():
                dirs.append(Path(raw).expanduser())
    env = os.environ.get("STOPA_PLUGINS_DIR", "")
    for chunk in filter(None, env.split(os.pathsep)):
        p = Path(chunk).expanduser()
        if p not in dirs:
            dirs.append(p)
    default_dir = Path.home() / ".stopa" / "plugins"
    if default_dir not in dirs:
        dirs.append(default_dir)
    return dirs


def load_verified_names(settings: dict[str, Any] | None = None) -> frozenset[str]:
    """Allowlist ověřených pluginů (settings klíč ``plugins_verified``)."""
    raw = (settings or {}).get("plugins_verified", [])
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(x for x in raw if isinstance(x, str))


def _load_manifest_file(plugin_dir: Path) -> PluginManifest:
    """Načte plugin.json; poškozený JSON nebo chybné schéma → ValueError/TypeError."""
    mf = plugin_dir / MANIFEST_NAME
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"plugin.json je poškozený ({type(exc).__name__})") from exc
    return parse_manifest(data)


def _issue_from(exc: Exception) -> str:
    """Jednorádkové znění chyby pro manifest issues."""
    msg = str(exc).replace("\n", " ")
    return f"{type(exc).__name__}: {msg}"[:200]


def discover_plugins(
    dirs: Iterable[Path] | None = None,
    settings: dict[str, Any] | None = None,
    stopa_version: str = "2.0.0",
) -> dict[str, LoadedPlugin]:
    """Prohledá adresáře a vrátí jméno → plugin (první výhra dle řazení dirů).

    Manifest-only fáze — kód se importuje až při rozřešení kapacit.
    Plugin bez validního manifestu = issues (ne selhání celého skenu).
    """
    search_dirs = list(dirs) if dirs is not None else resolve_plugin_dirs(settings)
    verified = load_verified_names(settings)
    out: dict[str, LoadedPlugin] = {}
    for d in search_dirs:
        if not d.is_dir():
            continue
        for sub in sorted(d.iterdir()):
            if not sub.is_dir() or not (sub / MANIFEST_NAME).is_file():
                continue
            try:
                manifest = _load_manifest_file(sub)
            except (TypeError, ValueError) as exc:  # poškozený manifest → issues, ne crash skenu
                if sub.name not in out:
                    out[sub.name] = LoadedPlugin(
                        name=sub.name,
                        version="0.0.0",
                        path=sub,
                        verified=False,
                        issues=(_issue_from(exc),),
                    )
                continue
            if manifest.name in out:  # první výhra — kolize ignoruje
                continue
            issues = tuple(validate_manifest(manifest, stopa_version))
            out[manifest.name] = LoadedPlugin(
                name=manifest.name,
                version=manifest.version,
                path=sub,
                verified=manifest.name in verified,
                description=manifest.description,
                author=manifest.author,
                min_stopa_version=manifest.min_stopa_version,
                api_version=manifest.api_version,
                capabilities=tuple(manifest.capabilities),
                issues=issues,
            )
    return out


def _plugin_module(plugin_dir: Path, plugin_name: str, module: str):
    """Importuje modul pluginu pod unikátním aliasem (bez sys.path zásahů)."""
    safe = "".join(c if c.isalnum() else "_" for c in f"{plugin_name}.{module}")
    file_path = plugin_dir / f"{module}.py"
    spec = importlib.util.spec_from_file_location(f"stopa_plugin_{safe}", file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"nelze načíst modul {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # registrace pro dataclass/pickle konzistenci
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return mod


def resolve_extractors(
    plugin_dir: Path, plugin_name: str, specs: tuple[ExtractorSpec, ...]
) -> list[ResolvedExtractor]:
    """In-process rozřešení extractor kapacit (ověřená cesta)."""
    out: list[ResolvedExtractor] = []
    for spec in specs:
        mod = _plugin_module(plugin_dir, plugin_name, spec.module)
        detect_fn: Callable[[Path], bool] | None = None
        if spec.detect_fn:
            fn: object = getattr(mod, spec.detect_fn, None)
            if not callable(fn):
                raise TypeError(f"{plugin_name}: {spec.detect_fn} není volatelná")
            detect_fn = cast("Callable[[Path], bool]", fn)
        extract_obj: object = getattr(mod, spec.extract_fn, None)
        if not callable(extract_obj):
            raise TypeError(f"{plugin_name}: {spec.extract_fn} není volatelná")
        out.append(
            ResolvedExtractor(
                spec=spec,
                detect_fn=detect_fn,
                extract_fn=cast("Callable[[Path], list[Any]]", extract_obj),
            )
        )
    return out


def resolve_triage_profiles(
    plugin_dir: Path, plugin_name: str, specs: tuple[TriageProfileSpec, ...]
) -> tuple[Any, ...]:
    """In-process rozřešení triage profilů (ověřená cesta)."""
    profiles = []
    for spec in specs:
        mod = _plugin_module(plugin_dir, plugin_name, spec.module)
        factory = getattr(mod, spec.factory, None)
        if not callable(factory):
            raise TypeError(f"{plugin_name}: {spec.factory} není volatelná")
        profiles.append(factory())
    return tuple(profiles)


def resolve_ai_tools(
    plugin_dir: Path, plugin_name: str, specs: tuple[_AiToolSpec, ...]
) -> tuple[Any, ...]:
    """In-process rozřešení AI toolů (ověřená cesta)."""
    tools: list[Any] = []
    for spec in specs:
        mod = _plugin_module(plugin_dir, plugin_name, spec.module)
        factory = getattr(mod, spec.factory, None)
        if not callable(factory):
            raise TypeError(f"{plugin_name}: {spec.factory} není volatelná")
        result = factory()
        if not isinstance(result, (list, tuple)):
            raise TypeError(
                f"{plugin_name}: {spec.factory} musí vracet list[ToolSpec], ne {type(result).__name__}"
            )
        tools.extend(list(result))
    return tuple(tools)


def _rlimit_factory(
    max_mem_mb: int,
    cpu_seconds: int | None = None,
    max_fds: int = 1024,
    max_procs: int | None = None,
    max_file_mb: int | None = None,
) -> Callable[[], None]:
    """preexec_fn: stropy subprocessu (Linux RLIMIT_AS + P0-3: CPU, NOFILE + P4-2).

    RLIMIT_NOFILE chrání proti file-descriptor exhaust; na systémech bez práva
    zvýšit limit se ticho ignoruje (limit může být i nižší než požadovaný).
    P4-2: ``RLIMIT_NPROC`` (fork bomb; pozor — Linux počítá per UID napříč systémem)
    a ``RLIMIT_FSIZE`` (obrovský soubor); tichá degradace jako NOFILE.

    Release 2.4 CI fix: i ``RLIMIT_AS``/``RLIMIT_CPU`` degraduji ticho — hard cap
    hostu může být nižší než požadovaný strop (např. macOS CI runner) a nechráněné
    setrlimit hází ValueError v preexec_fn → celý dětský proces padne dřív, než
    sandbox vůbec běží.
    """

    def factory() -> None:  # pragma: no cover - běží v dětském procesu
        if os.name != "posix":  # Windows nemá resource modul
            return
        import resource

        limit = max_mem_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        except (ValueError, OSError):
            pass
        if cpu_seconds is not None and cpu_seconds > 0:
            try:
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            except (ValueError, OSError):
                pass
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (max_fds, max_fds))
        except (ValueError, OSError):
            pass
        if max_procs is not None and max_procs > 0:
            try:
                resource.setrlimit(resource.RLIMIT_NPROC, (max_procs, max_procs))
            except (ValueError, OSError):
                pass
        if max_file_mb is not None and max_file_mb > 0:
            fsize = max_file_mb * 1024 * 1024
            try:
                resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
            except (ValueError, OSError):
                pass

    return factory


def _run_dir_root() -> Path:
    """Kořen izolovaných plugin runů (env STOPA_PLUGIN_RUNS_DIR nebo ~/.stopa/plugin-runs)."""
    env = os.environ.get("STOPA_PLUGIN_RUNS_DIR", "")
    if env.strip():
        return Path(env).expanduser()
    return Path.home() / ".stopa" / "plugin-runs"


def _isolated_workdir(plugin_name: str) -> Path:
    """P0-3: jednorázový workdir per run — plugin nedědí host cwd (defect v 2.0 GA)."""
    stamp = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    wd = _run_dir_root() / f"{plugin_name}-{stamp}"
    wd.mkdir(parents=True, exist_ok=True)
    return wd


def _unshare_net_available() -> bool:
    """P0-3: probe zda ``unshare --net true`` funguje (Linux + práva/user ns)."""
    if os.name != "posix" or not sys.platform.startswith("linux"):
        return False
    try:
        proc = subprocess.run(
            ["unshare", "--net", "true"], capture_output=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _unshare_userns_available() -> bool:
    """P4-2: probe přesné kombinace, kterou ``sandbox_exec`` skutečně použije.

    Pozor: stačí `unshare --user true` (vznikne user ns), ale `--map-root-user`
    navíc píše do /proc/self/uid_map — při nepřivilegovaném usernsu musí být
    mapovány VŠECHNY GIDy procesu (kernel rule), jinak EPERM. Proto probe testuje
    kompletní příkaz; selže-li → strict degraduje na seccomp-only (graceful).
    """
    if os.name != "posix" or not sys.platform.startswith("linux"):
        return False
    try:
        proc = subprocess.run(
            ["unshare", "--user", "--map-root-user", "--mount", "true"],
            capture_output=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


# ---------------------------------------------------------------------------
# P4-2 — strict profil: seccomp-bpf allowlist přes ctypes (bez nové závislosti)
# ---------------------------------------------------------------------------

#: AUDIT_ARCH_* konstanty — stabilní kernel ABI per architektura.
_AUDIT_ARCHS = {"x86_64": 0xC000003E, "aarch64": 0xC00000B7}

#: SYS_seccomp / SYS_prctl čísla (stabilní kernel ABI) — glibc ≥2.41 už
#: `seccomp()` neexportuje jako dynamický symbol, proto raw syscall přes libc.syscall().
_SYS_SECCOMP_NR = {"x86_64": 317, "aarch64": 277}
_SYS_PRCTL_NR = {"x86_64": 157, "aarch64": 167}

# BPF instrukce — CLASSIC seccomp-bpf opcodey (uapi linux/bpf.h, ne eBPF!):
_BPF_LD_ABS_W = 0x20   # BPF_LD|BPF_W|BPF_ABS — load absolute word (k = offset v seccomp_data)
_BPF_JMP_EQ_K = 0x15   # BPF_JMP|BPF_JEQ|BPF_K — jump if == k
_BPF_RET_K = 0x06      # BPF_RET|BPF_K — return constant (eBPF exit 0x95 tady nefunguje!)

#: CORE syscally — CPython runtime + základní file I/O; chybí-li některý v
#: tabulce → fail-closed ValueError (audit per Python verze, viz
#: SECURITY_THREAT_MODEL.md). Názvy se řeší v runtime → žádné hardcoded čísla
#: (kromě fallback tabulek níže = stabilní kernel ABI).
_STRICT_CORE_SYSCALLS: tuple[str, ...] = (
    # interpret / glibc základy
    "read", "write", "close", "stat", "fstat", "lseek", "mmap", "mprotect",
    "munmap", "brk", "rt_sigaction", "rt_sigprocmask", "sigaltstack",
    "exit_group", "wait4", "getrandom", "clock_gettime", "nanosleep",
    "futex", "getdents64",
    # bootstrap dynamicky linkovaného bináře (ld.so + glibc start — bez nich
    # umírá KAŽDÉ čerstvé dětské binárko; empiricky ověřeno strace 2026-11):
    # execve = preexec vždy execne nový binář, access/pread64 = ld.so preload
    # check + čtení ELF dat, fcntl = CPython F_GETFD po open.
    "execve", "access", "pread64", "fcntl",
    # lstat: site.py `addpackage` před otevřením .pth volá os.lstat a při OSError
    # ticho vrátí → pod filtrem bez lstat umírá celý mechanismus .pth (editable
    # instalace, distutils-precedence apod.) — empiricky ověřeno strace 2026-11.
    "lstat",
    # uname: os.uname() / platform.machine() — běžné plugin API; pod filtrem bez
    # něj padá `import platform` v dětském procesu (EPERM) — empiricky 2026-11.
    "uname",
    # mkdir: glibc mkdir() na x86_64 = přímý syscall (ne mkdirat!) — _db_dir()
    # vždy volá Path.mkdir → bez něj EPERM v dětském procesu; na aarch64 ho kernel
    # nemá samostatně (glibc → mkdirat AT_FDCWD, viz AARCH64_CORE výjimka).
    "mkdir",
    # file I/O (pathlib, json dump, workdir)
    "openat", "newfstatat", "readlinkat", "faccessat", "pipe", "dup", "dup3",
    "chdir", "getcwd", "mkdirat", "unlinkat", "renameat", "symlinkat",
    "truncate", "ftruncate", "fchmod", "utimensat",
)

#: OPTIONAL syscally — legitimní pro pluginy, ale ne každý je na každé arch;
#: chybějící se ticho vynechávají (nikdo jich v CORE cestě nepotřebuje).
_STRICT_OPTIONAL_SYSCALLS: tuple[str, ...] = (
    "arch_prctl",          # x86_64: CPython thread-local storage
    "set_robust_list",     # glibc robust futexy
    "set_tid_address",     # glibc thread cleanup
    "prctl",               # glibc PR_SET_NAME (thread names)
    "rt_sigreturn",        # explicitní signálový return
    "fork", "vfork", "clone",   # pluginy, které spouštějí subprocessy
    "waitid", "kill", "tgkill", "exit",
    "clock_nanosleep",     # time.sleep (alternativa k nanosleep)
    "gettimeofday",        # starší časové API
    "pipe2",               # glibc fallback pro pipe (aarch64 nemá __NR_pipe)
    "socket", "bind", "connect", "accept", "sendto", "recvfrom",
    "sendmsg", "recvmsg", "shutdown", "listen",   # síťová izolace = unshare --net
    # runtime convenience pro pluginy (glibc ≥2.35 / běžné Python API):
    "gettid",              # os.gettid, glibc thread registry
    "prlimit64",           # resource module, RLIMIT dotazy
    "pwrite64",            # os.pwrite (symetrie k CORE pread64)
    "readlink",            # os.readlink (x86_64; aarch64 řeší readlinkat)
    "rseq",                # glibc ≥2.35 restartable sequences
)

#: aarch64 kernel ABI — neexistuje samostatný `stat`/`lstat` (pokrývá newfstatat),
#: `pipe` (jen pipe2), `access` (glibc ho řeší přes faccessat) ani `mkdir`
#: (ARM64 číslo 39 = umount2; glibc mkdir() → mkdirat AT_FDCWD); CPython na arm64
#: funguje přes tyto alternativy.
_STRICT_AARCH64_CORE = tuple(
    n for n in _STRICT_CORE_SYSCALLS if n not in ("stat", "lstat", "pipe", "access", "mkdir")
) + ("pipe2",)

#: P4-2 — fallback tabulky syscallů (stabilní kernel ABI; zdroj: glibc unistd_64.h
#: a kernel v6.1 include/uapi/asm-generic/unistd.h). Používají se jen při
#: nedostupnosti ``os.syscalls`` (některé CPython buildy je nemají).
_STRICT_FALLBACK_SYSCALLS: dict[str, dict[str, int]] = {
    "x86_64": {
        # CORE
        "read": 0, "write": 1, "close": 3, "stat": 4, "fstat": 5, "lseek": 8,
        "mmap": 9, "mprotect": 10, "munmap": 11, "brk": 12, "rt_sigaction": 13,
        "rt_sigprocmask": 14, "sigaltstack": 131, "exit_group": 231, "wait4": 61,
        "getrandom": 318, "clock_gettime": 228, "nanosleep": 35, "futex": 202,
        "getdents64": 217, "openat": 257, "newfstatat": 262, "readlinkat": 267,
        "faccessat": 269, "pipe": 22, "dup": 32, "dup3": 292, "chdir": 80,
        "getcwd": 79, "mkdirat": 258, "unlinkat": 263, "renameat": 264,
        "symlinkat": 266, "truncate": 76, "ftruncate": 77, "fchmod": 91,
        "utimensat": 280,
        # CORE bootstrap (ld.so/glibc start) — lstat: site.py addpackage .pth check,
        # uname: os.uname()/platform.machine() v dětském procesu,
        # mkdir: glibc mkdir() = přímý syscall 83 (_db_dir → Path.mkdir)
        "execve": 59, "access": 21, "pread64": 17, "fcntl": 72, "lstat": 6,
        "uname": 63, "mkdir": 83,
        # OPTIONAL
        "rt_sigreturn": 15, "socket": 41, "connect": 42, "accept": 43,
        "sendto": 44, "recvfrom": 45, "sendmsg": 46, "recvmsg": 47,
        "shutdown": 48, "bind": 49, "listen": 50, "clone": 56, "fork": 57,
        "vfork": 58, "exit": 60, "kill": 62, "gettimeofday": 96,
        "prctl": 157, "arch_prctl": 158, "set_tid_address": 218,
        "clock_nanosleep": 230, "tgkill": 234, "waitid": 247,
        "set_robust_list": 273, "pipe2": 293,
        # runtime convenience (glibc ≥2.35 / Python API)
        "pwrite64": 18, "readlink": 89, "gettid": 186, "prlimit64": 302,
        "rseq": 334,
    },
    "aarch64": {
        # CORE (kernel ABI: bez `stat`, s pipe2)
        "read": 63, "write": 64, "close": 57, "fstat": 80, "lseek": 62,
        "mmap": 222, "mprotect": 226, "munmap": 215, "brk": 214,
        "rt_sigaction": 134, "rt_sigprocmask": 135, "sigaltstack": 132,
        "exit_group": 94, "wait4": 260, "getrandom": 278, "clock_gettime": 113,
        "nanosleep": 101, "futex": 98, "getdents64": 61, "openat": 56,
        "newfstatat": 79, "readlinkat": 78, "faccessat": 48, "dup": 23,
        "dup3": 24, "chdir": 49, "getcwd": 17, "mkdirat": 34, "unlinkat": 35,
        "renameat": 38, "symlinkat": 36, "truncate": 45, "ftruncate": 46,
        "fchmod": 52, "utimensat": 88, "pipe2": 59,
        # CORE bootstrap (ld.so/glibc start) — aarch64 bez `access`/`lstat`
        # (glibc → faccessat/newfstatat); uname = os.uname()/platform.machine()
        "pread64": 67, "fcntl": 25, "uname": 160,
        # OPTIONAL (aarch64 nemá fork/vfork/arch_prctl/readlink → ticho vynechány)
        "set_robust_list": 99, "set_tid_address": 96, "prctl": 167,
        "rt_sigreturn": 139, "clone": 220, "execve": 221, "waitid": 95,
        "kill": 129, "tgkill": 131, "exit": 93, "clock_nanosleep": 115,
        "gettimeofday": 169, "socket": 198, "bind": 200, "connect": 203,
        "accept": 202, "sendto": 206, "recvfrom": 207, "sendmsg": 211,
        "recvmsg": 212, "shutdown": 210, "listen": 201,
        # runtime convenience (glibc ≥2.35 / Python API)
        "pwrite64": 68, "gettid": 178, "prlimit64": 261, "rseq": 293,
    },
}


def _build_seccomp_strict_filter() -> tuple[list[tuple[int, int, int, int]], int]:
    """P4-2: sestaví BPF allowlist (rodič — deterministické, testovatelné).

    Program: kontrola architektury → allow seznam syscallů → default ERRNO(EPERM)
    (blokováný syscall selže s EPERM místo SIGSYS killu = lepší diagnostika).

    Returns:
        (instrukce jako 4-tice code/jt/jf/k, očekávaná AUDIT_ARCH konstanta)

    Raises:
        ValueError: nepodporovaná architektura / chybějící CORE syscall / os.syscalls.
    """
    import platform as _platform

    arch = _platform.machine()
    audit_arch = _AUDIT_ARCHS.get(arch)
    if audit_arch is None:
        raise ValueError(
            f"strict profil podporuje jen x86_64/aarch64, aktuální architektura {arch!r}"
        )
    table: dict[str, int] | None = getattr(os, "syscalls", None)
    if not isinstance(table, dict):  # některé CPython buildy nemají os.syscalls
        table = _STRICT_FALLBACK_SYSCALLS.get(arch)
        if table is None:
            raise ValueError(f"strict profil — žádná tabulka syscallů pro arch {arch!r}")
    core_names = (
        _STRICT_AARCH64_CORE if arch == "aarch64" else _STRICT_CORE_SYSCALLS
    )
    missing_core = [n for n in core_names if n not in table]
    if missing_core:
        raise ValueError(
            f"strict profil — chybějící CORE syscally v tabulce pro {arch}: {missing_core}"
        )
    allowed = list(core_names) + [
        n for n in _STRICT_OPTIONAL_SYSCALLS if n in table
    ]
    nums = sorted({table[n] for n in allowed})

    # Layout: [0]=load arch, [1]=arch EQ, [2]=load nr, [3..n]=allow EQ chain,
    # [idx_errno]=RET ERRNO(EPERM), [idx_allow]=RET ALLOW.
    idx_errno = 3 + len(nums)
    idx_allow = idx_errno + 1
    insns: list[tuple[int, int, int, int]] = []
    insns.append((_BPF_LD_ABS_W, 0, 0, 4))            # seccomp_data.arch (offset 4)
    insns.append((_BPF_JMP_EQ_K, 0, idx_errno - 2, audit_arch))  # arch OK → další; jf → errno
    insns.append((_BPF_LD_ABS_W, 0, 0, 0))            # seccomp_data.nr (offset 0)
    for num in nums:
        p = len(insns)
        # jt → RET ALLOW; jf=0 → fall-through na další EQ (skok N znamená
        # cíl i+N+1 — viz bpf_convert_filter).
        insns.append((_BPF_JMP_EQ_K, idx_allow - p - 1, 0, num))
    insns.append((_BPF_RET_K, 0, 0, 0x00050001))      # default: ERRNO|EPERM (uapi: RET_ERRNO=0x50000)
    insns.append((_BPF_RET_K, 0, 0, 0x7FFF0000))      # SECCOMP_RET_ALLOW
    return insns, audit_arch


def _seccomp_strict_preexec(insns: list[tuple[int, int, int, int]]) -> Callable[[], None]:
    """P4-2: preexec_fn — v dětském procesu NO_NEW_PRIVS + seccomp filter.

    Raw syscall přes ``libc.syscall()`` (glibc ≥2.41 neexportuje `seccomp()` jako
    dynamický symbol); čísla SYS_seccomp/SYS_prctl = stabilní kernel ABI per arch.
    """

    import ctypes as _ct
    import platform as _platform

    arch = _platform.machine()  # stejný proces, kde běžel _build_seccomp_strict_filter
    sys_seccomp_nr = _SYS_SECCOMP_NR.get(arch)
    sys_prctl_nr = _SYS_PRCTL_NR.get(arch)
    if sys_seccomp_nr is None or sys_prctl_nr is None:
        raise ValueError(f"seccomp strict — žádná SYS čísla pro arch {arch!r}")

    class _sock_filter(_ct.Structure):
        _fields_ = [
            ("code", _ct.c_ushort),
            ("jt", _ct.c_ubyte),
            ("jf", _ct.c_ubyte),
            ("k", _ct.c_uint),
        ]

    arr = (_sock_filter * len(insns))()
    for i, (code, jt, jf, k) in enumerate(insns):
        arr[i].code, arr[i].jt, arr[i].jf, arr[i].k = code, jt, jf, k

    def factory() -> None:  # pragma: no cover - běží v dětském procesu
        lib = _ct.CDLL(None, use_errno=True)
        lib.syscall.restype = _ct.c_long
        c = _ct.c_long  # explicitní 64-bit argy (bez argtypes by ctypes poslal int32 → špinavé horní bity registrů)
        PR_SET_NO_NEW_PRIVS = 0x26
        # kernel ≥6.x validuje i nevyužité arg3/arg4/arg5 (musí být 0) — explicitní nuly!
        if int(lib.syscall(c(sys_prctl_nr), c(PR_SET_NO_NEW_PRIVS), c(1), c(0), c(0), c(0))) != 0:
            raise ValueError(
                f"seccomp strict: prctl(NO_NEW_PRIVS) selhal errno={_ct.get_errno()}"
            )

        class _sock_fprog(_ct.Structure):
            _fields_ = [
                ("len", _ct.c_uint),
                ("filter", _ct.POINTER(_sock_filter)),
            ]

        prog = _sock_fprog(len(arr), arr)
        # uapi linux/seccomp.h: SET_MODE_STRICT=0, SET_MODE_FILTER=**1**,
        # GET_ACTION_AVAIL=2 (častá past — 2 by instalaci dekodovalo jako
        # dotaz na dostupnost akce).
        SECCOMP_SET_MODE_FILTER = 1
        if int(lib.syscall(c(sys_seccomp_nr), c(SECCOMP_SET_MODE_FILTER), c(0), _ct.byref(prog))) != -1:
            return
        raise ValueError(
            f"seccomp strict: instalace filteru selhala errno={_ct.get_errno()}"
        )

    return factory


def _strict_mount_setup() -> None:
    """P4-2 strict: soukromá mount namespace — / read-only, workdir (cwd) rw bind.

    Běží v dětském procesu před plugin kódem (mapped root uvnitř user ns).
    Fail-closed: selže-li jakýkoli mount → ValueError (host požadoval izolaci a
    nemohl ji dát — konzistentní s P0-3 síťovou izolací).
    """
    wd = os.getcwd()
    steps = (
        ("make-rprivate", ["--make-rprivate", "/"]),
        ("bind /", ["--bind", "/", "/"]),
        ("ro-bind /", ["-o", "remount,ro,bind", "/", "/"]),
        ("rw-workdir", ["--bind", wd, wd]),
    )
    for label, argv in steps:
        proc = subprocess.run(["mount", *argv], capture_output=True, timeout=10, check=False)
        if proc.returncode != 0:
            err = (proc.stderr or b"").decode(errors="replace").strip()[:200]
            raise ValueError(f"strict mount setup selhal ({label}): {err}")


def sandbox_exec(
    argv: list[str],
    limits: SandboxLimits | None = None,
    workdir: Path | None = None,
) -> dict[str, Any]:
    """Sandbox běh: ``python -m stopa.cli plugin-run <argv>`` s limity.

    Výsledek = JSON stdout ({"ok": true, "result": ...}); timeout/paměť/
    ne-JSON → ValueError se srozumitelným důvodem (graceful degradation).

    P0-3 hardening:
    - ``workdir=None`` → izolovaný jednorázový workdir pod ``_run_dir_root()``
      (úklid při úspěchu, zachování při chybě pro debug); explicitní workdir se neuklídí.
    - RLIMIT_CPU + RLIMIT_NOFILE kromě stávajících RLIMIT_AS a wall-clock timeoutu;
      překročení CPU limitu (SIGXCPU) → výrazná chyba, ne „nevrátil JSON“.
    - strop velikosti stdout+stderr (``max_output_mb``).
    - volitelná síťová izolace ``network_isolated`` přes obal ``unshare --net``
      (Linux; při nedostupnosti probe → ValueError, host požadoval izolaci a nemohl ji dát).

    P4-2 hardening:
    - default profil: navíc RLIMIT_NPROC (fork bomb) + RLIMIT_FSIZE (obrovský soubor);
    - ``profile="strict"``: seccomp-bpf allowlist přes ctypes (fail-closed na
      nepodporované architektuře) + volitelný user namespace wrapper
      (``unshare --user --map-root-user --mount``; při dostupnosti → child dělá
      / read-only + workdir rw bind, env STOPA_SANDBOX_STRICT_MOUNTS).
    """
    lim = limits or sandbox_limits({})
    env = dict(os.environ)
    env.update(lim.extra_env)
    cmd = [sys.executable, "-m", "stopa.cli", "plugin-run", *argv]

    if lim.network_isolated:
        if not _unshare_net_available():
            raise ValueError(
                "sandbox síťová izolace nedostupná (unshare --net nefunguje na tomto systému)"
            )
        cmd = ["unshare", "--net"] + cmd

    def _base_rlimits() -> Callable[[], None] | None:
        return (
            _rlimit_factory(
                lim.max_mem_mb,
                lim.cpu_seconds,
                max_procs=lim.max_procs,
                max_file_mb=lim.max_file_mb,
            )
            if os.name == "posix"
            else None
        )

    # P4-2 — strict profil: seccomp-bpf allowlist (rodič sestaví BPF program;
    # fail-closed na nepodporované architektuře / chybějících CORE syscallích)
    # + volitelný user namespace wrapper.
    if lim.profile == "strict":
        insns, _audit_arch = _build_seccomp_strict_filter()
        seccomp_fn = _seccomp_strict_preexec(insns)
        base = _base_rlimits()

        def _strict_preexec() -> None:  # P4-2: rlimity + seccomp v dětském procesu
            if base is not None:
                base()
            seccomp_fn()

        preexec = _strict_preexec
        if _unshare_userns_available():
            cmd = ["unshare", "--user", "--map-root-user", "--mount"] + cmd
            env["STOPA_SANDBOX_STRICT_MOUNTS"] = "1"  # child: / ro + workdir rw bind
    else:
        preexec = _base_rlimits()

    isolated = workdir is None
    plugin_name = argv[0] if argv and isinstance(argv[0], str) else "plugin"
    wd = Path(workdir) if not isolated else _isolated_workdir(plugin_name)
    try:
        proc = subprocess.run(
            cmd,
            check=False,  # exit kód zpracováváme explicitně níže
            capture_output=True,
            text=True,
            timeout=lim.timeout_s,
            env=env,
            cwd=str(wd),
            preexec_fn=preexec if os.name == "posix" else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(
            f"sandbox timeout po {lim.timeout_s} s (workdir pro debug: {wd})"
        ) from exc

    out_chars = len(proc.stdout or "") + len(proc.stderr or "")  # text mode: char ≈ byte
    max_chars = lim.max_output_mb * 1024 * 1024
    if out_chars > max_chars:
        raise ValueError(
            f"sandbox výstup příliš velký ({out_chars} B > limit {lim.max_output_mb} MB)"
        )

    import signal as _signal

    # Release 2.4 CI fix: bez posix gate — testy CPU limitu běží i na Windows, kde
    # ``signal.SIGXCPU`` neexistuje (fallback 24); reálně negativní returncode na
    # Windows nevzniká (preexec_fn = None), takže klasifikace je tam inertní.
    sigxcpu = getattr(_signal, "SIGXCPU", 24)
    if proc.returncode in (-sigxcpu, -24):
        raise ValueError(
            f"sandbox překročil CPU limit ({lim.cpu_seconds} s; workdir pro debug: {wd})"
        )
    stdout = (proc.stdout or "").strip()
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        tail = (proc.stderr or "")[-300:]
        raise ValueError(
            f"sandbox nevrátil JSON (exit {proc.returncode}): {tail} (workdir pro debug: {wd})"
        ) from exc
    if not isinstance(payload, dict) or not payload.get("ok"):
        detail = payload.get("error", "neznámá chyba") if isinstance(payload, dict) else "?"
        raise ValueError(f"sandbox selhal: {detail} (workdir pro debug: {wd})")

    if isolated:  # úspěch → uklidit jednorázový workdir
        import shutil

        shutil.rmtree(wd, ignore_errors=True)
    return payload


def profile_to_dict(profile: Any) -> dict[str, Any]:
    """TriageProfile → JSON-safe dict (pro sandbox přenos)."""
    d = dataclasses.asdict(profile)
    for sig in d.get("signals", []):
        if isinstance(sig.get("patterns"), list):  # asdict tuple→list; normalizace
            sig["patterns"] = tuple(sig["patterns"])
    return d


def profile_from_dict(data: dict[str, Any]) -> Any:
    """Rekonstrukce TriageProfile z dictu (sandbox cesta)."""
    from stopa.intelligence.triage import SignalSpec, TriageProfile

    signals = tuple(
        SignalSpec(
            key=s["key"],
            weight=int(s.get("weight", 1)),
            kind=s.get("kind", ""),
            pattern=str(s.get("pattern", "")),
            patterns=tuple(s.get("patterns") or ()),
            min_count=int(s.get("min_count", 1)),
            entity_kind=str(s.get("entity_kind", "")),
            description=str(s.get("description", "")),
        )
        for s in data.get("signals", [])
    )
    return TriageProfile(
        key=data["key"],
        title=data.get("title", ""),
        description=data.get("description", ""),
        signals=signals,
        threshold=int(data.get("threshold", 0)),
        min_signals=int(data.get("min_signals", 2)),
        hypothesis_template=data.get("hypothesis_template", ""),
    )
