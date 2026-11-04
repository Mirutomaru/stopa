"""ETAPA B vlna 14 — Google 2025 Warrant Return parser (cloud export / warrant return).

AXIOM ekvivalenty: ``GoogleAccessLogDevices2025Artifact`` +
``GoogleAccountTargetAssociation2025Artifact`` + ``GoogleCalls2025Artifact``
(``Magnet.Artifacts.Google.*2025*``) — nová generace Google WR exportů (2025):
přístupová loga zařízení, asociace účtu s cílem a telefonní hovory.

Podporované formáty (defenzivní parsing, auto-detekce podtypu)::

    1. Access log devices::

        [{"deviceName": "Pixel 8", "ipAddress": "1.2.3.4",
          "accessTime": "2025-01-15T09:00:00Z", "app": "Gmail"}, ...]

    2. Account target association::

        [{"accountEmail": "user@gmail.com", "targetId": "tgt_123",
          "associationType": "owner", "createdTime": "2025-01-15T09:00:00Z"}, ...]

    3. Calls::

        [{"callerNumber": "+420...", "calleeNumber": "+420...",
          "startTime": "2025-01-15T09:00:00Z", "durationSeconds": 120,
          "direction": "outgoing"}, ...]

Jeden záznam = jeden artifact (podtyp → konkrétní ``artifact_type``:
event_log_entry / contact / call_record). Neznámá pole se ignorují.

Detekce: **name-based** — google marker + klíčová slova; v dispatchi pre-pass
na celé cestě PŘED basename chainem (generic basenames kolidují s ostatními
detektory).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_ITEMS_PER_FILE = 5_000


@dataclass
class Google2025Record:
    """Jeden Google 2025 WR záznam (podtyp + normalizovaná data)."""

    kind: str = ""  # access_log | target_assoc | call
    name: str | None = None
    detail: str | None = None
    ip_address: str | None = None
    app: str | None = None
    account_email: str | None = None
    target_id: str | None = None
    association_type: str | None = None
    caller_number: str | None = None
    callee_number: str | None = None
    direction: str | None = None
    duration_s: int | None = None
    created_s: float | None = None


def _to_str(value: Any) -> str | None:
    """Tolerantní konverze na non-empty string."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_str(*values: Any) -> str | None:
    """První non-empty string z řetězce kandidátů."""
    for v in values:
        s = _to_str(v)
        if s:
            return s
    return None


def _to_int(value: Any) -> int | None:
    """Tolerantní konverze na nezáporné celé číslo."""
    try:
        num = int(float(value))
    except (ValueError, TypeError):
        return None
    return num if num >= 0 else None


def _to_epoch(value: Any) -> float | None:
    """Tolerantní konverze času na epoch sekundy.

    Podporuje: int/float (sekundy i milisekundy), ISO 8601 stringy
    (s ``Z`` i offsetem). Neznámé tvary → None.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (ValueError, TypeError):
        text = _to_str(value)
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return float(dt.timestamp())
    # milisekundy — heuristika: epoch > 1e12 už jsou ms (rok ~33658)
    if abs(num) >= 10**12:
        num /= 1000.0
    return num if num > 0 else None


def _detect_kind(name: str, item: dict[str, Any]) -> str:
    """Určí Google 2025 podtyp podle cesty/názvu + tvaru položky.

    Klíčová slova jsou bez podtržítek — skutečné exporty používají CamelCase
    (``GoogleAccessLogDevices2025.json``, ``AccountTargetAssociation2025.json``).
    """
    lower = name.lower()
    # explicitní hint z cesty
    for marker, kind in (
        ("accesslog", "access_log"),
        ("targetassoc", "target_assoc"),
        ("call", "call"),
    ):
        if marker in lower:
            return kind
    # fallback podle klíčů
    if any(k in item for k in ("deviceName", "ipAddress")) and _to_str(
        item.get("accessTime")
    ):
        return "access_log"
    if any(k in item for k in ("targetId", "associationType")):
        return "target_assoc"
    # hovory: explicitní pole NEBO from/to + čas (bez kolize s access log)
    if any(k in item for k in ("callerNumber", "calleeNumber", "durationSeconds")):
        return "call"
    if (
        _to_str(item.get("from")) is not None
        and _to_str(item.get("to")) is not None
        and _to_str(item.get("startTime", item.get("time"))) is not None
    ):
        return "call"
    return ""


def parse_google_2025_wr(data: bytes, kind_hint: str = "") -> list[Google2025Record]:
    """ČISTÝ parser — Google 2025 WR JSON → záznamy.

    Args:
        data: Obsah souboru (JSON).
        kind_hint: Volitelný hint podtypu z cesty; prázdně = auto-detekce.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez Google 2025 WR záznamů.
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[Google2025Record] = []

    def add_access_log(item: dict[str, Any]) -> None:
        device = _to_str(item.get("deviceName", item.get("device")) or "")
        app = _to_str(item.get("app", item.get("application")))
        ip = _to_str(
            item.get("ipAddress", item.get("clientIp", item.get("sourceIPAddress")))
        )
        name = device or app or None
        detail_parts = [x for x in (device, app) if x]
        records.append(
            Google2025Record(
                kind="access_log",
                name=name,
                ip_address=ip,
                app=app,
                detail=(" / ".join(detail_parts)[:120] or None),
                created_s=_to_epoch(item.get("accessTime", item.get("time"))),
            )
        )

    def add_target_assoc(item: dict[str, Any]) -> None:
        email = _first_str(
            item.get("accountEmail"), item.get("email"), item.get("account")
        )
        target_id = _to_str(item.get("targetId", item.get("id")))
        assoc_type = _to_str(item.get("associationType", item.get("type")))
        records.append(
            Google2025Record(
                kind="target_assoc",
                name=email or target_id,
                account_email=email,
                target_id=target_id,
                association_type=assoc_type,
                created_s=_to_epoch(item.get("createdTime", item.get("time"))),
            )
        )

    def add_call(item: dict[str, Any]) -> None:
        caller = _first_str(
            item.get("callerNumber"), item.get("from"), item.get("source")
        )
        callee = _first_str(
            item.get("calleeNumber"), item.get("to"), item.get("destination")
        )
        direction = (_to_str(item.get("direction")) or "").lower() or None
        duration = _to_int(item.get("durationSeconds", item.get("duration")))
        name = f"{caller or '?'} → {callee or '?'}"
        records.append(
            Google2025Record(
                kind="call",
                name=name,
                caller_number=caller,
                callee_number=callee,
                direction=direction,
                duration_s=duration,
                created_s=_to_epoch(item.get("startTime", item.get("time"))),
            )
        )

    handlers = {
        "access_log": add_access_log,
        "target_assoc": add_target_assoc,
        "call": add_call,
    }

    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("entries", "items", "logs", "calls", "associations"):
            val = payload.get(key)
            if isinstance(val, list):
                items.extend(x for x in val if isinstance(x, dict))
        # plochý objekt — jeden záznam
        if not items and any(
            k in payload
            for k in (
                "deviceName",
                "targetId",
                "callerNumber",
            )
        ):
            items = [payload]
    elif isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]

    for item in items[:MAX_ITEMS_PER_FILE]:
        kind = (
            kind_hint
            if kind_hint in handlers
            else _detect_kind("", item)
        )
        handler = handlers.get(kind)
        if handler:
            handler(item)

    records = records[:MAX_ITEMS_PER_FILE]
    if not records:
        raise TypeError("Nenalezeny Google 2025 WR záznamy")
    return records


