"""SQLite schéma case DB — tabulky, indexy, triggery (ETAPA C vlna 3 z db.py).

Jedna DB na případ. Schéma se aplikuje idempotentně (`IF NOT EXISTS`);
staré case DB doplní `apply_legacy_migrations()` z `migrations.py`.
"""

from __future__ import annotations

import sqlite3

# E1: verze schématu — migrace běží idempotentně (IF NOT EXISTS / ALTER),
# ale verzi umožňuje detekci starých case DB a zálohu před destruktivní změnou.
SCHEMA_VERSION = 28


def _schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row["value"]) if row else 1


_SCHEMA_CORE = """
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    examiner TEXT,
    notes TEXT,
    timezone_name TEXT DEFAULT 'Europe/Prague',  -- E2: lokální TZ pro zobrazení timeline
    auto_export_enabled INTEGER NOT NULL DEFAULT 0,  -- STP-069: opt-in automatický export (default off)
    last_auto_export_path TEXT,  -- STP-069: cesta k poslednímu automatickému ZIP bundle
    auto_export_interval_minutes INTEGER,  -- STP-070: interval periodického auto-bundle v minutách (NULL = nenastaveno)
    last_auto_export_at TEXT  -- STP-070: UTC čas posledního spuštění periodického auto-exportu
);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id),
    kind TEXT NOT NULL CHECK (kind IN ('folder', 'file')),
    path TEXT NOT NULL,
    size_bytes INTEGER,
    added_at TEXT NOT NULL,
    -- P0.4/P1 — source manifest: deterministický snapshot souborového stavu zdroje
    manifest_sha256 TEXT,  -- SHA-256 kanonické serializace (NULL = dosud nevytvořen)
    manifest_version INTEGER DEFAULT 1,
    manifest_json TEXT,  -- kanonická forma položek (historie drží audit chain)
    created_at_utc TEXT,  -- ISO 8601 UTC — čas vytvoření manifestu
    file_count INTEGER,
    total_size_bytes INTEGER,
    source_type TEXT,
    source_identifier TEXT,
    acquisition_method TEXT,
    filesystem_type TEXT,
    acquisition_tool_version TEXT
);
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    rel_path TEXT NOT NULL,
    name TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime TEXT, ctime TEXT, atime TEXT,
    sha256 TEXT, md5 TEXT, sha512 TEXT,  -- STP-022: SHA-512 (forensic profil)
    hashed_at TEXT,  -- P0-1 provenance: čas vyhasování (ISO UTC; NULL = legacy řádek před v21)
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
    validation_status TEXT NOT NULL DEFAULT 'extracted',  -- extracted|validated|needs_validation
    review_state TEXT NOT NULL DEFAULT 'draft'            -- F4.3 peer-review: draft→reviewed→approved→court_ready
        CHECK (review_state IN ('draft','reviewed','approved','court_ready')),
    parent_artifact_id TEXT REFERENCES artifacts(id) ON DELETE SET NULL  -- P0-1 provenance: odvozený artefakt (NULL = kořenový)
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

-- F3.5: Hypothesis Graph — AI generuje graf hypotéz (pro → proti, confidence),
-- člověk ručně potvrzuje/vyvrací. Citace = ID artefaktů (lineage k důkazu).
CREATE TABLE IF NOT EXISTS hypotheses (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    claim TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0.1 AND confidence <= 0.9),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'confirmed', 'refuted')),
    support_json TEXT NOT NULL DEFAULT '[]',   -- ID artefaktů: důkazy PRO hypotézu
    against_json TEXT NOT NULL DEFAULT '[]',   -- ID artefaktů: důkazy PROTI hypotéze
    parent_id TEXT REFERENCES hypotheses(id) ON DELETE SET NULL,  -- podhypotéza (strom)
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hypotheses_case ON hypotheses(case_id);
CREATE INDEX IF NOT EXISTS idx_hypotheses_status ON hypotheses(status);

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
    reason TEXT,                    -- ingest | correlate | export | manual | key_rotation
    public_key_b64 TEXT             -- P0-2: klíč, kterým byl bod podepsán (rotace-safe ověření; NULL = legacy → meta fallback)
);

-- F4.3 — Peer-Review Workflow: auditní stopa review akcí u artefaktů.
-- Aktuální stav = normalizovaný sloupec artifacts.review_state; tady je neměnná
-- historie (kdo, kdy, na co) pro soudní doložitelnost. Kritický artefakt
-- vyžaduje ≥ 2 distinct examinátorů před schválením (domain/review.py).
CREATE TABLE IF NOT EXISTS artifact_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    reviewer TEXT NOT NULL,
    new_state TEXT NOT NULL CHECK (new_state IN ('draft','reviewed','approved','court_ready')),
    note TEXT,
    ts_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifact_reviews_case ON artifact_reviews(case_id);
CREATE INDEX IF NOT EXISTS idx_artifact_reviews_artifact ON artifact_reviews(artifact_id);
"""

