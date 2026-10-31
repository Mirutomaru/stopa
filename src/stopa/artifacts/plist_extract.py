"""Apple property list extraktor — časové značky + struktura.

AXIOM-style (Apple plist / iMessage / LaunchServices artifacty): každý soubor se
signaturou `plist` (binární bplist00 i XML) projde nativním `plistlib`.
- datetime listy → artifact `plist_date` s cestou klíče a hodnotou
- triage artifact `property_list` — top-level struktura + počty

ČISTÁ funkce `build_plist_artifacts()` pracuje nad načteným Python objektem (dict/
list/scalar) — testy nepotřebují IO ani soubory. IO je jen v `extract_plist_artifacts()`.
"""

from __future__ import annotations

import logging
import plistlib
from datetime import datetime
from pathlib import Path

from stopa.models import Artifact

log = logging.getLogger("stopa.artifacts.plist")

# E1: verze parseru — eviduje se v audit logu (reprodukovatelnost analýzy)
PARSER_VERSION = "1.0"

MAX_DATE_ARTIFACTS = 50  # nevtěsnávat stovky date polí do timeline
MAX_TOP_KEYS = 30  # triage artifact — seznam top-level klíčů


def _walk(data, prefix: str):
    """Rekurzivně vrací (cesta_klíče, hodnota) pro všechny listy plist stromu."""
    if isinstance(data, dict):
        for k, v in data.items():
            path = f"{prefix}/{k}" if prefix else str(k)
            yield from _walk(v, path)
    elif isinstance(data, (list, tuple)):
        for i, v in enumerate(data):
            yield from _walk(v, f"{prefix}[{i}]")
    else:
        yield prefix, data


def build_plist_artifacts(data) -> list[Artifact]:
    """ČISTÁ funkce: z načteného plist objektu vybere date artifacty + triage.

    `data` je výsledek `plistlib.load()` — dict/list/scalar. datetime listy se
    stanou artifacty (Apple plists ukládají časy jako native date typ).
    """
    out: list[Artifact] = []

    # 1) date artifacty — každé datetime pole s cestou klíče
    date_count = 0
    for path, value in _walk(data, ""):
        if isinstance(value, datetime):
            date_count += 1
            if date_count > MAX_DATE_ARTIFACTS:
                break
            out.append(
                Artifact(
                    artifact_type="plist_date",
                    timestamp=value,
                    title=f"{path} = {value.isoformat()}",
                    details={"key_path": path},
                )
            )

    # 2) triage artifact — struktura + počty
    top_keys: list[str] = []
    if isinstance(data, dict):
        top_keys = [str(k) for k in data][:MAX_TOP_KEYS]
    elif isinstance(data, (list, tuple)):
        top_keys = [f"[{i}]" for i in range(min(len(data), MAX_TOP_KEYS))]

    out.append(
        Artifact(
            artifact_type="property_list",
            timestamp=None,
            title=f"Property list — {len(top_keys)}+ klíčů, {date_count} datových polí",
            details={
                "top_level_keys": top_keys,
                "truncated": (isinstance(data, dict) and len(data) > MAX_TOP_KEYS),
                "date_fields": date_count,
                "root_type": type(data).__name__,
            },
        )
    )
    return out


def extract_plist_artifacts(path: Path) -> list[Artifact]:
    """Extrahuje artifacty z Apple property list (binární i XML). Vrací Artifacty BEZ
    source_id/file_id (ty doplní pipeline — extraktor nezná kontext případu).

    Chyby (poškozený plist, neplatný formát) → log + práznej výsledek, nikdy ne výjimka.
    """
    try:
        with open(path, "rb") as f:
            data = plistlib.load(f)
    except Exception as e:  # noqa: BLE001 — poškozený/neplatný plist, defenzivní
        log.warning("Plist load %s: %s", path, e)
        return []

    try:
        return build_plist_artifacts(data)
    except Exception as e:  # noqa: BLE001 — neočekávaný tvar dat
        log.warning("Plist extract %s: %s", path, e)
        return []
