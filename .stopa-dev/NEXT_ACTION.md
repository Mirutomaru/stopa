# STOPA — NEXT ACTION

## Aktuální fáze
Oblast H/M (AI governance) — **STP-019 hotový** (PII redaktor + audit modelových volání);
ETAPA B vlny 1–3 hotové, STP-018 Timeline Intelligence 2.0 hotový, STP-020 report engine hotový.

## ID aktuálního úkolu
**STP-021** (READY — čeká na zahájení)

## Název úkolu
Performance: stream parsing velkých E01 + progress monitoring (oblast N/O, priorita P2)

## Proč se úkol provádí
Velké E01 extrakty (GB řádově) zatěžují RAM peak; chybí stream parsing a viditelný
progress v web UI. Oblast N/O, priorita **P2**.

## Co již bylo provedeno (STP-019)
- `domain/pii_redaction.py` — nový deterministický PII redaktor (bez I/O): maskuje telefony,
  e-maily, WhatsApp JID a platformní handle ve všech LLM prompt messages PŘED inference;
  stavební kameny opakovány z `entities.py`/`entity_resolution.py`; priorita překryvu
  JID > e-mail > handle > telefon; vrací seznam detekcí (`PiiDetection`) pro audit.
- `intelligence/ai_orchestrator.py` — `build_prompt()`/`orchestrate()` + parametr
  `redact_pii: bool = True` (default ON, fail-safe); auditní SHA-256 nad redigovaným textem.
- `domain/ai_assistant.py` — všechny tři E11 prompt buildery maskují PII (`_maybe_redact`).
- `web/app.py` — **audit E11 modelových volání** (dříve jen I1): `_ai_nl_search/_ai_summary/
  _ai_explain` zapisují `ai_query` záznam (model name + SHA-256 promptu + citace, agent
  `e11:<režim>`); settings toggle `ai_redact_pii` (GET/PUT `/api/settings`, default ON).
- `cli.py` — `_load_ai_redact_pii()` čte `settings.json` z db_dir; `cmd_analyze` předává
  `redact_pii` do orchestrace i auditního hashu.
- **23 nových testů** (`tests/test_pii_redaction.py`); full suite **1110 passed, 1 skipped**, ruff clean.

## Které soubory byly změněny (STP-019)
`src/stopa/domain/pii_redaction.py` (nový), `src/stopa/intelligence/ai_orchestrator.py`,
`src/stopa/domain/ai_assistant.py`, `src/stopa/web/app.py`, `src/stopa/cli.py`,
`tests/test_pii_redaction.py` (nový), `STOPA_AI_GOVERNANCE.md`, README.md, STOPA_CHANGELOG.md.

## Které soubory je potřeba prostudovat (před STP-021)
1. `src/stopa/pipeline.py` — aktuální ingest tok E01 (kde se čtou soubory do paměti)
2. `src/stopa/web/app.py` — Processing Monitor endpointy (pokud existují) + progress stavy
3. `.stopa-dev/TASKS.md` — STP-021 definice rozsahu

## Co zbývá dokončit (STP-021)
1. Stream parsing velkých E01 souborů (snížení RAM peaku)
2. Web Processing Monitor (viditelný progress ingestu/analýzy)
3. Testy na syntetickém případě; dokumentace; changelog update

## Jaké testy spustit
```bash
.venv/bin/python -m pytest tests/test_pii_redaction.py -q   # PII redaktor (STP-019)
.venv/bin/ruff check src/stopa tests scripts                # lint (musí být clean)
.venv/bin/python -m pytest -q                               # plná sada (baseline 1110 passed, 1 skipped)
```

## Jak poznat úspěšné dokončení
- Stream parsing sníží RAM peak na velkých E01 extraktech
- Web UI zobrazuje progress ingestu/analýzy
- Ruff clean na `src/stopa tests scripts`
- Plná sada bez regresí (≥ baseline 1110 passed, 1 skipped)
- Commit `feat(perf): STP-021 — stream parsing + progress monitoring ...`

## Co nesmí být změněno
- Existující report sekce 1–20 (backward compat) — nové funkce se přidávají
- C3 registry: `build_registry()` vynucuje 1:1 sync s pipeline + shodu verzí, jinak `RegistryError`
- Neodstraňovat existující testy kvůli zelenému výsledku; nepoužívat mockování místo kritické logiky
- Originální důkazní data zůstávají neměnná

## Další úkol po STP-021
STP-022 (Security: SHA-512 + RBAC minimální + pip-audit CI, P2) nebo STP-023 (Export JSONL/XML/STIX, P3).