#: F4.4 — multi-tenant RBAC DDL; aplikuje se samostatně i na instance DB
# (``{db_dir}/stopa_instance.db``) — orgs/teams/users/case_members jsou globální
# objekty sdílené napříč case DB (stejné tabulky v case DB = forward-compat).
MULTITENANT_DDL = """
-- stub cases pro FK z case_members v instance DB; v case DB ho IF NOT EXISTS přeskočí
CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY);

-- F4.4: Multi-tenant RBAC — organizace → týmy → uživatelé + per-case členství.
-- Fail-closed: nečlen bez admin role nemá přístup (domain/multitenant.py).
CREATE TABLE IF NOT EXISTS orgs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    UNIQUE(org_id, name)
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT,
    team_id TEXT REFERENCES teams(id) ON DELETE SET NULL,
    role TEXT NOT NULL DEFAULT 'examiner' CHECK (role IN ('analyst','examiner','admin')),
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS case_members (
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('analyst','examiner','admin')),
    granted_by TEXT,
    ts_utc TEXT NOT NULL,
    PRIMARY KEY(case_id, user_id)
);
"""

#: P2-6 — Cross-case correlation DDL (**instance DB** ``{db_dir}/stopa_instance.db``,
# ne case DB): audit trail dotazů s hash chainem (GENESIS → SHA-256; stejný idiom
# jako P2-4 ``hypothesis_revisions``) + explicitní cross-tenant oprávnění uživatelům.
#: Aplikuje se idempotentně vedle :data:`MULTITENANT_DDL` (bez verze instance DB).
CROSS_CASE_DDL = """
-- P2-6: Audit trail cross-case dotazů — kdo/kdy/které případy/rozsah, hash chain.
CREATE TABLE IF NOT EXISTS cross_case_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT,                      -- username (multi-user) / None = legacy single-operator
    cases_json TEXT NOT NULL,        -- seřazená ID případů dotazu (deterministické)
    scope_json TEXT NOT NULL DEFAULT '{}',  -- {"entity": "email"|"phone"|"hash"|null}
    prev_hash TEXT NOT NULL,         -- hash předchozího záznamu nebo 'GENESIS'
    hash TEXT NOT NULL               -- SHA-256(prev_hash|payload) — kanonický JSON
);

-- P2-6: Explicitní cross-tenant grant (user → org): dotaz smí mostovat mezi
-- vlastní tenancí uživatele a daným orgem. Default = jen stejný tenant.
CREATE TABLE IF NOT EXISTS xcorr_grants (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    granted_by TEXT,
    ts_utc TEXT NOT NULL,
    PRIMARY KEY(user_id, org_id)
);
"""

#: P2-2 — Centrální registr případů DDL (**instance DB** ``{db_dir}/stopa_instance.db``,
#: ne case DB): cross-case přehled s tenancy kontrolou při čtení. ``tenant`` = primární
#: tenance (deterministicky nejmenší org_id mezi orgy členů; NULL = legacy/bez vlastníka).
#: ``stats_json`` = deterministický snapshot {"files", "artifacts", "size_bytes"} z case DB.
#: Sync při lifecycle operacích (create/delete/update) + explicitní ``stopa registry --sync``.
CASE_REGISTRY_DDL = """
-- P2-2: Centrální registr případů — cross-case přehled nad instance DB.
CREATE TABLE IF NOT EXISTS case_registry (
    case_id TEXT PRIMARY KEY,        -- odpovídá {case_id}.db v db_dir
    name TEXT NOT NULL DEFAULT '',   -- zobrazovací název případu (z cases.name)
    examiner TEXT,                   -- vedoucí vyšetřovatel / vlastník
    tenant TEXT,                     -- primární org_id; NULL = legacy/bez vlastníka
    created_at TEXT,                 -- ISO UTC z case DB (cases.created_at)
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    stats_json TEXT NOT NULL DEFAULT '{}',  -- {"files": N, "artifacts": M, "size_bytes": K}
    synced_at TEXT NOT NULL,                -- poslední sync ISO UTC
    node_id TEXT,                           -- P4-7: který uzel naposledy heartbeatnul řádek
    last_heartbeat INTEGER NOT NULL DEFAULT 0  -- P4-7: monotónní seq lease (bez clock driftu)
);
CREATE INDEX IF NOT EXISTS idx_case_registry_tenant ON case_registry(tenant);
"""

