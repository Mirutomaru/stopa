"""STOPA i18n — lehký katalogový modul (P4-8).

Dva JSON katalogy (cs, en) + helper ``t(key, **params)``. Výchozí jazyk je ``cs``
a výchozí stav CLI/Web je byte-kompatibilní se stavem před P4-8.

Způsoby výběru jazyka (priorita):
  1. flag ``--lang cs|en`` na top-level (před subpříkazem),
  2. environment proměnná ``STOPA_LANG``,
  3. default ``cs``.

Poznámka: subpříkaz ``stopa report --lang`` je *jazyk reportu* — jiný význam,
zůstává nezávislý na tomto modulu.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

_log = logging.getLogger("stopa.i18n")

SUPPORTED_LANGS: tuple[str, ...] = ("cs", "en")
DEFAULT_LANG: str = "cs"
ENV_VAR: str = "STOPA_LANG"

_CATALOG_DIR = Path(__file__).resolve().parent
_cache: dict[str, dict[str, str]] = {}
_active_lang: str = DEFAULT_LANG


def load_catalog(lang: str) -> dict[str, str]:
    """Načíst (a cachovat) katalog pro ``lang``; chybějící/rozbitý soubor → {}.

    Fail-open: katalog je doplněk nad výchozím cs stavem — při jeho ztrátě se
    radši loguje a vrací prázdná mapa (t() pak spadne na fallback/cs).
    """
    if lang in _cache:
        return _cache[lang]
    path = _CATALOG_DIR / f"{lang}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("katalog není JSON objekt")  # typová chyba → TypeError (TRY004)
        catalog = {str(k): str(v) for k, v in data.items()}
    except (OSError, ValueError, TypeError) as exc:  # defensive — viz docstring
        _log.warning("i18n katalog %s se nepodařilo načíst: %s", lang, exc)
        catalog = {}
    _cache[lang] = catalog
    return catalog


def set_lang(lang: str) -> None:
    """Přepnout aktivní jazyk (validace proti SUPPORTED_LANGS)."""
    global _active_lang
    if lang not in SUPPORTED_LANGS:
        raise ValueError(f"neznámý jazyk {lang!r} (povoleno: {', '.join(SUPPORTED_LANGS)})")
    _active_lang = lang


def get_lang() -> str:
    """Aktivní jazyk."""
    return _active_lang


def t(key: str, **params: object) -> str:
    """Překlad klíče v aktivním jazyce.

    Fallback řetězec: aktivní katalog → cs katalog → samotný klíč (fail-open).
    ``params`` se dosazuje přes ``str.format`` jen při předání.
    """
    catalog = load_catalog(_active_lang)
    value = catalog.get(key)
    if value is None and _active_lang != DEFAULT_LANG:
        value = load_catalog(DEFAULT_LANG).get(key)
    if value is None:
        _log.debug("i18n chybějící klíč: %s", key)
        return key
    if params:
        try:
            value = value.format(**params)
        except (KeyError, IndexError, ValueError) as exc:  # defensive
            _log.warning("i18n format klíče %s selhal: %s", key, exc)
    return value


def resolve_lang(argv: list[str]) -> tuple[str, list[str]]:
    """Vyřešit jazyk z CLI argv (flag ``--lang`` v top-level pozici).

    Skenuje tokeny do prvního positionálního argumentu (subpříkazu); podpořeny
    tvary ``--lang en`` i ``--lang=en``. Vybraný pair se z argv odstraní, aby
    ho argparse neviděl jako cizí flag.

    Priorita: explicitní flag > env STOPA_LANG > default cs.
    """
    lang: str | None = None
    kept: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if not tok.startswith("-"):
            break  # první positionál = subpříkaz, top-level sken končí
        if tok == "--lang" and i + 1 < len(argv):
            lang = argv[i + 1]
            i += 2
            continue
        if tok.startswith("--lang="):
            lang = tok.split("=", 1)[1]
            i += 1
            continue
        kept.append(tok)
        i += 1

    resolved = lang or os.environ.get(ENV_VAR, "").strip().lower() or DEFAULT_LANG
    if resolved not in SUPPORTED_LANGS:
        raise ValueError(f"stopa: neznámá hodnota --lang/STOPA_LANG {resolved!r} "
                         f"(povoleno: {', '.join(SUPPORTED_LANGS)})")
    return resolved, kept + argv[i:]


def catalog(lang: str) -> dict[str, str]:
    """Publický accessor pro Web route /api/i18n/{lang}."""
    if lang not in SUPPORTED_LANGS:
        raise ValueError(f"neznámý jazyk {lang!r}")
    return load_catalog(lang)
