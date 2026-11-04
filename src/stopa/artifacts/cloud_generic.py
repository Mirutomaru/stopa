"""ETAPA B vlna 14 — Generic cloud metadata parser (cloud export / warrant return).

AXIOM ekvivalenty: ``CloudAccountsInfoArtifact`` + ``CloudAndroidBackupsArtifact``
+ ``CloudAzureVirtualMachineSnapshotArtifact`` + ``CloudConnectedAppsArtifact``
+ ``CloudPasswordsArtifact`` + ``CloudRecentDevicesArtifact`` +
``CloudTimelineArtifact`` (``Magnet.Artifacts.Cloud.*``) — účty, Android backupy,
Azure VM snapshoty, propojené aplikace, hesla, nedávná zařízení a timeline události.

Podporované formáty (defenzivní parsing, auto-detekce podtypu)::

    1. Accounts info::

        [{"email": "user@x.cz", "provider": "google",
          "displayName": "Jan Novák"}, ...]

    2. Android backups::

        [{"packageName": "com.whatsapp", "backupTime": "2025-01-15T09:00:00Z",
          "sizeBytes": 2048}, ...]

    3. Azure VM snapshot::

        [{"vmName": "prod-web-01", "snapshotId": "/subs/.../snap1",
          "createdTime": "2025-01-15T09:00:00Z", "sizeGb": 128}, ...]

    4. Connected apps::

        [{"appName": "Gmail", "provider": "google",
          "lastUsedTime": "2025-01-15T09:00:00Z"}, ...]

    5. Passwords::

        [{"service": "github.com", "username": "user",
          "password": "secret", "created": 1728136800}, ...]

    6. Recent devices::

        [{"deviceName": "Pixel 8", "lastSeenTime": "2025-01-15T09:00:00Z",
          "ipAddress": "1.2.3.4"}, ...]

    7. Timeline::

        [{"event": "login", "actor": "user@x.cz",
          "time": "2025-01-15T09:00:00Z", "details": "..."}, ...]

Jeden záznam = jeden artifact (podtyp → konkrétní ``artifact_type``). Neznámá
pole se ignorují.

Detekce: **name-based** — cloud marker + klíčová slova; v dispatchi pre-pass na
celé cestě PŘED basename chainem (generic basenames kolidují s ostatními
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
class CloudGenericRecord:
    """Jeden generic cloud záznam (podtyp + normalizovaná data)."""

    kind: str = ""  # accounts | android_backup | azure_vm | apps | passwords | devices | timeline
    name: str | None = None
    detail: str | None = None
    email: str | None = None
    provider: str | None = None
    package_name: str | None = None
    size_bytes: int | None = None
    vm_name: str | None = None
    snapshot_id: str | None = None
    size_gb: float | None = None
    app_name: str | None = None
    service: str | None = None
    username: str | None = None
    password: str | None = None
    device_name: str | None = None
    ip_address: str | None = None
    event: str | None = None
    actor: str | None = None
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


def _to_float(value: Any) -> float | None:
    """Tolerantní konverze na float."""
    try:
        num = float(value)
    except (ValueError, TypeError):
        return None
    return num


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
    """Určí generic cloud podtyp podle cesty/názvu + tvaru položky."""
    lower = name.lower()
    # explicitní hint z cesty (konkrétnější PŘED obecnějším; klíčová slova bez
    # podtržítek — skutečné exporty používají CamelCase)
    for marker, kind in (
        ("androidbackup", "android_backup"),
        ("azurevirtualmachine", "azure_vm"),
        ("accountsinfo", "accounts"),
        ("connectedapps", "apps"),
        ("passwords", "passwords"),
        ("recentdevices", "devices"),
        ("timeline", "timeline"),
    ):
        if marker in lower:
            return kind
    # fallback podle klíčů
    if any(k in item for k in ("vmName", "snapshotId")):
        return "azure_vm"
    if any(k in item for k in ("packageName",)) and _to_str(
        item.get("backupTime")
    ):
        return "android_backup"
    if any(k in item for k in ("service", "username")) and (
        _to_str(item.get("password")) or _to_str(item.get("created")) is not None
    ):
        return "passwords"
    if any(k in item for k in ("deviceName",)) and _to_str(
        item.get("lastSeenTime")
    ):
        return "devices"
    if any(k in item for k in ("appName",)) and _to_str(item.get("provider")):
        return "apps"
    if any(k in item for k in ("event", "actor")) and _to_str(
        item.get("time")
    ):
        return "timeline"
    if any(k in item for k in ("email", "provider")) and _to_str(
        item.get("displayName")
    ):
        return "accounts"
    return ""


def parse_cloud_generic(data: bytes, kind_hint: str = "") -> list[CloudGenericRecord]:
    """ČISTÝ parser — generic cloud JSON → záznamy.

    Args:
        data: Obsah souboru (JSON).
        kind_hint: Volitelný hint podtypu z cesty; prázdně = auto-detekce.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez generic cloud záznamů.
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[CloudGenericRecord] = []

    def add_accounts(item: dict[str, Any]) -> None:
        email = _first_str(
            item.get("email"),
            item.get("accountEmail"),
            item.get("accountName"),
            item.get("username"),
        )
        provider = _to_str(item.get("provider"))
        display = _to_str(item.get("displayName", item.get("name")))
        records.append(
            CloudGenericRecord(
                kind="accounts",
                name=display or email,
                email=email,
                provider=provider,
            )
        )

    def add_android_backup(item: dict[str, Any]) -> None:
        pkg = _to_str(item.get("packageName", item.get("package")))
        if not pkg:
            return
        records.append(
            CloudGenericRecord(
                kind="android_backup",
                name=pkg,
                package_name=pkg,
                size_bytes=_to_int(item.get("sizeBytes", item.get("size"))),
                created_s=_to_epoch(item.get("backupTime", item.get("time"))),
            )
        )

    def add_azure_vm(item: dict[str, Any]) -> None:
        vm = _to_str(item.get("vmName", item.get("name")))
        snap_id = _to_str(item.get("snapshotId", item.get("id")))
        records.append(
            CloudGenericRecord(
                kind="azure_vm",
                name=vm or (snap_id[:60] if snap_id else None),
                vm_name=vm,
                snapshot_id=snap_id,
                size_gb=_to_float(item.get("sizeGb", item.get("sizeGB"))),
                created_s=_to_epoch(item.get("createdTime", item.get("time"))),
            )
        )

    def add_apps(item: dict[str, Any]) -> None:
        app = _to_str(item.get("appName", item.get("name")))
        provider = _to_str(item.get("provider"))
        records.append(
            CloudGenericRecord(
                kind="apps",
                name=app,
                app_name=app,
                provider=provider,
                created_s=_to_epoch(item.get("lastUsedTime", item.get("time"))),
            )
        )

    def add_passwords(item: dict[str, Any]) -> None:
        service = _first_str(
            item.get("service"), item.get("url"), item.get("domain")
        )
        user = _to_str(item.get("username", item.get("user")) or "")
        pwd = _to_str(item.get("password", item.get("secret")))
        name = f"{service}:{user}" if (service and user) else (service or user)
        records.append(
            CloudGenericRecord(
                kind="passwords",
                name=name,
                service=service,
                username=user or None,
                password=pwd,
                created_s=_to_epoch(item.get("created", item.get("time"))),
            )
        )

    def add_devices(item: dict[str, Any]) -> None:
        device = _to_str(item.get("deviceName", item.get("name")))
        ip = _to_str(
            item.get("ipAddress", item.get("clientIp", item.get("sourceIPAddress")))
        )
        records.append(
            CloudGenericRecord(
                kind="devices",
                name=device,
                device_name=device,
                ip_address=ip,
                created_s=_to_epoch(item.get("lastSeenTime", item.get("time"))),
            )
        )

    def add_timeline(item: dict[str, Any]) -> None:
        event = _to_str(item.get("event", item.get("type")))
        actor = _first_str(
            item.get("actor"), item.get("user"), item.get("account")
        )
        detail = _to_str(item.get("details", item.get("description")))
        records.append(
            CloudGenericRecord(
                kind="timeline",
                name=event,
                event=event,
                actor=actor,
                detail=(detail[:200] if detail else None),
                created_s=_to_epoch(item.get("time", item.get("timestamp"))),
            )
        )

    handlers = {
        "accounts": add_accounts,
        "android_backup": add_android_backup,
        "azure_vm": add_azure_vm,
        "apps": add_apps,
        "passwords": add_passwords,
        "devices": add_devices,
        "timeline": add_timeline,
    }

    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("entries", "items", "accounts", "backups", "apps", "passwords", "devices", "events"):
            val = payload.get(key)
            if isinstance(val, list):
                items.extend(x for x in val if isinstance(x, dict))
        # plochý objekt — jeden záznam
        if not items and any(
            k in payload
            for k in (
                "email",
                "packageName",
                "vmName",
                "appName",
                "service",
                "deviceName",
                "event",
            )
        ):
            items = [payload]
    elif isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]

    hint_ok = kind_hint in handlers
    for item in items[:MAX_ITEMS_PER_FILE]:
        kind = (
            kind_hint
            if hint_ok
            else _detect_kind("", item)
        )
        handler = handlers.get(kind)
        if handler:
            handler(item)

    records = records[:MAX_ITEMS_PER_FILE]
    if not records:
        raise TypeError("Nenalezeny generic cloud záznamy")
    return records


