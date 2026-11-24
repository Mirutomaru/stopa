"""ETAPA B vlna 15 — Windows LSA Credential Cache extrakce z registry.

AXIOM ekvivalent: ``LsaRegistryExtractor``.

Windows **Credential Cache** (LSA secrets / „cached credentials") je uložen
tak, že offline nástroje ho čtou buď z paměti LSASS, nebo z registry hive.
Tento extraktor je *tolerantní skener* — prochází klíče/hodnoty předané hive
a hledá indikátory cached credential; bez příslušných klíčů vrátí prázdný
výsledek (pattern jako win_sids / clipboard).

BEZPEČNOST: do case DB se **neukládá surové heslo** — pouze typ + fingerprint
(prvních 16 hex znaků SHA-256) + délka. Case DB se kopíruje/posílá/backupuje,
proto tajnost zůstává jen jako neobnovitelný otisk (rozhodnutí F-krypto).

Artifact type: ``credential`` — jeden cached credential = jeden artifact.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_CREDENTIALS_PER_HIVE = 500

# Indikátory LSA credential cache — cesta klíče NEBO název hodnoty.
# Uvědomělá tolerantní sada: pokryje běžné položky bez přetěžování falešnými
# pozitivami (musí se zároveň nacházet v kontextu credential/lsa).
_KEY_MARKERS = ("credential", "cachedcredentials", "lsa")
_VALUE_NAMES = {"cachedcredentials", "password", "pwdhash"}


def _printable_ratio(s: str) -> float:
    """Podíl tisknutelných znaků (prázdný → 0.0)."""
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
            logger.debug("LSA: UTF-16LE decode selhal (%d B) → zkusím UTF-8", len(raw))
        try:
            s = raw.decode("utf-8")
            if _printable_ratio(s) > 0.9:
                return s.strip()
        except (UnicodeDecodeError, UnicodeError):
            logger.debug("LSA: oba decode selhaly (%d B) → prázdný string", len(raw))
        return ""
    return str(raw).strip()


@dataclass
class LsaCredentialEntry:
    """Jeden cached credential — identifikátor + otisk tajnosti + zdroj."""

    account: str = ""  # účet / název (z cesty klíče nebo názvu hodnoty)
    key_path: str = ""  # cesta registry klíče (kontext)
    secret_fingerprint: str = ""  # prvních 16 hex SHA-256 tajnosti (NE surová)
    byte_length: int = 0  # délka tajnosti v bytech
    source: str = "lsa"
    timestamp: datetime | None = None


def fingerprint_secret(raw: Any) -> tuple[str, int]:
    """ČISTÁ funkce: tajnost → (prvních 16 hex SHA-256, délka v bytech).

    Surová hodnota se nikdy nevrací — jen neobnovitelný otisk. Prázdný vstup
    → ("", 0).
    """
    if raw is None:
        return "", 0
    data = raw if isinstance(raw, (bytes, bytearray)) else str(raw).encode("utf-8")
    if not data:
        return "", 0
    return hashlib.sha256(bytes(data)).hexdigest()[:16], len(data)


def _key_matches(key_path: str) -> bool:
    """Cesta klíče obsahuje indikátor credential cache."""
    lp = key_path.lower().replace("/", "\\")
    return any(m in lp for m in _KEY_MARKERS)


def build_lsa_artifacts(entries: list[LsaCredentialEntry]) -> list[Artifact]:
    """ČISTÁ funkce: z LSA záznamů vytvoří artifacty (credential)."""
    artifacts: list[Artifact] = []
    seen: set[str] = set()
    for e in entries[:MAX_CREDENTIALS_PER_HIVE]:
        if not e.secret_fingerprint or not _key_matches(e.key_path):
            continue
        # dedupe podle (account, fingerprint) — stejný otisk = stejná tajnost
        key = f"{e.account}|{e.secret_fingerprint}"
        if key in seen:
            continue
        seen.add(key)

        label = e.account or _tail(e.key_path)
        details: dict[str, Any] = {
            "engine": "lsa",
            "source": e.source,
            "secret_sha256_16": e.secret_fingerprint,  # otisk, NE surové heslo
            "byte_length": e.byte_length,
        }
        if e.key_path:
            details["key_path"] = e.key_path

        artifacts.append(
            Artifact(
                artifact_type="credential",
                timestamp=e.timestamp,
                title=f"LSA credential: {label}",
                details=details,
                confidence=0.75,  # tolerantní skener — nižší důvěryhodnost
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def _tail(key_path: str) -> str:
    """Poslední segment cesty klíče (fallback label)."""
    s = key_path.strip().replace("/", "\\")
    if not s:
        return ""
    return s.rsplit("\\", 1)[-1] or s


def _extract_from_hive(hive) -> list[LsaCredentialEntry]:
    """Prochází klíče hive → LSA záznamy (tolerantní skener)."""
    entries: list[LsaCredentialEntry] = []
    for key in hive.recurse_subkeys():
        raw_path = (key.path or "").replace("/", "\\")
        if not _key_matches(raw_path):
            continue
        for val in getattr(key, "values", None) or []:
            vname = (getattr(val, "name", "") or "").lower()
            # název hodnoty je indikátor, NEBO cesta klíče už credential kontext
            is_cred_value = vname in _VALUE_NAMES or "credential" in raw_path.lower().replace("/", "\\")
            if not is_cred_value:
                continue
            raw_val = getattr(val, "value", None)
            fp, length = fingerprint_secret(raw_val)
            if not fp:
                continue
            account = vname if vname != "cachedcredentials" else _tail(raw_path)
            entries.append(
                LsaCredentialEntry(
                    account=account,
                    key_path=raw_path,
                    secret_fingerprint=fp,
                    byte_length=length,
                    source="lsa",
                    timestamp=getattr(key, "timestamp", None),
                )
            )
    return entries


def extract_lsa_artifacts(path) -> list[Artifact]:
    """Pipeline entrypoint — registry hive → credential artifacty (LSA cache).

    Sekundární extraktor vedle generic/Amcache/ShimCache/SID. Běží na SYSTEM /
    SECURITY hive (regf magic); bez příslušných klíčů vrátí prázdný výsledek.
    """
    from regipy.registry import RegistryHive  # type: ignore[import-untyped]

    try:
        hive = RegistryHive(hive_path=str(path))
    except FileNotFoundError:
        logger.warning("Registry hive nenalezena pro LSA extrakci: %s", path)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.error("Chyba při otevírání hive pro LSA %s: %s", path, exc)
        return []

    entries = _extract_from_hive(hive)
    logger.debug("LSA %s: %d záznamů", path, len(entries))
    return build_lsa_artifacts(entries)
