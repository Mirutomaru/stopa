# STOPA — Checkpoint (poslední dokončený stav)

**Datum:** 2026-11-04
**Poslední dokončený úkol:** STP-039 — ETAPA C vlna 1: rozdělení monolitu `db.py` (Case/File/Audit repozitáře) | Commit: ```58628a9```

## Stav projektu
- **Fáze:** Oblast A (Core Architecture) — **ETAPA C vlna 1 DOKONČENA ★**
- **Full suite:** 1757 passed, 1 skipped (~18s); ruff clean (`src/stopa tests scripts`)
- **Coverage AXIOM:** covered **198 / 232 ★**, NOT_SUPPORTED celkem **0** (base-class 34 = rozhraní)
- **C3 registry:** 76 parserů (bez změny — vlna 1 je refactor datové vrstvy, ne parsery)

## Co se stalo (STP-039)
Rozklad monolitu `src/stopa/data/db.py` (~2090 ř., 67 metod) na doménová repozitáře — vlna 1:
- **CaseRepository** (`data/case_repository.py`) — cases, sources, custody metadata
- **FileRepository** (`data/file_repository.py`) — files, evidence_marks, FTS5 search + `_fts_query`
- **AuditRepository** (`data/audit_repository.py`) — audit log + hash chaining (P0 Core C4) + Ed25519 kontrolní body + custody items
- **_helpers.py** — sdílené konverze (`_iso`, `_row_to_record`)
- Facade `CaseDB` drží tři repozitáře na **sdílené SQLite connection** a deleguje; **backward compat zachován** (veřejné API beze změny, `_fts_query` re-export pro `test_search`)
- `db.py`: 2090 → **1565 řádků** (−525)
- Nové testy: `tests/test_stp039_wave1_repos.py` (**15 testů**)

## Nejbližší krok
**STP-040 — ETAPA C vlna 2:** extrakce `ArtifactRepository` + `EntityRepository` (~23 metod: artifacts CRUD/FTS5, findings, lineage_events, analysis_operations, entity resolution). Akceptační kritéria: žádná změna veřejného API `CaseDB`, full suite zelená, ruff clean.

## Po vlně 3 (STP-041)
facade úklid + audit — cíl `db.py` < ~600 řádků = ETAPA C dokončena ★
