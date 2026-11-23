"""ETAPA B vlna 3 — LimeWire / Limerunner / Luckywire parser (P2P shared files).

AXIOM ekvivalenty: ``LimewireArtifact`` + ``LimerunnerArtifact`` +
``LuckywireArtifact`` (``Magnet.Artifacts.Limewire``) — sdílené soubory z P2P
klientů LimeWire, Limerunner a Luckywire. AXIOM Artifact Reference popisuje
atributy::

    File Name, Size, Path, Hash, Date Modified, Date Accessed,
    Downloaded By/From/To/On, Uploaded By/From/To/On   (LimeWire/Limerunner)
    File Name, Size, Path, Hash, Date Modified, Date Accessed  (Luckywire)

Zdroj je lokální databáze / log klienta (``LimeWire.dat``, registry, Java
serialization). STOPA port: **textový/JSON parser** — detekce po markerech
``limewire``/``limerunner``/``luckywire``; záznamy buď JSON pole::

    [{"filename": "a.mp3", "size": 123, "path": "...", "hash": "..."}]

nebo pipe-delimited řádky ``name|size|path|hash|modified|accessed``.

Detekce: **name-based** (``limewire``, ``limerunner``, ``luckywire``) +
content check. Rodina se určí podle prvního nalezeného markeru (Limerunner je
specifický, proto před obecným Limewire).

Artifact types: ``limewire_shared_file`` / ``limerunner_shared_file`` /
``luckywire_shared_file`` — jeden sdílený soubor = jeden artifact.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_FILES_PER_FILE = 20_000

# marker → artifact_type (pořadí = priorita; Limerunner před Limewire)
_FAMILY_MARKERS: tuple[tuple[str, str], ...] = (
    ("limerunner", "limerunner_shared_file"),
    ("limewire", "limewire_shared_file"),
    ("luckywire", "luckywire_shared_file"),
)

# pipe-delimited řádek: name|size|path|hash[|modified][|accessed]
_PIPE_RE = re.compile(
    r"^(?P<name>[^|]+)\|(?P<size>\d+)\|(?P<path>[^|]*)\|(?P<hash>[^|]*)"
    r"(?:\|(?P<modified>[^|]*))?(?:\|(?P<accessed>[^|]*))?$"
)


@dataclass
class SharedFile:
    """Jeden sdílený P2P soubor."""

    filename: str = ""
    size: int | None = None
    path: str = ""
    hash: str = ""
    date_modified: datetime | None = None
    date_accessed: datetime | None = None
    transfer: dict[str, Any] = field(default_factory=dict)


def _parse_ts(raw: str | None) -> datetime | None:
    """Konverze časového řetězce na UTC datetime (None při selhání)."""
    if not raw:
        return None
    s = raw.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _to_int(value: Any) -> int | None:
    """Bezpečná konverze na int (None při selhání)."""
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def detect_family(name: str = "", head: bytes = b"") -> str | None:
    """Určí P2P rodinu podle názvu/obsahu.

    Returns:
        artifact_type rodiny nebo ``None`` pokud nezapadá. Limerunner má
        prioritu před Limewire (specifický marker).
    """
    low_name = name.lower()
    for marker, atype in _FAMILY_MARKERS:
        if marker in low_name:
            return atype
    low = head[:4096].lower()
    for marker, atype in _FAMILY_MARKERS:
        if marker.encode() in low and (b"filename" in low or b"|" in low):
            return atype
    return None


def parse_shared_files(data: bytes) -> list[SharedFile]:
    """ČISTÝ parser — P2P shared files export → záznamy.

    Podporuje JSON pole záznamů i pipe-delimited text.

    Raises:
        ValueError: Neplatné JSON (při JSON vstupu).
        TypeError: Platné JSON, ale ne pole záznamů.
    """
    out: list[SharedFile] = []
    text = data.decode("utf-8", errors="replace")

    # Konzervativní JSON detekce — pipe řádky i komentáře mohou obsahovat [],
    # proto JSON uznáme jen při jasném signálu (objekt, uzavřené pole s {}/"",
    # nebo kompaktní pole v prvním řádku).
    candidate = text.strip()
    first_line = candidate.split("\n", 1)[0] if candidate else ""
    looks_json = (
        (candidate.startswith("{") and candidate.endswith("}"))
        or (
            candidate.startswith("[")
            and candidate.endswith("]")
            and ("{" in candidate or '"' in candidate)
        )
        or (candidate.startswith("[") and ("{" in first_line or '"' in first_line))
    )
    if looks_json:
        try:
            payload = bounded_json_loads(candidate)
        except json.JSONDecodeError as e:
            raise ValueError(f"Neplatné JSON: {e}") from None
        if not isinstance(payload, list):
            raise TypeError("Očekáváno JSON pole záznamů")
        for item in payload:
            if len(out) >= MAX_FILES_PER_FILE:
                logger.warning("P2P shared files: limit %d souborů", MAX_FILES_PER_FILE)
                break
            if not isinstance(item, dict):
                continue
            transfer = {
                k: str(v)
                for k, v in item.items()
                if k in (
                    "downloaded_by", "downloaded_from", "downloaded_to", "downloaded_on",
                    "uploaded_by", "uploaded_from", "uploaded_to", "uploaded_on",
                )
            }
            out.append(
                SharedFile(
                    filename=str(item.get("filename") or item.get("name") or "").strip(),
                    size=_to_int(item.get("size")),
                    path=str(item.get("path") or "").strip(),
                    hash=str(item.get("hash") or item.get("sha1") or "").strip(),
                    date_modified=_parse_ts(str(item["date_modified"])) if item.get("date_modified") else None,
                    date_accessed=_parse_ts(str(item["date_accessed"])) if item.get("date_accessed") else None,
                    transfer=transfer,
                )
            )
        return out

    # pipe-delimited text.
    for line in text.splitlines():
        if len(out) >= MAX_FILES_PER_FILE:
            logger.warning("P2P shared files: limit %d souborů", MAX_FILES_PER_FILE)
            break
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _PIPE_RE.match(line)
        if m:
            out.append(
                SharedFile(
                    filename=m.group("name").strip(),
                    size=int(m.group("size")),
                    path=(m.group("path") or "").strip(),
                    hash=(m.group("hash") or "").strip(),
                    date_modified=_parse_ts(m.group("modified")),
                    date_accessed=_parse_ts(m.group("accessed")),
                )
            )
    return out


def is_limewire_family_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce P2P shared files exportu (LimeWire/Limerunner/Luckywire)."""
    return detect_family(name=name, head=head) is not None


