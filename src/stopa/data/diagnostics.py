"""BC shim (H2) — E12 diagnostics se přesunuly do ``stopa.core.diagnostics``.

Snapshot prostředí (verze knihoven + dostupnost tsk/ewf/cryptsetup) je
introspekce, ne case persistence; patří nad obě vrstvy. Shim drží starou cestu
funkční **stejným modulovým objektem** — konzumenti přes ``stopa.data.diagnostics``
(web/system, test_e12) zůstávají beze změny a vidí totéž co core cesta.
"""

from __future__ import annotations

import sys as _sys

from stopa.core import diagnostics as _core_diag  # zdroj jmen; níže alias identity

# alias: stará cesta == core modul (identity), ne jen re-export atributů
_sys.modules[__name__] = _core_diag
