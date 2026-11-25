"""STOPA Rust core (F2.1) — lazy import PyO3 extension s Python fallbackem.

Rust modulu ``stopa_core`` (rust/src/lib.rs, build přes maturin) zrychluje:
- one-pass MD5/SHA-1/SHA-256 hashing souboru (GIL uvolněné po celou dobu)
- Aho-Corasick multi-pattern scan pro carving (per-pattern nenakládající shody,
  přesná parity se smyčkou ``data.find(magic)`` v domain/carving.py)

Import je LAZY + cache — pokud wheel není nainstalován (např. čistý sdist bez
předkompilovaného artefaktu), vracejí funkce ``None`` a volající používá
referenční Python cestu. Výsledky jsou bitově identické (parity testy).

Bezpečnost: žádné IO sem — čisté propojení mezi domain logikou a Rust corem;
IO (File::open, buffer) běží uvnitř Rust core s uvolněným GILem.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - jen pro typy (bez stubů v wheelu)
    from stopa_core import find_offsets as _rust_find_offsets  # noqa: F401
    from stopa_core import hash_file as _rust_hash_file  # noqa: F401

_UNTRIED = object()  # sentinel — "import ještě nezkoušen"
_mod: Any = _UNTRIED


def _load() -> Any | None:
    """Načte stopa_core jednou; při selhání trvale vrátí None (bez retry)."""
    global _mod
    if _mod is not _UNTRIED:
        return _mod
    try:
        import stopa_core  # type: ignore[import-not-found]

        _mod = stopa_core
    except Exception as exc:  # noqa: BLE001 - ImportError / OSError při load .so — fallback
        _logger.debug("stopa_core nedostupné, Python fallback: %s", exc)
        _mod = None
    return _mod


def is_available() -> bool:
    """Je Rust core načítelný (wheel nainstalovaný)?"""
    return _load() is not None


def rust_version() -> str | None:
    """Verze Rust core pro diagnostics, ``None`` pokud nedostupné."""
    mod = _load()
    if mod is None:
        return None
    try:
        return mod.rust_version()
    except Exception:  # noqa: BLE001 - defenzivní, pragma: no cover
        return None


def hash_file(path: str, algorithms: list[str]) -> dict[str, str] | None:
    """One-pass hashing přes Rust core; ``None`` → volající použije fallback.

    Podporuje pouze md5/sha1/sha256 (ověří si volající — ostatní algoritmy
    zůstanou na Python hashlib cestě). Chyby IO se propagují jako OSError,
    neznámý algoritmus jako ValueError (parity s domain/hashing.py).
    """
    mod = _load()
    if mod is None:
        return None
    try:
        return dict(mod.hash_file(path, list(algorithms)))
    except (OSError, ValueError):
        raise
    except Exception as exc:  # noqa: BLE001 - defenzivní, fallback místo pádu pipeline
        _logger.warning("Rust hash_file selhal (%s) — Python fallback", exc)
        return None


def find_offsets(data: bytes, patterns: list[bytes]) -> list[tuple[int, int]] | None:
    """Multi-pattern scan přes Rust core; ``None`` → volající použije fallback.

    Vrací ``(offset, pattern_index)`` seřazené deterministicky — per-pattern
    nenakládající shody (ekvivalent smyčky ``data.find(magic, pos + len)``).
    """
    mod = _load()
    if mod is None:
        return None
    try:
        raw = mod.find_offsets(data, [bytes(p) for p in patterns])
        return [(int(off), int(idx)) for off, idx in raw]
    except Exception as exc:  # noqa: BLE001 - defenzivní, fallback místo pádu pipeline
        _logger.warning("Rust find_offsets selhal (%s) — Python fallback", exc)
        return None


def block_dedupe_file(
    path: str | Path,
    *,
    avg_size: int | None = None,
    min_size: int | None = None,
    max_size: int | None = None,
) -> list[tuple[str, int]] | None:
    """One-pass block-level deduplikace souboru přes Rust core; ``None`` → Python fallback.

    Vrací ``(sha256_hex, length)`` v pořadí bloků souboru — bitová parita s
    ``domain.block_dedupe.chunk_bytes`` (parity testy F2.3). Volající bez wheelu
    čte byty souboru a spustí referenční implementaci.

    Parametrické chyby: ValueError ještě před voláním Rustu (stejná zpráva jako
    referenční cesta); IO chyby se propagují jako OSError.
    """
    from stopa.domain import block_dedupe  # lazy — bez cyklu při načtení modulu

    if avg_size is None:
        avg_size = block_dedupe.DEFAULT_AVG_SIZE
    if min_size is None:
        min_size = block_dedupe.DEFAULT_MIN_SIZE
    if max_size is None:
        max_size = block_dedupe.DEFAULT_MAX_SIZE
    block_dedupe.validate_sizes(avg_size, min_size, max_size)

    mod = _load()
    if mod is None:
        return None
    try:
        raw = mod.block_dedupe(str(path), avg_size, min_size, max_size)
        return [(str(h), int(l)) for h, l in raw]
    except (OSError, ValueError):
        raise  # soubor neexistuje / parametry — volající řeší explicitně
    except Exception as exc:  # noqa: BLE001 - defenzivní, fallback místo pádu pipeline
        _logger.warning("Rust block_dedupe selhal (%s) — Python fallback", exc)
        return None


def block_dedupe_files(
    paths: list[str | Path],
    *,
    avg_size: int | None = None,
    min_size: int | None = None,
    max_size: int | None = None,
) -> list[list[tuple[str, int]]] | None:
    """Batch one-pass block-level deduplikace více souborů; ``None`` → Python fallback.

    Jediné uvolnění GIL pro celý batch (bez per-file hraničního overheadu —
    viz měření F2.3 AK2). Vrací list v pořadí ``paths``, každý prvek je
    ``(sha256_hex, length)`` bloky souboru — shodné se opakovaným voláním
    :func:`block_dedupe_file` na stejných datech (parity testy F2.3).

    Parametrické chyby: ValueError ještě před voláním Rustu (validace jednou,
    stejná zpráva jako referenční cesta); IO chyba se propaguje jako OSError
    se jménem souboru.
    """
    from stopa.domain import block_dedupe  # lazy — bez cyklu při načtení modulu

    if avg_size is None:
        avg_size = block_dedupe.DEFAULT_AVG_SIZE
    if min_size is None:
        min_size = block_dedupe.DEFAULT_MIN_SIZE
    if max_size is None:
        max_size = block_dedupe.DEFAULT_MAX_SIZE
    block_dedupe.validate_sizes(avg_size, min_size, max_size)

    mod = _load()
    if mod is None:
        return None
    try:
        raws = mod.block_dedupe_files([str(p) for p in paths], avg_size, min_size, max_size)
        return [[(str(h), int(l)) for h, l in blocks] for blocks in raws]
    except (OSError, ValueError):
        raise  # soubor neexistuje / parametry — volající řeší explicitně
    except Exception as exc:  # noqa: BLE001 - defenzivní, fallback místo pádu pipeline
        _logger.warning("Rust block_dedupe_files selhal (%s) — Python fallback", exc)
        return None


def reset_cache() -> None:
    """Testovací hook — vynutí znovuzkoušení importu."""
    global _mod
    _mod = _UNTRIED
