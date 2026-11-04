# STOPA — Checkpoint (latest)

**Datum:** 2026-11-04
**Úkol:** STP-038 — ETAPA C: volba směru + synchronizace roadmapy (rozdělení `db.py`)
**Oblast / priorita:** A (Core Architecture) / P1
**Stav:** DONE ★ **ETAPA C ZAHÁJENA**

## Co se stalo
- Audit reálného stavu všech oblastí A–Q v kódu (ne jen roadmapě).
- Synchronizace zastaralých „Nedokončeno" položek — mezitím dokončeno: E Timeline Intel 2.0 ✓ (STP-018), L report **20 sekcí** ✓ (STP-020), H PII redactor + governance ✓ (STP-019), J RBAC minimální ✓ (STP-022), K/Q STIX 2.1 + JSONL/XML ✓ (STP-023), N/O stream parsing + Processing Monitor ✓ (STP-021).
- **ROZHODNUTÍ: ETAPA C = oblast A — rozdělení monolitu `db.py` (~2090 ř., 67 metod) na doménová repozitáře** (nejvyšší zbývající priorita P1, největší technický dluh).

## Plán vln ETAPY C
| Vlna | Úkol | Obsah | Akceptační kritéria |
|---|---|---|---|
| 1 | STP-039 | `CaseRepository` + `FileRepository` + `AuditRepository` (~28 metod) | backward compat API, full suite zelená, ruff clean |
| 2 | STP-040 | `ArtifactRepository` + `EntityRepository` (~23 metod) | totéž |
| 3 | STP-041 | facade úklid + audit (`db.py` < ~600 ř.) | totéž + finální audit test |

## Metriky (bez změny — jen docs)
- Full suite: **1742 passed, 1 skipped** (~18s)
- Ruff: clean
- Coverage: covered **198 / 232 ★**, NOT_SUPPORTED **0**
- C3 registry: **76 parserů**

## Commity
- Feature (docs): viz `git log` — `docs(stp-038): ETAPA C volba směru + synchronizace roadmapy (db.py)`
- Předchozí HEAD: `a4307c8` (STP-037 docs)

## Nejbližší krok
**STP-039 — ETAPA C vlna 1:** extrakce `CaseRepository` + `FileRepository` + `AuditRepository` z `db.py`; `CaseDB` deleguje, facade zachován.
