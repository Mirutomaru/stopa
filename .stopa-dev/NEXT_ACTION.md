# STOPA — NEXT ACTION

## Aktuální stav (2026-11-06)
**ETAPA E DOKONČENA ★★** — STP-048 (vlna 3: sandbox E2E testy + corrupt-file regression EVTX/LNK + dokumentace `docs/STOPA_SANDBOX.md`) hotový. Oblast M (Security) uzavřena.

## Hotové
- **STP-048:** nový `tests/test_stp048_sandbox_e2e.py` (**4 E2E testy** přes reálný subprocess): umělý hangující parser (`sb_stp048_hang.hang`, sleep 5 s) registrovaný pod signaturu `sqlite` → celá `process_source` doběhne za <20 s a v DB je **`parser_error` artifact s kategorií `timeout`** + audit log (bez sandboxu by visela navěky); corrupt EVTX (validní magic + garbage tělo) a corrupt LNK (validní signatura + garbage tělo) → nepadají pipeline; plný `process_source` E2E na corrupt EVTX+LNK evidenci → rychle, žádný parser_error. Nová dokumentace **`docs/STOPA_SANDBOX.md`** — kontrakt workeru (stdout=JSON / stderr / exit 0-1 + RLIMIT_CPU backstop), limity (30 s / 16 MiB), kategorie selhání (timeout>truncated>bad_payload>crash + struktura `parser_error`), fallback (`STOPA_SANDBOX=0`), jak přidat parser do sandboxu. Full suite **1850 passed, 1 skipped**, ruff clean.
- **STP-047:** `_extract_artifacts_for` (pipeline.py) volá všechny extraktory přes nový `_run_extractor()` → `run_extractor_sandboxed()` (subprocess izolace s timeoutem); selhání parseru → `parser_error` artifact s kategorií z `SandboxResult`. Fallback bez sandboxu = přímé volání (`STOPA_SANDBOX=0`). **Fix reálného hang bugu** v `sqlite_carver.recover_rows` — validace `db_size_pages` proti velikosti souboru. 12 nových testů, full suite 1846 passed.
- **STP-046:** `src/stopa/domain/sandbox.py` (SandboxConfig, SandboxResult, validate_artifact_payload, build_worker_command, failure_category s prioritou timeout>truncated>bad_payload>crash, sandbox_available, run_extractor_sandboxed) + `src/stopa/sandbox_worker.py`. 21 testů. Feature commit `91854d8`.

## Další krok — oblast H: AI Copilot grounding
**Detekce rozporů mezi odpovědí LLM a artifacty v DB.** Citace existují (E11: `extract_citations()` validuje ID proti DB), chybí ověření, že tvrdění v textu odpovídají datům (např. datum/typ/hodnota uváděná v odpovědi vs. reálné details_json citovaného artifactu). Plán vln:
1. **Vlna 1:** čistý domain modul `domain/ai_grounding.py` — extrakce tvrdění z odpovědi (datumy, typy souborů, entity) + porovnání proti details_json citovaných artifactů → kategorie rozporu (mismatch_date/mismatch_type/unverified_claim), deterministické.
2. **Vlna 2:** zapojení do web endpointu `POST /api/cases/{id}/ai/query` — grounding report v odpovědi + GUI štítky u citací (✓ ověřeno / ⚠ rozpor).
3. **Vlna 3:** testy (mock LM Studio přes httpx.MockTransport) + dokumentace → ETAPA H dokončena ★★.

## Poté — další oblasti (pořadí podle priority)
I+O Validation Center UI → G File Intelligence → J Case Management 2.0 → K Export Engine (Plaso) → Q Interoperability (UCO/STIX).
