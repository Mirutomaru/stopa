"""ETAPA B vlna 12 — Amazon EC2/S3 parser (cloud export / warrant return).

AXIOM ekvivalenty: ``CloudAmazonEC2InstanceArtifact``,
``CloudAmazonS3FilesArtifact``
(``Magnet.Artifacts.Cloud.Amazon.*``) — instancí EC2 a souborů S3 z AWS
exportu/warrant returnu.

Podporovaný formát: **JSON export** s auto-detekcí (defenzivní)::

    Instance → ``cloud_instance``::

        [{"instances": [{"instanceId": "i-0abc123", "state": "running",
          "privateIpAddresses": ["10.0.0.5"], "publicIpAddress": "1.2.3.4",
          "launchTime": "2024-10-03T12:00:00Z"}]}]

    S3 soubory → ``cloud_file``::

        {"buckets": [{"name": "corp-data", "objects": [
          {"key": "docs/smlouva.pdf", "size": 1024,
           "lastModified": "2024-10-03T12:00:00Z"}]}]}

Jeden záznam = jeden artifact (``details.engine='amazon_ec2_s3'``,
``mimetype='aws:ec2'|'aws:s3'``). Neznámá pole se ignoruje.

Detekce: **name-based** — Amazon/EC2/S3 marker v názvu/cestě; v dispatchi
pre-pass na celé cestě PŘED basename chainem (generic basenames
``instances.json`` / ``files.json`` kolidují s ostatními detektory).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_ITEMS_PER_FILE = 5_000


@dataclass
class Ec2InstanceRecord:
    """Jedna EC2 instance."""

    instance_id: str | None = None
    state: str | None = None
    private_ips: list[str] = field(default_factory=list)
    public_ip: str | None = None
    launch_s: float | None = None


@dataclass
class S3ObjectRecord:
    """Jeden S3 objekt."""

    bucket: str | None = None
    key: str | None = None
    size_bytes: int | None = None
    modified_s: float | None = None


def _to_str(value: Any) -> str | None:
    """Tolerantní konverze na non-empty string."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_list(value: Any) -> list[Any]:
    """Normalizuje pole / scalar / None na list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _to_int(value: Any) -> int | None:
    """Tolerantní konverze na non-negative int."""
    try:
        num = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
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


def parse_ec2_instances(data: bytes) -> list[Ec2InstanceRecord]:
    """ČISTÝ parser — EC2 instances JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez instancí.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[Ec2InstanceRecord] = []

    def add(item: dict[str, Any]) -> None:
        instance_id = _to_str(
            item.get("instanceId", item.get("InstanceId", item.get("id")))
        )
        state = _to_str(item.get("state", item.get("status")))
        private_ips: list[str] = []
        for raw in _as_list(
            item.get("privateIpAddresses", item.get("privateIpAddress"))
        ):
            if isinstance(raw, dict):
                ip = _to_str(raw.get("ipAddress", raw.get("privateIpAddress")))
            else:
                ip = _to_str(raw)
            if ip:
                private_ips.append(ip)
        public_ip = _to_str(
            item.get("publicIpAddress", item.get("publicIp"))
        )
        launch_s = _to_epoch(
            item.get("launchTime", item.get("creationDate", item.get("startTime")))
        )
        if not instance_id and not private_ips and not public_ip:
            return
        records.append(
            Ec2InstanceRecord(
                instance_id=instance_id,
                state=state,
                private_ips=private_ips,
                public_ip=public_ip,
                launch_s=launch_s,
            )
        )

    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("instances", "value", "items", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                items = [x for x in val if isinstance(x, dict)]
                break
    elif isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]

    for item in items[:MAX_ITEMS_PER_FILE]:
        add(item)

    records = records[:MAX_ITEMS_PER_FILE]
    if not records:
        raise TypeError("Nenalezeny EC2 instance")
    return records


