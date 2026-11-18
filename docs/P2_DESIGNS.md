# STOPA — P2 návrhy (před implementací)

Podle pravidla v `ROADMAP_2_1.md`: **každá P2 položka dostane návrh + prioritu + AK před
implementací; neimplementovat všechny automaticky.** Vytvořeno 2026-11-18 po release
v2.1.0 (`4f14108`). Aktuální schéma **v22** — všechny návrhy používají pouze aditivní
migrace (v23+), Clean Architecture (čistá domain / data I/O / presentation), offline
deterministické testy a zachování stávajícího veřejného API.

## Doporučené pořadí

| # | Položka | Priorita | Velikost | Proč na tomto místě |
|---|---------|----------|----------|---------------------|
| 1 | P2-4 Investigation Workspace | **1** | M | nejrychlejší workflow přínos; staví přímo na F3.5 + F4.3, nízké riziko |
| 2 | P2-3 Advanced Timeline Intelligence | **2** | M–L | vysoká forenzní hodnota; silný základ (timeline engine E2 + anomálie) |
| 3 | P2-6 Cross-case Correlation | **3** | M | tenancy-citlivé — provést PŘED škálováním (P2-1); re-use E4 pravidel |
| 4 | P2-5 Threat Intelligence Workspace | **4** | M | rozšíření hotových F6.2/F6.3; IoC + stáří intel dat |
| 5 | P2-2 Centrální registr případů | **5** | S | malý DB-prac, nad existujícím instance DB (F4.4) |
| 6 | P2-7 Plugin Marketplace & Case Exchange | **6** | L | trust model + anonymizace — po stabilních cross-case základech |
| 7 | P2-1 Distribuované zpracování | **7** | L | největší infra; single-machine offline režim zůstává defaultem |

---

### P2-4 — Investigation Workspace (priorita 1)

**Cíl:** hypotézy + poznámky + úkoly + revize v jednom forenzně sledovatelném povrchu.
**Základ:** `hypotheses` (schéma v15) + F3.5 hypothesis graph (`intelligence/hypothesis_graph.py`),
peer review F4.3 (stavový automat draft→reviewed→approved→court_ready, schema v16),
append-only audit_log s hash chain.

**Návrh:**
- Domain `domain/investigation_workspace.py` — čisté modely: poznámka ukotvená na
  artefakt/entity/timeline event (ref kind + id, validace existence), úkol (status,
  assignee, due), revize hypotézy = **append-only** (forenzní sledovatelnost; tamper
  detekce přes hash chain audit_log).
- Data: aditivní migrace **v23** — tabulky `inv_notes`, `inv_tasks`, `hypothesis_revisions`;
  orchestrace v `data/investigation_repository.py` (rozpočet db.py <600 → tenká facade).
- Presentation: CLI `stopa inv <case> note|task|hypo-rev [--json]` (exit 0/1); Web
  `/api/cases/{id}/investigation*`; live update přes F4.2 LiveEventBus; SPA panel.

**AK:**
- Poznámka na neexistující ref → `ValueError` (semantická chyba) / špatný typ refu → `TypeError`.
- Revize hypotézy append-only: změna starší revize = detekovatelná (hash chain).
- RBAC: viewer read-only, examiner může tvořit; web E2E přes TestClient.
- Suite green + ruff clean; žádné breaking changes (stávající API zachováno).

**Velikost/riziko:** M / nízké — re-use existujících stavových automatů a auditu.

---

### P2-3 — Advanced Timeline Intelligence (priorita 2)

**Cíl:** normalizace časových údajů, anomálie, korelace napříč zdroji, vysvětlení nejistoty.
**Základ:** materializovaná timeline `timeline_events` + E2 detekce anomálií
(`domain/timeline_anomaly.py`, okno + duplikáty), `run_timeline_intel` v pipeline,
kanonické entity z E4, provenance P0-1 (confidence per artefakt).

