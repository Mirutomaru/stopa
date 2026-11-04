# STOPA — Nejbližší akce

**Datum:** 2026-11-04
**Poslední dokončený úkol:** STP-040 — ETAPA C vlna 2: rozdělení monolitu `db.py` (Artifact/Entity repozitáře) | Commit: ```28b6222```

## Stav
- **ETAPA C vlna 1+2 DOKONČENA ★** — `db.py` 2090 → **1011 řádků** (−54 % původní velikosti)
- Facade `CaseDB` drží pět repozitářů na sdílené SQLite connection: Case / File / Audit / Artifact / Entity
- Full suite **1774 passed, 1 skipped**; ruff clean; backward compat API beze změny

## Nejbližší úkol
**STP-041 — ETAPA C vlna 3: rozdělení `db.py` — facade úklid + závěrečný audit** (oblast A, P1)
- Úklid zbývajícího kódu v `CaseDB` (SCHEMA/migrace/close zůstávají; delegované metody bez duplicit)
- Závěrečný audit celého rozkladu: backward compat API (`CaseDB`, `SCHEMA_VERSION`, `_fts_query`), plná test suite, ruff clean
- **Cíl: `db.py` < ~600 ř. = ETAPA C dokončena ★**

## Akceptační kritéria (vlna 3)
1. Žádná změna veřejného API `CaseDB`
2. Full suite zelená, ruff clean
3. `db.py` < ~600 řádků; pět repozitářů + `_helpers` jako samostatné moduly
