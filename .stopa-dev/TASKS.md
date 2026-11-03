# STOPA — TASKS (centrální registr úkolů)

Stavy: BACKLOG | READY | IN_PROGRESS | TESTING | BLOCKED | DONE | PARTIAL | REJECTED | DEPRECATED
Formát ID: STP-NNN. Jeden úkol = jedna souvislá funkce. Velké funkce rozděleny na vlny.

---

## STP-001 — P0 Core C1: Evidence Model + Lineage
- **Oblast:** A (Core) | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Provenance každého nálezu — každý artifact/finding dohledatelný ke zdroji.
- **Dotčené moduly:** `domain/evidence_model.py`, `domain/lineage.py`
- **Akceptační kritéria:** lineage chain pro každý finding; testy zelené.
- **Testy:** `test_evidence_model.py` (14), `test_lineage.py` (12) — PASS
- **Dokončeno:** 2026-10 | Commit: `943753b`

## STP-002 — P0 Core C2: Integrity (SHA-256/MD5 + Ed25519)
- **Oblast:** A/M | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Hash integrity důkazů, Ed25519 podpisy exportů a reportů.
- **Dotčené moduly:** `domain/integrity.py`, `domain/hashing.py`
- **Testy:** `test_integrity.py` (22), `test_hashing.py` (7) — PASS
- **Dokončeno:** 2026-10 | Commit: `8b09071`

## STP-003 — P0 Core C3: Audit Log (hash chaining)
- **Oblast:** A/M | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Tamper-evidentní audit log s hash chainingem; každá operace dohledatelná.
- **Dotčené moduly:** `data/db.py` (audit tabulky), `domain/report.py`
- **Testy:** zahrnuto v plné sadě — PASS
- **Dokončeno:** 2026-10 | Commit: `a0e4577`

## STP-004 — P0 Core C4: Reproducibility Engine
- **Oblast:** A | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Každá analytická operace reprodukovatelná; exporty s manifestem.
- **Dotčené moduly:** `domain/reproducibility.py`, `domain/export.py`
- **Testy:** `test_reproducibility.py` (20) — PASS
- **Dokončeno:** 2026-10 | Commit: `a554a20`

## STP-005 — P0 Core C5: Export Engine (CSV/JSON + manifest)
- **Oblast:** K | **Priorita:** P0 | **Stav:** DONE
- **Popis:** CSV/JSON exporty artifactů/timeline/korelací s reprodukovatelným manifestem.
- **Dotčené moduly:** `domain/export.py`, `cli.py` (`stopa export`)
- **Testy:** zahrnuto v plné sadě — PASS
- **Dokončeno:** 2026-10 | Commit: `5b10a95`

## STP-006 — P0 Core C6/E13: Benchmark Engine + validační reporty
- **Oblast:** A/P | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Deterministické workloads, měření času a špičkové RAM; detekce regresí >20%;
  validační reporty per-artifact (parser ID+verze, status, confidence, provenance).
- **Dotčené moduly:** `domain/benchmark.py`, `data/benchmark_engine.py`
- **Testy:** `test_benchmark_engine.py` (18) — PASS
- **Dokončeno:** 2026-10 | Commit: `42ade02`

## STP-007 — P0 Intelligence I1: AI orchestrace
- **Oblast:** H | **Priorita:** P0 | **Stav:** DONE
- **Popis:** 5 deklarativních agentů (case/timeline/artifact/media/report analyst), Pydantic výstupy,
  auto/explicitní routing, fail-closed validace LLM výstupu + citace `[art:<id>]`. AI volitelná.
- **Dotčené moduly:** `intelligence/{__init__,agents,case_context,ai_orchestrator}.py`
- **Testy:** `test_intelligence.py` (25) — PASS
- **Dokončeno:** 2026-11 | Commit: `61f9a03`

## STP-008 — P0 Intelligence I2: Forensic RAG
- **Oblast:** H | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Tři znalostní vrstvy (Case/Technical/Knowledge), chunking markdown, FTS5 sanitizace,
  prompt injection ochrana `<untrusted_source>`, audit AI dotazů do `analysis_operations`.
- **Dotčené moduly:** `intelligence/rag.py`
- **Testy:** `test_rag.py` (30) — PASS
- **Dokončeno:** 2026-11 | Commit: `97cd4d6`

## STP-009 — P0 Intelligence I3: Entity Resolution 2.0
- **Oblast:** F | **Priorita:** P0 | **Stav:** DONE
- **Popis:** 4 confidence levels (confirmed/strong_candidate/possible/unverified) + backward compat
  mapping; normalizace platformních účtů (WhatsApp JID → E164, skype:/telegram:); nový druh entity
  `user_account`; merge candidates s důvody; časové rozmezí vztahů; schéma v10→v11 (idempotentní migrace).
