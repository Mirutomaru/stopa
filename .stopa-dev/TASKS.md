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
- **Dokončeno:** 2026-11-03 | Commit: `e0c34b3`

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
- **Oblast:** D | **Priorita:** P1 | **Stav:** DONE
- **Popis:** Kik, MailRu (Chat/Contact/Group), Bebo, Chatroulette, Limewire/Limerunner/Luckywire —
  SQLite-based legacy messenger extraktory.
- **Závislosti:** STP-016
- **Dotčené moduly:** `src/stopa/artifacts/*` (5 nových: `kik_messenger`, `mailru_agent`,
  `bebo_chat`, `chatroulette`, `limewire_p2p`), `pipeline.py` (importy + NAME_BASED_EXTRACTORS
  +4 + `_name_based_match` +4), `sqlite_extract.py` (Kik branch do dispatch chainu),
  `validation_registry.py` (+4 záznamy → **24 parserů**), `scripts/build_axiom_coverage.py`,
  `STOPA_COVERAGE_MATRIX.csv`.
- **Výsledek:** 5 nových parserů pokrývající **9 AXIOM typů** (KikLocalUserExtractor,
  MailRuChat/Contact/GroupArtifact, BeboArtifact, ChatrouletteArtifact, Limewire/Limerunner/
  LuckywireArtifact) + **75 testů**; C3 registry 20 → **24 parserů**; coverage covered
  **42 → 51** (+9 typů z 232, deterministická SHA-256 ✓); full suite **1041 passed, 1 skipped**,
  ruff clean. Kik přes SQLite dispatch chain (iOS `ZKIK*` / Android `users+messages`, aliasy
  sloupců, epoch s/ms); ostatní name-based s konzervativní JSON detekcí.
- **Dokončeno:** 2026-11-03 | Commit: (vlna 3)

## STP-018 — Timeline Intelligence 2.0
- **Oblast:** E | **Priorita:** P2 | **Stav:** DONE
- **Popis:** Rozpory v timeline, duplikáty napříč zdroji, přesnost timestampů (source vs derived).
- **Závislosti:** STP-016
- **Dotčené moduly:** `src/stopa/domain/timeline_intel.py` (nový čistý modul bez IO),
  `data/db.py` (SCHEMA_VERSION 11→**12**, nové sloupce `timeline_events`, migrace
  `_migrate_timeline_intel()`, metody `set/clear_timeline_intel_groups()`),
  `models.py` (`Artifact.ts_origin`), `pipeline.py` (insert subject_values+ts_origin,
  post-pass `run_timeline_intel()`), `cli.py` (`add` post-pass + `timeline --intel [--window N]`),
  `web/app.py` (POST `/api/cases/{id}/timeline/intel`), `domain/report.py` (podsekce 8.1),
  `domain/i18n.py`, `presentation/case_report.py`, `domain/export.py`.
- **Výsledek:** tři analytické vrstvy — rozpory `concurrent_activity` (union-find,
  deterministické group ID), duplikáty napříč zdroji `cross_source_duplicate` (provenience
  všech výskytů) a timestamp provenance (`ts_origin` + klasifikace přesnosti); schéma v12
  (idempotentní migrace bez ztráty dat); post-pass po ingestu + explicitní CLI/web; report
  podsekce Timeline Intelligence 2.0; export rozšířen o nové sloupce; **32 nových testů**
  (`tests/test_timeline_intel.py`); full suite **1073 passed, 1 skipped**, ruff clean.
- **Dokončeno:** 2026-11-03 | Commit: `cd5aa25`

## STP-019 — AI governance + PII redaktor
- **Oblast:** H/M | **Priorita:** P2 | **Stav:** DONE
- **Popis:** `STOPA_AI_GOVERNANCE.md` (kořen), PII redaktor před LLM inference, explicitní oddělení případů.
- **Závislosti:** —
- **Dotčené moduly:** `src/stopa/domain/pii_redaction.py` (nový), `intelligence/ai_orchestrator.py`,
  `domain/ai_assistant.py`, `web/app.py`, `cli.py`, `STOPA_AI_GOVERNANCE.md`.
- **Akceptační kritéria:** PII redaktor maskuje e-mail/telefon/JID/handle v LLM promptu (volitelně);
  governance politika dokumentovaná + auditovatelná (verze modelu v audit logu); ruff clean;
  plná sada bez regresí.
- **Výsledek:** `domain/pii_redaction.py` — deterministický PII redaktor (bez I/O) maskuje telefony,
  e-maily, WhatsApp JID a platformní handle ve všech prompt messages PŘED odesláním do LLM;
  stavební kameny opakovány z `entities.py`/`entity_resolution.py`; priorita překryvu
  JID > e-mail > handle > telefon; vrací seznam detekcí pro audit. I1 orchestrace:
  `build_prompt()`/`orchestrate()` + parametr `redact_pii=True` (default ON, fail-safe);
  auditní SHA-256 nad redigovaným textem. E11 asistent: všechny tři prompt buildery maskují PII.
  Audit E11 modelových volání: dříve jen I1 — teď zapisují `ai_query` záznam (model name +
  SHA-256 promptu + citace, agent `e11:<režim>`) i všechny tři režimy E11. Settings toggle
  `ai_redact_pii` (default ON): GET/PUT `/api/settings`, CLI čte `settings.json`.
  **23 nových testů** (`tests/test_pii_redaction.py`); full suite **1110 passed, 1 skipped**, ruff clean.
- **Dokončeno:** 2026-11-03 | Commit: `6d74ab3`

## STP-020 — Report engine: 9 → 20 sekcí
- **Oblast:** L | **Priorita:** P1 | **Stav:** DONE
- **Popis:** Titulní strana, metodika, nástroje+verze, omezení, závěr + další sekce.
- **Závislosti:** —
- **Dotčené moduly:** `src/stopa/domain/report.py` (SECTIONS + build_html),
  `src/stopa/presentation/case_report.py` (stavba ReportData), `domain/i18n.py`,
  případně `web/app.py` (report endpoint).
- **Akceptační kritéria:** report obsahuje nové sekce (titulní strana, metodika,
  nástroje+verze, omezení, závěr); existující 9 sekcí se nemění (backward compat);
  i18n cs/en; testy na syntetickém případě; plná sada bez regresí.
- **Výsledek:** report rozšířen z 9 na **20 sekcí** — titulní strana (cover),
  10 Metodika analýzy, 11 Nástroje a verze (env_snapshot C5 + E12 diagnostics),
  12 Omezení analýzy, 13 Závěr, 14 Provenience timestampů, 15 Evidence lineage,
  16 Integrity Ed25519, 17 Rejstřík entit, 18 Příloha A (validace parserů C3),
  19 Příloha B (reprodukční prostředí C5), 20 Příloha C (rozložení důvěryhodnosti);
  backward compat sekcí 1–9 zachována; ~60 nových i18n klíčů cs/en; defenzivní
  naplnění z case DB; **14 nových testů** (`tests/test_report.py`, třída
  `TestStp020Sections`); full suite **1087 passed, 1 skipped**, ruff clean.
- **Dokončeno:** 2026-11-03 | Commit: `7360bab`

## STP-021 — Performance: stream parsing velkých E01 + progress monitoring
- **Oblast:** N/O | **Priorita:** P2 | **Stav:** DONE
- **Popis:** Stream parsing (snížení RAM peaku), web Processing Monitor.
- **Závislosti:** —
- **Dokončeno:** 2026-11-03 | Commit: ``e0c34b3``
- **Detaily:** `stream_to_raw()` chunked 1 MiB (RAM peak z GB na ~1 MiB), byte-level progress v
  `process_disk_image(extract_progress=)`, web job registry + `GET /api/cases/{id}/processing`
  + async ingest (`SourceIn.background`, default sync = backward compat), GUI checkbox „pozadí"
  + polling status baru. **7 nových testů** (`tests/test_stp021.py`).

## STP-022 — Security: SHA-512 + RBAC minimální + pip-audit CI
- **Oblast:** M | **Priorita:** P2 | **Stav:** DONE
- **Popis:** SHA-512 v integrity vrstvě, minimální RBAC (actor povinný), pip-audit do CI.
- **Závislosti:** —
- **Dokončeno:** 2026-11-03 | Commit: ``9707cd8``
- **Detaily:** `compute_audit_hash/verify_chain(algo="sha256|sha512")` + per-algorithm GENESIS;
  manifesty `build_manifest(include_sha512=True)` opt-in (backward compat); FORENSIC profil
  počítá SHA-512 v jednom průchodu (`ProcessingProfile.compute_sha512`, sloupec `files.sha512`
  + migrace, dedupe + `search_by_hash()` přes SHA-256/SHA-512/MD5); report CoC manifest
  +SHA-512 sloupec (jen když existuje); nový `domain/rbac.py` (`normalize_actor`,
  `require_actor`+`ActorError`, `resolve_actor`) — `log_operation(strict=)` atribuce
  explicitní actor > case examiner > None; CI job `security` s pip-audit. **32 nových testů**
  (`tests/test_stp022.py`).

## STP-023 — Export: JSONL/XML/STIX formáty
- **Oblast:** K/Q | **Priorita:** P3 | **Stav:** DONE
- **Popis:** Rozšíření export engine o JSONL, XML, STIX 2.1 (UCO mapping zbývá jako volitelné rozšíření).
- **Závislosti:** —
- **Dokončeno:** 2026-11-03 | Commit: ``210c370``
- **Detaily:** `domain/export.py` +`to_jsonl` (1 objekt/řádek, streamovací), `to_xml`
  (deterministický ElementTree, UTF-8, kořen `stopa_<dataset>`), `to_stix_bundle`
  (STIX 2.1 bundle — artefakty → file/message objekty + `x-stopa` rozšíření, ostatní
  datasety → `x-stopa-record`; deterministická UUIDv5 ID ze STOPA namespace pro C4
  reprodukovatelnost); CLI `stopa export --format csv|json|jsonl|xml|stix`. **17 nových
  testů** (`tests/test_stp023.py`).

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
- **Dokončeno:** 2026-11-03 | Commit: `e0c34b3`

