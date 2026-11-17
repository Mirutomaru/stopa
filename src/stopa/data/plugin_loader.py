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
    AiToolSpec as _AiToolSpec,
)
from stopa.domain.plugins import (
    ExtractorSpec,
    PluginManifest,
    SandboxLimits,
    TriageProfileSpec,
    parse_manifest,
    sandbox_limits,
    validate_manifest,
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
    max_mem_mb: int, cpu_seconds: int | None = None, max_fds: int = 1024
) -> Callable[[], None]:
    """preexec_fn: stropy subprocessu (Linux RLIMIT_AS + P0-3: CPU, NOFILE).

    RLIMIT_NOFILE chrání proti file-descriptor exhaust; na systémech bez práva
    zvýšit limit se ticho ignoruje (limit může být i nižší než požadovaný).
    """

    def factory() -> None:  # pragma: no cover - běží v dětském procesu
        if os.name != "posix":  # Windows nemá resource modul
            return
        import resource

        limit = max_mem_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        if cpu_seconds is not None and cpu_seconds > 0:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (max_fds, max_fds))
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
            preexec_fn=(
                _rlimit_factory(lim.max_mem_mb, lim.cpu_seconds) if os.name == "posix" else None
            ),
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

    if os.name == "posix" and proc.returncode in (-_signal.SIGXCPU, -24):
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
