"""ETAPA B vlna 2 — Google Login/Sign-in History parser (lokální profil / Takeout).

AXIOM ekvivalent: ``GoogleLoginHistoryArtifact``
(``Magnet.Artifacts.Cloud.Google.WarrantReturn.GoogleLoginHistoryArtifact``).

Podporované formáty:
1. **JSON Takeout** (``sign-ins.json``, ``login_history.json``) — pole objektů::

       [{"time": {"timestamp": "1625097600", "displayTime": "..."},
         "deviceName": "Chrome on Windows",
         "ipAddress": "83.10.1.2",
         "location": "Prague, Czechia"}]

2. **Warrant return CSV** (``login_history.csv``, ``sign-ins.csv``) — sloupce
   ``Time,Timestamp,Device Name,IP Address,Location,...``.

Detekce: **name-based** (``sign-in``, ``login_history``, ``loginhistor``) + content check.

Artifact type: ``google_login`` — jedno přihlášení = jeden artifact.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_ENTRIES_PER_FILE = 5_000


@dataclass
class GoogleLoginEntry:
    """Jeden záznam Google Login/Sign-in History."""

    timestamp_s: int | None = None
    display_time: str = ""
    device_name: str = ""
    ip_address: str = ""
    location: str = ""


def _to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


def parse_login_history_json(data: bytes) -> list[GoogleLoginEntry]:
    """ČISTÝ parser — JSON Takeout formát → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne pole záznamů.
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    if not isinstance(payload, list):
        raise TypeError("Očekáváno JSON pole záznamů")

    entries: list[GoogleLoginEntry] = []
    for item in payload[:MAX_ENTRIES_PER_FILE]:
        if not isinstance(item, dict):
            continue
        time_obj = item.get("time") or {}
        ts_raw = time_obj.get("timestamp") if isinstance(time_obj, dict) else None
        display = str(time_obj.get("displayTime", "")) if isinstance(time_obj, dict) else ""

        entries.append(
            GoogleLoginEntry(
                timestamp_s=_to_int(ts_raw),
                display_time=display,
                device_name=str(item.get("deviceName") or item.get("device_name") or "").strip(),
                ip_address=str(item.get("ipAddress") or item.get("ip_address") or "").strip(),
                location=str(item.get("location") or "").strip(),
            )
        )

    return entries


def parse_login_history_csv(data: bytes) -> list[GoogleLoginEntry]:
    """ČISTÝ parser — warrant return CSV → záznamy.

    Sloupce (case-insensitive): Time/Timestamp, Device Name/DeviceName,
    IP Address/IPAddress, Location. Čas = epoch s/ms nebo ISO text.

    Raises:
        ValueError: Chybí sloupec pro čas i zařízením i IP (nejde o login history).
    """
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    fields = {f.lower().strip(): f for f in (reader.fieldnames or [])}

    ts_col = fields.get("timestamp", fields.get("time"))
    dev_col = fields.get("device name", fields.get("devicename", fields.get("device")))
    ip_col = fields.get("ip address", fields.get("ipaddress", fields.get("ip")))
    loc_col = fields.get("location")

    if not (ts_col or dev_col or ip_col):
        raise ValueError("Chybí sloupce Time/Device/IP")

    entries: list[GoogleLoginEntry] = []
    for row in reader:
        if len(entries) >= MAX_ENTRIES_PER_FILE:
            logger.warning("LoginHistory CSV: limit %d záznamů", MAX_ENTRIES_PER_FILE)
            break

        ts_s: int | None = None
        display = ""
        raw_ts = (row.get(ts_col) or "").strip() if ts_col else ""
        if raw_ts:
            digits = raw_ts.replace(".", "", 1).lstrip("-")
            if digits.isdigit():
                v = int(raw_ts)
                ts_s = v // 1000 if len(digits) >= 13 else v
            else:
                display = raw_ts

        entries.append(
            GoogleLoginEntry(
                timestamp_s=ts_s,
                display_time=display,
                device_name=(row.get(dev_col) or "").strip() if dev_col else "",
                ip_address=(row.get(ip_col) or "").strip() if ip_col else "",
                location=(row.get(loc_col) or "").strip() if loc_col else "",
            )
        )

    return entries


def is_login_history_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Google Login/Sign-in History exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("sign-in", "signin", "login_history", "loginhistor")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        markers = (b"devicename", b"ipaddress", b"timestamp")
        csv_markers = (b"device name", b"ip address", b"time,")
        if not any(m in h for m in markers) and not any(m in h for m in csv_markers):
            return False
    return True


def build_login_artifacts(entries: list[GoogleLoginEntry]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (google_login)."""
    artifacts: list[Artifact] = []
    for e in entries:
        parts = [p for p in (e.device_name, e.ip_address, e.location) if p]
        title = "Google login: " + ("; ".join(parts)[:100] if parts else "(bez detailů)")

        details: dict[str, Any] = {
            "engine": "google_takeout",
            "device_name": e.device_name,
            "ip_address": e.ip_address,
            "location": e.location,
        }
        if e.display_time:
            details["display_time"] = e.display_time

        ts = from_unix(e.timestamp_s) if e.timestamp_s is not None else None
        artifacts.append(
            Artifact(
                artifact_type="google_login",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.85 if (e.ip_address or e.device_name) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_login_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Google Login History → google_login artifacty.

    Chyby (poškozený soubor, IO) → log + prázdný výsledek, nikdy ne výjimka.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("LoginHistory %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    head = data[:2048].lstrip().lower()
    parser = parse_login_history_json if head.startswith(b"[") else parse_login_history_csv
    try:
        entries = parser(data)
    except (ValueError, TypeError) as e:
        logger.debug("LoginHistory %s: %s", path, e)
        return []

    return build_login_artifacts(entries)
