# ROADMAP STOPA 2.1 — Komplexní audit, bezpečnostní zpevnění a strategický rozvoj

**Zdroj požadavků:** [`STOPA_2_1_MASTER_PROMPT.md`](./STOPA_2_1_MASTER_PROMPT.md) (master prompt od externího evaluátora).
**Výchozí stav:** Release 2.0 GA, commit `4a3a867`, suite **3652 passed / 1 skipped**, Ruff clean, schema v19.
**Zásadní pravidla (z master promptu):** audit před refaktorem; malé kontrolované změny; každý nález s označením VERIFIED / PARTIALLY VERIFIED / IMPLEMENTED / NOT IMPLEMENTED / BLOCKED / N/A; destruktivní operace a změny datových kontraktů vyžadují souhlas uživatele; testy deterministické a offline.

> Stav níže je **ověřený stav kódu v `4a3a867`** (soubory + tabulky), ne popis z dokumentace. Ověřeno: `src/stopa/models.py`, `domain/evidence_model.py`, `data/schema.py` (SCHEMA_VERSION=19), `data/plugin_loader.py`.

---

## 0. Inventura — co už STOPA 2.0 má (ověřený stav vs. master prompt)

| Master prompt fáze | Stav v 2.0 GA | Důkaz (soubor/tabulka) | Chybí (gap) |
|---|---|---|---|
| F2 Evidence Provenance Engine | **PARTIALLY IMPLEMENTED** | `domain/evidence_model.py::Provenance` (parser_id, parser_version, extracted_at, offset, record_ref); `artifacts.provenance_json`; `lineage_events` (C2: tool_version, config_hash, input/output refs); `analysis_operations` (C5: stopa_version, parser_versions_json, config_hash, outputs_json) | per-file čas výpočtu hash; metadata akvize u sources (nástroj+verze); explicitní parent_artifact_id pro odvozené artefakty |
| F3 Immutable Evidence Ledger | **IMPLEMENTED** (jádro) | `audit_log` append-only via SQL triggery + hash chain (`prev_hash`, `hash`) — C4; `integrity_checkpoints` = Ed25519 podpis posledního audit řádku | kanonická serializace dokumentovaná; CLI pro ověření celé historie z jednoho příkazu; externí časová razítka (RFC 3161) |
| F4 Integrita/Merkle/pečeti | **IMPLEMENTED** | `case_seals` (Merkle root_hash + Ed25519 signature_b64 + public_key_b64 snapshot); F5.2 signovaný report; `domain/case_seal.py`, `domain/integrity.py` | správa/rotace/obnova klíčů; ověření podpisu na jiném zařízení (CLI); verzování kryptografických metadat; migrace na nové hash algoritmy bez znehodnocení historie |
| F5 Forensic Assurance Center | **NOT IMPLEMENTED** (jako sjednocené UI) — data existují rozptýleně | data: case_seals, integrity_checkpoints, audit_log, findings.confidence_level, artifact_reviews, parser registry | jeden přehledový dashboard s vysvětlovatelnými stavy (ne jen zelená/červená ikona) |
| F6 Parser Quality Framework | **PARTIALLY IMPLEMENTED** | `validation_registry.py` (~1 095 ř.); F5.5 Daubert pack (22 referencí); C5 reparse engine (exit codes 0/1/2) | per-parser stav validace + testovací pokrytí jako data; Parser Validation Lab UI; differential testing design |
| F7 AI Forensic Intelligence 2.0 | **PARTIALLY IMPLEMENTED** | `intelligence/tool_agent.py` (ToolSpec registry, tool calling); Finding s povinnou provenance + `ConfidenceLevel` 5 úrovní (AI grounding); F3.1–F3.5 (profily, NL→SQL, právní docs, hypothesis graph) | role agentů s minimálními oprávněními; retry/backoff/jitter; token limity; prompt-injection ochrana; evaluační sada; audit AI výstupů v ledgeru |
| F8 Frontend/UX | **DUALITY VERIFIED** | React SPA (`frontend/` → build do `web/static/spa/`) + legacy static UI (`web/static/app.js`, `index.html`, `js/components/modules.js`); část funkcí (ATT&CK heat-mapa, Daubert) jen v legacy | feature parity mapa; migrace po modulech; React jako jediný kanonický frontend |
| F9 Plugin Security | **IMPLEMENTED** (základ) — izolace slabá | `data/plugin_loader.py::sandbox_exec`: subprocess + RLIMIT_AS + timeout; allowlist `plugins_verified`; `domain/plugins.py` manifest validace (TypeError/ValueError sémantika, max 50 kapacit) | read-only přístup k důkazům; izolovaný workdir (CLI dnes posílá `workdir=None` = host cwd!); omezení CPU/NOFILE/výstupu; síťová izolace; SemVer plugin API; podepisování balíčků |
| F10 Datová vrstva a škálování | **IMPLEMENTED** (single-node) | SQLite per case (`cases/<id>.db`), WAL, `stopa_instance.db` pro RBAC (orgs/teams/users/case_members); volitelné DuckDB OLAP; LiveEventBus bez Redis | benchmarky před/po; tenancy isolation audit; zálohování/obnova dokumentované; multi-instance bus |
| F11 Refactoring velkých modulů | **RIZIKO VERIFIED** | `cli.py` 4 433 ř.; `web/app.py` 3 310 ř.; `pipeline.py` ~1 532 ř.; `validation_registry.py` ~1 095 ř.; `db.py` 599 ř. (budget <600 via meta-test) | characterization tests; postupná extrakce s kompatibilními importy/CLI |
| F12 Testování/QA/supply chain | **IMPLEMENTED** (jádro) | pytest 3652 offline deterministických; Ruff clean; CI `ci.yml`+`release.yml`; benchmark suite 80 workloadů s noise guardem | property-based (Hypothesis); fuzzing parserů; Playwright E2E; Bandit/Semgrep/Grype; cross-platform matrix; testy úniků paměti a crash recovery |
| F13 Capability Registry | **PARTIALLY IMPLEMENTED** | 9 optional extras s graceful degradation (`web, pdf, fde, tsk, stix, xlsx, meta, net, analytics`); lazy import + fallbacky | registry schopností (balíčky×platforma×stav); UI pravdivě rozlišuje 6 stavů dostupnosti; testy že fallback nezakrývá chybu |
| F14 Nové produktové schopnosti A–N | **NOT IMPLEMENTED** (kromě parciál: entities/correlations = zárodek Evidence Graph, hypothesis graph F3.5) | — | priorita + AK pro každou; neimplementovat všechny automaticky |

