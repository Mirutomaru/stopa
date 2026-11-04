# STOPA — NEXT ACTION

**Aktuální stav:** STP-037 hotový (ETAPA B vlna 15 — závěrečný audit) → **ETAPA B DOKONČENA ★**
**Commit:** `166e42e` (feature), HEAD po docs follow-upu viz git log.

## Co je hotové
- [x] ETAPA B vlny 1–15 — celá oblast D (Artifact Engine) ✅
- [x] Coverage: covered **198 / 232 ★**, NOT_SUPPORTED celkem **0** (base-class 34 = rozhraní/DEPRECATED)
- [x] C3 registry: **76 verzovaných parserů**
- [x] Závěrečný audit test `tests/test_etapa_b_final_audit.py` — 13 invariantních testů, offline
- [x] Full suite: **1742 passed, 1 skipped**; ruff clean

## Nejbližší krok (STP-038)
**Volba oblasti pro ETAPU C.** Kandidáti dle roadmapy (priorita P0→P2):
1. **E — Advanced Timeline** (základ hotov, P2; nejbližší úkol STP-018)
2. **F — Evidence Graph** (P?)
3. **N — Performance** (STP-021 stream parsing velkých E01 + progress monitoring)

Doporučení: projít roadmapu a vybrat oblast s nejvyšší prioritou; pak rozložit do vln/úkolů
jako ETAPA B (TASKS.md → implementace → testy → docs).

## Kontrolní příkazy
```bash
cd /home/ai/Prace/projekty/stopa
.venv/bin/python -m pytest tests/test_etapa_b_final_audit.py -q   # 13 passed
.venv/bin/python -m pytest tests/ -q                              # 1742 passed, 1 skipped
.venv/bin/ruff check src/stopa tests scripts                      # All checks passed!
```

## Reference
- Checkpoint: `.stopa-dev/checkpoints/latest.md` (STP-037) + `history/20261104-stp036-vlna14-cloud-export-done.md`
- DEV OS: TASKS.md (STP-037), FEATURE_REGISTRY.md (F-066), TEST_REGISTRY.md (T-087, celkem 1742), PROJECT_STATE.md
- Roadmap: `STOPA_ROADMAP.md` — oblast D ✅ hotovo (vlny 1–15)
