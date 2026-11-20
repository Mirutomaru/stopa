# STOPA — P3 návrhy (před implementací)

Podle pravidla v `ROADMAP_2_1.md`: **každá položka dostane návrh + prioritu + AK před
implementací; neimplementovat všechny automaticky.** Vytvořeno 2026-11-20 po release
**v2.2.0** (`2bd603e`, P2 roadmap hotová 7/7, suite **4698p/1s**). Aktuální schéma case DB
**v24** + instance DB DDL (case_registry / cross_case) — všechny návrhy používají pouze
aditivní migrace (**v25+**), Clean Architecture (čistá domain / data I/O / presentation),
offline deterministické testy a zachování stávajícího veřejného API, CLI povrchu i datových
formátů.

**Zdroj požadavků:** (a) F14 produktové schopnosti z master promptu bez dosud implementovaného
povrchu — Advanced Search, Artifact Version Comparison, Automated Classification, Evidence
Storage Manager; (b) známé limity release 2.2 (`docs/RELEASE_NOTES_2_2.md`) — SPA view
timeline-intel, YARA/Sigma matching, TLP distribuční politika Case Exchange.

## Doporučené pořadí

| # | Položka | Priorita | Velikost | Proč na tomto místě |
|---|---------|----------|----------|---------------------|
| 1 | P3-1 Advanced Search (FTS5 + metadata + vztahy) | **1** | M | nejvyšší denní workflow hodnota; staví přímo na hotových FTS5 tabulkách + graph v22 |
| 2 | P3-6 UI/policy follow-upy z 2.2 (SPA timeline-intel + TLP exchange) | **2** | S | uzavření deklarovaných limitů release; malé, nízké riziko |
| 3 | P3-2 Artifact Version Comparison | **3** | S–M | re-use F5.3 parser versioning/reparse infrastrukturny — rychlá výhra |
| 4 | P3-5 Threat Intel: YARA/Sigma matching | **4** | S–M | dokončení příběhu P2-5 nad hotou INTEL_DDL v24 |
| 5 | P3-3 Automated Classification | **5** | M–L | větší návrhová plocha (pravidla + overrides) — po stabilizaci search/compare |
| 6 | P3-4 Evidence Storage Manager | **6** | M–L | dotýká se originálního úložiště důkazů = nejpřísnější forenzní konzervativita |

---

### P3-1 — Advanced Search: FTS5 + metadata + vztahy (priorita 1)

**Cíl:** jedno hledání kombinující volný text, strukturované filtry a průchod vztahy
(graph), deterministicky a bez nové infrastrukturní vrstvy.
**Základ:** FTS5 tabulky `files_fts` + `artifacts_fts` (`data/schema.py` ~L535/L557),
existující CLI search v `cli/commands/core.py`, Evidence Graph **v22** `graph_edges` (P1-3),
kanonické entity E4, timeline_events.

**Návrh:**
- Domain `domain/search_adv.py` — čistý query model: `{text?, filters{kind, size_min/max,
  mtime_from/to, source_id, entity}, relations{depth 1..3, edge_types?}}` + deterministické
  vyhodnocení a řazení výsledků (stable sort po relevance → id). Žádné I/O.
- Data: `data/search_repository.py` — SQL složení FTS5 `MATCH` + `WHERE` filtry; relation
  traversal = omezený BFS nad `graph_edges` s deterministickým pořadím (depth-first by rowid);
  orchestrace zde, ne v db.py facade (rozpočet <600 ř.).
- Presentation: rozšíření existujícího `stopa search <case> "query"` o **volitelné** flagy
  `--kind --entity --size-min/--size-max --mtime-from/--to --rel-depth N [--json]` —
  bez flagů = byte-přesně stávající chování (backward compat); Web GET
  `/api/cases/{id}/search/advanced`.

**AK:**
- Čistý textový dotaz bez filterů = **identické výsledky jako současná FTS5 cesta** (regresní test).
- Filtry deterministicky zužují; prázdný výsledek ≠ chyba (exit 0, `[]`).
- Průchod vztahy depth 1..3 reprodukovatelný (stejné ID vstup → stejné ID výstup, pořadí stabilní).
- RBAC viewer read-only; suite green + ruff clean; žádné breaking changes.

