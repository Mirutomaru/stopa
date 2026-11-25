"""P0.3 — jednotná správa dočasných dešifrovaných obrazů a tajných souborů.

Všechny FDE cesty (FDE/BDE/FVDE/BitLocker/EWF/LUKS) dříve volaly ``mkstemp``
každá jinak; úklid závisel na paměti volajícího. Tato abstrakce dává:

- **kontextový manager** s garantovaným cleanupem (úspěch i výjimka),
- **izolované dočasné úložiště** (env ``STOPA_TMP_DIR``, jinak ``$TMPDIR/stopa-tmp``)
  s právy 0700, jednotlivé soubory od ``mkstemp`` 0600,
- **evidování** v modulem registru (dočasné objekty vidí dashboard i reaper),
- **auditní callbacky** ``temp_created`` / ``temp_removed``,
- **kontrolu diskového prostoru** před vytvořením (``expected_size``),
- **obnovu osiřelých souborů při startu** — :func:`reap_orphans`.

Poznámka k sanitizaci: zero-fill + unlink je *best effort* — na SSD, copy-on-write
a žurnálovacích FS není obyčejný unlink ani přepsání zaručenou sanitizací.
Pro plnou záruku použijte šifrované dočasné úložiště nebo tmpfs (``STOPA_TMP_DIR``).

Vrstva: ``domain`` (sdílená abstrakce pro FDE moduly v domain i data).
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)

AuditFn = Callable[[str, dict[str, object]], None]  # (event_type, details) → audit DB


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def temp_base_dir() -> Path:
    """Izolované dočasné úložiště STOPA — env ``STOPA_TMP_DIR``, jinak ``$TMPDIR/stopa-tmp``."""
    env = os.environ.get("STOPA_TMP_DIR")
    if env:
        return Path(env)
    return Path(tempfile.gettempdir()) / "stopa-tmp"


class TempImageError(OSError):
    """Chyba správy dočasného dešifrovaného obrazu (prostor, oprávnění, registry)."""


@dataclass(frozen=True)
class TempObjectRecord:
    """Záznam v registru dočasných objektů (evidování + dashboard)."""

    path: str
    prefix: str
    owner: str
    created_at_utc: str
    size_bytes: int = 0
    detached: bool = False  # ownership předán volajícímu (release_temp / reaper)


_REGISTRY: dict[str, TempObjectRecord] = {}
_LOCK = threading.Lock()  # registry sdílí proces; thread-safety levná pojistka


def _register(rec: TempObjectRecord) -> None:
    with _LOCK:
        if rec.path in _REGISTRY:
            _log.warning("[stopa-temp] dvojité evidování objektu %s (současná použití?)", rec.path)
        _REGISTRY[rec.path] = rec


def _deregister(path: str) -> TempObjectRecord | None:
    with _LOCK:
        return _REGISTRY.pop(path, None)


def registry_snapshot() -> tuple[TempObjectRecord, ...]:
    """Aktuální stav registru (pro integrity dashboard)."""
    with _LOCK:
        return tuple(sorted(_REGISTRY.values(), key=lambda r: r.created_at_utc))


def _zero_fill(p: Path) -> None:
    """Best-effort zero-fill (SSD/COW — viz modul docstring). Tichá při chybě."""
    try:
        size = p.stat().st_size
        if size <= 0:
            return
        with open(p, "r+b") as f:
            step = min(4 * 1024 * 1024, size)
            zeros = b"\x00" * step
            remaining = size
            while remaining > 0:
                n = min(step, remaining)
                f.write(zeros[:n])
                remaining -= n
            f.flush()
            os.fsync(f.fileno())
    except OSError as e:
        _log.debug("[stopa-temp] zero-fill %s selhal (nekritické): %s", p, e)


def release_temp(path: Path | str, audit: AuditFn | None = None) -> None:
    """Převezme ownership a uklidí objekt: zero-fill + fsync + unlink + audit.

    Používá volající, kterému byl objekt ``detach()``-nut (nebo který drží cestu
    z legacy kódu). Idempotentní — druhý vol s tímto souborem je no-op.
    """
    p = Path(path)
    rec = _deregister(str(p))
    if not p.exists() and rec is None:
        return  # už uklizené (idempotence)
    _zero_fill(p)
    try:
        p.unlink(missing_ok=True)
    except OSError as e:
        raise TempImageError(f"Úklid dočasného souboru selhal: {p}") from e
    if audit is not None and rec is not None:
        try:
            audit("temp_removed", {"path": str(p), "owner": rec.owner, "size_bytes": rec.size_bytes})
        except Exception as e:  # noqa: BLE001 — audit nemá zabít úklid
            _log.warning("[stopa-temp] audit temp_removed selhal (nekritické): %s", e)


class EncryptedTempImage:
    """Jednotný dočasný dešifrovaný obraz / tajný soubor (kontextový manager).

    Použití::

        with EncryptedTempImage(prefix="stopa-fde-", suffix=".img") as t:
            fd, name = t.open()          # jako mkstemp — volající píše přes fd
            ...streaming...
            t.detach()                   # ownership předat volajícímu (volá release_temp)

    Bez ``detach()`` při exitu automaticky zero-fill + unlink + audit.
    """

    def __init__(
        self,
        prefix: str = "stopa-",
        suffix: str = ".img",
        base_dir: Path | str | None = None,
        expected_size: int | None = None,
        owner: str = "",
        audit: AuditFn | None = None,
    ) -> None:
        self._prefix = prefix
        self._suffix = suffix
        self._base_dir = Path(base_dir) if base_dir is not None else temp_base_dir()
        self._expected_size = expected_size
        self._owner = owner or f"stopa-{os.getpid()}"
        self._audit = audit
        self._fd: int | None = None
        self._path: Path | None = None
        self._detached = False
        self._created_at = _utc_iso()

    # ── životní cyklus ────────────────────────────────────────────
    def open(self) -> tuple[int, str]:
        """Vytvoří soubor (mkstemp v izolovaném diru) a vrátí ``(fd, cesta)``.

        Kontroluje dostupný diskový prostor při ``expected_size``; registr +
        audit ``temp_created`` se provedou tady. Idempotentní volání = chyba.
        """
        if self._path is not None:
            raise TempImageError("EncryptedTempImage.open() zavoláno dvakrát")
        base = self._base_dir
        try:
            base.mkdir(parents=True, exist_ok=True)
            os.chmod(base, 0o700)  # izolace — jen vlastníč (idempotentní)
        except OSError as e:
            raise TempImageError(f"Dočasné úložiště nedostupné: {base}") from e
        if self._expected_size is not None and self._expected_size > 0:
            try:
                free = shutil.disk_usage(base).free
            except OSError as e:
                raise TempImageError(f"Kontrola disku selhala pro {base}: {e}") from e
            if free < self._expected_size:
                raise TempImageError(
                    f"Nedostatek místa v {base}: volné {free} B, potřeba {self._expected_size} B"
                )
        fd, name = tempfile.mkstemp(suffix=self._suffix, prefix=self._prefix, dir=str(base))
        self._fd = fd
        self._path = Path(name)
        rec = TempObjectRecord(
            path=str(self._path),
            prefix=self._prefix,
            owner=self._owner,
            created_at_utc=self._created_at,
        )
        _register(rec)
        if self._audit is not None:
            try:
                self._audit("temp_created", {"path": str(self._path), "owner": self._owner})
            except Exception as e:  # noqa: BLE001 — audit nemá zabít vytvoření
                _log.warning("[stopa-temp] audit temp_created selhal (nekritické): %s", e)
        return fd, name

    @property
    def path(self) -> Path:
        """Cesta k dočasnému souboru (po ``open()``)."""
        if self._path is None:
            raise TempImageError("EncryptedTempImage použit před open()/__enter__()")
        return self._path

    @property
    def fd(self) -> int:
        """File descriptor z ``mkstemp`` (pro ``os.fdopen(fd, "wb")``)."""
        if self._fd is None:
            raise TempImageError("EncryptedTempImage.open() ještě nepadlo")
        return self._fd

    def take_fd(self) -> int:
        """Odebere ownership file descriptoru (volající ho uzavře přes ``os.fdopen``).

        Bez tohoto volání by ``__exit__`` zavřel fd za volajícím — při
        ``os.fdopen(fd, "wb")`` by došlo k dvojitému close.
        """
        if self._fd is None:
            raise TempImageError("take_fd() bez open()/__enter__() nebo dvakrát")
        fd, self._fd = self._fd, None
        return fd

    def detach(self) -> Path:
        """Předá ownership volajícímu — exit už soubor neuklidí.

        Volající je povinen později zavolat :func:`release_temp` (nebo reaper
        při startu procesy zachytí osiřelý objekt).
        """
        if self._path is None:
            raise TempImageError("detach() před open()/__enter__()")
        self._detached = True
        rec = _REGISTRY.get(str(self._path))
        if rec is not None:
            with _LOCK:
                _REGISTRY[str(self._path)] = TempObjectRecord(
                    path=rec.path, prefix=rec.prefix, owner=rec.owner,
                    created_at_utc=rec.created_at_utc, size_bytes=rec.size_bytes, detached=True,
                )
        return self._path

    def __enter__(self) -> EncryptedTempImage:  # noqa: PYI034 — vrací self; Self až s typing_extensions/3.11
        self.open()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: object) -> bool:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError as e:
                _log.debug("[stopa-temp] close fd selhal (nekritické): %s", e)
        if self._path is not None and not self._detached:
            size = 0
            try:
                size = self._path.stat().st_size
            except OSError:
                # soubor mohl mezi close a stat zmizet → size=0, unlink níže missing_ok — H1
                pass
            _zero_fill(self._path)
            try:
                self._path.unlink(missing_ok=True)
            except OSError as e:
                raise TempImageError(f"Úklid dočasného souboru selhal: {self._path}") from e
            rec = _deregister(str(self._path))
            if self._audit is not None and rec is not None:
                try:
                    self._audit(
                        "temp_removed",
                        {"path": str(self._path), "owner": self._owner,
                         "size_bytes": size, "error": exc_type.__name__ if exc_type else ""},
                    )
                except Exception as e:  # noqa: BLE001 — audit nemá zabít exit
                    _log.warning("[stopa-temp] audit temp_removed selhal (nekritické): %s", e)
        return False  # výjimky se propisují


def reap_orphans(
    base_dir: Path | str | None = None,
    max_age_seconds: int = 24 * 3600,
    audit: AuditFn | None = None,
) -> list[Path]:
    """Obnova po crashu/výpadku: najde a uklidí osiřelé dočasné soubory.

    Volat při startu procesů (CLI main / web startup). Kriterium: soubor v
    izolovaném úložišti s prefixem ``stopa-`` starší než ``max_age_seconds``,
    který není v aktivním registru (nebo je označen detached a starý).
    Vrací seznam uklizených cest (volající může auditovat agregátně).
    """
    base = Path(base_dir) if base_dir is not None else temp_base_dir()
    if not base.is_dir():
        return []
    now = time.time()
    reaped: list[Path] = []
    for entry in sorted(base.iterdir()):
        try:
            if not entry.is_file() or not entry.name.startswith("stopa-"):
                continue
            age = now - entry.stat().st_mtime
            if age < max_age_seconds:
                continue
            rec = _REGISTRY.get(str(entry))
            # aktivní (nedetached) objekt v registru nechejme — běží zpracování
            if rec is not None and not rec.detached:
                continue
        except OSError as e:
            _log.debug("[stopa-temp] reaper: nepochopitelný entry %s: %s", entry, e)
            continue
        release_temp(entry, audit=audit)
        reaped.append(entry)
    if reaped and audit is not None:
        try:
            audit("temp_orphans_reaped", {"count": len(reaped), "paths": [str(p) for p in reaped]})
        except Exception as e:  # noqa: BLE001 — audit nemá zabít reaper
            _log.warning("[stopa-temp] audit temp_orphans_reaped selhal (nekritické): %s", e)
    return reaped


@contextmanager
def temp_secret_file(
    prefix: str = "stopa-",
    suffix: str = ".bin",
    expected_size: int | None = None,
    owner: str = "",
    audit: AuditFn | None = None,
) -> Iterator[Path]:
    """Jednoduchý kontext pro tajné soubory (např. LUKS passphrase) — jen cesta."""
    with EncryptedTempImage(
        prefix=prefix, suffix=suffix, expected_size=expected_size, owner=owner, audit=audit
    ) as t:
        yield t.path