---

## P0 — Kritické základy (nejprve; podle master promptu upraveno o reálná zjištění)

### P0-1 · Evidence Provenance Engine — hardening existujícího C1/C2/C5
**Stav:** ✅ **hotové (jádro)** — schema **v21** (aditivní `files.hashed_at`, `custody_items.acquisition_tool/tool_version/verified_hash`, `artifacts.parent_artifact_id` self-FK) + idempotentní migrace pro case DB ≤ v20; čistá doména `domain/provenance_chain.py` (gaps vs. warnings, deterministické chronologické řazení); `data/provenance_repository.py`; CLI `stopa provenance <case> <artifact>` (exit **0** kompletní / **1** neznámý artefakt / **2** mezery) + Web `/api/cases/{id}/artifacts/{aid}/provenance`; testy **41/41 green** + živý CLI E2E.
**Přínos:** dohledatelný řetězec ZDROJ → AKVIZE → OVĚŘENÍ → PARSER → ARTEFAKT → ANALÝZA → REPORT.
**Změny (additive, zpětná kompatibilita):**
1. `files` +kolumna `hashed_at TEXT` (+ metadata: kdy se hash počítal) — additive s defaultem NULL = staré řádky nezměněny
2. `sources`/`custody_items` +metadata akvize: `acquisition_tool`, `tool_version`, `verified_hash` (hash v okamžiku nabytí vs. aktuální → detekce změny originálu)
3. `artifacts` +kolumna `parent_artifact_id TEXT NULL` (explicitní vazba odvozeného artefaktu)
4. Doménový modul `domain/provenance_chain.py`: stavěný řetězec z lineage_events+analysis_operations; funkce `chain_complete(artifact)` → completeness report (co chybí: hash? parser verze? akvize?)
5. CLI `stopa provenance <artifact_id>` (JSON) + Web endpoint `/api/cases/{id}/artifacts/{aid}/provenance`
6. Migrace v20→v21 s testem zálohy/obnovy (pravidlo 9: additive = nízké riziko, ale plán migrace se sepíše) — **P0-2 obsadil v20** (`integrity_checkpoints.public_key_b64`)

**AK:** každý nový artefakt má ≥1 Provenance; `stopa provenance` vrátí kompletní řetězec pro referenční case; staré case DB bez nového kódu čitelné (default NULL); testy poškození řetězce.
**Velikost:** M · **Závislosti:** —

### P0-2 · Integrita a ověřování pečetí
**Stav:** ✅ **hotové (jádro)** — AES-GCM obal soukromého klíče (`STOPA_INTEGRITY_MASTER_KEY`), rotace-safe checkpoints (`integrity_checkpoints.public_key_b64`, schema v20 + migrace), CLI `integrity-keys` / `rotate-key`; 77/77 testů + živý E2E. Zbývá (volitelné): RFC 3161 timestamping, kanonická serializace dokument.
**Přínos:** nezávislá ověřitelnost pečetě i na jiném zařízení; správa klíčů.
1. CLI `stopa verify-seal --case <dir> [--key pub.b64]` — ověří Merkle root + Ed25519 podpis bez soukromého klíče (veřejný klíč je v case_seals.public_key_b64)
2. Klíčová správa: `~/.stopa/keys/` (soukromý+veřejný), rotace (`stopa key rotate`), export pro jiná zařízení; staré pečetě zůstanou ověřitelné (public key snapshot v řádku)
3. Dokument kanonické serializace + verzování kryptografických metadat (`case_seals.meta_json` → `format_version`)
4. RFC 3161 trusted timestamping = volitelná (offline režim nesmí záviset na síti); externí svědek dokumentován

**AK:** pečeť ověřitelná offline i na jiném zařízení s veřejným klíčem; rotace neznehodnotí historii; testy: změna/odstranění/přeuspořádání řádků detekovány.
**Velikost:** M · **Závislosti:** P0-1 (audit chain)

