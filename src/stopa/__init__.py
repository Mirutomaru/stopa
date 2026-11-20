"""STOPA — unifikovaná forenzní workbench."""

from __future__ import annotations

# audit P2 — verze z jednoho zdroje: pyproject.toml (metadata instalace).
# Fallback jen pro dev běh přímo ze src/ bez `pip install -e .`
# (editable metadata chybí) — hodnotu měnit v pyproject.toml.
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("stopa")
except PackageNotFoundError:  # dev run bez instalace
    __version__ = "2.3.0"
