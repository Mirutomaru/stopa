# STOPA — Checkpoint (2026-11-07)

## Hotovo
**STP-059 — Oblast Q: Timesketch push ★ = odeslání case dat do Timesketch hotové**
- `data/timesketch_client.py` (nový, 253 ř.) — HTTP klient po vzoru `LmStudioClient` s injektovatelným transportem (offline testovatelnost přes `httpx.MockTransport`): login flow s CSRF scrapem (`input#csrf_token`, fallback `<meta name="csrf-token">`), `create_sketch()` POST `/api/v1/sketches/` → 201, ID z `objects[0].id`; `upload_timeline()` multipart `/api/v1/upload/` (sketch_id/name/file) → `{timeline_id, task_id}`; `health()` bez side effectů; výjimky `TimesketchError` / `TimesketchUnavailable` (graceful degradation); env override `STOPA_TIMESKETCH_URL/USER/PASSWORD`.
- `domain/timesketch_push.py` (nový, 83 ř.) — čistá doménová logika s injektovatelným klientem (`Protocol`): reuse exportních konvertorů (`to_l2tcsv`, timeline records), název sketchu `STOPA <case> — <what>`, souhrn `{sketch_id, timeline_id, task_id, records}` pro audit bez přístupových údajů; prázdný dataset → `ValueError`.
- `cli.py` — nový příkaz `stopa timesketch-push <case> --what artifacts|timeline|correlations` (stejná doménová funkce jako web).
- `web/app.py` — endpoint `POST /api/cases/{id}/timesketch-push`: RBAC `_require("analysis.run")`, validace `what ∈ {artifacts, timeline, correlations}` → 400, nedostupná Timesketch → 503, selhání pushu → 502; audit log `timesketch_pushed` + integrity checkpoint. **Oprava reálného bugu:** web `create_case` nevytvářel Ed25519 klíč (CLI ano) → integrity checkpointy se ticho propadaly; doplněno generování klíče s graceful degradation.
- Testy: `tests/test_stp059.py` (nový, 501 ř., 20 testů) — klient přes MockTransport (login/CSRF fallback/create_sketch/upload/health/env), doména s fake klientem (payload, souhrn, ValueError), web E2E (400/503/502 + audit `timesketch_pushed` + integrity checkpoint v DB).

## Stav
- Full suite: **2048 passed, 1 skipped** (baseline 2028 + 20); ruff clean.
- Commit: `35e3c77` feat(interop): STP-059 Timesketch push — klient, doména, CLI, web endpoint + testy.

## Další
Oblast Q rozšířena ★★ (Timesketch push = třetí interop smyčka: export l2tcsv → import l2tcsv → push do Timesketch). Další kandidáti dle priority: viz NEXT_ACTION.md / ROADMAP.md (nová oblast dle priority uživatele, nebo volitelné rozšíření — např. GUI tlačítko pro Timesketch push v Interop Export Center modulu).
