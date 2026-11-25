"""E12 — System Diagnostics: verze knihoven + dostupnost volitelných komponent.

Čistá sběr bez DB přístupu (web vrstva doplní poslední operace z audit_log).
Všechny kontroly jsou defenzivní — chybějící závislost není chyba, jen
``available=False`` / verze ``None`` (graceful degradation jako u E11 AI).
"""

from __future__ import annotations

import sys


def _try_version(module: str) -> str | None:
    """Verze nainstalovaného modulu.

    Returns:
        Verze (str), ``"ok"`` pokud modul nemá ``__version__``, nebo ``None``
        pokud se nedá importovat.
    """
    try:
        mod = __import__(module)
    except ImportError:
        return None
    v = getattr(mod, "__version__", None)
    return str(v) if v else "ok"


def collect_diagnostics() -> dict:
    """Snapshot prostředí — verze Pythonu/knihoven + dostupnost komponent.

    Komponenty (volitelné závislosti STOPA):
    - ``tsk`` — pytsk3 (filesystem walk diskových obrazů, E4)
    - ``ewf`` — libewf+libafflib přes ctypes (E01/AFF4 kontejnery, E6)
    - ``cryptsetup`` — binárka pro FDE LUKS/FBE dešifrování (E7)
    """
    from stopa.data.ewf_container import ewf_available
    from stopa.data.tsk_py import py_available
    from stopa.domain.fde_luks import cryptsetup_available

    return {
        "python": sys.version.split()[0],
        "libraries": {
            "fastapi": _try_version("fastapi"),
            "pytsk3": _try_version("pytsk3"),
            "PIL": _try_version("PIL"),
            "httpx": _try_version("httpx"),
        },
        "components": {
            "tsk": py_available(),
            "ewf": ewf_available(),
            "cryptsetup": cryptsetup_available(),
        },
    }
