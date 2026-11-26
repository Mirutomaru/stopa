"""F6 — Guard synchronizace changelog zrcadla.

Autoritativní kopie changelogu = ``STOPA_CHANGELOG.md`` v kořeni repa;
``docs/STOPA_CHANGELOG.md`` je jeho zrcadlo s přesně jednou dodatečnou
řádkou (Poznámka o zrcadlení). Historický nález F6: zrcadlo se od 2026-11-17
desynkronizovalo — chyběly všechny sekce releases 2.1→2.7 + P/F vlny
(40 vs 52 sekcí). Tyto testy brání opakování driftu.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROOT_CHANGELOG = REPO_ROOT / "STOPA_CHANGELOG.md"
MIRROR_CHANGELOG = REPO_ROOT / "docs" / "STOPA_CHANGELOG.md"
NOTE_PREFIX = "> **Poznámka"


def _normalized_lines(text: str) -> list[str]:
    """Normalizace běhů prázdných řádků (poznámka zrcadla přidává kontext)."""
    return re.sub(r"\n{3,}", "\n\n", text).splitlines()


def test_mirror_in_sync_with_root():
    root_text = ROOT_CHANGELOG.read_text(encoding="utf-8")
    mirror_lines = MIRROR_CHANGELOG.read_text(encoding="utf-8").splitlines()
    stripped_text = "\n".join(l for l in mirror_lines if not l.startswith(NOTE_PREFIX))
    assert _normalized_lines(stripped_text) == _normalized_lines(root_text), (
        "docs/STOPA_CHANGELOG.md se desynkronizoval od kořenové STOPA_CHANGELOG.md — "
        "úpravy provádět v kořeni a zrcadlo znovu synchronizovat"
    )


def test_mirror_note_present():
    lines = MIRROR_CHANGELOG.read_text(encoding="utf-8").splitlines()
    notes = [l for l in lines if l.startswith(NOTE_PREFIX)]
    assert len(notes) == 1, "zrcadlo musí nést přesně jeden Poznámka řádek o zrcadlení"
