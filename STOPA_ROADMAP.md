# STOPA — ROADMAP (kořenový výstup MASTER PROMPT)

**Datum:** 2026-11-03 · **Commit:** `e227929` · **Verze aplikace:** 0.1.0
Dlouhodobá vývojová mapa, oblasti A–Q. Stav vychází ze zdrojového kódu a testů — žádný smyšlený stav,
každá položka je doložitelná v kódu/testech/auditu. Autoritativní detail: `.stopa-dev/ROADMAP.md` (tento soubor je jeho kořenová zrcadlová verze).

## A. Core Architecture
- **Stav:** ✅ hotovo (ETAPA C dokončena ★★ — rozklad monolitu `db.py`) | **Priorita:** P1
- **Dokončeno:** Evidence Model + Lineage, Integrity (SHA-256/MD5, Ed25519 podpisy, hash-chained audit log), Reproducibility Engine, Benchmark Engine (detekce regresí >20%), C3 Parser Validation Registry (13 parserů, 1:1 sync s pipeline). **ETAPA C vlna 1 hotová (STP-039):** vyčleněny `CaseRepository` + `FileRepository` + `AuditRepository` (+ `_helpers.py`), facade `CaseDB` deleguje na sdílenou connection, backward compat zachován; `db.py` 2090 → **1565 řádků**. **ETAPA C vlna 2 hotová (STP-040):** vyčleněny `ArtifactRepository` + `EntityRepository`, facade deleguje ~23 metod, backward compat zachován; `db.py` 1565 → **1011 řádků**. **ETAPA C vlna 3 hotová (STP-041):** vyčleněny `schema.py` (SCHEMA_VERSION + DDL) a `migrations.py` (legacy migrace), facade úklid; `db.py` 1011 → **476 řádků** — celkem ~2090 → 476 = **−77 %**, cíl < ~600 splněn ★.
- **Nedokončeno:** — (ETAPA C dokončena; SHA-512 v integrity vrstvě hotové STP-022).
- **Závislosti:** — | **Nejbližší úkol:** volba ETAPY D (audit reálného stavu oblastí B/C/G/I/M)

## B. Evidence Acquisition
- **Stav:** ✅ hotovo | **Priorita:** P1
- **Dokončeno:** EWF/libewf (`EWF available: True`), RAW/IMG přes TSK (pytsk3 + CLI fallback), FDE dešifrování (AES-CBC/FBE, LUKS), ingest s chain of custody.

## C. Filesystem Analysis
- **Stav:** ✅ hotovo | **Priorita:** P1
- **Dokončeno:** NTFS/FAT/APFS přes TSK, MFT, carving + volný prostor (`domain/carving.py`, `sqlite_carver.py`), USN Journal parser.

