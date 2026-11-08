# NĚJBLIŽŠÍ AKCE — STOPA (2026-11-08)

## Hotovo právě teď: **STP-065 ★★ = Timesketch push s limit + UI input** (ROADMAP #1)
Parametr `limit` pro push do Timesketch v doméně (`push_to_timesketch(..., limit=None)` — `None` = vše, `< 1` → ValueError, souhrn rozšířen o `total_records`), web endpointu (`TimesketchPushIn.limit: int | None = Field(ge=1)` → neplatné = 422), CLI (`stopa timesketch-push --limit N`) a UI (input `#ts-push-limit`, prázdné = vše; JS posílá limit v POST body jen když vyplněný). **10 nových testů** (`tests/test_stp065.py`: doména + web E2E) + JS DOM rozšířeno 19→23 (**23/23 passed**). Full suite **2085 passed, 1 skipped**, ruff clean.

## Co dělat dál (ROADMAP kandidáti)
1. **STP-066: Export center — náhled CSV/JSON před downloadem** — generalizace STP-064 preview na ostatní formáty (`?what=&format=`), sdílený UI komponent; read-only, bez auditu.
2. **STP-067: Interop export historie v UI** — tabulka posledních 10 exportů už existuje (audit log); přidat re-download z audit záznamu (cache poslední export na disk pod case dir) + testy.

## Stav verifikace (2026-11-08, STP-065)
- Full suite: **2085 passed, 1 skipped** (+10 nad baseline 2075/1s)
- `tests/test_stp065.py`: **10/10 passed** (doména: limit=None vše / limit=N prvních N po řádcích / limit>dataset vše / limit=0 a negativní ValueError / prázdný dataset s limitem ValueError; web E2E: push s limit=2 z 5 → summary records=2 total_records=5 + audit nese oba počty, backward compat bez limitu, limit=0/-1 → 422)
- JS DOM: `node tests/js/interop.test.mjs` → **23/23 passed** (4 nové: push s limitem body {what,limit}, prázdný input jen {what}, invalidní limit 0 → ✗ + 0 API volání, stav „z celkem N")
- Ruff: clean; coverage matice 237 řádků (bez změny — limit je parametr nadstaveby bez nových axiomů); C3 registry **76** (bez změny — žádný nový parser)

## Checkpoint
`.stopa-dev/checkpoints/latest.md` = STP-065; předchozí (STP-064) archivován do `history/20261108-stp064-l2tcsv-preview-done-archived.md`.
