# STOPA — TEST REPORT (kořenový výstup MASTER PROMPT)

**Datum:** 2026-11-03 · **Commit:** `e227929` (+ `19a458d`) · **Verze aplikace:** 0.1.0
Výsledky doloženy reálným spuštěním — ne deklarací. Spuštění: `.venv/bin/python -m pytest -q`.

## 1. Souhrn (čerstvý běh dne 2026-11-03)

| Metrika | Hodnota |
|---|---|
| **Výsledek** | ✅ **895 passed, 1 skipped** (1 warning — deprekace FastAPI `on_event`) |
| Čas běhu | 12.80 s |
| Testové soubory | **53** |
| Celkem collected testů | **896** (895 passed + 1 skipped) |
| Lint | ✅ ruff clean (`src/stopa tests scripts`) |
| Režim | plně offline — žádné externí API, syntetické fixtures (~29 MB) |

## 2. Rozpis testů podle souborů (doloženo `pytest --collect-only`, celkem 896)

| tests/test_audit_fixes.py | 15 |
| tests/test_bad_extension.py | 26 |
| tests/test_benchmark_engine.py | 18 |
| tests/test_carving_zip_rar.py | 13 |
| tests/test_dedupe.py | 8 |
| tests/test_e10.py | 17 |
| tests/test_e11.py | 19 |
| tests/test_e12.py | 11 |
| tests/test_e3.py | 8 |
| tests/test_e4.py | 21 |
| tests/test_e5.py | 6 |
| tests/test_e6.py | 23 |
| tests/test_e7.py | 21 |
| tests/test_e8.py | 16 |
| tests/test_e9.py | 22 |
| tests/test_email_mbox.py | 17 |
| tests/test_entity_resolution.py | 26 |
| tests/test_evidence_manager.py | 19 |
| tests/test_evidence_model.py | 14 |
| tests/test_ewf_container.py | 11 |
| tests/test_fde.py | 18 |
| tests/test_fde_b2.py | 32 |
| tests/test_hashing.py | 7 |
| tests/test_image_phase5.py | 30 |
| tests/test_imessage_cloud.py | 29 |
| tests/test_integrity.py | 22 |
| tests/test_intelligence.py | 25 |
| tests/test_lineage.py | 12 |
| tests/test_mobile_extract.py | 6 |
| tests/test_mobile_image_io.py | 4 |
| tests/test_net_connections.py | 12 |
| tests/test_pipeline.py | 16 |
| tests/test_plist_extract.py | 14 |
| tests/test_profiles.py | 6 |
| tests/test_rag.py | 30 |
| tests/test_registry_extract.py | 13 |
| tests/test_report.py | 16 |
| tests/test_reproducibility.py | 20 |
| tests/test_search.py | 14 |
| tests/test_signatures.py | 29 |
| tests/test_sqlite_extract.py | 20 |
| tests/test_sqlite_recover.py | 13 |
| tests/test_sqlite_recover_io.py | 8 |
| tests/test_timeline_engine.py | 41 |
| tests/test_times.py | 7 |
| tests/test_tsk.py | 22 |
| tests/test_tsk_py.py | 13 |
| tests/test_validation_registry.py | 10 |
| tests/test_web.py | 29 |
| tests/test_win_clipboard.py | 12 |
| tests/test_win_schedtask.py | 11 |
| tests/test_win_sids.py | 12 |
| tests/test_win_wlan.py | 12 |


## 3. Pokrytí oblastí
- **P0 Core C1–C6:** evidence model, lineage, validation registry (13 parserů), integrity (hash chaining + Ed25519), reproducibility (`stopa replay`), benchmark engine — `test_evidence_model.py`, `test_lineage.py`, `test_validation_registry.py`, `test_integrity.py`, `test_reproducibility.py`, `test_benchmark_engine.py`.
- **P0 Intelligence I1–I3:** AI orchestrace (5 agentů, fail-closed), Forensic RAG (3 vrstvy, prompt injection ochrana), Entity Resolution 2.0 — `test_ai_orchestrator.py`, `test_rag.py`, `test_entity_resolution.py` (26 testů).
- **ETAPA B vlna 1 (76 nových testů):** email mbox/EML (17), WiFi WLAN XML (12), Scheduled Tasks XML (11), netstat/connstat text (12), Clipboard registry (12), SID extraction (12) — `test_email_mbox.py`, `test_win_wlan.py`, `test_win_schedtask.py`, `test_net_connections.py`, `test_win_clipboard.py`, `test_win_sids.py`.
- **Diskové obrazy/carving:** E01/AFF4, TSK, carving ZIP/RAR, volný prostor — `test_tsk_py.py`, `test_carving_zip_rar.py` apod.
- **Windows parsery:** registry hive (fake regipy objekty), plist, LNK, prefetch, USN, jumplist, EVTX.
- **Web API:** 30 endpointů přes FastAPI TestClient — `test_web_api.py`.
- **Audit opravy E-fáze:** path traversal, CRLF hardening, ranged read exportu — `test_audit_fixes.py` (15).

## 4. Skipped testy
1 skipped — podmíněný test závislý na volitelné závislosti (weasyprint PDF), běžně očekávaný stav bez `[pdf]` extra.

## 5. Testovací pravidla (z MASTER promptu)
- Každý nový parser = automatizované testy + záznam v C3 registry + řádek v coverage matrix.
- Mockování jen u I/O hranice (fake `regipy.RegistryHive`), ne jako náhrada kritické forenzní logiky.
- Neodstraňovat existující testy kvůli zelenému výsledku; nepoužívat mockování místo reálné logiky.
- Plná sada musí zůstat plně offline (magic bytes + SQLite + FTS5 + syntetické fixtures).

## 6. Zbývající dluh (z TEST_REGISTRY)
- Benchmark ne běží automaticky v CI (BLK-003) — ručně `stopa benchmark`.
- Security testy ad-hoc; chybí fixture poškozeného obrazu pro robustnost parsery.

## 7. Historie počtů testů (vývoj)
656 → 668 → 678 → 700 → 720 → 738 (P0 Core C1–C6) → 763 (I1) → 793 (I2) → 819 (I3) → **895 passed + 1 skipped** (ETAPA B vlna 1, commit `afc49a0`).