- **Dotčené moduly:** `domain/entity_resolution.py`, `entities.py`, `correlation.py`, `data/db.py`,
  `web/app.py`, `cli.py`, `report.py`, `i18n.py`, `graph.js`
- **Testy:** `test_entity_resolution.py` (26) + aktualizace e4/e5/e10/reproducibility — PASS
- **Dokončeno:** 2026-11 | Commit: `2244d95`

## STP-010 — FÁZE 1: Kompletní technický audit
- **Oblast:** A (celá) | **Priorita:** P1 | **Stav:** DONE
- **Popis:** Přepis `docs/STOPA_TECHNICAL_AUDIT.md` na aktuální stav (commit `2244d95`, schema v11,
  819 testů); mapa architektury, funkční/neúplné moduly, technický dluh, cílová architektura, plán.
- **Dotčené moduly:** `docs/STOPA_TECHNICAL_AUDIT.md`
- **Testy:** baseline 819 passed — PASS
- **Dokončeno:** 2026-11 | Commit: `ad06f66`

## STP-011 — FÁZE 15: Coverage matrix CSV (centrální matice v kořeni)
- **Oblast:** D/P | **Priorita:** P1 | **Stav:** DONE
- **Popis:** `scripts/build_axiom_coverage.py` generuje `STOPA_COVERAGE_MATRIX.csv` (232 typů × 10 sloupců),
  deterministický výstup (SHA-256 diff ✓).
- **Dotčené moduly:** `scripts/build_axiom_coverage.py`, `STOPA_COVERAGE_MATRIX.csv`
- **Testy:** determinismus ověřen — PASS
- **Dokončeno:** 2026-11 | Commit: `ad06f66`

## STP-012 — DEV OS bootstrap: projektová paměť `.stopa-dev/`
- **Oblast:** P (QA) | **Priorita:** P1 | **Stav:** DONE
- **Popis:** Vytvořena složka `.stopa-dev/` se všemi povinnými dokumenty DEV OS (PROJECT_STATE,
  NEXT_ACTION, ROADMAP, TASKS, MODULE_MAP, FEATURE_REGISTRY, TEST_REGISTRY, DECISIONS, CHANGELOG, BLOCKERS)
  + checkpoint.
- **Dotčené moduly:** `.stopa-dev/*`
- **Testy:** konzistence s git/testy ověřena — PASS
- **Dokončeno:** 2026-11-03 | Commit: (tento commit)

## STP-013 — ETAPA B vlna 1a: email mbox/EML + WiFi WLAN XML
- **Oblast:** D | **Priorita:** P0 | **Stav:** DONE
- **Popis:** `email_mbox.py` (mbox/EML, hlavičky, MIME body) + `win_wlan.py` (WLAN profile XML,
  namespace-agnosticky). Registrace pipeline + C3.
- **Testy:** `test_email_mbox.py` (17), `test_win_wlan.py` (12) — PASS
- **Dokončeno:** 2026-11 | Commit: `afc49a0`

## STP-014 — ETAPA B vlna 1b: Scheduled Tasks XML + netstat/connstat text
- **Oblast:** D | **Priorita:** P0 | **Stav:** DONE
- **Popis:** `win_schedtask.py` (Task Scheduler XML, UTF-16 BOM) + `net_connections.py`
  (token-based parser Windows/Unix, IPv4/IPv6/wildcard). Registrace pipeline + C3.
- **Testy:** `test_win_schedtask.py` (11), `test_net_connections.py` (12) — PASS
- **Dokončeno:** 2026-11 | Commit: `afc49a0`

## STP-015 — ETAPA B vlna 1c: Clipboard registry + SID extraction
- **Oblast:** D | **Priorita:** P0 | **Stav:** DONE
- **Popis:** `win_clipboard.py` (NTUSER.DAT Clipboards, CF_* formáty) + `win_sids.py`
  (SAM/SECURITY Users + ProfileList). Sekundární registry průchody v `_extract_registry_all`.
- **Testy:** `test_win_clipboard.py` (12), `test_win_sids.py` (12) — PASS
- **Dokončeno:** 2026-11 | Commit: `afc49a0`

## STP-016 — ETAPA B vlna 2: Google lokální profily + scan text outputy
- **Oblast:** D | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Port zbývajících nejvyšší-hodnotových portable-local typů: Google SearchHistory/
  LocationHistory/LoginHistory/AccountInfo, CmdScan/FileScan text outputy, CurrentTabs, MSNArtifact.
- **Závislosti:** STP-013..015 (vzory parserů hotové)
- **Dotčené moduly:** `src/stopa/artifacts/*` (7 nových), `pipeline.py`, `validation_registry.py`,
  `scripts/build_axiom_coverage.py`
