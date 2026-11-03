# STOPA — NEXT ACTION

## Aktuální fáze
ETAPA B — port AXIOM extraktorů (237 položek, `docs/re-axiom/axiom-artifact-extractors.json`)
— vlny 1–3 hotové; dále pokračování podle priority nebo přechod na oblast E.

## ID aktuálního úkolu
**STP-018** (READY — čeká na zahájení)

## Název úkolu
Timeline Intelligence 2.0: rozpory v timeline, duplikáty, přesnost timestampů (source vs derived)

## Proč se úkol provádí
Po vlnách 1–3 má STOPA **51/232** covered AXIOM typů a bohatou artifact bázii. Timeline je
hlavním analytickým výstupem — chybí ale inteligentní vrstva: detekce časových rozporů
(souběžné aktivity jednoho uživatele), duplicitních záznamů (stejný obsah z více zdrojů) a
rozlišení source vs derived timestampů (MACE, provenance). Oblast E, priorita P2.

## Co již bylo provedeno (vlna 3, commit vlna 3)
- 5 nových parserů: `kik_messenger.py` (SQLite dispatch chain — iOS `ZKIK*` / Android
  `users+messages`, aliasy sloupců, epoch s/ms), `mailru_agent.py` (chat log `|` formát +
  kontakty + skupiny), `bebo_chat.py` (text/JSON carving), `chatroulette.py` (text/JSON),
  `limewire_p2p.py` (LimeWire/Limerunner/Luckywire P2P shared files, JSON/pipe)
- Pokryto **9 AXIOM typů**: KikLocalUserExtractor, MailRuChat/Contact/GroupArtifact,
  BeboArtifact, ChatrouletteArtifact, Limewire/Limerunner/LuckywireArtifact
- Registrace: pipeline `NAME_BASED_EXTRACTORS` + `_name_based_match` (+4) a Kik do SQLite
  dispatch chainu; C3 registry **+4 záznamy → 24 parserů** (`build_registry()` ověřeno)
- **75 nových testů**, plná sada **1041 passed, 1 skipped**, ruff clean
- Coverage matice regenerována: covered **42 → 51** (+9 typů z 232), deterministická (SHA-256 diff ✓)

## Které soubory byly změněny (vlna 3)
`src/stopa/artifacts/{kik_messenger,mailru_agent,bebo_chat,chatroulette,limewire_p2p}.py`,
`src/stopa/pipeline.py`, `src/stopa/artifacts/sqlite_extract.py`,
`src/stopa/domain/validation_registry.py`,
`tests/test_{kik_messenger,mailru_agent,bebo_chat,chatroulette,limewire_p2p}.py`,
`scripts/build_axiom_coverage.py`, `STOPA_COVERAGE_MATRIX.csv`, README.md, STOPA_CHANGELOG.md

## Které soubory je potřeba prostudovat (před STP-018)
1. `src/stopa/domain/timeline*.py` — existující timeline engine (generování, řazení, dedupe)
2. `src/stopa/data/db.py` — tabulka artifactů + timestamp pole (`timestamp`, provenance?)
3. `docs/STOPA_TARGET_ARCHITECTURE.md` — oblast E (Timeline Intelligence)
4. `.stopa-dev/ROADMAP.md` — sekce E: definice rozsahu Timeline 2.0

## Co zbývá dokončit (STP-018)
1. Audit existující timeline logiky (co už umí, co chybí)
2. Detekce časových rozporů (souběžné aktivity jednoho subjektu — sliding window)
3. Deduplikace záznamů s identickým obsahem z více zdrojů (provenance zachovat)
4. Rozlišení source vs derived timestampů + přesnost (MACE u NTFS, atd.)
5. Testy na syntetických fixtures; dokumentace; coverage/changelog update

## Jaké testy spustit
```bash
.venv/bin/python -m pytest tests/test_timeline*.py -q   # timeline testy
.venv/bin/ruff check src/stopa tests scripts            # lint (musí být clean)
.venv/bin/python -m pytest -q                           # plná sada (baseline 1041 passed, 1 skipped)
```

## Jak poznat úspěšné dokončení
- Nové testy zelené + plná sada bez regresí (≥ baseline 1041)
- Ruff clean na `src/stopa tests scripts`
- Timeline report obsahuje sekce: rozpory, duplikáty, timestamp provenance
- Commit `feat(timeline): STP-018 — Timeline Intelligence 2.0 ...`

## Co nesmí být změněno
- Existující timeline výstupy (backward compat) — nové sekce se přidávají, staré se nemění
- C3 registry: `build_registry()` vynucuje 1:1 sync s pipeline + shodu verzí, jinak `RegistryError`
- Neodstraňovat existující testy kvůli zelenému výsledku; nepoužívat mockování místo kritické logiky
- Originální důkazní data zůstávají neměnná (parsery pracují na kopiích)

## Další úkol po STP-018
STP-019 — AI governance + PII redaktor (oblast H/M, P2) nebo pokračování ETAPA B vlny 4
dle priority v ROADMAP.md.