### P0-3 · Plugin sandbox hardening
**Přínos:** neověřený plugin nedokáže tichě psát do host cwd, spálit CPU nebo výstup.
**Ověřený defect:** CLI posílá `sandbox_exec(..., workdir=None)` → subprocess běží v **host cwd**.
1. Izolovaný workdir per run: `~/.stopa/plugin-runs/<name>-<ts>/` (auto-vytvoření; úklid při OK, zachování při chybě pro debug)
2. `SandboxLimits` +pole: `cpu_seconds`, `max_output_mb`; preexec_fn rozšířen o RLIMIT_CPU + RLIMIT_NOFILE (počítadlo fd proti file-descriptor exhaust)
3. Omezení velikosti stdout/stderr → jasné ValueError (ne memory blowup)
4. Síťová izolace (Linux): volitelný `network_isolated` flag → `unshare --net` pokud dostupná; jinak dokumentovaná omezení + env konvence `STOPA_PLUGIN_NO_NETWORK=1`; Windows = dokumentované limity
5. Read-only evidence: host předá cesty jako read-only symlinky do izolovaného workdiru (konvencí v1, bind mount v2)

**AK:** neověřený plugin bez oprávnění nenajde soubory host cwd; timeout CPU i wall-clock fungují; 3 sample pluginy prochází hardeningem bez změny chování; testy offline.
**Velikost:** M · **Závislosti:** —

### P0-4 · Forensic Validation Lab (Parser Quality Framework jádro)
**Stav:** ✅ **hotové (jádro)** — `domain/parser_status.py` + `data/parser_status_service.py`, CLI `stopa parser-status [--format json] [--fail-on-unvalidated]` (exit 0/1/2), Web `/api/parser-status` + UI sloupce Stav/Testy v Validation Center, design doc [`DIFFERENTIAL_TESTING.md`](./DIFFERENTIAL_TESTING.md); živý běh **78/78 parserů validováno**, test suite green.
**Přínos:** transparentní stav validace každého parseru — počet typů ≠ prokázaná ekvivalence s komerčními nástroji.
1. Per-parser záznam: validovaný/nevalidovaný, poslední úspěšná validace (ts), testovací pokrytí (počet testů), známé limity — v `validation_registry.py` jako data + CLI `stopa parser-status [--format json]`
2. Parser Validation Lab: Web přehled (počet parserů / validovaných / úspěšnost / regrese)
3. Differential testing design doc (referenční nástroje, normalizace výstupů, report rozdílných polí; „ani STOPA ani reference automaticky nemají pravdu“)

**AK:** každý z ~78 registrovaných parserů má stav validace viditelný v CLI+Web; testy: parser bez testu = `unvalidated`; differential design doc se schváleným workflow.
**Velikost:** M · **Závislosti:** —

### P0-5 · Threat model (THREAT_MODEL.md)
**Přínos:** jedna dokumentovaná mapa hrozeb s kontrolami — předpoklad pro P0-1..4 a F9/F7.
Rozsah: pluginy (neověřený kód), AI (prompt injection z analyzovaných dat, neověřené výstupy), Web API (RBAC, nedůvěryhodná data v UI), soubory (magic bytes vs. přípona, FDE obrazy), DB (per-case SQLite, instance DB), supply chain (extras).
**AK:** dokument se strukturovanými hrozbami (aktivní entita → hrozba → kontrola → zbytkové riziko); každá P0 položka odkazuje na svůj Threat ID.
**Velikost:** S · **Závislosti:** —

### P0-6 · Frontend sjednocení — strategie a parity mapa (`FRONTEND_MIGRATION.md`)
**Stav:** ✅ **hotové (dokument)** — parity mapa **19/19 legacy modulů** (✅ 3 / 🟡 6 / ❌ 10 → kroky S1–S10), migrační pořadí dle master promptu s AK per krok (každý = releasovatelný celek + rebuild SPA bundle), plán deprecace legacy UI. Implementační kroky S1–S10 = obsah etapy D/F.
**Přínos:** jedno kanonické UI; konec dvojího údržbářského režimu.
1. Feature parity mapa: každá funkce legacy UI → ekvivalent v React SPA (existuje/chybí/částečný) — **ověřený deficit:** ATT&CK heat-mapa + Daubert tlačítka jsou dnes jen v legacy
2. Migrační pořadí (z master promptu): 1. ATT&CK+threat intel → 2. Daubert/validace → 3. reporty/exporty → 4. evidence management → 5. timeline → 6. artifact viewer → 7. pluginy → 8. case mgmt → 9. AI workspace → 10. administrace
3. Legacy UI se odstraňuje až po prokázané parity + testech workflow

**AK:** parity mapa pokrytá 100 % funkcí legacy; každý migrační krok = samostatný releasovatelný celek s akceptačním kritériem; WS reconnect/souběh/test více instancí ověřen.
**Velikost:** S (dokument) + M (migrace v P1/P2) · **Závislosti:** —

---

## P1 — Zásadní rozvoj