**Návrh:**
- Domain `domain/timeline_adv.py` — čistá logika: (1) normalizace všech zdrojů do UTC
  s deklarovanou **přesností** (s/ms/unknown); (2) gap/outlier detekce na celé timeline
  (IQR + konfigurovatelné okno); (3) cross-source korelace = sdílená entity v časovém
  okně (re-use E4 kanonických tvarů, verified/inferred confidence); (4) vysvětlení
  nejistoty: per artefakt confidence + provenance ref → proč je údaj nejisté.
- Data: volitelná cache tabulka `timeline_intel` (v23), recompute při ingestu;
  CLI `stopa timeline-intel <case> [--json]` exit 0/1; Web sekce + SPA view.

**AK:**
- Syntetická deterministická timeline s známými gaps/outliery/korelacemi → přesná detekce
  (počet + ID); TZ edge cases (DST přechod, epocha µs Chrome).
- Výstup je **deterministický** (stejné vstupy = stejný JSON) — offline test bez LLM.
- Perf: případ s 1M timeline eventů zpracován < cíle naměřeného benchmarkem (naměřit, nevymýšlet).

**Velikost/riziko:** M–L / střední — numerické heuristiky vyžadují calibraci na reálných datech.

---

### P2-6 — Cross-case Correlation (priorita 3)

**Cíl:** korelace napříč případy s přísným oprávněním a prevencí úniku mezi tenancy.
**Základ:** E4 entity + correlation engine (per-case), F4.4 multi-tenant RBAC
(`data/user_repository.py`, instance DB), read-only sandbox `file:?mode=ro` z F3.3, audit_log.

**Návrh:**
- Explicitní oprávnění `cross_case_query`; domain `domain/cross_case.py` — kanonické
  entity porovnávány napříč case DB přes **read-only spojení**; výsledek vždy anotován
  zdrojovými případy + confidence (verified/inferred dle E4 pravidel).
- Tenancy izolace: default = stejný tenant; cross-tenant jen explicitním grantem.
  Každý dotaz → audit záznam v instance DB (`cross_case_queries`: who/when/cases/scope)
  s hash chain.
- Data: `data/cross_case_repository.py`; CLI `stopa xcorr <case_a> <case_b>|--all
  [--entity email|tel|hash] [--json]` — exit 0 OK, **2 = bez oprávnění**, 1 chyba;
  Web sekce s audit trail.

**AK:**
- Únik test: entity sdílená jen mezi jinými tenancy se neobjeví bez grantu.
- Read-only důkaz: mutace zdrojového case DB během dotazu → chyba (mode=ro).
- Audit: každý dotaz přesně 1 záznam, hash chain validovatelný; deterministické pořadí výsledků.

**Velikost/riziko:** M / střední — forenzní citlivost tenancy vyžaduje pečlivé testy izolace.

---

### P2-5 — Threat Intelligence Workspace (priorita 4)

**Cíl:** STIX 2.1 + ATT&CK + IoC feed se stářím intel dat; YARA/Sigma pokud legálně bezpečně.
**Základ:** F6.2 STIX export (`domain/export.py`), F6.3 `domain/mitre_attack.py`
(coverage 83,6 %), IoC signály c2_beaconing/base64_blob_payload v triage F3.2.

**Návrh:**
- Domain `domain/threat_intel.py` — čisté modely: IoC (ip/domain/hash/url + TLP + zdroj +
  `acquired_at`) → **stáří = now − acquired_at** s konfigurovatelnými prahy (fresh/stale/old);
  STIX 2.1 bundle import/export obousměrně (kanonický tvar — deterministické pořadí objektů).
- Matching IoC × case artefakty/entity: přesné + normalizované tvary (E4 kanonika);
  ATT&CK techniky ↔ artefakty mapuje existující F6.3.
- YARA/Sigma: volitelná extra `[yara]` (yara-python) s graceful degradation; Sigma jen do
  reportu, pokud licenční audit potvrdí (dokumentovat rozhodnutí).
