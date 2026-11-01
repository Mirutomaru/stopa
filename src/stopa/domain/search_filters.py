"""E9 — Search rozšíření: parsování metadata filtrů z dotazu (čistá logika).

Dotaz je libovolná kombinace FTS5 textových termínů a prefixovaných filtrů,
oddělených mezerami. Filtry se aplikují jako SQL WHERE na vrstvu nad FTS MATCH:

- ``size:<op><hodnota>``   — velikost souboru; op ∈ {>, <, >=, <=, =};
  hodnota v bajtech nebo s jednotkou KB/MB/GB (binární, ×1024).
- ``mtime:<rozsah>``       — čas úpravy; rozsah ``A..B`` (včetně konců) nebo
  porovnání ``>DATE`` / ``<DATE`` / ``>=DATE`` / ``<=DATE`` / ``=DATE``.
  Datum = ISO 8601 (jen datum → půlnoc).
- ``ext:<přípona>``        — přípona bez tečky, malá písmena; lze opakovat.

Zbývající tokeny tvoří FTS textový dotaz (projdou `_fts_query` v datové vrstvě).
Čistý modul bez IO → 100% offline testovatelný.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

# jednotky velikosti (binární — forenzní konvence ×1024)
_SIZE_UNITS = {"": 1, "B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}

# operátory velikosti (dlouhé před krátkými — řazení v regexu)
_SIZE_OPS = (">=", "<=", ">", "<", "=")


class SearchFilterError(ValueError):
    """Neplatný filtr v dotazu (špatná jednotka, datum, operátor)."""


@dataclass(frozen=True)
class SizeFilter:
    """Filtr velikosti souboru — op + hranice v bajtech."""

    op: str  # '>', '<', '>=', '<=', '='
    bytes_: int


@dataclass(frozen=True)
class MtimeFilter:
    """Filtr času úpravy — volitelné dolní/horní mez (výchozí = včetně konců)."""

    from_dt: datetime | None = None
    to_dt: datetime | None = None
    from_inclusive: bool = True
    to_inclusive: bool = True


@dataclass(frozen=True)
class SearchFilters:
    """Výsledek parsování dotazu: textové termíny + metadata filtry."""

    text_terms: tuple[str, ...] = ()
    size: SizeFilter | None = None
    mtime: MtimeFilter | None = None
    exts: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_text(self) -> bool:
        return bool(self.text_terms)


def _size_to_bytes(value: str) -> int:
    """``1MB`` → 1048576; ``2048`` → 2048 (bajty). Podpora celých i desetinných."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([A-Za-z]*)", value.strip())
    if not m:
        raise SearchFilterError(f"neplatná velikost: {value!r}")
    number, unit = m.group(1), m.group(2).upper()
    if unit not in _SIZE_UNITS:
        raise SearchFilterError(f"neznámá jednotka velikosti: {unit or '∅'}")
    return int(float(number) * _SIZE_UNITS[unit])


def _parse_size(token: str) -> SizeFilter:
    """``size:>1MB`` → SizeFilter('>', 1048576)."""
    body = token[len("size:"):]
    for op in _SIZE_OPS:
        if body.startswith(op):
            return SizeFilter(op=op, bytes_=_size_to_bytes(body[len(op):]))
    raise SearchFilterError(f"chybějící operátor velikosti: {token!r}")


def _parse_dt(value: str) -> datetime:
    """ISO 8601 datum/datetime → naive UTC datetime (pro deterministické porovnání).

    Podporované tvary: ``YYYY``, ``YYYY-MM``, ``YYYY-MM-DD`` (→ půlnoc),
    plné ISO datetimes s volitelným TZ offsetem.
    """
    v = value.strip()
    # zkrácené tvary — fromisoformat je přísný na délku
    m = re.fullmatch(r"(\d{4})(?:-(\d{2}))?", v)
    if m:
        year = int(m.group(1))
        month = int(m.group(2)) if m.group(2) else 1
        return datetime(year, month, 1)
    try:
        dt = datetime.fromisoformat(v)
    except ValueError as exc:
        raise SearchFilterError(f"neplatné datum: {value!r}") from exc
    if dt.tzinfo is not None:
        # normalizace na UTC → naive (SQLite porovnává řetězce; konzistentní tvar)
        dt = dt.astimezone(_utc()).replace(tzinfo=None)
    return dt


