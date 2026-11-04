"""SQLite case database — srdce STOPA případu (AXIOM artifact database / FTK index).

Jedna DB na případ: cases, sources, files tabulky. Všechny operace idempotentní
(re-ingest stejného zdroje aktualizuje záznamy podle rel_path).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from stopa.data.artifact_repository import ArtifactRepository  # ETAPA C vlna 2
from stopa.data.audit_repository import AuditRepository  # ETAPA C vlna 1
from stopa.data.case_repository import CaseRepository  # ETAPA C vlna 1
from stopa.data.entity_repository import EntityRepository  # ETAPA C vlna 2
from stopa.data.file_repository import FileRepository, _fts_query  # noqa: F401 — _fts_query backward compat (test_search)
from stopa.domain.evidence_model import Finding
from stopa.domain.integrity import GENESIS, compute_audit_hash  # migrace audit chain
from stopa.domain.lineage import LineageEvent
from stopa.domain.reproducibility import AnalysisOperation
from stopa.models import Artifact, Case, EvidenceSource, FileRecord

# E1: verze schématu — migrace běží idempotentně (IF NOT EXISTS / ALTER),
# ale verze umožňuje detekci starých case DB a zálohu před destruktivní změnou.
SCHEMA_VERSION = 12


def _schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row["value"]) if row else 1


SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    examiner TEXT,
    notes TEXT,
    timezone_name TEXT DEFAULT 'Europe/Prague'  -- E2: lokální TZ pro zobrazení timeline
);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id),
    kind TEXT NOT NULL CHECK (kind IN ('folder', 'file')),
    path TEXT NOT NULL,
    size_bytes INTEGER,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    rel_path TEXT NOT NULL,
    name TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime TEXT, ctime TEXT, atime TEXT,
    sha256 TEXT, md5 TEXT, sha512 TEXT,  -- STP-022: SHA-512 (forensic profil)
    signature_type TEXT, extension TEXT,
    bad_extension INTEGER NOT NULL DEFAULT 0,
    is_duplicate_of TEXT,
    hash_set_hit TEXT,
    meta_addr TEXT,
    UNIQUE (source_id, rel_path)
);
CREATE INDEX IF NOT EXISTS idx_files_source ON files(source_id);
CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    file_id TEXT REFERENCES files(id),
    rel_path TEXT,
    artifact_type TEXT NOT NULL,
    timestamp TEXT,
    title TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    -- E2 Timeline Engine: provenience + důvěryhodnost (reprodukovatelnost analýzy)
    confidence REAL,
    parser_version TEXT,
    extracted_at TEXT,
    anomaly_flags TEXT,  -- komou oddělené kanonické flagy nesrovnalostí
    -- P0 Core C1: Unified Evidence Model — strukturovaná provenance + stav validace
    provenance_json TEXT NOT NULL DEFAULT '[]',
    validation_status TEXT NOT NULL DEFAULT 'extracted'  -- extracted|validated|needs_validation
);
CREATE INDEX IF NOT EXISTS idx_artifacts_source ON artifacts(source_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_ts ON artifacts(timestamp);
-- E3: filtrace artifactů podle typu (GUI chat view, timeline filtry) — častý dotaz
CREATE INDEX IF NOT EXISTS idx_artifacts_type ON artifacts(artifact_type);
-- name-based fallback (iCloud Messages) volá replace pro KAŽDÝ soubor → DELETE WHERE file_id=?
CREATE INDEX IF NOT EXISTS idx_artifacts_file ON artifacts(file_id);

-- E2 Timeline Engine: materializovaná timeline — jeden řádek = jedna událost v čase.
-- Naplní se explicitním insertem při artifact extrakci (pipeline), ne triggerem
-- (trigger by byl křehký na re-ingest / replace). UTC timestamp + lokální zobrazení
-- počítá GUI přes case timezone_name; anomaly_flags = kanonické flagy nesrovnalostí.
CREATE TABLE IF NOT EXISTS timeline_events (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    artifact_id TEXT REFERENCES artifacts(id),
    file_id TEXT REFERENCES files(id),
    rel_path TEXT,
    event_type TEXT NOT NULL,          -- artifact_type (browser_history, chat_message, …)
    ts_utc TEXT NOT NULL,              -- ISO UTC — čas události
    title TEXT,
    confidence REAL,
    parser_version TEXT,
    extracted_at TEXT,                 -- kdy byl artifact extrahován (odliší se od event time)
    anomaly_flags TEXT,                -- komou oddělené kanonické flagy nesrovnalostí
    -- STP-018 Timeline Intelligence 2.0: provenience + přesnost timestampů
    ts_origin TEXT NOT NULL DEFAULT 'source',   -- source (z obsahu) | derived (MACE apod.)
    subject_values_json TEXT,          -- normalizované entity subjektu (JSON list) — pro rozpory
    contradiction_group_id TEXT,       -- ID skupiny časového rozporu (NULL = bez rozporu)
    dup_group_id TEXT                  -- ID skupiny duplikátu napříč zdroji (NULL = originál)
);
CREATE INDEX IF NOT EXISTS idx_timeline_ts ON timeline_events(ts_utc);
CREATE INDEX IF NOT EXISTS idx_timeline_source ON timeline_events(source_id);

-- E4 Entity + Correlation Engine: kanonické entity extrahované z artifactů.
-- value_normalized je klíč pro propojování (tel:+E164, email lowercase, host, hash hex).
-- first_seen/last_seen = rozsah časové osy, kdy se entita objevila (z timestampů artifactů).
-- P0 I3 Entity Resolution 2.0: + kind 'user_account' (platformní identifikátory).
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

-- E4: propojení mezi entitami — explicitní krok `stopa correlate` (ne při extrakci).
-- relation: same_contact | temporal_overlap | hash_match.
-- P0 I3 Entity Resolution 2.0: confidence = 4 úrovně vztahů
--   (confirmed / strong_candidate / possible / unverified); staré DB migrují
--   verified→confirmed, inferred→possible. first_seen/last_seen = časové rozmezí vztahu.
-- evidence_json = [ {artifact_id, file_id, rel_path, detail} ] — dohledatelnost každého propojení.
CREATE TABLE IF NOT EXISTS correlations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    entity_a TEXT NOT NULL,        -- kanonický identifikátor (tel:+420..., email:...)
    entity_b TEXT NOT NULL,
    relation TEXT NOT NULL CHECK (relation IN ('same_contact', 'temporal_overlap', 'hash_match')),
    confidence TEXT NOT NULL DEFAULT 'possible' CHECK (confidence IN ('confirmed', 'strong_candidate', 'possible', 'unverified')),
    evidence_json TEXT NOT NULL DEFAULT '[]',
    first_seen TEXT,               -- P0 I3: časové rozmezí vztahu (ISO UTC)
    last_seen TEXT,                -- P0 I3: časové rozmezí vztahu (ISO UTC)
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_correlations_case ON correlations(case_id);

-- Meta (verze schématu, stav FTS indexu…)
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- GUI: ručně označené soubory (File Inspector → „Mark as Evidence“ / „Add to Report“)
CREATE TABLE IF NOT EXISTS evidence_marks (
    file_id TEXT PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    marked_at TEXT NOT NULL,
    flags TEXT  -- komou oddělené flagy: "evidence", "report"
);

-- E1 Evidence Manager: neměnný audit log operací (kdo/kdy/co — SWGDE-style provenience)
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    -- P0 Core C4: Evidence Integrity 2.0 — hash chaining (prev_hash + vlastní hash)
    prev_hash TEXT,
    hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
-- append-only: UPDATE/DELETE se tichom ignorují (RAISE(IGNORE)) — neměnná stopa
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log BEGIN
    SELECT RAISE(IGNORE);
END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log BEGIN
    SELECT RAISE(IGNORE);
END;

-- P0 Core C1: Unified Evidence Model — derived findings / analytical observations.
-- Každé zjištění nese confidence_level (5 úrovní, AI grounding §5.3) a provenance_json
-- (≥1 Provenance záznam — doložitelnost až k důkaznímu zdroji). details_json = volitelný obsah.
CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,  -- correlation | anomaly | contradiction | ai_observation | …
    confidence_level TEXT NOT NULL DEFAULT 'derived'
        CHECK (confidence_level IN ('direct', 'derived', 'interpretation', 'hypothesis', 'unverified')),
    provenance_json TEXT NOT NULL DEFAULT '[]',
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_findings_case ON findings(case_id);
CREATE INDEX IF NOT EXISTS idx_findings_kind ON findings(kind);

-- P0 Core C2: Evidence Lineage Engine — append-only řetězec původu zjištění.
-- Každý krok (extract/correlate/finding/report) nese verzi nástroje, hash konfigurace
-- a vstupní/výstupní reference → zpětné dohledání tvrzení v reportu až k důkazu.
CREATE TABLE IF NOT EXISTS lineage_events (
    id TEXT PRIMARY KEY,
    case_id TEXT REFERENCES cases(id) ON DELETE CASCADE,  -- NULL = operace mimo konkrétní případ
    op_type TEXT NOT NULL,  -- extract | correlate | finding_added | report_generated | …
    tool_version TEXT,
    config_hash TEXT,
    input_refs_json TEXT NOT NULL DEFAULT '[]',
    output_refs_json TEXT NOT NULL DEFAULT '[]',
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lineage_case ON lineage_events(case_id);
CREATE INDEX IF NOT EXISTS idx_lineage_op ON lineage_events(op_type);

-- P0 Core C4: Evidence Integrity 2.0 — Ed25519 kontrolní body.
-- Kontrolní bod = podpis hashu posledního audit řádku; ukládá se po operacích
-- měnících důkazy (ingest, correlate, export) + na požádání. Nezávislá kontrola:
-- veřejný klíč + kontrolní body stačí k ověření integrity bez soukromého klíče.
CREATE TABLE IF NOT EXISTS integrity_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    audit_row_id INTEGER NOT NULL,  -- ID posledního audit řádku v okamžiku podpisu
    last_hash TEXT NOT NULL,        -- hash posledního audit řádku (podepsaný)
    signature_b64 TEXT NOT NULL,    -- Ed25519 podpis last_hash (base64)
    reason TEXT                     -- ingest | correlate | export | manual | …
);

-- P0 Core C5: Reproducibility Engine — záznamy analytických operací.
-- Každá operace nese vstupní soubory + hashe, verze parserů/STOPA, hash konfigurace,
-- deterministický souhrn výstupů a prostředí → opakovatelnost + porovnání výsledků.
CREATE TABLE IF NOT EXISTS analysis_operations (
    id TEXT PRIMARY KEY,
    case_id TEXT REFERENCES cases(id) ON DELETE CASCADE,  -- NULL = operace mimo konkrétní případ
    op_type TEXT NOT NULL,          -- extract | correlate | …
    source_id TEXT,                 -- zdroj operace (extract → evidence source)
    input_files_json TEXT NOT NULL DEFAULT '[]',   -- [{rel_path, sha256}] vstupních souborů
    parser_versions_json TEXT NOT NULL DEFAULT '{}',  -- verze všech parserů v době běhu
    stopa_version TEXT,             -- verze STOPA (single-source z pyproject)
    config_hash TEXT,               -- SHA-256 normalizované konfigurace (profil + parametry)
    params_json TEXT NOT NULL DEFAULT '{}',  -- parametry operace pro replay (profil, …)
    outputs_json TEXT NOT NULL DEFAULT '{}',  -- deterministický souhrn výsledku (porovnání replay)
    duration_ms INTEGER,            -- čas zpracování v ms
    env_json TEXT NOT NULL DEFAULT '{}',      -- prostředí: python / platforma / sqlite
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ops_case ON analysis_operations(case_id);
CREATE INDEX IF NOT EXISTS idx_ops_type ON analysis_operations(op_type);

-- E1 Evidence Manager: custody items — metadata nabytí důkazu per source (průběžná evidence)
CREATE TABLE IF NOT EXISTS custody_items (
    source_id TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
    acquired_at TEXT NOT NULL,
    method TEXT,
    custodian TEXT,
    notes TEXT
);

-- FÁZE 3: full-text search (FTS5) — external content nad `files` + sync triggery.
-- Idempotentní i pro staré case DB z FÁZE 1 (IF NOT EXISTS).
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    rel_path, name, signature_type, hash_set_hit,
    content='files', content_rowid='rowid'
);
CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, rel_path, name, signature_type, hash_set_hit)
    VALUES (new.rowid, new.rel_path, new.name, new.signature_type, new.hash_set_hit);
END;
CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, rel_path, name, signature_type, hash_set_hit)
    VALUES ('delete', old.rowid, old.rel_path, old.name, old.signature_type, old.hash_set_hit);
END;
CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, rel_path, name, signature_type, hash_set_hit)
    VALUES ('delete', old.rowid, old.rel_path, old.name, old.signature_type, old.hash_set_hit);
    INSERT INTO files_fts(rowid, rel_path, name, signature_type, hash_set_hit)
    VALUES (new.rowid, new.rel_path, new.name, new.signature_type, new.hash_set_hit);
END;

-- E9 Search rozšíření: full-text nad artifacty (title + details_json).
-- External content nad `artifacts` — rowid = artifacts.rowid. details_json je
-- surový JSON (tokenizace unicode61 rozloží i hodnoty uvnitř klíčů/hodnot).
CREATE VIRTUAL TABLE IF NOT EXISTS artifacts_fts USING fts5(
    artifact_type, title, details_json,
    content='artifacts', content_rowid='rowid'
);
CREATE TRIGGER IF NOT EXISTS artifacts_ai AFTER INSERT ON artifacts BEGIN
    INSERT INTO artifacts_fts(rowid, artifact_type, title, details_json)
    VALUES (new.rowid, new.artifact_type, new.title, new.details_json);
END;
CREATE TRIGGER IF NOT EXISTS artifacts_ad AFTER DELETE ON artifacts BEGIN
    INSERT INTO artifacts_fts(artifacts_fts, rowid, artifact_type, title, details_json)
    VALUES ('delete', old.rowid, old.artifact_type, old.title, old.details_json);
END;
CREATE TRIGGER IF NOT EXISTS artifacts_au AFTER UPDATE ON artifacts BEGIN
    INSERT INTO artifacts_fts(artifacts_fts, rowid, artifact_type, title, details_json)
    VALUES ('delete', old.rowid, old.artifact_type, old.title, old.details_json);
    INSERT INTO artifacts_fts(rowid, artifact_type, title, details_json)
    VALUES (new.rowid, new.artifact_type, new.title, new.details_json);
END;
"""


