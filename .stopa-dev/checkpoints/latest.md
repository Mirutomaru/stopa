# Checkpoint — 2026-11-09 (STP-070)

## Hotovo v tomto cyklu
- **STP-070** (ROADMAP po STP-069): periodický plánovač auto-bundle — rozšíření STP-069 o časový interval per case.
- Doména: `domain/export_schedule.py` (nový, čistý modul bez I/O) — `parse_interval_minutes()` (None/"" → None; celé číslo 5–43200 min; jinak ValueError), `is_due(last_run_utc, now_utc, interval_minutes)` deterministické rozhodnutí.
- Data vrstva: schema v14 + sloupce `cases.auto_export_interval_minutes` / `last_auto_export_at`, idempotentní migrace pro DB ≤ v13; repo metody `set_auto_export_interval/mark_auto_export_ran/list_scheduled_cases`; facade db.py.
- Web scheduler: daemon thread `stopa-auto-export`, tick 60 s (sleep-first → testy nevidí tick); due případy → `build_auto_bundle()` re-use, atomický zápis tmp→rename; chyba u jednoho případu nepadá tick (warning log).
- API: PATCH `/api/cases/{id}` + `auto_export_interval_minutes` (5–43200, null = vymazat), serializace v detailu i listu; CLI `case auto-interval <minutes|off>` + `--interval N`; UI input `.case-auto-interval`.

## Stav testů
- Python full suite: **2153 passed, 1 skipped** (před STP-070: 2135) — +19 v `tests/test_stp070.py` (doména parse/is_due, data persist/readback/filtr, web E2E PATCH 422/serializace, scheduler tick due/nedue/disabled).
- ruff clean.

## Zbývá / další krok
1. Push na origin/main — až na explicitní pokyn uživatele.
2. P4 kandidáti z revize 2026-11-24 (viz NEXT_ACTION.md): re-pin carving wheel v2.4.0, rozšíření AI Copilotu.

## Poznámky pro příští agenta
- Commit: `e37b328` feat(stp-070): periodický plánovač auto-bundle (interval per case, schema v14).
- Checkpoint STP-069 archivován do `history/20261109-stp069-auto-bundle-done-archived.md`; archive STP-068 v history/ chybí (checkpoint byl přepsán bez archivace).
