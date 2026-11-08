# STOPA — Checkpoint (aktualizováno 2026-11-08)

## Stav: STP-062 dokončen ★★ (oblast O+Q — UI polling Timesketch status)

### Co se udělalo
- **UI polling Timesketch status** (F-087 rozšířeno): tlačítko 📡 Stav indexace v kartě Timesketch push; poll `GET /api/cases/{id}/timesketch-status` každých 5 s, max 10 min
- Terminální stavy: `ready` → ✅ Indexace dokončena (zastaví), `fail`/`failed` → ❌ (zastaví); `pending`/`processing` → ⏳ pokračuje
- Chybové cesty: 404 = žádný push (zastaví, "Nejdřive spusťte Push"), 503 Timesketch nedostupný = pokračuje dál, jiná chyba = zastaví
- **JS DOM testy rozšířeny 5 → 11** (tests/js/interop.test.mjs): render tlačítka + onclick, poll→ready stop, poll→fail stop, 404 stop, 503 pokračuje, max 10 min stop; vm sandbox doplněn o setInterval/clearInterval
- Full suite **2058 passed, 1 skipped** (bez změny — JS DOM testy běží samostatně přes Node), ruff čistý

### Commit
- `d4f3a1e` feat(web): STP-062 UI polling Timesketch status (oblast O+Q ★★)

### Zbývá / další kandidáti
- **STP-063** — viz NEXT_ACTION.md (kandidáti: Timesketch timeline detail v UI, L2T CSV preview endpoint, GUI polish)
