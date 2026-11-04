# STOPA — Checkpoint (poslední dokončený stav)

**Datum:** 2026-11-04
**Poslední dokončený úkol:** STP-040 — ETAPA C vlna 2: rozdělení monolitu `db.py` (Artifact/Entity repozitáře) | Commit: ```28b6222```

## Stav projektu
- **Fáze:** Oblast A (Core Architecture) — **ETAPA C vlna 2 DOKONČENA ★**
- **Full suite:** 1774 passed, 1 skipped (~18s); ruff clean (`src/stopa tests scripts`)
- **Coverage AXIOM:** covered **198 / 232 ★**, NOT_SUPPORTED celkem **0** (base-class 34 = rozhraní)
- **C3 registry:** 76 parserů (bez změny — vlna 2 je refactor datové vrstvy, ne parsery)

## Co se stalo (STP-040)
Rozklad monolitu `src/stopa/data/db.py` na doménová repozitáře — vlna 2:
- **ArtifactRepository** (`data/artifact_repository.py`, 712 ř.) — artifacts upsert/replace/list/get, findings CRUD, lineage_events append-only + dohledání řetězce, analysis_operations, timeline events + intel groups + window; konvertory `_row_to_artifact`/`_row_to_finding`/`_row_to_lineage_event`/`_row_to_analysis_operation`
- **EntityRepository** (`data/entity_repository.py`, 138 ř.) — entities upsert s agregací first/last_seen při re-runu, correlations clear/add/list
- `db.py`: 1565 → **1011 řádků** (−554); facade `CaseDB` drží pět repozitářů na sdílené connection a deleguje; backward compat zachován (`CaseDB`, `SCHEMA_VERSION`, `_fts_query`)
- Testy: 17 nových testů zelených (`tests/test_stp040_wave2_repos.py`)

## Nejbližší krok
**STP-041 — ETAPA C vlna 3:** facade úklid + závěrečný audit; cíl `db.py` < ~600 ř. = **ETAPA C dokončena ★**.