class CaseDB:
    """Tenká SQLite vrstva — žádné business logiky (ta je v domain/)."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        # Migrace: stará case DB bez sloupce meta_addr (GUI hex dump přes TSK icat).
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(files)").fetchall()}
        if "meta_addr" not in cols:
            self.conn.execute("ALTER TABLE files ADD COLUMN meta_addr TEXT")
            self.conn.commit()
        # STP-022 Security: stará case DB bez sloupce sha512 (SHA-512 v integrity vrstvě).
        if "sha512" not in cols:
            self.conn.execute("ALTER TABLE files ADD COLUMN sha512 TEXT")
            self.conn.commit()
        # Migrace: stará evidence_marks bez sloupce flags (GUI „Add to Report“).
        em_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(evidence_marks)").fetchall()}
        if "flags" not in em_cols:
            self.conn.execute("ALTER TABLE evidence_marks ADD COLUMN flags TEXT")
            self.conn.commit()
        # E2 Timeline Engine: stará case DB bez sloupce timezone_name (cases).
        case_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(cases)").fetchall()}
        if "timezone_name" not in case_cols:
            self.conn.execute(
                "ALTER TABLE cases ADD COLUMN timezone_name TEXT DEFAULT 'Europe/Prague'"
            )
            self.conn.commit()
        # E2 Timeline Engine: stará case DB bez provenience sloupců (artifacts).
        art_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(artifacts)").fetchall()}
        for col, decl in (
            ("confidence", "REAL"),
            ("parser_version", "TEXT"),
            ("extracted_at", "TEXT"),
            ("anomaly_flags", "TEXT"),
            # P0 Core C1: Unified Evidence Model — strukturovaná provenance + stav validace.
            ("provenance_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("validation_status", "TEXT NOT NULL DEFAULT 'extracted'"),
        ):
            if col not in art_cols:
                self.conn.execute(f"ALTER TABLE artifacts ADD COLUMN {col} {decl}")
                self.conn.commit()
        # P0 Core C4: Evidence Integrity 2.0 — hash chaining audit logu (sloupce + backfill).
        self._migrate_audit_chain()
        # P0 Intelligence I3: Entity Resolution 2.0 — CHECK rozšíření entities/correlations.
        self._migrate_entity_resolution()
        # STP-018 Timeline Intelligence 2.0 — provenience + analytické sloupce timeline_events.
        self._migrate_timeline_intel()
        # P0 Core C5: Reproducibility Engine — stará DB bez sloupce params_json.
        ops_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(analysis_operations)").fetchall()}
        if "params_json" not in ops_cols:
            self.conn.execute(
                "ALTER TABLE analysis_operations ADD COLUMN params_json TEXT NOT NULL DEFAULT '{}'"
            )
            self.conn.commit()
        # FÁZE 3 backfill: staré case DB (bez FTS indexu) — jednou doindexovat existující řádky.
        # 'rebuild' u external-content FTS5 přečte obsah přímo z tabulky `files`.
        # Meta-flaga je spolehlivější než COUNT(*) (external-content stíny po delete).
        already = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'fts_backfilled'"
        ).fetchone()
        if already is None:
            n_files = self.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            if n_files:
                self.conn.execute("INSERT INTO files_fts(files_fts) VALUES ('rebuild')")
            # flaga vždy — buď jsme rebuild udělali, nebo bylo prázdné (triviálně indexováno)
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('fts_backfilled', '1')"
            )
            self.conn.commit()
        # E9: backfill artifacts_fts — stará case DB bez FTS nad artifacty.
        already_art = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'artifacts_fts_backfilled'"
        ).fetchone()
        if already_art is None:
            n_arts = self.conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
            if n_arts:
                self.conn.execute(
                    "INSERT INTO artifacts_fts(artifacts_fts) VALUES ('rebuild')"
                )
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, value)"
                " VALUES ('artifacts_fts_backfilled', '1')"
            )
            self.commit()
        # E1: verze schématu — stará DB se migrují idempotentně nahoře;
        # po migraci zaznamenáme aktuální verzi pro diagnostiku (stopa audit / Diagnostics).
        if _schema_version(self.conn) < SCHEMA_VERSION:
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, value)"
                " VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self.conn.commit()
        # ETAPA C vlna 1 — doménová repozitáře (sdílená connection). Facade
        # CaseDB deleguje; backward compat API zůstává na CaseDB.
        self.case_repo = CaseRepository(self.conn)
        self.file_repo = FileRepository(self.conn)
        self.audit_repo = AuditRepository(self.conn)
        # ETAPA C vlna 2 — artifacty/findings/lineage + entity/correlations.
        self.artifact_repo = ArtifactRepository(self.conn)
        self.entity_repo = EntityRepository(self.conn)

    def schema_version(self) -> int:
        """Aktuální verze schématu case DB (E1 — diagnostika / migrace)."""
        return _schema_version(self.conn)

    # ── P0 Core C4: Evidence Integrity 2.0 ────────────────────
    def _migrate_audit_chain(self) -> None:
        """Stará case DB bez hash chaining sloupců (audit_log).

        Idempotentní: přidá ``prev_hash``/``hash`` a backfillne existující řádky
        (řetězec od GENESIS, chronologicky podle id). Nové DB mají sloupce ze SCHEMA.
        """
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(audit_log)").fetchall()}
        if "prev_hash" not in cols:
            self.conn.execute("ALTER TABLE audit_log ADD COLUMN prev_hash TEXT")
            self.conn.commit()
        if "hash" not in cols:
            self.conn.execute("ALTER TABLE audit_log ADD COLUMN hash TEXT")
            self.conn.commit()
        # Backfill: řádky bez hashu (staré DB) — doplnit řetězec od GENESIS.
        rows = self.conn.execute(
            "SELECT id, ts, action, actor, details_json FROM audit_log"
            " WHERE hash IS NULL ORDER BY id ASC"
        ).fetchall()
        if not rows:
            return
        # append-only triggery (RAISE IGNORE) by UPDATE pohltily — na čas zrušit.
        self.conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
        self.conn.execute("DROP TRIGGER IF EXISTS audit_no_delete")
        prev = GENESIS
        for r in rows:
            h = compute_audit_hash(prev, r["ts"], r["action"], r["actor"], r["details_json"])
            self.conn.execute(
                "UPDATE audit_log SET prev_hash = ?, hash = ? WHERE id = ?",
                (prev, h, r["id"]),
            )
            prev = h
        # triggery obnovit (stejná definice jako v SCHEMA)
        self.conn.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log BEGIN
                SELECT RAISE(IGNORE);
            END;
            CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log BEGIN
                SELECT RAISE(IGNORE);
            END;
            """
        )
        self.conn.commit()

    def _migrate_entity_resolution(self) -> None:
        """P0 I3 Entity Resolution 2.0 — stará case DB (schéma ≤ v10).

        Idempotentní, bez ztráty dat:
        - ``entities``: CHECK rozšíření o kind ``user_account`` (tabulka se
          rebuilduje — SQLite nemůže ALTER CHECK; žádné FK na tabulku);
        - ``correlations``: confidence 2→4 úrovně (verified→confirmed,
          inferred→possible) + nové sloupce first_seen/last_seen.

        Nové DB mají oba CHECKy a sloupce přímo ze SCHEMA — migrace je no-op.
        """
        from stopa.domain.entity_resolution import map_legacy_confidence  # lazy — bez cyklu

        ent_sql = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='entities'"
        ).fetchone()
        if ent_sql is not None and "user_account" not in str(ent_sql["sql"]):
            cols = [c[1] for c in self.conn.execute("PRAGMA table_info(entities)").fetchall()]
            self.conn.execute("ALTER TABLE entities RENAME TO _entities_old")
            self.conn.executescript(
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
            self.conn.execute(
                f"INSERT INTO entities ({', '.join(cols)}) SELECT {', '.join(cols)} FROM _entities_old"
            )
            self.conn.execute("DROP TABLE _entities_old")
            self.conn.commit()

        cor_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(correlations)").fetchall()}
        if "first_seen" not in cor_cols:
            self.conn.execute("ALTER TABLE correlations ADD COLUMN first_seen TEXT")
            self.conn.commit()
        if "last_seen" not in cor_cols:
            self.conn.execute("ALTER TABLE correlations ADD COLUMN last_seen TEXT")
            self.conn.commit()

        # CHECK constraint starého schématu — pokud tabulka nemá novou škálu,
        # rebuildovat (i když je prázdná). Staré confidence hodnoty se remapují
        # PŘI KOPÍROVÁNÍ do nové tabulky (verified→confirmed, inferred→possible)
        # — UPDATE před rebuildem by narazil na starý CHECK verified/inferred.
        cor_sql = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='correlations'"
        ).fetchone()
        if cor_sql is not None and "strong_candidate" not in str(cor_sql["sql"]):
            cols = [c[1] for c in self.conn.execute("PRAGMA table_info(correlations)").fetchall()]
            rows = self.conn.execute(f"SELECT {', '.join(cols)} FROM correlations").fetchall()
            self.conn.execute("ALTER TABLE correlations RENAME TO _correlations_old")
            self.conn.executescript(
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
            self.conn.executemany(
                f"INSERT INTO correlations ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                new_rows,
            )
            self.conn.execute("DROP TABLE _correlations_old")
            self.conn.commit()

    def _migrate_timeline_intel(self) -> None:
        """STP-018 Timeline Intelligence 2.0 — stará case DB (schéma ≤ v11).

        Idempotentní, bez ztráty dat: přidá sloupce ``ts_origin`` (default
        'source' — staré timestampy jsou vždy z obsahu artifactu),
        ``subject_values_json``, ``contradiction_group_id``, ``dup_group_id``.
        Nové DB mají sloupce přímo ze SCHEMA — migrace je no-op.
        """
        tl_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(timeline_events)").fetchall()}
        if "ts_origin" not in tl_cols:
            self.conn.execute(
                "ALTER TABLE timeline_events ADD COLUMN ts_origin TEXT NOT NULL DEFAULT 'source'"
            )
            self.conn.commit()
        for col, decl in (
            ("subject_values_json", "TEXT"),
            ("contradiction_group_id", "TEXT"),
            ("dup_group_id", "TEXT"),
        ):
            if col not in tl_cols:
                self.conn.execute(f"ALTER TABLE timeline_events ADD COLUMN {col} {decl}")
                self.conn.commit()

    def _last_audit_row(self) -> tuple[int | None, str]:
        """ID posledního audit řádku + jeho hash (GENESIS pokud log prázdný)."""
        return self.audit_repo._last_audit_row()

    def _case_examiner(self) -> str | None:
        """Examiner případu (fallback actor pro audit trail). Case DB = jeden případ."""
        return self.audit_repo._case_examiner()

    def log_operation(
        self,
        action: str,
        actor: str | None = None,
        details: dict | None = None,
        *,
        strict: bool = False,  # STP-022 — RBAC minimální (actor povinný)
    ) -> int:
        """Neměnný záznam operace (append-only) + hash chaining (P0 Core C4). Vrací ID řádku."""
        return self.audit_repo.log_operation(action, actor, details, strict=strict)

    def verify_audit_chain(self):
        """Ověří celý hash řetězec audit logu. Vrací :class:`ChainReport`."""
        return self.audit_repo.verify_audit_chain()

    # ── Ed25519 kontrolní body (P0 Core C4) ───────────────────
    def ensure_integrity_key(self) -> tuple[str, str]:
        """Vygeneruje Ed25519 klíčový pár případu (idempotentní)."""
        return self.audit_repo.ensure_integrity_key()

    def integrity_public_key(self) -> str | None:
        """Veřejný Ed25519 klíč případu (base64), pokud byl vygenerován."""
        return self.audit_repo.integrity_public_key()

    def add_integrity_checkpoint(self, reason: str) -> int | None:
        """Podpisne hash posledního audit řádku a uloží kontrolní bod."""
        return self.audit_repo.add_integrity_checkpoint(reason)

    def list_integrity_checkpoints(self) -> list[dict]:
        """Kontrolní body (chronologicky) — pro report / nezávislou kontrolu."""
        return self.audit_repo.list_integrity_checkpoints()

    def verify_integrity_checkpoints(self) -> list[dict]:
        """Ověří kontrolní body veřejným klíčem (nezávislá kontrola)."""
        return self.audit_repo.verify_integrity_checkpoints()

    # ── cases ────────────────────────────────────────────────
    def add_case(self, case: Case) -> None:
        self.case_repo.add_case(case)

    def list_cases(self) -> list[Case]:
        """Všechny případy v case DB (pro web GUI přehled)."""
        return self.case_repo.list_cases()

    def get_case(self, case_id: str) -> Case | None:
        return self.case_repo.get_case(case_id)

    def update_case(
        self,
        case_id: str,
        name: str | None = None,
        examiner: str | None = None,
        notes: str | None = None,
        timezone_name: str | None = None,
    ) -> bool:
        """E12 — aktualizace metadat případu (jen zadaná pole). True pokud existoval."""
        return self.case_repo.update_case(
            case_id, name=name, examiner=examiner, notes=notes, timezone_name=timezone_name
        )

    def delete_case(self, case_id: str) -> bool:
        """E12 — smaže případ i všechny jeho zdroje (kaskáda na files/artifacts/timeline)."""
        return self.case_repo.delete_case(case_id)

    # ── sources ──────────────────────────────────────────────
    def add_source(self, source: EvidenceSource) -> None:
        self.case_repo.add_source(source)

    def get_source(self, source_id: str) -> EvidenceSource | None:
        return self.case_repo.get_source(source_id)

    def list_sources(self, case_id: str) -> list[EvidenceSource]:
        return self.case_repo.list_sources(case_id)

    # ── files ────────────────────────────────────────────────
    def upsert_file(self, rec: FileRecord) -> str:
        """Idempotentní insert/update podle (source_id, rel_path). Vrací kanonický file id."""
        return self.file_repo.upsert_file(rec)

    def commit(self) -> None:
        self.conn.commit()

    def list_files(
        self,
        source_id: str | None = None,
        bad_extensions_only: bool = False,
        duplicates_only: bool = False,
        signature_family: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[FileRecord]:
        return self.file_repo.list_files(
            source_id=source_id,
            bad_extensions_only=bad_extensions_only,
            duplicates_only=duplicates_only,
            signature_family=signature_family,
            limit=limit,
            offset=offset,
        )

    def get_file(self, file_id: str) -> FileRecord | None:
        """Jeden soubor podle ID (File Inspector v GUI)."""
        return self.file_repo.get_file(file_id)

    # ── file flags (GUI File Inspector: „Mark as Evidence“ / „Add to Report“) ──
    def set_file_flag(self, file_id: str, flag: str, on: bool) -> None:
        """Přepne flag souboru („evidence“ / „report“). Idempotentní."""
        self.file_repo.set_file_flag(file_id, flag, on)

    def get_file_flags(self, file_id: str) -> tuple[str, ...]:
        return self.file_repo.get_file_flags(file_id)

    def list_marked(self) -> list[tuple[FileRecord, tuple[str, ...]]]:
        """Všechny označené soubory (pro report / Evidence modul)."""
        return self.file_repo.list_marked()

    # ── E1 Evidence Manager: audit log + custody items ────────
    def list_audit_log(
        self, limit: int | None = 100, offset: int | None = None
    ) -> list[dict]:
        """Audit trail — nejnovější operace první (chronologická stopa)."""
        return self.audit_repo.list_audit_log(limit=limit, offset=offset)

    def set_custody_item(
        self,
        source_id: str,
        acquired_at: datetime | None = None,
        method: str | None = None,
        custodian: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Metadata nabytí důkazu pro jeden source (idempotentní upsert)."""
        self.audit_repo.set_custody_item(
            source_id, acquired_at=acquired_at, method=method, custodian=custodian, notes=notes
        )

    def get_custody_item(self, source_id: str) -> dict | None:
        return self.audit_repo.get_custody_item(source_id)

    def list_custody_items(self) -> list[dict]:
        return self.audit_repo.list_custody_items()

    def search(
        self,
        query: str,
        source_id: str | None = None,
        limit: int | None = 100,
    ) -> list[FileRecord]:
        """Full-text search (FTS5) + E9 metadata filtry + in-artifact prefix.

        `query` — kombinace FTS5 termínů a prefixovaných filtrů:
        - textové termíny → files_fts MATCH (fráze, prefix *, AND/OR/NOT)
        - ``size:>1MB`` / ``mtime:2026-01..2026-06`` / ``ext:jpg`` → SQL WHERE
        - ``in-artifact:X`` → artifacts_fts MATCH → vráceny soubory s odpovídajícím artifactem

        Výsledek je řazen podle relevance (bm25) a omezen na existující soubory.
        """
        return self.file_repo.search(query, source_id=source_id, limit=limit)

    def search_by_hash(
        self, hash_hex: str, source_id: str | None = None, limit: int | None = 100
    ) -> list[FileRecord]:
        """E9 — exact hash lookup (SHA-256 / SHA-512 / MD5).

        `hash_hex` — hex string bez prefixu; porovnává se s columnami
        sha256, sha512 a md5 (case-insensitive přes LOWER). STP-022: +SHA-512.
        """
        return self.file_repo.search_by_hash(hash_hex, source_id=source_id, limit=limit)

    def stats(self, source_id: str | None = None) -> dict[str, int]:
        return self.file_repo.stats(source_id)

    # ── artifacts (AXIOM-style) ──────────────────────────────
    # ── P0 Core C1: Unified Evidence Model — artifacts (ETAPA C vlna 2 → ArtifactRepository) ──
    def upsert_artifact(self, art: Artifact) -> None:
        """Idempotentní upsert artifactu podle (source_id, artifact_type, rel_path)."""
        self.artifact_repo.upsert_artifact(art)

    def replace_artifacts_for_file(self, file_id: str, arts: list[Artifact]) -> int:
        """Idempotentní výměna artifactů jednoho souboru (re-ingest → čisté data)."""
        return self.artifact_repo.replace_artifacts_for_file(file_id, arts)

    def clear_timeline_events(self, source_id: str | None = None) -> int:
        """Odstraní materializované timeline události; ``source_id=None`` vyčistí celý případ."""
        return self.artifact_repo.clear_timeline_events(source_id)

    def list_artifacts(
        self,
        source_id: str | None = None,
        artifact_type: str | None = None,
        rel_path_like: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        anomalies_only: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Artifact]:
        """Timeline dotaz — chronologicky; E2 filtry (časové okno, anomálie)."""
        return self.artifact_repo.list_artifacts(
            source_id=source_id,
            artifact_type=artifact_type,
            rel_path_like=rel_path_like,
            from_ts=from_ts,
            to_ts=to_ts,
            anomalies_only=anomalies_only,
            limit=limit,
            offset=offset,
        )

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        """Jeden artifact podle ID (E11 — AI explain režim); ``None`` = nenalezen."""
        return self.artifact_repo.get_artifact(artifact_id)

    # ── P0 Core C1: findings (ETAPA C vlna 2 → ArtifactRepository) ───────
    def add_finding(self, finding: Finding) -> str:
        """Vloží derived finding / analytical observation. Vrací ID záznamu."""
        return self.artifact_repo.add_finding(finding)

    def list_findings(
        self,
        case_id: str | None = None,
        kind: str | None = None,
        confidence_level: str | None = None,
    ) -> list[Finding]:
        """Findings s volitelnými filtry (case/kind/confidence)."""
        return self.artifact_repo.list_findings(
            case_id=case_id, kind=kind, confidence_level=confidence_level
        )

    def get_finding(self, finding_id: str) -> Finding | None:
        """Jeden finding podle ID; ``None`` = nenalezen."""
        return self.artifact_repo.get_finding(finding_id)

    def delete_finding(self, finding_id: str) -> bool:
        """Odstraní finding; ``True`` pokud řádek existoval."""
        return self.artifact_repo.delete_finding(finding_id)

    # ── P0 Core C2: Evidence Lineage (ETAPA C vlna 2 → ArtifactRepository) ──
    def log_lineage(
        self,
        op_type: str,
        *,
        case_id: str | None = None,
        tool_version: str | None = None,
        config_hash: str | None = None,
        input_refs: tuple[str, ...] | list[str] = (),
        output_refs: tuple[str, ...] | list[str] = (),
        details: dict | None = None,
    ) -> str:
        """Zaznamená jeden krok v řetězci důkazů (append-only). Vrací ID události."""
        return self.artifact_repo.log_lineage(
            op_type,
            case_id=case_id,
            tool_version=tool_version,
            config_hash=config_hash,
            input_refs=input_refs,
            output_refs=output_refs,
            details=details,
        )

    def list_lineage(self, case_id: str | None = None) -> list[LineageEvent]:
        """Všechny lineage události (volitelně jen pro případ), chronologicky."""
        return self.artifact_repo.list_lineage(case_id)

    def get_lineage_chain(self, ref: str) -> list[LineageEvent]:
        """Zpětné dohledání řetězce pro referenci (vzor ``build_chain``)."""
        return self.artifact_repo.get_lineage_chain(ref)

    # ── P0 Core C5: Reproducibility Engine (ETAPA C vlna 2 → ArtifactRepository) ──
    def record_operation(
        self,
        op_type: str,
        *,
        case_id: str | None = None,
        source_id: str | None = None,
        input_files: list[dict[str, str | None]] | None = None,
        parser_versions: dict[str, str] | None = None,
        stopa_version: str | None = None,
        config_hash: str | None = None,
        params: dict | None = None,
        outputs: dict | None = None,
        duration_ms: int | None = None,
    ) -> str:
        """Zaznamená analytickou operaci pro opakování + porovnání (append-only)."""
        return self.artifact_repo.record_operation(
            op_type,
            case_id=case_id,
            source_id=source_id,
            input_files=input_files,
            parser_versions=parser_versions,
            stopa_version=stopa_version,
            config_hash=config_hash,
            params=params,
            outputs=outputs,
            duration_ms=duration_ms,
        )

    def list_operations(
        self, case_id: str | None = None, op_type: str | None = None
    ) -> list[AnalysisOperation]:
        """Záznamy operací (chronologicky); volitelně filtrované případem / typem."""
        return self.artifact_repo.list_operations(case_id=case_id, op_type=op_type)

    def get_operation(self, op_id: str) -> AnalysisOperation | None:
        """Jeden záznam operace podle ID (None pokud neexistuje)."""
        return self.artifact_repo.get_operation(op_id)

    # ── E2 Timeline Engine (ETAPA C vlna 2 → ArtifactRepository) ───────────
    def add_timeline_event(
        self,
        *,
        source_id: str,
        ts_utc: datetime,
        event_type: str,
        artifact_id: str | None = None,
        file_id: str | None = None,
        rel_path: str | None = None,
        title: str | None = None,
        confidence: float | None = None,
        parser_version: str | None = None,
        extracted_at: datetime | None = None,
        anomaly_flags: tuple[str, ...] | list[str] = (),
        ts_origin: str = "source",  # STP-018: source (z obsahu) | derived (MACE apod.)
        subject_values: tuple[str, ...] | list[str] = (),  # STP-018: normalizované entity subjektu
    ) -> str:
        """Explicitní insert jednoho timeline eventu (ROADMAP E2 bod 2)."""
        return self.artifact_repo.add_timeline_event(
            source_id=source_id,
            ts_utc=ts_utc,
            event_type=event_type,
            artifact_id=artifact_id,
            file_id=file_id,
            rel_path=rel_path,
            title=title,
            confidence=confidence,
            parser_version=parser_version,
            extracted_at=extracted_at,
            anomaly_flags=anomaly_flags,
            ts_origin=ts_origin,
            subject_values=subject_values,
        )

    def list_timeline_events(
        self,
        source_id: str | None = None,
        event_type: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        anomalies_only: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict]:
        """Timeline dotaz nad materializovanou tabulkou (chronologicky)."""
        return self.artifact_repo.list_timeline_events(
            source_id=source_id,
            event_type=event_type,
            from_ts=from_ts,
            to_ts=to_ts,
            anomalies_only=anomalies_only,
            limit=limit,
            offset=offset,
        )

    def set_timeline_intel_groups(
        self,
        contradiction: dict[str, str],  # event_id → group_id (jen události v rozporu)
        duplicates: dict[str, str],     # event_id → dup_group_id (jen duplikáty napříč zdroji)
    ) -> int:
        """STP-018 — zápis analytických skupin do materializované timeline."""
        return self.artifact_repo.set_timeline_intel_groups(contradiction, duplicates)

    def clear_timeline_intel_groups(self) -> None:
        """STP-018 — reset analytických skupin + jejich flagů (před re-runem)."""
        self.artifact_repo.clear_timeline_intel_groups()

    def timeline_window(self, source_id: str | None = None) -> dict[str, datetime | None]:
        """Min/max pozorovaných časů událostí — operační okno pro anomaly detekci."""
        return self.artifact_repo.timeline_window(source_id)

    def artifact_stats(self, source_id: str | None = None) -> dict[str, int]:
        """Počty artifactů celkem + podle typu (volitelně jen zdroj)."""
        return self.artifact_repo.artifact_stats(source_id)

    # ── E4 Entity + Correlation Engine (ETAPA C vlna 2 → EntityRepository) ──
    def upsert_entities(self, case_id: str, rows) -> int:
        """Idempotentní upsert kanonických entit (UNIQUE case+kind+value)."""
        return self.entity_repo.upsert_entities(case_id, rows)

    def list_entities(self, case_id: str) -> list[dict]:
        """Kanonické entity případu (ORDER BY kind, value_normalized)."""
        return self.entity_repo.list_entities(case_id)

    def clear_correlations(self, case_id: str) -> int:
        """Vymaže propojení případu (re-run korelace = explicitní krok)."""
        return self.entity_repo.clear_correlations(case_id)

    def add_correlation(
        self,
        case_id: str,
        entity_a: str,
        entity_b: str,
        relation: str,
        confidence: str,
        evidence: list[dict],
        first_seen: str | None = None,
        last_seen: str | None = None,
    ) -> int:
        """Vloží jedno propojení s evidence listem. Vrací ID řádku."""
        return self.entity_repo.add_correlation(
            case_id, entity_a, entity_b, relation, confidence, evidence,
            first_seen=first_seen, last_seen=last_seen,
        )

    def list_correlations(self, case_id: str) -> list[dict]:
        """Propojení případu s evidence listy (ORDER BY id)."""
        return self.entity_repo.list_correlations(case_id)

    def close(self) -> None:
        self.conn.close()



# ETAPA C vlna 1: _FTS5_OPS + _fts_query přesunuty do file_repository.py
# (import nahoře; backward compat pro `from stopa.data.db import _fts_query`).