**Velikost/riziko:** M / nízké — re-use FTS5 + graph engine; hlavně SQL složení a determinismus BFS.

---

### P3-6 — UI/policy follow-upy z release 2.2 (priorita 2)

**Cíl:** uzavřít dvě deklarované limity 2.2 bez nových API endpointů.
**Základ:** Web API `GET /api/cases/{id}/timeline/advanced-intel` (P2-3 W2, hotové JSON),
exchange bundle v1 (P2-7) s TLP už přítomným u IoC (P2-5).

**Návrh:**
- **SPA timeline-intel view**: panel v existujícím SPA frontendu renderující 4 sekce API
  (normalizace/gaps/outliers, cross-source korelace, nejistoty) — čisté JS nad hotovým
  endpointem, žádná změna backendu.
- **TLP distribuční politika Case Exchange**: `pack` bere `--tlp CLEAR|GREEN|AMBER|RED`,
  bundle dostane pole `tlp`; `verify` porovnává deklarovaný TLP s nejvyšším TLP v entitách →
  **varování** (ne chyba) se seznamem violujících entity; exit kódy bez změny.

**AK:**
- SPA view renderuje všechny sekce API bez nových endpointů (E2E TestClient + SPA smoke).
- Bundle s `tlp` polem zůstává validní i pro starší `verify` (aditivní pole, default CLEAR).
- TLP violace = varování se stabilním pořadem entity; deterministický bundle digest ovlivněn pouze pokud je `--tlp` zadáno.

**Velikost/riziko:** S / velmi nízké — UI + 1 aditivní pole v bundle.

---

### P3-2 — Artifact Version Comparison (priorita 3)

**Cíl:** srovnání verzí téhož artefaktu napříč běhy/reparse: co se změnilo, proč a je to
forenzně vysvětlitelné.
**Základ:** F5.3 parser versioning & reproducibility (`parser_version` per artefakt + reparse
cesta), provenance P0-1 (parent_artifact_id lineage), `artifacts.values_json` + hash.

**Návrh:**
- Domain `domain/artifact_compare.py` — kanonický **path-based JSON diff** dvou verzí
  (added/removed/changed se stabilním pořadím cest), metadata diff (parser_version, source_id,
  run id, mtime); vstupy = dva artefaktové ID, validace existence a shody `artifact_key`
  (jiný artefakt = `ValueError`, špatný typ = `TypeError`).
- Data: tenká orchestrace v existujícím repository vrstvě (čtení artifacts + lineage);
  volitelně aditivní sloupec `supersedes_artifact_id` pokud lineage neřeší verze (audit před
  migrací v25).
- Presentation: CLI `stopa compare-artifacts <case> <id_a> <id_b> [--json]` exit **0**=shoda /
  **1**=rozdíly / **2**=chyba + Web `/api/cases/{id}/artifacts/compare`.