## D. Artifact Engine
- **Stav:** ✅ hotovo (ETAPA B, vlny 1–15) | **Priorita:** P0
- **Dokončeno:** 76 parser modulů; C3 registry **76 verzovaných parserů**; ETAPA B vlny 1–15 hotové — vlna 1 (email mbox/EML, WiFi WLAN XML, Scheduled Tasks XML, netstat/connstat text, Clipboard registry, SID extraction) `afc49a0`; vlna 2 (Google Search/Location/Login History + Account Info, memory scan CmdScan/FileScan, DDG Current Tabs, MSN Messenger); vlna 3 (Kik Messenger, Mail.ru Agent, Bebo Live Chat, Chatroulette, LimeWire/Limerunner/Luckywire P2P); **vlna 4** (STP-026): DDG cookies, DDG allowlisted websites, OpenOffice/LibreOffice Base (.odb), iOS parked car locations, iOS voicemail, Windows UserAssist MRU; **vlna 5** (STP-027): Google Aggregated Activities + Identity Sessions, Google Maps Activity (semantic location history), Google Chat rodina (Chat/Hangouts/PlusChat/Talk Takeout JSON), Google Account metadata (change history/devices/export summary), Drive Activity, Samsung Voice Recording; **vlna 6** (STP-028): Google Photos (Takeout/warrant JSON), Google Mail Message Information (Gmail warrant return), Google Bar (Chrome History `search_terms`), Attachment Extractor (MIME/RFC822 přílohy); **vlna 7** (STP-029): Google Chrome Bookmarks (Bookmarks JSON, date_added µs/1601), Google Chrome History Warrant Return (visit_time µs/1601), Google Contacts Warrant Return (Takeout/warrant JSON + People API fallback), Google Chrome Autofill/Contact Info (name/email/adresa), Skype Warrant Return (4 subtypy s auto-detekcí: account/chat/connection/contacts); **vlna 8** (STP-030): Google Chrome Preferences (extensions/search/sync → browser_extension/browser_setting), Cloud Drive soubory (Google/OneDrive/Apple, provider auto-detekce), Google Voice Warrant Return (4 subtypy: SMS/voicemail/kontakty/předplatitel), Windows Drivers (paměťový dump, anomaly unsigned_driver) + pipeline retry na celé cestě pro Takeout soubory se generic názvy; **vlna 9** (STP-031): memory forensics — Memory Processes (PsxView EPROCESS/PEB mismatch → `psxview_mismatch`), Memory Network Connections, Memory Handles (hex normalizace handle value), Memory Modules (Malfind skryté moduly → `hidden_module` / DLL injection), Memory API Hooks & Callbacks; dispatch PŘED netstatem (sdílená klíčová slova connections/sockets); **vlna 10** (STP-032): cloud SNS exporty — Instagram Direct Messages (DM konverzace, sdílená média → share), Instagram Posts/Media/Stories/Comments (`sns_post`/`sns_comment`, stories detekce), Instagram Account Actions/History/Followers (`event_log_entry` + `contact` sns:instagram), Snapchat Warrant Return (zprávy/skupiny/přátelé/geolokace/IP historie/info o účtu, auto-detekce subtypu); **nový `_sns_prepass()` na celé cestě PŘED basename chainem** (generic basenames photos.json/messages.json kolidují s Google detektory; account PŘED posts — „AccountHistory" obsahuje substring „stor(y)"); **vlna 11** (STP-033): cloud SNS exporty — Twitter/X Posts (`sns_post`, retweety/odpovědi post_type), Twitter/X Direct Messages (konverzační i flat formát → `chat_message`), Twitter/X Users (sociální graf → `contact` sns:twitter, relationship account/follower/following), Facebook Warrant Return (Messenger zprávy/přátelé/timeline/profil, auto-detekce sekcí); pre-pass rozšířen o 4 nové detektory bez kolizí; **vlna 12** (STP-034): cloud-export Microsoft + Amazon — Microsoft Contacts (`contact`), Outlook Mail PST export (`email_message`), Teams Conversations (`chat_message`), Teams Teams & Members (`contact` sns:microsoft:teams), Outlook Calendar (`calendar_event`), SharePoint Warrant Return (strany → `web_page`, dokumenty → `document`), Amazon CloudTrail API akce (`event_log_entry`), Amazon EC2 instance + S3 objekty (`network_connection`/`file_metadata`); pre-pass rozšířen o 8 MS+Amazon detektorů (specifické PŘED obecnými, conversations PŘED teams); **vlna 13** (STP-035): cloud-export Google II + Box/Dropbox/Mega — Google Calendar Events WR/Takeout (`calendar_event`), Google Keep Notes + Tasks (`document_metadata` kind=keep_note|task), Box Cloud soubory/složky/enterprise+audit eventy (`document_metadata` kind=file|folder|comment|event), Dropbox + Mega položky (provider auto-detekce → `document_metadata`); **11 čistých flipů bez nového kódu** (existující parsery už typy pokrývaly: iMessage cloud, Google Photos ×2, Gmail Messages WR, Chat/Chats/Hangouts, Google Activity, Semantic Location History ×2); **vlna 14** (STP-036): dokončení cloud-export kategorie — Apple Cloud rodina (Contacts/Keychain/Mail/Photos/Backup, auto-detekce podtypu), Google 2025 WR (AccessLogDevices + AccountTargetAssociation + Calls), WhatsApp Chats + Backups, generic cloud metadata (AccountsInfo/ConnectedApps/RecentDevices/Timeline/Passwords/AndroidBackups/AzureVM), Gmail Messages, Maps Labeled Places WR; pre-pass rozšířen o 6 detektorů (specifické PŘED obecným `cloud_generic`, Apple vyžaduje `.json` — nekrade iMessage TSV); **vlna 15** (STP-037): ZÁVĚREČNÝ AUDIT ETAPY B — `tests/test_etapa_b_final_audit.py` (13 invariantních testů: bijekce matice ↔ AXIOM RE reference, SUPPORTED/DEPRECATED/NOT_SUPPORTED rozdělení, C3 registry 76 parserů s existujícími test_files, pipeline dispatch sync). Coverage: **covered 198 / 232** unikátních AXIOM typů ★ — ETAPA B dokončena.
- **Nedokončeno:** portable-local zbývá **0 typů** ★ (všechny lokální pokryty); memory **0 typů** ★ (vyzerovala vlnou 9); cloud-export **0 typů** ★ (vyčerpano vlnou 14 — celá kategorie dokončena); base-class 34 (rozhraní, ne extraktory).
- **Závislosti:** pipeline dispatch + C3 registry sync | **Nejbližší úkol:** ETAPA B dokončena (STP-037, vlna 15) — další: volba oblasti pro ETAPU C (např. E Advanced Timeline / F Evidence Graph / N Performance)

