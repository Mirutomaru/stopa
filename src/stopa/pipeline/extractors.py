"""Extrakce artefaktů — head signatur, sandbox běh extraktorů, sqlite/registry.

P1-4 vlna D: vyčleněno z monolitu ``pipeline.py``; zde žijí i konstanty
SIGNATURE_HEAD_BYTES a SANDBOX_* (jediný spotřebitel).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from stopa.artifacts.registry_extract import extract_registry_artifacts
from stopa.artifacts.sqlite_extract import extract_sqlite_artifacts
from stopa.artifacts.sqlite_recover import recover_deleted_rows
from stopa.artifacts.win_amcache import extract_amcache_artifacts
from stopa.artifacts.win_clipboard import extract_clipboard_artifacts
from stopa.artifacts.win_lsa import extract_lsa_artifacts
from stopa.artifacts.win_shimcache import extract_shimcache_artifacts
from stopa.artifacts.win_sids import extract_sid_artifacts
from stopa.artifacts.win_userassist import extract_userassist_artifacts
from stopa.domain.sandbox import (
    CATEGORY_BAD_PAYLOAD,
    CATEGORY_CRASH,
    SandboxConfig,
    SandboxResult,
    run_extractor_sandboxed,
    sandbox_available,
)
from stopa.models import Artifact

log = logging.getLogger("stopa.pipeline")

SIGNATURE_HEAD_BYTES = 65536  # stačí pro všechny signatury v hlavičce


SANDBOX_ENABLED = os.environ.get("STOPA_SANDBOX", "1") != "0"


SANDBOX_CONFIG = SandboxConfig()  # defaultní limity (30 s / 16 MiB) z domain/sandbox.py


def _extract_sqlite_all(path: Path) -> list[Artifact]:
    """SQLite — aktivní řádky (schema matchery) + carving smazaných (.db + .wal).

    Obě cesty jsou nezávislé; jedna selže → log + prázdný výsledek, druhá běží dál.
    """
    arts = extract_sqlite_artifacts(path)
    try:
        arts.extend(recover_deleted_rows(path))
    except Exception as e:  # noqa: BLE001 — carving je bonus, nesmí potopit extrakci
        log.warning("SQLite recover %s: %s", path, e)
    return arts


def _extract_registry_all(path: Path) -> list[Artifact]:
    """Registry hive (regf) — generic + Amcache + ShimCache + Clipboard + SID + UserAssist.

    Všechny extraktory sdílejí `regf` magic → jeden kombinovaný dispatch
    (pattern jako `_extract_sqlite_all`). Každá cesta je nezávislá: Amcache
    běží jen na Amcache.hve, ShimCache jen na SYSTEM hive; bez příslušného
    klíče vrátí prázdný výsledek. ETAPA B vlna 1: + Clipboard (NTUSER.DAT)
    a SID extrakce (SAM/SECURITY/ProfileList). ETAPA B vlna 4: + UserAssist MRU
    (NTUSER.DAT — spuštěné aplikace / otevřené dokumenty).
    """
    arts = extract_registry_artifacts(path)
    try:
        arts.extend(extract_amcache_artifacts(path))
    except Exception as e:  # noqa: BLE001 — Amcache je bonus, nesmí potopit extrakci
        log.warning("Amcache %s: %s", path, e)
    try:
        arts.extend(extract_shimcache_artifacts(path))
    except Exception as e:  # noqa: BLE001 — ShimCache je bonus, nesmí potopit extrakci
        log.warning("ShimCache %s: %s", path, e)
    try:
        arts.extend(extract_clipboard_artifacts(path))
    except Exception as e:  # noqa: BLE001 — Clipboard je bonus (ETAPA B vlna 1)
        log.warning("Clipboard %s: %s", path, e)
    try:
        arts.extend(extract_sid_artifacts(path))
    except Exception as e:  # noqa: BLE001 — SID je bonus (ETAPA B vlna 1)
        log.warning("SID %s: %s", path, e)
    try:
        arts.extend(extract_lsa_artifacts(path))
    except Exception as e:  # noqa: BLE001 — LSA credential cache je bonus (vlna 15)
        log.warning("LSA %s: %s", path, e)
    try:
        arts.extend(extract_userassist_artifacts(path))
    except Exception as e:  # noqa: BLE001 — UserAssist je bonus (ETAPA B vlna 4)
        log.warning("UserAssist %s: %s", path, e)
    return arts


def _parser_error_artifact(
    fn: Callable[[Path], list[Artifact]], ver: str | None, res: SandboxResult
) -> Artifact:
    """Selhání parseru → ``parser_error`` artifact (ETAPA E vlna 2, STP-047).

    Pipeline nepadne — selhání je záznam s kategorií z ``SandboxResult``
    (timeout | truncated | bad_payload | crash) pro audit log.
    """
    category = res.category or CATEGORY_CRASH
    return Artifact(
        artifact_type="parser_error",
        title=f"parser selhal ({category})",
        details={
            "category": category,
            "error": res.error or "",
            "parser": f"{fn.__module__}.{fn.__name__}",
        },
        parser_version=ver,
    )


def _run_extractor(
    fn: Callable[[Path], list[Artifact]], path: Path, ver: str | None
) -> list[Artifact]:
    """Jeden extraktor — přes sandbox subprocess (default) nebo přímo.

    ETAPA E vlna 2 (STP-047): poškozený vstupní soubor nesmí viset ani
    crashnout celou pipeline. Sandbox běží parser v dceřiném procesu s
    timeoutem; selhání → ``parser_error`` artifact s kategorií z
    ``SandboxResult``. Fallback (sandbox vypnutý / worker nedostupný) =
    přímé volání, původní chování.
    """
    if SANDBOX_ENABLED and sandbox_available():
        res = run_extractor_sandboxed(fn.__module__, fn.__name__, path, SANDBOX_CONFIG)
        if res.ok:
            try:
                return [Artifact.model_validate(d) for d in res.artifacts]
            except ValidationError as e:  # payload prošel strukturou, ale ne modelem
                log.warning(
                    "sandbox parser %s.%s — model validace selhala: %s",
                    fn.__module__,
                    fn.__name__,
                    e,
                )
                return [
                    _parser_error_artifact(
                        fn,
                        ver,
                        SandboxResult(ok=False, category=CATEGORY_BAD_PAYLOAD, error=str(e)),
                    )
                ]
        log.warning(
            "sandbox parser %s.%s selhal (%s): %s",
            fn.__module__,
            fn.__name__,
            res.category,
            res.error,
        )
        return [_parser_error_artifact(fn, ver, res)]
    # fallback — přímé volání (STOPA_SANDBOX=0 nebo worker modul chybí)
    return fn(path)


def _read_head(path: Path) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read(SIGNATURE_HEAD_BYTES)
    except OSError as e:
        log.warning("signatura — nelze číst %s: %s", path, e)
        return b""
