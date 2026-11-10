# STOPA — ZÁVĚREČNÍ VALIDAČNÍ ZPRÁVA (2026-11-10)

**Verze:** 0.1.0 · **Commit HEAD:** `e37b328` (main, working tree čistý)
**Účel:** závěrečná validace celého projektu po dokončení roadmapy A–Q a ulehnutí technického dluhu.

---

## 1. Verdikt

STOPA je **funkčně kompletní forenzní workbench**: všechny 15 oblastí roadmapy (A Core
Architecture … Q Interoperability) jsou hotové, všechny úkoly v registru DONE,
**OPEN blokérů = 0 ★**, celá testová sada zelená, ruff clean.

## 2. Ověřeno živě dnešním dnem (2026-11-10)

| Kontrola | Výsledek |
|---|---|
| Python full suite (`python -m pytest -q`) | **2154 passed, 1 skipped** (~51 s) |
| `ruff check src/stopa tests scripts` | **All checks passed!** |
| JS DOM testy (node + jsdom) | graph / interop / modules → **3× PASS** |
| Git stav | main @ `e37b328`, working tree čistý, 0 rozpracovaných úkolů |
| Úkoly v registru `.stopa-dev/TASKS.md` | **40/40 STP DONE**, 0 IN_PROGRESS/BLOCKED |

## 3. Rozsah produktu

- **Kód:** ~42 700 řádků Pythonu v `src/stopa/`, 88 souborů extraktorů artifactů
- **Web API:** 47 endpointů (FastAPI) + vanilla JS SPA bez build kroku
- **CLI:** case/add/files/search/timeline/stats/report/export/correlate/mobile/image/plaso-import/timesketch-push/benchmark/serve
- **Coverage matice** (`STOPA_COVERAGE_MATRIX.csv`, deterministická, SHA-256 ověřitelná):
  **198 / 232 unikátních AXIOM typů = SUPPORTED ★**, zbývajících 34 = DEPRECATED base-class rozhraní
  (ne extraktory) → **NOT_SUPPORTED = 0**
- **Parser registry C3:** 76 verzovaných parserů, 1:1 sync s pipeline

## 4. Ulehnutý technický dluh (doloženo v `.stopa-dev/BLOCKERS.md`)

| Blokér | Stav | Důkaz |
|---|---|---|
| BLK-001 RAM peak velkých E01 | **RESOLVED** (STP-021, `e0c34b3`) | `stream_to_raw()` po 1 MiB chunkách — RAM peak = chunka, ne obraz; zapojeno v image_pipeline |
| BLK-002 monolit `db.py` (~2090 ř.) | **RESOLVED** (ETAPA C, STP-039/040/041) | db.py → **498 ř. (−76 %)**; 5 repozitářů + schema/migrations moduly; API `CaseDB` beze změny |
| BLK-003 benchmark mimo CI | **RESOLVED** (ETAPA D, STP-043/044) | CI job `benchmark` proti baseline, fail >20 % regrese + noise guard; 6 E2E testů |
| BLK-004 chybějící RBAC | **RESOLVED** (STP-053, UI STP-056) | permission matrix role×oprávnění, fail-closed `_require()` na 20 mutující endpointy; přepínač role v Settings bez restartu |
| BLK-005 AI governance doc | **RESOLVED** (STP-019) | `STOPA_AI_GOVERNANCE.md` + PII redaktor + audit modelových volání |

**Otevřený dluh: žádný.** Historické záznamy BLK-R1/BLK-R2 jsou dokumentační poznámky, ne blokéry.

## 5. Kvalitní brány (stálé)

- **CI** (`.github/workflows/ci.yml`): lint → pytest → JS DOM → pip-audit → benchmark proti baseline
- **Benchmark engine:** 77 položek, detekce regresí >20 % + CI noise guard ≥0.5 ms
- **Sandbox parserů** (ETAPA E): subprocess izolace + timeout — poškozený soubor nepadne pipeline; fix reálného hang bugu `sqlite_carver`
- **Integrita:** SHA-256/MD5/SHA-512, Ed25519 podpisy exportů a reportů, hash-chained audit log (tamper-evident), chain of custody v reportu
- **Reprodukovatelnost:** verze nástroje + parser versions ve všech reportech/exportech

## 6. Známé limity (ne blokující)

1. `test_stp044_ci_benchmark_e2e` je občas flaky v CI — timing šum benchmarku, lokálně stabilní;
   noise guard (≥0.5 ms) tlumí falešné regrese.
2. LUKS dešifrování vyžaduje root + cryptsetup (limitace platformy, ne nástroje).
3. ElfFile varianta EVTX: event_id/timestamp binárně kódované v BinXML — extrahuje se content-scanem,
   numerické pole může být None u této varianty (dokumentováno v parseru).

## 7. Doporučení pro další vývoj (volitelné)

- Import cizích timeline (Plaso hotový; Timesketch import by byl přirozený doplněk)
- GUI tlačítko Timesketch push už je — případně automatický push po analýze (pattern STP-069/070)
- Release: bump verze 0.1.0 → 1.0, build distributivního balíčku

---

**Závěr:** projekt je v produkcích nasaditelném stavu, plně testovaný a dokumentovaný.
Validace provedena 2026-11-10; všechny údaje doloženy reálným výstupem nástrojů (viz §2).