## E. Advanced Timeline
- **Stav:** ✅ hotovo | **Priorita:** P2
- **Dokončeno:** timeline engine + anomálie (`timeline_anomaly.py`), Map/WorldMap covered. STP-018: **Timeline Intelligence 2.0** — `domain/timeline_intel.py` (rozpory `concurrent_activity` union-find, duplikáty napříč zdroji `cross_source_duplicate`, timestamp provenance `ts_origin` + klasifikace přesnosti), schéma v12, post-pass po ingestu + CLI/web, report podsekce 8.1, export rozšířen; 32 testů (`tests/test_timeline_intel.py`).
- **Nedokončeno:** — (základ + Intelligence 2.0 hotové)
- **Nejbližší úkol:** —

## F. Evidence Graph
- **Stav:** ✅ hotovo | **Priorita:** P2
- **Dokončeno:** Entity Resolution 2.0 (4 confidence levels, normalizace účtů, merge candidates), korelace s časovým rozmezí, web graph.js + endpoint merge-candidates.

## G. File Intelligence
- **Stav:** 🔧 částečně | **Priorita:** P3
- **Dokončeno:** file_meta (EXIF/PDF/OOXML/ID3/MP4), bad_extension detekce, dedupe, search filters.
- **Nedokončeno:** file preview v UI.

## H. AI Copilot
- **Stav:** ✅ P0 hotovo | **Priorita:** P2 (rozšíření)
- **Dokončeno:** I1 AI orchestrace (5 agentů, routing, fail-closed validace), I2 Forensic RAG (3 vrstvy, citace, prompt injection ochrana), LM Studio klient. AI = volitelná závislost. STP-019: PII redaktor před inference (`domain/pii_redaction.py`, toggle `ai_redact_pii`), audit modelových volání (I1+E11 do `analysis_operations`: model name + SHA-256 promptu), `STOPA_AI_GOVERNANCE.md`.
- **Nedokončeno:** AI grounding + detekce rozporů.
- **Nejbližší úkol:** — (AI grounding + detekce rozporů = budoucí P2)

## I. Validation Engine
- **Stav:** ✅ hotovo | **Priorita:** P2
- **Dokončeno:** C3 Parser Validation Registry (13 parserů), validační reporty per-artifact (ID+verze, status, confidence, provenance).
- **Nedokončeno:** UI Validation Center.

## J. Case Management
- **Stav:** ✅ základ hotov | **Priorita:** P3
- **Dokončeno:** cases DB (schema v12), chain of custody, audit trail, E3 resume/checkpointing. STP-022: RBAC minimální (`domain/rbac.py` — actor atribuce explicitní > examiner, `strict=`).
- **Nedokončeno:** Case Mgmt 2.0 (RBAC rozšíření).

