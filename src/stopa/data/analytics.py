"""F2.2 — DuckDB OLAP vrstva pro timeline & analytics.

Architektura (OLTP/OLAP split):
- **SQLite** zůstává single source of truth (cases, files, artifacts, audit_log, FTS5).
- **DuckDB** čte case DB přes ``ATTACH ... (TYPE SQLITE)`` a materiálové native
  tabulky (timeline_events/entities/correlations) postaví explicitním refreshem —
  DuckDB 2.x nepodporuje CREATE MATERIALIZED VIEW, proto je materiálový stav
  odvozený artefakt v ``<case>.duckdb`` vedle case DB.
- Staleness: **filesystem signatura** (mtime_ns+size hlavního souboru i WAL) se
  porovnává se signaturou uloženou při refreshu → O(1), přesná i cross-process,
  bez COUNT(*) v hot pathu a bez TTL race window. Při neshodě auto-refresh
  (RW režim) nebo explicitní signál stale + živé počty (read-only režim).

Bez duckdb = ``duckdb_available()`` False → volající jde na SQLite fallback.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path
from typing import Any

try:  # lazy — duckdb je volitelná závislost [analytics]
    import duckdb
except ImportError:  # pragma: no cover — záleží na instalaci
    duckdb = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class AnalyticsError(Exception):
    """Chyba OLAP vrstvy (IO, schema, DuckDB stav)."""


def duckdb_available() -> bool:
    """DuckDB je nainstalováno a importovatelné."""
    return duckdb is not None


def case_duckdb_path(db_path: str | Path) -> Path:
    """Cesta k materiálovému DuckDB souboru vedle case DB (case-XXX.db → case-XXX.duckdb)."""
    p = Path(db_path)
    return p.with_suffix(".duckdb")


def drop_case_analytics(db_path: str | Path) -> bool:
    """Uvolní sdílenou konexi a smaže materiálový .duckdb soubor (case delete).

    Materiálový stav je odvozený artefakt — po smazání případu musí zmizet.
    Vrací True, pokud byl soubor smazán.
    """
    duckdb_file = case_duckdb_path(db_path)
    key = str(duckdb_file.resolve())
    with _LOCK:
        con = _CONNS.pop(key, None)
    if con is not None:
        close_fn = getattr(con, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception as exc:  # noqa: BLE001 — close může selhat na zamčeném souboru
                logger.warning("DuckDB close selhalo pro %s: %s", duckdb_file, exc)
    if duckdb_file.exists():
        try:
            duckdb_file.unlink()
            return True
        except OSError as exc:
            logger.warning("DuckDB unlink selhalo pro %s: %s", duckdb_file, exc)
            return False
    return False


# ── sdílené konexe per proces (web server = multi-thread; jeden RW soubor na případ) ──

_CONNS: dict[str, object] = {}
_LOCK = threading.Lock()


def _attach_alias(db_path: Path) -> str:
    """Deterministický unikátní alias pro ATTACH case DB."""
    digest = hashlib.sha1(str(db_path.resolve()).encode()).hexdigest()[:12]
    return f"case_{digest}"


def _shared_connection(duckdb_file: Path, sqlite_file: Path) -> tuple[Any, str]:
    """Vrátí sdílenou DuckDB konexi per (soubor) + provede ATTACH case DB."""
    key = str(duckdb_file.resolve())
    with _LOCK:
        con = _CONNS.get(key)
        if con is None:
            if duckdb is None:
                raise AnalyticsError("DuckDB není nainstalováno (pip install 'stopa[analytics]')")
            try:
                con = duckdb.connect(str(duckdb_file))
            except Exception as exc:  # soubor může být zamčen jiným procesem
                raise AnalyticsError(f"DuckDB otevření selhalo pro {duckdb_file}: {exc}") from exc
            alias = _attach_alias(sqlite_file)
            try:
                con.execute("SHOW DATABASES")
                existing = [row[0] for row in con.fetchall()]
            except Exception:  # noqa: BLE001 — SHOW se může nedařit v prázdném DB
                existing = []
            if alias not in existing:
                con.execute(f"ATTACH ? AS {alias} (TYPE SQLITE)", [str(sqlite_file)])
            _CONNS[key] = con
        return con, _attach_alias(sqlite_file)


# ── filesystem signatura pro staleness detekci (O(1), cross-process) ──

def _file_sig(path: Path) -> tuple[int, int]:
    """(mtime_ns, size) souboru; neexistuje → (0, 0)."""
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return (0, 0)


def db_signature(db_path: Path) -> str:
    """Deterministická signatura živého case DB (hlavní soubor + WAL).

    Jakákoli commitovaná změna SQLite mění mtime/size hlavního souboru nebo
    WAL (WAL mode: commity píšou do -wal; checkpoint pak upraví main) →
    signatura se změní. Porovnání je O(1) — žádné COUNT(*).
    """
    main = _file_sig(db_path)
    wal = _file_sig(db_path.with_name(db_path.name + "-wal"))
    raw = f"{main[0]}:{main[1]}:{wal[0]}:{wal[1]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


# ── meta snapshot (signatura + počty) pro staleness detekci a zobrazení ──

_META_TABLE = "analytics_meta"


def _ensure_meta(con: Any) -> None:
    con.execute(
        f"""CREATE TABLE IF NOT EXISTS {_META_TABLE} (
            key VARCHAR PRIMARY KEY,
            value VARCHAR
        )"""
    )


def _read_snapshot(con: Any) -> dict[str, str]:
    try:
        rows = con.execute(f"SELECT key, value FROM {_META_TABLE}").fetchall()
    except Exception:  # noqa: BLE001 — tabulka ještě nemusí existovat
        return {}
    return {k: (v or "") for k, v in rows}


def _write_snapshot(con: Any, snapshot: dict[str, str]) -> None:
    """Přepíše meta snapshot (signatura + počty řádků).

    Meta tabulka je odvozený stav → DROP+CREATE zajišťuje správné schéma i při
    migraci starších .duckdb souborů (schéma drift např. BIGINT→VARCHAR).
    """
    con.execute(f"DROP TABLE IF EXISTS {_META_TABLE}")
    _ensure_meta(con)
    for k, v in snapshot.items():
        con.execute(
            f"INSERT OR REPLACE INTO {_META_TABLE} (key, value) VALUES (?, ?)",
            [k, str(v)],
        )


def _sqlite_counts(con: Any, alias: str) -> dict[str, int]:
    """Živé počty řádků v SQLite case DB (přes ATTACH)."""
    out: dict[str, int] = {}
    for table in ("timeline_events", "entities", "correlations"):
        try:
            row = con.execute(f"SELECT COUNT(*) FROM {alias}.main.{table}").fetchone()
            out[table] = int(row[0]) if row else 0
        except Exception:  # noqa: BLE001 — tabulka může chybět v velmi staré DB
            out[table] = 0
    return out


# ── materiálové tabulky (DuckDB native — OLAP rychlost) ──

_MATERIALIZED = {
    "tl_events": """
        CREATE OR REPLACE TABLE tl_events AS
        SELECT id, source_id, artifact_id, file_id, rel_path, event_type,
               ts_utc, TRY_CAST(ts_utc AS TIMESTAMP) AS ts, title, confidence,
               parser_version, extracted_at, anomaly_flags, ts_origin
        FROM {alias}.main.timeline_events
    """,
    "tl_entities": """
        CREATE OR REPLACE TABLE tl_entities AS
        SELECT id, case_id, kind, value_normalized, raw_value, first_seen, last_seen
        FROM {alias}.main.entities
    """,
    "tl_correlations": """
        CREATE OR REPLACE TABLE tl_correlations AS
        SELECT id, case_id, entity_a, entity_b, relation, confidence,
               evidence_json, first_seen, last_seen, created_at
        FROM {alias}.main.correlations
    """,
}


class AnalyticsStore:
    """OLAP queries nad materiálovými DuckDB tabulkami pro jeden případ.

    ``readonly=True`` — jen čtení; při stale snapshotu neaktualizuje (vrací
    fresh=False + živé počty). Default RW — auto-refresh při neshodě signatury.
    """

    def __init__(self, db_path: str | Path, *, readonly: bool = False) -> None:
        self._db_file = Path(db_path)
        if not self._db_file.exists():
            raise AnalyticsError(f"Case DB neexistuje: {self._db_file}")
        self._duckdb_file = case_duckdb_path(self._db_file)
        self.readonly = readonly
        con, alias = _shared_connection(self._duckdb_file, self._db_file)
        self._con = con
        self._alias = alias

    def refresh(self) -> dict[str, int]:
        """(Re)vytvoří materiálové tabulky ze SQLite + uloží signaturu a počty."""
        if self.readonly:
            raise AnalyticsError("refresh() vyžaduje RW AnalyticsStore")
        for sql in _MATERIALIZED.values():
            self._con.execute(sql.format(alias=self._alias))
        counts = _sqlite_counts(self._con, self._alias)
        snap = {"signature": db_signature(self._db_file)}
        snap.update({f"count_{k}": str(v) for k, v in counts.items()})
        _write_snapshot(self._con, snap)
        return counts

    def _stored_counts(self) -> dict[str, int]:
        snap = _read_snapshot(self._con)
        return {k.removeprefix("count_"): int(v) for k, v in snap.items() if k.startswith("count_")}

    def _is_fresh(self) -> bool:
        """Signatura materiálového stavu odpovídá živým souborům (O(1))."""
        stored = _read_snapshot(self._con).get("signature")
        if not stored:
            # ještě nebylo materiálováno — tl_* tabulky vůbec neexistují,
            # takže i prázdný case je stale (jinak OLAP query spadne na chybějící tabulku)
            return False
        return stored == db_signature(self._db_file)

    def status(self) -> dict:
        """Stav materiálového stavu; při neshodě v RW režimu auto-refresh.

        ``live`` = živé počty (při fresh se rovnají snapshot — signatura změněna nebyla);
        u stale readonly se spočítají přes ATTACH pro zobrazení.
        """
        fresh = self._is_fresh()
        if not fresh and not self.readonly:
            self.refresh()
            fresh = True
        snap_counts = self._stored_counts()
        live = snap_counts if fresh else _sqlite_counts(self._con, self._alias)
        return {
            "available": True,
            "fresh": fresh,
            "snapshot": snap_counts,
            "live": live,
            "readonly": self.readonly,
        }

    # ── OLAP queries (běží na materiálových tabulkách) ──

    def timeline_range(
        self, from_ts: str, to_ts: str, *, event_type: str | None = None, limit: int = 10_000
    ) -> list[dict]:
        """Chronologické okno událostí (AK: 10M eventů v rozmezí 1 h < 2 s)."""
        if not self.status()["fresh"]:
            raise AnalyticsError("Stale materiálový stav — spustěte refresh")
        sql = "SELECT id, source_id, file_id, rel_path, event_type, ts_utc, title, confidence, anomaly_flags FROM tl_events WHERE ts >= TRY_CAST(? AS TIMESTAMP) AND ts <= TRY_CAST(? AS TIMESTAMP)"
        params: list[object] = [from_ts, to_ts]
        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
        sql += " ORDER BY ts LIMIT ?"
        params.append(limit)
        rows = self._con.execute(sql, params).fetchall()
        keys = ("id", "source_id", "file_id", "rel_path", "event_type", "ts_utc", "title", "confidence", "anomaly_flags")
        return [dict(zip(keys, r)) for r in rows]

    def hourly_histogram(self, *, from_ts: str | None = None, to_ts: str | None = None) -> list[dict]:
        """Agregace: počet událostí po hodinách (AK: agregace < 5 s)."""
        if not self.status()["fresh"]:
            raise AnalyticsError("Stale materiálový stav — spustěte refresh")
        sql = "SELECT date_trunc('hour', ts) AS hour_bucket, COUNT(*) AS events FROM tl_events WHERE ts IS NOT NULL"
        params: list[object] = []
        if from_ts:
            sql += " AND ts >= TRY_CAST(? AS TIMESTAMP)"
            params.append(from_ts)
        if to_ts:
            sql += " AND ts <= TRY_CAST(? AS TIMESTAMP)"
            params.append(to_ts)
        sql += " GROUP BY 1 ORDER BY 1"
        rows = self._con.execute(sql, params).fetchall()
        return [
            # DuckDB str(TIMESTAMP) → "YYYY-MM-DD HH"; API kontrakt = ISO 8601 (T)
            {"hour": str(r[0]).replace(" ", "T"), "events": int(r[1])} for r in rows if r[0] is not None
        ]

    def top_event_types(self, *, limit: int = 20) -> list[dict]:
        """Nejčastější typy událostí."""
        if not self.status()["fresh"]:
            raise AnalyticsError("Stale materiálový stav — spustěte refresh")
        rows = self._con.execute(
            "SELECT event_type, COUNT(*) AS n FROM tl_events GROUP BY 1 ORDER BY 2 DESC LIMIT ?", [limit]
        ).fetchall()
        return [{"event_type": r[0], "count": int(r[1])} for r in rows]

    def entity_summary(self) -> list[dict]:
        """Shrnutí entit po kind: počet + rozsah first_seen/last_seen."""
        if not self.status()["fresh"]:
            raise AnalyticsError("Stale materiálový stav — spustěte refresh")
        rows = self._con.execute(
            """SELECT kind, COUNT(*) AS n, MIN(first_seen) AS earliest, MAX(last_seen) AS latest
               FROM tl_entities GROUP BY 1 ORDER BY 2 DESC"""
        ).fetchall()
        return [
            {
                "kind": r[0],
                "count": int(r[1]),
                "earliest_first_seen": str(r[2]) if r[2] else None,
                "latest_last_seen": str(r[3]) if r[3] else None,
            }
            for r in rows
        ]

    # ── F2.3: block-level deduplikace (CDC bloky v DuckDB) ──

    _BLOCK_TABLE = "block_hashes"

    def refresh_blocks(self) -> dict[str, int]:
        """(Re)vypočítá CDC bloky pro souborové zdroje důkazů do ``block_hashes``.

        Zdroje ``kind='file'`` se skutečně existující cestou na disku (disk image /
        jednotlivé soubory); složkové zdroje jsou ve F2.3 mimo scope. Vždy
        přepočítá — jednorázová operace, nespárovaná se SQLite signaturou
        (bloky vycházejí z bajtů na disku, ne z SQLite).

        Cesta: Rust core (``rust_core.block_dedupe_files`` — batch, jedno GIL
        uvolnění pro všechny soubory) → bez wheelu Python reference
        ``domain.block_dedupe.chunk_bytes``.

        Vrací ``{"files": n_souborů, "blocks": celkem_bloků}``.
        """
        if self.readonly:
            raise AnalyticsError("refresh_blocks() vyžaduje RW AnalyticsStore")

        from stopa.data import rust_core  # lazy — wheel je volitelný

        con = self._con
        con.execute(
            f"CREATE TABLE IF NOT EXISTS {self._BLOCK_TABLE} ("
            "source_id TEXT, file_path TEXT, block_index INTEGER, sha256 TEXT, length INTEGER)"
        )
        srcs = con.execute(
            f"SELECT id, path FROM {self._alias}.main.sources WHERE kind = 'file' ORDER BY id"
        ).fetchall()

        todo: list[tuple[object, Path]] = []
        for source_id, file_path in srcs:
            p = Path(file_path)
            if not p.is_file():
                continue  # zdroj bez souboru na disku — nečistíme tabulku
            todo.append((source_id, p))

        total_blocks = 0
        files_done = 0
        if not todo:
            return {"files": 0, "blocks": 0}

        chunks_by_file = rust_core.block_dedupe_files([p for _sid, p in todo])
        if chunks_by_file is None:  # bez wheelu → Python reference (bajty do paměti)
            from stopa.domain import block_dedupe

            chunks_by_file = [block_dedupe.chunk_bytes(p.read_bytes()) for _sid, p in todo]

        insert_sql = f"INSERT INTO {self._BLOCK_TABLE} VALUES (?, ?, ?, ?, ?)"
        for (source_id, p), chunks in zip(todo, chunks_by_file):
            con.execute(f"DELETE FROM {self._BLOCK_TABLE} WHERE source_id = ?", [source_id])
            if chunks:
                con.executemany(
                    insert_sql,
                    [[source_id, str(p), idx, h, length] for idx, (h, length) in enumerate(chunks)],
                )
            total_blocks += len(chunks)
            files_done += 1
        return {"files": files_done, "blocks": total_blocks}

    def dedupe_summary(self) -> dict:
        """Úspora místa z duplicity bloků (AK F2.3: ≥ 30 % na typických datech).

        Bloky se stejným SHA-256 = identický obsah → stejná délka; unikátní bajty
        = součet délek prvních výskytů hashů. Včetně top 10 nejvíce duplikovaných
        bloků (pro forenzní interpretaci — co se v datech opakuje).
        """
        con = self._con
        try:
            agg = con.execute(
                f"SELECT COUNT(*), COALESCE(SUM(length), 0), COUNT(DISTINCT sha256) "
                f"FROM {self._BLOCK_TABLE}"
            ).fetchone()
            unique_bytes = con.execute(
                f"SELECT COALESCE(SUM(length), 0) FROM (SELECT MIN(length) AS length "
                f"FROM {self._BLOCK_TABLE} GROUP BY sha256)"
            ).fetchone()[0]
        except Exception as exc:
            raise AnalyticsError("block_hashes neexistuje — spusťte refresh_blocks()") from exc

        total_blocks, total_bytes, unique_blocks = int(agg[0]), int(agg[1]), int(agg[2])
        duplicated_bytes = total_bytes - int(unique_bytes)
        top = con.execute(
            f"SELECT sha256, COUNT(*) AS n, MIN(length) AS length FROM {self._BLOCK_TABLE} "
            "GROUP BY 1 HAVING n > 1 ORDER BY 2 DESC LIMIT 10"
        ).fetchall()
        return {
            "total_blocks": total_blocks,
            "unique_blocks": unique_blocks,
            "duplicate_blocks": total_blocks - unique_blocks,
            "total_bytes": total_bytes,
            "unique_bytes": int(unique_bytes),
            "duplicated_bytes": duplicated_bytes,
            "savings_pct": round(duplicated_bytes / total_bytes * 100.0, 2) if total_bytes else 0.0,
            "top_duplicated": [{"sha256": r[0], "count": int(r[1]), "length": int(r[2])} for r in top],
        }
