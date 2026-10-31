"""Windows registry hive extraktor — persistence, USB zařízení, uživatelské info.

AXIOM-style (Registry / DPAPI artifacty): každý soubor se signaturou `regf` projde
parserem (regipy) a vybereme forenzně cenné klíče:
- Run/RunOnce/RunOnceEx → persistence (co se spouští při startu)
- MountedDevices → připojená USB/removable média
- Control Panel\\User Name, Environment → identita uživatele

ČISTÁ funkce `build_registry_artifacts()` pracuje nad objekty s atributy
`.path` / `.timestamp` / `.values` (regipy Subkey/Value přesně takhle vypadají) —
testy nepotřebují regipy ani IO. IO je jen v `extract_registry_artifacts()`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from stopa.models import Artifact

log = logging.getLogger("stopa.artifacts.registry")

# E1: verze parseru — eviduje se v audit logu (reprodukovatelnost analýzy)
PARSER_VERSION = "1.0"

MAX_VALUE_LEN = 200  # nevtěsnávat obří data do detailů
MAX_TOP_KEYS = 30  # triage artifact — seznam top-level klíčů


# (substring cesty, artifact_type, popis) — pořadí = priorita (první shoda vyhraje).
# Konkrétnější patterns PŘED obecnějšími (\CurrentVersion\Run je substring \...RunOnce).
INTERESTING_KEY_PATTERNS: list[tuple[str, str, str]] = [
    (r"\CurrentVersion\RunOnce", "registry_persistence", "Jednorázový start (RunOnce)"),
    (r"\CurrentVersion\Run", "registry_persistence", "Spouštěno při startu (Run)"),
    (r"\MountedDevices", "registry_usb_device", "Připojené USB/removable média"),
    (r"\Control Panel\User Name", "registry_user_info", "Uživatelské jméno"),
    (r"\Environment", "registry_environment", "Uživatelské proměnné prostředí"),
]


def _match_interesting(path: str) -> tuple[str, str] | None:
    """Vrátí (artifact_type, popis) pro první shodu s cesty klíče, jinak None."""
    norm = path.replace("/", "\\")
    for pattern, art_type, desc in INTERESTING_KEY_PATTERNS:
        if pattern.lower() in norm.lower():
            return art_type, desc
    return None


def _value_to_str(value) -> str:
    """Bezpečná serializace registry hodnoty (bytes/str/int) do textu."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            s = value.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — defenzivní fallback
            s = repr(value)
    else:
        s = str(value)
    return s[:MAX_VALUE_LEN]


def build_registry_artifacts(subkeys) -> list[Artifact]:
    """ČISTÁ funkce: z iterovatelných registry klíčů vybere forenzně cenné artifacty.

    Každý `subkey` musí mít `.path`, `.timestamp` a `.values` (seznam objektů s
    `.name` / `.value`). Klíče bez hodnot se ignorují (jen prázdné kontejnery).
    """
    out: list[Artifact] = []
    for sub in subkeys:
        path = getattr(sub, "path", "") or ""
        match = _match_interesting(path)
        if match is None:
            continue
        art_type, desc = match

        values = getattr(sub, "values", []) or []
        value_map: dict[str, str] = {}
        for v in values:
            name = getattr(v, "name", "") or "(Default)"
            value_map[name] = _value_to_str(getattr(v, "value", None))

        if not value_map:
            continue  # prázdný kontejner — nic k extrakci

        ts = getattr(sub, "timestamp", None)
        out.append(
            Artifact(
                artifact_type=art_type,
                timestamp=ts,
                title=f"{desc} — {path}",
                details={"key_path": path, "values": value_map},
            )
        )
    return out


def _triage_artifact(subkeys) -> Artifact:
    """Triage artifact pro celou hive — počet klíčů + top-level jména."""
    total = 0
    top_keys: list[str] = []
    for sub in subkeys:
        total += 1
        path = getattr(sub, "path", "") or ""
        # top-level = první segment cesty (bez vedoucího \\)
        seg = path.lstrip("\\").split("\\")[0]
        if seg and seg not in top_keys:
            top_keys.append(seg)
    return Artifact(
        artifact_type="registry_hive",
        timestamp=None,
        title=f"Registry hive — {total} klíčů",
        details={
            "key_count": total,
            "top_level_keys": top_keys[:MAX_TOP_KEYS],
            "truncated": len(top_keys) > MAX_TOP_KEYS,
        },
    )


def extract_registry_artifacts(path: Path) -> list[Artifact]:
    """Extrahuje artifacty z Windows registry hive (regf). Vrací Artifacty BEZ
    source_id/file_id (ty doplní pipeline — extraktor nezná kontext případu).

    Chyby (poškozená hive, chybějící regipy) → log + práznej výsledek, nikdy ne výjimka.
    """
    try:
        from regipy.registry import RegistryHive  # type: ignore[import-untyped] — volitelná závislost
    except ImportError as e:
        log.warning("regipy není nainstalován (pip install regipy): %s", e)
        return []

    try:
        hive = RegistryHive(hive_path=str(path))
        subkeys = list(hive.recurse_subkeys())
    except Exception as e:  # noqa: BLE001 — poškozená/partial hive, defenzivní
        log.warning("Registry open %s: %s", path, e)
        return []

    if not subkeys:
        return []

    arts = build_registry_artifacts(subkeys)
    arts.append(_triage_artifact(iter(subkeys)))
    return arts
