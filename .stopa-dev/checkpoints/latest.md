# STOPA CHECKPOINT — latest

**Datum:** 2026-11-03
**Verze projektu:** 0.1.0, commit `7360bab` (STP-020) + předchozí `cd5aa25` (STP-018), `025c6c0` (vlna 3), `1b046ee` (vlna 2), `afc49a0` (vlna 1)
**Poslední dokončený úkol:** STP-020 (Report engine 9 → 20 sekcí — oblast L, P1) — před ním STP-018 (Timeline Intelligence 2.0), STP-017 (ETAPA B vlna 3), STP-016 (vlna 2), STP-012c (`2549ce6`), STP-012b (`19a458d`), STP-012 (`e227929`), STP-013..015 (vlna 1)
**Aktuální fáze:** Oblast L hotová — čeká na zahájení **STP-019** (AI governance + PII redaktor, oblast H/M, P2); ETAPA B vlny 1–3 hotové

## Aktuální stav
| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **21** |
| Čekající (BACKLOG/READY) | **4** (READY: STP-019; BACKLOG: 3) |
| Blokované | 0 |
| Full suite | **1087 passed, 1 skipped** (~13s) |
| Ruff | clean (`src/stopa tests scripts`) |
| Coverage matice | covered **51 / 232**, deterministická (SHA-256 diff ✓) |
| C3 registry | **24 parserů** (`build_registry()`) |

## STP-020 — co se provedlo
Rozšíření HTML/PDF reportu z 9 na **20 sekcí**:
1. **Titulní strana (cover)** — název případu, ID, znalec, datum vytvoření/generování, verze nástroje; nová CSS třída `.cover`.
2. **Sekce 10 — Metodika analýzy** — deterministicky z dat (zdroje/soubory/bajty, signatury, počet parserů C3, korelace, Timeline Intel okno).
3. **Sekce 11 — Nástroje a verze** — STOPA/Python/SQLite/platforma (`env_snapshot()` C5) + dostupnost TSK/EWF/cryptsetup (E12 diagnostics).
4. **Sekce 12 — Omezení analýzy** — RAM peak (BLK-001), confidence omezení, truncation limity.
5. **Sekce 13 — Závěr** — souhrn findings + počty rozporových/duplikátových skupin (STP-018).
6. **Sekce 14 — Provenience timestampů** — source vs derived (STP-018).
7. **Sekce 15 — Evidence lineage** (C2, počet kroků).
8. **Sekce 16 — Integrity Ed25519** (C4, veřejný klíč + kontrolní body).
9. **Sekce 17 — Rejstřík entit** (E4/I3).
10. **Sekce 18 — Příloha A: validace parserů** (C3 registry, deterministické pořadí).
11. **Sekce 19 — Příloha B: reprodukční prostředí** (C5 snapshot).
12. **Sekce 20 — Příloha C: rozložení důvěryhodnosti** (timeline + korelace).

Backward compat sekcí 1–9 zachována (testy asertují texty, ne čísla). ~60 nových i18n klíčů cs/en. Defenzivní naplnění z case DB (`case_report.py`).

## Změněné soubory (STP-020)
- `src/stopa/domain/report.py` — docstring, `ReportData` +4 pole (entities/lineage_steps/integrity_pub_key/integrity_checkpoints), CSS `.cover`, titulní strana, render sekcí 10–20
- `src/stopa/domain/i18n.py` — ~60 nových klíčů cs/en pro sekce 10–20
- `src/stopa/presentation/case_report.py` — defenzivní naplnění nová pole z case DB (entity, lineage, integrity checkpoints + veřejný klíč)
- `tests/test_report.py` — +fixture `rich_data`, třída `TestStp020Sections` (**14 testů**)
- README.md (řádek STP-020 + test count 1087), STOPA_CHANGELOG.md (+docs zrcadlo)
- `.stopa-dev/*` — NEXT_ACTION, PROJECT_STATE, TASKS, CHANGELOG, checkpoint

## Jak pokračovat (STP-019)
1. Přečíst `STOPA_AI_GOVERNANCE.md` (kořen) — existující governance dokumentace
2. Přečíst `src/stopa/intelligence/ai_orchestrator.py` — audit AI volání, citace
3. PII redaktor: detekce e-mail/telefon/JID/handle v LLM výstupu, volitelné maskování
4. Governance politika: kdy je AI povolená, auditovatelnost modelových volání (verze modelu)
5. Testy na syntetickém případě; dokumentace; changelog update

## Co nesmí být změněno
- Existující report sekce 1–20 (backward compat) — nové funkce se přidávají
- C3 registry: `build_registry()` vynucuje 1:1 sync s pipeline + shodu verzí, jinak `RegistryError`
- Neodstraňovat existující testy kvůli zelenému výsledku; nepoužívat mockování místo kritické logiky
- Originální důkazní data zůstávají neměnná (report pracuje na case DB)

## Příkazy k ověření
```bash
cd /home/ai/Prace/projekty/stopa
.venv/bin/python -m pytest tests/test_report.py -q   # 30 passed (16 původních + 14 nových)
.venv/bin/ruff check src/stopa tests scripts         # All checks passed!
.venv/bin/python -m pytest -q                        # 1087 passed, 1 skipped
```
