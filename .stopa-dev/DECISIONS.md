# STOPA — DECISIONS (architektonická rozhodnutí)

Každé rozhodnutí: ID, datum, problém, zvažované možnosti, vybrané řešení, důvod, dopady, dotčené moduly.

## ADR-001 — Clean Architecture jako kostra
- **Datum:** 2026-09 | **Problém:** jak oddělit doménovou logiku od I/O v forenzní aplikaci.
- **Možnosti:** (a) monolit, (b) Clean Architecture vrstvy domain/artifacts/data/web.
- **Vybráno:** (b). `domain/` čistá bez I/O; `artifacts/` I/O jen v entrypointech; `data/` IO vrstva; `web/`+`cli.py` prezentace.
- **Důvod:** offline provoz, testovatelnost doménové logiky bez fixture diskových obrazů, AI jako volitelná závislost.
- **Dopady:** každý nový parser musí respektovat rozvrstvení; pipeline je jediný dispatch bod.
- **Dotčené moduly:** `src/stopa/domain/*`, `src/stopa/artifacts/*`, `src/stopa/data/*`, `src/stopa/web/*`, `pipeline.py`

## ADR-002 — Pipeline dispatch: signatury + name-based fallback
- **Datum:** 2026-10 | **Problém:** XML/mbox nemají spolehlivé magic bytes.
- **Možnosti:** (a) jen magic bytes, (b) signatury + `_name_based_match` fallback, (c) plugin systém s manifestem.
- **Vybráno:** (b). `ARTIFACT_EXTRACTORS` (magic), `NAME_BASED_EXTRACTORS` (názvy souborů), `_extract_registry_all` (sekundární registry průchody — sdílená regf magic).
- **Důvod:** minimální složitost; XML/mbox detekovatelné podle názvu (vzor iCloud Messages); registry hivy sdílejí magiku → jeden kombinovaný průchod.
- **Dopady:** nový parser bez magiky = záznam v `NAME_BASED_EXTRACTORS`; Clipboard/SID nemají nezávislé C3 položky (sekundární průchody).
- **Dotčené moduly:** `pipeline.py`, `src/stopa/artifacts/*`

## ADR-003 — C3 Parser Validation Registry s vynuceným 1:1 syncem
- **Datum:** 2026-10 | **Problém:** jak zajistit, že každý parser má validační specifikaci (ID, verze, formáty, omezení).
- **Možnosti:** (a) volitelné metadata, (b) `build_registry()` s `RegistryError` při nesynchronizaci.
- **Vybráno:** (b). `PARSER_VALIDATIONS` v `domain/validation_registry.py`; `parser_versions()` = unie `ARTIFACT_EXTRACTORS` + `NAME_BASED_EXTRACTORS`.
- **Důvod:** forenzní auditovatelnost — každý parser musí mít ID+verzi; testy chytí rozjezd pipeline vs registry.
- **Dopady:** každý nový nezávislý parser = záznam v PARSER_VALIDATIONS (po vlně 1: 13 parserů).
- **Dotčené moduly:** `src/stopa/domain/validation_registry.py`, `pipeline.py`, `tests/test_validation_registry.py`

## ADR-004 — SQLite schéma s idempotentními migracemi (v11)
- **Datum:** 2026-11 | **Problém:** změna CHECK constraintu confidence levels (I3) v existujících DB.
- **Možnosti:** (a) přepis dat, (b) rebuild tabulek s kopírováním + remap při kopírování.
- **Vybráno:** (b). `_migrate_entity_resolution()` — SQLite nemění CHECK in-place; staré tabulky se rebuildují; legacy hodnoty (`verified`→`confirmed`, `inferred`→`possible`) se remapují **při kopírování řádků** (ne před rebuildem, aby starý CHECK nebyl porušen).
- **Důvod:** zpětná kompatibilita existujících případů; idempotence migrace.
- **Dopady:** SCHEMA_VERSION 10→11; `INSERT...SELECT` bez placeholderů musí jít přes `execute`, ne `executemany`; `sqlite3.Row` nemá `.get()`.
- **Dotčené moduly:** `src/stopa/data/db.py`, `src/stopa/domain/entity_resolution.py`, `tests/test_entity_resolution.py`