- Data: tabulky `ioc_feed_items`, `intel_matches` (v23); CLI `stopa intel import|match <case>
  [--json]`; Web sekce.

**AK:**
- Deterministický matching na syntetickém case → přesné hit seznamy; stáří klasifikace správně
  po hranicích prahů (boundary testy).
- STIX roundtrip: import → export = identický kanonický bundle.
- Bez yara-python = skip (offline determinismus); licenční poznámka v docs.

**Velikost/riziko:** M / nízké–střední — hlavně formátová disciplína STIX.

---

### P2-2 — Centrální registr případů (priorita 5)

**Cíl:** cross-case registry nad existujícím `stopa_instance.db` s tenancy kontrolami.
**Základ:** instance DB z F4.4 RBAC (`data/user_repository.py`, migrations).

**Návrh:**
- Rozšíření instance schématu (aditivní): tabulka `case_registry` (case_id, name, examiner,
  tenant, created_at, status, stats snapshot: files/artifacts size); sync při open/close case.
- Tenancy kontrola při čtení; CLI `stopa registry [--tenant X] [--json]`; Web dashboard sekce.

**AK:**
- Přidání/smazání případu idempotentní (double-add = 1 řádek); cross-tenant izolace prokázána testem.
- Stats snapshot konzistentní s case DB (deterministický výpočet).

**Velikost/riziko:** S / nízké — čistě DB práce nad existující infrastrukturou.

---

### P2-7 — Plugin Marketplace & Case Exchange (priorita 6)

**Cíl:** podepisování pluginů, anonymizace případů, model důvěry; neimplementovat bez jasných oprávnění.
**Základ:** F6.4 plugin ecosystem (`domain/plugins.py`, manifest validation `min_stopa_version`),
Ed25519 v `domain/integrity.py`, provenance P0-1.

**Návrh:**
- Podepisování: Ed25519 nad digested manifestem; trust model = root key marketplace + pinning
  (verifiable offline); `stopa plugin verify <pkg>` exit 0/1.
- Anonymizace před exportem: čistá domain `domain/anonymize.py` — kanonické entity → stabilní
  pseudonimy; mapping klíče se do bundle **nedostává** (re-anonymizovatelné s klíčem, jinak ne).
- Case Exchange = formát bundle v1 (JSON + provenance P0-1 + volitelný Ed25519 podpis);
  CLI `stopa exchange pack|verify <case> [--out SOUBOR]`; Web marketplace sekce.

**AK:**
- Tamperovaný podpis/manifest → verify exit 1; anonymizace stabilní (stejná entity = stejný pseudonym
  v opakovaném běhu) a reverzibilní jen s klíčem; offline testy bez sítě.

**Velikost/riziko:** L / střední–vysoké — trust model + právní stránka anonymizace vyžadují review.

---

### P2-1 — Distribuované zpracování (priorita 7)

**Cíl:** fronty úkolů, workeři, kapacitní řízení; offline single-machine režim zůstane defaultem.
**Základ:** F2.4 paralelní ingest s backpressure (`pipeline/pool.py`, ProcessPoolExecutor),
F2.5 query cache, checkpointing E3.

**Návrh:**
- Abstrakce fronty `domain/work_queue.py` — `WorkQueue(Protocol)`: in-process implementace =
  aktuální stav (default), volitelný broker backend jako extra `[dist]`; workeři berou batche zdrojů;
  kapacitní řízení = max workerů + disk budget + checkpointing E3.
- Determinismus: DB writes zůstávají v hlavním procesu (pattern F2.4) → stejný výsledek jako single-machine.

**AK:**
- Identický výstup hash manifestu pro single-machine vs distribuovaný běh na stejném vstupu.
- Graceful shutdown: SIGTERM → fronta dotáhne, žádné částečné artefakty (resume E3 funguje).
- Benchmark 48-souborový tree: throughput ≥ N/2× sekvenčního běhu při N workerech (naměřit).

**Velikost/riziko:** L / střední — determinismus + backpressure jsou hlavních rizik; provést až po P2-6.
