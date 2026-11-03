# STOPA CHECKPOINT — latest

**Datum:** 2026-11-03
**Verze projektu:** 0.1.0, commit `1b046ee` (vlna 2) + tento vlna 3 commit
**Poslední dokončený úkol:** STP-017 (ETAPA B vlna 3 — legacy mobile/messenger SQLite) — před ním STP-016 (vlna 2, `1b046ee`), STP-012c (kořenové výstupy MASTER promptu 9/9, `2549ce6`), STP-012b (`19a458d`), STP-012 (DEV OS bootstrap, `e227929`), STP-013..015 (vlna 1, `afc49a0`)
**Aktuální fáze:** ETAPA B — port AXIOM extraktorů (vlny 1–3 hotové)

## Aktuální stav
- **1041 passed + 1 skipped** (`.venv/bin/python -m pytest -q`), ruff clean (`src/stopa tests scripts`)
- Coverage AXIOM: **covered 51 / 232** unikátních typů (před vlnou 3: 42, před vlnou 2: 33)
- C3 Parser Validation Registry: **24 parserů**, sync s pipeline OK (`build_registry()`)
- DB schema: **v11**; artifact_type = volný TEXT bez CHECK

## Provedené změny (tento cyklus — vlna 3)
### Změněné soubory
- Nové parsery: `src/stopa/artifacts/{kik_messenger,mailru_agent,bebo_chat,chatroulette,limewire_p2p}.py`
- `pipeline.py` — importy + NAME_BASED_EXTRACTORS (+4) + `_name_based_match` (+4 větví)
- `sqlite_extract.py` — Kik branch do dispatch chainu (schéma-based, před mobile fallback)
- `domain/validation_registry.py` — +4 záznamy (celkem 24 parserů; Kik bez samostatného záznamu — SQLite chain vzor clipboard/SID)
- Nové testy: `tests/test_{kik_messenger,mailru_agent,bebo_chat,chatroulette,limewire_p2p}.py` (**75 testů**)
- `scripts/build_axiom_coverage.py` — COVERED +9 typů vlny 3 + `_covered_desc`
- `STOPA_COVERAGE_MATRIX.csv`, `docs/re-axiom/AXIOM_COVERAGE.{md,json}` — regenerovány (covered 51)
- `README.md` (řádek vlny 3 + test count 1041), `STOPA_CHANGELOG.md` (+ sekce vlna 3, docs zrcadlo sync)

### Nové funkce
- **Kik Messenger** — SQLite dispatch chain: iOS `kik.sqlite` (`ZKIKUSER`/`ZKIKMESSAGE`, prefix ZKIK) i Android aliasy (`users`+`messages`); defenzivní mapování sloupců přes aliasy, epoch s/ms; detekce schéma-based (iOS stačí `ZKIK*`, Android vyžaduje obě tabulky — proti false-positive na obecných DB)
- **Mail.ru Agent** — desktop IM lokální logy: chat log text `|` formát (typ zprávy/délka z hranatých závorek), kontakty, skupiny
- **Bebo Live Chat** — textový chat log (`[ts] user said:`) i JSON pole; konzervativní JSON detekce
- **Chatroulette video chat** — text/JSON carving (stejný vzor)
- **LimeWire/Limerunner/Luckywire P2P shared files** — JSON i pipe-delimited; detekce rodiny s prioritou Limerunner > Luckywire > LimeWire

### Opravy
- Kik: closure `g()` binduje `low` přes default argument (ruff B023); test fixture DB dostaly `row_factory = sqlite3.Row`
- Bebo/Chatroulette/LimeWire: konzervativní JSON detekce — textový log začíná na `[ts] user said:` a narážel na `startswith("[")`; JSON se uznává jen při jasném signálu (objekt, uzavřené pole s `{}`/`""`, kompaktní pole v 1. řádku)

## Testování
- **Provedeno:** plná sada 1041 passed, 1 skipped; ruff clean; determinismus matice SHA-256 ✓ (2 běhy identické)
- **Neprovedeno:** benchmark engine v CI (BLK-003), E2E na reálném E01

## Rozpracovaná práce
- Vlna 3: **hotová a commitnutá** (tento commit)
- DEV OS paměť: aktualizována (PROJECT_STATE, TASKS STP-017 DONE + STP-018 READY, NEXT_ACTION → STP-018, CHANGELOG)

## Další krok
- **ID úkolu:** STP-018 — Timeline Intelligence 2.0 (oblast E, P2)
- **Konkrétní instrukce:** rozpory v timeline (souběžné aktivity jednoho subjektu), duplikáty (stejný obsah z více zdrojů), přesnost timestampů (source vs derived). Nejdřív audit existující timeline logiky.
- **Relevantní soubory:** `src/stopa/domain/timeline*.py`, `src/stopa/data/db.py` (artifact tabulka + timestamp pole), `docs/STOPA_TARGET_ARCHITECTURE.md` (oblast E)
- **Akceptační kritéria:** plná sada bez regresí (≥ 1041); ruff clean; timeline report se novými sekcemi; commit.

## Rizika
- Timeline 2.0 musí zachovat backward compat existujících výstupů — nové sekce se přidávají, staré se nemění
- Source vs derived timestampy: u NTFS MACE je třeba explicitní provenance pole (ne odhad)
- Registry sekundární průchody (Clipboard/SID vzor) nemají nezávislé C3 položky