## K. Export Engine
- **Stav:** ✅ hotovo | **Priorita:** P2
- **Dokončeno:** CSV/JSON exporty s manifestem pro reprodukovatelnost (`domain/export.py`). STP-023: **JSONL** (streamovací, 1 objekt/řádek), **XML** (deterministický ElementTree, UTF-8) a **STIX 2.1 bundle** (artefakty → file/message objekty + `x-stopa` rozšíření, deterministická UUIDv5 ID pro C4 reprodukovatelnost); CLI `--format csv|json|jsonl|xml|stix`.
- **Nedokončeno:** Plaso formát (volitelné).

## L. Report Engine
- **Stav:** ✅ hotovo | **Priorita:** P1
- **Dokončeno:** HTML report **20 sekcí** (chain of custody, artifacty, findings, manifest SHA-256 + Ed25519 podpis, audit trail, timeline, korelace; STP-020: titulní strana, metodika, nástroje+verze, omezení, závěr, provenience timestampů, lineage, integrity, rejstřík entit, přílohy A/B/C), PDF přes weasyprint (volitelné).
- **Nedokončeno:** — (20 sekcí hotové)
- **Nejbližší úkol:** —

## M. Security
- **Stav:** 🔧 v průběhu (ETAPA E — izolace parserů / sandbox; **vlna 1 hotová ★** STP-046) | **Priorita:** P2
- **Dokončeno:** Ed25519 podpisy, hash chaining audit logu, prompt injection ochrana RAG. STP-022: SHA-512 v integrity vrstvě (audit chain `algo=`, per-algorithm GENESIS, manifesty opt-in), SHA-512 v pipeline (FORENSIC profil, one-pass hashing, dedupe + hash lookup), report CoC +SHA-512 sloupec, RBAC minimální (`domain/rbac.py` — actor atribuce explicitní > examiner, `strict=`), pip-audit CI job `security`.
- **Nedokončeno:** izolace parserů (sandbox) — **STP-045 audit prokázal reálný hang**: poškozený SQLite soubor (garbage `db_size_pages` = 1.7 mld. stránek v 920 B souboru) visí >15 s v `sqlite_carver.recover_rows` a zastaví celou pipeline; parsery běží přímo ve worker vláknech bez izolace, nativní extenze (PIL/openpyxl/cryptography/regipy) v hlavním procesu.

## N. Performance
- **Stav:** ✅ hotovo | **Priorita:** P2
- **Dokončeno:** ThreadPoolExecutor paralelizace pipeline, benchmark engine s detekcí regresí. STP-021: stream parsing velkých E01/AFF4 (`stream_to_raw` — chunked 1 MiB, RAM peak z GB na ~1 MiB), byte-level progress v `process_disk_image`.
- **Nedokončeno:** CI běh benchmarku.

## O. User Interface
- **Stav:** ✅ základ hotov | **Priorita:** P3
- **Dokončeno:** FastAPI 30 endpointů + vanilla JS SPA (dark mode), graph.js. STP-021: Processing Monitor — `GET /api/cases/{id}/processing` + async ingest (`background=true`) s živým progress v status baru.
- **Nedokončeno:** Validation Center / Audit Center moduly.

## P. Quality Assurance
- **Stav:** ✅ hotovo (ETAPA D dokončena ★★ — CI benchmark job + E2E testy + dokumentace) | **Priorita:** P1
- **Dokončeno:** 1813 testů plně offline (syntetické fixtures), ruff clean, deterministická coverage matice, DEV OS projektová paměť (`.stopa-dev/`). STP-022: CI pipeline `.github/workflows/ci.yml` (lint + pytest + JS DOM + pip-audit security job). Benchmark engine (`domain/benchmark.py` + `data/benchmark_engine.py`, CLI `stopa benchmark`) s detekcí regresí >20 %. **STP-043: CI job `benchmark`** — běh engine suite=all (77 položek) proti versionované baseline `benchmarks/baseline.json`, fail na regresi >20 % a ≥0.5 ms (CI noise guard), upload výsledků jako artifact. **STP-044: E2E subprocess testy** (`tests/test_stp044_ci_benchmark_e2e.py`, 6) + dokumentace `docs/STOPA_BENCHMARKS.md` (workflow, prahy a proč, baseline update, report/artifact).

