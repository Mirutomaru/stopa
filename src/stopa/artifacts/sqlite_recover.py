"""SQLite carving — IO wrapper nad ``domain.sqlite_recover``.

Čistá binární logika (varint, record decoding, freelist/WAL scan) žije v
``stopa.domain.sqlite_recover``; tady je jen čtení souborů a převod na
Artifacty pro pipeline:

- ``recover_deleted_rows(path)`` — smazané řádky z .db (+ sousední -wal).
  Vrací Artifacty BEZ source_id/file_id (ty doplní pipeline, jako ostatní
  extraktory). Chyby → log + prázdný výsledek, nikdy ne výjimka nahoru.

WAL soubor se hledá vedle DB jako ``<jméno>-wal`` — standardní konvence
SQLite (journal_mode=WAL; shared memory je ``<jméno>-shm``). Pokud neexistuje,
obnova běží jen nad .db.
"""

from __future__ import annotations

import logging
from pathlib import Path

from stopa.domain.sqlite_recover import RecoveredRow, recover_from_wal, recover_rows
from stopa.models import Artifact

log = logging.getLogger("stopa.artifacts.sqlite_recover")


def _row_to_artifact(row: RecoveredRow) -> Artifact:
    """Převod obnoveného řádku na Artifact (title = první textová hodnota)."""
    # title — první čitelný text, jinak rowid
    title: str | None = None
    for v in row.values:
        if isinstance(v, str) and v.strip():
            title = v[:300]
            break
    if title is None:
        title = f"(rowid {row.rowid})"

    return Artifact(
        artifact_type="sqlite_deleted_row",
        timestamp=None,  # smazané řádky nemají spolehlivý čas
        title=title,
        details={
            "source": row.source,
            "page": row.page,
            "rowid": row.rowid,
            "values": [v for v in row.values if isinstance(v, (str, int, float))],
        },
    )


def recover_deleted_rows(path: Path) -> list[Artifact]:
    """Obnoví smazané řádky ze SQLite souboru (+ sousední ``<jméno>-wal``).

    IO wrapper — čte ``path`` a volitelně ``<jméno>-wal``, pak zavolá
    čisté funkce z domény. Vrací Artifacty bez source_id/file_id.
    """
    try:
        db_data = path.read_bytes()
    except OSError as e:
        log.warning("SQLite recover read %s: %s", path, e)
        return []

    rows = recover_rows(db_data)

    # sousední WAL — standardní konvence SQLite (journal_mode=WAL): <jméno>-wal
    wal_path = path.with_name(path.name + "-wal")
    if wal_path.is_file():
        try:
            wal_data = wal_path.read_bytes()
            rows.extend(recover_from_wal(db_data, wal_data))
        except OSError as e:
            log.warning("SQLite recover WAL %s: %s", wal_path, e)

    return [_row_to_artifact(r) for r in rows]
