# STOPA — NEXT ACTION

## Aktuální fáze
Oblast L (Report Engine) — rozšíření reportu z 9 sekcí na 20; ETAPA B vlny 1–3 hotové,
STP-018 Timeline Intelligence 2.0 hotový (commit STP-018).

## ID aktuálního úkolu
**STP-020** (READY — čeká na zahájení)

## Název úkolu
Report engine: 9 → 20 sekcí (titulní strana, metodika, nástroje+verze, omezení, závěr + další sekce)

## Proč se úkol provádí
Report je hlavním výstupem pro soud/experta. Aktuálně má 9 sekcí; profesionální forenzní
report (AXIOM/EnCase standard) vyžaduje titulní stranu s metadaty případu, metodiku,
seznam nástrojů+verzí, omezení analýzy a závěr. Oblast L, priorita **P1** — nejvyšší
priorita mezi definovanými úkoly v TASKS.md (STP-019/021/022 jsou P2, STP-023 je P3).

## Co již bylo provedeno (STP-018, commit STP-018)
- `domain/timeline_intel.py` — nový čistý modul bez IO: rozpory `concurrent_activity`,
  duplikáty napříč zdroji `cross_source_duplicate`, timestamp provenance (`ts_origin` +
  klasifikace přesnosti).
- Schéma **v12**: nové sloupce `timeline_events` (`ts_origin`, `subject_values_json`,
  `contradiction_group_id`, `dup_group_id`) + idempotentní migrace `_migrate_timeline_intel()`.
- Pipeline post-pass `run_timeline_intel()` po ingestu; CLI `stopa timeline --intel [--window N]`;
  web POST `/api/cases/{id}/timeline/intel`; report podsekce Timeline Intelligence 2.0 (8.1);
  export rozšířen o nové sloupce.
- **32 nových testů** (`tests/test_timeline_intel.py`); full suite **1073 passed, 1 skipped**, ruff clean.

## Které soubory byly změněny (STP-018)
`src/stopa/domain/timeline_intel.py` (nový), `src/stopa/data/db.py`, `src/stopa/models.py`,
`src/stopa/pipeline.py`, `src/stopa/cli.py`, `src/stopa/web/app.py`,
`src/stopa/domain/report.py`, `src/stopa/domain/i18n.py`,
`src/stopa/presentation/case_report.py`, `src/stopa/domain/export.py`,
`tests/test_timeline_intel.py` (nový), `tests/test_entity_resolution.py`,
`tests/test_reproducibility.py` (SCHEMA_VERSION aserty → konstanta), README.md,
STOPA_CHANGELOG.md (+ docs zrcadlo).

## Které soubory je potřeba prostudovat (před STP-020)
1. `src/stopa/domain/report.py` — SECTIONS list + build_html (9 sekcí, render funkce)
2. `src/stopa/presentation/case_report.py` — stavba ReportData z case DB
3. `src/stopa/domain/i18n.py` — struktura klíčů cs/en pro nové sekce
4. `.stopa-dev/ROADMAP.md` — oblast L: definice rozsahu 20 sekcí

## Co zbývá dokončit (STP-020)
1. Audit existujících 9 sekcí reportu (co už je, co chybí pro 20 sekcí)
2. Titulní strana: název případu, ID, vyšetřovatel, datum, verze nástroje
3. Metodika: popis použitých metod (extrakce, parsery, korelace) — deterministicky z dat
4. Nástroje+verze: STOPA version + Python/SQLite/TSK/libewf (env_snapshot existuje v C5)
5. Omezení analýzy: chybějící parsery, confidence omezení, RAM peak (z benchmarku)
6. Závěr: souhrn findings + timeline intel rozporů/duplikátů
7. Testy na syntetickém případě; dokumentace; changelog update

## Jaké testy spustit
```bash
.venv/bin/python -m pytest tests/test_report*.py -q   # report testy (pokud existují)
.venv/bin/ruff check src/stopa tests scripts          # lint (musí být clean)
.venv/bin/python -m pytest -q                         # plná sada (baseline 1073 passed, 1 skipped)
```

## Jak poznat úspěšné dokončení
- Report obsahuje nové sekce (titulní strana, metodika, nástroje+verze, omezení, závěr)
- Existující 9 sekcí se nemění (backward compat) — staré testy zůstávají zelené
- Ruff clean na `src/stopa tests scripts`
- Plná sada bez regresí (≥ baseline 1073 passed, 1 skipped)
- Commit `feat(report): STP-020 — Report engine 9 → 20 sekcí ...`

## Co nesmí být změněno
- Existující 9 sekcí reportu (backward compat) — nové sekce se přidávají, staré se nemění
- C3 registry: `build_registry()` vynucuje 1:1 sync s pipeline + shodu verzí, jinak `RegistryError`
- Neodstraňovat existující testy kvůli zelenému výsledku; nepoužívat mockování místo kritické logiky
- Originální důkazní data zůstávají neměnná (report pracuje na case DB)

## Další úkol po STP-020
STP-019 — AI governance + PII redaktor (oblast H/M, P2) nebo STP-021/022 (P2) dle priority.
