"""ETAPA B vlna 1 — testy Windows SID extrakce z registry.

ČISTÉ funkce (_is_sid / build_sid_artifacts) + IO entrypoint
(extract_sid_artifacts přes monkeypatchovaný regipy.RegistryHive).
Žádný reálný SAM/NTUSER.DAT, žádné sítě.
"""

from __future__ import annotations

from stopa.artifacts.win_sids import (
    PARSER_VERSION,
    _is_sid,
    build_sid_artifacts,
    extract_sid_artifacts,
)

# ── fake regipy objekty ────────────────────────────────────────────────

class FakeValue:
    def __init__(self, name: str, value):
        self.name = name
        self.value = value


class FakeKey:
    def __init__(self, path: str, values=None, timestamp=None):
        self.path = path
        self.values = values or []
        self.timestamp = timestamp


class FakeHive:
    """Fake RegistryHive — recurse_subkeys() vrací předpřipravené klíče."""

    def __init__(self, keys: list[FakeKey]):
        self._keys = keys

    def recurse_subkeys(self):
        return iter(self._keys)


SAM_KEYS = [
    FakeKey(
        "Sam\\Domains\\Account\\Users\\S-1-5-21-1111111111-2222222222-3333333333-1001",
        values=[FakeValue("Name", "jan".encode("utf-16-le"))],
    ),
    FakeKey(
        "Sam\\Domains\\Account\\Users\\S-1-5-21-1111111111-2222222222-3333333333-500",
        values=[FakeValue("Name", b"Administrator")],  # UTF-8 fallback
    ),
]

PROFILE_KEYS = [
    FakeKey(
        "Microsoft\\Windows NT\\CurrentVersion\\ProfileList\\S-1-5-21-1111111111-2222222222-3333333333-1001",
        values=[FakeValue("ProfileImagePath", "C:\\Users\\jan".encode("utf-16-le"))],
    ),
]


# ── _is_sid (čistá funkce) ────────────────────────────────────────────

def test_is_sid_valid():
    assert _is_sid("S-1-5-21-1111111111-2222222222-3333333333-1001") is True
    assert _is_sid("S-1-5-32-544") is True


def test_is_sid_invalid():
    assert _is_sid("not-a-sid") is False
    assert _is_sid("") is False
    assert _is_sid("S-9-5-1") is False  # major version != 1


# ── build_sid_artifacts (čistá funkce) ────────────────────────────────

def test_build_sam_entry():
    from stopa.artifacts.win_sids import SidEntry

    arts = build_sid_artifacts(
        [SidEntry(sid="S-1-5-21-1111111111-2222222222-3333333333-1001", name="jan", source="sam")]
    )
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "user_sid"
    assert a.parser_version == PARSER_VERSION
    assert a.details.get("sid") == "S-1-5-21-1111111111-2222222222-3333333333-1001"
    assert a.details.get("name") == "jan"
    assert a.details.get("source") == "sam"


def test_build_dedup_same_sid():
    from stopa.artifacts.win_sids import SidEntry

    sid = "S-1-5-21-1111111111-2222222222-3333333333-1001"
    arts = build_sid_artifacts(
        [
            SidEntry(sid=sid, name="jan", source="sam"),
            SidEntry(sid=sid, name="", source="profile_list"),  # duplicita → skip
        ]
    )
    assert len(arts) == 1


def test_build_invalid_sid_skipped():
    from stopa.artifacts.win_sids import SidEntry

    arts = build_sid_artifacts([SidEntry(sid="not-a-sid", name="x", source="sam")])
    assert arts == []


def test_build_empty():
    assert build_sid_artifacts([]) == []


# ── extract_sid_artifacts (IO přes fake hive) ─────────────────────────

def test_extract_sam_users(monkeypatch):
    monkeypatch.setattr("regipy.registry.RegistryHive", lambda **kw: FakeHive(SAM_KEYS))
    arts = extract_sid_artifacts("/fake/SAM")
    assert len(arts) == 2
    names = {a.details.get("name") for a in arts}
    # UTF-16LE "jan" + UTF-8 fallback "Administrator"
    assert names == {"jan", "Administrator"}


def test_extract_profile_list(monkeypatch):
    monkeypatch.setattr("regipy.registry.RegistryHive", lambda **kw: FakeHive(PROFILE_KEYS))
    arts = extract_sid_artifacts("/fake/NTUSER.DAT")
    assert len(arts) == 1
    a = arts[0]
    # jméno uživatele extrahováno z cesty profilu (C:\\Users\\jan → jan)
    assert a.details.get("name") == "jan"
    assert a.details.get("source") == "profile_list"


def test_extract_no_sid_keys(monkeypatch):
    other = [FakeKey("Software\\Microsoft\\Windows\\CurrentVersion\\Run")]
    monkeypatch.setattr("regipy.registry.RegistryHive", lambda **kw: FakeHive(other))
    assert extract_sid_artifacts("/fake/NTUSER.DAT") == []


def test_extract_missing_file(monkeypatch):
    def _raise(**_kw):
        raise FileNotFoundError("no hive")

    monkeypatch.setattr("regipy.registry.RegistryHive", _raise)
    assert extract_sid_artifacts("/fake/nope.dat") == []


def test_extract_hive_error(monkeypatch):
    def _raise(**_kw):
        raise ValueError("corrupt hive")

    monkeypatch.setattr("regipy.registry.RegistryHive", _raise)
    # chyba hive → prázdný výsledek (ne výjimka — ostatní extraktory běží dál)
    assert extract_sid_artifacts("/fake/bad.dat") == []


def test_extract_sam_and_profile_combined(monkeypatch):
    """SAM + ProfileList dohromady — duplicitní SID se deduplikuje."""
    monkeypatch.setattr(
        "regipy.registry.RegistryHive", lambda **kw: FakeHive(SAM_KEYS + PROFILE_KEYS)
    )
    arts = extract_sid_artifacts("/fake/SAM")
    # 2 SAM uživatele; profilový SID je duplicita s prvním → celkem 2
    assert len(arts) == 2
