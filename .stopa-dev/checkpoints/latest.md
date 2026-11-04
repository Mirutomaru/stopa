# CHECKPOINT — STP-041 hotový = ETAPA C vlna 3 DOKONČENA ★ = CELÁ ETAPA C DOKONČENA ★★ (2026-11-04)

## Stav
- **ETAPA C dokončena** — monolit `db.py` rozložen na doménová repozitáře + schema/migrations moduly.
- `db.py`: ~2090 → 1565 (vlna 1) → 1011 (vlna 2) → **476 řádků** (vlna 3) = **−77 %**; cíl < ~600 splněn.
- `CaseDB` = tenký agregátor 5 repozitářů na sdílené SQLite connection; backward compat zachován (`CaseDB`, `SCHEMA_VERSION`, `_fts_query`).

## Co se stalo (STP-041, commit ```824755d```)
- **`schema.py`** (293 ř.): SCHEMA_VERSION + `_schema_version` + kompletní DDL (15 tabulek, indexy, triggery, FTS5).
- **`migrations.py`** (268 ř.): `apply_legacy_migrations` — audit chain backfill od GENESIS s obnovou triggerů, entity CHECK rebuild + confidence remap, timeline intel sloupce, FTS backfill flagy.
- **Facade úklid:** mrtvé `_last_audit_row`/`_case_examiner` pryč; `__init__` volá `apply_legacy_migrations(self.conn)`.
- Testy: `tests/test_stp041_wave3_schema_migrations.py` — **18 testů** (SCHEMA DDL, legacy v10 migrace end-to-end, idempotence, backward compat).

## Verify
- Ruff: All checks passed! ✓
- Full suite: **1792 passed, 1 skipped** (baseline 1774 + 18) ✓
- Nové testy: 18/18 passed ✓

## Další krok
**Volba ETAPY D** — audit reálného stavu zbývajících oblastí (B disk images, C filesystems, G timeline, I report engine, M performance, R UI) + rozhodnutí o směru. Kandidáti dle roadmapy: B/C (disk+filesystem), G (timeline intelligence), I (report engine 20 sekcí — rozšíření), M (performance/benchmark v CI).