#: P4-7 — DB event bus (instance DB): cross-process distribuce LiveEvent událostí
# bez Redis. ``id`` = monotónní sekvence → deterministický pořad napříč procesy
# (pořadí = id, ne čas; ``ts_utc`` je jen diagnostika). Polling worker čte
# ``WHERE id > ? ORDER BY id`` (viz :mod:`stopa.data.event_repository`).
EVENT_BUS_DDL = """
-- P4-7: Cross-process event bus v instance DB (polling worker, bez Redis).
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- monotónní sekvence — deterministický pořad
    topic TEXT NOT NULL,                   -- case:{case_id} (domain.events.case_topic)
    payload_json TEXT NOT NULL,            -- kanonické JSON události (sort_keys, bez mezer)
    ts_utc TEXT NOT NULL                   -- ISO UTC (diagnostika; pořadí = id)
);
CREATE INDEX IF NOT EXISTS idx_events_topic_id ON events(topic, id);
"""

#: F4.5 — Case sharing & collaboration DDL (case DB): comments na artefaktech
# + in-app notifikace. ``artifact_comments.case_id`` je denormalizace (artifacts
# nemá vlastní case_id sloupec — JOIN přes files→sources; viz F4.3).
COLLAB_DDL = """
-- F4.5: Case sharing & collaboration — comments na artefaktech + @mentions.
-- Optimistické zamykání: revision bumpuje se každou editací (conflict resolution);
-- mentions_json = [username, …] rozparsované z těla komentáře (domain/collab.py).
CREATE TABLE IF NOT EXISTS artifact_comments (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    author TEXT NOT NULL,
    body TEXT NOT NULL CHECK (length(body) <= 4000),
    mentions_json TEXT NOT NULL DEFAULT '[]',
    revision INTEGER NOT NULL DEFAULT 0,
    edited_at TEXT,
    ts_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifact_comments_case ON artifact_comments(case_id);
CREATE INDEX IF NOT EXISTS idx_artifact_comments_artifact ON artifact_comments(artifact_id);

-- F4.5: In-app notifikace (inbox per uživatel; email backend injektovatelný).
-- username = příjemce (lidově čitelné, přežije i smazání uživatele z org).
CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('mention', 'comment', 'shared')),
    body TEXT NOT NULL,
    case_id TEXT,
    artifact_id TEXT,
    read INTEGER NOT NULL DEFAULT 0,
    ts_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(username, read);
"""

#: F5.1 — Merkle Tree Case Sealing DDL (case DB). Pečeť = snapshot stavu případu
# (první N řádků artifacts/timeline_events v pořadí vložení + audit prefix do
# audit_row_id) zamknutý jedním Merkle kořenem podepsaným Ed25519 klíčem případu.
# Sub-rooty per tabulka ve meta_json = diagnostika „která tabulka se změnila".
CASE_SEALS_DDL = """
CREATE TABLE IF NOT EXISTS case_seals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,                 -- UTC ISO čas zamčení
    sealed_by TEXT,                   -- znalec/actor v okamžiku pečetě
    reason TEXT,                      -- manual | before_court | export | …
    artifacts_count INTEGER NOT NULL,  -- fixovaný počet řádků artifacts (první v pořadí vložení)
    timeline_count INTEGER NOT NULL,   -- fixovaný počet řádků timeline_events
    audit_row_id INTEGER NOT NULL,     -- poslední audit_log id zahrnutý v pečetí (předpona)
    root_hash TEXT NOT NULL,           -- hex Merkle kořen (64 znaků, SHA-256)
    signature_b64 TEXT NOT NULL,       -- Ed25519 podpis root_hash (base64)
    public_key_b64 TEXT NOT NULL,      -- snapshot veřejného klíče v okamžiku pečetě
    meta_json TEXT NOT NULL DEFAULT '{}'  -- formát verze, sub-rooty per tabulka, columns_hash
);
"""

