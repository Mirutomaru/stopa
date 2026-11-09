"""SQLite schéma case DB — tabulky, indexy, triggery (ETAPA C vlna 3 z db.py).

Jedna DB na případ. Schéma se aplikuje idempotentně (`IF NOT EXISTS`);
staré case DB doplní `apply_legacy_migrations()` z `migrations.py`.
"""

from __future__ import annotations

import sqlite3

# E1: verze schématu — migrace běží idempotentně (IF NOT EXISTS / ALTER),
# ale verze umožňuje detekci starých case DB a zálohu před destruktivní změnou.
SCHEMA_VERSION = 13


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
    timezone_name TEXT DEFAULT 'Europe/Prague',  -- E2: lokální TZ pro zobrazení timeline
    auto_export_enabled INTEGER NOT NULL DEFAULT 0,  -- STP-069: opt-in automatický export (default off)
    last_auto_export_path TEXT  -- STP-069: cesta k poslednímu automatickému ZIP bundle
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
