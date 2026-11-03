# STOPA — NEXT ACTION

## Aktuální fáze
Oblast L (Report Engine) — **STP-020 hotový** (report 9 → 20 sekcí); ETAPA B vlny 1–3 hotové,
STP-018 Timeline Intelligence 2.0 hotový.

## ID aktuálního úkolu
**STP-019** (READY — čeká na zahájení)

## Název úkolu
AI governance + PII redaktor (oblast H/M, priorita P2)

## Proč se úkol provádí
AI vrstva (I1–I3) je hotová; chybí governance: politika použití AI v forenzním kontextu,
PII redaktor pro citace/odpovědi LLM a auditovatelnost modelových volání. Oblast H/M, priorita **P2**.

## Co již bylo provedeno (STP-020)
- `domain/report.py` — rozšíření HTML/PDF reportu z 9 na **20 sekcí**: titulní strana (cover),
  10 Metodika analýzy, 11 Nástroje a verze, 12 Omezení analýzy, 13 Závěr, 14 Provenience
  timestampů, 15 Evidence lineage, 16 Integrity Ed25519, 17 Rejstřík entit,
  18 Příloha A (validace parserů C3), 19 Příloha B (reprodukční prostředí C5),
  20 Příloha C (rozložení důvěryhodnosti). Backward compat sekcí 1–9 zachována.
- `domain/i18n.py` — ~60 nových klíčů cs/en pro sekce 10–20.
- `presentation/case_report.py` — defenzivní naplnění nová pole `ReportData` z case DB
  (entity, lineage, integrity checkpoints + veřejný klíč).
- **14 nových testů** (`tests/test_report.py`, třída `TestStp020Sections`); full suite
  **1087 passed, 1 skipped**, ruff clean.

## Které soubory byly změněny (STP-020)
`src/stopa/domain/report.py`, `src/stopa/domain/i18n.py`,
`src/stopa/presentation/case_report.py`, `tests/test_report.py`, README.md,
STOPA_CHANGELOG.md (+ docs zrcadlo).

## Které soubory je potřeba prostudovat (před STP-019)
1. `docs/STOPA_AI_GOVERNANCE.md` — existující governance dokumentace (pokud je)
2. `src/stopa/intelligence/ai_orchestrator.py` — audit AI volání, citace
3. `src/stopa/domain/i18n.py` + report sekce 17 (rejstřík entit) — kde PII uniká do výstupů
4. `.stopa-dev/TASKS.md` — STP-019 definice rozsahu

## Co zbývá dokončit (STP-019)
1. Audit existující AI governance + PII toku v citacích/odpovědích LLM
2. PII redaktor: detekce e-mail/telefon/JID/handle v LLM výstupu, volitelné maskování
3. Governance politika: kdy je AI povolená, auditovatelnost modelových volání (verze modelu)
4. Testy na syntetickém případě; dokumentace; changelog update

## Jaké testy spustit
```bash
.venv/bin/python -m pytest tests/test_report*.py -q   # report testy
.venv/bin/ruff check src/stopa tests scripts          # lint (musí být clean)
.venv/bin/python -m pytest -q                         # plná sada (baseline 1087 passed, 1 skipped)
```

## Jak poznat úspěšné dokončení
- PII redaktor maskuje e-mail/telefon/JID/handle v LLM výstupu (volitelně)
- Governance politika dokumentovaná + auditovatelná (verze modelu v audit logu)
- Ruff clean na `src/stopa tests scripts`
- Plná sada bez regresí (≥ baseline 1087 passed, 1 skipped)
- Commit `feat(ai): STP-019 — AI governance + PII redaktor ...`

## Co nesmí být změněno
- Existující report sekce 1–20 (backward compat) — nové funkce se přidávají
- C3 registry: `build_registry()` vynucuje 1:1 sync s pipeline + shodu verzí, jinak `RegistryError`
- Neodstraňovat existující testy kvůli zelenému výsledku; nepoužívat mockování místo kritické logiky
- Originální důkazní data zůstávají neměnná

## Další úkol po STP-019
STP-021/022 (P2) nebo STP-023 (P3) dle priority.
