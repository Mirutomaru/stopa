# STOPA — NEXT ACTION

## Aktuální stav (2026-11-06)
**STP-049 + STP-050 DOKONČENY ★★** — ETAPA H (AI grounding) a oblast I+O Validation Center UI hotové. Poslední commit `0b761ab` (feat(web): Validation Center UI — C3 registry + C6 report v SPA).

## Hotové
- **STP-050:** Validation Center v GUI — endpointy `GET /api/cases/{id}/validation` (C6 `build_validation_report`: total_artifacts, coverage per-parser, validační statusy, per-artifact řádky s parser ID+verze/confidence/provenance) + `GET /api/validation/registry` (C3 registry); SPA modul `mod-validation` (`js/components/validation.js`, statistické karty, coverage bar, tabulky). Full suite **1901 passed, 1 skipped** (+10), ruff clean.
- **STP-049:** AI grounding — `domain/ai_grounding.py` (čistá logika: `extract_claims()` + `ground_answer()`, kategorie rozporu mismatch_date/mismatch_type/unverified_claim, `.verified_citations`); zapojení do všech 3 AI režimů web endpointu (pole `grounding`), GUI ⚠ štítky citací + findings panel; dokumentace `docs/STOPA_AI_ARCHITECTURE.md` §1.1. Full suite **1891 passed, 1 skipped** (+41), ruff clean. Commit `1c107ba`.
- **STP-048:** sandbox E2E testy + corrupt-file regression EVTX/LNK + dokumentace `docs/STOPA_SANDBOX.md` (ETAPA M uzavřena).

## Další krok — výběr oblasti (pořadí podle priority)
1. **G File Intelligence** — souborová inteligence (typy, relace, timeline enrichment).
2. **J Case Management 2.0** — rozšíření RBAC.
3. **K Export Engine** — Plaso formát (volitelné).
4. **O Audit Center modul** — UI pro audit trail (doplní oblast O po Validation Centeru).
5. **Q Interoperability** — UCO/STIX rozšíření.

## Potvrzené konvence
- Jeden úkol → implementace → test → dokumentace → checkpoint → další úkol.
- Domain = čistá logika bez IO; IO jen v `data/` a entrypointech.
- Před commitem: full suite + ruff clean + DEV OS synchronizace (TASKS/PROJECT_STATE/NEXT_ACTION/FEATURE_REGISTRY/TEST_REGISTRY/CHANGELOG/checkpoint).
