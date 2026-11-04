"""ETAPA B vlna 14 — syntetické offline testy cloud-export parserů (dokončení kategorie).

Pokrývá 6 nových parserů (Apple rodina, Google 2025 WR, WhatsApp, generic
cloud metadata, Gmail Messages, Maps Labeled Places) + dispatch pre-pass
routing. Všechny fixture jsou syntetické JSON bez externích závislostí.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stopa.artifacts.apple_cloud import (
    build_apple_cloud_artifacts,
    extract_apple_cloud_artifacts,
    is_apple_file,
    parse_apple_cloud,
)
from stopa.artifacts.cloud_generic import (
    build_cloud_generic_artifacts,
    extract_cloud_generic_artifacts,
    is_cloud_generic_file,
    parse_cloud_generic,
)
from stopa.artifacts.gmail_messages import (
    build_gmail_artifacts,
    extract_gmail_artifacts,
    is_gmail_file,
    parse_gmail_messages,
)
from stopa.artifacts.google_2025_wr import (
    build_google_2025_artifacts,
    extract_google_2025_artifacts,
    is_google_2025_file,
    parse_google_2025_wr,
)
from stopa.artifacts.maps_labeled_places import (
    build_maps_labeled_artifacts,
    extract_maps_labeled_artifacts,
    is_maps_labeled_file,
    parse_maps_labeled_places,
)
from stopa.artifacts.whatsapp_cloud import (
    build_whatsapp_artifacts,
    extract_whatsapp_artifacts,
    is_whatsapp_file,
    parse_whatsapp_cloud,
)

# ---------------------------------------------------------------------------
# Apple Cloud rodina
# ---------------------------------------------------------------------------


class TestAppleCloud:
    def test_parse_contacts_list(self):
        data = json.dumps(
            [
                {
                    "firstName": "Jan",
                    "lastName": "Novák",
                    "emailAddresses": [{"value": "jan@x.cz"}],
                    "phoneNumbers": [{"value": "+4201"}],
                }
            ]
        ).encode()
        recs = parse_apple_cloud(data)
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "contact"
        assert r.name == "Jan Novák"
        assert r.email == "jan@x.cz"
        assert r.phone == "+4201"

    def test_parse_keychain(self):
        data = json.dumps(
            [
                {
                    "label": "GitHub",
                    "account": "mirda",
                    "type": "internetPassword",
                    "data": {"password": "sekret"},
                }
            ]
        ).encode()
        recs = parse_apple_cloud(data)
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "keychain"
        assert r.name == "GitHub:mirda"

    def test_parse_mail(self):
        data = json.dumps(
            [
                {
                    "subject": "Faktura",
                    "from": "posil@x.cz",
                    "to": ["jan@y.cz"],
                    "date": "2026-01-05T10:00:00Z",
                    "body": "Posílám fakturu.",
                }
            ]
        ).encode()
        recs = parse_apple_cloud(data)
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "mail"
        assert r.name == "Faktura"
        assert r.sender == "posil@x.cz"
        assert r.recipient is not None and "jan@y.cz" in r.recipient

    def test_parse_backup(self):
        data = json.dumps(
            [{"name": "iPhone 15 backup", "domain": "com.apple.mobilebackup"}]
        ).encode()
        recs = parse_apple_cloud(data)
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "backup"
        assert r.name == "iPhone 15 backup"

    def test_kind_hint_overrides(self):
        data = json.dumps([{"label": "x", "account": "y"}]).encode()
        recs = parse_apple_cloud(data, kind_hint="keychain")
        assert len(recs) == 1
        assert recs[0].kind == "keychain"

    def test_build_artifacts_contact(self):
        data = json.dumps(
            [{"firstName": "Jan", "lastName": "Novák", "emailAddresses": [{"value": "jan@x.cz"}]}]
        ).encode()
        arts = build_apple_cloud_artifacts(parse_apple_cloud(data))
        assert len(arts) == 1
        a = arts[0]
        assert a.details.get("engine") == "apple_cloud"

    def test_extract_roundtrip(self, tmp_path: Path):
        p = tmp_path / "AppleContacts.json"
        p.write_text(json.dumps([{"firstName": "Jan", "lastName": "Novák"}]))
        arts = extract_apple_cloud_artifacts(p)
        assert len(arts) == 1

    def test_detector_positive(self):
        assert is_apple_file("AppleCloudExport/contacts.json")
        assert is_apple_file("icloud/keychain_export.json")

    def test_detector_negative_generic(self):
        assert not is_apple_file("contacts.json")


# ---------------------------------------------------------------------------
# Google 2025 Warrant Return
# ---------------------------------------------------------------------------


class TestGoogle2025Wr:
    def test_parse_access_log(self):
        data = json.dumps(
            [
                {
                    "deviceName": "Pixel 8",
                    "ipAddress": "1.2.3.4",
                    "accessTime": "2026-01-01T00:00:00Z",
                }
            ]
        ).encode()
        recs = parse_google_2025_wr(data)
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "access_log"
        assert r.name == "Pixel 8"
        assert r.ip_address == "1.2.3.4"
        assert r.created_s is not None

    def test_parse_target_assoc(self):
        data = json.dumps(
            [
                {
                    "targetId": "tgt-1",
                    "associationType": "owner",
                    "accountEmail": "jan@x.cz",
                }
            ]
        ).encode()
        recs = parse_google_2025_wr(data)
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "target_assoc"
        assert r.target_id == "tgt-1"
        assert r.association_type == "owner"
        assert r.account_email == "jan@x.cz"

    def test_parse_calls_explicit_fields(self):
        data = json.dumps(
            [
                {
                    "callerNumber": "+420111",
                    "calleeNumber": "+420222",
                    "startTime": "2026-01-01T10:00:00Z",
                    "durationSeconds": 90,
                }
            ]
        ).encode()
        recs = parse_google_2025_wr(data)
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "call"
        assert r.caller_number == "+420111"
        assert r.callee_number == "+420222"
        assert r.duration_s == 90

    def test_parse_calls_from_to_fallback(self):
        data = json.dumps(
            [
                {
                    "from": "+420111",
                    "to": "+420222",
                    "startTime": "2026-01-01T10:00:00Z",
                    "duration": 120,
                }
            ]
        ).encode()
        recs = parse_google_2025_wr(data)
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "call"
        assert r.duration_s == 120

    def test_kind_hint_from_path(self):
        data = json.dumps([{"deviceName": "X", "ipAddress": "9.9.9.9"}]).encode()
        recs = parse_google_2025_wr(data, kind_hint="access_log")
        assert len(recs) == 1
        assert recs[0].kind == "access_log"

    def test_build_artifacts(self):
        data = json.dumps(
            [{"deviceName": "Pixel", "ipAddress": "1.2.3.4", "accessTime": "2026-01-01T00:00:00Z"}]
        ).encode()
        arts = build_google_2025_artifacts(parse_google_2025_wr(data))
        assert len(arts) == 1

    def test_extract_roundtrip(self, tmp_path: Path):
        p = tmp_path / "GoogleAccessLogDevices2025.json"
        p.write_text(json.dumps([{"deviceName": "Pixel", "ipAddress": "1.2.3.4"}]))
        arts = extract_google_2025_artifacts(p)
        assert len(arts) == 1

    def test_detector_positive(self):
        assert is_google_2025_file("GoogleAccessLogDevices2025.json")
        assert is_google_2025_file("AccountTargetAssociation2025.json")
        assert is_google_2025_file("google/calls.json")

    def test_detector_negative_generic(self):
        assert not is_google_2025_file("calls.json")


# ---------------------------------------------------------------------------
# WhatsApp Cloud
# ---------------------------------------------------------------------------


class TestWhatsAppCloud:
    def test_parse_chats(self):
        data = json.dumps(
            [
                {
                    "sender": "+4201",
                    "text": "Ahoj",
                    "timestamp": 1700000000,
                    "type": "text",
                }
            ]
        ).encode()
        recs = parse_whatsapp_cloud(data)
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "chat"
        assert r.sender == "+4201"
        assert r.text == "Ahoj"
        assert r.created_s is not None

    def test_parse_backups(self):
        data = json.dumps(
            [{"backupDate": "2026-01-01", "version": "2.23", "sizeBytes": 1024}]
        ).encode()
        recs = parse_whatsapp_cloud(data)
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "backup"
        assert r.version == "2.23"

    def test_build_artifacts_chat(self):
        data = json.dumps([{"sender": "+4201", "text": "Ahoj"}]).encode()
        arts = build_whatsapp_artifacts(parse_whatsapp_cloud(data))
        assert len(arts) == 1
        a = arts[0]
        assert a.details.get("engine") == "whatsapp_cloud"

    def test_extract_roundtrip(self, tmp_path: Path):
        p = tmp_path / "WhatsAppChats.json"
        p.write_text(json.dumps([{"sender": "+4201", "text": "Ahoj"}]))
        arts = extract_whatsapp_artifacts(p)
        assert len(arts) == 1

    def test_detector_positive(self):
        assert is_whatsapp_file("whatsapp/chats.json")
        assert is_whatsapp_file("WhatsAppBackups.json")

    def test_detector_negative_generic(self):
        assert not is_whatsapp_file("chats.json")


# ---------------------------------------------------------------------------
# Generic cloud metadata
# ---------------------------------------------------------------------------


class TestCloudGeneric:
    def test_parse_accounts(self):
        data = json.dumps([{"accountName": "jan@x.cz", "provider": "Google"}]).encode()
        recs = parse_cloud_generic(data, kind_hint="accounts")
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "accounts"
        assert r.email == "jan@x.cz"
        assert r.provider == "Google"

    def test_parse_passwords(self):
        data = json.dumps(
            [{"service": "GitHub", "username": "mirda", "password": "sekret"}]
        ).encode()
        recs = parse_cloud_generic(data, kind_hint="passwords")
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "passwords"
        assert r.service == "GitHub"
        assert r.username == "mirda"

    def test_parse_connected_apps(self):
        data = json.dumps([{"appName": "Photos", "scope": "read"}]).encode()
        recs = parse_cloud_generic(data, kind_hint="apps")
        assert len(recs) == 1
        assert recs[0].kind == "apps"

    def test_parse_recent_devices(self):
        data = json.dumps([{"deviceName": "Pixel", "ipAddress": "5.6.7.8"}]).encode()
        recs = parse_cloud_generic(data, kind_hint="devices")
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "devices"
        assert r.device_name == "Pixel"

    def test_parse_timeline(self):
        data = json.dumps([{"event": "login", "actor": "jan@x.cz"}]).encode()
        recs = parse_cloud_generic(data, kind_hint="timeline")
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "timeline"
        assert r.event == "login"

    def test_parse_android_backups(self):
        data = json.dumps([{"packageName": "com.example.app", "sizeBytes": 2048}]).encode()
        recs = parse_cloud_generic(data, kind_hint="android_backup")
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "android_backup"
        assert r.package_name == "com.example.app"

    def test_parse_azure_vm(self):
        data = json.dumps(
            [{"vmName": "prod-1", "snapshotId": "snap-9", "sizeGb": 40.5}]
        ).encode()
        recs = parse_cloud_generic(data, kind_hint="azure_vm")
        assert len(recs) == 1
        r = recs[0]
        assert r.kind == "azure_vm"
        assert r.vm_name == "prod-1"

    def test_build_artifacts(self):
        data = json.dumps([{"service": "GitHub", "username": "mirda"}]).encode()
        arts = build_cloud_generic_artifacts(
            parse_cloud_generic(data, kind_hint="passwords")
        )
        assert len(arts) == 1

    def test_extract_roundtrip(self, tmp_path: Path):
        p = tmp_path / "AccountsInfo.json"
        p.write_text(json.dumps([{"accountName": "jan@x.cz"}]))
        arts = extract_cloud_generic_artifacts(p)
        assert len(arts) == 1

    def test_detector_positive(self):
        assert is_cloud_generic_file("CloudExport/AccountsInfo.json")
        assert is_cloud_generic_file("cloud/ConnectedApps.json")
        assert is_cloud_generic_file("cloud/AzureVirtualMachineSnapshots.json")

    def test_detector_negative_generic(self):
        # bez cloud markery nepadne (aby se nekradly cizí soubory)
        assert not is_cloud_generic_file("timeline.json")


# ---------------------------------------------------------------------------
# Gmail Messages
# ---------------------------------------------------------------------------


class TestGmailMessages:
    def test_parse_messages(self):
        data = json.dumps(
            [
                {
                    "from": "a@b.c",
                    "to": "d@e.f",
                    "subject": "Test",
                    "date": "2026-01-01T00:00:00Z",
                    "body": "telo",
                }
            ]
        ).encode()
        recs = parse_gmail_messages(data)
        assert len(recs) == 1
        r = recs[0]
        assert r.subject == "Test"
        assert r.sender == "a@b.c"
        assert r.recipient == "d@e.f"
        assert r.body == "telo"
        assert r.created_s is not None

    def test_build_artifacts(self):
        data = json.dumps([{"from": "a@b.c", "to": "d@e.f", "subject": "Test"}]).encode()
        arts = build_gmail_artifacts(parse_gmail_messages(data))
        assert len(arts) == 1

    def test_extract_roundtrip(self, tmp_path: Path):
        p = tmp_path / "GmailMessages.json"
        p.write_text(json.dumps([{"from": "a@b.c", "to": "d@e.f", "subject": "T"}]))
        arts = extract_gmail_artifacts(p)
        assert len(arts) == 1

    def test_detector_positive(self):
        assert is_gmail_file("gmail/messages.json")
        assert is_gmail_file("GmailMessages.json")

    def test_detector_negative_generic(self):
        assert not is_gmail_file("messages.json")


# ---------------------------------------------------------------------------
# Google Maps Labeled Places WR
# ---------------------------------------------------------------------------


class TestMapsLabeledPlaces:
    def test_parse_places(self):
        data = json.dumps(
            [
                {
                    "label": "Domov",
                    "name": "Můj dům",
                    "latitude": 50.1,
                    "longitude": 14.4,
                }
            ]
        ).encode()
        recs = parse_maps_labeled_places(data)
        assert len(recs) == 1
        r = recs[0]
        assert r.label == "Domov"
        assert r.name == "Můj dům"
        assert r.latitude == pytest.approx(50.1)
        assert r.longitude == pytest.approx(14.4)

    def test_build_artifacts(self):
        data = json.dumps([{"label": "Práce", "latitude": 50.2, "longitude": 14.5}]).encode()
        arts = build_maps_labeled_artifacts(parse_maps_labeled_places(data))
        assert len(arts) == 1

    def test_extract_roundtrip(self, tmp_path: Path):
        p = tmp_path / "LabeledPlaces.json"
        p.write_text(json.dumps([{"label": "Domov", "latitude": 50.1}]))
        arts = extract_maps_labeled_artifacts(p)
        assert len(arts) == 1

    def test_detector_positive(self):
        assert is_maps_labeled_file("maps/labeled_places.json")
        assert is_maps_labeled_file("GoogleMapsLabeledPlacesWarrantReturn.json")

    def test_detector_negative_generic(self):
        assert not is_maps_labeled_file("places.json")


# ---------------------------------------------------------------------------
# Dispatch pre-pass routing (vlna 14)
# ---------------------------------------------------------------------------


class TestWave14Dispatch:
    @pytest.fixture()
    def pipeline(self):
        from stopa import pipeline

        return pipeline

    def test_apple_contacts_routes(self, pipeline):
        r = pipeline._sns_prepass("/case/AppleCloudExport/contacts.json")
        assert r is not None
        assert r[0].__name__ == "extract_apple_cloud_artifacts"

    def test_icloud_keychain_routes(self, pipeline):
        r = pipeline._sns_prepass("/case/icloud/keychain_export.json")
        assert r is not None
        assert r[0].__name__ == "extract_apple_cloud_artifacts"

    def test_google2025_accesslog_routes(self, pipeline):
        r = pipeline._sns_prepass("/case/GoogleAccessLogDevices2025.json")
        assert r is not None
        assert r[0].__name__ == "extract_google_2025_artifacts"

    def test_google2025_targetassoc_routes(self, pipeline):
        r = pipeline._sns_prepass("/case/AccountTargetAssociation2025.json")
        assert r is not None
        assert r[0].__name__ == "extract_google_2025_artifacts"

    def test_whatsapp_routes(self, pipeline):
        r = pipeline._sns_prepass("/case/whatsapp/chats.json")
        assert r is not None
        assert r[0].__name__ == "extract_whatsapp_artifacts"

    def test_gmail_routes(self, pipeline):
        r = pipeline._sns_prepass("/case/gmail/messages.json")
        assert r is not None
        assert r[0].__name__ == "extract_gmail_artifacts"

    def test_maps_labeled_routes(self, pipeline):
        r = pipeline._sns_prepass("/case/maps/labeled_places.json")
        assert r is not None
        assert r[0].__name__ == "extract_maps_labeled_artifacts"

    def test_cloud_generic_accounts_routes(self, pipeline):
        r = pipeline._sns_prepass("/case/CloudExport/AccountsInfo.json")
        assert r is not None
        assert r[0].__name__ == "extract_cloud_generic_artifacts"

    def test_cloud_generic_azure_routes(self, pipeline):
        r = pipeline._sns_prepass("/case/cloud/AzureVirtualMachineSnapshots.json")
        assert r is not None
        assert r[0].__name__ == "extract_cloud_generic_artifacts"

    def test_generic_basenames_not_stolen(self, pipeline):
        # generic basenames bez cloud markery nepadnou do cloud_generic
        for name in ("timeline.json", "passwords.json", "accounts.json"):
            r = pipeline._sns_prepass(f"/case/{name}")
            if r is not None:
                assert r[0].__name__ != "extract_cloud_generic_artifacts"

    def test_older_waves_keep_order(self, pipeline):
        # vlna 13 (box) drží pořadí před vlnou 14
        r = pipeline._sns_prepass("/case/box_files_export.json")
        assert r is not None
        assert r[0].__name__ == "extract_box_artifacts"


# ---------------------------------------------------------------------------
# C3 registry (vlna 14)
# ---------------------------------------------------------------------------


class TestWave14Registry:
    def test_registry_count(self):
        # 70 (po vlně 13) + 6 = min. 76 parserů (další vlny přidávají další)
        from stopa.domain.validation_registry import build_registry

        reg = build_registry()
        assert len(reg) >= 76

    def test_wave14_records_present(self):
        from stopa.domain.validation_registry import build_registry

        reg = build_registry()
        for pid in (
            "apple_cloud",
            "google_2025_wr",
            "whatsapp_cloud",
            "cloud_generic",
            "gmail_messages",
            "maps_labeled_places",
        ):
            assert pid in reg, f"chybí C3 záznam {pid}"
