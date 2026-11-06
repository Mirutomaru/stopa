# STOPA — Checkpoint (2026-11-06)

## Hotovo
**STP-054 — Oblast K Export Engine: Plaso interop formát l2tcsv ★**
- `domain/export.py::to_l2tcsv()` — 17 pevných polí log2timeline.pl (dle oficiální Plaso dokumentace): date/time z ISO UTC, timezone=Z, source=STOPA, sourcetype per dataset, short (100 znaků), desc deterministický popis, notes = anomaly flags, format=stopa.<dataset>, extra = JSON všech ne-None polí (sort_keys).
- CLI `stopa export <case_id> --what ... --format l2tcsv [--limit N] [--out SOUBOR]`.
- Testy: `tests/test_stp054.py` (19) — header, časové konverze, neznámý čas → prázdná pole, truncace, escapování, determinita.

## Stav
- Full suite: **1975 passed, 1 skipped** (baseline 1956 + 19); ruff clean.
- HEAD před commitem: `0f0f9e8` (docs devos STP-053). STP-054 commit hash viz git log.

## Další
Q Interop / UCO mapping nebo J UI přepínač role v Settings (RBAC enforcement hotový STP-053, K Plaso hotové STP-054).
