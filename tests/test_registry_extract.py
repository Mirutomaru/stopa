"""Testy registry hive extraktoru — FÁZE 4b.

ČISTÉ funkce testujeme nad fake objekty (žádný regipy, žádné IO).
IO wrapper testujeme na reálných souborech (ne-hive → defenzivní []).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from stopa.artifacts.registry_extract import build_registry_artifacts


class FakeValue:
    def __init__(self, name: str, value):
        self.name = name
        self.value = value


class FakeSubkey:
    """Imituje regipy Subkey — .path / .timestamp / .values."""

    def __init__(self, path: str, timestamp=None, values=None):
        self.path = path
        self.timestamp = timestamp
        self.values = values or []


TS = datetime(2024, 3, 15, 12, 34, 56, tzinfo=UTC)

RUN_KEY = FakeSubkey(
    r"\Software\Microsoft\Windows\CurrentVersion\Run",
    timestamp=TS,
    values=[FakeValue("CCleaner", b"C:\\Program Files\\CCleaner\\ccleaner64.exe")],
)
MOUNTED_DEVICES = FakeSubkey(
    r"\MountedDevices",
    timestamp=TS,
    values=[
        FakeValue("\\DosDevices\\PhysicalDrive1", "\\Device\\Harddisk1\\Partition2"),
        FakeValue("USBSTOR\\DISK_0", "\\Device\\Ide\\IdePort0"),
    ],
)
USER_NAME = FakeSubkey(
    r"\Control Panel\User Name",
    timestamp=TS,
    values=[FakeValue("", "Gamer")],  # Default value (prázdné jméno)
)
ENV_KEY = FakeSubkey(
    r"\Environment",
    timestamp=TS,
    values=[FakeValue("PATH", b"C:\\Windows;C:\\bin"), FakeValue("USERPROFILE", b"C:\\Users\\Gamer")],
)
PLAIN_KEY = FakeSubkey(r"\Some\Random\Key", timestamp=TS, values=[FakeValue("X", "1")])
EMPTY_CONTAINER = FakeSubkey(r"\Software\Microsoft\Windows\CurrentVersion\Run", timestamp=TS)


class TestBuildRegistryArtifacts:
    def test_run_key_is_persistence(self):
        arts = build_registry_artifacts([RUN_KEY])
        assert len(arts) == 1
        a = arts[0]
        assert a.artifact_type == "registry_persistence"
        assert a.timestamp == TS
        assert "CCleaner" in a.details["values"]
        # bytes hodnota decode do textu
        assert isinstance(a.details["values"]["CCleaner"], str)

    def test_mounted_devices_is_usb(self):
        arts = build_registry_artifacts([MOUNTED_DEVICES])
        assert len(arts) == 1
        assert arts[0].artifact_type == "registry_usb_device"
        assert len(arts[0].details["values"]) == 2

    def test_user_name_is_user_info(self):
        arts = build_registry_artifacts([USER_NAME])
        assert len(arts) == 1
        assert arts[0].artifact_type == "registry_user_info"
        # Default value (prázdné jméno) se serializuje jako "(Default)"
        assert arts[0].details["values"]["(Default)"] == "Gamer"

    def test_environment_key(self):
        arts = build_registry_artifacts([ENV_KEY])
        assert len(arts) == 1
        assert arts[0].artifact_type == "registry_environment"
        assert arts[0].details["values"]["USERPROFILE"] == "C:\\Users\\Gamer"

    def test_plain_key_ignored(self):
        # klíč mimo INTERESTING_KEY_PATTERNS → žádný artifact
        assert build_registry_artifacts([PLAIN_KEY]) == []

    def test_empty_container_skipped(self):
        # Run klíč bez hodnot (jen kontejner) → ignorovat
        assert build_registry_artifacts([EMPTY_CONTAINER]) == []

    def test_mixed_keys_only_interesting_extracted(self):
        arts = build_registry_artifacts([RUN_KEY, PLAIN_KEY, MOUNTED_DEVICES, USER_NAME])
        types = [a.artifact_type for a in arts]
        assert "registry_persistence" in types
        assert "registry_usb_device" in types
        assert "registry_user_info" in types
        # plain key se nedostane do výstupu
        assert len(arts) == 3

    def test_path_with_forward_slashes(self):
        # cesty s / (normalizace) — shoda i tak
        fwd = FakeSubkey(
            "/Software/Microsoft/Windows/CurrentVersion/Run",
            timestamp=TS,
            values=[FakeValue("X", "y")],
        )
        arts = build_registry_artifacts([fwd])
        assert len(arts) == 1
        assert arts[0].artifact_type == "registry_persistence"

    def test_long_value_truncated(self):
        long_val = FakeSubkey(
            r"\Environment",
            timestamp=TS,
            values=[FakeValue("HUGE", b"A" * 500)],
        )
        arts = build_registry_artifacts([long_val])
        assert len(arts[0].details["values"]["HUGE"]) == 200

    def test_none_value_serialized_empty(self):
        k = FakeSubkey(r"\Environment", timestamp=TS, values=[FakeValue("NUL", None)])
        arts = build_registry_artifacts([k])
        assert arts[0].details["values"]["NUL"] == ""


class TestExtractRegistryArtifactsIO:
    def test_non_hive_file_returns_empty(self, tmp_path: Path):
        """Soubor s regf magic ale jinak poškozený → defenzivní [], ne výjimka."""
        from stopa.artifacts.registry_extract import extract_registry_artifacts

        p = tmp_path / "broken.hive"
        p.write_bytes(b"regf" + b"\x01\x02\x03\x04" * 64)  # regf magic, ale neplatná struktura
        assert extract_registry_artifacts(p) == []

    def test_missing_file_returns_empty(self, tmp_path: Path):
        from stopa.artifacts.registry_extract import extract_registry_artifacts

        assert extract_registry_artifacts(tmp_path / "chybi.hive") == []


class TestTriageArtifact:
    def test_triage_counts_and_top_keys(self):
        from stopa.artifacts.registry_extract import _triage_artifact

        keys = [
            FakeSubkey(r"\Software\A", values=[]),
            FakeSubkey(r"\Software\B", values=[]),
            FakeSubkey(r"\System\C", values=[]),
            FakeSubkey(r"\SAM\D", values=[]),
        ]
        art = _triage_artifact(iter(keys))
        assert art.artifact_type == "registry_hive"
        assert art.details["key_count"] == 4
        # top-level jména bez vedoucího \\, deduplikované
        assert set(art.details["top_level_keys"]) <= {"Software", "System", "SAM"}