## STP-026 — ETAPA B vlna 4: portable-local AXIOM porty (6 parserů)
- **Oblast:** D (Artifact Engine) | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Port 6 AXIOM extraktorů do čistého Pythonu — DuckDuckGo cookies, DDG allowlisted
  websites, OpenOffice/LibreOffice Base (.odb), iOS parked car locations, iOS voicemail,
  Windows UserAssist MRU. Coverage matice flip 5 přímých typů NOT_SUPPORTED → SUPPORTED.
- **Závislosti:** pipeline dispatch + C3 registry (sdílené záznamy `sqlite`/`registry_hive`)
- **Dotčené moduly:** `src/stopa/artifacts/{ddg_cookies,allowlisted_websites,openoffice_base,parked_car_locations,ios_voicemail,win_userassist}.py` (nové), `sqlite_extract.py`, `pipeline.py`, `domain/validation_registry.py`, `scripts/build_axiom_coverage.py`, `tests/test_w4_parsers.py` (nový)
- **Testy:** 33 nových testů zelených (`tests/test_w4_parsers.py`); full suite **1199 passed, 1 skipped** (baseline 1166 + 33); ruff clean — PASS
- **Dokončeno:** 2026-11-04 | Commit: ``cd932e1``

## STP-027 — ETAPA B vlna 5: Google Takeout rodina + Samsung voice (6 parserů / 12 AXIOM typů)
- **Oblast:** D (Artifact Engine) | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Port 12 AXIOM extraktorů do čistého Pythonu — Google Aggregated Activities +
  Identity Sessions, Google Maps Activity (semantic location history), Google Chat rodina
  (Chat/Hangouts/PlusChat/Talk sdílený Takeout JSON parser), Google Account metadata
  (change history/devices/export summary), Drive Activity, Samsung Voice Recording.
  Coverage matice flip 12 přímých typů NOT_SUPPORTED → SUPPORTED (**56 → 68 / 232**).
- **Závislosti:** pipeline dispatch (name-based — specifické detekce PŘED obecnějšími vlna-2 Google) + C3 registry (sdílený `sqlite` záznam rozšířen o Samsung)
- **Dotčené moduly:** `src/stopa/artifacts/{google_aggregated_activities,google_maps_activity,google_chat_family,google_account_meta,drive_activity,samsung_voice_recording}.py` (nové), `sqlite_extract.py`, `pipeline.py`, `domain/validation_registry.py`, `scripts/build_axiom_coverage.py`, `tests/test_w5_parsers.py` (nový)
- **Testy:** 43 nových testů zelených (`tests/test_w5_parsers.py`); full suite **1242 passed, 1 skipped** (baseline 1199 + 43); ruff clean; `build_registry()` = **34 parserů** — PASS
- **Dokončeno:** 2026-11-04 | Commit: ```b786064```

## STP-028 — ETAPA B vlna 6: Google local profile/takeout + přílohy (4 parsery / 4 AXIOM typy)
- **Oblast:** D (Artifact Engine) | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Port 4 AXIOM extraktorů do čistého Pythonu — Google Photos (Takeout/warrant JSON, photoTakenTime/geoData E7), Google Mail Message Information (Gmail warrant return JSON, threadId/internalDate µs), Google Bar (Chrome History DB tabulka `search_terms` — omnibox dotazy), Attachment Extractor (MIME/RFC822 přílohy → email_attachment artifacty). Coverage matice flip 4 přímých typů NOT_SUPPORTED → SUPPORTED (**68 → 72 / 232**); portable-local **4 → 0** ★.
- **Závislosti:** pipeline dispatch (name-based photos/mail_info + bonus hooky GoogleBar v `_extract_chrome_history` a AttachmentExtractor v `email_mbox`) + C3 registry (nové záznamy google_photos/google_mail_info/attachment_extractor; sdílené sqlite/email_mbox rozšířeny)
- **Dotčené moduly:** `src/stopa/artifacts/{google_photos,google_mail_info,google_bar,attachment_extractor}.py`, `pipeline.py`, `sqlite_extract.py`, `email_mbox.py`, `validation_registry.py`, `scripts/build_axiom_coverage.py`
- **Testy:** 37 nových testů zelených (`tests/test_w6_parsers.py`); full suite **1279 passed, 1 skipped** (baseline 1242 + 37); ruff clean; `build_registry()` = **36 parserů** (předtím 34)
- **Dokončeno:** 2026-11-04 | Commit: ```9ffde5b```

## STP-029 — ETAPA B vlna 7: Chrome Bookmarks/History/Autofill + Contacts + Skype WR (5 parserů / 12 AXIOM typů)
- **Oblast:** D (Artifact Engine) | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Port 12 cloud-export AXIOM typů do čistého Pythonu — Google Chrome Bookmarks (Bookmarks JSON, rekurzivní walk `roots`, date_added µs/1601), Google Chrome History Warrant Return (visit_time µs/1601), Google Contacts Warrant Return (Takeout/warrant JSON + People API fallback), Google Chrome Autofill/Contact Info (name/email/adresa), Skype Warrant Return (4 subtypy s auto-detekcí: account/chat/connection/contacts, composetime ISO 8601 i epoch ms). Coverage matice flip 12 typů NOT_SUPPORTED → SUPPORTED (**72 → 84 / 232**); cloud-export **111 → 99**.
- **Závislosti:** pipeline dispatch (name-based 5 parserů, specifické detekce PŘED obecnějšími Google/Skype) + C3 registry (nové záznamy chrome_bookmarks/chrome_history_wr/contacts_wr/chrome_autofill/skype_warrant_return)
- **Dotčené moduly:** `src/stopa/artifacts/{google_chrome_bookmarks,google_chrome_history_wr,google_contacts_wr,google_chrome_autofill,skype_warrant_return}.py`, `pipeline.py`, `validation_registry.py`, `scripts/build_axiom_coverage.py`
- **Testy:** 39 nových testů zelených (`tests/test_w7_parsers.py`); full suite **1318 passed, 1 skipped** (baseline 1279 + 39); ruff clean; `build_registry()` = **41 parserů** (předtím 36)
- **Dokončeno:** 2026-11-04 | Commit: ```5e47850```

## STP-030 — ETAPA B vlna 8: Chrome prefs/sync + cloud Drive soubory + Google Voice WR + Windows drivers (4 parsery / 16 AXIOM typů)
- **Oblast:** D (Artifact Engine) | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Port 16 cloud-export/mem AXIOM typů do čistého Pythonu — Google Chrome Preferences (extensions.settings → rozšíření s manifest name/version, default_search_provider_data + custom search engines, sync.data_type_enabled), Cloud Drive soubory (Google/OneDrive/Apple Takeout/warrant JSON; název/velikost/checksum/MIME/čas ISO i epoch; provider auto-detekce z markerů), Google Voice Warrant Return (4 subtypy s auto-detekcí: SMS texty/hlasové schránky/kontakty/předplatitel, timestampMsInEpoch → unix s), Windows Drivers (paměťový dump; baseAddress normalizace na hex, nesignovaný driver → anomaly flag `unsigned_driver`). Coverage matice flip 16 typů NOT_SUPPORTED → SUPPORTED (**84 → 100 / 232** ★ první stovka); cloud-export **99 → 84**, memory **15 → 14**.
- **Závislosti:** pipeline dispatch (name-based 4 parsery) + C3 registry (nové záznamy chrome_preferences/cloud_drive_files/google_voice_wr/win_drivers) + **nový mechanismus**: `_extract_artifacts_for()` retry name-based matche na celé cestě pro Takeout soubory se generic názvy (`Drive/Files.json`, `Voice/Texts.json` — klíčové slovo v rodičovské složce, ne v basename; parsery defenzivní → cizí soubory projdou bez artifactů)
- **Dotčené moduly:** `src/stopa/artifacts/{chrome_preferences,cloud_drive_files,google_voice_wr,win_drivers}.py`, `pipeline.py` (importy + NAME_BASED_EXTRACTORS + dispatch + path retry), `validation_registry.py`, `scripts/build_axiom_coverage.py`
- **Testy:** 32 nových testů zelených (`tests/test_w8_parsers.py`); full suite **1350 passed, 1 skipped** (baseline 1318 + 32); ruff clean; `build_registry()` = **45 parserů** (předtím 41)
- **Dokončeno:** 2026-11-04 | Commit: ```1a3e007```

### STP-031 — ETAPA B vlna 9: memory forensics (procesy/spojení/handlery/moduly/hooks)
- **Oblast:** D (Artifact Engine) | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Port 14 memory AXIOM typů (live forensics / paměťový dump) do čistého Pythonu — Memory Processes (seznam procesů pid/name/ppid/cmdline/threads/user; PsxView subtyp: EPROCESS vs PEB mismatch → anomaly flag `psxview_mismatch`), Memory Network Connections (síťová spojení proto/localAddress/remoteAddress/state, uppercase normalizace), Memory Handles (otevřené handlery, handle value hex normalizace int/decimal/hex tolerantně), Memory Modules (načtené moduly baseAddress/size/inLdrList; Malfind subtyp: modul v paměti ne v LDR listu → anomaly flag `hidden_module` / DLL injection), Memory API Hooks & Callbacks (hooky/callback funkce apiFunction/callbackAddress/hookType, adresa hex normalizace). Coverage matice flip 14 typů NOT_SUPPORTED → SUPPORTED (**100 → 114 / 232**); memory kategorie **vyzerovala 14 → 0 ★**.
- **Závislosti:** pipeline dispatch (name-based 5 parserů, **PŘED netstatem** — sdílená klíčová slova `connections`/`sockets`) + C3 registry (nové záznamy mem_processes/mem_network/mem_handles/mem_modules/mem_hooks)
- **Dotčené moduly:** `src/stopa/artifacts/{mem_processes,mem_network,mem_handles,mem_modules,mem_hooks}.py`, `pipeline.py` (importy + NAME_BASED_EXTRACTORS + dispatch), `validation_registry.py`, `scripts/build_axiom_coverage.py`
- **Testy:** 35 nových testů zelených (`tests/test_w9_parsers.py`); full suite **1385 passed, 1 skipped** (baseline 1350 + 35); ruff clean; `build_registry()` = **50 parserů** (předtím 45)
- **Dokončeno:** 2026-11-04 | Commit: ```4747738```


