"""F1.2 — Volatility 3 CLI wrapper (ROADMAP V2 Fáze 1).

IO vrstva: spouští externí ``vol`` proces s JSON rendererem a vrací
syntetizované výstupy. Domain logika je v ``domain/mem_forensics.py``.

Design:
  * **Volitelná runtime závislost** (jako pytsk3/regipy) — bez nainstalovaného
    balíčku vrací ``vol_available() == False`` a ``run_vol_plugin`` zvedne
    ``VolUnavailable`` srozumitelně; nic se neinstaluje implicitně.
  * **Subprocess, ne Python API** — Volatility 3 mění interní layout mezi
    verze (2.x → změny plugin registry); stabilní kontrakt je CLI + JSON
    renderer (``-r json``).
  * Cesta k vol: env ``STOPA_VOL_BIN`` (striktní) → venv bin vedle aktuálního
    interpretu → PATH.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger("stopa.volatility")


class VolError(RuntimeError):
    """Obecná chyba vol CLI běhu."""


class VolUnavailable(VolError):
    """Volatility 3 není nainstalovaná / vol binárka nenalezena."""


@dataclass
class VolPluginResult:
    """Výsledek jednoho pluginu — syntetizovaný JSON výstup + metadatum."""

    plugin: str
    rows: list[dict] = field(default_factory=list)
    exit_code: int = 0
    stderr_tail: str = ""


def _vol_candidates() -> list[str]:
    """Kandidátní cesty k vol binárce (v pořadí priorizace)."""
    candidates: list[str] = []
    env_bin = os.environ.get("STOPA_VOL_BIN")
    if env_bin:  # striktní — explicitní cesta musí existovat
        return [env_bin]
    venv_bin = Path(sys.executable).resolve().parent / "vol"
    if venv_bin.exists():
        candidates.append(str(venv_bin))
    on_path = shutil.which("vol")
    if on_path:
        candidates.append(on_path)
    return candidates


def vol_available() -> bool:
    """Existuje volatelná ``vol`` binárka (bez spuštění)."""
    return any(Path(c).is_file() for c in _vol_candidates())


def resolve_vol_bin() -> str | None:
    """První volatelný kandidát, jinak None."""
    for c in _vol_candidates():
        if Path(c).is_file():
            return c
    return None


def run_vol_plugin(
    dump_path: str,
    plugin: str,
    *,
    timeout_s: int = 600,
    extra_args: list[str] | None = None,
) -> VolPluginResult:
    """Spuští ``vol -q -r json -f <dump> <plugin>`` a parsuje JSON výstup.

    Args:
        dump_path: Cesta k memory dumpu (raw/LZMA/pcap…).
        plugin: Plné jméno Volatility 3 pluginu (např. ``windows.pslist``).
        timeout_s: Deadline běhu jednoho pluginu.
        extra_args: Dodatečné argumenty pluginu (před pluginem, po -f).

    Raises:
        VolUnavailable: vol nenalezeno.
        VolError: neúspěšný exit / nevalidní JSON / timeout.
    """
    vol_bin = resolve_vol_bin()
    if vol_bin is None:
        raise VolUnavailable(
            "Volatility 3 není nainstalovaná (nainstalujte přes `pip install volatility3` "
            "do STOPA venv, nebo nastavte STOPA_VOL_BIN)"
        )

    cmd = [vol_bin, "-q", "-r", "json", "-f", str(dump_path)]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(plugin)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise VolError(f"vol {plugin}: timeout po {timeout_s}s") from e
    except OSError as e:
        raise VolError(f"vol {plugin}: selhalo spuštění: {e}") from e

    stderr_tail = (proc.stderr or "")[-2000:]
    if proc.returncode != 0 and not (proc.stdout or "").strip():
        # vol vrací nonzero i s výpisem symbol hints — bez stdoutu je to chyba
        raise VolError(f"vol {plugin}: exit {proc.returncode} — {stderr_tail}")

    out = (proc.stdout or "").strip()
    if not out:
        return VolPluginResult(plugin=plugin, rows=[], exit_code=proc.returncode, stderr_tail=stderr_tail)

    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        raise VolError(f"vol {plugin}: nevalidní JSON výstup: {e}") from e

    if isinstance(data, dict):
        rows = [data]
    elif isinstance(data, list):
        rows = data
    else:
        raise VolError(f"vol {plugin}: neočekávaný JSON typ: {type(data).__name__}")

    return VolPluginResult(plugin=plugin, rows=rows, exit_code=proc.returncode, stderr_tail=stderr_tail)


def run_vol_plugins(
    dump_path: str,
    plugins: list[str],
    *,
    timeout_s: int = 600,
    progress: callable | None = None,  # type: ignore[type-arg]
) -> dict[str, VolPluginResult]:
    """Spustí sérii pluginů (pořadí = pořadí v ``plugins``); vrace mapu.

    Chyba jednoho pluginu se neshodí do výjimky — uloženo jako
    ``VolError.message`` ve stderr_tail, aby zbytek analýzy pokračoval
    (Forenzní kontext: jeden padlý plugin ≠ padlá analýza).

    Args:
        progress: Volitelná callback(done, total, label) pro CLI progress.
    """
    results: dict[str, VolPluginResult] = {}
    total = len(plugins)
    for i, plugin in enumerate(plugins):
        if progress is not None:
            try:
                progress(i, total, f"vol {plugin}")
            except Exception as exc:  # noqa: BLE001 — progress je kosmetický
                _log.debug("vol progress callback selhal: %s", exc)
        try:
            results[plugin] = run_vol_plugin(dump_path, plugin, timeout_s=timeout_s)
        except VolUnavailable:
            raise  # chybějící vol zastaví celou analýzu (deterministicky)
        except VolError as e:
            results[plugin] = VolPluginResult(
                plugin=plugin, rows=[], exit_code=-1, stderr_tail=str(e)[:2000]
            )
    if progress is not None:
        try:
            progress(total, total, "hotovo")
        except Exception as exc:  # noqa: BLE001 — progress je kosmetický
            _log.debug("vol progress callback selhal: %s", exc)
    return results
