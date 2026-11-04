"""ETAPA B vlna 9 — Memory API hooks / callbacks parser (live forensics / paměťový dump).

AXIOM ekvivalent: ``ApiHooksArtifact`` + ``CallbacksArtifact`` +
``ExecutiveObjectCallbacksArtifact`` (``Magnet.Artifacts.Memory.Artifacts.*``) —
zaregistrované hooky a callback funkce v paměti.

Podporovaný formát: **JSON export seznamu hooků/callbacků** (výstup memory
scanneru / warrant return)::

    [{"pid": 1234, "processName": "chrome.exe", "apiFunction": "NtReadFile",
      "callbackAddress": "0x7ff9a1b2c000", "module": "C:\\Windows\\System32\\ntdll.dll",
      "hookType": "inline"}]

   nebo pod klíčem ``hooks``/``callbacks``/``value``. Jeden hook/callback = jeden
   artifact (``mem_hook``). Adresy se normalizují na hex string; neznámá pole se
   ignoruje.

Detekce: **name-based** (``api_hooks``, ``apishot``, ``callbacks``,
``executive_callbacks``, ``mem_hook``) + content check (JSON s hook-like klíči —
callbackAddress/apiFunction). V dispatchi PŘED netstatem a ostatními memory
parsery (specifická klíčová slova, žádná kolize).

Artifact type: ``mem_hook`` — jeden hook/callback = jeden artifact.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_HOOKS_PER_FILE = 5_000


@dataclass
class MemHookRecord:
    """Jeden API hook / callback z paměťového dumpu."""

    pid: int | None = None
    process_name: str | None = None
    api_function: str | None = None
    callback_address: str | None = None
    module: str | None = None
    hook_type: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _normalize_address(value: Any) -> str | None:
    """Normalizace adresy (int / hex string / decimal string) → hex string."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return f"0x{value:x}"
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.lower().startswith("0x"):
            return f"0x{int(text, 16):x}"
        return f"0x{int(text, 10):x}"
    except ValueError:
        # nečíslicová adresa — ponechat jako text (defenzivně)
        return text


def _to_int(value: Any) -> int | None:
    """Tolerantní konverze na int (int / numeric string)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _extract_hook_list(payload: Any) -> list[dict[str, Any]]:
    """Vytáhne seznam hooků/callbacků (pole nebo pod klíčem)."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("hooks", "callbacks", "value", "items", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def parse_mem_hooks(data: bytes) -> list[MemHookRecord]:
    """ČISTÝ parser — memory hooks/callbacks JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez hooků/callbacků.
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    items = _extract_hook_list(payload)
    if not items:
        raise TypeError("Nenalezeny hooky/callbacky")

    records: list[MemHookRecord] = []
    for item in items[:MAX_HOOKS_PER_FILE]:
        api_function = item.get("apiFunction", item.get("function")) \
            or item.get("callbackName")
        callback_address = _normalize_address(
            item.get("callbackAddress", item.get("address"))
        )
        if not api_function and callback_address is None:
            continue

        process_name = item.get("processName") or item.get("process_name") \
            or item.get("name")
        module = item.get("module") or item.get("moduleName")
        hook_type = item.get("hookType", item.get("type"))
        hook_type = str(hook_type).strip() or None if hook_type is not None else None

        extra: dict[str, Any] = {}
        for key in ("originalAddress", "trampoline"):
            val = item.get(key)
            if isinstance(val, (str, int)) and str(val).strip():
                extra[key.lower()] = _normalize_address(val) or str(val).strip()

        records.append(
            MemHookRecord(
                pid=_to_int(item.get("pid", item.get("Pid"))),
                process_name=str(process_name).strip() or None if process_name is not None else None,
                api_function=str(api_function).strip() if api_function is not None else None,
                callback_address=callback_address,
                module=str(module).strip() if module is not None else None,
                hook_type=hook_type,
                extra=extra,
            )
        )

    return records


def is_mem_hooks_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce memory hooks/callbacks exportu."""
    lower = name.lower()
    if not any(k in lower for k in (
        "api_hooks", "apishot", "callbacks", "executive_callbacks", "mem_hook",
    )):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
        joined = head[:2048].lower()
        if not any(k in joined for k in (b'"callbackaddress"', b'"apifunction"', b'"function"')):
            return False
    return True


def build_hook_artifacts(records: list[MemHookRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (mem_hook)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "mem_hooks"}
        if r.pid is not None:
            details["pid"] = r.pid
        if r.process_name:
            details["process_name"] = r.process_name
        if r.api_function:
            details["api_function"] = r.api_function
        if r.callback_address:
            details["callback_address"] = r.callback_address
        if r.module:
            details["module"] = r.module[:300]
        if r.hook_type:
            details["hook_type"] = r.hook_type
        details.update(r.extra)

        artifacts.append(
            Artifact(
                artifact_type="mem_hook",
                timestamp=None,  # snapshot paměti bez času
                title=f"Hook: {r.api_function or '?'} → {r.callback_address or '?'}"[:120],
                details=details,
                confidence=0.8 if (r.api_function and r.callback_address) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_mem_hook_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — memory hooks/callbacks JSON → mem_hook artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("MemHooks %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_mem_hooks(data)
    except (ValueError, TypeError) as e:
        logger.debug("MemHooks %s: %s", path, e)
        return []

    return build_hook_artifacts(records)
