# STOPA — Checkpoint (2026-11-07)

## Hotovo
**STP-060 — Oblast O+Q: Timesketch push UI ★ = GUI tlačítko pro Timesketch push v Interop Export Center hotové**
- `web/static/index.html` — nová karta `#ts-push-card` v modulu Interop Exporty (nad „Přehled datasetů“): popis + tlačítko `#btn-ts-push` („🚀 Push do Timesketch“) + stavový výstup `#ts-status`. Reuse existujícího selectu `#ix-what` (dataset) — push odesílá právě zvolený dataset.
- `web/static/js/components/interop.js` (+25 ř.) — wiring `btn-ts-push.onclick`: POST `/api/cases/{id}/timesketch-push` s body `{what}` (z `#ix-what`), busy stav (disabled + „Odesílám…“), úspěch → `✓ Push hotovo — sketch N, timeline M, záznamů K` + toast, selhání → `✗ Push selhal: <msg>` + toast, `finally` tlačítko znovu aktivní. Stejný vzorec jako ostatní POST moduly (ai.js/files.js).
- `tests/js/interop.test.mjs` (nový, 5 DOM testů přes jsdom po vzoru E5 graph.test.mjs): wiring onclick, POST kontrakt (metoda + endpoint + body `{what}`), úspěšný stavový výstup, selhání (✗ + reaktivace tlačítka v finally), busy disabled během pushu. Spustí: `node tests/js/interop.test.mjs` → **5/5 passed**.
- Ověřeno: statické soubory servírují nové UI (TestClient smoke), full suite **2048p/1s** bez regresí, ruff clean.

## Stav
- HEAD: `ddb3aa0` feat(web): STP-060 Timesketch push UI — tlačítko v Interop Export Center + DOM testy
- Full suite: **2048 passed, 1 skipped**, ruff clean; JS DOM: graph 5/5 + interop 5/5
- Oblast Q ★★ (Timesketch push CLI+web API) + oblast O rozšířena o GUI vrstvu — třetí interop smyčka je teď plně dostupná z UI.

## Další krok
DEV OS sync (tento checkpoint + ROADMAP/TASKS/NEXT_ACTION/registry), pak code review request ★.
