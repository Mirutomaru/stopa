# CHECKPOINT — STP-042 hotový = ETAPA D ZAHÁJENA ★ (2026-11-04)

## Stav
- **ETAPA D zahájena** — volba směru dokončena: **oblast P (Quality Assurance): CI běh benchmarku proti baseline**.
- Audit reálného stavu kandidátů v kódu: P QA (engine hotový, CI job chybí), M sandbox (neexistuje), H AI grounding (citace ano, rozporů ne), I+O UI (registry ano, UI ne), G/J/K/Q (částečně/ne).
- Obě roadmapy synchronizovány: sekce P → 🔧 v průběhu ETAPA D + nová sekce „ETAPA D — ROZHODNUTÍ O SMĚRU" s audit tabulkou a plánem vln 1–2.

## Klíčové čísla
- `db.py`: **476 ř.** (ETAPA C dokončena ★★, −77 % od ~2090)
- Full suite: **1792 passed, 1 skipped** | ruff clean
- C3 registry: **76 parserů** | covered **198 / 232 ★** (NOT_SUPPORTED 0)
- Dokončené úkoly: **42**

## Co je hotové (STP-042)
- [x] Audit reálného stavu všech kandidátských oblastí v kódu
- [x] ROZHODNUTÍ: ETAPA D = P QA CI benchmark job (jediný zbývající P1, nejmenší rozsah s největším dopadem)
- [x] DEV OS ROADMAP + root STOPA_ROADMAP sync (sekce P + sekce ETAPA D rozhodnutí)
- [x] TASKS.md záznam STP-042 | PROJECT_STATE fáze/next/testing/datum
- [x] CHANGELOG záznam | checkpoint archivace STP-041 do history/

## Co zbývá (STP-043 — ETAPA D vlna 1)
- [ ] `.github/workflows/ci.yml` + job `benchmark` (po lint/test)
- [ ] `scripts/ci_benchmark.py`: `run_benchmark(suite="core")` → porovnání s baseline přes `detect_regressions(threshold=0.20)` → fail na regresii → upload výsledků jako artifact
- [ ] Inicializace versionovaného baseline artefaktu `benchmarks/baseline.json` (z lokálního běhu)

## Další krok
**STP-043 — ETAPA D vlna 1: CI benchmark job.** Po dokončení: STP-044 vlna 2 = testy + dokumentace.
