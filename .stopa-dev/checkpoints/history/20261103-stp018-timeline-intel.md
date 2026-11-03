# STOPA CHECKPOINT — latest

**Datum:** 2026-11-03
**Verze projektu:** 0.1.0, commit `cd5aa25` (STP-018) + předchozí `025c6c0` (vlna 3), `1b046ee` (vlna 2), `afc49a0` (vlna 1)
**Poslední dokončený úkol:** STP-018 (Timeline Intelligence 2.0 — oblast E, P2) — před ním STP-017 (ETAPA B vlna 3), STP-016 (vlna 2, `1b046ee`), STP-012c (`2549ce6`), STP-012b (`19a458d`), STP-012 (`e227929`), STP-013..015 (vlna 1, `afc49a0`)
**Aktuální fáze:** Oblast L (Report Engine) — příprava STP-020 (9 → 20 sekcí); ETAPA B vlny 1–3 hotové

## Aktuální stav
| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **20** |
| Čekající (BACKLOG/READY) | **5** (READY: STP-020; BACKLOG: 4) |
| Blokované | 0 |
| Full suite | **1073 passed, 1 skipped** (~13s) |
| Ruff | clean (`src/stopa tests scripts`) |
| Coverage matice | covered **51 / 232**, deterministická (SHA-256 diff ✓) |
| C3 registry | **24 parserů** (`build_registry()`) |

## STP-018 — co se provedlo
Tři analytické vrstvy nad materializovanou timeline:
1. **Rozpory `concurrent_activity`** — stejná normalizovaná entita ve dvou událostech v okně 60 s + odlišný typ/soubor → union-find tranzitivní uzavření, deterministické group ID (SHA-256).
2. **Duplikáty napříč zdroji `cross_source_duplicate`** — stejný obsah (typ+title) z ≥2 různých (source_id, rel_path), provenance všech výskytů zachována.
3. **Timestamp provenance** — `ts_origin` (source vs derived) + klasifikace přesnosti (`classify_precision`: second/millisecond/microsecond/file_metadata/unknown).

## Změněné soubory (STP-018)
- nový: `src/stopa/domain/timeline_intel.py` (čistá logika bez IO, ~301 ř.)
- `data/db.py`: SCHEMA_VERSION 11→**12**, nové sloupce `timeline_events` (`ts_origin`, `subject_values_json`, `contradiction_group_id`, `dup_group_id`), migrace `_migrate_timeline_intel()`, metody `set/clear_timeline_intel_groups()`
- `models.py`: `Artifact.ts_origin = "source"` default
- `pipeline.py`: insert subject_values+ts_origin, post-pass `run_timeline_intel(db, window_seconds=60)`
- `cli.py`: `add` post-pass po ingestu; `timeline --intel [--window N]`
- `web/app.py`: POST `/api/cases/{id}/timeline/intel?window_seconds=60`
- `domain/report.py`: podsekce Timeline Intelligence 2.0 (8.1) — rozpory + duplikáty s provenance
- `domain/i18n.py`, `presentation/case_report.py`, `domain/export.py` (TIMELINE_COLUMNS + timeline_records)
- nový test: `tests/test_timeline_intel.py` (**32 testů**)
- `tests/test_entity_resolution.py` + `tests/test_reproducibility.py`: SCHEMA_VERSION aserty → konstanta (robustní vůči bumpům)
- README.md, STOPA_CHANGELOG.md (+docs zrcadlo), `.stopa-dev/*`

## Jak pokračovat (STP-020)
1. Přečíst `src/stopa/domain/report.py` — SECTIONS list + build_html (9 sekcí)
2. Přečíst `src/stopa/presentation/case_report.py` — stavba ReportData z case DB
3. Přečíst `src/stopa/domain/i18n.py` — struktura klíčů cs/en
4. Audit existujících 9 sekcí → definovat rozsah 20 sekcí (titulní strana, metodika, nástroje+verze, omezení, závěr + další)
5. Implementace + testy na syntetickém případě; dokumentace; changelog update

## Co nesmí být změněno
- Existující 9 sekcí reportu (backward compat) — nové sekce se přidávají, staré se nemění
- C3 registry: `build_registry()` vynucuje 1:1 sync s pipeline + shodu verzí, jinak `RegistryError`
- Neodstraňovat existující testy kvůli zelenému výsledku; nepoužívat mockování místo kritické logiky
- Originální důkazní data zůstávají neměnná (report pracuje na case DB)

## Příkazy k ověření
```bash
cd /home/ai/Prace/projekty/stopa
.venv/bin/python -m pytest tests/test_timeline_intel.py -q   # 32 passed
.venv/bin/ruff check src/stopa tests scripts                 # All checks passed!
.venv/bin/python -m pytest -q                                # 1073 passed, 1 skipped
```
