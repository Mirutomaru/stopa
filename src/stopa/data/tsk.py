"""TSK facade — jednotné veřejné API nad pytsk3 (primární) a CLI binárky (fallback).

Clean Architecture: konzumenti (`image_pipeline`, `web/app`) importují ODTUD,
ne přímo z backendů. Tuto vrstvu mění jen při přidání nového backendu.

Strategie volby backendu:
1. ``pytsk3`` — nativní bindingy, žádné subprocess (preferováno)
2. CLI binárky (mmls/fls/icat/blkls/img_stat) — fallback když pytsk3 chybí

Veřejné API (shoda s původním monolitem):
- ``Partition``, ``ImageFile``, ``TskError`` — datové typy + výjimka
- ``TSK_AVAILABLE`` — True pokud je dostupný alespoň jeden backend
- ``tsk_bin_dir()`` — cesta ke TSK binárkám (CLI fallback)
- ``image_partitions(path) -> list[Partition]``
- ``list_files(path, partition=None, include_deleted=True) -> list[ImageFile]``
- ``extract_file(path, meta_addr, partition=None) -> bytes``
- ``free_blocks(path, partition=None) -> list[str]``
- ``image_info(path) -> dict[str, str]``

Privátní helpery (pro testy):
- ``_desc_to_fstype(desc) -> str | None``
- ``_parse_fls_line(line) -> ImageFile | None``
"""

from __future__ import annotations

import logging
from pathlib import Path

# --- backends -----------------------------------------------------------------
import stopa.data.tsk_cli as _cli
import stopa.data.tsk_py as _py

# --- sdílené typy + výjimka ---------------------------------------------------
from stopa.data.tsk_types import (
    ImageFile,
    Partition,
    TskError,
    desc_to_fstype,
)

_log = logging.getLogger(__name__)


def tsk_bin_dir() -> str:
    """Cesta ke TSK binárkám (CLI backend); při chybě ``TskError``."""
    return _cli.tsk_bin_dir()


# --- dostupnost ----------------------------------------------------------------

#: True pokud je dostupný alespoň jeden backend (pytsk3 NEBO CLI binárky).
TSK_AVAILABLE: bool = _py.py_available() or _cli.cli_available()


def _use_py() -> bool:
    """Vrátí True, pokud má být použit pytsk3 backend."""
    return _py.py_available()


# --- public API (facade) -------------------------------------------------------


def image_partitions(image_path: Path) -> list[Partition]:
    """Seznam partici/volumin v obrazu.

    Preferuje pytsk3 (Volume_Info); fallback na mmls.
    Vrací jen data partitiony s rozpoznaným fstype.
    """
    if _use_py():
        try:
            return _py.image_partitions(image_path)
        except TskError as e:
            # pytsk3 selhalo (např. raw obraz bez partition tabulky) → zkusit CLI
            if not _cli.cli_available():
                raise
            _log.debug("pytsk3 image_partitions selhalo, fallback na mmls: %s", e)
    return _cli.image_partitions(image_path)


def list_files(
    image_path: Path,
    partition: Partition | None = None,
    include_deleted: bool = True,
) -> list[ImageFile]:
    """Rekurzivní seznam souborů v obrazu.

    Preferuje pytsk3 (dir walk); fallback na fls -r -l -p.
    ``partition`` — z image_partitions; None → DETECT / první data partice.
    ``include_deleted`` — False → jen alokované soubory.
    """
    if _use_py():
        try:
            return _py.list_files(image_path, partition=partition, include_deleted=include_deleted)
        except TskError as e:
            if not _cli.cli_available():
                raise
            _log.debug("pytsk3 list_files selhalo, fallback na fls: %s", e)
    return _cli.list_files(image_path, partition=partition, include_deleted=include_deleted)


def extract_file(
    image_path: Path, meta_addr: str, partition: Partition | None = None
) -> bytes:
    """Obsah souboru podle metadata adresy.

    Preferuje pytsk3 (open_meta + read_random); fallback na icat.
    Vrací raw bajty (binární obsah).
    """
    if _use_py():
        try:
            return _py.extract_file(image_path, meta_addr, partition=partition)
        except TskError as e:
            if not _cli.cli_available():
                raise
            _log.debug(
                "pytsk3 extract_file selhalo (addr=%s), fallback na icat: %s", meta_addr, e
            )
    return _cli.extract_file(image_path, meta_addr, partition=partition)


def free_blocks(image_path: Path, partition: Partition | None = None) -> list[str]:
    """Volné bloky — pro carving nealokovaného prostoru.

    Preferuje pytsk3 (complement runs); fallback na blkls.
    Vrací seřazené adresy bloků jako str.
    """
    if _use_py():
        try:
            return _py.free_blocks(image_path, partition=partition)
        except TskError as e:
            if not _cli.cli_available():
                raise
            _log.debug("pytsk3 free_blocks selhalo, fallback na blkls: %s", e)
    return _cli.free_blocks(image_path, partition=partition)


def image_info(image_path: Path) -> dict[str, str]:
    """Základní info o obrazu (typ, velikost, sektor).

    Preferuje pytsk3 (Img_Info.get_size); fallback na img_stat.
    """
    if _use_py():
        try:
            return _py.image_info(image_path)
        except TskError as e:
            if not _cli.cli_available():
                raise
            _log.debug("pytsk3 image_info selhalo, fallback na img_stat: %s", e)
    return _cli.image_info(image_path)


# --- privátní helpery (pro testy) ----------------------------------------------

#: Alias pro ``desc_to_fstype`` (test_tsk.py importuje jako ``_desc_to_fstype``).
_desc_to_fstype = desc_to_fstype

#: Parsování řádku fls -l (CLI backend; test_tsk.py importuje jako ``_parse_fls_line``).
_parse_fls_line = _cli.parse_fls_line
