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


def reset_cache() -> None:
    """Testovací hook — vynutí znovuzkoušení importu."""
    global _mod
    _mod = _UNTRIED