### STP-032 — ETAPA B vlna 10: cloud SNS exporty (Instagram/Snapchat warrant return)
- **Oblast:** D (Artifact Engine) | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Port 20 cloud SNS AXIOM typů do čistého Pythonu — Instagram Direct Messages (DM konverzace participants/messages, tolerantní klíče sender/from + text/body; sdílená média → `message_type=share` + media_url), Instagram Posts/Media/Stories/Comments (`sns_post`/`sns_comment`, stories detekce `is_story=True`), Instagram Account Actions/History/Followers (akce účtu login/password/device/IP → `event_log_entry`; followery/following → `contact` s `mimetype=sns:instagram`), Snapchat Warrant Return (zprávy WR + skupinové chaty, přátelé → contact sns:snapchat:user, geolokace → location_data, IP historie → network_connection, info o účtu; auto-detekce subtypu podle obsahu). Coverage matice flip 20 typů NOT_SUPPORTED → SUPPORTED (**114 → 134 / 232**); cloud-export kategorie **84 → 64** (největší jednorázový skok v ETAPA B).
- **Závislosti:** pipeline dispatch — **nový `_sns_prepass()` na celé cestě PŘED basename chainem** (generic basenames `photos.json`/`messages.json` kolidují s Google detektory, které dostávají jen `name`; account detektor PŘED posts — „AccountHistory" obsahuje substring „stor(y)") + C3 registry (nové záznamy instagram_messages/instagram_posts/instagram_account/snapchat_wr)
- **Dotčené moduly:** `src/stopa/artifacts/{instagram_messages,instagram_posts,instagram_account,snapchat_wr}.py`, `pipeline.py` (importy + `_sns_prepass()`), `validation_registry.py`, `scripts/build_axiom_coverage.py`
- **Testy:** 81 nových testů zelených (`tests/test_w10_parsers.py`); full suite **1466 passed, 1 skipped** (baseline 1385 + 81); ruff clean; `build_registry()` = **54 parserů** (předtím 50)
- **Dokončeno:** 2026-11-04 | Commit: ```da83a6f```

### STP-033 — ETAPA B vlna 11: cloud SNS exporty (Twitter/X + Facebook warrant return)
- **Oblast:** D (Artifact Engine) | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Port 13 cloud SNS AXIOM typů do čistého Pythonu — Twitter/X Posts (příspěvky author/text/created_at, tolerantní klíče tweet_id/from_user/body/date; retweety a odpovědi → `post_type`), Twitter/X Direct Messages (DM konverzace sender/recipient/text/timestamp; konverzační formát participants/messages i plošný), Twitter/X Users (uživatelé + sociální graf screen_name/name/followers_count; vlastní účet → relationship=account, sekce followers/following → follower/following), Facebook Warrant Return (Messenger zprávy konverzace i flat, přátelé → contact sns:facebook, timeline příspěvky → sns_post post_type=timeline, info o profilu → contact relationship=account; auto-detekce sekcí podle struktury payloadu). Coverage matice flip 13 typů NOT_SUPPORTED → SUPPORTED (**134 → 147 / 232**); cloud-export kategorie **64 → 51**.
- **Závislosti:** pipeline dispatch — `_sns_prepass()` rozšířen o 4 nové detektory (twitter_posts/twitter_messages/twitter_users/facebook_wr) bez kolizí s Instagram/Snapchat ani Google detektory + C3 registry (nové záznamy twitter_posts/twitter_messages/twitter_users/facebook_wr)
- **Dotčené moduly:** `src/stopa/artifacts/{twitter_posts,twitter_messages,twitter_users,facebook_wr}.py`, `pipeline.py` (importy + `_sns_prepass()`), `validation_registry.py`, `scripts/build_axiom_coverage.py`
- **Testy:** 87 nových testů zelených (`tests/test_w11_parsers.py`); full suite **1553 passed, 1 skipped** (baseline 1466 + 87); ruff clean; `build_registry()` = **58 parserů** (předtím 54)
- **Dokončeno:** 2026-11-04 | Commit: ```bea2a25```

### STP-034 — ETAPA B vlna 12: cloud-export Microsoft + Amazon (8 parserů / 12 AXIOM typů)
- **Oblast:** D (Artifact Engine) | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Port 12 cloud-export AXIOM typů do čistého Pythonu — celá Microsoft rodina: Graph/Outlook kontakty (`contact`, tolerantní klíče, vlastní účet → relationship=account), Outlook mail PST export (`email_message`, konverzační i flat formát), Teams konverzace/zprávy (`chat_message`), Teams týmy + členové (`contact` sns:microsoft:teams, role owner/member), Outlook kalendář události (`calendar_event`); SharePoint Warrant Return (strany → `web_page`, dokumenty → `document`, auto-detekce kind); Amazon rodina: CloudTrail API akce (`event_log_entry`, explicitní isinstance fallback pro userIdentity), EC2 instance + S3 objekty (`network_connection`/`file_metadata`, union detekce podle struktury). Coverage matice flip 12 typů NOT_SUPPORTED → SUPPORTED (**147 → 159 / 232**); cloud-export kategorie **51 → 39**.
- **Závislosti:** pipeline dispatch — `_sns_prepass()` rozšířen o 8 MS+Amazon detektorů (specifické PŘED obecnými, conversations PŘED teams; bez kolizí s Google contacts ani Twitter/SNS) + C3 registry (nové záznamy ms_contacts/ms_mail_pst/ms_teams_conversations/ms_teams_teams/ms_outlook_calendar/sharepoint_wr/amazon_cloudtrail/amazon_ec2_s3)
- **Dotčené moduly:** `src/stopa/artifacts/{ms_contacts,ms_mail_pst,ms_teams_conversations,ms_teams_teams,ms_outlook_calendar,sharepoint_wr,amazon_cloudtrail,amazon_ec2_s3}.py`, `pipeline.py` (importy + NAME_BASED_EXTRACTORS + `_sns_prepass()`), `validation_registry.py`, `scripts/build_axiom_coverage.py`
- **Testy:** 73 nových testů zelených (`tests/test_w12_parsers.py`); full suite **1626 passed, 1 skipped** (baseline 1553 + 73); ruff clean; `build_registry()` = **66 parserů** (předtím 58)
- **Dokončeno:** 2026-11-04 | Commit: ```47e7103```

### STP-035 — ETAPA B vlna 13: cloud-export Google II + Box/Dropbox/Mega (4 nové parsery / 9 typů + 11 čistých flipů)
- **Oblast:** D (Artifact Engine) | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Port 9 cloud-export AXIOM typů do čistého Pythonu — Google Calendar Events WR/Takeout (`calendar_event`, tolerantní klíče summary/subject, start.dateTime/date, organizer.displayName PŘED email), Google Keep Notes + Tasks (`document_metadata` kind=keep_note|task, auto-detekce podle klíčů), Box Cloud soubory/složky/enterprise+audit eventy (`document_metadata` kind=file|folder|comment|event), Dropbox + Mega položky (provider auto-detekce — Dropbox API klíče path_lower/bytes/is_dir PŘED Mega size/type, hint z cesty). **11 čistých flipů bez nového kódu** (existující parsery už typy pokrývaly: iMessage cloud→imessage_cloud, Google Photos×2→google_photos, Gmail Messages WR→google_mail_info, Chat/ChatSpaces/Chats/Hangouts→google_chat_family, Google Activity→aggregated_activities, Semantic Location History activity_segment+place_visit→maps_activity). Coverage matice flip 20 typů NOT_SUPPORTED → SUPPORTED (**159 → 179 / 232**); cloud-export kategorie **39 → 19**.
- **Závislosti:** pipeline dispatch — `_sns_prepass()` rozšířen o vlnu 13 detektory (calendar PŘED keep; box/dropbox/mega dle markery; specifické PŘED obecnými) + C3 registry (nové záznamy google_calendar_events/google_keep_tasks/box_cloud/dropbox_mega)
- **Dotčené moduly:** `src/stopa/artifacts/{google_calendar_events,google_keep_tasks,box_cloud,dropbox_mega}.py`, `pipeline.py` (importy + NAME_BASED_EXTRACTORS + `_sns_prepass()`), `validation_registry.py`, `scripts/build_axiom_coverage.py`, `tests/test_w12_parsers.py` (robustní registry count)
- **Testy:** 45 nových testů zelených (`tests/test_w13_parsers.py`); full suite **1671 passed, 1 skipped** (baseline 1626 + 45); ruff clean; `build_registry()` = **70 parserů** (předtím 66)
- **Dokončeno:** 2026-11-04 | Commit: ```31bceb2```