## Q. Interoperability
- **Stav:** 🔧 částečně | **Priorita:** P3
- **Dokončeno:** TSK/libewf integrace, iMessage cloud CSV/XLSX, mobilní logical exporty. STP-023: **STIX 2.1 výstup** (společné s K — `to_stix_bundle`, deterministická UUIDv5 ID).
- **Nedokončeno:** UCO mapping (nad STIX), Plaso import.

---

## ETAPA C — ROZHODNUTÍ O SMĚRU (STP-038, 2026-11-04)

**Kontext:** ETAPA B (Artifact Engine, oblast D) dokončena vlnou 15 (STP-037). Všechny P0 úkoly hotové;
full suite **1742 passed, 1 skipped**; C3 registry **76 parserů**; covered **198 / 232 ★**.

**Audit reálného stavu (ověřeno v kódu, ne jen roadmapě):** několik „Nedokončeno" položek bylo
mezitím dokončeno a roadmapu jsem synchronizoval — E Timeline Intel 2.0 ✓ (STP-018), L report
**20 sekcí** ✓ (STP-020), H PII redactor + governance ✓ (STP-019), J RBAC minimální ✓ (STP-022),
K/Q STIX 2.1 + JSONL/XML ✓ (STP-023), N/O stream parsing + Processing Monitor ✓ (STP-021).

**Co reálně zbývá (pořadí podle priority):**
| Priorita | Oblast | Zbývající práce |
|---|---|---|
| **P1** | A Core | rozdělení monolitu `db.py` (~2090 ř., 67 metod → doménová repozitáře) |
| P1 | P QA | CI běh benchmarku (job `benchmark` v ci.yml) |
| P2 | M Security | izolace parserů (sandbox) |
| P2 | H AI | AI grounding + detekce rozporů |
| P2 | I/O UI | Validation Center / Audit Center moduly |
| P3 | G/J/K/Q | file preview, Case Mgmt 2.0, Plaso, UCO mapping |

**ROZHODNUTÍ — ETAPA C = oblast A (Core Architecture): rozdělení monolitu `db.py` na doménová repozitáře.**
Důvody: (1) nejvyšší zbývající priorita **P1**; (2) největší technický dluh ovlivňující všechny ostatní oblasti;
(3) čistě definovaný rozsah — 67 metod `CaseDB` → doménová repozitáře podle Clean Architecture;
(4) inkrementální a plně testovatelné vlny (každá vlna drží full suite zelenou).

**Plán vln ETAPY C:**
- **Vlna 1 (STP-039):** ✅ **hotová** — extrakce `CaseRepository` + `FileRepository` + `AuditRepository`
  (~28 metod: case/source/custody, file/flags/marked, audit log/operations/integrity checkpoints);
  `CaseDB` deleguje; facade zachován pro backward compat. `db.py` 2090 → **1565 řádků** (−525), full suite **1757 passed**.
- **Vlna 2 (STP-040):** ✅ **hotová** — extrakce `ArtifactRepository` + `EntityRepository`
  (~23 metod: artifacts/findings/timeline events/intel groups, entities/correlations/lineage);
  `CaseDB` deleguje; facade zachován pro backward compat. `db.py` 1565 → **1011 řádků** (−554), full suite **1774 passed**.
- **Vlna 3 (STP-041):** ✅ **hotová** — extrakce `schema.py` (SCHEMA_VERSION + DDL) a `migrations.py`
  (legacy migrace: audit chain backfill, entity CHECK rebuild, timeline intel sloupce), facade úklid;
  `CaseDB` = tenký agregátor 5 repozitářů. `db.py` 1011 → **476 řádků** (−535), full suite **1792 passed**.

**Akceptační kritéria ETAPY C:** `db.py` < ~600 ř.; každé repozitářové modulu vlastní testy;
žádná změna veřejného API `CaseDB` (backward compat); full suite zelená po každé vlně; ruff clean.

**ETAPA C DOKONČENA ★★ (2026-11-04)** — všechny 3 vlny hotové, cíl < ~600 ř. splněn (476 ř.),
backward compat zachován, full suite **1792 passed, 1 skipped**. Další = volba ETAPY D.

## ETAPA D — ROZHODNUTÍ O SMĚRU (STP-042, 2026-11-04)