- **Akceptační kritéria:** každý typ = parser + detekce + registrace pipeline+C3 + testy;
  coverage covered count vzrostl; plná sada bez regresí.
- **Testovací požadavky:** syntetické fixtures, pattern `test_win_wlan.py`/`test_net_connections.py`.
- **Výsledek:** 7 nových parserů (`google_search_history`, `google_location_history`,
  `google_login_history`, `google_account_info`, `mem_scan`, `ddg_current_tabs`, `msn_messenger`) +
  71 testů; C3 registry 13 → **20 parserů**; coverage covered **33 → 42** (+9 typů, deterministická);
  full suite **966 passed, 1 skipped**, ruff clean.
- **Dokončeno:** 2026-11-03 | Commit: (vlna 2)

## STP-017 — ETAPA B vlna 3: legacy mobile/messenger SQLite typy
- **Oblast:** D | **Priorita:** P1 | **Stav:** BACKLOG
- **Popis:** Kik, MailRu (Chat/Contact/Group), Bebo, Chatroulette, Limewire/Limerunner/Luckywire —
  SQLite-based legacy messenger extraktory.
- **Závislosti:** STP-016

## STP-018 — Timeline Intelligence 2.0
- **Oblast:** E | **Priorita:** P2 | **Stav:** BACKLOG
- **Popis:** Rozpory v timeline, duplikáty, přesnost timestampů (source vs derived).
- **Závislosti:** STP-016

## STP-019 — AI governance + PII redaktor
- **Oblast:** H/M | **Priorita:** P2 | **Stav:** BACKLOG
- **Popis:** `STOPA_AI_GOVERNANCE.md` (kořen), PII redaktor před LLM inference, explicitní oddělení případů.
- **Závislosti:** —

## STP-020 — Report engine: 9 → 20 sekcí
- **Oblast:** L | **Priorita:** P1 | **Stav:** BACKLOG
- **Popis:** Titulní strana, metodika, nástroje+verze, omezení, závěr + další sekce.
- **Závislosti:** —

## STP-021 — Performance: stream parsing velkých E01 + progress monitoring
- **Oblast:** N/O | **Priorita:** P2 | **Stav:** BACKLOG
- **Popis:** Stream parsing (snížení RAM peaku), web Processing Monitor.
- **Závislosti:** —

## STP-022 — Security: SHA-512 + RBAC minimální + pip-audit CI
- **Oblast:** M | **Priorita:** P2 | **Stav:** BACKLOG
- **Popis:** SHA-512 v integrity vrstvě, minimální RBAC (actor povinný), pip-audit do CI.
- **Závislosti:** —

## STP-023 — Export: JSONL/XML/STIX formáty
- **Oblast:** K/Q | **Priorita:** P3 | **Stav:** BACKLOG
- **Popis:** Rozšíření export engine o JSONL, XML, STIX/UCO.
- **Závislosti:** —

## STP-024 — DEV OS: doplnění povinných polí registrů (STP-012b)
- **Oblast:** P (QA) | **Priorita:** P1 | **Stav:** DONE
- **Popis:** `FEATURE_REGISTRY.md` +sloupce Popis/Verze; `TEST_REGISTRY.md` +pole Datum/Verze
  aplikace/Případná chyba/Odkaz na protokol; `DECISIONS.md` +pole Dotčené moduly u všech ADR.
- **Dotčené moduly:** `.stopa-dev/*`
- **Testy:** konzistence s promptem DEV OS ověřena — PASS
- **Dokončeno:** 2026-11-03 | Commit: `19a458d`

## STP-025 — Kořenové výstupy MASTER DEVELOPMENT PROMPT (STP-012c)
- **Oblast:** P (QA) | **Priorita:** P1 | **Stav:** DONE
- **Popis:** Vytvořeny všechny povinné kořenové soubory: `STOPA_TECHNICAL_AUDIT.md`,
  `STOPA_ARCHITECTURE.md`, `STOPA_ROADMAP.md` (A–Q), `STOPA_CHANGELOG.md` (autoritativní kopie,
  pointer v docs/), `STOPA_TEST_REPORT.md` (tabulka 53 souborů / 896 testů doloženo collect-only),
  `STOPA_SECURITY_REPORT.md` (T1–T10), `STOPA_AI_GOVERNANCE.md` (nový, F-044),
  `STOPA_VALIDATION_REPORT.md` (C3 registry 13 parserů živě ověřeno). `STOPA_COVERAGE_MATRIX.csv`
  už v kořeni existoval.
- **Dotčené moduly:** kořen projektu, `.stopa-dev/*`, `docs/STOPA_CHANGELOG.md`
- **Testy:** ruff clean; testy nedotčeny (895 passed, 1 skipped) — PASS
- **Dokončeno:** 2026-11-03 | Commit: (tento commit)