### STP-036 — ETAPA B vlna 14: dokončení cloud-export kategorie (6 nových parserů / 19 typů → NOT_SUPPORTED celkem 0 ★)
- **Oblast:** D (Artifact Engine) | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Port posledních 19 cloud-export AXIOM typů do čistého Pythonu — **celá cloud-export kategorie dokončena (NOT_SUPPORTED 0 ★)**: Apple Cloud rodina (Contacts/Keychain/Mail/Photos/Backup, auto-detekce podtypu `_detect_kind`), Google 2025 WR (AccessLogDevices + AccountTargetAssociation + Calls, klíčová slova bez podtržítek pro CamelCase exporty), WhatsApp Chats + Backups, generic cloud metadata (AccountsInfo/ConnectedApps/RecentDevices/Timeline/Passwords/AndroidBackups/AzureVM snapshots — nejobecnější detektor, v pre-passu poslední), Gmail Messages (`email_message`), Maps Labeled Places WR (`location_point`). Coverage matice flip 19 typů NOT_SUPPORTED → SUPPORTED (**179 → 198 / 232 ★**); cloud-export kategorie **19 → 0 ★ (vyčerpána)**; NOT_SUPPORTED celkem **0** (base-class 34 = rozhraní, ne extraktory).
- **Závislosti:** pipeline dispatch — `_sns_prepass()` rozšířen o 6 vlna-14 detektorů (specifické PŘED obecným `cloud_generic`; Apple vyžaduje `.json` příponu — nekrade iMessage TSV) + C3 registry (nové záznamy apple_cloud/google_2025_wr/whatsapp_cloud/cloud_generic/gmail_messages/maps_labeled_places)
- **Dotčené moduly:** `src/stopa/artifacts/{apple_cloud,google_2025_wr,whatsapp_cloud,cloud_generic,gmail_messages,maps_labeled_places}.py`, `pipeline.py` (importy + NAME_BASED_EXTRACTORS + `_sns_prepass()`), `validation_registry.py`, `scripts/build_axiom_coverage.py`
- **Testy:** 58 nových testů zelených (`tests/test_w14_parsers.py`); full suite **1729 passed, 1 skipped** (baseline 1671 + 58); ruff clean; `build_registry()` = **76 parserů** (předtím 70)
- **Dokončeno:** 2026-11-04 | Commit: ```496391b```

### STP-037 — ETAPA B vlna 15: ZÁVĚREČNÝ AUDIT (ETAPA B dokončena ★)
- **Oblast:** D (Artifact Engine) | **Priorita:** P0 | **Stav:** DONE
- **Popis:** Závěrečný audit celé ETAPY B po vlnách 1–14 — nový `tests/test_etapa_b_final_audit.py` s 13 invariantními testy: bijekce coverage matice ↔ AXIOM RE reference (232 typů oběma směry), SUPPORTED = 198 typů každý s parserem + `stav_testovani=testováno`, DEPRECATED = 34 base-class rozhraní (multi, ne extraktory — potvrzeno v AXIOM RE jsonu), NOT_SUPPORTED = **0 ★**, C3 registry = 76 verzovaných parserů (všechny test_files existují, verze neprázdné), pipeline dispatch (signatura + name-based) ↔ C3 registry sync. Spouští se offline — jen čtení CSV/JSON + importy.
- **Závislosti:** žádná (jen čtení `STOPA_COVERAGE_MATRIX.csv`, `docs/re-axiom/axiom-artifact-extractors.json` + importy)
- **Dotčené moduly:** `tests/test_etapa_b_final_audit.py` (nový soubor, 13 testů)
- **Testy:** 13 nových testů zelených; full suite **1742 passed, 1 skipped** (baseline 1729 + 13); ruff clean
- **Finální stav ETAPY B:** covered **198 / 232** unikátních AXIOM typů ★, NOT_SUPPORTED celkem **0**, C3 registry **76 parserů**; oblast D v roadmapě ✅ hotovo (vlny 1–15)
- **Dokončeno:** 2026-11-04 | Commit: ```166e42e```

