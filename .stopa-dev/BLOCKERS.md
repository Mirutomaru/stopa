# STOPA — BLOCKERS (evidence překážek)

Blokovaný úkol nesmí být označen jako DONE. Stav: OPEN | RESOLVED | ACCEPTED.

## BLK-001 — RAM peak u velkých E01 obrazů
- **Popis:** pipeline načítá velké obrazy do paměti; chybí stream parsing.
- **Důvod:** image_pipeline pracuje s celým obrazem v RAM (ThreadPoolExecutor paralelizace).
- **Dotčená funkce:** F-010/F-011 (disk images), N (Performance).
- **Dopad:** obrazy >8 GB mohou vyžadovat hodně RAM.
- **Možné řešení:** stream parsing po sektorech/chuncích; limit počtu workerů podle velikosti obrazu.
- **Stav:** OPEN | **Blokuje:** STP-021 (ne kriticky — funkční, jen omezený)

## BLK-002 — Monolit `data/db.py` (~1942 řádků)
- **Popis:** CaseDB obsahuje DDL + migrace + CRUD + audit v jednom souboru.
- **Důvod:** historický růst; migrace jsou navzájem závislé (v10→v11 rebuild tabulek).
- **Dotčená funkce:** A (Core), J (Case Management).
- **Dopad:** obtížnější testování jednotlivých částí; riziko regresí při změně.
- **Možné řešení:** postupné rozdělení na `db_schema.py` / `db_migrations.py` / `db_queries.py` s zachováním veřejného rozhraní CaseDB.
- **Stav:** OPEN | **Blokuje:** nic kritického (technický dluh)

## BLK-003 — Benchmark engine neběží v CI
- **Popis:** detekce regresí >20% existuje, ale benchmark se spouští ručně (`stopa benchmark`).
- **Důvod:** chybí CI pipeline (GitHub Actions).
- **Dotčená funkce:** F-007, P (QA).
- **Dopad:** výkonové regrese se objeví až při ručním měření.
- **Možné řešení:** CI job s baseline porovnáním; pip-audit do stejného pipeline.
- **Stav:** OPEN | **Blokuje:** STP-022 (částečně)

## BLK-004 — RBAC chybí (actor = volitelný string)
- **Popis:** audit log přijímá libovolný actor; žádná povinná identita/role.
- **Důvod:** single-user desktop aplikace; multi-user nasazení zatím nevyžadováno.
- **Dotčená funkce:** M (Security), J (Case Management).
- **Dopad:** při sdíleném nasazení nelze rozlišit oprávnění.
- **Možné řešení:** minimální RBAC — povinný actor + role (viewer/analyst/admin) v meta tabulce.
- **Stav:** OPEN | **Blokuje:** STP-022

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
