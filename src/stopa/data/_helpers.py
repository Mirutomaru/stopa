"""Sdílené pomocné funkce datové vrstvy (ETAPA C — rozdělení db.py).

Tenké konverze řádků SQLite → Pydantic modely + normalizace času. Žádná
business logika; používají je repozitáře i facade ``CaseDB`` (bez cyklických
importů — tento modul nezávisí na ostatních modulech data/).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from stopa.models import FileRecord


def _iso(dt) -> str | None:
    """datetime → ISO 8601 (naivní čas se doplní UTC); None → None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _row_to_record(r: sqlite3.Row) -> FileRecord:
    """Řádek tabulky ``files`` → Pydantic model :class:`FileRecord`."""

    def parse(v):
        return datetime.fromisoformat(v) if v else None

    return FileRecord(
        id=r["id"],
        source_id=r["source_id"],
        rel_path=r["rel_path"],
        name=r["name"],
        size_bytes=r["size_bytes"],
        mtime=parse(r["mtime"]),
        ctime=parse(r["ctime"]),
        atime=parse(r["atime"]),
        sha256=r["sha256"],
        md5=r["md5"],
        sha512=r["sha512"] if "sha512" in r else None,  # noqa: SIM401 (Row bez .get)
        signature_type=r["signature_type"],
        extension=r["extension"],
        bad_extension=bool(r["bad_extension"]),
        is_duplicate_of=r["is_duplicate_of"],
        hash_set_hit=r["hash_set_hit"],
        meta_addr=r["meta_addr"] if "meta_addr" in r else None,  # noqa: SIM401 (Row bez .get)
    )
