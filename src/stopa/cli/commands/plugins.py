"""CLI — plugin ekosystém F6.4 (list/info/verify/run + sandbox entry point).

P1-4 (refaktor god-file ``cli.py``): přesunuto bez změny chování;
facade ``stopa.cli`` re-exportuje implementace pro kompatibilitu.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .._util import _load_settings_dict, _open_db, _print_json, _save_settings_dict


def _plugin_row(p) -> dict:
    """LoadedPlugin → JSON-safe řádek (sdílené CLI + Web)."""
    return {
        "name": p.name,
        "version": p.version,
        "description": p.description,
        "author": p.author,
        "min_stopa_version": p.min_stopa_version,
        "verified": p.verified,
        "capabilities": list(p.capabilities),
        "issues": list(p.issues),
        "path": str(p.path),
    }


def _discover_plugin(args_name: str):
    """Najde plugin podle jména; vrací (plugin|None, settings)."""
    import stopa as _stopa_pkg
    from stopa.data.plugin_loader import discover_plugins

    settings = _load_settings_dict()
    plugins = discover_plugins(settings=settings, stopa_version=_stopa_pkg.__version__)
    return plugins.get(args_name), settings


def _plugin_manifest(name_path: Path):
    """Re-parse manifestu (data vrstva — spec pro rozřešení kapacit)."""
    from stopa.domain.plugins import parse_manifest

    return parse_manifest(json.loads((name_path / "plugin.json").read_text(encoding="utf-8")))


def _plugin_exec_cap_in_process(plugin, cap: str, args) -> object:
    """In-process běh jedné kapacity (ověřená cesta; sandbox = tenže kód v subprocessu)."""
    from stopa.data.plugin_loader import (
        profile_to_dict,
        resolve_ai_tools,
        resolve_extractors,
        resolve_triage_profiles,
    )

    manifest = _plugin_manifest(plugin.path)
    if cap == "extractor":
        key = getattr(args, "key", None) or ""
        spec = next((e for e in manifest.extractors if e.key == key), None)
        if spec is None:
            raise ValueError(f"extractor klíč {key!r} neexistuje v pluginu {plugin.name}")
        resolved = resolve_extractors(plugin.path, plugin.name, (spec,))
        out = []
        for f in getattr(args, "files", []) or []:
            arts = resolved[0].extract_fn(Path(f))
            out.extend(a.model_dump() if hasattr(a, "model_dump") else dict(a) for a in arts)
        return out
    if cap == "triage_profile":
        profiles = resolve_triage_profiles(plugin.path, plugin.name, manifest.triage_profiles)
        return [profile_to_dict(pr) for pr in profiles]
    if cap == "ai_tool":
        tools = resolve_ai_tools(plugin.path, plugin.name, manifest.ai_tools)
        want = getattr(args, "tool", None) or ""
        tool = next((t for t in tools if t.name == want), tools[0] if len(tools) == 1 else None)
        if tool is None:
            avail = ", ".join(t.name for t in tools)
            raise ValueError(f"AI tool {want!r} neexistuje (dostupné: {avail})")
        params_raw = getattr(args, "params", "{}") or "{}"
        params = json.loads(params_raw)
        case_id = getattr(args, "case_id", None)
        if not case_id:
            raise ValueError("ai_tool vyžaduje --case-id")
        db = _open_db(case_id)
        try:
            return tool.handler(db, case_id, params)
        finally:
            db.close()
    raise ValueError(f"neznámá kapacita {cap!r}")  # pragma: no cover


def cmd_plugin_list(args: argparse.Namespace) -> int:
    """F6.4 — seznam detekovaných pluginů (manifest + stav ověření)."""
    import stopa as _stopa_pkg
    from stopa.data.plugin_loader import discover_plugins

    settings = _load_settings_dict()
    plugins = discover_plugins(settings=settings, stopa_version=_stopa_pkg.__version__)
    rows = sorted(plugins.values(), key=lambda x: x.name)
    if getattr(args, "json", False):
        _print_json({"ok": True, "count": len(rows), "plugins": [_plugin_row(r) for r in rows]})
        return 0
    if not rows:
        print("Žádné pluginy nenalezeny (settings plugins_dirs / STOPA_PLUGINS_DIR / ~/.stopa/plugins)")
        return 0
    for p in rows:
        mark = "ověřený" if p.verified else "sandbox "
        caps = ",".join(p.capabilities) or "-"
        warn = f"  [{len(p.issues)} upozornění]" if p.issues else ""
        print(f"{p.name} v{p.version}  ({mark})  [{caps}]  {p.description}{warn}")
    return 0


def cmd_plugin_info(args: argparse.Namespace) -> int:
    """F6.4 — detail jednoho pluginu."""
    plugin, _ = _discover_plugin(args.name)
    if plugin is None:
        print(f"Plugin nenalezen: {args.name}", file=sys.stderr)
        return 1
    row = _plugin_row(plugin)
    if getattr(args, "json", False):
        _print_json({"ok": True, "plugin": row})
        return 0
    print(f"{row['name']} v{row['version']} — {row['description'] or '(bez popisu)'}")
    print(f"  autor:          {row['author'] or '-'}")
    print(f"  min_stopa:      {row['min_stopa_version']}")
    print(f"  stav:           {'ověřený (in-process)' if row['verified'] else 'neověřený (sandbox)'}")
    print(f"  kapacity:       {', '.join(row['capabilities']) or '-'}")
    print(f"  cesta:          {row['path']}")
    for issue in row["issues"]:
        print(f"  upozornění:     {issue}")
    return 0


def cmd_plugin_verify(args: argparse.Namespace) -> int:
    """F6.4 — správa allowlistu ověřených pluginů (settings.json plugins_verified)."""
    settings = _load_settings_dict()
    raw = settings.get("plugins_verified")
    names = {x for x in raw if isinstance(x, str)} if isinstance(raw, list) else set()
    action = "přidán" if args.add else "odebrán"
    if args.add:
        names.add(args.name)
    elif args.name not in names:
        print(f"Plugin {args.name} nebyl v allowlistu (nic neodebráno)", file=sys.stderr)
        return 1
    else:
        names.discard(args.name)
    settings["plugins_verified"] = sorted(names)
    _save_settings_dict(settings)
    print(f"{action}: {args.name} → allowlist {sorted(names)}")
    return 0


def cmd_plugin_run(args: argparse.Namespace) -> int:
    """F6.4 — běh kapacity pluginu; neověřený = sandbox subprocess s limity."""
    import stopa as _stopa_pkg
    from stopa.data.plugin_loader import discover_plugins, sandbox_exec
    from stopa.domain.plugins import sandbox_limits as parse_sandbox_limits

    settings = _load_settings_dict()
    plugins = discover_plugins(settings=settings, stopa_version=_stopa_pkg.__version__)
    plugin = plugins.get(args.name)
    if plugin is None:
        print(f"Plugin nenalezen: {args.name}", file=sys.stderr)
        return 1

    argv = [args.name, "--cap", args.cap]  # sandbox_exec doplní "plugin-run" sám
    if args.cap == "extractor":
        argv += ["--key", args.key or ""] + [f for x in (args.files or []) for f in ("--file", x)]
    elif args.cap == "ai_tool":
        if args.tool:
            argv += ["--tool", args.tool]
        if args.case_id:
            argv += ["--case-id", args.case_id]
        argv += ["--params", args.params or "{}"]

    sandboxed = not plugin.verified
    try:
        if sandboxed:
            # P0-3: workdir=None → sandbox_exec sám vytvoří izolovaný jednorázový workdir
            payload = sandbox_exec(
                argv, limits=parse_sandbox_limits(settings.get("plugin_sandbox")), workdir=None
            )
            result = payload.get("result")
        else:
            result = _plugin_exec_cap_in_process(plugin, args.cap, args)
    except (ValueError, TypeError, ImportError) as exc:
        print(f"Plugin běh selhal: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        _print_json({"ok": True, "name": plugin.name, "cap": args.cap, "sandboxed": sandboxed, "result": result})
    else:
        mode = "sandbox" if sandboxed else "in-process"
        print(f"{plugin.name} / {args.cap} ({mode}):")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_plugin_run_entry(args: argparse.Namespace) -> int:
    """F6.4 — interní entry point sandbox subprocessu (přímý běh, JSON stdout)."""
    plugin, _ = _discover_plugin(args.name)
    if plugin is None:
        print(json.dumps({"ok": False, "error": f"plugin nenalezen: {args.name}"}))
        return 1
    try:
        result = _plugin_exec_cap_in_process(plugin, args.cap, args)
        json.dumps(result, ensure_ascii=False)  # enforce JSON-safety dříve než tisk
    except Exception as exc:  # noqa: BLE001 — sandbox hlásí cokoliv jako error envelope
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    return 0