#: P4-6 — Sealing v2: time hash chain F5.1 pečetí (case DB, aditivní v27).
# Každý záznam vazí předchozí Merkle root + aktuální root + case_id + čas
# (chain_hash = SHA-256; genesis = self-binding vlastní root) → manipulace
# s jakýmkoli minulým rootem láme linku. seal_id = 1:1 odkaz na řádek
# case_seals (zdroj Ed25519 podpisu); merkle_root je denormalizovaná kopie
# pro samostatnou tamper-evidence + vazbu witnesse. witness_json = externí
# důkaz (kind/ref/digest/content_b64) — volitelný out-of-band attestation.
SEAL_CHAIN_DDL = """
CREATE TABLE IF NOT EXISTS seal_chain (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,             -- pořadové číslo v řetězci případu (1-based)
    seal_id INTEGER NOT NULL UNIQUE,  -- 1:1 na case_seals.id (Ed25519 podpis + root)
    ts TEXT NOT NULL,                 -- musí odpovídat case_seals.ts dané pečetě
    merkle_root TEXT NOT NULL,        -- kopie case_seals.root_hash (tamper-evidence)
    prev_merkle_root TEXT NOT NULL,   -- root předchozí pečetě; genesis = vlastní root
    chain_hash TEXT NOT NULL,         -- H(prev || case_id || ts || merkle_root), SHA-256 hex
    witness_json TEXT,                -- P4-6 externí witness (null = bez attestation)
    UNIQUE (case_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_seal_chain_case ON seal_chain(case_id);
"""

# P1-3 Evidence Graph — ruční/AI hrany unifikovaného grafu důkazů.
# Každá hrana nese vztah, polaritu (podpůrná/protichůdná), důvod vzniku a confidence.
# Derived hrany (korelace/hypotézy/události/findings) se počítají na letě
# z existujících tabulek — tady se ukládají jen explicitní ruční/AI vztahy.
GRAPH_EDGES_DDL = """
CREATE TABLE IF NOT EXISTS graph_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    src_type TEXT NOT NULL CHECK (src_type IN ('artifact','entity','event','finding','hypothesis')),
    src_id TEXT NOT NULL,
    dst_type TEXT NOT NULL CHECK (dst_type IN ('artifact','entity','event','finding','hypothesis')),
    dst_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    polarity TEXT NOT NULL DEFAULT 'neutral' CHECK (polarity IN ('supports','contradicts','neutral')),
    reason TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
    created_at TEXT NOT NULL,
    UNIQUE (case_id, src_type, src_id, dst_type, dst_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_graph_edges_case ON graph_edges(case_id);
"""

# P2-4 Investigation Workspace — poznámky, úkoly a revize hypotéz (aditivní).
# Poznámka je ukotvena na artefakt/entity/timeline event; revize hypotézy =
# append-only řetězec s hash chain (tamper detekce bez LLM).
INVESTIGATION_DDL = """
CREATE TABLE IF NOT EXISTS inv_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    ref_kind TEXT NOT NULL CHECK (ref_kind IN ('artifact', 'entity', 'timeline_event')),
    ref_id TEXT NOT NULL,
    text TEXT NOT NULL,
    author TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inv_notes_case ON inv_notes(case_id);

CREATE TABLE IF NOT EXISTS inv_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'done')),
    assignee TEXT,
    due TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inv_tasks_case ON inv_tasks(case_id);

CREATE TABLE IF NOT EXISTS hypothesis_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    hypothesis_id TEXT NOT NULL REFERENCES hypotheses(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    content_json TEXT NOT NULL,
    author TEXT,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (hypothesis_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_hyprev_case ON hypothesis_revisions(case_id);
"""

