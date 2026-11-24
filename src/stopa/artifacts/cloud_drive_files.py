"""ETAPA B vlna 8 — Cloud Drive soubory parser (Google Drive / OneDrive / Apple).

AXIOM ekvivalenty: ``CloudDriveFileArtifact`` + ``CloudDriveFileVersionArtifact``
+ ``CloudOneDriveFileArtifact`` + ``CloudOneDriveFileVersionArtifact`` +
``CloudAppleDriveArtifact``.

Podporovaný formát: **JSON export cloud úložiště** (warrant return / Takeout).
Parser je defenzivní — rozpozná více variant struktury::

    # Google Drive (pole souborů)
    [{"id": "...", "name": "doc.pdf", "sizeBytes": 1234,
      "md5Checksum": "...", "createdTime": "2026-01-01T00:00:00Z",
      "modifiedTime": "...", "owners": [{"emailAddress": "..."}]}]

    # OneDrive (value pole)
    {"value": [{"id": "...", "name": "doc.pdf", "size": 1234,
                "file": {"hashes": {...}}, "createdDateTime": "...",
                "lastModifiedDateTime": "..."}]}

    # Apple Drive / plochý export
    {"files": [{"fileName": "...", "fileSize": ..., "modifiedDate": ...}]}

   Jeden soubor = jeden artifact (``cloud_file``). Verze souboru (version)
   se rozbalí do ``details.versions``, pokud jsou v záznamu přítomny.
   Neznámé pole se ignoruje; provider se určí podle markerů.

Detekce: **name-based** (``drive``, ``onedrive``, ``apple_drive``, ``files.json``)
+ content check (JSON s file-like klíči).

Artifact type: ``cloud_file`` — jeden cloud soubor = jeden artifact.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_FILES_PER_FILE = 5_000


@dataclass
class CloudFileRecord:
    """Jeden záznam cloud souboru (provider-agnostický)."""

    name: str = ""
    size_bytes: int | None = None
    checksum: str | None = None
    owner: str = ""
    created_s: float | None = None
    modified_s: float | None = None
    provider: str = "unknown"  # google_drive | onedrive | apple_drive | unknown
    extra: dict[str, Any] = field(default_factory=dict)


def _iso_to_seconds(value: Any) -> float | None:
    """ISO 8601 / epoch s / ms → epoch sekundy (tolerantně)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        # heuristika: ms vs s
        if v > 1e12:
            v /= 1000.0
        return v if v > 0 else None
    text = str(value).strip()
    if not text:
        return None
    try:
        # epoch s / ms jako číslo v textu
        num = float(text)
        if num > 1e12:
            num /= 1000.0
        return num if num > 0 else None
    except ValueError:
        logger.debug("epoch číselný parse selhal pro %r → zkusím další formát", text[:40])
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _detect_provider(payload: Any, name: str) -> str:
    """Určení provideru podle markerů v payloadu / názvu souboru.

    Takeout ``Files.json`` je pole → klíče se sbírají i z prvních položek.
    """
    lower_name = name.lower()
    keys: set[str] = set()

    def collect(obj: Any) -> None:
        if isinstance(obj, dict):
            for k in obj:
                keys.add(str(k).lower())
        elif isinstance(obj, list):
            for item in obj[:5]:  # jen vzorek — velká pole nebrzdí detekci
                collect(item)

    collect(payload)
    text_keys = " ".join(keys)

    if "onedrive" in lower_name or "lastmodifieddatetime" in text_keys:
        return "onedrive"
    if "apple" in lower_name:
        return "apple_drive"
    if "sizebytes" in text_keys or "md5checksum" in text_keys:
        return "google_drive"
    if "drive" in lower_name:
        return "google_drive"
    return "unknown"


