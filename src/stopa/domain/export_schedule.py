"""STP-070 — Periodický plánovač auto-bundle: čistá doménová logika.

Rozšíření STP-069 (opt-in auto-export po ``process_source``) o časový
interval: web scheduler pravidelně projde případy s zapnutým auto-expor­tem
a vygeneruje bundle, pokud od posledního spuštění uplynul nastavený interval.

Tento modul je ČISTÝ — žádné I/O, žádné DB, žádná síť (Clean Architecture):
- :func:`parse_interval_minutes` — validace uživatelského vstupu (minuty)
- :func:`is_due`                 — rozhodnutí „je čas na auto-bundle“

Obě funkce jsou deterministické a 100% offline testovatelné.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# Rozsah intervalu v minutách: minimum 5 (častější = zbytečný I/O),
# maximum 30 dní (delší nemá smysl pro „periodický“ export).
MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 43_200


def parse_interval_minutes(value: float | str | None) -> int | None:
    """Validuje interval periodického auto-exportu a vrátí celé minuty.

    Args:
        value: ``None`` (interval nenastaven → scheduler case přeskočí),
            kladné číslo v minutách, nebo řetězec s celým číslem.

    Returns:
        Celé minuty (int) nebo ``None`` pro „nenastaveno“.

    Raises:
        ValueError: neplatný typ/formát, ne-kladná hodnota, nebo hodnota
            mimo rozsah [MIN_INTERVAL_MINUTES, MAX_INTERVAL_MINUTES].
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        minutes = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"interval musí být celé číslo v minutách, dostal: {value!r}")
    if minutes < MIN_INTERVAL_MINUTES or minutes > MAX_INTERVAL_MINUTES:
        raise ValueError(
            f"interval mimo rozsah {MIN_INTERVAL_MINUTES}–{MAX_INTERVAL_MINUTES} "
            f"minut (dostal: {minutes})"
        )
    return minutes


def is_due(
    last_run_utc: datetime | None,
    now_utc: datetime,
    interval_minutes: int,
) -> bool:
    """Rozhodne, zda je čas na další periodický auto-bundle.

    Args:
        last_run_utc: UTC čas posledního úspěšného spuštění (None = nikdy).
        now_utc: aktuální UTC čas (explicitní parametr → deterministické testy).
        interval_minutes: nastavený interval v minutách (> 0).

    Returns:
        True pokud od posledního spuštění uplynul celý interval, nebo pokud
        se bundle ještě nikdy nevygeneroval.
    """
    if last_run_utc is None:
        return True
    elapsed = now_utc - last_run_utc
    return elapsed >= timedelta(minutes=interval_minutes)
