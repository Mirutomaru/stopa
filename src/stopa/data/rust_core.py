"""BC shim (H2) — Rust core facade se přesunula do ``stopa.core.rust_core``.

Data vrstva už není semantické domovisko mostu na volitelný PyO3 wheel; leží
v neutrální capability vrstvě ``core/`` (nad domain i data). Tento shim drží
starou import cestu ``stopa.data.rust_core`` funkční **stejným modulovým
objektem** — monkeypatch atributů (např. ``_mod``, fallback testy F21/F23)
funguje identicky přes obě cesty. Data-layer konzumenti (analytics, benchmark)
i testy zůstávají beze změny.
"""

from __future__ import annotations

import sys as _sys

from stopa.core import rust_core as _core_rc  # zdroj jmen; níže alias identity

# alias: stará cesta == core modul (identity), ne jen re-export atributů
_sys.modules[__name__] = _core_rc