**Kontext:** ETAPA C (Core Architecture, oblast A) dokončena vlnou 3 (STP-041). `db.py`
~2090 → **476 ř.** (−77 %), full suite **1792 passed, 1 skipped**; C3 registry **76 parserů**;
covered **198 / 232 ★**.

**Audit reálného stavu kandidátů (STP-042):**
| Oblast | Stav v kódu | Rozsah | Priorita |
|---|---|---|---|
| **P QA — CI benchmark job** | Benchmark engine hotový (`domain/benchmark.py` 95 ř. + `data/benchmark_engine.py` 267 ř., CLI `stopa benchmark`, detekce regresí >20 %); CI má lint+test+security, **benchmark chybí**; baseline soubor neexistuje | malý–střední (CI job + baseline + testy) | **P1** |
| M Security — sandbox parserů | `domain/sandbox*` neexistuje; parsery běží v hlavním procesu | velký (subprocess/namespace izolace) | P2 |
| H AI Copilot — grounding | `ai_assistant.py` má citace (`CITATION_RE`, `extract_citations`), ale žádná detekce rozporů | střední–velký (LLM volání, heuristiky) | P2 |
| I+O Validation/Audit Center UI | `validation_registry.py` existuje; UI moduly chybí | velký (SPA + endpointy) | P2/P3 |
| G File preview / J Case Mgmt 2.0 / K Plaso / Q UCO | částečně/neexistují | střední–velký | P3 |

**ROZHODNUTÍ — ETAPA D = oblast P (Quality Assurance): CI běh benchmarku proti baseline.**
Důvody: (1) **jediný zbývající P1 úkol**; (2) nejmenší rozsah s největším dopadem —
benchmark engine už je hotový a testovaný, chybí jen jeho zapojení do CI;
(3) chrání ETAPU C (refactor `db.py`) i budoucí vlny před tichou regresí výkonu;
(4) čistě definovaný rozsah: CI job + baseline artefakt + deterministické testy.

**Plán vln ETAPY D:**
- **Vlna 1 (STP-043):** ✅ **hotová** — CI benchmark job: `.github/workflows/ci.yml` + `scripts/ci_benchmark.py`:
  běh `run_benchmark(suite="all")` (77 položek, ~0.25 s), porovnání s baseline (`benchmarks/baseline.json`) přes
  `detect_regressions(threshold=0.20)`, fail na regresii >20 % a ≥0.5 ms (**CI noise guard** — relativní práh je pod
  ~1 ms křehký; měření ukázalo falešné pozitivní, např. +22.7 % = šum 5 µs), upload výsledků jako artifact;
  inicializace baseline z lokálního běhu (verze 1). Full suite **1807 passed** (+15 testů `test_stp043_ci_benchmark.py`).
- **Vlna 2 (STP-044):** ✅ **hotová** — E2E subprocess testy `tests/test_stp044_ci_benchmark_e2e.py` (6): běh
  `scripts/ci_benchmark.py` jako skutečný subprocess (stejný způsob jako GitHub Actions) s dočasnou baseline —
  první běh bez baseline (exit 0), `--update-baseline`, běh proti vlastní baseline (exit 0, noise guard), umělá
  regrese na položce ≥1 ms (baseline /2 → exit 1 + REGRESIE na stderr), poškozená baseline (exit 2), artifact výstup
  identický se stdout reportem; dokumentace `docs/STOPA_BENCHMARKS.md` (workflow, prahy a proč, baseline update,
  report/artifact) + README odkaz. Full suite **1813 passed** (+6 testů).

**Akceptační kritéria ETAPA D:** CI job `benchmark` běží po lint/test; regrese >20 % failuje build;
baseline je versionovaný artefakt v repozitáři; testy offline (bez sítě); full suite zelená; ruff clean.

**ETAPA D DOKONČENA ★★ (2026-11-04)** — CI job `benchmark` aktivní, baseline artefakt versionován
(`benchmarks/baseline.json`, verze 1), E2E testy + dokumentace hotové; full suite **1813 passed, 1 skipped**, ruff clean.
Další = volba ETAPY E (kandidát M Security sandbox P2).

