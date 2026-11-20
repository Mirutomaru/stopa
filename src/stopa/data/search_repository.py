"""P3-1 Advanced Search — datová vrstva (FTS5 + metadata filtry + relace BFS).

Návrh ``docs/P3_DESIGNS.md`` P3-1, vlna 2. Čistá logika žije v
``domain/search_adv.py``; tento modul ji odráží do SQL:

- **Bazová vyhledávání** = stávající E9 cesta (``FileRepository.search`` — FTS5
  MATCH + inline filtry ``size:/mtime:/ext:/in-artifact:``). Čistý textový dotaz
  bez strukturovaných filtrů se do ní deleguje → byte-identický výsledek s
  dosavadním chováním (AK1).
- **Strukturované filtry** (kind/size/mtime/source/entity) se aplikují čistým
  predikátem ``matches_filters`` na neomezený bazový výsledek — deterministicky,
  pořadí (bm25 / mtime DESC) zachováno; limit po filtrování.
- **Relace** (--rel-depth) = omezený BFS přes ``graph_edges`` (domain
  ``traverse_relations``, multi-zdroj z artefaktů zásahů); dosažené artefakty se
  mapují zpět na soubory (``related_files``), ostatní uzly → ``related_nodes``.

Modul žije v data/ (ne v facade db.py — rozpočet <600 ř.).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from stopa.data._helpers import _row_to_record
from stopa.data.file_repository import FileRepository
from stopa.domain.search_adv import (
    AdvancedSearchQuery,
    RelationSpec,
    matches_filters,
    traverse_relations,
)
from stopa.models import FileRecord


@dataclass(frozen=True)
class AdvancedSearchResult:
    """Výsledek strukturovaného vyhledávání.

    ``related_files`` / ``related_nodes`` jsou plné jen když dotaz obsahoval
    ``relations`` (rel_depth); jinak prázdné — formát odpovídá JSON kontraktu
    Web endpointu i CLI --json.
    """

    results: tuple[FileRecord, ...] = ()
    related_files: tuple[FileRecord, ...] = ()
    related_nodes: tuple[dict, ...] = ()


class SearchRepository:
    """Orchestrace P3-1 pokročilého vyhledávání nad existující case DB.

    Tenká vrstva bez business logiky (ta je v domain); sdílená
    ``sqlite3.Connection`` přichází od facade :class:`CaseDB`.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── bazové výsledky (E9 cesta nebo přímý SELECT) ────────────────
    def _base_records(self, query: AdvancedSearchQuery) -> list[FileRecord]:
        """Neomezený bazový výsledek v stejném pořadí jako E9.

        - text → ``FileRepository.search`` (FTS5 + inline filtry, limit=None);
        - bez textu → přímý SELECT z files (stejné řazení jako no-FTS větev E9).
        """
        text = (query.text or "").strip()
        if text:
            return FileRepository(self.conn).search(text, limit=None)
        rows = self.conn.execute(
            "SELECT f.* FROM files f ORDER BY f.mtime DESC, f.name"
        ).fetchall()
        return [_row_to_record(r) for r in rows]

    # ── soubor → přímé entity (graph_edges, obě směry) ──────────────
    def _file_entities(self) -> dict[str, set[str]]:
        """Mapuje file_id → množinu entit přímo spojených s jeho artefakty."""
        out: dict[str, set[str]] = {}
        q = (
            "SELECT DISTINCT a.file_id, e.dst_id AS ent"
            " FROM artifacts a JOIN graph_edges e ON e.src_id = a.id AND e.dst_type = 'entity'"
            " WHERE a.file_id IS NOT NULL"
            " UNION SELECT a.file_id, e.src_id"
            " FROM artifacts a JOIN graph_edges e ON e.dst_id = a.id AND e.src_type = 'entity'"
            " WHERE a.file_id IS NOT NULL"
        )
        for r in self.conn.execute(q).fetchall():
            if r["file_id"]:
                out.setdefault(r["file_id"], set()).add(r["ent"])
        return out

    # ── hlavní vstupní bod ───────────────────────────────────────────
    def search_advanced(self, query: AdvancedSearchQuery) -> AdvancedSearchResult:
        """Provede strukturovaný dotaz a vrátí zásahy + (volitelně) kontext relací.

        - žádné strukturované filtry a bez relací → delegace do E9 cesty (AK1);
        - filtry přes ``matches_filters`` (AND), pořadí bazového výsledku drží;
        - relace: BFS z artefaktů zásahů, related_files = soubory dosažených
          artefaktových uzlů, které nejsou už v results.

        Vynejme ``scope='artifacts'`` (W2 pokrývá 'files') → NotImplementedError.
        """
        if query.scope != "files":
            raise NotImplementedError(f"scope={query.scope!r} — P3-1 W2 pokrývá 'files'")

        f = query.filters
        structured = any(
            (f.kind, f.size_min, f.size_max, f.mtime_from, f.mtime_to, f.entity)
        )

        if not structured and query.relations is None:
            records = FileRepository(self.conn).search(
                query.text or "", source_id=f.source_id, limit=query.limit
            )
            return AdvancedSearchResult(results=tuple(records))

        base = self._base_records(query)
        entity_map = self._file_entities() if f.entity is not None else {}
        out: list[FileRecord] = []
        for rec in base:
            data = rec.model_dump(mode="json")  # datetime → ISO str (smlouva matches_filters)
            if f.entity is not None:
                data["entities"] = sorted(entity_map.get(rec.id, set()))
            if matches_filters(data, f):
                out.append(rec)
        if query.limit is not None:
            out = out[: query.limit]

        related_files: tuple[FileRecord, ...] = ()
        related_nodes: tuple[dict, ...] = ()
        if query.relations is not None and out:
            related_files, related_nodes = self._expand_relations(out, query.relations)
        return AdvancedSearchResult(
            results=tuple(out), related_files=related_files, related_nodes=related_nodes
        )

    # ── expanze relací (multi-zdrojový BFS přes graph_edges) ─────────
    def _expand_relations(
        self, hits: list[FileRecord], spec: RelationSpec
    ) -> tuple[tuple[FileRecord, ...], tuple[dict, ...]]:
        """BFS z artefaktů zásahů; deterministické sloučení multi-zdrojových běhů."""
        file_ids = [r.id for r in hits]
        ph = ",".join("?" * len(file_ids))
        art_rows = self.conn.execute(
            f"SELECT DISTINCT id, file_id FROM artifacts WHERE file_id IN ({ph})",
            file_ids,
        ).fetchall()
        if not art_rows:
            return (), ()

        edges = [
            dict(r)
            for r in self.conn.execute(
                "SELECT src_type, src_id, dst_type, dst_id, relation FROM graph_edges"
            ).fetchall()
        ]

        # Sloučení běhů: minimální hloubka; relace sjednoceny jen při stejné hloubce.
        merged: dict[tuple[str, str], tuple[int, set[str]]] = {}
        for art_id in sorted({a["id"] for a in art_rows}):
            for rn in traverse_relations(edges, ("artifact", art_id), spec):
                key = (rn.node_type, rn.node_id)
                cur = merged.get(key)
                if cur is None or rn.depth < cur[0]:
                    merged[key] = (rn.depth, set(rn.relations))
                elif rn.depth == cur[0]:
                    cur[1].update(rn.relations)

        related_nodes: tuple[dict, ...] = tuple(
            {"type": t, "id": i, "depth": d, "relations": sorted(rels)}
            for (t, i), (d, rels) in sorted(merged.items(), key=lambda kv: (kv[1][0], kv[0]))
        )

        art_depth = {i: d for (t, i), (d, _rels) in merged.items() if t == "artifact"}
        reached_art_ids = sorted(art_depth)
        hit_ids = set(file_ids)
        related_files: tuple[FileRecord, ...] = ()
        if not reached_art_ids:
            return (), related_nodes

        ph2 = ",".join("?" * len(reached_art_ids))
        rows2 = self.conn.execute(
            f"SELECT id, file_id FROM artifacts WHERE id IN ({ph2})", reached_art_ids
        ).fetchall()
        file_depth: dict[str, int] = {}
        for r in rows2:
            if not r["file_id"]:
                continue
            d = art_depth[r["id"]]
            cur = file_depth.get(r["file_id"])
            if cur is None or d < cur:
                file_depth[r["file_id"]] = d

        want_ids = sorted(fid for fid in file_depth if fid not in hit_ids)
        if want_ids:
            ph3 = ",".join("?" * len(want_ids))
            recs = [
                _row_to_record(r)
                for r in self.conn.execute(
                    f"SELECT f.* FROM files f WHERE f.id IN ({ph3})", want_ids
                ).fetchall()
            ]
            related_files = tuple(sorted(recs, key=lambda r: (file_depth[r.id], r.rel_path)))
        return related_files, related_nodes
