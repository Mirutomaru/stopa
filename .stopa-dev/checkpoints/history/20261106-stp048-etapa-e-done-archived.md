# STOPA — CHECKPOINT (latest)

- **Datum:** 2026-11-06
- **HEAD:** `5965cb4` (STP-048 test commit; předchozí HEAD `13e9f77` = docs STP-047, feature STP-047 = `3fc2dac`)
- **Fáze:** Oblast M (Security) — **ETAPA E DOKONČENA ★★** (STP-046/047/048 = sandbox kontrakt + zapojení do pipeline + fix reálného hang bugu + E2E testy + dokumentace). Další oblast podle priority: H AI Copilot grounding.
- **Poslední dokončený úkol:** STP-048 — ETAPA E vlna 3: sandbox E2E testy + corrupt-file regression EVTX/LNK + dokumentace `docs/STOPA_SANDBOX.md`

## Klíčové rozhodnutí
1. **E2E kontrakt** (`tests/test_stp048_sandbox_e2e.py`, 4 testy): umělý hangující parser (`sb_stp048_hang.hang`, sleep 5 s) registrovaný pod signaturu `sqlite` → celá `process_source` doběhne za <20 s a v DB je **`parser_error` artifact s kategorií `timeout`** + audit log (bez sandboxu by pipeline visela navěky). Krátký timeout 1.5 s přes monkeypatch `SANDBOX_CONFIG` → deterministický test bez čekání 30 s; dočasný modul najde subprocess přes `PYTHONPATH`.
2. **Corrupt-file regression** (validní magic/signatura + garbage tělo): EVTX (`EVTX` + garbage) → parser defenzivně vrací `[]`; LNK (76 B header + IShellLink CLSID + garbage) → extrahuje co umí, nepadne. Plný `process_source` E2E na corrupt EVTX+LNK evidenci → rychle, žádný parser_error. SQLite regression pokryto STP-047 (carver fix).
3. **Dokumentace** (`docs/STOPA_SANDBOX.md`): kontrakt workeru (stdout=JSON / stderr / exit 0-1 + RLIMIT_CPU backstop), limity (timeout 30 s, payload 16 MiB), kategorie selhání s prioritou timeout>truncated>bad_payload>crash + struktura `parser_error` artifactu, fallback bez sandboxu (`STOPA_SANDBOX=0` / `SANDBOX_ENABLED`), jak přidat parser do sandboxu.

## Plán ETAPY E
- **Vlna 1 (STP-046):** ✅ `domain/sandbox.py` + worker modul — kontrakt, timeout, JSON marshalling (`91854d8`).
- **Vlna 2 (STP-047):** ✅ zapojení do pipeline + fix hang bugu v `sqlite_carver.recover_rows` (`3fc2dac`).
- **Vlna 3 (STP-048):** ✅ E2E testy (hangující parser přes celou `process_source`, corrupt EVTX/LNK) + `docs/STOPA_SANDBOX.md` → **ETAPA E dokončena ★★**.

## Stav
- Full suite: **1850 passed, 1 skipped** (+4 testy nad baseline 1846), ruff clean.
- Cílený běh `test_stp048_sandbox_e2e.py`: **4 passed in ~1.9 s**.
- C3 registry: **76 parserů**; covered **198 / 232 ★**.
- DEV OS sync: TASKS STP-048 DONE, PROJECT_STATE (ETAPA E DOKONČENA ★★, completed tasks **48**, nejbližší = H AI Copilot grounding), FEATURE_REGISTRY F-074, TEST_REGISTRY T-095 + total 1850, CHANGELOG ×3, ROADMAP ×2 (sekce M ✅ hotovo, vlna 3 ✅), NEXT_ACTION (další = H AI Copilot grounding s plánem vln).
