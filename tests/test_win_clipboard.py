"""ETAPA B vlna 1 — testy Windows Clipboard registry parseru.

ČISTÉ funkce (_decode_value / build_clipboard_artifacts) + IO entrypoint
(extract_clipboard_artifacts přes monkeypatchovaný regipy.RegistryHive).
Žádný reálný NTUSER.DAT, žádné sítě.
"""

from __future__ import annotations

from stopa.artifacts.win_clipboard import (
    KNOWN_CF_FORMATS,
    PARSER_VERSION,
    _decode_value,
    build_clipboard_artifacts,
    extract_clipboard_artifacts,
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


CLIP_KEYS = [
    FakeKey(
        "Software\\Microsoft\\Windows\\CurrentVersion\\Clipboards",
        values=[
            FakeValue("(default)", None),  # default se ignoruje
            FakeValue("000D", "Tajné heslo: hunter2"),
            FakeValue("0001", b"\x00\x01\x02\xff\xfe\xfd"),  # binární
        ],
    ),
]


# ── _decode_value (čistá funkce) ──────────────────────────────────────

def test_decode_str():
    text, is_bin = _decode_value("hello world")
    assert text == "hello world" and is_bin is False


def test_decode_bytes_utf16le_text():
    raw = "Přihlašovací jméno".encode("utf-16-le")
    text, is_bin = _decode_value(raw)
    assert text == "Přihlašovací jméno" and is_bin is False


def test_decode_bytes_binary_hex_preview():
    # \xff\xfe\xfd\xfc — selže UTF-8 (invalid) i UTF-16LE (U+FEFF není tisknutelný) → hex
    text, is_bin = _decode_value(b"\xff\xfe\xfd\xfc")
    assert is_bin is True
    assert text == "fffe fd fc".replace(" ", "")  # hex preview


def test_decode_none():
    assert _decode_value(None) == ("", False)


# ── build_clipboard_artifacts (čistá funkce) ──────────────────────────

def test_build_artifacts_known_format():
    from stopa.artifacts.win_clipboard import ClipboardEntry

    arts = build_clipboard_artifacts(
        [ClipboardEntry(format_id="000D", format_name=KNOWN_CF_FORMATS["000D"], data_text="abc")]
    )
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "clipboard_entry"
    assert a.parser_version == PARSER_VERSION
    assert a.details.get("format") == "CF_UNICODETEXT"
    assert a.details.get("data") == "abc"


def test_build_artifacts_unknown_format_label():
    from stopa.artifacts.win_clipboard import ClipboardEntry

    arts = build_clipboard_artifacts([ClipboardEntry(format_id="00FF", data_text="x")])
    # neznámý formát → CF_<id> label
    assert arts[0].details.get("format") == "CF_00FF"


def test_build_artifacts_empty():
    assert build_clipboard_artifacts([]) == []


# ── extract_clipboard_artifacts (IO přes fake hive) ───────────────────

def test_extract_clipboards_key(monkeypatch):
    monkeypatch.setattr("regipy.registry.RegistryHive", lambda **kw: FakeHive(CLIP_KEYS))
    arts = extract_clipboard_artifacts("/fake/NTUSER.DAT")
    # (default) se ignoruje → 2 záznamy
    assert len(arts) == 2
    formats = {a.details.get("format_id") for a in arts}
    assert formats == {"000D", "0001"}


def test_extract_no_clipboards_key(monkeypatch):
    other = [FakeKey("Software\\Microsoft\\Windows\\CurrentVersion\\Run")]
    monkeypatch.setattr("regipy.registry.RegistryHive", lambda **kw: FakeHive(other))
    assert extract_clipboard_artifacts("/fake/NTUSER.DAT") == []


def test_extract_missing_file(monkeypatch):
    def _raise(**_kw):
        raise FileNotFoundError("no hive")

    monkeypatch.setattr("regipy.registry.RegistryHive", _raise)
    assert extract_clipboard_artifacts("/fake/nope.dat") == []


def test_extract_hive_error(monkeypatch):
    def _raise(**_kw):
        raise ValueError("corrupt hive")

    monkeypatch.setattr("regipy.registry.RegistryHive", _raise)
    # chyba hive → prázdný výsledek (ne výjimka — ostatní extraktory běží dál)
    assert extract_clipboard_artifacts("/fake/bad.dat") == []


def test_extract_alternative_subkey_structure(monkeypatch):
    """Alternativní struktura: Clipboards\\<fmt> podklíče s hodnotou Data."""
    keys = [
        FakeKey(
            "Software\\Microsoft\\Windows\\CurrentVersion\\Clipboards\\000D",
            values=[FakeValue("Data", "text z podklíče")],
        ),
    ]
    monkeypatch.setattr("regipy.registry.RegistryHive", lambda **kw: FakeHive(keys))
    arts = extract_clipboard_artifacts("/fake/NTUSER.DAT")
    assert len(arts) == 1
    assert arts[0].details.get("format_id") == "000D"
    assert arts[0].details.get("data") == "text z podklíče"
