# STOPA 2.1 — Executive Summary (auditní výstupy)

**Stav:** Release 2.0 GA, commit `4a3a867` = origin/main · suite **3652 passed / 1 skipped** · Ruff clean · schema v19
**Zdroj požadavků:** `docs/prompts/STOPA_2_1_MASTER_PROMPT.md` · **Plán:** `docs/ROADMAP_2_1.md` (detail s AK a velikostmi)

## Co audit prokázal (ověřeno v kódu, ne z dokumentace)

### Silné stránky
- **Clean Architecture drží:** doménová vrstva = čistá logika bez I/O; Pydantic v2 boundary modely; repository pattern s tenkou CaseDB facade.
- **Forenzní jádro je silnější než typické open-source workbench:** append-only `audit_log` s hash chainem (SQL triggery RAISE(IGNORE) proti UPDATE/DELETE), Ed25519 integrity checkpoints, Merkle case seals se snapshotem veřejného klíče, Reproducibility Engine (`analysis_operations`: verze parserů + config_hash + outputs_json → replay porovnání).
- **AI grounding už existuje:** `Finding` vyžaduje ≥1 Provenance (validator) a nese 5úrovňové `ConfidenceLevel` — AI domněnka se nedá prezentovat jako fakt bez označení.
- **3652 offline deterministických testů** + benchmark suite s noise guardem; volitelné extras (9 ks) s graceful degradation → základní workflow běží bez internetu i bez Rust extenze.

### Nalezená rizika (seřazeno podle dopadu)

| # | Nález | Závažnost | Důkaz | Oprava |
|---|---|---|---|---|
| 1 | **Plugin sandbox běží v host cwd** — neověřený plugin může tichě psát kamkoliv, kde byl `stopa` spuštěn; chybí CPU/fd/output limity | P0 (bezpečnost) | `cli.py:3318` posílá `workdir=None`; `plugin_loader.py::sandbox_exec` má jen RLIMIT_AS+timeout | ROADMAP P0-3 |
| 2 | **Dvojité frontend** — část funkcí (ATT&CK heat-mapa, Daubert) existuje jen v legacy static UI; React SPA je paralelní | P0 (údržba/UX) | `web/static/app.js` + `js/components/modules.js` vs. `frontend/src/` (build do `static/spa/`) | ROADMAP P0-6 |
| 3 | **God-files** — `cli.py` 4 433 ř., `web/app.py` 3 310 ř., `pipeline.py` ~1 532, `validation_registry.py` ~1 095; degradace maintainability | P1 (údržba) | `wc -l src/stopa/cli.py` atd. v `4a3a867` | ROADMAP P1-4 |
| 4 | **Provenance gap** — hash souborů bez času výpočtu; akvize bez nástroje+verze; odvozené artefakty bez explicitního parent linku (jen implicitní lineage_events) | P0 (doložitelnost) | `schema.py` tabulky `files`, `sources`, `custody_items`; `artifacts.provenance_json` existuje | ROADMAP P0-1 |
| 5 | **Pečetě: klíčová správa a cross-device verifikace chybí** — Ed25519 podpis se ověřuje jen v aplikaci; rotace/obnova klíče neřešena | P0 (důvěra) | `case_seals` tabulka + `domain/case_seal.py`; žádný CLI `verify-seal` | ROADMAP P0-2 |
| 6 | **Parser quality bez datového stavu** — ~78 parserů, validace existuje (Daubert F5.5, reparse C5), ale per-parser „validovaný? kdy? kolik testů?“ není evidováno a viditelné | P0/P1 (doložitelnost) | `validation_registry.py` bez validity-status pole; chybí `stopa parser-status` | ROADMAP P0-4 |
| 7 | **Graceful degradation = netestovaná plocha** — 9 optional extras × fallbacky; CI nainstaluje jen subset, cesta „bez X“ nemusí být pokryta | P1 (spolehlivost) | `pyproject.toml` extras; `ci.yml` bez matrix nad extras | ROADMAP P1-5 |
| 8 | **AI framework bez produkční robustnosti** — retry/backoff/jitter, token limity, prompt-injection ochrana a eval sada chybí | P1 (spolehlivost) | `intelligence/tool_agent.py` jednoduché volání LLM | ROADMAP P1-2 |
| 9 | **Single-process model** — LiveEventBus bez Redis, in-memory cache; multi-instance deploy nefunguje | P2 (škálování) | `web/app.py` event bus implementace | ROADMAP P2-1 |
| 10 | **i18n jen v React SPA** — legacy UI a CLI česky hardcodované | P2 (UX) | `frontend/src/i18n/` vs. `cli.py` výstupy | při P0-6 migraci |

## Prioritizace (upravená o zjištění auditu)

**P0 (kritické základy):** 1. Provenance hardening (migrace v20) · 2. Pečetě+klíčová správa · 3. Plugin sandbox hardening · 4. Validation Lab jádro · 5. Threat model · 6. Frontend parity mapa
**P1:** Parser Quality Framework plně · AI orchestrátor 2.0 · Evidence Graph · refactoring god-files · cross-platform CI · crash recovery · Assurance Center UI
**P2:** distribuované zpracování · centrální registr · timeline intelligence · investigation workspace · threat intel workspace · cross-case correlation · marketplace

## První implementační krok (ETAPA C)
Startujeme **P0-3 plugin sandbox hardening** — jediná P0 položka bez změny datového kontraktu (nejnižší riziko dle pravidla 9 master promptu): izolovaný workdir per run, RLIMIT_CPU+RLIMIT_NOFILE, output cap, síťová izolace pro Linux. Pak v pořadí P0-5 → P0-2 → P0-4 → P0-1 (migrace).