def build_google_2025_artifacts(records: list[Google2025Record]) -> list[Artifact]:
    """ČISTÁ funkce: z Google 2025 WR záznamů vytvoří artifacty."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "google_2025_wr", "kind": r.kind}

        ts = None
        if r.created_s is not None:
            try:
                ts = from_unix(r.created_s)
            except ValueError:
                ts = None

        if r.kind == "access_log":
            title = f"Google přístup (zařízení): {r.name or '(bez jména)'}"[:120]
            if r.ip_address:
                details["ip_address"] = r.ip_address
            if r.app:
                details["app"] = r.app
            artifacts.append(
                Artifact(
                    artifact_type="event_log_entry",
                    timestamp=ts,
                    title=title,
                    details=details,
                    confidence=0.85 if (r.name and ts) else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )

        elif r.kind == "target_assoc":
            title = f"Google účet→cíl: {r.account_email or r.target_id or '?'}"[:120]
            if r.target_id:
                details["target_id"] = r.target_id
            if r.association_type:
                details["association_type"] = r.association_type
            artifacts.append(
                Artifact(
                    artifact_type="contact",
                    timestamp=ts,
                    title=title,
                    details=details,
                    confidence=0.85 if (r.account_email and r.target_id) else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )

        elif r.kind == "call":
            title = f"Google hovor: {r.name}"[:120]
            if r.caller_number:
                details["caller"] = r.caller_number
            if r.callee_number:
                details["callee"] = r.callee_number
            if r.direction:
                details["direction"] = r.direction
            if r.duration_s is not None:
                details["duration_seconds"] = r.duration_s
            artifacts.append(
                Artifact(
                    artifact_type="call_record",
                    timestamp=ts,
                    title=title,
                    details=details,
                    confidence=0.85 if (r.caller_number and ts) else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )

    return artifacts


def extract_google_2025_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Google 2025 WR JSON → artifacty (podtyp auto)."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("Google2025 %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    # podtyp hint z cesty (detektor už marker ověřil; klíčová slova bez
    # podtržítek — skutečné exporty používají CamelCase)
    lower = str(path).lower()
    hint = ""
    for marker, kind in (
        ("accesslog", "access_log"),
        ("targetassoc", "target_assoc"),
        ("call", "call"),
    ):
        if marker in lower:
            hint = kind
            break

    try:
        records = parse_google_2025_wr(data, kind_hint=hint)
    except (ValueError, TypeError) as e:
        logger.debug("Google2025 %s: %s", path.name, e)
        return []

    return build_google_2025_artifacts(records)


def is_google_2025_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Google 2025 WR exportu.

    Vyžaduje google marker + klíčové slovo (accesslog/targetassoc/call) —
    generic ``calls.json`` bez markery nepadne, aby se nekradly cizí soubory.
    Klíčová slova jsou bez podtržítek: skutečné exporty používají CamelCase
    (``GoogleAccessLogDevices2025.json``, ``AccountTargetAssociation2025.json``).
    ``accesslog``/``targetassoc`` jsou samy o sobě dostatečně specifické;
    obecné ``call`` vyžaduje google marker v cestě.
    """
    lower = name.lower()
    if any(m in lower for m in ("accesslog", "targetassoc")) or "google" in lower and "call" in lower:
        matched = True
    else:
        matched = False
    if not matched:
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