def parse_s3_objects(data: bytes) -> list[S3ObjectRecord]:
    """ČISTÝ parser — S3 objects JSON → záznamy.

    Podporuje bucket-based formát (``buckets[].objects[]``) i plochý seznam
    objektů s klíčem ``bucket``/``Bucket``.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez S3 objektů.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[S3ObjectRecord] = []

    def add(bucket: str | None, item: dict[str, Any]) -> None:
        key = _to_str(item.get("key", item.get("Key", item.get("name"))))
        size = _to_int(
            item.get("size", item.get("Size", item.get("fileSize")))
        )
        modified_s = _to_epoch(
            item.get("lastModified", item.get("LastModified", item.get("modified")))
        )
        if not key:
            return
        records.append(
            S3ObjectRecord(
                bucket=bucket,
                key=key,
                size_bytes=size,
                modified_s=modified_s,
            )
        )

    def handle(obj: Any) -> None:
        if isinstance(obj, dict):
            buckets = obj.get("buckets") or obj.get("Buckets")
            if isinstance(buckets, list):
                for b in buckets:
                    if not isinstance(b, dict):
                        continue
                    bucket_name = _to_str(
                        b.get("name", b.get("Name", b.get("bucket")))
                    )
                    objects = b.get("objects") or b.get("Objects") or []
                    if isinstance(objects, list):
                        for o in objects:
                            if isinstance(o, dict):
                                add(bucket_name, o)
            else:
                # plochý objekt s klíčem?
                if any(k in obj for k in ("key", "Key")):
                    bucket = _to_str(obj.get("bucket") or obj.get("Bucket"))
                    add(bucket, obj)
        elif isinstance(obj, list):
            for item in obj:
                handle(item)

    handle(payload)

    records = records[:MAX_ITEMS_PER_FILE]
    if not records:
        raise TypeError("Nenalezeny S3 objekty")
    return records


def build_ec2_instance_artifacts(
    records: list[Ec2InstanceRecord],
) -> list[Artifact]:
    """ČISTÁ funkce: z EC2 instancí vytvoří artifacty (cloud_instance)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {
            "engine": "amazon_ec2_s3",
            "mimetype": "aws:ec2",
        }
        if r.state:
            details["state"] = r.state
        if r.private_ips:
            details["private_ips"] = r.private_ips
        if r.public_ip:
            details["public_ip"] = r.public_ip

        title = f"EC2 Instance: {r.instance_id or '(bez ID)'}"
        ts = None
        if r.launch_s is not None:
            try:
                ts = from_unix(r.launch_s)
            except ValueError:
                ts = None

        artifacts.append(
            Artifact(
                artifact_type="cloud_instance",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.85 if r.instance_id else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def build_s3_object_artifacts(records: list[S3ObjectRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze S3 objektů vytvoří artifacty (cloud_file)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {
            "engine": "amazon_ec2_s3",
            "mimetype": "aws:s3",
        }
        if r.bucket:
            details["bucket"] = r.bucket
        if r.size_bytes is not None:
            details["size"] = r.size_bytes

        title = f"S3 Object: {r.key or '(bez klíče)'}"
        ts = None
        if r.modified_s is not None:
            try:
                ts = from_unix(r.modified_s)
            except ValueError:
                ts = None

        artifacts.append(
            Artifact(
                artifact_type="cloud_file",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.8 if r.size_bytes is not None else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_amazon_ec2_s3_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Amazon EC2/S3 JSON → artifacty (auto-detekce).

    Zkouší oba formáty; výsledek je union (instance + S3 objekty).
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("AmazonEc2S3 %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    artifacts: list[Artifact] = []
    try:
        instances = parse_ec2_instances(data)
        artifacts.extend(build_ec2_instance_artifacts(instances))
    except (ValueError, TypeError):
        logger.debug("EC2 instance parse selhal — ne EC2 formát, zkusím S3 níže")
    try:
        objects = parse_s3_objects(data)
        artifacts.extend(build_s3_object_artifacts(objects))
    except (ValueError, TypeError) as e:
        logger.debug("AmazonEc2S3 %s: %s", path.name, e)

    return artifacts


def is_amazon_ec2_s3_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Amazon EC2/S3 exportu.

    Vyžaduje amazon marker + ec2/s3/instance/bucket klíčová slova — generic
    ``instances.json`` / ``files.json`` bez markery nepadnou, aby se nekradly
    cizí soubory.
    """
    lower = name.lower()
    if "amazon" not in lower and "aws" not in lower:
        return False
    if not any(k in lower for k in ("ec2", "s3", "instance", "bucket")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