def _extract_file_list(payload: Any) -> list[dict[str, Any]]:
    """Vytáhne seznam souborových záznamů z libovolné podporované struktury."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("value", "files", "items", "results", "data"):
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
            if isinstance(val, dict):
                nested = _extract_file_list(val)
                if nested:
                    return nested
    return []


def parse_cloud_drive_files(data: bytes, name: str = "") -> list[CloudFileRecord]:
    """ČISTÝ parser — cloud drive JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez souborových záznamů.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    items = _extract_file_list(payload)
    if not items:
        raise TypeError("Nenalezeny souborové záznamy")

    provider = _detect_provider(payload, name)
    records: list[CloudFileRecord] = []
    for item in items[:MAX_FILES_PER_FILE]:
        rec_name = str(
            item.get("name") or item.get("fileName") or item.get("title") or ""
        ).strip()
        if not rec_name and "id" in item:
            rec_name = str(item["id"])

        size = item.get("sizeBytes", item.get("size", item.get("fileSize")))
        try:
            size_bytes = int(size) if size is not None else None
        except (ValueError, TypeError):
            size_bytes = None

        checksum = item.get("md5Checksum") or item.get("checksum")
        if isinstance(checksum, str):
            checksum = checksum.strip() or None
        else:
            checksum = None

        owner = ""
        owners = item.get("owners")
        if isinstance(owners, list) and owners:
            first = owners[0]
            if isinstance(first, dict):
                owner = str(first.get("emailAddress") or "").strip()

        created_s = _iso_to_seconds(item.get("createdTime", item.get("createdDateTime")))
        modified_s = _iso_to_seconds(
            item.get("modifiedTime", item.get("lastModifiedDateTime", item.get("modifiedDate")))
        )

        extra: dict[str, Any] = {}
        # verze souboru (Google Drive versions / OneDrive version)
        versions = item.get("versions") or item.get("versionHistory")
        if isinstance(versions, list):
            vlist = []
            for v in versions[:20]:
                if not isinstance(v, dict):
                    continue
                vlist.append(
                    {
                        "created": _iso_to_seconds(v.get("createdTime", v.get("createdDateTime"))),
                        "size": v.get("sizeBytes", v.get("size")),
                    }
                )
            if vlist:
                extra["versions"] = vlist

        records.append(
            CloudFileRecord(
                name=rec_name,
                size_bytes=size_bytes,
                checksum=checksum,
                owner=owner,
                created_s=created_s,
                modified_s=modified_s,
                provider=provider,
                extra=extra,
            )
        )

    return records


def is_cloud_drive_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce cloud drive exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("drive", "onedrive", "apple_drive")):
        return False
    # vyhnout se kolizi s drive_activity (vlna 5) — ten má vlastní detektor
    if "activity" in lower or "drive_activity" in lower:
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
        joined = head[:2048].lower()
        if not any(
            k in joined
            for k in (b"name", b"sizebytes", b"size", b"filename", b"createdtime", b"lastmodifieddatetime")
        ):
            return False
    return True


def build_cloud_file_artifacts(records: list[CloudFileRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (cloud_file)."""
    artifacts: list[Artifact] = []
    for r in records:
        label = r.name or "soubor"
        title = f"{r.provider}: {label}"

        details: dict[str, Any] = {"engine": "cloud_drive_files", "provider": r.provider}
        if r.size_bytes is not None:
            details["size_bytes"] = r.size_bytes
        if r.checksum:
            details["md5"] = r.checksum
        if r.owner:
            details["owner"] = r.owner
        details.update(r.extra)

        ts = None
        for candidate in (r.modified_s, r.created_s):
            if candidate is not None:
                from stopa.domain.times import from_unix

                try:
                    ts = from_unix(candidate)
                except ValueError:
                    ts = None
                break

        artifacts.append(
            Artifact(
                artifact_type="cloud_file",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.8 if (r.name and r.size_bytes is not None) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_cloud_drive_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — cloud drive JSON → cloud_file artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("CloudDrive %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_cloud_drive_files(data, name=path.name)
    except (ValueError, TypeError) as e:
        logger.debug("CloudDrive %s: %s", path, e)
        return []

    return build_cloud_file_artifacts(records)
