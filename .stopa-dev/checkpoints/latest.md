# STOPA CHECKPOINT — latest

**Datum:** 2026-11-03
**Verze projektu:** 0.1.0, commit `6d74ab3` (STP-019) + předchozí `7360bab` (STP-020), `cd5aa25` (STP-018), `025c6c0` (vlna 3), `1b046ee` (vlna 2), `afc49a0` (vlna 1)
**Poslední dokončený úkol:** STP-019 (AI governance + PII redaktor — oblast H/M, P2) — před ním STP-020 (Report engine 9→20 sekcí), STP-018 (Timeline Intelligence 2.0), STP-017 (ETAPA B vlna 3), STP-016 (vlna 2), STP-012c (`2549ce6`), STP-012b (`19a458d`), STP-012 (`e227929`), STP-013..015 (vlna 1)
**Aktuální fáze:** Oblast H/M hotová — čeká na zahájení **STP-021** (Performance: stream parsing velkých E01 + progress monitoring, oblast N/O, P2); ETAPA B vlny 1–3 hotové

## Aktuální stav
| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **22** |
| Čekající (BACKLOG/READY) | **3** (BACKLOG: STP-021, STP-022, STP-023) |
| Blokované | 0 |
| Full suite | **1110 passed, 1 skipped** (~14s) |
| Ruff | clean (`src/stopa tests scripts`) |
| Coverage matice | covered **51 / 232**, deterministická (SHA-256 diff ✓) |
| C3 registry | **24 parserů** (`build_registry()`) |

## STP-019 — co se provedlo
AI governance + PII redaktor pro důvěryhodnost AI vrstvy:
1. **`domain/pii_redaction.py` (nový)** — deterministický PII redaktor bez I/O: maskuje telefony (`+420****3456`), e-maily (`j***@example.com`), WhatsApp JID (`wa:+420****3456`) a platformní handle (`skype:j***`) ve všech prompt messages PŘED odesláním do LLM. Stavební kameny opakovány z `entities.py`/`entity_resolution.py`; priorita překryvu JID > e-mail > handle > telefon; vrací seznam detekcí (`PiiDetection`) pro audit.
2. **I1 orchestrace** — `build_prompt()`/`orchestrate()` + parametr `redact_pii: bool = True` (default ON, fail-safe); auditní SHA-256 nad redigovaným textem (odpovídá tomu, co LLM uviděl).
3. **E11 asistent** — helper `_maybe_redact()`, všechny tři prompt buildery (`nl_search`/`summary`/`explain`) maskují PII podle `redact_pii`.
4. **Audit E11 modelových volání** — dříve auditoval jen I1; teď zapisují `ai_query` záznam (model name + SHA-256 promptu + citace, agent `e11:<režim>`) i všechny tři režimy E11.
5. **Settings toggle** `ai_redact_pii` (default ON) — GET/PUT `/api/settings`, CLI `_load_ai_redact_pii()` čte settings.json z db_dir; `cmd_analyze` předává `redact_pii` do orchestrace i auditního hashu.
6. **Governance doc** — `STOPA_AI_GOVERNANCE.md`: §7 audit E11, §8 endpoint, §9 PII ✅ mitigováno.

## Změněné soubory (STP-019)
- `src/stopa/domain/pii_redaction.py` (nový) — deterministický PII redaktor bez I/O
- `src/stopa/intelligence/ai_orchestrator.py` — `build_prompt()`/`orchestrate()` + `redact_pii`, auditní hash nad redigovaným textem
- `src/stopa/domain/ai_assistant.py` — `_maybe_redact()`, tři E11 buildery maskují PII
- `src/stopa/web/app.py` — `SettingsIn.ai_redact_pii`, GET/PUT settings, I1 toggle + auditní hash, audit E11 (3 režimy)
- `src/stopa/cli.py` — `_load_ai_redact_pii()`, `cmd_analyze` předává `redact_pii`
- `tests/test_pii_redaction.py` (nový) — **23 testů**
- `STOPA_AI_GOVERNANCE.md`, README.md, STOPA_CHANGELOG.md (+docs zrcadlo), STOPA_ROADMAP.md
- `.stopa-dev/*` — NEXT_ACTION, PROJECT_STATE, TASKS, CHANGELOG, FEATURE_REGISTRY (F-044), TEST_REGISTRY (T-072), BLOCKERS, checkpoint

## Jak pokračovat (STP-021)
1. Přečíst `src/stopa/pipeline.py` — aktuální ingest tok E01 (kde se čtou soubory do paměti)
2. Přečíst `src/stopa/web/app.py` — Processing Monitor endpointy + progress stavy
3. Stream parsing velkých E01 souborů (snížení RAM peaku)
4. Web Processing Monitor (viditelný progress ingestu/analýzy)
5. Testy na syntetickém případě; dokumentace; changelog update

## Co nesmí být změněno
- Existující report sekce 1–20 (backward compat) — nové funkce se přidávají
- C3 registry: `build_registry()` vynucuje 1:1 sync s pipeline + shodu verzí, jinak `RegistryError`
- Neodstraňovat existující testy kvůli zelenému výsledku; nepoužívat mockování místo kritické logiky
- Originální důkazní data zůstávají neměnná

## Příkazy k ověření
```bash
cd /home/ai/Prace/projekty/stopa
.venv/bin/python -m pytest tests/test_pii_redaction.py -q   # 23 passed
.venv/bin/ruff check src/stopa tests scripts                # All checks passed!
.venv/bin/python -m pytest -q                               # 1110 passed, 1 skipped
```
