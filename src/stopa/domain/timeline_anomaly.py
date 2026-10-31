"""Timeline nesrovnalosti — ČISTÁ logika, bez IO (E2 Timeline Engine).

Tři forenzní pravidla detekce podezřelých událostí v timeline. Každé pravidlo
je samostatná čistá funkce → 100% offline testovatelné s fixturemi.

Pravidla:
- ``mtime_before_ctime`` : soubor byl „upraven“ PŘEDTÍM, než vznikl (nemožné
  pořadí časů → manipulace / špatný parser).
- ``out_of_range``       : timestamp leží mimo operační rozsah zařízení
  (mimo min/max pozorovaných událostí ± tolerance) → hodiny posunuté,
  import z cizího zdroje, nebo artefakt.
- ``duplicate``          : dvě různé události se stejným typem a obsahem do
  <1 s od sebe → dvojnásobná extrakce / replay.

Výstup je tuple kanonických flagů (prázdné = bez nesrovnalosti). Flagy se
materializují do ``timeline_events.anomaly_flags`` při extrakci artifactů.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Kanonické názvy flagů (stabilní — GUI / report / testy se na ně spoléhají).
FLAG_MTIME_BEFORE_CTIME = "mtime_before_ctime"
FLAG_OUT_OF_RANGE = "out_of_range"
FLAG_DUPLICATE = "duplicate"

DEFAULT_TOLERANCE_DAYS = 30.0   # tolerance pro „mimo rozsah zařízení“
DUPLICATE_THRESHOLD_SECONDS = 1.0


@dataclass
class AnomalyContext:
    """Kontext pro detekci — operační okno zařízení + již viděné události.

    ``window_start`` / ``window_end`` jsou min/max pozorovaných časů (UTC).
    Pokud nejsou známy (první extrakce), pravidlo out_of_range se nepoužije.

    ``seen_timestamps`` — již viděné události ``(ts, key)`` pro duplikát detekci;
    pipeline je seeduje ze stavu DB a průběžně doplňuje během běhu.
    """

    window_start: datetime | None = None
    window_end: datetime | None = None
    tolerance_days: float = DEFAULT_TOLERANCE_DAYS
    seen_timestamps: list[tuple[datetime, str]] = field(default_factory=list)


def check_mtime_before_ctime(
    mtime: datetime | None, ctime: datetime
) -> bool:
    """Pravidlo 1 — mtime < ctime (upraveno dříve než vytvořeno)."""
    if mtime is None or ctime is None:
        return False
    return mtime < ctime


def check_out_of_range(
    ts: datetime | None, ctx: AnomalyContext
) -> bool:
    """Pravidlo 2 — timestamp mimo operační rozsah zařízení (± tolerance)."""
    if ts is None or ctx.window_start is None or ctx.window_end is None:
        return False
    tol = timedelta(days=ctx.tolerance_days)
    lo = ctx.window_start - tol
    hi = ctx.window_end + tol
    return not (lo <= ts <= hi)


def check_duplicate(
    ts: datetime | None, key: str, seen: list[tuple[datetime, str]]
) -> bool:
    """Pravidlo 3 — duplicitní událost (<1 s od stejného klíče).

    ``key`` identifikuje „stejnou“ událost (artifact_type + title/rel_path),
    aby se nehlásilo jako duplikát dvě legitimně odlišné zprávy ve stejnou vteřinu.
    """
    if ts is None:
        return False
    for seen_ts, seen_key in seen:
        if seen_key == key and abs((ts - seen_ts).total_seconds()) < DUPLICATE_THRESHOLD_SECONDS:
            return True
    return False


def detect_anomalies(
    artifact_type: str,
    ts: datetime | None,
    *,
    title: str | None = None,
    rel_path: str | None = None,
    file_mtime: datetime | None = None,
    file_ctime: datetime | None = None,
    ctx: AnomalyContext | None = None,
) -> tuple[str, ...]:
    """Spustí všechna pravidla a vrátí kanonické flagy (prázdné = OK).

    Čistá funkce — žádné IO. ``ctx`` nese operační okno + již viděné události;
    volající (pipeline / DB) ji sestaví ze stavu case DB.
    """
    ctx = ctx or AnomalyContext()
    flags: list[str] = []

    if check_mtime_before_ctime(file_mtime, file_ctime):
        flags.append(FLAG_MTIME_BEFORE_CTIME)

    if ts is not None and check_out_of_range(ts, ctx):
        flags.append(FLAG_OUT_OF_RANGE)

    # duplikát: klíč = typ + obsah (title nebo rel_path), aby se porovnávaly jen „stejné“ události
    key = f"{artifact_type}|{title or ''}|{rel_path or ''}"
    if ts is not None and check_duplicate(ts, key, ctx.seen_timestamps):
        flags.append(FLAG_DUPLICATE)

    return tuple(flags)


def parse_flags(raw: str | None) -> tuple[str, ...]:
    """Comma-separated flagy → tuple (prázdné/None = bez nesrovnalosti)."""
    if not raw:
        return ()
    return tuple(f for f in raw.split(",") if f)


def flags_str(flags: tuple[str, ...] | list[str]) -> str:
    """Tuple flagů → comma-separated string pro uložení do DB."""
    return ",".join(flags)
