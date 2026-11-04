# STOPA — NEXT ACTION

**Datum:** 2026-11-04
**Poslední hotový úkol:** STP-039 — ETAPA C vlna 1: rozdělení monolitu `db.py` (Case/File/Audit repozitáře) | Commit ```58628a9``` ★ **ETAPA C vlna 1 DOKONČENA**

## Co je hotové
- ETAPA B dokončena (STP-037, vlna 15 — závěrečný audit; commit `166e42e`); oblast D ✅ hotovo.
- ETAPA C zahájena (STP-038 volba směru + synchronizace roadmapy; commit `1292e72`).
- **ETAPA C vlna 1 dokončena (STP-039):** vyčleněny CaseRepository + FileRepository + AuditRepository do samostatných modulů, sdílené konverze do `_helpers.py`; facade `CaseDB` deleguje na sdílenou connection; backward compat zachován. `db.py` 2090 → **1565 řádků** (−525). Full suite **1757 passed, 1 skipped**, ruff clean.

## Nejbližší úkol — STP-040 (ETAPA C vlna 2)
**Rozdělení `db.py` — extrakce `ArtifactRepository` + `EntityRepository`:**
1. Nové moduly `src/stopa/data/artifact_repository.py`, `entity_repository.py`.
2. Přesun ~23 metod (artifacts CRUD/FTS5, findings, lineage_events, analysis_operations, entity resolution).
3. `CaseDB` deleguje do repozitářů — facade zachován pro backward compat (žádná změna veřejného API).
4. Testy: existující suite musí zůstat zelená + nové testy repozitářů; ruff clean.

**Akceptační kritéria:** žádná změna veřejného API `CaseDB`, full suite **1757+ passed**, ruff clean, commit `refactor(data): ETAPA C vlna 2 — Artifact/Entity Repository`.

## Po STP-040
STP-041 (vlna 3: facade úklid + audit, cíl `db.py` < ~600 ř.) = **ETAPA C dokončena ★**.
