# STOPA — NEXT ACTION

**Datum:** 2026-11-04
**Poslední hotový úkol:** STP-038 — ETAPA C volba směru + synchronizace roadmapy (oblast A, P1) ★ **ETAPA C ZAHÁJENA**

## Co je hotové
- ETAPA B dokončena (STP-037, vlna 15 — závěrečný audit; commit `166e42e`); oblast D ✅ hotovo.
- Audit reálného stavu všech oblastí A–Q v kódu + synchronizace zastaralých „Nedokončeno" položek roadmapy (E/L/H/J/K/Q/N/O).
- **ROZHODNUTÍ: ETAPA C = rozdělení monolitu `db.py` (~2090 ř., 67 metod) na doménová repozitáře.**

## Nejbližší úkol — STP-039 (ETAPA C vlna 1)
**Rozdělení `db.py` — extrakce `CaseRepository` + `FileRepository` + `AuditRepository`:**
1. Nové moduly `src/stopa/data/repositories/case_repository.py`, `file_repository.py`, `audit_repository.py`.
2. Přesun ~28 metod (case/source/custody, file/flags/marked, audit log/operations/integrity checkpoints).
3. `CaseDB` deleguje do repozitářů — facade zachován pro backward compat (žádná změna veřejného API).
4. Testy: existující suite musí zůstat zelená + nové testy repozitářů; ruff clean.

**Akceptační kritéria:** žádná změna veřejného API `CaseDB`, full suite **1742+ passed**, ruff clean, commit `refactor(data): ETAPA C vlna 1 — Case/File/Audit Repository`.

## Po STP-039
STP-040 (vlna 2: Artifact/Entity Repository ~23 metod) → STP-041 (vlna 3: facade úklid + audit, `db.py` < ~600 ř.).
