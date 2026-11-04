# STOPA — Checkpoint (latest)

**Datum:** 2026-11-04
**Verze aplikace:** 0.1.0 (`pyproject.toml`)
**Commit:** ```5e47850``` (předchozí: `5d7e95b` STP-028 docs, `9ffde5b` STP-028 feature, `0f8a2e8`, `b786064`, `069e839`, `cd932e1`)

## Co se stalo
**STP-029 — ETAPA B vlna 7: Chrome Bookmarks/History/Autofill + Contacts + Skype WR (5 parserů / 12 AXIOM typů)** (oblast D, P0) hotový.
Pět nových extraktorů v čistém Pythonu nad stávajícím pipeline dispatchem:
- **Chrome Bookmarks** (`google_chrome_bookmarks.py`) — Bookmarks JSON: rekurzivní walk `roots`,
  folder path z hierarchie, `date_added` µs od 1601 → unix s; name-based detekce; artifact type `browser_bookmark`.
- **Chrome History WR** (`google_chrome_history_wr.py`) — warrant return JSON: `visit_time` µs od 1601,
  dict wrapper i pole; name-based detekce; artifact type `browser_visit`.
- **Google Contacts WR** (`google_contacts_wr.py`) — Takeout/warrant JSON: `name`/`givenName`/`familyName`,
  `emails[]`/`phoneNumbers[]`; People API fallback `names[].displayName`; name-based detekce; artifact type `contact`.
- **Chrome Autofill/Contact Info** (`google_chrome_autofill.py`) — Autofill/ContactInfo JSON: name/email/adresa,
  prázdný záznam vynechán; name-based detekce s klíčovým slovem `contactinfo`; artifact type `autofill_entry`.
- **Skype Warrant Return** (`skype_warrant_return.py`) — 4 subtypy s auto-detekcí (account details, chat history
  records, connection history, contacts); `composetime` ISO 8601 i epoch ms; name-based detekce.

Pipeline dispatch: 5 parserů do `NAME_BASED_EXTRACTORS` + `_name_based_match()`
(specifické vlna-7 detekce PŘED obecnými Google/Skype). C3 registry (`domain/validation_registry.py`): nové záznamy
`chrome_bookmarks`/`chrome_history_wr`/`contacts_wr`/`chrome_autofill`/`skype_warrant_return` → **41 verzovaných parserů**
(`build_registry()` OK; předtím 36).

## Změněné soubory
- Nové parsery: `src/stopa/artifacts/{google_chrome_bookmarks,google_chrome_history_wr,google_contacts_wr,google_chrome_autofill,skype_warrant_return}.py`.
- `src/stopa/pipeline.py` — importy 5 parserů abecedně, `NAME_BASED_EXTRACTORS` + `_name_based_match()` rozšířeny.
- `src/stopa/domain/validation_registry.py` — C3 registry rozšířeno (41 parserů).
- `scripts/build_axiom_coverage.py` — COVERED + _covered_desc +12 AXIOM typů.
- Regenerováno: `STOPA_COVERAGE_MATRIX.csv`, `docs/re-axiom/AXIOM_COVERAGE.{md,json}`.
- Nový test: `tests/test_w7_parsers.py` (**39 testů** — syntetické offline fixtures).
- Oprava: `tests/test_w6_parsers.py` (hardcodovaný `len(reg)==36` → robustní přítomnost + verze).
- `STOPA_CHANGELOG.md` (+docs zrcadlo), `STOPA_ROADMAP.md` (D covered 84/232, 41 parser modulů).

## Testy
- Nové: `.venv/bin/python -m pytest tests/test_w7_parsers.py -q` → **39 passed**.
- Full suite: `.venv/bin/python -m pytest -q` → **1318 passed, 1 skipped** (baseline 1279 + 39).
- Ruff: `All checks passed!` pro `src/stopa tests scripts`.

## Registry
- Feature: **F-058** ETAPA B vlna 7 — Chrome Bookmarks/History/Autofill + Contacts + Skype WR (5 parserů / 12 AXIOM typů).
- Testy: **T-079** `tests/test_w7_parsers.py` (39).
- Celkový stav TEST_REGISTRY: **1318 testů: 1317 PASS + 1 skipped**.

## Coverage matice
covered **72 → 84 / 232** unikátních typů — flip 12 AXIOM typů NOT_SUPPORTED → SUPPORTED (cloud-export):
ChromeBookmarksArtifact, CloudChromeBookmarksArtifact, ChromeHistoryArtifact, ContactsWarrantReturnArtifact,
CloudGoogleContactsArtifact, AutofillWarrantReturnArtifact, ContactInfoWarrantReturnArtifact, CloudAutofillArtifact,
SkypeAccountDetailsArtifact, SkypeChatHistoryRecordsArtifact, SkypeConnectionHistoryArtifact, SkypeContactsArtifact.
NOT_SUPPORTED 126 → 114; DEPRECATED 34 (bez změny); **portable-local NOT_SUPPORTED = 0 ★** (bez změny).

## Další krok
**ETAPA B vlna 8 — Artifact Engine: cloud-export typy (zbývá 99)** (oblast D, P0) —
Google Drive/Docs rodina, Chrome prefs/extensions warrant return, Google Voice 2025/2026; detail v `NEXT_ACTION.md`.
