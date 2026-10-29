"""Forenzní časové konverze — ČISTÁ logika, bez IO.

Každý browser/OS má jinou epochu a jednotku:
- Unix (Linux/macOS/iPhone): sekundy od 1970-01-01 UTC
- Windows FILETIME: 100ns intervaly od 1601-01-01 UTC
- Chrome/Firefox history: **mikrosekundy** od 1601 (Chrome) / sekundy od 1970 (Firefox)
- SQLite datetime(): ISO text

Detekce formátu podle velikosti čísla je heuristická, ale pro reálná data
spolehlivá (rozsahy se nepřekrývají o řád více).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
WINDOWS_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


def from_unix(value: float) -> datetime:
    """Unix epoch (sekundy, může být float s frakcí)."""
    if value < 0:
        raise ValueError(f"Unix čas musí být ≥ 0, dostal {value}")
    return UNIX_EPOCH + timedelta(seconds=float(value))


def to_chrome_micros(dt: datetime) -> int:
    """datetime → Chrome history.last_visit_time (µs od Windows epochy 1601)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = dt.astimezone(timezone.utc) - WINDOWS_EPOCH
    return int(delta.total_seconds() * 1_000_000)


def from_windows_filetime(value: int) -> datetime:
    """Windows FILETIME — 100ns intervaly od 1601-01-01."""
    if value <= 0:
        raise ValueError(f"FILETIME musí být kladné, dostal {value}")
    return WINDOWS_EPOCH + timedelta(microseconds=int(value) // 10)


def from_chrome_micros(value: int) -> datetime:
    """Chrome history.last_visit_time — mikrosekundy od Windows epochy (1601)."""
    if value <= 0:
        raise ValueError(f"Chrome čas musí být kladný, dostal {value}")
    return WINDOWS_EPOCH + timedelta(microseconds=int(value))


def detect_and_convert(value: float) -> datetime:
    """Heuristická detekce formátu podle velikosti čísla.

    Rozsahy (aktuální doba ~2026):
      unix sekundy     : ~1.7e9  – 4.1e9   (1970–2100)
      unix ms          : ~1.7e12 – 4.1e12
      unix µs          : ~1.7e15 – 4.1e15
      windows FILETIME : ~13.1e18 (100ns od 1601, rok 2026)
      chrome µs(1601)  : ~13.1e15 (µs od 1601, rok 2026)

    Chrome µs a unix µs se liší o faktor ~8047 → rozlišitelné.
    """
    v = float(value)
    if v <= 0:
        raise ValueError(f"Čas musí být kladný, dostal {value}")
    if v < 1e11:          # unix sekundy (až ~5138)
        return from_unix(v)
    if v < 1e14:          # unix milisekundy
        return from_unix(v / 1000.0)
    if v < 1e17:          # unix mikrosekundy
        return from_unix(v / 1_000_000.0)
    if v < 1e20:          # windows FILETIME (100ns od 1601)
        return from_windows_filetime(int(v))
    raise ValueError(f"Nerozpoznaný časový formát: {value}")


def to_iso(dt: datetime | None) -> str | None:
    """Normalizace na ISO s UTC (naivní → předpokládá UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()
