# STOPA — VALIDATION REPORT (kořenový výstup MASTER PROMPT)

**Datum:** 2026-11-03 · **Commit:** `e227929` · **Verze aplikace:** 0.1.0
Základ: `docs/STOPA_VALIDATION_STRATEGY.md` (ETAPA C) + živý stav C3 Parser Validation Registry (`build_registry()`).

## 1. Principy validace
1. **Unit test ≠ forenzní validace.** Parser prochází unit testy = funkční; je *forenzně validovaný* až po ověření na referenčním datasetu s očekávanými výsledky (NIST/SWGDE-style).
2. **Každý parser má identitu** — ID, verzi, formáty, omezení, referenční dataset, očekávané výsledky. Bez identity = `NEEDS VALIDATION`.
3. **Determinismus** — benchmarky a regresní sada běží na fixních datech; výsledek je reprodukovatelný (SHA-256 diff).

## 2. Parser Validation Registry (C3) — živý stav
`build_registry()` ověřeno dne 2026-11-03: **13 registrovaných parserů**, 1:1 synchronizace s pipeline (`ARTIFACT_EXTRACTORS` + `NAME_BASED_EXTRACTORS`), shoda verzí; při driftu → `RegistryError`.

| parser_id | test soubor | formáty (počet) | omezení (počet) |
|---|---|---|---|
| email_mbox | tests/test_email_mbox.py | 2 | 3 |
| evtx | tests/test_e7.py | 2 | 62 |
| icloud_messages | tests/test_imessage_cloud.py | 1 | 1 |
| lnk | tests/test_e6.py | — | 1 |
| net_connections | tests/test_net_connections.py | 2 | 3 |
| plist | tests/test_plist_extract.py | — | 1 |
| registry_hive | tests/test_registry_extract.py | — | 2 |
| sqlite | tests/test_sqlite_extract.py | 4 | 2 |
| wifi_wlan | tests/test_win_wlan.py | 1 | 2 |
| win_jumplist | tests/test_e6.py | 1 | 2 |
| win_prefetch | tests/test_e6.py | — | 2 |
| win_schedtask | tests/test_win_schedtask.py | 1 | 2 |
| win_usn | tests/test_e7.py | 1 | 1 |

*(— = formáty definovány jako textový popis, ne počítelná množina.)*

**Sekundární registry průchody** (sdílená `regf` magic, bez nezávislého C3 záznamu): Amcache, ShimCache, Clipboard (`win_clipboard.py`), SID extraction (`win_sids.py`) — testovány v `test_win_clipboard.py` / `test_win_sids.py`.

## 3. Kritéria validace parseru
Parser je **forenzně validovaný** pokud:
1. Má záznam v Validation Registry (ID, verze, formáty, omezení) — ✅ všech 13
2. Prochází pozitivními testy na referenčním datasetu s očekávanými výsledky
3. Prochází negativními testy (poškozený soubor → `[]`, ne výjimka)
4. Má edge-case testy (prázdný soubor, maximální velikost, neplatné encodingy)
5. Má regresní test (změna parseru = změna očekávaného výsledku je explicitně zaznamenána)

Bez bodů 2–3 = `NEEDS VALIDATION` (funkční, ale netvrzeno jako forenzně validovaný).

## 4. Referenční datasety
- Malé syntetické soubory pro každý parser (commitované do repo), každý s `README.md` + `expected.json`.
- Negativní varianty: poškozené/krátké soubory → očekává se `[]` bez výjimky.

## 5. Benchmark Engine (C6)
`data/benchmark_engine.py`: deterministické workloads na syntetických datech; metрики čas + špičková RAM (tracemalloc); historie do `meta` (`benchmark_history`, max 50 záznamů); **regresní práh >20 % zpomalení = warning**. CLI: `stopa benchmark [case] [--suite core|parsers|all]`.

## 6. Evidence Validation Reports
- `stopa validate <case_id> [--json]` → per-artifact: parser ID+verze, validation status, confidence, provenance; souhrn coverage (kolik artefaktů je z validovaných parserů).
- Deterministický JSON export + HTML přes report engine.

## 7. Souhrn stavu validace
| Metrika | Hodnota | Důkaz |
|---|---|---|
| Registrované parsery (C3) | **13** | živý `build_registry()` |
| Testy registry vs pipeline | ✅ sync + verze | `tests/test_validation_registry.py` (10 testů) |
| Plná testová sada | **895 passed, 1 skipped** | `.venv/bin/python -m pytest -q` |
| Lint | ruff clean | `ruff check src/stopa tests scripts` |
| Coverage AXIOM | covered **33 / 232** typů | `STOPA_COVERAGE_MATRIX.csv` (deterministická) |

## 8. Zbývající dluh
- Benchmark ne běží automaticky v CI (BLK-003) — ručně `stopa benchmark`.
- Chybí fixture poškozeného obrazu pro robustnost parsery (negativní testy).
- UI Validation Center (P2 workspace).

## 9. Reference zdroje
NIST CFToolVal metodika · SWGDE best practices · Microsoft docs (LNK/Prefetch/EVTX/USN) · SQLite file format · plist spec · C2PA spec · Volatility 3 docs.