### STP-038 — ETAPA C: volba směru + synchronizace roadmapy (rozdělení `db.py`)
- **Oblast:** A (Core Architecture) | **Priorita:** P1 | **Stav:** DONE
- **Popis:** Po dokončení ETAPY B (STP-037) — audit reálného stavu všech oblastí A–Q v kódu (ne jen roadmapě), synchronizace zastaralých „Nedokončeno" položek a rozhodnutí o směru ETAPY C. Zjištěno: několik položek bylo mezitím dokončeno — E Timeline Intel 2.0 ✓ (STP-018), L report **20 sekcí** ✓ (STP-020), H PII redactor + governance ✓ (STP-019), J RBAC minimální ✓ (STP-022), K/Q STIX 2.1 + JSONL/XML ✓ (STP-023), N/O stream parsing + Processing Monitor ✓ (STP-021). **ROZHODNUTÍ: ETAPA C = oblast A — rozdělení monolitu `db.py` (~2090 ř., 67 metod) na doménová repozitáře** (nejvyšší zbývající priorita P1, největší technický dluh).
- **Závislosti:** STP-037 (ETAPA B dokončena)
- **Dotčené moduly:** `STOPA_ROADMAP.md` (root — faktické opravy A/E/H/J/L/P/Q + sekce „ETAPA C — ROZHODNUTÍ O SMĚRU"), `.stopa-dev/ROADMAP.md` (autoritativní — synchronizace D–Q + sekce rozhodnutí), DEV OS registry/checkpoint/NEXT_ACTION
- **Testy:** full suite **1742 passed, 1 skipped** (bez změny — jen docs); ruff clean
- **Plán vln ETAPY C:** vlna 1 STP-039 (`CaseRepository`+`FileRepository`+`AuditRepository`, ~28 metod), vlna 2 STP-040 (`ArtifactRepository`+`EntityRepository`, ~23 metod), vlna 3 STP-041 (facade úklid + audit). Akceptační kritéria: `db.py` < ~600 ř., backward compat API, full suite zelená po každé vlně.
- **Dokončeno:** 2026-11-04 | Commit: ```1292e72```

### STP-039 — ETAPA C vlna 1: rozdělení `db.py` (Case/File/Audit repozitáře)
- **Oblast:** A (Core Architecture) | **Priorita:** P1 | **Stav:** DONE
- **Popis:** První vlna rozkladu monolitu `src/stopa/data/db.py` (~2090 ř., 67 metod) na doménová repozitáře. Vyčleněny tři tenké SQLite vrstvy bez business logiky: **CaseRepository** (cases, sources, custody metadata), **FileRepository** (files, evidence_marks, FTS5 search + `_fts_query`), **AuditRepository** (audit log + hash chaining P0 Core C4 + Ed25519 kontrolní body). Sdílené konverze (`_iso`, `_row_to_record`) přesunuty do `_helpers.py`. Facade `CaseDB` drží tři repozitáře na sdílené SQLite connection a deleguje; **backward compat zachován** (veřejné API beze změny, `_fts_query` re-export pro `test_search`).
- **Závislosti:** STP-038 (volba směru ETAPY C)
- **Dotčené moduly:** `src/stopa/data/{case_repository,file_repository,audit_repository,_helpers}.py` (nové), `db.py` (facade — 2090 → **1565 řádků**, −525; zbývají artifacts/findings/lineage/analysis_operations pro vlny 2–3)
- **Testy:** 15 nových testů zelených (`tests/test_stp039_wave1_repos.py` — wiring sdílené connection, delegace přes facade i přímé čtení z repo, nezávislé repozitáře na stejném spojení, backward compat `_fts_query`); full suite **1757 passed, 1 skipped** (baseline 1742 + 15); ruff clean
- **Dokončeno:** 2026-11-04 | Commit: ```58628a9```

### STP-040 — ETAPA C vlna 2: rozdělení `db.py` (Artifact/Entity repozitáře)
- **Oblast:** A (Core Architecture) | **Priorita:** P1 | **Stav:** DONE
- **Popis:** Druhá vlna rozkladu monolitu `src/stopa/data/db.py` na doménová repozitáře. Vyčleněny dvě tenké SQLite vrstvy bez business logiky: **ArtifactRepository** (artifacts, findings, lineage_events, analysis_operations, timeline events + konvertory `_row_to_artifact`/`_row_to_finding`/`_row_to_lineage_event`/`_row_to_analysis_operation`) a **EntityRepository** (entities s agregací first/last_seen při re-runu, correlations). Facade `CaseDB` drží pět repozitářů na sdílené SQLite connection a deleguje; **backward compat zachován** (veřejné API beze změny — `CaseDB`, `SCHEMA_VERSION`, `_fts_query`).
- **Závislosti:** STP-039 (vlna 1 — Case/File/Audit repozitáře)
- **Dotčené moduly:** `src/stopa/data/{artifact_repository,entity_repository}.py` (nové), `db.py` (facade — 1565 → **1011 řádků**, −554; zbývá vlna 3 = facade úklid + audit)
- **Testy:** 17 nových testů zelených (`tests/test_stp040_wave2_repos.py` — wiring sdílené connection, delegace přes facade i přímé čtení z repo, idempotentní upsert artifactu podle klíče, výměna artifactů souboru při re-ingestu, lineage chain dohledání, entity agregace first/last_seen, correlations); full suite **1774 passed, 1 skipped** (baseline 1757 + 17); ruff clean
- **Dokončeno:** 2026-11-04 | Commit: ```28b6222```

### STP-041 — ETAPA C vlna 3: rozdělení `db.py` (schema/migrations moduly + facade úklid)
- **Oblast:** A (Core Architecture) | **Priorita:** P1 | **Stav:** DONE
- **Popis:** Finální vlna rozkladu monolitu `src/stopa/data/db.py`. Vyčleněny dva samostatné moduly: **schema.py** (`SCHEMA_VERSION`, `_schema_version`, kompletní DDL — 15 tabulek, indexy, triggery, FTS5 virtual tables) a **migrations.py** (idempotentní migrace starých case DB — `apply_legacy_migrations` + audit chain backfill od GENESIS + entity resolution CHECK rebuild s confidence remapem verified→confirmed/inferred→possible + timeline intel sloupce + FTS backfill flagy; původně inline v `CaseDB.__init__`). Facade úklid: mrtvé privátní delegace `_last_audit_row`/`_case_examiner` (používané jen uvnitř `audit_repository`) odstraněny z `CaseDB`. **Backward compat zachován** (`CaseDB`, `SCHEMA_VERSION`, `_fts_query`).
- **Závislosti:** STP-040 (vlna 2 — Artifact/Entity repozitáře)
- **Dotčené moduly:** `src/stopa/data/{schema,migrations}.py` (nové), `db.py` (facade — 1011 → **476 řádků**, −535; celkem ETAPA C: ~2090 → 476, **−77 %**)
- **Testy:** 18 nových testů zelených (`tests/test_stp041_wave3_schema_migrations.py` — schema kompletnost (tabulky/FTS/triggery), legacy v10 DB migrace end-to-end přes `CaseDB`, audit chain backfill od GENESIS s obnovou triggerů, FTS backfill flagy, idempotence na nové DB, facade úklid + backward compat); full suite **1792 passed, 1 skipped** (baseline 1774 + 18); ruff clean
- **Finální stav ETAPY C:** `db.py` = tenký agregátor 5 repozitářů na sdílené connection; **ETAPA C DOKONČENA ★** (cíl < ~600 ř. splněn — 476 ř.)
- **Dokončeno:** 2026-11-04 | Commit: ```824755d```

### STP-042 — Volba ETAPY D + synchronizace roadmapy (audit reálného stavu)
- **Oblast:** P (Quality Assurance) | **Priorita:** P1 | **Stav:** DONE
- **Popis:** Audit reálného stavu všech kandidátských oblastí pro ETAPU D (ne jen staré „Nedokončeno" v roadmapě): **P QA** — benchmark engine hotový (`domain/benchmark.py` 95 ř. + `data/benchmark_engine.py` 267 ř., CLI `stopa benchmark`, detekce regresí >20 %), CI má lint+test+security ale **benchmark chybí**, baseline soubor neexistuje; **M Security** — sandbox parserů neexistuje (parsery v hlavním procesu); **H AI Copilot** — citace existují (`CITATION_RE`, `extract_citations`), detekce rozporů chybí; **I+O Validation/Audit Center UI** — registry existuje, UI moduly chybí; **G/J/K/Q** — částečně/neexistují. **ROZHODNUTÍ: ETAPA D = oblast P (CI běh benchmarku proti baseline)** — jediný zbývající P1 úkol, nejmenší rozsah s největším dopadem (engine hotový, chybí jen zapojení do CI), chrání ETAPU C i budoucí vlny před tichou regresí výkonu.
- **Závislosti:** STP-041 (ETAPA C dokončena)
- **Dotčené moduly:** `.stopa-dev/ROADMAP.md` + `STOPA_ROADMAP.md` (sekce P → 🔧 v průběhu ETAPA D; nová sekce „ETAPA D — ROZHODNUTÍ O SMĚRU" s audit tabulkou, rozhodnutím a plánem vln 1–2)
- **Testy:** bez změny kódu (docs/DEV OS); full suite **1792 passed, 1 skipped**; ruff clean
- **Plán ETAPY D:** Vlna 1 (STP-043) = CI benchmark job (`ci.yml` + `scripts/ci_benchmark.py` + baseline artefakt), Vlna 2 (STP-044) = testy + dokumentace
- **Dokončeno:** 2026-11-04 | Commit: ```d87a677```

### STP-043 — ETAPA D vlna 1: CI benchmark job proti baseline
- **Oblast:** P (Quality Assurance) | **Priorita:** P1 | **Stav:** DONE
- **Popis:** Zapojení hotového benchmark engine do CI. Nový skript `scripts/ci_benchmark.py` spustí `run_benchmark(suite="all")` (77 položek, ~0.25 s), porovná aktuální doby s versionovanou baseline přes domain API `detect_regressions(threshold=0.20)` a na regresi skončí exit 1; výsledek se vypíše jako JSON report (artifact). **CI noise guard** `--min-delta-ms 0.5`: relativní práh 20 % je pod ~1 ms křehký (měření ukázalo falešné pozitivní na sub-ms položkách — např. +22.7 % = šum 5 µs), proto se ignorují regresie s absolutním rozdílem < 0.5 ms. Nový CI job `benchmark` v `.github/workflows/ci.yml` (needs lint+test, Python 3.11, upload výsledků jako artifact, fail na regresi). Inicializován versionovaný baseline artefakt `benchmarks/baseline.json` (77 položek, verze 1).
- **Závislosti:** STP-042 (volba ETAPY D)
- **Dotčené moduly:** `.github/workflows/ci.yml` (+benchmark job), `scripts/ci_benchmark.py` (nový, 157 ř.), `benchmarks/baseline.json` (nový artefakt), `tests/test_stp043_ci_benchmark.py` (nový)
- **Testy:** 15 nových testů zelených (`tests/test_stp043_ci_benchmark.py` — load/save baseline, determinismus formátu, detekce regresí přes domain API, noise guard sub-ms falešné pozitivní, exit kódy main() 0/1/2 s monkeypatchovaným engine); full suite **1807 passed, 1 skipped** (baseline 1792 + 15); ruff clean
- **Dokončeno:** 2026-11-04 | Commit: ```0136e91```

### STP-044 — ETAPA D vlna 2: testy + dokumentace CI benchmark jobu
- **Oblast:** P (Quality Assurance) | **Priorita:** P1 | **Stav:** DONE
- **Popis:** Dokončení ETAPY D. (1) **E2E subprocess testy** `tests/test_stp044_ci_benchmark_e2e.py` (6): spouští `scripts/ci_benchmark.py` jako skutečný subprocess (stejný způsob jako GitHub Actions) s dočasnou baseline — první běh bez baseline (exit 0, baseline_present=False), `--update-baseline` (versionovaný artefakt), běh proti vlastní baseline (exit 0, noise guard), umělá regrese na položce ≥1 ms (baseline /2 → exit 1 + `REGRESIE` na stderr), poškozená baseline (exit 2), artifact výstup identický se stdout reportem. (2) **Dokumentace** `docs/STOPA_BENCHMARKS.md`: komponenty, workflow, exit codes, proč dva prahy (relativní 20 % + absolutní guard 0.5 ms — reálné falešné pozitivní win_schedtask +22.7 % = šum 5 µs), jak aktualizovat baseline (`--update-baseline` + commit s vysvětlením), jak číst report/artifact, ukázkové hodnoty baseline (pipeline.core ~63.5 ms, registry_hive ~22.6 ms, ostatní sub-ms). README: odkaz na benchmark docs + aktuální počet testů.
- **Závislosti:** STP-043 (CI benchmark job)
- **Dotčené moduly:** `tests/test_stp044_ci_benchmark_e2e.py` (nový, 6 E2E testů), `docs/STOPA_BENCHMARKS.md` (nová), `README.md` (odkaz + počet testů)
- **Testy:** 6 nových E2E testů zelených; full suite **1813 passed, 1 skipped** (baseline 1807 + 6); ruff clean
- **Dokončeno:** 2026-11-04 | Commit: ```ca93d58```

### STP-045 — Volba ETAPY E: oblast M Security — izolace parserů (sandbox)
- **Oblast:** M (Security) + DEV OS | **Priorita:** P2 | **Stav:** DONE
- **Popis:** Audit reálného stavu kandidátů ETAPY E (M sandbox / H AI grounding / I+O Validation Center) ověřený v kódu + empirickým probe. **Klíčový nález auditu:** poškozený SQLite soubor (garbage `db_size_pages` = 1 696 622 191 stránek v 920 B souboru) visí >15 s v `sqlite_carver.recover_rows` (smyčka `range(1, db_size_pages+1)` bez validace proti velikosti souboru) a zastaví celou pipeline — parsery běží přímo ve worker vláknech (`_process_file_worker` → `_extract_artifacts_for`) bez izolace. Vybráno **ETAPA E = M Security: izolace parserů (sandbox)** — nejvyšší zbývající priorita P2 + největší dopad na spolehlivost (forenzní nástroj zpracovává neověřený vstup). Plán vln 1–3: STP-046 `domain/sandbox.py` (kontrakt, timeout, marshalling), STP-047 zapojení do pipeline + fix hang bugu, STP-048 testy + dokumentace.
- **Závislosti:** STP-044 (ETAPA D dokončena ★★)
- **Dotčené moduly:** `.stopa-dev/ROADMAP.md` (sekce M + ETAPA E), `STOPA_ROADMAP.md` (sync), DEV OS TASKS/PROJECT_STATE/CHANGELOG/checkpoint/NEXT_ACTION, root+mirror changelog
- **Testy:** full suite **1813 passed, 1 skipped** (bez změny — volba etapy = docs); ruff clean
- **Dokončeno:** 2026-11-05 | Commit: ```586e85a```

### STP-046 — ETAPA E vlna 1: parser sandbox kontrakt (`domain/sandbox.py`)
- **Oblast:** M (Security) | **Priorita:** P2 | **Stav:** DONE
- **Popis:** Sandbox kontrakt pro izolaci artifact extraktorů od hlavního procesu pipeline. Nové moduly: `src/stopa/domain/sandbox.py` (čistá logika — `SandboxConfig` s limity timeout_s/max_result_bytes, `SandboxResult`, `validate_artifact_payload()` strukturální validace JSON kontraktu, `build_worker_command()`, `failure_category()` s prioritou timeout>truncated>bad_payload>crash, `sandbox_available()`, tenký IO wrapper `run_extractor_sandboxed()` přes subprocess) + `src/stopa/sandbox_worker.py` (dceřiný proces `python -m stopa.sandbox_worker <module> <func> <path>`; stdout = POUZE JSON array artifactů, exit 0/1 kontrakt, RLIMIT_CPU backstop na POSIX z env STOPA_SANDBOX_TIMEOUT).
- **Závislosti:** STP-045 (volba ETAPY E)
- **Dotčené moduly:** `src/stopa/domain/sandbox.py` (nový), `src/stopa/sandbox_worker.py` (nový), `tests/test_stp046_sandbox.py` (nový, 21 testů)
- **Testy:** 21 nových testů zelených; full suite **1834 passed, 1 skipped** (baseline 1813 + 21); ruff clean. E2E přes reálný subprocess: timeout (hang modul), crash (ValueError), bad_payload (chybějící artifact_type), truncated (payload > limit).
- **Dokončeno:** 2026-11-05 | Commity: ```91854d8``` (feature) + ```de18452``` (fix benchmark stabilizace)

### STP-047 — ETAPA E vlna 2: zapojení sandboxu do pipeline + fix reálného hang bugu
- **Oblast:** M (Security) | **Priorita:** P2 | **Stav:** DONE
- **Popis:** Dvě části. **(A) Fix reálného hang bugu** v `src/stopa/domain/sqlite_carver.py`: smyčka `for page_no in range(1, header.db_size_pages + 1)` bez validace proti velikosti souboru — poškozený SQLite (garbage `db_size_pages` = 1.7 mld. stránek v 920 B souboru) visel >15 s a zastavil celou pipeline; oprava: iterace omezená reálnou velikostí souboru (`max_pages = len(data) // page_size`, `last_page = min(db_size_pages, max_pages)`), corrupt header → 0.000 s (naměřeno). **(B) Zapojení sandboxu do pipeline** v `src/stopa/pipeline.py`: nový dispatch `_run_extractor()` — všechny tři extrakční cesty `_extract_artifacts_for` (signatura `ARTIFACT_EXTRACTORS`, SNS pre-pass, name-based fallback `NAME_BASED_EXTRACTORS`) běží přes `run_extractor_sandboxed()` (dceřiný proces, timeout 30 s / payload limit 16 MiB); selhání parseru → **`parser_error` artifact** s kategorií z `SandboxResult` (timeout/truncated/bad_payload/crash) — pipeline nepadne; fallback bez sandboxu = přímé in-process volání, řízeno konstantou `SANDBOX_ENABLED` (env `STOPA_SANDBOX=0`) + `sandbox_available()`. Konstanty `SANDBOX_ENABLED`/`SANDBOX_CONFIG` v `pipeline.py`; helper `_parser_error_artifact()`; parsery nepíší na stdout (JSON kontrakt workeru — ověřeno, 0× `print()` v `src/stopa/artifacts`).
- **Závislosti:** STP-046 (sandbox kontrakt)
- **Dotčené moduly:** `src/stopa/domain/sqlite_carver.py` (fix hang bugu), `src/stopa/pipeline.py` (sandbox importy, `ValidationError`, konstanty, `_parser_error_artifact()`, `_run_extractor()`, přepsaný `_extract_artifacts_for`)
- **Testy:** 12 nových testů zelených — `tests/test_sqlite_recover.py` (+4: corrupt header garbage `db_size_pages` nevisí <2 s, page_size=0 bez dělení nulou, db_size > velikost souboru skenuje jen reálné stránky, validní DB regression) + nový `tests/test_stp047_sandbox_integration.py` (8: E2E přes **reálný subprocess** — úspěch → artifacty, crash → parser_error, timeout → parser_error s měřením času, fallback bez sandboxu, corrupt SQLite přes celou pipeline); cílený běh 25 passed; full suite **1846 passed, 1 skipped** (baseline 1834 + 12); ruff clean
- **Dokončeno:** 2026-11-06 | Commit: ```3fc2dac``` (ETAPA E vlna 2 hotová ★)

### STP-048 — ETAPA E vlna 3: sandbox E2E testy + corrupt-file regression + dokumentace
- **Oblast:** M (Security) | **Priorita:** P2 | **Stav:** DONE
- **Popis:** Poslední vlna ETAPY E — testy + dokumentace. **(A) Umělý hangující parser přes celou pipeline** (`process_source`): dočasný modul `sb_stp048_hang.hang` (sleep 5 s) registrovaný pod signaturu `sqlite`, corrupt SQLite header ho spustí; sandbox timeout 1,5 s → v DB je **`parser_error` artifact s kategorií `timeout`** + audit log (`details.parser = sb_stp048_hang.hang`), pipeline doběhne za <20 s (bez sandboxu by visela navěky). **(B) Corrupt-file regression pro ostatní binární parsery**: corrupt EVTX (validní magic `EVTX` + garbage tělo → 0 artifactů, nepadá) a corrupt LNK (validní signatura cbLinkHeaderSize=76+IShellLink CLSID + garbage tělo → header artifact, nepadá) přes `_extract_artifacts_for`; plný `process_source` E2E na corrupt EVTX+LNK evidenci → doběhne rychle, artifacty v DB, žádný parser_error. **(C) Dokumentace** `docs/STOPA_SANDBOX.md`: kontrakt workeru (stdout=JSON array / stderr=logy / exit 0-1), limity (`SandboxConfig` timeout 30 s / payload 16 MiB), kategorie selhání (timeout>truncated>bad_payload>crash + `parser_error` artifact struktura), fallback bez sandboxu (`STOPA_SANDBOX=0`), jak přidat parser do sandboxu (registrace v `ARTIFACT_EXTRACTORS`/`NAME_BASED_EXTRACTORS`).
- **Závislosti:** STP-047 (sandbox zapojený do pipeline)
- **Dotčené moduly:** `tests/test_stp048_sandbox_e2e.py` (nový, 4 testy), `docs/STOPA_SANDBOX.md` (nový)
- **Testy:** 4 nové testy zelené — E2E hangující parser přes `process_source` → `parser_error`(timeout) v DB; corrupt EVTX/LNK regression; plný `process_source` E2E na corrupt evidenci. Cílený běh 4 passed in ~1,9 s (hang test reálně čeká 1,52 s na timeout); full suite **1850 passed, 1 skipped** (baseline 1846 + 4); ruff clean
- **Dokončeno:** 2026-11-06 | Testy: `5965cb4` (docs/DEV OS viz následující docs commit) — **ETAPA E dokončena ★★**

### STP-049 — ETAPA H vlna 1–3: AI Copilot grounding (detekce rozporů odpovědi LLM vs data citací)
- **Oblast:** H (AI Copilot) | **Priorita:** P2 | **Stav:** DONE
- **Popis:** První konkrétní realizace úrovně I5 pro existující E11 režimy — detekce rozporů mezi textem odpovědi LLM a daty citovaných záznamů. **(A) Vlna 1** `src/stopa/domain/ai_grounding.py` (nový, čistá logika bez IO): `extract_claims()` extrahuje tvrdění z odpovědi (ISO + česká data, slovník 62 typů artifactů), `ground_answer(text, citations, artifacts_by_id)` → deterministický `GroundingReport` s třemi kategoriemi rozporu (`mismatch_date` — datum neodpovídá timestamp citace; `mismatch_type` — zmiňovaný typ se liší od reálného; `unverified_claim` — citace bez ověřitelné kotvy) + `.verified_citations`; atribuce tvrdění k nejbližší citaci (vzdálenost znaků, tie → menší index). **(B) Vlna 2** zapojení do web endpointu `web/app.py`: nový defenzivní obal `_ground_answer_safe()` — všechny tři režimy (`nl_search`/`summary`/`explain`) vracejí pole `grounding` (report nebo `None` bez citací; interní chyba → log + degradace, hlavní odpověď se nedorozbije); GUI `js/components/ai.js` + `style.css`: citace s rozporu dostanou ⚠ štítek (`.flagged`) + panel findings pod odpovědí (kategorie, tvrzení → skutečná hodnota v DB). **(C) Vlna 3** testy + dokumentace: `tests/test_stp049_grounding.py` (33 domain testů, offline) + `tests/test_stp049_grounding_e2e.py` (8 web E2E přes TestClient + fake LmStudioClient — mismatch_date/mismatch_type/verified/žádné citace/nl_search inline tokeny/kontrakt pole ve všech režimech); dokumentace `docs/STOPA_AI_ARCHITECTURE.md` §1.1.
- **Závislosti:** STP-048 (ETAPA E dokončena ★★)
- **Dotčené moduly:** `src/stopa/domain/ai_grounding.py` (nový), `src/stopa/web/app.py` (`_ground_answer_safe()` + grounding ve všech 3 AI režimech), `src/stopa/web/static/js/components/ai.js` (⚠ štítky citací + findings panel), `src/stopa/web/static/style.css` (`.flagged`, `.ai-grounding`), `tests/test_stp049_grounding.py` (nový, 33 testů), `tests/test_stp049_grounding_e2e.py` (nový, 8 testů), `docs/STOPA_AI_ARCHITECTURE.md` (§1.1)
- **Testy:** 41 nových testů zelených; full suite **1891 passed, 1 skipped** (baseline 1850 + 41); ruff clean
- **Dokončeno:** 2026-11-06 | Commity: viz git log (feature + docs) — **ETAPA H dokončena ★★**

### STP-050 — Oblast I+O: Validation Center UI (C3 registry + C6 report v SPA)
- **Oblast:** I+O (Validation Engine / User Interface) | **Priorita:** P2 | **Stav:** DONE
- **Popis:** Doložitelnost extrakce v GUI. **(A)** `web/app.py` — `GET /api/cases/{id}/validation` (C6 `build_validation_report`: total_artifacts, coverage per-parser, validační statusy, per-artifact řádky s parser ID+verze/confidence/provenance) + `GET /api/validation/registry` (C3 `build_registry`/`registry_report`); defenzivní obaly — selhání → 500 s logem. **(B)** SPA: sekce `mod-validation` v index.html (statistické karty, coverage bar, per-parser tabulka, validační statusy, per-artifact report), nový `js/components/validation.js` (`renderValidationCenter()` — badge validated/needs_validation, fetch obou endpointů přes Promise.all), registrace modulu v modules.js/sidebar.js + styling.
- **Závislosti:** STP-049 (ETAPA H dokončena ★★)
- **Dotčené moduly:** `src/stopa/web/app.py`, `index.html`, `js/components/validation.js` (nový), `modules.js`, `sidebar.js`, `style.css`, `tests/test_stp050_validation_center.py` (nový, 10 testů)
- **Testy:** 10 nových testů zelených; full suite **1901 passed, 1 skipped** (baseline 1891 + 10); ruff clean
- **Dokončeno:** 2026-11-06 | Commit: `0b761ab`

### STP-051 — Oblast G: File Preview v UI (inline media + text preview)
- **Oblast:** G (File Intelligence / User Interface) | **Priorita:** P3 | **Stav:** DONE
- **Popis:** Vizualizace souborů přímo v inspectoru. **(A)** `domain/file_preview.py` (nový, čistá logika bez IO): `classify_preview(data, name)` → image/audio/video/text/None podle magic bytes (PNG/JPEG/GIF/WebP/BMP/WAV/RIFF-WMA/FLAC/MP3/ID3/MP4-ISO-BMFF) s fallbackem na příponu; `extract_text_preview()` — UTF-8 decode + BOM, NUL → 400 znaků nečitelných → binární, truncace na max_chars (default 4000); `preview_media_type()` → MIME. **(B)** `web/app.py` — `GET /api/files/{fid}/preview`: media → inline Response s Content-Type + Cache-Control no-store; text → JSON {text, truncated}; neznámý typ → 415; chybějící/nesčitatelný soubor → 404. **(C)** SPA: sekce PREVIEW v inspector draweru (index.html), `inspector.js` — `loadPreview()` (fetch + render img/audio/video/text, object URL lifecycle `_revokePreview()`, 415 → „preview není dostupné"), styling `.preview-box`/`.preview-text`.
- **Závislosti:** STP-050 (Validation Center hotový)
- **Dotčené moduly:** `src/stopa/domain/file_preview.py` (nový), `src/stopa/web/app.py`, `index.html`, `js/components/inspector.js`, `style.css`, `tests/test_stp051.py` (nový, 18 testů)
- **Testy:** 18 nových testů zelených; full suite **1919 passed, 1 skipped** (baseline 1901 + 18); ruff clean
- **Dokončeno:** 2026-11-06 | Commit: `11d80e4` — **Oblast G dokončena ★**

### STP-052 — Oblast O: Audit Center (neměnná stopa: hash chain + Ed25519 kontrolní body)
- **Oblast:** O (User Interface / Integrity C4) | **Priorita:** P3 | **Stav:** DONE
- **Popis:** Neměnný audit trail v GUI. **(A)** `web/app.py` — `GET /api/cases/{id}/audit`: agregace C4 integrity vrstvy — `verify_audit_chain()` (SHA-512 hash chain, first/last hash, broken index), Ed25519 kontrolní body (`list_integrity_checkpoints`) + nezávislé ověření podpisů (`verify_integrity_checkpoints`), public key (base64), audit záznamy (`list_audit_log`); defenzivní obaly — selhání → 500 s logem. **(B)** SPA: sekce `mod-audit` v index.html, nový `js/components/audit.js` (`renderAuditCenter()` — stat karty chain/checkpoints/záznamy, chain status badge valid/broken, kontrolní body se stavem podpisu verified/invalid, tabulka audit záznamů s operací/aktérem/datem), registrace v modules.js/sidebar.js (🛡). **(C)** Testy: tampering test simuluje útočníka s přímým přístupem k souboru — UPDATE detailu je na úrovni DB blokován append-only triggerem (`audit_no_update`), test ho dropne a ověří, že chain verifikaci odhalí broken index.
- **Závislosti:** STP-051 (File Preview hotový)
- **Dotčené moduly:** `src/stopa/web/app.py`, `index.html`, `js/components/audit.js` (nový), `modules.js`, `sidebar.js`, `tests/test_stp052.py` (nový, 8 testů)
- **Testy:** 8 nových testů zelených; full suite **1927 passed, 1 skipped** (baseline 1919 + 8); ruff clean
- **Dokončeno:** 2026-11-06 | Commit: viz git log — **Oblast O dokončena ★**

### STP-053 — Oblast J: Case Mgmt 2.0 (RBAC permission matrix + enforcement)
- **Oblast:** J (Case Management) / M (Security) | **Priorita:** P3 | **Stav:** DONE
- **Popis:** Role se doteď nikde neaplikovaly (STP-022 = jen actor atribuce). **(A)** `domain/rbac.py` rozšířeno o permission matici — role `analyst`/`examiner`/`admin`, oprávnění `case.read`/`analysis.run`/`file.flag`/`case.create`/`case.update`/`case.delete`/`source.add`/`settings.write`; `can()` fail-closed (neznámá role → jen case.read, neznámé oprávnění → False), `require_permission()` → `RBACDenied`, `permissions_for()`, `normalize_role()`; default = examiner. **(B)** `web/app.py` — enforcement `_require()` na mutující endpointy: POST/PATCH/DELETE cases, POST sources, timeline/correlate/AI query+analyze (analysis.run), file flag, PUT settings (settings.write + validace role → 400); GET settings vrací `permissions` aktuální role. Bez auth vrstvy = operační guardrail (localhost-only).
- **Závislosti:** STP-052 (Audit Center hotový)
- **Dotčené moduly:** `src/stopa/domain/rbac.py`, `src/stopa/web/app.py`, `tests/test_stp053.py` (nový, 29 testů)
- **Testy:** 29 nových testů zelených; full suite **1956 passed, 1 skipped** (baseline 1927 + 29); ruff clean
- **Dokončeno:** 2026-11-06 | Commit: viz git log — **Oblast J rozšířena ★**

### STP-054 — Oblast K: Export Engine (Plaso interop formát l2tcsv)
- **Oblast:** K (Export Engine) / Q (Interop) | **Priorita:** P3 | **Stav:** DONE
- **Popis:** Chybějící položka oblasti K. **(A)** `domain/export.py::to_l2tcsv()` — čisté serializace do 17 pevných polí log2timeline.pl (Plaso/Timesketch standard, formát ověřen proti oficiální Plaso dokumentaci): timestamp (ns epoch), score, datetime UTC ISO, message, source_short, tool_name=stopa, tool_module, event_type, container, path, uid/username/target_uid/target_username/session, offset_in_data; None → prázdné pole, CRLF řádky. **(B)** CLI `stopa export --format l2tcsv` (argparse choices + dispatch).
- **Závislosti:** STP-053 (RBAC hotový)
- **Dotčené moduly:** `src/stopa/domain/export.py`, `src/stopa/cli.py`, `tests/test_stp054.py` (nový, 19 testů)
- **Testy:** 19 nových testů zelených; full suite **1975 passed, 1 skipped** (baseline 1956 + 19); ruff clean
- **Dokončeno:** 2026-11-06 | Commit: viz git log — **Oblast K hotová ★**

### STP-055 — Oblast Q: Interop (UCO mapping)
- **Oblast:** Q (Interop) | **Priorita:** P3 | **Stav:** DONE
- **Popis:** Kurátorské mapování STOPA artifact typů na třídy oficiální UCO ontologie (`ucoProject/UCO`, třídy ověřeny z TTL). **(A)** `domain/uco.py` (čistá logika bez IO) — `UCO_ARTIFACT_MAP` 52 typů → reálné UCO třídy (observable/configuration/location/identity), `UCO_UNMAPPED` 14 typů bez ekvivalentu (explicitní, ne tichá ztráta); pokrytí 66/66 KNOWN_ARTIFACT_TYPES. `map_artifact_to_uco()` → (class, module) | None; `uco_type_label()` → `<module>:<Class>` nebo `stopa:<typ>`. **(B)** `to_uco_json(records, dataset)` — JSON-LD dokument (@context UCO, per-záznam objekty s @type/name/time/x-stopa-id/x-stopa bez None), deterministický výstup. **(C)** CLI `stopa export --format uco` (argparse choices + dispatch).
- **Závislosti:** STP-054 (export engine hotový)
- **Dotčené moduly:** `src/stopa/domain/uco.py` (nový), `src/stopa/cli.py`, `tests/test_stp055.py` (nový, 22 testů)
- **Testy:** 22 nových testů zelených; full suite **1997 passed, 1 skipped** (baseline 1975 + 22); ruff clean
- **Dokončeno:** 2026-11-07 | Commit: viz git log — **Oblast Q rozšířena ★**

### STP-056 — Oblast J: Case Mgmt 2.0 UI (přepínač role v Settings)
- **Oblast:** J (Case Management) | **Priorita:** P3 | **Stav:** DONE
- **Popis:** Backend enforcement hotový od STP-053; chyběl vizuální indikátor a ovládání. **(A)** `domain/rbac.py` — `ROLE_LABELS` (jediný zdroj labelů pro UI). **(B)** `web/app.py` — nový endpoint `GET /api/roles` vrací matici rolí (id/label/permissions) z permission matrix; role se nadále čte server-side ze settings. **(C)** SPA: topbar badge aktuální role (`#role-badge`, barva dle role), Settings preview panel oprávnění s živým přepínáním při změně `<select id="set-role">` (bez ukládání), nový modul `js/components/role.js` (`initRoles()` fail-safe, neblokující bootstrap), po uložení Settings se badge obnoví. **(D)** CSS `.role-badge*`, `.perm-preview`.
- **Závislosti:** STP-053 (RBAC enforcement hotový)
- **Dotčené moduly:** `src/stopa/domain/rbac.py`, `src/stopa/web/app.py`, `src/stopa/web/static/index.html`, `src/stopa/web/static/style.css`, `src/stopa/web/static/js/components/role.js` (nový), `src/stopa/web/static/app.js`, `src/stopa/web/static/js/components/modules.js`, `tests/test_stp056.py` (nový, 8 testů)
- **Testy:** 8 nových testů zelených; full suite **2005 passed, 1 skipped** (baseline 1997 + 8); ruff clean
- **Dokončeno:** 2026-11-07 | Commit: viz git log — **Oblast J UI hotová ★**

### STP-057 — Oblast Q: Plaso import (l2tcsv → case)
- **Oblast:** Q (Interop) | **Priorita:** P3 | **Stav:** DONE
- **Popis:** Doplněk k STP-054 exportu `to_l2tcsv` — čte 17 pevných polí log2timeline.pl (zpětně i cizí l2tcsv z Plaso/Timesketch) a importuje je do case DB. **(A)** `domain/plaso_import.py` (čistá logika bez IO): `parse_l2tcsv()` — text → `PlasoEvent`y, rekonstrukce UTC času ze sloupců date (MM/DD/YYYY) + time (HH:MM:SS) + timezone („Z“ = UTC; nevalidní/chybějící čas → None, bez fiktivního času), sourcetype → event_type (fallback „plaso_event“), extra JSON → details (plná věrnost dat exportu STOPA), confidence ∈ [0,1], notes → anomaly flags. `import_l2tcsv()` — orchestrace nad CaseDB: evidence source kind="file", idempotentní upsert artifactů, timeline events pro řádky s rekonstruovaným časem (ts_origin="source"), commit na konci + souhrn. **(B)** CLI `stopa plaso-import <case_id> SOUBOR` — audit log (`plaso_import`) + Ed25519 kontrolní bod po importu; chybějící soubor → SystemExit.
- **Závislosti:** STP-054 (export l2tcsv hotový)
- **Dotčené moduly:** `src/stopa/domain/plaso_import.py` (nový), `src/stopa/cli.py`, `tests/test_stp057_plaso_import.py` (nový, 14 testů)
- **Testy:** 14 nových testů zelených; full suite **2019 passed, 1 skipped** (baseline 2005 + 14); ruff clean. Pozn.: `test_stp044_ci_benchmark_e2e` je timing-sensitive — v plné suite pod zátěží jednou flaky, izolovaně stabilně PASS.
- **Dokončeno:** 2026-11-07 | Commit: viz git log — **Oblast Q hotová ★★** (UCO mapping + Plaso import)

### STP-058 — Oblast O+Q: Interop Export Center UI (GUI exporty l2tcsv/UCO/CSV/JSON/STIX)
- **Oblast:** O (User Interface) / Q (Interop) | **Priorita:** P3 | **Stav:** DONE
- **Popis:** GUI vrstva nad hotým interop export engine (STP-054 l2tcsv, STP-055 UCO, F-054 JSONL/XML/STIX). **(A)** `web/app.py` — nový endpoint `GET /api/cases/{id}/interop-export?what=&format=`: `what ∈ {artifacts, timeline, correlations}` (záznamy přes hoté domain konvertory `artifact_records`/`timeline_records`/`correlation_records`), `format ∈ {csv, json, jsonl, xml, stix, uco, l2tcsv}` — dispatch na `to_csv`/`json.dumps`/`to_jsonl`/`to_xml`/`to_stix_bundle`/`to_uco_json`/`to_l2tcsv`; neplatný parametr → 400; výsledek jako download (`Content-Disposition: attachment`, filename `{case_id}_{what}.{ext}`); každý export → audit log `interop_exported` (details what/format/records) + integrity checkpoint `interop-export`. **(B)** SPA: nový modul `js/components/interop.js` — sekce `mod-interop` v index.html (datasety s živými počty z case detail + correlations, výběr datasetu × formátu, tlačítko Stáhnout → endpoint v novém okně, tabulka posledních 10 exportů z audit logu); registrace do `sidebar.js` (MODULES + ikona ⇩) a dispatch v `modules.js`.
- **Závislosti:** STP-054/055/057 (export engine + UCO hotové), F-054 (JSONL/XML/STIX)
- **Dotčené moduly:** `src/stopa/web/app.py`, `src/stopa/web/static/index.html` (sekce mod-interop + script tag), `src/stopa/web/static/js/components/interop.js` (nový), `src/stopa/web/static/js/components/sidebar.js`, `src/stopa/web/static/js/components/modules.js`, `tests/test_web.py` (+9 testů — TestInteropExport)
- **Testy:** 9 nových testů zelených; full suite **2028 passed, 1 skipped** (baseline 2019 + 9); ruff clean
- **Dokončeno:** 2026-11-07 | Commit: viz git log — **Oblast O rozšířena ★** (GUI interop exporty)

### STP-059 — Oblast Q: Timesketch push (case data → Timesketch)
- **Oblast:** Q (Interop) | **Priorita:** P3 | **Stav:** DONE
- **Popis:** Třetí interop smyčka — odeslání case dat do Timesketch přes REST API. **(A)** `data/timesketch_client.py` (nový, 253 ř.) — HTTP klient po vzoru `LmStudioClient` s injektovatelným transportem (offline testovatelnost přes `httpx.MockTransport`): login flow s CSRF scrapem (`input#csrf_token`, fallback `<meta name="csrf-token">`), `create_sketch()` POST `/api/v1/sketches/` → 201 (ID z `objects[0].id`), `upload_timeline()` multipart `/api/v1/upload/` (sketch_id/name/file) → `{timeline_id, task_id}`, `health()` bez side effectů; výjimky `TimesketchError` / `TimesketchUnavailable` (graceful degradation); env override `STOPA_TIMESKETCH_URL/USER/PASSWORD`. **(B)** `domain/timesketch_push.py` (nový, 83 ř.) — čistá doménová logika s injektovatelným klientem (`Protocol`): reuse exportních konvertorů (`to_l2tcsv`, timeline records), název sketchu `STOPA <case> — <what>`, souhrn `{sketch_id, timeline_id, task_id, records}` pro audit bez přístupových údajů; prázdný dataset → `ValueError`. **(C)** CLI `stopa timesketch-push <case> --what artifacts|timeline|correlations` (stejná doménová funkce jako web). **(D)** Web endpoint `POST /api/cases/{id}/timesketch-push`: RBAC `_require("analysis.run")`, validace `what ∈ {artifacts, timeline, correlations}` → 400, nedostupná Timesketch → 503, selhání pushu → 502; audit log `timesketch_pushed` + integrity checkpoint.
- **Závislosti:** STP-054 (export l2tcsv), E11 MockTransport vzor (`LmStudioClient`)
- **Dotčené moduly:** `src/stopa/data/timesketch_client.py` (nový), `src/stopa/domain/timesketch_push.py` (nový), `src/stopa/cli.py`, `src/stopa/web/app.py` (+ oprava: web `create_case` generuje Ed25519 integrity klíč — dříve checkpointy ticho propadaly), `tests/test_stp059.py` (nový, 20 testů)
- **Testy:** 20 nových testů zelených; full suite **2048 passed, 1 skipped** (baseline 2028 + 20); ruff clean
- **Dokončeno:** 2026-11-07 | Commit: `35e3c77` — **Oblast Q rozšířena ★★** (Timesketch push)

### STP-060 — Oblast O+Q: Timesketch push UI (GUI tlačítko v Interop Export Center)
- **Oblast:** O (User Interface) + Q (Interop) | **Priorita:** P3 | **Stav:** DONE
- **Popis:** GUI vrstva nad hotým Timesketch push API (STP-059). **(A)** `index.html` — nová karta `#ts-push-card` v modulu Interop Exporty: popis + tlačítko `#btn-ts-push` („🚀 Push do Timesketch“) + stavový výstup `#ts-status`; reuse existujícího selectu `#ix-what` (dataset). **(B)** `js/components/interop.js` — wiring `btn-ts-push.onclick`: POST `/api/cases/{id}/timesketch-push` s body `{what}`, busy stav (disabled + „Odesílám…“), úspěch → `✓ Push hotovo — sketch N, timeline M, záznamů K` + toast, selhání → `✗ Push selhal: <msg>` + toast, `finally` reaktivace tlačítka. Stejný vzorec jako ostatní POST moduly (ai.js/files.js).
- **Závislosti:** STP-059 (Timesketch push API), E5 DOM test vzor (`tests/js/graph.test.mjs`)
- **Dotčené moduly:** `src/stopa/web/static/index.html`, `src/stopa/web/static/js/components/interop.js` (+25 ř.), `tests/js/interop.test.mjs` (nový, 5 DOM testů)
- **Testy:** JS DOM **5/5 passed** (`node tests/js/interop.test.mjs`: wiring onclick, POST kontrakt, úspěšný stav, selhání + reaktivace, busy disabled); full suite **2048 passed, 1 skipped** bez regresí; ruff clean
- **Dokončeno:** 2026-11-07 | Commit: `ddb3aa0` — **Oblast O rozšířena ★** (Timesketch push UI)

### STP-061 — Oblast Q ★★: Timesketch timeline status (live polling)
- **Oblast:** Q (Interop) | **Priorita:** P3 | **Stav:** DONE
- **Popis:** Read-only vrstva pro live stav indexace naposledy pushnuté timeline. **(A)** `data/timesketch_client.py` — nová metoda `timeline_status(sketch_id, timeline_id)`: GET `/api/v1/sketches/{sid}/timelines/{tid}/`, nested parsing `objects[0].status.status` (kontrakt ověřený z oficiálního Timesketch zdroje), vrací `{status, updated_at}`, hájí `TimesketchError`/`TimesketchUnavailable`. **(B)** `web/app.py` — read-only endpoint `GET /api/cases/{case_id}/timesketch-status`: RBAC `case.read`, najde poslední audit záznam `timesketch_pushed` → dotáže Timesketch; 404 bez pushu, 503 nedostupná, 502 selhání dotazu.
- **Závislosti:** STP-059 (Timesketch push + audit záznam), E11 MockTransport vzor
- **Dotčené moduly:** `src/stopa/data/timesketch_client.py` (+metoda), `src/stopa/web/app.py` (+endpoint), `tests/test_stp061.py` (nový, 10 testů)
- **Testy:** **10/10 passed** (`tests/test_stp061.py`: klient ready/processing/chybové cesty + web E2E 404/503/200/502); full suite **2058 passed, 1 skipped** (+10) bez regresí; ruff clean
- **Dokončeno:** 2026-11-08 | Commit: `8c02098` — **Oblast Q rozšířena ★★** (Timesketch live status)
