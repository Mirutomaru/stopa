"""ETAPA B vlna 1 — Windows SID extrakce z registry.

AXIOM ekvivalent: ``GetsidsArtifact`` / ``SidsArtifact`` / ``UserSidsArtifact``.

Podporované hivy (sdílená ``regf`` magic — sekundární průchod v pipeline):
- **SAM** — ``Sam\\Domains\\Account\\Users\\<SID>`` s hodnotou ``Name``
  → uživatelské účty se jménem a SID.
- **SECURITY** — stejná struktura (zrcadlo SAM).
- **NTUSER.DAT / SOFTWARE** — ``Microsoft\\Windows NT\\CurrentVersion\\ProfileList\\<SID>``
  → profily uživatelů (SID + jméno profilu, pokud je k dispozici).

Sekundární extraktor vedle generic registry extraktoru (pattern jako
Amcache/ShimCache/Clipboard). Detekce podle cesty klíče; bez příslušných
klíčů → prázdný výsledek.

Artifact type: ``user_sid`` — jeden SID = jeden artifact.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_SIDS_PER_HIVE = 200

# SID formát: S-1-5-21-... (domain) nebo S-1-5-32-... (alias) apod.
_SID_RE = re.compile(r"^S-1-\d+(-\d+){1,9}$")


def _printable_ratio(s: str) -> float:
    """Podíl tisknutelných znaků v řetězci (prázdný → 0.0)."""
    if not s:
        return 0.0
    sample = s[:64]
    return sum(c.isprintable() or c.isspace() for c in sample) / len(sample)


def _decode_reg_str(raw: Any) -> str:
    """Registry string hodnota → text (UTF-16LE nejdřív, pak UTF-8 fallback)."""
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        try:
            s = raw.decode("utf-16-le").strip("\x00")
            if _printable_ratio(s) > 0.9:
                return s.strip()
        except (UnicodeDecodeError, UnicodeError):
            pass
        try:
            s = raw.decode("utf-8")
            if _printable_ratio(s) > 0.9:
                return s.strip()
        except (UnicodeDecodeError, UnicodeError):
            pass
        return ""
    return str(raw).strip()


@dataclass
class SidEntry:
    """Jeden SID záznam — identifikátor + jméno + zdroj."""

    sid: str = ""
    name: str = ""  # uživatelské jméno (SAM) nebo profil (ProfileList)
    source: str = ""  # sam | security | profile_list
    timestamp: datetime | None = None


def _is_sid(name: str) -> bool:
    """Ověří, že jméno klíče je platný SID."""
    return bool(_SID_RE.match(name.strip()))


def build_sid_artifacts(entries: list[SidEntry]) -> list[Artifact]:
    """ČISTÁ funkce: ze SID záznamů vytvoří artifacty (user_sid)."""
    artifacts: list[Artifact] = []
    seen: set[str] = set()
    for e in entries[:MAX_SIDS_PER_HIVE]:
        if not _is_sid(e.sid) or e.sid in seen:
            continue
        seen.add(e.sid)

        label = f"{e.name} ({e.sid})" if e.name else e.sid
        details: dict[str, Any] = {
            "engine": "sids",
            "sid": e.sid,
            "source": e.source,
        }
        if e.name:
            details["name"] = e.name

        artifacts.append(
            Artifact(
                artifact_type="user_sid",
                timestamp=e.timestamp,
                title=f"SID: {label}",
                details=details,
                confidence=0.95 if e.source in ("sam", "security") else 0.85,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def _extract_sam_users(hive, source_hint: str = "sam") -> list[SidEntry]:
    """SAM/SECURITY — Sam\\Domains\\Account\\Users\\<SID> s hodnotou Name.

    ``source_hint`` — „sam“ nebo „security“ podle názvu hive souboru (obě hivy
    mají identickou strukturu, rozlišení jen po jméně souboru).
    """
    entries: list[SidEntry] = []
    for key in hive.recurse_subkeys():
        raw_path = (key.path or "").replace("/", "\\")
        kpath = raw_path.lower()
        if "sam\\domains\\account\\users\\" not in kpath and "security\\sam" not in kpath:
            continue
        sid = raw_path.rsplit("\\", 1)[-1]  # SID zůstává v původním (velkém) písmenu
        if not _is_sid(sid):
            continue
        name = ""
        for val in key.values or []:
            vname = getattr(val, "name", "") or ""
            if vname.lower() == "name":
                name = _decode_reg_str(getattr(val, "value", None))
                break
        entries.append(
            SidEntry(
                sid=sid,
                name=name,
                source=source_hint,
                timestamp=getattr(key, "timestamp", None),
            )
        )
    return entries


def _extract_profile_list(hive) -> list[SidEntry]:
    """ProfileList — Microsoft\\Windows NT\\CurrentVersion\\ProfileList\\<SID>."""
    entries: list[SidEntry] = []
    for key in hive.recurse_subkeys():
        raw_path = (key.path or "").replace("/", "\\")
        kpath = raw_path.lower()
        if "currentversion\\profilelist\\" not in kpath:
            continue
        sid = raw_path.rsplit("\\", 1)[-1]  # SID zůstává v původním (velkém) písmenu
        if not _is_sid(sid):
            continue
        name = ""
        for val in key.values or []:
            vname = getattr(val, "name", "") or ""
            if vname.lower() == "profileimagepath":
                s = _decode_reg_str(getattr(val, "value", None))
                # ...\\Users\<username> — jméno uživatele z cesty profilu
                if "users" in s.lower():
                    name = s.rsplit("\\", 1)[-1].strip()
                break
        entries.append(
            SidEntry(sid=sid, name=name, source="profile_list", timestamp=getattr(key, "timestamp", None))
        )
    return entries


def extract_sid_artifacts(path) -> list[Artifact]:
    """Pipeline entrypoint — registry hive → user_sid artifacty.

    Sekundární extraktor pro SAM / SECURITY / NTUSER.DAT hivy (regf magic).
    Běží vedle generic + Amcache + ShimCache + Clipboard; bez příslušných
    klíčů vrátí prázdný výsledek.
    """
    from regipy.registry import RegistryHive  # type: ignore[import-untyped]

    try:
        hive = RegistryHive(hive_path=str(path))
    except FileNotFoundError:
        logger.warning("Registry hive nenalezena pro SID extrakci: %s", path)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.error("Chyba při otevírání hive pro SID %s: %s", path, exc)
        return []

    # SAM a SECURITY mají identickou strukturu — zdroj určí název souboru
    hint = "security" if "security" in str(path).lower() else "sam"
    entries = _extract_sam_users(hive, hint) + _extract_profile_list(hive)
    logger.debug("SID %s: %d záznamů", path, len(entries))
    return build_sid_artifacts(entries)
