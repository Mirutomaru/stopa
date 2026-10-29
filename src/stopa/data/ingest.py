"""Ingest — procházení evidence source (složka/soubor) a tvorba FileRecordů.

AXIOM-style: zdroj se přidá do případu, pak se zpracuje processing profilem.
Symlinky se nejdou (forenzní konzervativismus — cykly), skryté soubory ANO.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class WalkedFile:
    """Surový záznam z procházky — ještě bez hashů/signatur (ty dělá pipeline)."""

    rel_path: str  # forward slashes, relativní ke kořeni zdroje
    name: str
    size_bytes: int
    mtime: datetime | None = None
    ctime: datetime | None = None
    atime: datetime | None = None


def _ts(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def walk_source(root: Path) -> list[WalkedFile]:
    """Prochází zdroj a vrátí seřazený seznam souborů (deterministický pořádek).

    - složka → rekurzivní procházka, rel_path relativní ke kořeni
    - jediný soubor → jeden záznam s rel_path = jméno souboru
    - symlinky se přeskočí (cykly), chybějící soubory → FileNotFoundError
    """
    if not root.exists():
        raise FileNotFoundError(f"Zdroj neexistuje: {root}")

    files: list[WalkedFile] = []
    if root.is_file():
        st = root.stat()
        files.append(
            WalkedFile(
                rel_path=root.name,
                name=root.name,
                size_bytes=st.st_size,
                mtime=_ts(st.st_mtime),
                ctime=_ts(st.st_ctime),
                atime=_ts(st.st_atime),
            )
        )
    else:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            # deterministický pořádek procházky (os.walk je platformově proměnlivý)
            dirnames.sort()
            base = Path(dirpath)
            for fn in sorted(filenames):
                p = base / fn
                if p.is_symlink():
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue  # soubor zmizel během procházky — nenechat padnout ingest
                rel = p.relative_to(root).as_posix()
                files.append(
                    WalkedFile(
                        rel_path=rel,
                        name=fn,
                        size_bytes=st.st_size,
                        mtime=_ts(st.st_mtime),
                        ctime=_ts(st.st_ctime),
                        atime=_ts(st.st_atime),
                    )
                )
    files.sort(key=lambda f: f.rel_path)
    return files


def source_size(root: Path) -> int | None:
    """Celková velikost zdroje (pro EvidenceSource.size_bytes)."""
    if root.is_file():
        return root.stat().st_size
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        for fn in filenames:
            p = base / fn
            try:
                if not p.is_symlink():
                    total += p.stat().st_size
            except OSError:
                pass
    return total
