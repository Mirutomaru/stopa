"""P0.3 — jednotná správa dočasných dešifrovaných obrazů (temp_images).

Zlaté testy abstrakce: izolované úložiště 0700/0600, garantovaný cleanup při
úspěchu i výjimce, detach/release kontrakt, auditní callbacky, disk-space
kontrola, reaper osiřelých souborů a temp_secret_file (scénář P0.2 LUKS keyfile).

Vše offline + deterministické: vlastní base_dir přes parametr, registry čisté
fixturem mezi testy.
"""

import os
import tempfile
import time
from pathlib import Path

import pytest

from stopa.domain.temp_images import (
    _REGISTRY,
    EncryptedTempImage,
    TempImageError,
    _zero_fill,
    reap_orphans,
    registry_snapshot,
    release_temp,
    temp_base_dir,
    temp_secret_file,
)


@pytest.fixture(autouse=True)
def clean_registry():
    """Registry je modulová — mezi testy čistá (žádné křížové kontaminace)."""
    for key in list(_REGISTRY):
        del _REGISTRY[key]
    yield
    for key in list(_REGISTRY):
        del _REGISTRY[key]


@pytest.fixture()
def stopa_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Izolované STOPA_TMP_DIR pro test (ne znečišťuje reálné $TMPDIR/stopa-tmp)."""
    base = tmp_path / "stopatmp"
    monkeypatch.setenv("STOPA_TMP_DIR", str(base))
    return base


class TestCreateAndPermissions:
    def test_created_in_isolated_dir_with_0700(self, stopa_dir: Path) -> None:
        with EncryptedTempImage(prefix="stopa-test-", suffix=".img", owner="t1") as t:
            p = t.path
            assert p.parent == stopa_dir
            # dir 0700 (izolace), soubor od mkstemp 0600
            assert (p.parent.stat().st_mode & 0o777) == 0o700
            assert (p.stat().st_mode & 0o777) == 0o600

    def test_registry_record_fields(self, stopa_dir: Path) -> None:
        with EncryptedTempImage(prefix="stopa-test-", owner="t1"):
            recs = registry_snapshot()
            assert len(recs) == 1
            assert recs[0].owner == "t1"
            assert recs[0].prefix == "stopa-test-"
            assert not recs[0].detached

    def test_default_base_dir_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STOPA_TMP_DIR", str(tmp_path / "custom"))
        assert temp_base_dir() == tmp_path / "custom"
        monkeypatch.delenv("STOPA_TMP_DIR")
        # gettempdir() si cacheuje výsledek — reset cache, ať se TMPDIR znovu vyhodnotí
        monkeypatch.setattr(tempfile, "tempdir", None)
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        assert temp_base_dir() == tmp_path / "stopa-tmp"

    def test_open_twice_raises(self, stopa_dir: Path) -> None:
        t = EncryptedTempImage(prefix="stopa-test-")
        with pytest.raises(TempImageError, match="dvakrát"), t:
            t.open()


class TestCleanupGuarantees:
    def test_cleanup_on_success(self, stopa_dir: Path) -> None:
        t = EncryptedTempImage(prefix="stopa-test-")
        p: Path | None = None
        with t as img:
            p = img.path
            assert p.exists()
        assert p is not None and not p.exists()
        assert registry_snapshot() == ()

    def test_cleanup_on_exception_and_propagation(self, stopa_dir: Path) -> None:
        p: Path | None = None
        cm = EncryptedTempImage(prefix="stopa-test-")
        with pytest.raises(ValueError, match="boom"), cm as img:
            p = img.path
            raise ValueError("boom")
        assert p is not None and not p.exists()  # výjimka se propisuje I soubor je pryč

    def test_take_fd_no_double_close_on_exit(self, stopa_dir: Path) -> None:
        """Streaming vzorec: os.fdopen(take_fd()) — exit nesmí zavřít dvakrát."""
        p: Path | None = None
        with EncryptedTempImage(prefix="stopa-test-") as t:
            fd = t.take_fd()
            with os.fdopen(fd, "wb") as f:
                f.write(b"\x01" * 4096)
            p = t.path
        assert p is not None and not p.exists()  # cleanup fungoval bez double-close chyb

    def test_take_fd_without_open_raises(self, stopa_dir: Path) -> None:
        with pytest.raises(TempImageError):
            EncryptedTempImage().take_fd()

    def test_path_before_open_raises(self, stopa_dir: Path) -> None:
        with pytest.raises(TempImageError, match="před open"):
            _ = EncryptedTempImage().path  # property getter musí zvednout chybu


class TestDetachReleaseContract:
    def test_detach_keeps_file_release_removes(self, stopa_dir: Path) -> None:
        events: list[tuple[str, dict]] = []

        def audit(event_type: str, details: dict) -> None:
            events.append((event_type, details))

        t = EncryptedTempImage(prefix="stopa-test-", owner="detach", audit=audit)
        p: Path | None = None
        with t as img:
            p = img.detach()
        # po exitu soubor STÁLE existuje (ownership u volajícího)
        assert p is not None and p.exists()
        recs = registry_snapshot()
        assert len(recs) == 1 and recs[0].detached

        release_temp(p, audit=audit)
        assert not p.exists()
        assert [e for e, _ in events] == ["temp_created", "temp_removed"]

    def test_release_idempotent(self, stopa_dir: Path) -> None:
        p: Path | None = None
        with EncryptedTempImage(prefix="stopa-test-") as img:
            p = img.detach()
        assert p is not None
        release_temp(p)
        release_temp(p)  # druhý vol = no-op bez výjimky

    def test_release_unknown_path_noop(self, stopa_dir: Path) -> None:
        release_temp(stopa_dir / "neznamy.img")  # bez výjimky


class TestAuditAndDisk:
    def test_audit_failure_does_not_break_lifecycle(self, stopa_dir: Path) -> None:
        def bad_audit(event_type: str, details: dict) -> None:
            raise RuntimeError("audit DB down")

        with EncryptedTempImage(prefix="stopa-test-", audit=bad_audit) as img:
            p = img.path
        assert not p.exists()  # životní cyklus přežil auditní selhání

    def test_expected_size_insufficient(self, stopa_dir: Path) -> None:
        with pytest.raises(TempImageError, match="Nedostatek místa"):
            EncryptedTempImage(prefix="stopa-test-", expected_size=2**63).open()


class TestZeroFillAndReaper:
    def test_zero_fill_clears_content(self, tmp_path: Path) -> None:
        p = tmp_path / "zero.img"
        p.write_bytes(b"A" * 10_000)
        _zero_fill(p)
        assert p.read_bytes() == b"\x00" * 10_000

    def test_reaper_cleans_old_orphans_only(self, stopa_dir: Path) -> None:
        stopa_dir.mkdir(parents=True, exist_ok=True)
        old = stopa_dir / "stopa-fde-old.img"
        old.write_bytes(b"x")
        fresh = stopa_dir / "stopa-fde-new.img"
        fresh.write_bytes(b"x")
        foreign = stopa_dir / "cizi-soubor.img"
        foreign.write_bytes(b"x")

        # starý mtime (2 dny) — jen u orphanů, ne u aktivního objektu
        old_ts = time.time() - 2 * 86400
        os.utime(old, (old_ts, old_ts))
        os.utime(foreign, (old_ts, old_ts))

        # aktivní registrovaný objekt se starým mtime — reaper ho musí NECHAT
        active = EncryptedTempImage(prefix="stopa-test-", owner="active")
        fd, _name = active.open()
        os.close(fd)  # obsah nezáleží — jen existence v registru
        os.utime(active.path, (old_ts, old_ts))
        events: list[tuple[str, dict]] = []
        try:
            reaped = reap_orphans(base_dir=stopa_dir, audit=lambda e, d: events.append((e, d)))
        finally:
            release_temp(active.path)  # aktivní se uklidí až teď

        assert set(reaped) == {old}  # starý orphan pryč; čerstvý + cizí + aktivní zůstaly
        assert not old.exists()
        assert fresh.exists() and foreign.exists()
        assert [e for e, _ in events] == ["temp_orphans_reaped"]

    def test_reaper_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        assert reap_orphans(base_dir=tmp_path / "neni") == []


class TestSecretFileP02:
    """Scénář P0.2 — LUKS keyfile: životnost = kontext, úklid i při výjimce."""

    def test_secret_file_cleanup_on_success(self, stopa_dir: Path) -> None:
        with temp_secret_file(prefix="stopa-luks-key-", suffix=".bin", owner="fde_luks") as kf:
            kf.write_bytes(b"tajne-heslo")
            assert (kf.stat().st_mode & 0o777) == 0o600
        assert not kf.exists()

    def test_secret_file_cleanup_on_exception(self, stopa_dir: Path) -> None:
        """cryptsetup open zvedne výjimku → keyfile nesmí zůstat ležet."""
        cm = temp_secret_file(prefix="stopa-luks-key-", owner="fde_luks")
        with pytest.raises(OSError, match="cryptsetup"), cm as kf:
            kf.write_bytes(b"tajne-heslo")
            raise OSError("cryptsetup open selhalo")
        assert not kf.exists()
