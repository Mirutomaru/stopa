"""STOPA — Parser Sandbox kontrakt (ETAPA E vlna 1, STP-046).

Izolace artifact extraktorů od hlavního procesu pipeline: parser běží v
dceřiném procesu s timeoutem a limitem velikosti výsledku; výsledek se
marshalluje jako JSON. Poškozený vstupní soubor tak nesmí viset ani crashnout
celou pipeline (nález auditu STP-045: ``sqlite_carver`` visel >15 s na garbage
``db_size_pages`` = 1,7 mld. stránek v 920 B souboru).

Čistá logika (offline testovatelné):
- ``SandboxConfig`` — limity běhu (timeout, max_result_bytes)
- ``SandboxResult`` — výsledek jednoho sandboxovaného běhu
- ``validate_artifact_payload()`` — strukturální validace JSON payloadu
- ``build_worker_command()`` — argv dceřiného procesu
- ``failure_category()`` — klasifikace selhání (timeout/truncated/bad_payload/crash)

Tenký IO wrapper: ``run_extractor_sandboxed()`` (subprocess). Worker samotný
je modul ``stopa.sandbox_worker`` (entrypoint ``python -m stopa.sandbox_worker``).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field

# Výchozí limity — dostatečné pro reálné parsery (iCloud XLSX, registry hives),
# krátké proti neomezenému CPU spinu (audit: hang >15 s bez jakéhokoli limitu).
DEFAULT_TIMEOUT_S = 30.0
MAX_RESULT_BYTES_DEFAULT = 16 * 1024 * 1024  # 16 MiB JSON payloadu

# Kategorie selhání — stabilní řetězce pro audit log / parser_error artifact.
CATEGORY_TIMEOUT = "timeout"
CATEGORY_TRUNCATED = "truncated"
CATEGORY_BAD_PAYLOAD = "bad_payload"
CATEGORY_CRASH = "crash"


class SandboxPayloadError(ValueError):
    """JSON payload z workeru nesplňuje kontrakt (ne array / chybí artifact_type)."""


@dataclass(frozen=True)
class SandboxConfig:
    """Limity jednoho sandboxovaného běhu parseru.

    Args:
        timeout_s: maximální doba běhu dceřiného procesu (s); >0.
        max_result_bytes: maximální velikost JSON payloadu na stdout; >=1.
    """

    timeout_s: float = DEFAULT_TIMEOUT_S
    max_result_bytes: int = MAX_RESULT_BYTES_DEFAULT

    def __post_init__(self) -> None:
        if self.timeout_s <= 0:
            raise ValueError(f"timeout_s musí být > 0, dostalo {self.timeout_s!r}")
        if self.max_result_bytes < 1:
            raise ValueError(
                f"max_result_bytes musí být >= 1, dostalo {self.max_result_bytes!r}"
            )


@dataclass(frozen=True)
class SandboxResult:
    """Výsledek jednoho sandboxovaného běhu parseru.

    Attributes:
        ok: True = parser doběhl a payload prošel validací.
        artifacts: normalizované artifact dicty (prázdné tuple při selhání).
        error: lidsky čitelná chyba (None při úspěchu).
        category: kategorie selhání (None při úspěchu) — timeout | truncated |
            bad_payload | crash.
    """

    ok: bool
    artifacts: tuple[dict, ...] = field(default_factory=tuple)
    error: str | None = None
    category: str | None = None


def validate_artifact_payload(payload: object) -> list[dict]:
    """Strukturální validace JSON payloadu z workeru (čistá funkce).

    Kontrakt: JSON array objektů, každý s neprázdným textovým ``artifact_type``.
    Plnou Pydantic validaci (Artifact.model_validate) dělá konzument — tady je
    jen levná brána před drahým parsem.

    Raises:
        SandboxPayloadError: payload není array / položka není objekt /
            chybí nebo je prázdné ``artifact_type``.
    """
    if not isinstance(payload, list):
        raise SandboxPayloadError(
            f"payload musí být JSON array, dostalo {type(payload).__name__}"
        )
    out: list[dict] = []
    for i, item in enumerate(payload):
        if not isinstance(item, dict):
            raise SandboxPayloadError(f"položka {i} není objekt")
        art_type = item.get("artifact_type")
        if not isinstance(art_type, str) or not art_type:
            raise SandboxPayloadError(f"položka {i}: artifact_type chybí nebo je prázdné")
        out.append(item)
    return out


def build_worker_command(
    module_name: str, func_name: str, path: object, python: str | None = None
) -> list[str]:
    """argv dceřiného procesu (čistá funkce — ``python`` parametr pro testy)."""
    return [
        python or sys.executable,
        "-m",
        "stopa.sandbox_worker",
        module_name,
        func_name,
        str(path),
    ]


def failure_category(
    timed_out: bool, truncated: bool, payload_error: bool, returncode: int | None
) -> str:
    """Klasifikace selhání podle priority (čistá funkce).

    Priorita: timeout > truncated > bad_payload > crash. ``returncode=None``
    bez timeoutu = proces zabit signálem → crash.
    """
    if timed_out:
        return CATEGORY_TIMEOUT
    if truncated:
        return CATEGORY_TRUNCATED
    if payload_error:
        return CATEGORY_BAD_PAYLOAD
    return CATEGORY_CRASH


def sandbox_available() -> bool:
    """Backend detekce: worker modul je importovatelný (čistá funkce)."""
    return importlib.util.find_spec("stopa.sandbox_worker") is not None


def run_extractor_sandboxed(
    module_name: str,
    func_name: str,
    path: object,
    config: SandboxConfig | None = None,
    env_extra: dict[str, str] | None = None,
) -> SandboxResult:
    """Spustí jeden extraktor v izolovaném dceřiném procesu (tenký IO wrapper).

    Args:
        module_name: modul s extraktorem (např. ``stopa.artifacts.sqlite_recover``).
        func_name: jméno funkce vracející ``list[Artifact]`` pro ``Path(path)``.
        path: vstupní soubor parseru.
        config: limity; default ``SandboxConfig()`` (30 s / 16 MiB).
        env_extra: dodatečné proměnné prostředí pro dceřiný proces.

    Returns:
        SandboxResult — nikdy ne hází výjimku (všechna selhání → category).
    """
    cfg = config or SandboxConfig()
    cmd = build_worker_command(module_name, func_name, path)
    env = dict(os.environ)
    # Worker aplikuje RLIMIT_CPU backstop (POSIX) — i kdyby timeout selhal.
    env["STOPA_SANDBOX_TIMEOUT"] = str(cfg.timeout_s)
    if env_extra:
        env.update(env_extra)

    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=cfg.timeout_s, env=env, check=False
        )  # exit code je součástí kontraktu (klasifikace níže)
    except subprocess.TimeoutExpired:
        return SandboxResult(
            ok=False,
            category=CATEGORY_TIMEOUT,
            error=f"parser přesáhl timeout {cfg.timeout_s:g} s",
        )

    stdout_b = proc.stdout or b""
    truncated = len(stdout_b) > cfg.max_result_bytes
    if truncated:
        return SandboxResult(
            ok=False,
            category=CATEGORY_TRUNCATED,
            error=(
                f"payload {len(stdout_b)} B přesáhl limit "
                f"{cfg.max_result_bytes} B"
            ),
        )

    items: list[dict] = []
    if proc.returncode != 0:
        err_tail = (proc.stderr or b"")[-512:].decode("utf-8", "replace").strip()
        return SandboxResult(
            ok=False,
            category=CATEGORY_CRASH,
            error=f"dceřiný proces ukončen s kódem {proc.returncode}: {err_tail}",
        )
    try:
        payload = json.loads(stdout_b.decode("utf-8"))
        items = validate_artifact_payload(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, SandboxPayloadError) as e:
        return SandboxResult(
            ok=False, category=CATEGORY_BAD_PAYLOAD, error=f"platný JSON, ale {e}"
        )
    return SandboxResult(ok=True, artifacts=tuple(items))
