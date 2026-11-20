# STOPA 2.2 — Release Notes

**Stav:** ready to push — `main` lokálně (16 commitů před `origin/main`, push/tag v tomto releasu)
**Datum validace:** 2026-11-20 · **Referenční GA:** STOPA 2.1 (`4f14108`, tag `v2.1.0`)

## Shrnutí

STOPA 2.2 uzavírá **post-release roadmap P2 (7/7 položek)**: investigation
workspace, pokročilá timeline inteligence, cross-case korelace, threat
intelligence workspace, centrální registr případů, plugin marketplace & Case
Exchange a distribuované zpracování. Veřejné API, CLI povrch i datové formáty
zůstávají kompatibilní — všechny migrace jsou aditivní a idempotentní
(case DB v23→v24; instance DB DDL bez bumpu `SCHEMA_VERSION`). Žádné síťové
závislosti v základním forenzním workflow (offline režim zachován).

## Hlavní změny

### P2-4 Investigation Workspace (`c12b617` / `05f811f`)

- Schéma **v23**: poznámky, úkoly a revize hypotéz s append-only **hash
  chain** — tamper = exit **2** (porušený řetězec), 1 = chyba, 0 = OK.
- CLI `stopa workspace note/task/hypo-rev <case> ... [--json]`; Web
  `/api/cases/{id}/inv/*` (7 rout). Testy **69/69** (W2 finální baterie).

### P2-3 Advanced Timeline Intelligence (`9e6465d` / `fc6db63`)

- Čistá doména `domain/timeline_adv.py`: normalizace epoch/ISO/TZ, IQR gaps a
  outliery (Tukey plotny), cross-source korelace s E4 confidence, vysvětlení
  nejistoty. Performance: **1M událostí = 3,06 s / peak RSS 1,3 GB**.
- CLI `stopa timeline-intel <case> [--json]` + Web GET
  `/api/cases/{id}/timeline/advanced-intel` (on-the-fly, bez DDL).

### P2-6 Cross-case Correlation (`dbd4739` / `7216338`)

- Instance DDL `cross_case_queries` + `xcorr_grants`; doména
  `domain/cross_case.py`: sdílené entity s E4 confidence, tenancy pravidla
  (legacy/tenant_isolation/grant/no_permission) fail-closed, audit hash chain
  od GENESIS (1 záznam na dotaz).
- CLI `stopa xcorr <case_a> <case_b>|--all [--entity email|tel|hash]
  [--user U]` exit **0**/1/**2** + Web `/api/xcorr/{correlate,audit,grants}`.

### P2-5 Threat Intelligence Workspace (`6b07cda` / `4305d26`)

- Schéma v23→**v24**: `INTEL_DDL` — `ioc_feed_items` (idempotentní UUIDv5 id)
  a `intel_matches`.
- Doména `domain/threat_intel.py`: IoC ip|domain|hash|url + TLP, kanonizace
  fail-closed, stáří fresh/stale/old se striktními prahy, **STIX 2.1 bundle
  roundtrip** (export→import→export stabilní), deterministické matching s
  evidence cap. Testy domény **56/56**, boundary CLI/Web **18/18**.
- CLI `stopa intel import|match <case> [--json]` + Web
  `/api/cases/{id}/intel/{feed,import,match}` (404/400/201).

### P2-2 Centrální registr případů (`5c3a919`)

- Instance DB `case_registry` (DDL idempotentní v `open_instance()`); čistá
  doména `domain/case_registry.py`: primary_tenant = nejmenší org_id, stats
  snapshot kanonickým JSON, konzervativní viditelnost (multi-user off/admin/
  tenant None = vše; jinak jen vlastní org).
- CLI `stopa registry [--tenant ORG] [--user U] [--sync CASE_ID] [--json]`
  exit **0**/1/**2** + Web `/api/registry`; defenzivní auto_sync/auto_remove
  hooky (zrcadlo nesmí rozbít hlavní operaci).

### P2-7 Plugin Marketplace & Case Exchange (`e532c10` / `39e5e18`)

- W1: `domain/anonymize.py` — HMAC-SHA256 pseudonimy (deterministické per
  klíč+entita; mapping „kind|hodnota"→pseudonym se do bundle neexportuje),
  AnonKey 32B + fingerprint; **Ed25519 podpis pluginů** (`domain/plugins.py`,
  manifest_digest = SHA-256 kanonického JSON, pinované kořeny).
- W2: **bundle `stopa-exchange/v1`** — deterministické counts
  {files,artifacts,entities}, bundle_digest nad kanonickým JSON bez klíče
  `signature`, verify fail-closed (no_trust_roots/untrusted_signature/
  signature_mismatch); data vrstva = read-only snapshot case DB; CLI
  `stopa exchange pack <case> [--out|--anon --key-out]` +
  `verify BUNDLE [--roots F | --root LABEL=B64...]`; Web marketplace
  `/api/exchange/pack|verify`.

### P2-1 Distribuované zpracování (`ca550e0` / `b53982e`)

- W1: čistá doména `domain/work_queue.py` — `WorkQueue(Protocol[T])`,
  `InProcessWorkQueue` (backpressure `put()` při plné frontě, graceful
  `stop()` → QueueStopped fail-closed + `drained()`), `CapacityBudget`
  (max_workers + disk_budget_bytes; 0/None = bez limitu).
- W2: integrace do pipeline core — `process_source(work_queue=None,
  disk_budget_bytes=None)`, refill burst přes frontu s zachovaným FIFO
  determinismem a DB writes v hlavním procesu (pattern F2.4); CLI
  `stopa add --disk-budget MB` (0 = bez limitu). Nalezený a opravený
  deadlock: injektovaná fronta `maxsize < window` blokovala main thread —
  invariant `maxsize ≥ window|∞` zdokumentován + test na hranici.
- **AK doloženo měřením:** parita hash manifestů sekvenční == paralelní s
  injektovanou frontou == default ✅; graceful SIGTERM stop+resume bez ztráty
  dat ✅; benchmark 48 souborů/1,2 GB N=4 = **3,51×** (CI threads 3,54×) ≥
  cíl N/2 = 2,0× PROSPEL ✅.

## Validace

- **Full regression: `4698 passed / 1 skipped`, exit 0** (~52 min; +420 testů
  vs. báze 4278p na STOPA 2.1).
- Ruff clean repo-wide (line length 100, přísnější pravidla RUF046/SIM103/
  RUF007); rozpočet `src/stopa/data/db.py` **599 < 600 ř.** nedotčen.
- Golden povrchy (CLI / Web / pipeline / validation registry) — všechny změny
  aditivní, ověřeno set-difem byte-přesně vs. HEAD; povrchy green.
- Package kompatibilita: `python -m stopa.cli` exit 0 (entry point
  `stopa = "stopa.cli:main"` nedotčen).

## Známé limity

- **P2-3:** SPA view pro timeline-intel je follow-up — Web API je hotové.
- **P2-1:** distribuovaný režim v 2.2 = multiproces na jednom stroji (offline
  režim zachován); síťoví workeri nejsou součástí AK 2.2.
- **P2-5:** YARA/Sigma matching není součástí 2.2 (IoC + STIX 2.1 podle
  návrhu v `docs/P2_DESIGNS.md`).
- **P2-7:** Case Exchange bundle v1 = trust model přes podepsané kořeny;
  distribuční TLP politiky = follow-up.