def build_shared_file_artifacts(
    records: list[SharedFile], artifact_type: str
) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (shared file)."""
    artifacts: list[Artifact] = []
    for rec in records:
        ts = rec.date_modified or rec.date_accessed
        details: dict[str, Any] = {
            "engine": "limewire_p2p",
            "filename": rec.filename,
            "size": rec.size,
            "path": rec.path,
            "hash": rec.hash,
        }
        if rec.transfer:
            details["transfer"] = rec.transfer
        artifacts.append(
            Artifact(
                artifact_type=artifact_type,
                timestamp=ts,
                title=f"P2P {rec.filename or '(bez názvu)'}",
                details=details,
                confidence=0.7 if rec.hash else 0.5,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_shared_files_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — P2P shared files → artifacty (rodina podle detekce).

    Chyby (poškozený soubor, IO, neplatné JSON) → log + prázdný výsledek,
    nikdy ne výjimka nahoru.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("P2P shared files %s: nelze číst (%s)", path, e)
        return []
    if not data:
        return []
    family = detect_family(name=path.name, head=data[:4096])
    if family is None:
        return []
    try:
        records = parse_shared_files(data)
    except (ValueError, TypeError) as e:
        logger.debug("P2P shared files %s: %s", path, e)
        return []
    return build_shared_file_artifacts(records, family)