def build_cloud_generic_artifacts(records: list[CloudGenericRecord]) -> list[Artifact]:
    """ČISTÁ funkce: z generic cloud záznamů vytvoří artifacty."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "cloud_generic", "kind": r.kind}

        ts = None
        if r.created_s is not None:
            try:
                ts = from_unix(r.created_s)
            except ValueError:
                ts = None

        if r.kind == "accounts":
            title = f"Cloud účet: {r.name or '(bez jména)'}"[:120]
            if r.email:
                details["email"] = r.email
            if r.provider:
                details["provider"] = r.provider
            artifacts.append(
                Artifact(
                    artifact_type="contact",
                    timestamp=None,
                    title=title,
                    details=details,
                    confidence=0.85 if (r.name and r.email) else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )

        elif r.kind == "android_backup":
            title = f"Android backup: {r.package_name or '(bez balíčku)'}"[:120]
            if r.size_bytes is not None:
                details["size_bytes"] = r.size_bytes
            artifacts.append(
                Artifact(
                    artifact_type="file_metadata",
                    timestamp=ts,
                    title=title,
                    details=details,
                    confidence=0.85 if (r.package_name and ts) else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )

        elif r.kind == "azure_vm":
            title = f"Azure VM snapshot: {r.vm_name or '(bez jména)'}"[:120]
            if r.snapshot_id:
                details["snapshot_id"] = r.snapshot_id[:200]
            if r.size_gb is not None:
                details["size_gb"] = r.size_gb
            artifacts.append(
                Artifact(
                    artifact_type="file_metadata",
                    timestamp=ts,
                    title=title,
                    details=details,
                    confidence=0.85 if (r.vm_name and ts) else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )

        elif r.kind == "apps":
            title = f"Propojená aplikace: {r.app_name or '(bez jména)'}"[:120]
            if r.provider:
                details["provider"] = r.provider
            artifacts.append(
                Artifact(
                    artifact_type="event_log_entry",
                    timestamp=ts,
                    title=title,
                    details=details,
                    confidence=0.85 if (r.app_name and ts) else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )

        elif r.kind == "passwords":
            title = f"Heslo: {r.name or '(bez služby)'}"[:120]
            if r.service:
                details["service"] = r.service
            if r.username:
                details["username"] = r.username
            # heslo do details (ne title — aby se netisklo v timeline)
            if r.password:
                details["password"] = r.password[:200]
            artifacts.append(
                Artifact(
                    artifact_type="credential",
                    timestamp=ts,
                    title=title,
                    details=details,
                    confidence=0.85 if (r.service and r.username) else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )

        elif r.kind == "devices":
            title = f"Nedávné zařízení: {r.device_name or '(bez jména)'}"[:120]
            if r.ip_address:
                details["ip_address"] = r.ip_address
            artifacts.append(
                Artifact(
                    artifact_type="event_log_entry",
                    timestamp=ts,
                    title=title,
                    details=details,
                    confidence=0.85 if (r.device_name and ts) else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )

        elif r.kind == "timeline":
            title = f"Cloud timeline: {r.event or '(bez události)'}"[:120]
            if r.actor:
                details["actor"] = r.actor
            if r.detail:
                details["detail"] = r.detail
            artifacts.append(
                Artifact(
                    artifact_type="event_log_entry",
                    timestamp=ts,
                    title=title,
                    details=details,
                    confidence=0.85 if (r.event and ts) else 0.6,
                    parser_version=PARSER_VERSION,
                )
            )

    return artifacts


def extract_cloud_generic_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — generic cloud JSON → artifacty (podtyp auto)."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("CloudGeneric %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    # podtyp hint z cesty (detektor už marker ověřil)
    lower = str(path).lower()
    hint = ""
    for marker, kind in (
        ("androidbackup", "android_backup"),
        ("azurevirtualmachine", "azure_vm"),
        ("accountsinfo", "accounts"),
        ("connectedapps", "apps"),
        ("passwords", "passwords"),
        ("recentdevices", "devices"),
        ("timeline", "timeline"),
    ):
        if marker in lower:
            hint = kind
            break

    try:
        records = parse_cloud_generic(data, kind_hint=hint)
    except (ValueError, TypeError) as e:
        logger.debug("CloudGeneric %s: %s", path.name, e)
        return []

    return build_cloud_generic_artifacts(records)


def is_cloud_generic_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce generic cloud exportu.

    Vyžaduje cloud marker + klíčové slovo (accounts/androidbackup/
    azurevirtualmachine/connectedapps/passwords/recentdevices/timeline) —
    generic ``timeline.json`` bez markery nepadne, aby se nekradly cizí
    soubory. Klíčová slova jsou bez podtržítek: skutečné exporty používají
    CamelCase (``ConnectedApps.json``, ``AndroidBackups.json``,
    ``AzureVirtualMachineSnapshots.json``).
    """
    lower = name.lower()
    if "cloud" not in lower:
        return False
    if not any(
        m in lower
        for m in (
            "accounts",
            "androidbackup",
            "azurevirtualmachine",
            "connectedapps",
            "passwords",
            "recentdevices",
            "timeline",
        )
    ):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
