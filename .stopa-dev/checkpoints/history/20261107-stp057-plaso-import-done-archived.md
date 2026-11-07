# STOPA — Checkpoint (2026-11-07)

## Hotovo
**STP-057 — Oblast Q Interop: Plaso import (l2tcsv → case) ★★ = OBLAST Q DOKONČENA**
- `domain/plaso_import.py` (nový, čistá logika bez IO): `parse_l2tcsv(text)` — 17 pevných polí log2timeline.pl; timestamp reconstruction (date MM/DD/YYYY + time HH:MM:SS + timezone „Z“ → UTC; neplatný/chybějící → `ts_utc=None` bez ztráty řádku); `extra` JSON se obnovuje do details (neplatné JSON → raw zachován); prázdné řádky přeskočeny; cizí sourcetype (ne-STOPA) → fallback event `plaso_event` (title z short, rel_path z filename).
- `import_l2tcsv(db, case_id, path)` — zdroj `EvidenceSource(kind="file")` s `.l2t.csv`, artifacty (`artifact_type` z sourcetype), timeline events (bez timestampu → jen artifact); audit `log_operation(action="plaso_import", details=souhrn)` + integrity checkpoint `plaso-import`.
- CLI: `stopa plaso-import <case_id> SOUBOR` (subparser po export; chybějící soubor → SystemExit „nenalezen“).
- Testy: `tests/test_stp057_plaso_import.py` (14) — parse roundtrip/naive/invalid timestamp, extra JSON restore + invalid raw fallback, empty rows skip, foreign sourcetype fallback; import E2E (source/artifact/timeline); CLI E2E (export timeline → l2tcsv → import, audit akce `plaso_import`, integrity checkpoint, chybějící soubor).

## Stav
- Full suite: **2019 passed, 1 skipped** (baseline 2005 + 14); ruff clean.
- HEAD před commitem: viz git log (STP-057 code commit). STP-057 DEV OS commit hash viz git log.

## Další
Oblast Q dokončena ★★ — interop kompletní (export l2tcsv + UCO, import l2tcsv). Další kandidáti dle priority: viz NEXT_ACTION.md / TASKS.md roadmap.
