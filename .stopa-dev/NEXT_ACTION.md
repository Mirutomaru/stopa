# NEXT ACTION — po STP-041 (ETAPA C dokončena ★★)

## Hotovo
- **STP-041 / ETAPA C vlna 3** — `schema.py` + `migrations.py` vyčleněny, facade úklid; commit ```824755d```.
- **ETAPA C dokončena ★★** — `db.py` ~2090 → **476 řádků (−77 %)**, cíl < ~600 splněn.
- Full suite: **1792 passed, 1 skipped**; ruff clean; DEV OS + changelog + roadmapy synchronizovány.

## Další krok — STP-042: volba ETAPY D
Audit reálného stavu zbývajících oblastí v kódu (ne jen roadmapě) + rozhodnutí o směru:
1. **B/C** — disk images & filesystemy (NTFS/EXT4/APFS/EWF — co je pokryto, co chybí).
2. **G** — timeline intelligence (co po STP-018 zbylo).
3. **I** — report engine (20 sekcí hotové; rozšíření/exporty?).
4. **M** — performance & benchmark (CI běží lint+test, ale bez benchmarku).

Kritéria volby: priorita P0/P1 v roadmapě + reálný stav kódu + dopad na uživatele.

## Po dokončení volby
- Synchronizace obou roadmap (root `STOPA_ROADMAP.md` + `.stopa-dev/ROADMAP.md`).
- DEV OS: TASKS STP-042, PROJECT_STATE fáze, checkpoint, NEXT_ACTION.
- Docs commit s reálným hashem.