#: P2-5 — Threat Intelligence Workspace DDL (case DB): IoC feed items s TLP a
# stářím intel dat + deterministické matchingy IoC × artefakty/entity.
INTEL_DDL = """
-- P2-5: IoC položky feedu — id = UUIDv5(kind|value), double-import = 1 řádek.
CREATE TABLE IF NOT EXISTS ioc_feed_items (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('ip', 'domain', 'hash', 'url', 'yara_rule', 'sigma_tpl')),  -- P3-5: pravidla = feed itemy
    value TEXT NOT NULL,             -- kanonický tvar (E4 kanonika)
    raw_value TEXT,                  -- původní tvar z feedu
    tlp TEXT NOT NULL DEFAULT 'GREEN' CHECK (tlp IN ('WHITE', 'GREEN', 'AMBER', 'RED')),
    source TEXT,                     -- zdroj intel dat (feed/proces)
    acquired_at TEXT NOT NULL,       -- ISO UTC — základ stáří klasifikace
    imported_at TEXT NOT NULL        -- ISO UTC času importu
);
CREATE INDEX IF NOT EXISTS idx_ioc_feed_case ON ioc_feed_items(case_id);

-- P2-5: Matching IoC × case artefakty/entity (re-run = clear + insert).
CREATE TABLE IF NOT EXISTS intel_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    ioc_id TEXT NOT NULL REFERENCES ioc_feed_items(id) ON DELETE CASCADE,
    match_kind TEXT NOT NULL CHECK (match_kind IN ('entity', 'file_hash', 'artifact_text', 'yara', 'sigma')),
    -- P3-5: yara/sigma = shody dedikovaných engine (pravidla žijí ve feedu)
    evidence_json TEXT NOT NULL DEFAULT '[]',  -- [{artifact_id, rel_path, ts_utc}, …] strop MAX_EVIDENCE
    first_seen TEXT,
    last_seen TEXT,
    matched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intel_matches_case ON intel_matches(case_id);
"""

# P3-3: výsledky klasifikace souborů (pravidlový klasifikátor, W2).
# Re-run `classify` = upsert AUTO polí per file (deterministický výsledek
# domain/classification.py); lidský override je aditivní sloupec — automatická
# hodnota vždy zůstává dohledatelná (reverzibilní, AK3). CHECK taxonomie musí
# sedět na CATEGORIES v domain/classification.py.
CLASSIFICATIONS_DDL = """
CREATE TABLE IF NOT EXISTS classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    file_id TEXT NOT NULL UNIQUE REFERENCES files(id) ON DELETE CASCADE,
    rel_path TEXT NOT NULL,          -- denormalizováno pro zobrazení
    category TEXT NOT NULL CHECK (category IN ('browser', 'chat_messaging', 'email', 'contact_identity', 'cloud_sync', 'location_tracking', 'system_logs', 'memory_capture', 'crypto_assets', 'documents_media', 'unknown')),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    reasons_json TEXT NOT NULL DEFAULT '[]',   -- JSON list[str] — neprázdné (AK2)
    needs_review INTEGER NOT NULL DEFAULT 0,
    risk_flags_json TEXT NOT NULL DEFAULT '[]',
    classified_at TEXT NOT NULL,     -- ISO UTC času běhu klasifikátoru
    stopa_version TEXT,              -- verze STOPA (single-source z pyproject)
    status TEXT NOT NULL DEFAULT 'auto' CHECK (status IN ('auto', 'overridden')),
    override_category TEXT CHECK (override_category IS NULL OR override_category IN ('browser', 'chat_messaging', 'email', 'contact_identity', 'cloud_sync', 'location_tracking', 'system_logs', 'memory_capture', 'crypto_assets', 'documents_media', 'unknown')),
    override_actor TEXT,             -- actor lidského override (RBAC resolved)
    override_reason TEXT NOT NULL DEFAULT '',  -- důvod override (forenzní stopa)
    overridden_at TEXT               -- ISO UTC času override
);
CREATE INDEX IF NOT EXISTS idx_classifications_case ON classifications(case_id);
"""

SCHEMA = _SCHEMA_CORE + MULTITENANT_DDL + COLLAB_DDL + CASE_SEALS_DDL + """
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
    notes TEXT,
    -- P0-1 provenance: acquisition metadata (aditivní; NULL = legacy řádek před v21)
    acquisition_tool TEXT, tool_version TEXT, verified_hash TEXT
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
""" + GRAPH_EDGES_DDL + INVESTIGATION_DDL + INTEL_DDL + CLASSIFICATIONS_DDL + SEAL_CHAIN_DDL  # P1-3 hrany / P2-4 investigation workspace / P2-5 threat intel (aditivní) / P3-3 klasifikace souborů (v26, aditivní) / P4-6 sealing v2 chain (v27, aditivní)
