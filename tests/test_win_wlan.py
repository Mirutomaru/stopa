"""ETAPA B vlna 1 — testy Windows WiFi (WLAN) profile XML parseru.

ČISTÉ funkce (parse_wlan_profile_xml / build_wifi_artifacts) + IO entrypoint
(extract_wifi_artifacts přes tmp_path). Žádný regipy, žádné sítě.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stopa.artifacts.win_wlan import (
    PARSER_VERSION,
    build_wifi_artifacts,
    extract_wifi_artifacts,
    is_wlan_profile_file,
    parse_wlan_profile_xml,
)

# ── syntetické fixtures ────────────────────────────────────────────────

WLAN_PROFILE = b"""<?xml version="1.0" encoding="utf-8"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v3">
  <name>OfficeWiFi</name>
  <MACAddress></MACAddress>
  <networkID>OfficeWiFi</networkID>
  <SSIDConfig>
    <SSID>
      <name>OfficeWiFi</name>
    </SSID>
  </SSIDConfig>
  <connectionType>ESS</connectionType>
  <connectionMode>AllowedUser</connectionMode>
  <smcSecurity>
    <authentication>WPA2</authentication>
    <encryption>AES</encryption>
    <useOneX>false</useOneX>
  </smcSecurity>
</WLANProfile>
"""

# open network + MAC adresa známého AP (v stationList)
WLAN_OPEN = b"""<?xml version="1.0" encoding="utf-8"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v3">
  <name>CafeOpen</name>
  <networkID>CafeOpen</networkID>
  <SSIDConfig>
    <SSID>
      <name>CafeOpen</name>
    </SSID>
  </SSIDConfig>
  <connectionType>ESS</connectionType>
  <connectionMode>AllowedUser</connectionMode>
  <smcSecurity>
    <authentication>open</authentication>
    <encryption>none</encryption>
    <useOneX>false</useOneX>
  </smcSecurity>
  <interface>
    <igb>
      <dot11>
        <stationList>
          <macAddress>AA:BB:CC:DD:EE:FF</macAddress>
        </stationList>
      </dot11>
    </igb>
  </interface>
</WLANProfile>
"""

# ne-WLAN XML (jiný root) — neměl by se parseovat na profily
OTHER_XML = b'<?xml version="1.0"?><Task xmlns="x"><name>t</name></Task>'


# ── is_wlan_profile_file (detekce) ─────────────────────────────────────

def test_is_wlan_by_name_and_content():
    # quality: positive
    assert is_wlan_profile_file("OfficeWiFi.xml", WLAN_PROFILE[:2048]) is True


def test_is_wlan_rejects_other_xml_content():
    # quality: negative
    # název sedí (wifi), ale obsah není WLANProfile → False
    assert is_wlan_profile_file("wifi_task.xml", OTHER_XML) is False


def test_is_wlan_requires_name_hint():
    # quality: positive
    # bez názvové nápovědy (.xml + wlan/wifi) — detekce nepadne
    assert is_wlan_profile_file("random.bin", WLAN_PROFILE[:2048]) is False


# ── parse_wlan_profile_xml (čistá funkce) ─────────────────────────────

def test_parse_wpa2_profile():
    # quality: positive
    profiles = parse_wlan_profile_xml(WLAN_PROFILE)
    assert len(profiles) == 1
    p = profiles[0]
    assert p.name == "OfficeWiFi"
    assert p.ssid == "OfficeWiFi"
    assert "wpa2" in p.encryption.lower()
    assert "aes" in p.encryption.lower()


def test_parse_open_profile_with_mac():
    # quality: positive
    profiles = parse_wlan_profile_xml(WLAN_OPEN)
    assert len(profiles) == 1
    p = profiles[0]
    assert p.name == "CafeOpen"
    assert p.ssid == "CafeOpen"
    assert p.mac_addresses == ["AA:BB:CC:DD:EE:FF"]


def test_parse_non_wlan_xml_empty():
    # quality: boundary
    # jiný root → žádné profily (ne výjimka)
    assert parse_wlan_profile_xml(OTHER_XML) == []


def test_parse_garbage_bytes_raises():
    # quality: corrupted
    # ne-XML → ValueError (entrypoint ho zachytí a vrátí [])
    with pytest.raises(ValueError):
        parse_wlan_profile_xml(b"\x00\x01\x02garbage")


# ── build_wifi_artifacts (čistá funkce) ───────────────────────────────

def test_build_artifacts():
    # quality: positive
    profiles = parse_wlan_profile_xml(WLAN_PROFILE)
    arts = build_wifi_artifacts(profiles)
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "wifi_profile"
    assert a.parser_version == PARSER_VERSION
    assert a.details.get("ssid") == "OfficeWiFi"


def test_build_artifacts_empty():
    # quality: boundary
    assert build_wifi_artifacts([]) == []


# ── extract_wifi_artifacts (IO přes tmp_path) ─────────────────────────

def test_extract_wlan_file(tmp_path: Path):
    # quality: positive
    p = tmp_path / "OfficeWiFi.xml"
    p.write_bytes(WLAN_PROFILE)
    arts = extract_wifi_artifacts(p)
    assert len(arts) == 1
    assert arts[0].artifact_type == "wifi_profile"


def test_extract_garbage_file(tmp_path: Path):
    # quality: corrupted
    # poškozený XML → prázdný výsledek (ne výjimka)
    p = tmp_path / "broken.xml"
    p.write_bytes(b"\x00\x01garbage")
    assert extract_wifi_artifacts(p) == []


def test_extract_missing_file(tmp_path: Path):
    # quality: negative
    assert extract_wifi_artifacts(tmp_path / "nope.xml") == []