**AK:**
- Identické hodnoty → prázdný diff, exit 0; změněná hodnota → záznam s cestou a oběma hodnotami.
- Diff deterministický (stejné vstupy → byte-přesný výstup, pořadí cest stabilní).
- Provenance: každá změna ukazuje parser_version obou verzí (vysvětlení „proč").

**Velikost/riziko:** S–M / nízké — čisté diff jádro; riziko = rozhodnutí o lineage sloupci (audit před migrací).

---

### P3-5 — Threat Intel: YARA/Sigma matching (priorita 4)

**Cíl:** dokončit návrh P2-5 (ROADMAP: „IoC + YARA/Sigma pokud legálně bezpečně“) —
YARA pravidla nad soubory, Sigma šablony nad timeline událostmi.
**Základ:** `INTEL_DDL` v24 (`ioc_feed_items`, `intel_matches`), `domain/threat_intel.py`
(kanonizace, TLP, stáří), STIX 2.1 roundtrip; volitelné závislosti s graceful degradation
(stávající pattern: `cryptography`, `stix2`).

**Návrh:**
- Domain: nový modul `domain/yara_sigma.py` (čistá logika) — YARA: kompilace pravidel z textu,
  **volitelná** závislost `yara-python` (bez balíku = explicitní status „nedostupné“, ne tichý
  skip); Sigma: deklarativní šablona → deterministické mapování na pole timeline_events.
- Data: matching results do existujícího `intel_matches` s `kind=yara|sigma` (aditivní hodnota,
  bez DDL změny pokud sloupec kind existuje — jinak v25); feed item nese pravidlo + verzi.
- Presentation: CLI rozšíření `stopa intel match <case>` o `--yara DIR | --sigma FILE`; Web
  `/api/cases/{id}/intel/match` s typem matchingu; report řadí deterministicky (entity → rule).

**AK:**
- Bez `yara-python`: explicitní status + exit code (ne tichá 0) — graceful degradation testována.
- Stejné soubory + stejná pravidla = stejné matchy v stejném pořadí (determinismus, offline).
- TLP respektováno stejně jako u IoC; stáří pravidel (fresh/stale/old) započítává se do reportu.

**Velikost/riziko:** S–M / střední — volitelná závislost rozšiřuje testovací povrch (importorskip pattern).

---

### P3-3 — Automated Classification (priorita 5)

**Cíl:** automatická klasifikace souborů/artefaktů do kategorií + rizika s důvěrou a
forenzně sledovatelným lidským override.
**Základ:** parser matching (signatury/názvy), `PARSER_VALIDATIONS` rejstřík (78 parserů,
E-registry), E4 entity, audit_log hash chain, RBAC F4.4.

**Návrh:**
- Domain `domain/classification.py` — **pravidlový** klasifikátor (offline determinismus: v 3.x
  žádné ML/síť): kategorie z kombinace parser signatury + typové heuristiky + entity →
  `{category, confidence 0..1, reasons[]}`; `confidence < threshold` → flag „needs review“.
- Override: append-only záznam (actor + důvod) do audit_log + sloupec na artifacts/tabulce
  klasifikací — původní automatická hodnota zůstává dohledatelná (reversibilní).
- Data: aditivní migrace **v25** (`classifications` tabulka); CLI `stopa classify <case>
  [--json] [--override ID --category X --reason R]`; Web `/api/cases/{id}/classification*`.

**AK:**
- Stejné vstupy → stejné výstupy (determinismus bez sítě/ML; seed konstantní).
- Každá klasifikace nese neprázdné `reasons[]` (forenzní vysvětlitelnost).
- Override auditovalný (hash chain) a reverzibilní na automatickou hodnotu.

**Velikost/riziko:** M–L / střední — návrhová plocha kategorií + threshold semantiky; riziko = creep pravidel (limitovat na PARSER_VALIDATIONS rodiny).

---

### P3-4 — Evidence Storage Manager (priorita 6)

**Cíl:** životný cyklus originálního úložiště důkazů: inventář, integrita (rehash), kapacitní
rozpočet a export/import kvarentény per případ.
**Základ:** ingest F2.x + block dedupe (`domain/block_dedupe.py`), artifacts s SHA-256 hash,
case DB struktura `case-<id>/`, CapacityBudget koncept (P2-1 `work_queue.py`).

**Návrh:**
- Domain `domain/evidence_storage.py` — inventář model `{path, size, sha256, status:
  verified|missing|corrupt}`, kapacitní report (rozpočet v B, utilization), **read-only
  rehash** (originál se nikdy neupravuje); export/import = deterministický manifest JSON
  s podpisem Ed25519 (re-use `domain/integrity.py`).
- Data: `data/evidence_storage_repository.py` nad kvarenténí adresářem per case; CLI
  `stopa evidence-storage <case> verify|report [--budget MB] [--export F | --import F]`.

**AK:**
- Chybějící/škodněný soubor (rozdílný hash) → detekce, exit **2** (jako P0-1 provenance gaps); originál read-only.
- Rehash 1M souborů < deklarovaný limit (benchmark AK z návrhu; cíl na úrovni F5.1 seal — řádově minuty).
- Import cizího manifestu = fail-closed při neověřeném podpisu; deterministický pořad manifestu.

**Velikost/riziko:** M–L / **středně-vysoké** (dotyk originálních dat → nejpřísnější konzervativita: read-only rehash + test obnovy před exportem).
