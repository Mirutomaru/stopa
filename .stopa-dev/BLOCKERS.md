# STOPA — BLOCKERS (evidence překážek)

Blokovaný úkol nesmí být označen jako DONE. Stav: OPEN | RESOLVED | ACCEPTED.

**Stav k 2026-11-10:** OPEN blokérů = **0 ★** — všechny původní položky vyřešeny,
doloženo commit hash + důkazem v kódu (ověřeno při závěrečné validaci).

## BLK-001 — RAM peak u velkých E01 obrazů
- **Popis:** pipeline načítá velké obrazy do paměti; chybí stream parsing.
- **Důvod:** image_pipeline pracuje s celým obrazem v RAM (ThreadPoolExecutor paralelizace).
- **Dotčená funkce:** F-010/F-011 (disk images), N (Performance).
- **Dopad:** obrazy >8 GB mohou vyžadovat hodně RAM.
- **Řešení:** stream parsing po chunkách + byte-level progress callback.
- **Stav:** RESOLVED v STP-021 (`e0c34b3`, 2026-11) | `ewf_container.stream_to_raw()`
  zapisuje kontejner do RAW po **1 MiB chunkách** (RAM peak = jedna chunka, ne celý obraz);
  zapojeno v `image_pipeline.py:116` (EWF→RAW před TSK). Progress callback pro Processing Monitor.

## BLK-002 — Monolit `data/db.py` (~1942 řádků)
- **Popis:** CaseDB obsahuje DDL + migrace + CRUD + audit v jednom souboru.
- **Důvod:** historický růst; migrace jsou navzájem závislé (v10→v11 rebuild tabulek).
- **Dotčená funkce:** A (Core), J (Case Management).
- **Dopad:** obtížnější testování jednotlivých částí; riziko regresí při změně.
- **Řešení:** rozdělení na doménová repozitáře + schema/migrations moduly, backward compat facade.
- **Stav:** RESOLVED v ETAPĚ C (STP-039/040/041, `58628a9`/`28b6222`/`824755d`, 2026-11) |
  `db.py` **2090 → 498 řádků (−76 %)**; vyčleněno: `case_repository.py`, `file_repository.py`,
  `audit_repository.py`, `artifact_repository.py`, `entity_repository.py`, `schema.py`,
  `migrations.py`. Veřejné API `CaseDB` beze změny, full suite zelená po každé vlně.

## BLK-003 — Benchmark engine neběží v CI
- **Popis:** detekce regresí >20% existuje, ale benchmark se spouští ručně (`stopa benchmark`).
- **Důvod:** chybí CI pipeline (GitHub Actions).
- **Dotčená funkce:** F-007, P (QA).
- **Dopad:** výkonové regrese se objeví až při ručním měření.
- **Řešení:** CI job `benchmark` proti versionované baseline + fail na regresi >20 %.
- **Stav:** RESOLVED v ETAPĚ D (STP-043/044, `0136e91`/`ca93d58`, 2026-11) |
  `.github/workflows/ci.yml` job `benchmark`: `scripts/ci_benchmark.py` běh suite=all (77 položek),
  porovnání s `benchmarks/baseline.json` (versionovaný artefakt), CI noise guard (≥0.5 ms),
  upload výsledků jako artifact; E2E subprocess testy (`test_stp044_ci_benchmark_e2e.py`, 6).

## BLK-004 — RBAC chybí (actor = volitelný string)
- **Popis:** audit log přijímá libovolný actor; žádná povinná identita/role.
- **Důvod:** single-user desktop aplikace; multi-user nasazení zatím nevyžadováno.
- **Dotčená funkce:** M (Security), J (Case Management).
- **Dopad:** při sdíleném nasazení nelze rozlišit oprávnění.
- **Řešení:** RBAC permission matrix + fail-closed enforcement na mutující endpointy.
- **Stav:** RESOLVED v STP-053 (`ef9c999`, 2026-11) | `domain/rbac.py` (role analyst/examiner/admin ×
  oprávnění, permission matrix = jediný zdroj pravdy), `_require()` na **20 mutující endpointy** v
  `web/app.py`; UI přepínač role bez restartu hotový od STP-056 (`7356330`).

## BLK-005 — `STOPA_AI_GOVERNANCE.md` chybí v kořeni
- **Popis:** MASTER DEVELOPMENT PROMPT vyžaduje 9 kořenových dokumentů; AI governance neexistuje.
- **Důvod:** AI vrstva (I1/I2) implementována dříve než požadavek na kořenové výstupy.
- **Dotčená funkce:** H (AI Copilot).
- **Dopad:** chybí formální governance dokumentace (PII, modely, oddělení případů).
- **Možné řešení:** STP-019 — vytvořit dokument + PII redaktor.
- **Stav:** RESOLVED v STP-019 (2026-11-03) | `STOPA_AI_GOVERNANCE.md` hotový, PII redaktor + audit modelových volání implementovány

## RESOLVED
- **BLK-R1** (2026-11): `sqlite3.Row` nemá `.get()` → ruff SIM118 opraven přímým přístupem s komentářem o migraci. RESOLVED v I3.
- **BLK-R2** (2026-11): holé `.venv/bin/pytest -q` mělo import-mode problém v `test_tsk_py.py` → spouštět `.venv/bin/python -m pytest -q`. RESOLVED (dokumentováno).
