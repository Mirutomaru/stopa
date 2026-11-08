# STOPA Checkpoint — 2026-11-08 (STP-065 DOKONČEN ★★)

## Úkol
**STP-065 — Timesketch push s limit + UI input** (oblast O+Q, P3): parametr `limit` pro push do Timesketch v doméně, web endpointu, CLI a UI. ROADMAP kandidát #1 po STP-064.

## Hotovo
1. **`src/stopa/domain/timesketch_push.py`** — `push_to_timesketch(client, case_name, what, records, limit=None)`:
   - `limit=None` → celý dataset; `limit < 1` → `ValueError`; pushne jen prvních N záznamů
   - souhrn rozšířen o klíč `total_records` (celkový počet v datasetu) — UI/audit ukáže „X záznamů (celkem Y)"
2. **`src/stopa/web/app.py`** — Pydantic model `TimesketchPushIn` dostal pole `limit: int | None = Field(ge=1)` → neplatné hodnoty (0, negativní) = HTTP 422; endpoint `POST /api/cases/{id}/timesketch-push` předává `body.limit` do domény.
3. **`src/stopa/cli.py`** — nový flag `--limit N` pro `stopa timesketch-push`; výstup ukazuje „X záznamů (celkem Y)".
4. **`src/stopa/web/static/index.html`** — v kartě Timesketch push nový input `<input type="number" id="ts-push-limit" min="1" step="1" placeholder="vše">`; prázdné = vše.
5. **`src/stopa/web/static/js/components/interop.js`** — handler `btn-ts-push` čte limit a zařazuje ho do POST body jen když je vyplněný; stavový text obsahuje počet záznamů i celkový count.

## Testy
- **10/10 passed** (`tests/test_stp065.py`, 251 ř., doména + web E2E): `limit=None` pushne vše, `limit=N` jen prvních N (payload ověřen po řádcích), limit > dataset → vše, `limit=0`/negativní → `ValueError`, prázdný dataset s limitem → `ValueError`; web E2E: push s `limit=2` z 5 záznamů (summary `records=2, total_records=5` + audit log nese oba počty), backward compat bez limitu, `limit=0`/`-1` → **422**.
- **JS DOM 23/23 passed** (`tests/js/interop.test.mjs` rozšířeno 19→23; 4 nové: push s limitem → body `{what, limit}`, prázdný input → jen `{what}`, invalidní limit (0) → ✗ + žádné API volání, úspěšný stav „z celkem N").
- **Full suite: 2085 passed, 1 skipped** (+10 nad baseline 2075/1s) bez regresí.
- Ruff: `All checks passed!` (opraveno 1 fixable v novém test souboru).
- Coverage matice: total=237 unique=232 (bez změny — limit je parametr nadstaveby bez nových axiomů). C3 registry: **76** (bez změny — žádný nový parser).

## Commit
`65ff065` feat(timesketch): STP-065 push limit — domain/web/CLI/UI + testy (8 souborů, +355/−17)

## Zbývá / další
- ROADMAP kandidáti: #2 STP-066 generalizace preview na ostatní formáty; #3 STP-067 re-download z audit historie.
