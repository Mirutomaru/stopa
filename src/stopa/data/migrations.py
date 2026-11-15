"""Idempotentní migrace starých case DB (ETAPA C vlna 3 — z `CaseDB.__init__`).

Všechny migrace jsou idempotentní (kontrola přes PRAGMA table_info /
sqlite_master) a bezpečné pro opakované spuštění při každém otevření CaseDB.
Nové DB mají vše přímo ze SCHEMA — migrace jsou no-op.
"""

from __future__ import annotations

import sqlite3

from stopa.data.schema import MULTITENANT_DDL, SCHEMA_VERSION, _schema_version
from stopa.domain.integrity import GENESIS, compute_audit_hash


def apply_legacy_migrations(conn: sqlite3.Connection) -> None:
    """Kompletní řetězec idempotentních migrací (původně inline v CaseDB.__init__)."""

    # Migrace: stará case DB bez sloupce meta_addr (GUI hex dump přes TSK icat).
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(files)").fetchall()}
    if "meta_addr" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN meta_addr TEXT")
        conn.commit()
    # STP-022 Security: stará case DB bez sloupce sha512 (SHA-512 v integrity vrstvě).
    if "sha512" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN sha512 TEXT")
        conn.commit()
    # Migrace: stará evidence_marks bez sloupce flags (GUI „Add to Report“).
    em_cols = {r["name"] for r in conn.execute("PRAGMA table_info(evidence_marks)").fetchall()}
    if "flags" not in em_cols:
        conn.execute("ALTER TABLE evidence_marks ADD COLUMN flags TEXT")
        conn.commit()
    # E2 Timeline Engine: stará case DB bez sloupce timezone_name (cases).
    case_cols = {r["name"] for r in conn.execute("PRAGMA table_info(cases)").fetchall()}
    if "timezone_name" not in case_cols:
        conn.execute(
            "ALTER TABLE cases ADD COLUMN timezone_name TEXT DEFAULT 'Europe/Prague'"
        )
        conn.commit()
    # E2 Timeline Engine: stará case DB bez provenience sloupců (artifacts).
    art_cols = {r["name"] for r in conn.execute("PRAGMA table_info(artifacts)").fetchall()}
    for col, decl in (
        ("confidence", "REAL"),
        ("parser_version", "TEXT"),
        ("extracted_at", "TEXT"),
        ("anomaly_flags", "TEXT"),
        # P0 Core C1: Unified Evidence Model — strukturovaná provenance + stav validace.
        ("provenance_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("validation_status", "TEXT NOT NULL DEFAULT 'extracted'"),
        # F4.3 Peer-Review Workflow — stav artifactu (validaci hlídá domain/review.py).
        ("review_state", "TEXT NOT NULL DEFAULT 'draft'"),
    ):
        if col not in art_cols:
            conn.execute(f"ALTER TABLE artifacts ADD COLUMN {col} {decl}")
            conn.commit()
    # P0 Core C4: Evidence Integrity 2.0 — hash chaining audit logu (sloupce + backfill).
    apply_audit_chain_migration(conn)
    # P0 Intelligence I3: Entity Resolution 2.0 — CHECK rozšíření entities/correlations.
    apply_entity_resolution_migration(conn)
    # STP-018 Timeline Intelligence 2.0 — provenience + analytické sloupce timeline_events.
    apply_timeline_intel_migration(conn)
    # STP-069: Plánované/periodické exporty — opt-in přepínač + cesta posledního auto-exportu.
    apply_auto_export_migration(conn)
    # STP-070: Periodický plánovač auto-bundle — interval v minutách + čas posledního spuštění.
    apply_auto_export_schedule_migration(conn)
    # P0 Core C5: Reproducibility Engine — stará DB bez sloupce params_json.
    ops_cols = {r["name"] for r in conn.execute("PRAGMA table_info(analysis_operations)").fetchall()}
    if "params_json" not in ops_cols:
        conn.execute(
            "ALTER TABLE analysis_operations ADD COLUMN params_json TEXT NOT NULL DEFAULT '{}'"
        )
        conn.commit()
    # FÁZE 3 backfill: staré case DB (bez FTS indexu) — jednou doindexovat existující řádky.
    # 'rebuild' u external-content FTS5 přečte obsah přímo z tabulky `files`.
    # Meta-flaga je spolehlivější než COUNT(*) (external-content stíny po delete).
    already = conn.execute(
        "SELECT value FROM meta WHERE key = 'fts_backfilled'"
    ).fetchone()
    if already is None:
        n_files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        if n_files:
            conn.execute("INSERT INTO files_fts(files_fts) VALUES ('rebuild')")
        # flaga vždy — buď jsme rebuild udělali, nebo bylo prázdné (triviálně indexováno)
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('fts_backfilled', '1')"
        )
        conn.commit()
    # E9: backfill artifacts_fts — stará case DB bez FTS nad artifacty.
    already_art = conn.execute(
        "SELECT value FROM meta WHERE key = 'artifacts_fts_backfilled'"
    ).fetchone()
    if already_art is None:
        n_arts = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        if n_arts:
            conn.execute(
                "INSERT INTO artifacts_fts(artifacts_fts) VALUES ('rebuild')"
            )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value)"
            " VALUES ('artifacts_fts_backfilled', '1')"
        )
        conn.commit()
    # F4.4 Multi-tenant RBAC — stará case DB (≤ v16) bez multi-tenant tabulek.
    # Idempotentní (CREATE … IF NOT EXISTS); stub `cases` je no-op, protože case DB
    # už má plnou cases tabulku z _SCHEMA_CORE. Instance DB dostane jen MULTITENANT_DDL.
    existing_tables = {
        r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if not {"orgs", "teams", "users", "case_members"} <= existing_tables:
        conn.executescript(MULTITENANT_DDL)
        conn.commit()
    # E1: verze schématu — stará DB se migrují idempotentně nahoře;
    # po migraci zaznamenáme aktuální verzi pro diagnostiku (stopa audit / Diagnostics).
    if _schema_version(conn) < SCHEMA_VERSION:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value)"
            " VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()