## ADR-005 — AXIOM port jako vlny, ne monolit
- **Datum:** 2026-11 | **Problém:** 237 AXIOM extraktorů (C#/.NET) vs STOPA Python; jak portovat bez ztráty kontroly.
- **Možnosti:** (a) hromadný port, (b) vlny podle hodnoty/portovatelnosti s coverage maticí.
- **Vybráno:** (b). `scripts/build_axiom_coverage.py` generuje deterministickou matici (232 unikátních typů: covered 33 / portable-local 38 / cloud-export 112 / memory 15 / base-class 34); vlna 1 = email, WiFi, ScheduledTasks, netstat, Clipboard, SID.
- **Důvod:** každý parser = parser + detekce + registrace (pipeline+C3) + testy + docs; malá kontrolovatelná celka; matice ukazuje pokrok.
- **Dopady:** `artifact_type` je volný TEXT bez CHECK → nové typy projdou bez migrace DB.
- **Dotčené moduly:** `src/stopa/artifacts/*`, `pipeline.py`, `src/stopa/domain/validation_registry.py`, `scripts/build_axiom_coverage.py`, `STOPA_COVERAGE_MATRIX.csv`

## ADR-006 — AI jako volitelná závislost (fail-closed)
- **Datum:** 2026-11 | **Problém:** LLM výstupy nemusí být spolehlivé; AI nesmí blokovat základní forenzní funkce.
- **Možnosti:** (a) AI povinná, (b) volitelná s fail-closed validací výstupů.
- **Vybráno:** (b). 5 deklarativních agentů; Pydantic validace; citace `[art:<id>]` povinné; bez LLM = fallback na pravidla. LM Studio port 1234 (skutečný model ověřit `/api/v0/models`).
- **Důvod:** offline provoz; auditovatelnost AI závěrů ke zdrojům.
- **Dopady:** `intelligence/` samostatná vrstva; RAG s prompt injection ochranou `<untrusted_source>`.
- **Dotčené moduly:** `src/stopa/intelligence/*`, `tests/test_ai_orchestrator.py`, `tests/test_rag.py`

## ADR-007 — Plně offline test suite se syntetickými fixtures
- **Datum:** 2026-10 | **Problém:** jak testovat forenzní logiku bez externích dat/API.
- **Možnosti:** (a) live API, (b) syntetické fixtures + mockované registry hive objekty.
- **Vybráno:** (b). 896 testů plně offline; registry parsery testovány přes monkeypatchovaný `regipy.RegistryHive` (fake hive objekty); uživatel jednou zamítl live stah dat z Yahoo Finance → před externími API se ptát.
- **Důvod:** determinismus, reprodukovatelnost, rychlost (~13 s).
- **Dopady:** každý nový parser = syntetický fixture; mockování jen u I/O hranice (hive), ne u kritické forenzní logiky.
- **Dotčené moduly:** `tests/*`, `src/stopa/artifacts/win_clipboard.py`, `src/stopa/artifacts/win_sids.py`

## ADR-008 — DEV OS projektová paměť v `.stopa-dev/`
- **Datum:** 2026-11-03 | **Problém:** konverzace není pamětí projektu; kontext se ztrácí mezi relacemi.
- **Možnosti:** (a) spolehnout se na chat historii, (b) povinná projektová paměť v repozitáři.
- **Vybráno:** (b). `.stopa-dev/` s PROJECT_STATE, NEXT_ACTION, ROADMAP, TASKS, MODULE_MAP, FEATURE_REGISTRY, TEST_REGISTRY, DECISIONS, CHANGELOG, BLOCKERS + checkpoints.
- **Důvod:** MASTER SYSTEM PROMPT DEV OS; nový agent pokračuje jen na základě těchto souborů.
- **Dopady:** po každém dokončeném úkolu aktualizace paměti + checkpoint; commit `afc49a0`+ (tento bootstrap).
- **Dotčené moduly:** `.stopa-dev/*`, `AGENTS.md`