**Co reálně zbývá po ETAPĚ D (pořadí podle priority):** P2 M sandbox / H AI grounding /
I+O Validation+Audit Center → P3 G file preview / J Case Mgmt 2.0 / K Plaso / Q UCO.

## ETAPA E — ROZHODNUTÍ O SMĚRU (STP-045, 2026-11-05)

**Kontext:** ETAPA D (Quality Assurance, oblast P) dokončena vlnou 2 (STP-044). CI benchmark
job aktivní s baseline artefaktem + E2E testy; full suite **1813 passed, 1 skipped**; C3 registry
**76 parserů**; covered **198 / 232 ★**.

**Audit reálného stavu kandidátů (STP-045) — ověřeno v kódu + empirickým probe:**
| Oblast | Stav v kódu | Rozsah | Priorita |
|---|---|---|---|
| **M Security — sandbox parserů** | Parsery běží přímo ve worker vláknech (`pipeline._process_file_worker` → `_extract_artifacts_for`, bez try/except na úrovni extraktoru); nativní extenze (PIL, openpyxl, cryptography, regipy) v hlavním procesu; **empirický probe: poškozený SQLite soubor visí >15 s** (`sqlite_carver.recover_rows` — garbage `db_size_pages` = 1.7 mld. stránek v 920 B souboru → nekonečná smyčka) | velký (subprocess izolace + timeout + result marshalling) | **P2** |
| H AI Copilot — grounding | `ai_assistant.py` má citace (`CITATION_RE`, `extract_citations` validuje ID proti DB), ale žádná detekce rozporů mezi odpovědí a artifacty; LLM volání = externí závislost (LM Studio) | střední–velký (heuristiky + prompt engineering, méně deterministické testy) | P2 |
| I+O Validation/Audit Center UI | `validation_registry.py` existuje (76 parserů); web má 30+ endpointů ale žádný Validation/Audit modul v SPA | velký (SPA moduly + endpointy + JS DOM testy) | P2/P3 |

**ROZHODNUTÍ — ETAPA E = oblast M (Security): izolace parserů (sandbox).**
Důvody: (1) **nejvyšší zbývající priorita P2** a zároveň největší dopad na spolehlivost —
audit prokázal, že jeden poškozený soubor dokáže zastavit celou pipeline (reálný hang, ne teorie);
(2) forenzní nástroj zpracovává **neověřený vstup** (diskové obrazy, registry hives, EVTX) —
bez izolace je každý parser potenciální vektor crashu/hangu/DoS; (3) čistě definovaný rozsah:
subprocess wrapper + timeout + deterministické testy s umělým hangujícím parserem;
(4) chrání ETAPY B–D (76 parserů, 1813 testů) před regresí spolehlivosti.

**Plán vln ETAPY E:**
- **Vlna 1 (STP-046):** ✅ `domain/sandbox.py` + `sandbox_worker.py` — čistá logika: definice sandbox kontraktu
  (parser → subprocess s timeout, JSON marshalling výsledků), detekce dostupnosti backendu
  (subprocess fallback), konfigurace limitů (timeout_s, max_result_bytes). Commit `91854d8`,
  full suite **1834 passed, 1 skipped** (+21 testů).
- **Vlna 2 (STP-047):** zapojení do pipeline — `_extract_artifacts_for` přes sandbox wrapper
  (per-parser timeout + catch → `parser_error` artifact místo crashu), fix reálného hang bugu
  v `sqlite_carver.recover_rows` (validace `db_size_pages` proti velikosti souboru).
- **Vlna 3 (STP-048):** testy + dokumentace — deterministické testy s umělým hangujícím parserem,
  corrupt-file regression testy (SQLite/EVTX/LNK), `docs/STOPA_SANDBOX.md`.

**Akceptační kritéria ETAPA E:** žádný parser nesmí zastavit pipeline (timeout + catch);
poškozený soubor → `parser_error` artifact, ne crash; deterministické testy offline;
full suite zelená po každé vlně; ruff clean.

**Co reálně zbývá po ETAPĚ E (pořadí podle priority):** P2 H AI grounding / I+O Validation+Audit Center → P3 G file preview / J Case Mgmt 2.0 / K Plaso / Q UCO.

