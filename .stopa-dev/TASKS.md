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
