"""ETAPA B vlna 1 — Windows WiFi (WLAN) profily parser.

AXIOM ekvivalent: ``WiFiLocationsArtifact``.

Podporovaný formát: **WLAN profile XML** — soubory z
``C:\\ProgramData\\Microsoft\\WLAN\\Profile\\*.xml`` (Windows Vista+).
Kořenový element ``<WLANProfile>`` obsahuje SSID, šifrování, klíč a
případně MAC adresy známých přístupových bodů.

Detekce: **name-based** (soubor v adresáři s názvem obsahujícím
``wlan``/``wifi``, nebo XML s kořenem ``WLANProfile``) — XML nemá magic
bytes, proto se používá AXIOM Hunter pattern jako u iCloud Messages.

Artifact type: ``wifi_profile`` — jeden profil = jeden artifact.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stopa.domain.xml_bounded import XmlLimitError, bounded_xml_parse
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_PROFILES_PER_FILE = 50


@dataclass
class WifiProfile:
    """Jeden WiFi profil — SSID, šifrování, klíč."""

    name: str = ""
    ssid: str = ""
    encryption: str = ""
    has_key: bool = False
    key_length: int | None = None
    mac_addresses: list[str] = field(default_factory=list)


def _local(tag: str) -> str:
    """XML tag bez namespace (``{ns}name`` → ``name``)."""
    return (tag or "").split("}")[-1].lower()


def _find_text(elem: ET.Element, local_tag: str) -> str:
    """Namespace-agnostický text prvního elementu s daným lokálním tagem."""
    for node in elem.iter():
        if _local(node.tag) == local_tag.lower() and node.text:
            return node.text.strip()
    return ""


def _find_elem(elem: ET.Element, local_tag: str) -> ET.Element | None:
    """Namespace-agnostické find prvního elementu s daným lokálním tagem."""
    for node in elem.iter():
        if _local(node.tag) == local_tag.lower():
            return node
    return None


def _parse_profile(elem: ET.Element) -> WifiProfile | None:
    """ČISTÝ parser jednoho ``<WLANProfile>`` elementu (namespace-agnosticky)."""
    name = _find_text(elem, "name") or elem.get("name", "")

    # SSID — <SSIDConfig><SSID><name>; fallback na textový obsah <SSID>
    ssid_elem = _find_elem(elem, "ssid")
    ssid = ""
    if ssid_elem is not None:
        inner = _find_elem(ssid_elem, "name")
        if inner is not None and inner.text:
            ssid = inner.text.strip()
        elif ssid_elem.text:
            ssid = ssid_elem.text.strip()

    # šifrování — <smcSecurity><authentication> + <encryption> (text obsah elementů)
    auth_text = _find_text(elem, "authentication")
    enc_text = _find_text(elem, "encryption")
    encryption_parts = [p for p in (auth_text.lower(), enc_text.lower()) if p]

    # klíč — <sharedKey><keyPassphrase> nebo <keyMaterial>
    has_key = False
    key_length: int | None = None
    shared_key = _find_elem(elem, "sharedkey")
    if shared_key is not None:
        for child in shared_key:
            tag = _local(child.tag)
            if tag in ("keypassphrase", "keymaterial"):
                has_key = True
                if child.text:
                    key_length = len(child.text.strip())

    # MAC adresy známých AP — <macAddress> (libovolná hloubka, např. stationList)
    macs: list[str] = []
    for node in elem.iter():
        tag = _local(node.tag)
        if tag == "macaddress" and node.text:
            mac = node.text.strip().upper()
            if re.fullmatch(r"[0-9A-F]{2}(:[0-9A-F]{2}){5}", mac) and mac not in macs:
                macs.append(mac)

    if not ssid and not name:
        return None

    return WifiProfile(
        name=name,
        ssid=ssid,
        encryption=" ".join(encryption_parts),
        has_key=has_key,
        key_length=key_length,
        mac_addresses=macs[:10],
    )


def parse_wlan_profile_xml(data: bytes) -> list[WifiProfile]:
    """ČISTÝ parser — XML obsah → profily.

    Raises:
        ValueError: Neplatné XML nebo chybějící WLANProfile kořen.
    """
    try:
        # P1 security — důkazový XML s limitem hloubky a entit
        root = bounded_xml_parse(data)
    except (ET.ParseError, XmlLimitError) as e:
        raise ValueError(f"Neplatné WLAN profile XML: {e}") from e

    # kořen může být <WLANProfile> přímo, nebo obálka s více profily
    if (root.tag or "").split("}")[-1].lower() == "wlanprofile":
        candidates = [root]
    else:
        candidates = list(root)

    profiles: list[WifiProfile] = []
    for elem in candidates[:MAX_PROFILES_PER_FILE]:
        if (elem.tag or "").split("}")[-1].lower() != "wlanprofile":
            continue
        try:
            prof = _parse_profile(elem)
        except Exception as e:  # noqa: BLE001 — jeden poškozený profil nepotopí soubor
            logger.warning("WLAN profile: chyba elementu (%s)", e)
            continue
        if prof is not None:
            profiles.append(prof)

    return profiles


def is_wlan_profile_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce WLAN profilu (AXIOM Hunter pattern).

    Soubory v ``WLAN\\Profile`` adresáři nemají spolehlivou magic — detekce
    podle názvu souboru. Volitelně se ověří i XML obsah (``head``), pokud je
    k dispozici, aby se nechytil náhodný .xml s podobným názvem.
    """
    lower = name.lower()
    # typické názvy: "SSID_name.xml", "Microsoft_Wi-Fi_<ssid>.xml"
    if not (lower.endswith(".xml") and ("wlan" in lower or "wi-fi" in lower or "wifi" in lower)):
        return False
    if head:
        h = head[:4096].lstrip()
        # XML deklarace + WLANProfile kořen v hlavičce
        if b"<" not in h:
            return False
        if b"wlanprofile" not in h.lower():
            return False
    return True


def build_wifi_artifacts(profiles: list[WifiProfile]) -> list[Artifact]:
    """ČISTÁ funkce: z profilů vytvoří artifacty (wifi_profile)."""
    artifacts: list[Artifact] = []
    for prof in profiles:
        label = prof.ssid or prof.name or "(bez názvu)"
        details: dict[str, Any] = {
            "engine": "wlan_profile",
            "ssid": prof.ssid,
            "profile_name": prof.name,
        }
        if prof.encryption:
            details["encryption"] = prof.encryption
        if prof.has_key:
            details["has_key"] = True
            if prof.key_length is not None:
                details["key_length"] = prof.key_length
        if prof.mac_addresses:
            details["known_ap_mac"] = prof.mac_addresses

        artifacts.append(
            Artifact(
                artifact_type="wifi_profile",
                timestamp=None,  # WLAN profile XML nemá spolehlivý čas
                title=f"WiFi profil: {label}",
                details=details,
                confidence=0.85 if prof.ssid else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_wifi_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — WLAN profile XML → wifi_profile artifacty.

    Chyby (poškozené XML, IO) → log + prázdný výsledek, nikdy ne výjimka.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("WiFi %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        profiles = parse_wlan_profile_xml(data)
    except ValueError as e:
        logger.debug("WiFi %s: %s", path, e)
        return []

    return build_wifi_artifacts(profiles)