def _utc():
    from datetime import timezone

    return timezone.utc


def _parse_mtime(token: str) -> MtimeFilter:
    """``mtime:A..B`` / ``mtime:>DATE`` / ``mtime:<DATE`` → MtimeFilter."""
    body = token[len("mtime:"):]
    if ".." in body:
        left, right = body.split("..", 1)
        return MtimeFilter(
            from_dt=_parse_dt(left) if left.strip() else None,
            to_dt=_parse_dt(right) if right.strip() else None,
        )
    for op in _SIZE_OPS:
        if body.startswith(op):
            dt = _parse_dt(body[len(op):])
            if op == ">":
                return MtimeFilter(from_dt=dt, from_inclusive=False)
            if op == "<":
                return MtimeFilter(to_dt=dt, to_inclusive=False)
            if op == ">=":
                return MtimeFilter(from_dt=dt, from_inclusive=True)
            if op == "<=":
                return MtimeFilter(to_dt=dt, to_inclusive=True)
            if op == "=":
                return MtimeFilter(from_dt=dt, to_dt=dt)
    raise SearchFilterError(f"neplatný mtime filtr: {token!r}")


def _parse_ext(token: str) -> str | None:
    """``ext:.jpg`` / ``ext:JPG`` → 'jpg'."""
    ext = token[len("ext:"):]
    ext = ext.removeprefix(".")
    return ext.lower() or None


def parse_search_query(query: str) -> SearchFilters:
    """Rozloží dotaz na textové termíny + metadata filtry.

    Tokeny se klasifikují podle prefixu (``size:``/``mtime:``/``ext:``);
    vše ostatní je FTS textový termín. Více filtrů stejného typu → poslední
    vyhraje (ext se akumuluje). Neznámý prefix zůstává textovým termínem.
    """
    terms: list[str] = []
    size: SizeFilter | None = None
    mtime: MtimeFilter | None = None
    exts: list[str] = []

    for token in query.split():
        if not token:
            continue
        low = token.lower()
        if low.startswith("size:"):
            size = _parse_size(token)
        elif low.startswith("mtime:"):
            mtime = _parse_mtime(token)
        elif low.startswith("ext:"):
            ext = _parse_ext(token)
            if ext and ext not in exts:
                exts.append(ext)
        else:
            terms.append(token)

    return SearchFilters(
        text_terms=tuple(terms),
        size=size,
        mtime=mtime,
        exts=tuple(exts),
    )


def size_sql(flt: SizeFilter) -> tuple[str, int]:
    """SizeFilter → (SQL fragment na `size_bytes`, hranice)."""
    op_map = {">": ">", "<": "<", ">=": ">=", "<=": "<=", "=": "="}
    return f"size_bytes {op_map[flt.op]} ?", flt.bytes_


def mtime_sql(flt: MtimeFilter) -> list[tuple[str, str]]:
    """MtimeFilter → seznam (SQL fragment na `mtime`, ISO mez).

    Porovnání přes SQLite ``datetime()`` normalizuje TZ offsety na UTC tvar.
    """
    out: list[tuple[str, str]] = []
    if flt.from_dt is not None:
        op = ">=" if flt.from_inclusive else ">"
        out.append((f"datetime(mtime) {op} datetime(?)", flt.from_dt.isoformat()))
    if flt.to_dt is not None:
        op = "<=" if flt.to_inclusive else "<"
        out.append((f"datetime(mtime) {op} datetime(?)", flt.to_dt.isoformat()))
    return out
