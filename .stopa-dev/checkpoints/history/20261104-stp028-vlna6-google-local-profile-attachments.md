# STOPA — Checkpoint (latest)

**Datum:** 2026-11-04
**Verze aplikace:** 0.1.0 (`pyproject.toml`)
**Commit:** ```9ffde5b``` (předchozí: `0f8a2e8` STP-027 docs, `b786064` STP-027 feature, `069e839`, `cd932e1`, `985ada6`, `210c370`, `5c08679`, `9707cd8`)

## Co se stalo
**STP-028 — ETAPA B vlna 6: Google local profile/takeout + přílohy (4 parsery / 4 AXIOM typy)** (oblast D, P0) hotový.
Čtyři nové extraktory v čistém Pythonu nad stávajícím pipeline dispatchem:
- **Google Photos** (`google_photos.py`) — Photos Takeout/warrant JSON (pole objektů): `photoTakenTime`
  ISO 8601 i epoch ms → unix s, `geoData` E7 souřadnice → stupně, description/mediaItemType; name-based detekce;
  artifact type `google_photo`.
- **Gmail warrant return** (`google_mail_info.py`) — pole zpráv: `threadId`, `internalDate` µs od Unix epochy
  i epoch s, from/to/cc jako objekt `{"emailAddress": …}` i plain string; name-based detekce; artifact type `google_mail_info`.
- **Google Bar / Chrome omnibox** (`google_bar.py`) — Chrome/Edge History DB tabulka `search_terms`:
  `term`, `time_last_used` (Chrome µs), weight/source; case-insensitive dedup; bonus hook v `_extract_chrome_history`;
  artifact type `browser_search`.
- **AttachmentExtractor** (`attachment_extractor.py`) — MIME/RFC822 přílohy: multipart walk, filename z
  Content-Disposition, content-type, velikost z Content-Length bez dekodování payloadu; bonus hook v `email_mbox`
  (každá příloha → samostatný artifact); artifact type `email_attachment`.

Pipeline dispatch: photos + mail_info do `NAME_BASED_EXTRACTORS` + `_name_based_match()`
(specifické detekce PŘED obecnějšími Google detekcemi), GoogleBar bonus v `_extract_chrome_history`,
AttachmentExtractor bonus v `email_mbox`. C3 registry (`domain/validation_registry.py`): nové záznamy
`google_photos`/`google_mail_info`/`attachment_extractor` + sdílené `sqlite` (GoogleBar) a `email_mbox`
(AttachmentExtractor) rozšířeny → **36 verzovaných parserů** (`build_registry()` OK; předtím 34).

## Změněné soubory
- Nové parsery: `src/stopa/artifacts/{google_photos,google_mail_info,google_bar,attachment_extractor}.py`.
- `src/stopa/pipeline.py` — importy 2 name-based parserů abecedně, `NAME_BASED_EXTRACTORS` + `_name_based_match()` rozšířeny.
- `src/stopa/artifacts/sqlite_extract.py` — bonus hook GoogleBar v `_extract_chrome_history`.
- `src/stopa/artifacts/email_mbox.py` — bonus hook AttachmentExtractor (přílohy → `email_attachment`).
- `src/stopa/domain/validation_registry.py` — C3 registry rozšířeno (36 parserů).
- `scripts/build_axiom_coverage.py` — COVERED + _covered_desc +4 AXIOM typy.
- Regenerováno: `STOPA_COVERAGE_MATRIX.csv`, `docs/re-axiom/AXIOM_COVERAGE.{md,json}`.
- Nový test: `tests/test_w6_parsers.py` (**37 testů** — syntetické offline fixtures).
- `STOPA_CHANGELOG.md` (+docs zrcadlo), `STOPA_ROADMAP.md` (D covered 72/232, 36 parser modulů).

## Testy
- Nové: `.venv/bin/python -m pytest tests/test_w6_parsers.py -q` → **37 passed**.
- Full suite: `.venv/bin/python -m pytest -q` → **1279 passed, 1 skipped** (baseline 1242 + 37).
- Ruff: `All checks passed!` pro `src/stopa tests scripts`.

## Registry
- Feature: **F-057** ETAPA B vlna 6 — Google local profile/takeout + přílohy (4 parsery / 4 AXIOM typy).
- Testy: **T-078** `tests/test_w6_parsers.py` (37).
- Celkový stav TEST_REGISTRY: **1279 testů: 1278 PASS + 1 skipped**.

## Coverage matice
covered **68 → 72 / 232** unikátních typů — flip 4 přímých AXIOM typů NOT_SUPPORTED → SUPPORTED:
GooglePhotosArtifact, GoogleMailMessageInformationArtifact (WarrantReturn), GoogleBarArtifact (top-level),
AttachmentExtractor (Common.dll). NOT_SUPPORTED 130 → 126; DEPRECATED 34 (bez změny);
**portable-local NOT_SUPPORTED = 0 ★** — všechny lokální typy pokryty.

## Další krok
**ETAPA B vlna 7 — Artifact Engine: cloud-export typy (zbývá 111)** (oblast D, P0) —
Google Drive/Docs rodina, Chrome warrant return (history/bookmarks/contacts/prefs), Google Voice 2025/2026;
detail v `NEXT_ACTION.md`.
