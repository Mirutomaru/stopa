"""SQLite carving — FORMATTER vrstva (A1 split).

Převod obnovených řádků (``RecoveredRow`` z ``sqlite_parser``) na Pydantic
modely pro case DB. Čistá logika bez IO → offline testovatelné; čtení souborů
zůstává v IO wrapperu ``artifacts/sqlite_recover.py``.

Součást rozbití původního monolitu ``sqlite_recover.py``:

- ``sqlite_parser.py`` — binární formát (stránky, buňky, freelisty, WAL)
- ``sqlite_carver.py`` — obnova smazaných řádků
- ``sqlite_formatter.py`` — TENTO modul: mapování na modely / Artifacty
"""

from __future__ import annotations

from stopa.domain.sqlite_parser import RecoveredRow
from stopa.models import Artifact


def row_to_artifact(row: RecoveredRow) -> Artifact:
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