def apply_audit_chain_migration(conn: sqlite3.Connection) -> None:
    """Stará case DB bez hash chaining sloupců (audit_log).

    Idempotentní: přidá ``prev_hash``/``hash`` a backfillne existující řádky
    (řetězec od GENESIS, chronologicky podle id). Nové DB mají sloupce ze SCHEMA.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(audit_log)").fetchall()}
    if "prev_hash" not in cols:
        conn.execute("ALTER TABLE audit_log ADD COLUMN prev_hash TEXT")
        conn.commit()
    if "hash" not in cols:
        conn.execute("ALTER TABLE audit_log ADD COLUMN hash TEXT")
        conn.commit()
    # Backfill: řádky bez hashu (staré DB) — doplnit řetězec od GENESIS.
    rows = conn.execute(
        "SELECT id, ts, action, actor, details_json FROM audit_log"
        " WHERE hash IS NULL ORDER BY id ASC"
    ).fetchall()
    if not rows:
        return
    # append-only triggery (RAISE IGNORE) by UPDATE pohltily — na čas zrušit.
    conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    conn.execute("DROP TRIGGER IF EXISTS audit_no_delete")
    prev = GENESIS
    for r in rows:
        h = compute_audit_hash(prev, r["ts"], r["action"], r["actor"], r["details_json"])
        conn.execute(
            "UPDATE audit_log SET prev_hash = ?, hash = ? WHERE id = ?",
            (prev, h, r["id"]),
        )
        prev = h
    # triggery obnovit (stejná definice jako v SCHEMA)
    conn.executescript(
        """
        CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log BEGIN
            SELECT RAISE(IGNORE);
        END;
        CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log BEGIN
            SELECT RAISE(IGNORE);
        END;
        """
    )
    conn.commit()


def apply_entity_resolution_migration(conn: sqlite3.Connection) -> None:
    """P0 I3 Entity Resolution 2.0 — stará case DB (schéma ≤ v10).

    Idempotentní, bez ztráty dat:
    - ``entities``: CHECK rozšíření o kind ``user_account`` (tabulka se
      rebuilduje — SQLite nemůže ALTER CHECK; žádné FK na tabulku);
    - ``correlations``: confidence 2→4 úrovně (verified→confirmed,
      inferred→possible) + nové sloupce first_seen/last_seen.

    Nové DB mají oba CHECKy a sloupce přímo ze SCHEMA — migrace je no-op.
    """
    from stopa.domain.entity_resolution import map_legacy_confidence  # lazy — bez cyklu

    ent_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='entities'"
    ).fetchone()
    if ent_sql is not None and "user_account" not in str(ent_sql["sql"]):
        cols = [c[1] for c in conn.execute("PRAGMA table_info(entities)").fetchall()]
        conn.execute("ALTER TABLE entities RENAME TO _entities_old")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK (kind IN ('phone', 'email', 'url_host', 'hash', 'user_account')),
                value_normalized TEXT NOT NULL,
                raw_value TEXT,
                first_seen TEXT,
                last_seen TEXT,
                UNIQUE (case_id, kind, value_normalized)
            );
            CREATE INDEX IF NOT EXISTS idx_entities_case ON entities(case_id);
            """
        )
        # INSERT…SELECT bez placeholderů → jeden execute (executemany by čekal parametry)
        conn.execute(
            f"INSERT INTO entities ({', '.join(cols)}) SELECT {', '.join(cols)} FROM _entities_old"
        )
        conn.execute("DROP TABLE _entities_old")
        conn.commit()

    cor_cols = {r["name"] for r in conn.execute("PRAGMA table_info(correlations)").fetchall()}
    if "first_seen" not in cor_cols:
        conn.execute("ALTER TABLE correlations ADD COLUMN first_seen TEXT")
        conn.commit()
    if "last_seen" not in cor_cols:
        conn.execute("ALTER TABLE correlations ADD COLUMN last_seen TEXT")
        conn.commit()

    # CHECK constraint starého schématu — pokud tabulka nemá novou škálu,
    # rebuildovat (i když je prázdná). Staré confidence hodnoty se remapují
    # PŘI KOPÍROVÁNÍ do nové tabulky (verified→confirmed, inferred→possible)
    # — UPDATE před rebuildem by narazil na starý CHECK verified/inferred.
    cor_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='correlations'"
    ).fetchone()
    if cor_sql is not None and "strong_candidate" not in str(cor_sql["sql"]):
        cols = [c[1] for c in conn.execute("PRAGMA table_info(correlations)").fetchall()]
        rows = conn.execute(f"SELECT {', '.join(cols)} FROM correlations").fetchall()
        conn.execute("ALTER TABLE correlations RENAME TO _correlations_old")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS correlations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                entity_a TEXT NOT NULL,
                entity_b TEXT NOT NULL,
                relation TEXT NOT NULL CHECK (relation IN ('same_contact', 'temporal_overlap', 'hash_match')),
                confidence TEXT NOT NULL DEFAULT 'possible' CHECK (confidence IN ('confirmed', 'strong_candidate', 'possible', 'unverified')),
                evidence_json TEXT NOT NULL DEFAULT '[]',
                first_seen TEXT,
                last_seen TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_correlations_case ON correlations(case_id);
            """
        )
        # Kopie řádků s parametry — při tom se remapují legacy confidence
        # (verified→confirmed, inferred→possible) přes map_legacy_confidence.
        conf_idx = cols.index("confidence") if "confidence" in cols else None
        new_rows: list[tuple] = []
        for r in rows:
            vals = list(r)
            if conf_idx is not None and vals[conf_idx] in ("verified", "inferred"):
                vals[conf_idx] = map_legacy_confidence(vals[conf_idx])
            new_rows.append(tuple(vals))
        conn.executemany(
            f"INSERT INTO correlations ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            new_rows,
        )
        conn.execute("DROP TABLE _correlations_old")
        conn.commit()


def apply_timeline_intel_migration(conn: sqlite3.Connection) -> None:
    """STP-018 Timeline Intelligence 2.0 — stará case DB (schéma ≤ v11).

    Idempotentní, bez ztráty dat: přidá sloupce ``ts_origin`` (default
    'source' — staré timestampy jsou vždy z obsahu artifactu),
    ``subject_values_json``, ``contradiction_group_id``, ``dup_group_id``.
    Nové DB mají sloupce přímo ze SCHEMA — migrace je no-op.
    """
    tl_cols = {r["name"] for r in conn.execute("PRAGMA table_info(timeline_events)").fetchall()}
    if "ts_origin" not in tl_cols:
        conn.execute(
            "ALTER TABLE timeline_events ADD COLUMN ts_origin TEXT NOT NULL DEFAULT 'source'"
        )
        conn.commit()
    for col, decl in (
        ("subject_values_json", "TEXT"),
        ("contradiction_group_id", "TEXT"),
        ("dup_group_id", "TEXT"),
    ):
        if col not in tl_cols:
            conn.execute(f"ALTER TABLE timeline_events ADD COLUMN {col} {decl}")
            conn.commit()


def apply_auto_export_migration(conn: sqlite3.Connection) -> None:
    """STP-069 Plánované/periodické exporty — stará case DB (schéma ≤ v12).

    Idempotentní, bez ztráty dat: přidá sloupce ``auto_export_enabled``
    (opt-in přepínač, default 0 = vypnuto) a ``last_auto_export_path``
    (cesta k poslednímu automaticky vygenerovanému ZIP bundle). Nové DB
    mají oba sloupce přímo ze SCHEMA — migrace je no-op.
    """
    case_cols = {r["name"] for r in conn.execute("PRAGMA table_info(cases)").fetchall()}
    if "auto_export_enabled" not in case_cols:
        conn.execute(
            "ALTER TABLE cases ADD COLUMN auto_export_enabled INTEGER NOT NULL DEFAULT 0"
        )
        conn.commit()
    if "last_auto_export_path" not in case_cols:
        conn.execute("ALTER TABLE cases ADD COLUMN last_auto_export_path TEXT")
        conn.commit()


def apply_auto_export_schedule_migration(conn: sqlite3.Connection) -> None:
    """STP-070 Periodický plánovač auto-bundle — stará case DB (schéma ≤ v13).

    Idempotentní, bez ztráty dat: přidá sloupce ``auto_export_interval_minutes``
    (interval periodického auto-exportu v minutách; NULL = nenastaveno →
    scheduler případ přeskočí) a ``last_auto_export_at`` (UTC ISO čas
    posledního spuštění periodického auto-exportu). Nové DB mají oba sloupce
    přímo ze SCHEMA — migrace je no-op.
    """
    case_cols = {r["name"] for r in conn.execute("PRAGMA table_info(cases)").fetchall()}
    if "auto_export_interval_minutes" not in case_cols:
        conn.execute(
            "ALTER TABLE cases ADD COLUMN auto_export_interval_minutes INTEGER"
        )
        conn.commit()
    if "last_auto_export_at" not in case_cols:
        conn.execute("ALTER TABLE cases ADD COLUMN last_auto_export_at TEXT")
        conn.commit()
