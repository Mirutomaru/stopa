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
| P1-1 | Parser Quality Framework — ✅ **jádro + vlny 1–8 hotovy** (framework, pilotní sady sqlite/email_mbox, bázisové markry pro všechny parsery; vlna 2 Google Takeout rodina; vlna 3 cloud warrant rodina; vlna 4 MS+Amazon rodina; vlna 5 Chrome+Skype rodina; vlna 6 sociální rodina Twitter/Facebook; vlna 7 cloud SNS Instagram/Snapchat; vlna 8 memory forensics rodina (w9 JSON + mem_scan text); category coverage **63.9 %**) | testovací sada per parser (pozitivní/negativní/hraniční/poškozené vstupy, časové pásmo/kódování/locale, limitní velikosti); regresní sada; syntetická anonymizovaná data | L |
| P1-2 | AI orchestrátor 2.0 + audit AI výstupů — ✅ **jádro hotovo** (doména rolí + I/O služba, 38 testů; zbývá eval sada a CLI/Web integrace) | role agentů (Evidence/Timeline/Network/Memory/Intelligence/Hypothesis/Report/QA) s minimálními oprávněními; retry+backoff+jitter; token limity; validace strukturovaných výstupů; prompt-injection ochrana; eval sada; AI záznamy do audit_log | L |
| P1-3 | Evidence Graph | rozšíření F3.5 hypothesis graph + entities/correlations na plný graf důkazů↔entity↔události↔zjištění; každá hrana s vysvětlením proč vznikla; podpůrné i protichůdné vazby | M |
| P1-4 | Postupný refactoring god-files | characterization tests nejdřív; extrakce: `cli.py`→`cli/commands/*.py` (argparse subcommand registry); `web/app.py`→routery per doméně; `pipeline.py`+`validation_registry.py` rozklad po odpovědnostech; kompatibilní importy + CLI/API | L |
| P1-5 | Cross-platform CI matrix | Linux+Windows; core min instalace / plná / web / Rust ext / volitelné extras jako samostatné joby; ověření že fallbacky nezakrývají chyby (testy „bez X“) | M |
| P1-6 | Crash recovery + reprodukovatelnost | testy obnovy po pádu (checkpoint ingest F2.4 existuje — doplnit E2E); memory-leak testy long-running; deterministické replay porovnání (C5 engine rozšířit) | M |
| P1-7 | Forensic Assurance Center UI | sjednocený dashboard: integrita důkazů, completeness provenance, chain of custody, stav ledgeru, pečetě/podpisy, validace parserů, reprodukovatelnost, auditní historie, AI stavy, integrita reportů — každý stav vysvětlen (co ověřeno/co chybí/jak napravit) | M |

---

## P2 — Rozšíření

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

---

## Postup práce (etapy A–G z master promptu)

| Etapa | Obsah | Stav |
|---|---|---|
| **A — Audit** | git status/commit; mapa repo; testy se skutečnými výsledky; bezpečnostní rizika; seznam priorit | ✅ tento commit (ROADMAP_2_1.md + EXECUTIVE_SUMMARY.md) |
| **B — Plán** | technický plán po malých krocích; u každé změny přínos/riziko/závislosti/testy; změny vyžadující souhlas uživatele (migrace v20, plugin API SemVer, schéma ledgeru) | ✅ P0 sekce nahoře (AK + velikosti) |
| **C — Kritická bezpečnost a integrita** | P0-1..P0-5; izolované změny + testy po každé | ✅ **P0-1 + P0-2 + P0-3 + P0-4 + P0-5 hotové** (P0-1: provenance engine — schema v21 + idempotentní migrace, čistá doména + repository, CLI `provenance` exit 0/1/2 + Web endpoint, testy 41/41 + živý E2E; P0-2: AES-GCM obal klíče + rotace-safe checkpoints, 77/77 testů + E2E; P0-3: sandbox hardening 60/60; P0-4: parser-status CLI+Web 78/78 validováno + differential design doc; P0-5: `SECURITY_THREAT_MODEL.md` T-1..T-10) |
| **D — Kvalita parserů a architektura** | P1-1, P1-4, P0-6 migrace po schváleném plánu | 🟡 P0-6 ✅ (dokument) + P1-1 jádro + vlny 1–6 hotové (**category coverage 57.4 %**); zbývá: per-parser fixture pro chybějící kategorie u zbývajících rodin parserů + P1-4 |
| **E — AI** | P1-2 | 🟡 jádro hotové (doména rolí + I/O služba, 38 testů offline); zbývá: eval sada + CLI/Web integrace |
| **F — Nové funkce** | jen schválené a odůvodněné; po malých releasovatelných celcích | ⏳ |
| **G — Validace a release** | kompletní testy + benchmarky + bezpečnostní kontroly + release notes + známé limity | ⏳ |

## Akceptační kritéria pro STOPA 2.1 (z master promptu, bez úprav)

Release 2.1 je připraven pouze pokud jsou doloženy: (1) originální důkazní data nedotčena; (2) původ důkazů a artefaktů dohledatelný; (3) ledger ověřuje integritu historie; (4) hash/podpisy/pečeti s automatizovanými testy; (5) parsery s transparentním stavem validace; (6) AI výstupy dohledatelné, podložené, označené neověřené dokud je nepotvrdí člověk; (7) pluginy s vynucenými oprávněními a izolací; (8) React frontend pokrývá schválené funkce legacy; (9) CLI/API kompatibilní nebo verzované+zdokumentované; (10) DB migrace s testem obnovy; (11) offline režim pro deklarované scénáře; (12) testy/benchmarky/bezpečnost se skutečnými výsledky; (13) dokumentace = reálný stav; (14) známé limity viditelně uvedeny.

## Git a zachování práce
Feature větev `feat/stopa-2.1` (nebo rovnou main po schválení); malé logické commity (`feat(p0-x): ...`); žádný force push; merge do main bez výslovného souhlasu ne; před každou migrací/plánem zálohy a obnovení; při nejistotě zastavit rizikovou operaci a popsat důvod.
