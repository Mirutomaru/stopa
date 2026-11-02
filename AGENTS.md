# STOPA — AGENTS.md (startup protokol pro vývojové agenty)

## Krok 1: Načti projektovou paměť (v tomto pořadí)
1. `.stopa-dev/PROJECT_STATE.md` — hlavní přehled projektu
2. `.stopa-dev/NEXT_ACTION.md` — **nejdůležitější soubor**: kde přesně pokračovat
3. `.stopa-dev/ROADMAP.md` — dlouhodobá mapa (A–Q)
4. `.stopa-dev/TASKS.md` — registr úkolů (STP-NNN, stavy)

## Krok 2: Ověř skutečný stav (nikdy nepředpokládej)
```bash
cd /home/ai/Prace/projekty/stopa
git log --oneline -3                      # HEAD odpovídá PROJECT_STATE?
git status --short                        # nezdokumentované změny?
.venv/bin/python -m pytest -q 2>&1 | tail -2   # plná sada (spolehlivý způsob — NE holé .venv/bin/pytest)
.venv/bin/ruff check src/stopa tests scripts
```

## Krok 3: Vypiš přehled a pokračuj podle NEXT_ACTION.md
```
STOPA DEVELOPMENT STATUS
Aktuální fáze: ...
Poslední dokončený úkol: ...
Aktuální úkol: ...
Stav: ...
Relevantní moduly: ...
Poslední testy: ...
Blokery: ...
Následující krok: ...
```

## Klíčová pravidla (shrnutí DEV OS MASTER PROMPT)
- **Jeden úkol → implementace → test → dokumentace → checkpoint → další úkol.**
- Nezačínej přepisovat od začátku; zachovej funkční části a Clean Architecture.
- Každé tvrzení podlož kódem/testem/reprodukcí — nevymýšlej existující funkce.
- IMPLEMENTED ≠ TESTED ≠ VERIFIED (FEATURE_REGISTRY.md).
- Nový parser = parser + detekce (signatura/NAME_BASED_EXTRACTORS) + registrace pipeline **i** C3 registry (`PARSER_VALIDATIONS`) + testy + docs + coverage matice update.
- `artifact_type` je volný TEXT bez CHECK → nové typy projdou bez DB migrace.
- Registry sekundární průchody (Amcache/ShimCache/Clipboard/SID) sdílejí regf magic v `_extract_registry_all` — nemají nezávislé C3 položky.
- Test suite je plně offline; před externími API voláními se zeptat uživatele.
- Po dokončení úkolu: aktualizuj TASKS/PROJECT_STATE/NEXT_ACTION/FEATURE_REGISTRY/TEST_REGISTRY/CHANGELOG + checkpoint do `.stopa-dev/checkpoints/latest.md` (starý archivuj do `history/`).

## Spolehlivé příkazy
| Účel | Příkaz |
|---|---|
| Plná test suite | `.venv/bin/python -m pytest -q` (NE holé `.venv/bin/pytest`) |
| Lint | `.venv/bin/ruff check src/stopa tests scripts` |
| Coverage matice | `.venv/bin/python scripts/build_axiom_coverage.py` (deterministická) |
| C3 registry sync | `.venv/bin/python -c "from stopa.domain.validation_registry import build_registry; print(len(build_registry()))"` |