| # | Položka | Obsah (STOPA-specific) | Velikost |
|---|---|---|---|
| P1-1 | Parser Quality Framework — ✅ **jádro + vlny 1–17 hotovy** (framework, pilotní sady sqlite/email_mbox, bázisové markry pro všechny parsery; vlna 2 Google Takeout rodina; vlna 3 cloud warrant rodina; vlna 4 MS+Amazon rodina; vlna 5 Chrome+Skype rodina; vlna 6 sociální rodina Twitter/Facebook; vlna 7 cloud SNS Instagram/Snapchat; vlna 8 memory forensics rodina (w9 JSON + mem_scan text); vlna 9 Windows forensics rodina — drivers/schedtask/jumplist/prefetch/USN, celá rodina plně pokrytá ve všech 8 kategoriích; vlna 10 Google Takeout/cloud export rodina — account_info/calendar_events/keep_tasks/voice_wr/location_history/login_history/search_history, celá sada plně pokrytá; vlna 11 Google rodina zbytek — account_change_history/aggregated_activities/chat_family/export_summary/identity_sessions/linked_devices/maps_activity + corrupted/locale, google_2025_wr + negative/locale, mail_info/photos + tz/encoding/locale/size, **celá Google rodina plně pokrytá ve všech 8 kategoriích (24/78 parserů plně)**; vlna 12 cloud export rodina — box_cloud/dropbox_mega/cloud_drive_files/icloud_messages + corrupted/encoding/locale/size/tz, cloud_generic + locale/negative; vlna 13 crypto extract + ddg current tabs + msn messenger — crypto_extract všech 8 kategorií (exchange CSV artefakty s CRYPTO_MAX_RECORDS=20_000 truncation, K1 scan s latin-1 fallback a PII guard), ddg_current_tabs/msn_messenger + {boundary, corrupted, encoding, locale, size, tz}; vlna 14 chat/network/P2P/WLAN rodina — bebo_chat/chatroulette/net_connections všech 5 chybějících kategorií (tz ekvivalence text/epoch/ISO formátů na stejný UTC epoch, latin-1 → U+FFFD fallback, netstat header scan prvých 2048 B), limewire_p2p/wifi_wlan + {encoding, locale, size, tz} (pipe vs JSON s prioritou limerunner > limewire > luckywire, WLANProfile XML iso-8859-1, MAC dedup+uppercase, truncation na 50 profilů); vlna 15 Windows/Apple system core rodina — chrome_preferences/plist/registry_hive/evtx/lnk všech chybějících kategorií (chrome JSON BOM→ValueError „Neplatné JSON" + MAX_EXTENSIONS_PER_FILE=2000 truncation + snapshot timestamp=None, plist naive datetime passthrough (FMT_BINARY epocha 2001) + MAX_DATE_ARTIFACTS=50/MAX_TOP_KEYS=30, registry RunOnce>Run priorita + slash normalizace + utf-8 errors=replace U+FFFD, EVTX FILETIME→aware UTC + ASCII-run BinXML heuristika (diakritika rozbíjí runy) + confidence 0.85/0.6, LNK CLSID @4..20 + max_scan=4096 ANSI path scan); vlna 16 locale sweep — 27 locale-only parserů (mem_* paměťová forensika, MS Office/Teams rodina, Chrome cloud export, Instagram/Twitter SNS, Amazon CloudTrail/EC2-S3, Google Contacts WR, Facebook/SharePoint/Snapchat WR) každý získal kategorii locale: česká diakritika („Příliš žluťoučký kůň" + doménová slova s háčky/čárkami) verbatim v doménových polích (názvy procesů/modulů/snapshots, subjekty e-mailů a schůzek, názvy záložek a dokumentů, bucket/key cesty S3 — EC2 record tags nenesou, tituly zpráv — skype_warrant title truncation [:60], sharepoint_wr auto-detekce document i page shape); vlna 17 capstone — posledních 9 parserů / 27 buněk (allowlisted_websites encoding/locale/size/tz — JSON domén s U+FFFD fallbackem a snapshot timestamp=None, mailru_agent encoding/locale/size/tz — chat log s naive→aware UTC (přesnost minuty → :00) a MAX_LINES_PER_FILE=20_000 truncation, openoffice_base encoding/locale/size/tz — ODF ZIP kde ElementTree respektuje deklaraci iso-8859-1 v XML hlavičce + dc:date astimezone(UTC)/naive→UTC + title [:120], sim_tpdu corrupted/encoding/locale/size/tz — binární smetí → [] nebo celosouborový latin-1 fallback, MAX_CONTACTS_PER_DUMP=2_000, apple_cloud/gmail_messages/maps_labeled_places/whatsapp_cloud locale+negatives s přesnými TypeError zprávami, drive_activity corrupted ValueError „Neplatné JSON" + locale); **category coverage 100 % (624/624), 78/78 parserů plně — P1-1 uzavřeno**) | testovací sada per parser (pozitivní/negativní/hraniční/poškozené vstupy, časové pásmo/kódování/locale, limitní velikosti); regresní sada; syntetická anonymizovaná data | L |
| P1-2 | AI orchestrátor 2.0 + audit AI výstupů — ✅ **hotovo** (doména rolí + I/O služba + case-level wiring; eval sada zlatých scenářů; CLI `stopa ai-run`; Web endpoity; celkem 74 testů offline) | role agentů (Evidence/Timeline/Network/Memory/Intelligence/Hypothesis/Report/QA) s minimálními oprávněními; retry+backoff+jitter; token limity; validace strukturovaných výstupů; prompt-injection ochrana; eval sada; AI záznamy do audit_log | L |
| P1-3 | Evidence Graph — ✅ **hotovo** (čistá doména `evidence_graph.py` + schema v22 `graph_edges` + repository; CLI `stopa graph <case> [--json]`; Web `/api/cases/{id}/evidence-graph`; 43 testů offline) | rozšíření F3.5 hypothesis graph + entities/correlations na plný graf důkazů↔entity↔události↔zjištění; každá hrana s vysvětlením proč vznikla (reason povinný); podpůrné i protichůdné vazby (polarity supports/contradicts/neutral); explicitní ruční/AI hrany mají přednost nad odvozenými | M |
| P1-4 | Postupný refactoring god-files | characterization tests nejdřív; extrakce: `cli.py`→`cli/commands/*.py` (argparse subcommand registry); `web/app.py`→routery per doméně; `pipeline.py`+`validation_registry.py` rozklad po odpovědnostech; kompatibilní importy + CLI/API | L |
| P1-5 | Cross-platform CI matrix | Linux+Windows; core min instalace / plná / web / Rust ext / volitelné extras jako samostatné joby; ověření že fallbacky nezakrývají chyby (testy „bez X“) | M |
| P1-6 | Crash recovery + reprodukovatelnost | testy obnovy po pádu (checkpoint ingest F2.4 existuje — doplnit E2E); memory-leak testy long-running; deterministické replay porovnání (C5 engine rozšířit) | M |
| P1-7 | Forensic Assurance Center UI | sjednocený dashboard: integrita důkazů, completeness provenance, chain of custody, stav ledgeru, pečetě/podpisy, validace parserů, reprodukovatelnost, auditní historie, AI stavy, integrita reportů — každý stav vysvětlen (co ověřeno/co chybí/jak napravit) | M |

---

## P2 — Rozšíření

> **Návrhy + priority + AK (2026-11-18):** `docs/P2_DESIGNS.md` — doporučené pořadí:
> P2-4 → P2-3 → P2-6 → P2-5 → P2-2 → P2-7 → P2-1.
> **Stav 2026-11-20: všech 7 položek hotovo ✅** (SHAs v `STOPA_CHANGELOG.md` / SKILL) — Release STOPA 2.2, suite **4698p/1s**.

| # | Položka | Pozn. |
|---|---|---|
| P2-1 | Distribuované zpracování | fronty úloh, workeři, kapacitní řízení; offline single-machine režim zůstane |
| P2-2 | Centrální registr případů | `stopa_instance.db` už existuje (RBAC) — rozšířit o cross-case registry s tenancy kontrolami |
| P2-3 | Advanced Timeline Intelligence | normalizace časových údajů, anomálie, korelace napříč zdroji, vysvětlení nejistoty |
| P2-4 | Investigation Workspace | hypotézy+poznámky+úkoly+revize; peer review (F4.3 existuje — rozšířit) |
| P2-5 | Threat Intelligence Workspace | STIX 2.1 + ATT&CK (F6.2/F6.3 existují) + IoC + YARA/Sigma (pokud legálně bezpečně); stáří intel dat |
| P2-6 | Cross-case correlation | přísné oprávnění, prevence úniku mezi tenancy, audit každého dotazu |
| P2-7 | Plugin marketplace a Case Exchange | podepisování, anonymizace, model důvěry; neimplementovat bez jasných oprávnění |

**F14 produktové schopnosti A–N (z master promptu):** Evidence Graph=P1-3; Advanced Timeline=P2-3; Investigation Workspace=P2-4; Chain of Custody=rozšíření `custody_items` v P0-1/P1-7; Threat Intel=P2-5; Automated Classification / Cross-case Correlation / Advanced Deduplication (F2.3 existuje) / Artifact Version Comparison / Advanced Search (FTS5 existuje — rozšířit o metadata+vztahy) / Distributed Processing=P2-1 / Evidence Storage Manager / QA Center=P0-4+P1-7 / Report Marketplace & Case Exchange=P2-7. Každá dostane návrh+prioritu+AK před implementací (neimplementovat všechny automaticky).

## P3 — Další rozšíření (post-2.2)

> **Návrhy + priority + AK (2026-11-20):** `docs/P3_DESIGNS.md` — doporučené pořadí:
> P3-1 Advanced Search → P3-6 UI/policy follow-upy z 2.2 → P3-2 Artifact Version Comparison →
> P3-5 YARA/Sigma matching → P3-3 Automated Classification → P3-4 Evidence Storage Manager.
> **Stav 2026-11-20: všech 6 položek hotovo ✅** (SHAs v `STOPA_CHANGELOG.md` / SKILL) — Release STOPA 2.3, suite **5013p/1s**.

| # | Položka | Pozn. |
|---|---------|-------|
| P3-1 | Advanced Search (FTS5 + metadata + vztahy) ✅ **hotovo 2026-11-20** (`71666c4`/`54c0682`) | W1 čistá doména `domain/search_adv.py`; W2 `data/search_repository.py` + CLI `stopa search` +7 volitelných flagů (bez nich byte-identicky) + Web GET `/api/cases/{id}/search/advanced`; testy W1 29 + W2 18, regression 175/175 |
| P3-2 | Artifact Version Comparison ✅ **hotovo 2026-11-20** (`855a36a`/`5819fa2`) | path-based JSON diff verzí napříč zachytími (klíč = type+rel_path, source není částí klíče); CLI `stopa compare-artifacts` (exit 0/1/2) + Web GET `/artifacts/compare`; identity = detaily + parser_version; testy 35/35, povrch aditivní CLI +7/Web 116→117 |
| P3-3 | Automated Classification ✅ **hotovo 2026-11-20** (`656ace8`/`b571d70`) | W1 doména `domain/classification.py` (uzavřená taxonomie 11 kategorií, váhové pravidlo + entity corroboration, needs_review pod prahem 0.6); W2 v26 tabulka classifications (upsert per file, aditivní override sloupce), data layer `classification_repository.py`, CLI `stopa classify` (+ --override/--category/--reason) exit 0/2 + Web /classifications; testy W1 27 + W2 22 |
| P3-4 | Evidence Storage Manager ✅ **hotovo 2026-11-20** (`2a38079`/`6168549`) | W1 doména `domain/evidence_storage.py` (uzavřené stavy verified/corrupt/missing/no_reference, read-only rehash sémantika + konzervativní I/O→missing, kapacitní rozpočet, Ed25519 kanonický manifest — veřejný klíč v podepsaném payloadu); W2 data-layer `evidence_storage_repository.py` (kvarenténa = unie zdrojů, streamovací rehash 1 MiB chunky, fail-closed export/import, meta perzistence bez DDL → bez v27), CLI `stopa evidence-storage verify|report [--budget MB] [--export\|--import F]` exit 0/2; testy W1 68 + W2 25 |
| P3-5 | Threat Intel: YARA/Sigma matching ✅ **hotovo 2026-11-20** (`6f1fee7`/`a869ddd`) | dokončení návrhu P2-5; W1 domain `yara_sigma.py` (YARA = volitelný yara-python s explicitním stavem, Sigma JSON/YAML šablony); W2 v25 migrace (feed kind += yara_rule/sigma_tpl, match_kind += yara/sigma), data-layer enginy, CLI `--yara DIR \| --sigma FILE`, Web body; 21 testů + regresní gate |
| P3-6 | UI/policy follow-upy z 2.2 ✅ **hotovo 2026-11-20** (`d8ae657`) | SPA view timeline-intel (4 sekce, live refresh) + TLP politika Case Exchange (--tlp, porušení = warning, bad_tlp fail-closed); testy 32 + vitest 13/13, web reg. 162/162, povrch aditivní CLI +1 |

---

## P4 — Stabilizace a škálování (post-2.3)

> **Návrhy + priority + AK (2026-11-20):** `docs/P4_DESIGNS.md` — zdroj = `STOPA_ANALYZE.md` §8 známý dluh
> (stav ověřen v HEAD: 2/10 hotovo, 5/10 částečné, 3/10 otevřené) + §7 design otázky; doporučené pořadí:
> P4-1 CI matrix pro volitelné extras → P4-3 Plugin API semvering → P4-2 sandbox hardening →
> P4-6 Sealing v2 (time hash chain + external witness) → P4-5 AI production robustness →
> P4-4 Frontend sjednocení (SPA kanonická) → P4-9 Cross-platform a stabilita → P4-8 i18n CLI/legacy →
> P4-7 Multi-node readiness → P4-10 Rust distribuce.
> **Schváleno uživatelem 2026-11-21**, doporučené pořadí se dodržuje.
> **Stav 2026-11-22: P4-1 + P4-3 + P4-2 + P4-6 + P4-5 + P4-4 + P4-9 + P4-8 + P4-7 hotové** — CI profily `test` (min) + nový `test-full` (všechny extras),
> `docs/EXTRAS_COVERAGE.md`, fail-closed opravy v 24 test souborech (test-only, src beze změny);
> min suite exit 0. P4-3: volitelné manifest pole `api_version` + validace, sekce „Contract stability"
> v PLUGINS_API.md, breaking change log marker `!plugins:`. P4-2: NPROC/FSIZE rlimity + strict
> seccomp-bpf profil (ctypes raw syscall, fail-closed per-arch tabulky x86_64/aarch64) + volitelný
> user ns wrapper, CLI `plugin run --sandbox {default,strict}`, 33 nových testů. P4-6: time hash chain
> F5.1 pečetí (domain seal_chain.py, genesis self-binding, fail-closed ověření), aditivní v27 tabulka
> seal_chain 1:1 s pečetí, externí witness url/file + inline b64 ≤ 32 kB, CLI `seal --witness` +
> `seal-chain`, Web GET /api/cases/{id}/seals/chain (120→121 rout), 26 nových testů. P4-5: AI production
> robustness — retry+backoff+jitter v ReAct agentu (deterministický per seed, jen transientní chyby,
> HTTP 5xx/429 = transient), token budget → explicitní `status="budget_exceeded"` + truncation marker
> (ne exception), stream/non-stream identita by construction (sdílená smyčka `_agent_loop`), SSE endpoint
> GET /api/cases/{id}/ai/run/stream (121→122 rout), eval gate CLI `stopa ai-eval --suite gold [--json]`
> (exit 0/1, zlaté scénáře v src jako single source of truth); 23 nových testů. P4-4: frontend sjednocení —
> SPA je kanonická na root URL (`GET /` = React build), legacy GUI non-kanonické pod `?ui=legacy` s deprecation
> bannerem + console.warn; `/spa/` zůstává alias (dynamický basename, SW se scope „/"); W2 doplnilo chybějící SPA
> view: ATT&CK heat-mapa `/attack` (parita legacy F6.3, STIX export) a `/reports` s Daubert pack tlačítkem (F5.5);
> graceful degradation na legacy bez SPA buildu; frontend vitest 20 testů + tsc clean + vite build. P4-9: cross-platform —
> leak canary `test_p49_leak_canary.py` (deterministický ingest loop, prah < 100 MiB tracemalloc), CI jobs `windows`/`macos`
> (portability core = kurátorovaný domain+data subset bez Rust wheelu → referenční carving cesta) a `docs/PLATFORM_MATRIX.md`;
> portability core 546p + canary 1p. P4-8: i18n CLI — cs/en JSON katalogy (`src/stopa/i18n/{cs,en}.json`, 339 klíčů),
> fail-open helper `t(key, **params)`; priorita flag --lang > env STOPA_LANG > default cs (byte-kompatibilní — nová zlatá
> `p48_cli_help_cs.json`); EN akceptační kritéria = top-level help + 100 % epilogů v angličtině; Web GET `/api/i18n/{lang}`
> pro legacy UI (web povrch 122→123 rout); 23 testů. P4-7: multi-node readiness — DB event bus v instance DB
> (tabulka `events`, pořadí = monotónní `id`; WAL + busy_timeout centralizovaně v `open_instance()`; web polling
> worker 0,25 s s deduplikací podle `_pid`, retence 2 h / pruning každých 240 cyklů); registry lease — sloupce
> node_id/last_heartbeat (idempotentní migrace), liveness nad monotónními sekvencemi beatů bez wall-clocku
> (alive/expired/unknown, LEASE_WINDOW=8; atomický beat BEGIN IMMEDIATE + max+1), web poller auto-heartbeat
> (STOPA_NODE_ID/hostname), `GET /api/registry` vrací lease mapu, CLI `stopa registry --heartbeat NODE`;
> W4 `docs/MULTI_NODE.md`; 24 testů (i na minimálním profilu). Zbývá 1 položka = návrh k implementaci.

| # | Položka | Priorita | Velikost | Pozn. |
|---|---------|----------|----------|-------|
| P4-1 | CI matrix pro volitelné extras („bez X“ + „s X“) | **P0** | S | ✅ **hotová**: profily min+full v ci.yml (nový job `test-full`), EXTRAS_COVERAGE.md; fail-closed opravy v 24 test souborech, bez src změn |
| P4-2 | Plugin sandbox hardening (rlimits + seccomp strict profil) | **P0** | M | ✅ **hotová**: NPROC/FSIZE rlimity + `profile` v SandboxLimits; strict = seccomp-bpf allowlist (ctypes, fail-closed per-arch tabulky x86_64/aarch64) + volitelný user ns wrapper; CLI `--sandbox {default,strict}`; 33 testů |
| P4-3 | Plugin API semvering + breaking change log | **P0** | S | ✅ **hotová**: volitelné `api_version` (default "1", rozsah [1, 1]) + validace; průchod digest/CLI/Web; sekce „Contract stability" v PLUGINS_API.md + marker `!plugins:` |
| P4-6 | Sealing v2 — time hash chain + external witness | **P1** | S–M | ✅ **hotová**: domain seal_chain.py (chain_hash z prev_root+case_id+ts+merkle_root, genesis self-binding, fail-closed ověření seq 1..N), aditivní v27 tabulka seal_chain 1:1 s pečetí (stejná transakce); CLI `seal --witness {url\|file}` + subpříkaz `seal-chain`; Web GET /api/cases/{id}/seals/chain (120→121 rout); witness inline b64 ≤ 32 kB; 26 testů |
| P4-5 | AI production robustness (streaming/retry/token budget/eval gate) | **P1** | M | ✅ **hotová**: `classify_llm_error` v doméně (transient = 5xx/429/markery; permanent propaguje), retry+backoff+jitter v `_agent_loop` (deterministický per seed RNG, injektovatelný sleep); token budget → `status="budget_exceeded"` + truncation marker (ne exception); stream/non-stream identita by construction; SSE GET /api/cases/{id}/ai/run/stream (121→122 rout); eval gate CLI `stopa ai-eval --suite gold [--json]` exit 0/1, zlaté scénáře v src (single source of truth); 23 testů |
| P4-4 | Frontend sjednocení — SPA kanonická, legacy za flagem | **P1** | L | ✅ **hotová**: W2 — nové SPA view `/attack` (ATT&CK heat-mapa F6.3 parita + STIX) a `/reports` (Daubert pack F5.5); W3 — `GET /` = kanonická SPA, legacy pod `?ui=legacy` s deprecation bannerem + console.warn, `/spa/` alias (dynamický basename, SW scope „/" ), fallback na legacy bez SPA buildu; web povrch beze změny (bez nových rout); frontend vitest 20 testů, tsc clean |
| P4-9 | Cross-platform a long-running stabilita (Win/macOS CI + leak canary) | **P2** | M | ✅ **hotová**: W1 audit readiness; W2 leak canary `test_p49_leak_canary.py` (deterministický ingest loop ~5 MB/23k záznamů, 16 iterací, prah < 100 MiB tracemalloc); W3 CI jobs `windows` + `macos` (portability core = kurátorovaný domain+data subset bez Rust wheelu → referenční carving cesta; full suite jen ubuntu); W4 `docs/PLATFORM_MATRIX.md` (matice × pokrytí, platformově omezené cesty, known gaps) |
| P4-8 | i18n CLI (+ legacy UI katalog) | **P2** | M | ✅ **hotová**: cs/en JSON katalogy (339 klíčů) + fail-open helper `t(key, **params)`; priorita flag --lang > env STOPA_LANG > default cs (byte-kompatibilní — zlatá `p48_cli_help_cs.json`); EN akceptační kritéria = top-level help + 100 % epilogů v angličtině; Web GET /api/i18n/{lang} pro legacy UI (web povrch 122→123 rout); 23 testů |
| P4-7 | Multi-node readiness (DB event bus + registry lease) | **P2** | L | ✅ **hotová**: W1 audit VERIFIED; W2 tabulka `events` v instance DB (pořadí = monotónní id, kanonické JSON, index topic+id), WAL + busy_timeout=5000 ms centralizovaně v `open_instance()`, web polling worker 0,25 s (publisher+subscriber, dedup `_pid`, retence 2 h / pruning 240 cyklů); W3 lease sloupce node_id/last_heartbeat (idempotentní migrace), liveness nad monotónními sekvencemi beatů (alive/expired/unknown, LEASE_WINDOW=8; atomický beat BEGIN IMMEDIATE + max+1 bez clock driftu), poller auto-heartbeat STOPA_NODE_ID/hostname, registry endpoint vrací lease mapu, CLI `stopa registry --heartbeat NODE [--json]`; W4 `docs/MULTI_NODE.md`; 24 testů offline (běží i na min profilu); zlaté povrchy beze změny (CLI 87 cest / CS byte-guard / Web 123 rout) |
| P4-10 | Rust distribuce — manylinux wheels | **P2** | M | GHA matrix x86_64/aarch64, extra `[carving]`, wheel parity gate |

---

## Postup práce (etapy A–G z master promptu)

| Etapa | Obsah | Stav |
|---|---|---|
| **A — Audit** | git status/commit; mapa repo; testy se skutečnými výsledky; bezpečnostní rizika; seznam priorit | ✅ tento commit (ROADMAP_2_1.md + EXECUTIVE_SUMMARY.md) |
| **B — Plán** | technický plán po malých krocích; u každé změny přínos/riziko/závislosti/testy; změny vyžadující souhlas uživatele (migrace v20, plugin API SemVer, schéma ledgeru) | ✅ P0 sekce nahoře (AK + velikosti) |
| **C — Kritická bezpečnost a integrita** | P0-1..P0-5; izolované změny + testy po každé | ✅ **P0-1 + P0-2 + P0-3 + P0-4 + P0-5 hotové** (P0-1: provenance engine — schema v21 + idempotentní migrace, čistá doména + repository, CLI `provenance` exit 0/1/2 + Web endpoint, testy 41/41 + živý E2E; P0-2: AES-GCM obal klíče + rotace-safe checkpoints, 77/77 testů + E2E; P0-3: sandbox hardening 60/60; P0-4: parser-status CLI+Web 78/78 validováno + differential design doc; P0-5: `SECURITY_THREAT_MODEL.md` T-1..T-10) |
| **D — Kvalita parserů a architektura** | P1-1, P1-4, P0-6 migrace po schváleném plánu | 🟡 P0-6 ✅ (dokument) + **P1-1 uzavřeno — jádro + vlny 1–17 (category coverage 100 %, 624/624, 78/78 parserů plně pokrytých)**; **P1-4: `cli.py` rozložena (vlna a pinning povrchu + vlna B balíček `cli/commands/*`, facade −83 %, povrch byte-přesný 14/14) + `web/app.py` rozložena (vlny C1/C2 — golden povrch 94 rout, routery per doméně, facade −69 %) + `pipeline.py` rozložena (vlny D1/D2 — golden povrch 16 jmen + 6 signatur, balíček `pipeline/*` 6 modulů, povrch byte-přesný 3/3) + `validation_registry.py` rozložena (vlny E1/E2 — golden povrch datového rejstříku 78 parserů, balíček `domain/validation_registry/*` 9 modulů, povrch byte-přesný 5/5)**; **P1-4 uzavřeno** |
| **E — AI** | P1-2 | ✅ hotovo — jádro + case-level wiring (`run_role_on_case`) + eval sada zlatých scenářů + CLI `stopa ai-run` (exit 0/2/1) + Web `/api/ai/orchestrator-status`, `/api/cases/{id}/ai/run`; **74 testů offline** |
| **F — Nové funkce** | jen schválené a odůvodněné; po malých releasovatelných celcích | 🟡 **P1-3 Evidence Graph ✅ hotovo** (čistá doména + schema v22 `graph_edges` + CLI `stopa graph` exit 0/1 + Web `/api/cases/{id}/evidence-graph`; **43 testů offline**); ⏳ ostatní čekají na schválení |
| **G — Validace a release** | kompletní testy + benchmarky + bezpečnostní kontroly + release notes + známé limity | ✅ suite25 4278p/1s; benchmark 79/80 (stale baseline doloženo párovým měřením); `docs/RELEASE_NOTES_2_1.md` s limitami |

## Akceptační kritéria pro STOPA 2.1 (z master promptu, bez úprav)

Release 2.1 je připraven pouze pokud jsou doloženy: (1) originální důkazní data nedotčena; (2) původ důkazů a artefaktů dohledatelný; (3) ledger ověřuje integritu historie; (4) hash/podpisy/pečeti s automatizovanými testy; (5) parsery s transparentním stavem validace; (6) AI výstupy dohledatelné, podložené, označené neověřené dokud je nepotvrdí člověk; (7) pluginy s vynucenými oprávněními a izolací; (8) React frontend pokrývá schválené funkce legacy; (9) CLI/API kompatibilní nebo verzované+zdokumentované; (10) DB migrace s testem obnovy; (11) offline režim pro deklarované scénáře; (12) testy/benchmarky/bezpečnost se skutečnými výsledky; (13) dokumentace = reálný stav; (14) známé limity viditelně uvedeny.

## Git a zachování práce
Feature větev `feat/stopa-2.1` (nebo rovnou main po schválení); malé logické commity (`feat(p0-x): ...`); žádný force push; merge do main bez výslovného souhlasu ne; před každou migrací/plánem zálohy a obnovení; při nejistotě zastavit rizikovou operaci a popsat důvod.
