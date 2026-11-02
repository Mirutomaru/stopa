# STOPA — Changelog

Formát: Conventional Commits + fáze. Nejnovější nahoře.

## [Unreleased] — 2026-11-02 (ETAPA A–C)

### Added (P0 Core C4 — Evidence Integrity 2.0)
- `domain/integrity.py` — čistá logika bez I/O: **hash chaining** audit logu
  (`compute_audit_hash`, `verify_chain` s detekcí rozbitého řetězce + ID prvního
  špatného řádku), **Ed25519** kontrolní body (lazy import `cryptography` — volitelná
  závislost, graceful degradation jako FDE: `generate_keypair`, `sign_hash`,
  `verify_signature`), **export manifesty** (`build_manifest` + deterministický
  `manifest_hash` — stejný vstup = stejný hash + Ed25519 podpis)
- DB schéma **v8 → v9**: audit_log +sloupce `prev_hash`/`hash`, nová tabulka
  `integrity_checkpoints`; idempotentní `_migrate_audit_chain()` (ALTER + backfill
  řetězce od GENESIS pro staré DB, triggery append-only dočasně zrušeny a obnoveny)
- `CaseDB.log_operation()` nyní chainuje; metody `ensure_integrity_key` /
  `add_integrity_checkpoint` / `verify_integrity_checkpoints`; odstraněna duplicitní
  stará `log_operation`
- CLI: nový subpříkaz **`stopa integrity <case>`** (ověření řetězce + klíč + kontrolní
  body, `--init-key`, `--checkpoint DŮVOD`); Ed25519 pár generován při `case new`;
  kontrolní body automaticky po ingest / correlate / export; `_write_export_manifest()`
  — podepsaný manifest vedle exportního souboru (reprodukovatelnost)
- `tests/test_integrity.py` — 22 testů (čistá logika: chain/tamper/Ed25519 roundtrip/
  manifest determinismus; DB integrace: chaining, backfill staré DB, kontrolní body,
  export manifest); suite 678 → **700 passed**

### Added (P0 Core C3 — Parser Validation Registry)
- `domain/validation_registry.py` — `ParserValidation` (parser_id, verze, formáty,
  omezení, referenční dataset, test files), deklarativní registry pro všech 9 parserů
  (sqlite, registry_hive, plist, lnk, win_prefetch, evtx, icloud_messages, win_jumplist,
  win_usn) s formáty a omezeními dle docstringů parserů
- `build_registry()` — synchronizace s pipeline (`parser_versions()`): každý extraktor má
  záznam v registry a naopak, verze se shodují; nesoulad → `RegistryError`; lazy import
  (domain bez tvrdé závislosti na pipeline)
- `registry_report()` — shrnutí registry pro CLI/GUI
- `tests/test_validation_registry.py` — 10 testů (sync s pipeline, verze, chybějící
  extraktor/záznam, version mismatch, frozen model, report); suite 668 → 678 passed

### Added (P0 Core C2 — Evidence Lineage Engine)
- `domain/lineage.py` — `LineageEvent` (append-only krok: verze nástroje, hash konfigurace,
  vstupní/výstupní reference), `config_hash()` (deterministický SHA-256 kanonické konfigurace),
  `build_chain()` (zpětné dohledání řetězce zdroj → … → ref); čistá logika bez I/O
- DB schéma **v8**: tabulka `lineage_events` + idempotentní migrace starých case DB
- `CaseDB`: log_lineage / list_lineage (chronologicky) / get_lineage_chain (chain traversal)
- Integrace do pipeline: krok `extract` (process_source, output_refs = ID artefaktů),
  `correlate` (run_correlation, artefakty → propojení), `finding_added` (add_finding,
  provenance refy → finding), `report_generated` (HTML/PDF report)
- `ProcessResult.extracted_artifact_ids` — output refs extrakčního kroku
- `tests/test_lineage.py` — 12 testů (model, CRUD, chain traversal, pipeline integrace, migrace v7→v8)

### Added (P0 Core C1 — Unified Evidence Model)
- `domain/evidence_model.py` — ConfidenceLevel (5 úrovní AI grounding), Provenance, Finding
  (povinná provenance = doložitelnost); čistá logika bez I/O
- `models.Artifact` +sloupce `provenance: list[Provenance]`, `validation_status`
  (staré artifacty čitelné s defaulty)
- DB schéma v7: tabulka `findings` (kind, confidence_level CHECK, provenance_json),
  sloupce `artifacts.provenance_json/validation_status`; idempotentní migrace starých DB
- `CaseDB`: add_finding / list_findings (filtry case/kind/confidence) / get_finding / delete_finding
- `tests/test_evidence_model.py` — 14 testů (modely, CRUD, CHECK constraint, migrace v6→v7, roundtrip)

### Added (dokumentace)
- `udelej.md` — master prompt STOPA Ultimate Forensic Platform (zadání)
- `docs/STOPA_TECHNICAL_AUDIT.md` — ETAPA A: kompletní technický audit (ověřená čísla,
  silné stránky, slabá místa S1–S11, návrhy architektonických změn)
- `docs/STOPA_GAP_ANALYSIS.md` — ETAPA B: gap analysis vs. zadání §4–§20
  (IMPLEMENTED/PARTIAL/MISSING/NEEDS VALIDATION/NOT RECOMMENDED + moduly/soubory)
- `docs/STOPA_TARGET_ARCHITECTURE.md` — ETAPA C: cílová architektura, datové modely
  (Unified Evidence Model, schéma v7), API kontrakty, závislosti, migrační strategie,
  technologické vyhodnocení (§20)
- `docs/STOPA_IMPLEMENTATION_ROADMAP.md` — ETAPA C: P0 Core (C1–C6), P0 Intelligence (I1–I5),
  P1 zdroje (S1–S6), P1 Multimedia (M1–M4), P2 enterprise/workspace (E1–E5) + odhady
- `docs/STOPA_VALIDATION_STRATEGY.md` — ETAPA C: Parser Validation Registry, referenční
  datasety, Benchmark Engine, regresní sada, validační reporty, kritéria validace parseru
- `docs/STOPA_SECURITY_MODEL.md` — ETAPA C: hrozby, Integrity 2.0 (hash chaining + Ed25519),
  AI bezpečnost, web API, důvěryhodnost vstupů, kontrolní seznam commitů
- `docs/STOPA_AI_ARCHITECTURE.md` — ETAPA C: multi-agent orchestrátor (5 agentů), Forensic RAG
  (Case/Technical/Knowledge vrstvy), AI grounding (5 úrovní), modelová vrstva

## [0.1.0] — 2026-11-02 (commit ae73ad0)

### Fixed (E-audit + code review)
- Path traversal case_id → `validate_case_id()` regex v open_db/delete_case
- rel_path traversal → resolve()+prefix check; RFC 5987 Content-Disposition + CRLF hardening
- RAM peak exportu → ranged read (seek+read) místo read_bytes()
- Mrtvý kód sqlite_formatter wrapper; redundantní datetime importy v db.py
- README test count; verze z jednoho zdroje (importlib.metadata)

### Added
- CI workflow od noly (ruff + pytest + JS DOM přes jsdom)
- `tests/test_audit_fixes.py` — 15 testů audit oprav
- Suite: **642 passed, 1 skipped**; ruff clean
