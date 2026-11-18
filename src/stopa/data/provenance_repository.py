"""P0-1 — provenance kontext z case DB (I/O vrstva).

Čistá logika řetězce žije v ``domain.provenance_chain``; tato třída jen
normalizuje řádky tabulek (files / sources / custody_items /
analysis_operations / lineage_events) do tvaru, který doména očekává.

Poznámka: sloupec ``artifacts.parent_artifact_id`` je aditivní (schéma v21);
staré case DB ho mají z migrace ``apply_provenance_metadata_migration``,
která běží idempotentně při otevírání CaseDB.
"""

from __future__ import annotations

import json
import sqlite3


def _ref_ids(raw: str | None) -> list[str]:
    """Rozbalí JSON seznam referencí na identifikátory (str nebo {id})."""
    try:
        items = json.loads(raw or "[]")
    except ValueError:
        return []
    out: list[str] = []
    for it in items if isinstance(items, list) else []:
        if isinstance(it, str):
            out.append(it)
        elif isinstance(it, dict) and it.get("id"):
            out.append(str(it["id"]))
    return out


class ProvenanceRepository:
    """Normalizovaný provenance kontext jednoho artefaktu (bez doménové logiky)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_artifact_context(self, artifact_id: str) -> dict | None:
        """Vrátí kwargs pro ``domain.provenance_chain.build_provenance``.

        ``None`` = artefakt v DB neexistuje (CLI exit 1 / Web 404).
        """
        art = self._conn.execute(
            "SELECT id, source_id, file_id, parent_artifact_id FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if art is None:
            return None
        art = dict(art)

        source_row = None
        if art["source_id"]:
            row = self._conn.execute(
                "SELECT * FROM sources WHERE id = ?", (art["source_id"],)
            ).fetchone()
            if row is not None:
                source_row = dict(row)

        file_row = None
        if art["file_id"]:
            row = self._conn.execute("SELECT * FROM files WHERE id = ?", (art["file_id"],)).fetchone()
            if row is not None:
                file_row = dict(row)

        custody_row = None
        if source_row is not None:
            row = self._conn.execute(
                "SELECT * FROM custody_items WHERE source_id = ?", (source_row["id"],)
            ).fetchone()
            if row is not None:
                custody_row = dict(row)

        operations: list[dict] = []
        if source_row is not None:
            operations = [
                dict(r)
                for r in self._conn.execute(
                    "SELECT id, op_type, stopa_version, config_hash, created_at"
                    " FROM analysis_operations WHERE source_id = ? ORDER BY created_at, id",
                    (source_row["id"],),
                ).fetchall()
            ]

        # Související lineage události: ref na artefakt / soubor / zdroj.
        relevant = {art["id"]}
        if art["file_id"]:
            relevant.add(art["file_id"])
        if source_row is not None:
            relevant.add(source_row["id"])
        rows = self._conn.execute(
            "SELECT id, op_type, tool_version, config_hash,"
            " input_refs_json, output_refs_json, created_at FROM lineage_events"
        ).fetchall()
        lineage_events: list[dict] = []
        for r in rows:
            rec = dict(r)
            refs = set(_ref_ids(rec.pop("input_refs_json", None))) | set(
                _ref_ids(rec.pop("output_refs_json", None))
            )
            if refs & relevant:
                lineage_events.append(rec)
        lineage_events.sort(key=lambda r: (r.get("created_at") or "", r["id"]))

        parent = art.get("parent_artifact_id")
        parent_exists: bool | None = None
        if parent:
            hit = self._conn.execute(
                "SELECT 1 FROM artifacts WHERE id = ?", (parent,)
            ).fetchone()
            parent_exists = hit is not None

        return {
            "artifact_id": art["id"],
            "file_row": file_row,
            "source_row": source_row,
            "custody_row": custody_row,
            "operations": operations,
            "lineage_events": lineage_events,
            "parent_artifact_id": parent,
            "parent_exists": parent_exists,
        }
