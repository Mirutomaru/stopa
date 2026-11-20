# STOPA 2.3 — Release Notes

**Stav:** ready to push — `main` lokálně (18 commitů před `origin/main`, push/tag v tomto releasu)
**Datum validace:** 2026-11-20 · **Referenční GA:** STOPA 2.2 (`2bd603e`, tag `v2.2.0`)

## Shrnutí

STOPA 2.3 uzavírá **post-release roadmap P3 (6/6 položek)**: pokročilé
vyhledávání, UI/policy follow-upy z 2.2, srovnání verzí artefaktů, YARA/Sigma
matching, automatizovaná klasifikace a evidence storage manager. Veřejné API,
CLI povrch i datové formáty zůstávají kompatibilní — všechny migrace jsou
aditivní a idempotentní (case DB v25→v26; P3-4 bez DDL přes `meta` klíč).
Žádné nové síťové závislosti v základním forenzním workflow (offline režim
zachován); `yara-python` zůstává volitelným extra (`rules`).

## Hlavní změny

### P3-1 Advanced Search (`71666c4` / `54c0682`)

- W1: čistá doména `domain/search_adv.py` — FTS5 + metadata + vztahy,
  deterministické skórování a řazení výsledků. Testy **29/29**.
- W2: `data/search_repository.py` + CLI `stopa search` (+7 volitelných flagů;
  bez nich výstup byte-identicky) + Web GET `/api/cases/{id}/search/advanced`.
  Testy W1 29 + W2 18, regression vrstva **175/175**.

### P3-6 UI/policy follow-upy z 2.2 (`d8ae657`)

- **(A)** TLP distribuční politika Case Exchange: `--tlp`, porušení =
  warning, bad_tlp fail-closed; **(B)** SPA view timeline-intel (4 sekce,
  live refresh). Testy **32** + vitest **13/13**, web regression 162/162;
  povrch aditivní CLI +1.

### P3-2 Artifact Version Comparison (`855a36a` / `5819fa2`)

- W1: čistá doména — path-based JSON diff verzí artefaktů napříč zachytími
  (klíč = type+rel_path, source není částí klíče); identity = detaily +
  parser_version. Testy **35/35**.
- W2: CLI `stopa compare-artifacts` (exit **0**/**1**/**2**) + Web GET
  `/artifacts/compare`. Povrch aditivní: CLI +7, Web 116→117 route.

### P3-5 Threat Intel: YARA/Sigma matching (`6f1fee7` / `a869ddd`)

- W1: čistá doména `domain/yara_sigma.py` — YARA přes volitelný yara-python
  (bez něj explicitní `RuntimeError`, nikoli tichý výsledek), Sigma JSON/YAML
  šablony. Testy **34/34** (+4 skip bez yara-python).
- W2: v25 migrace (feed kind += `yara_rule`/`sigma_tpl`, match_kind +=
  `yara`/`sigma`) — DDL z `sqlite_master` s textovou výměnou CHECK (fail-closed
  při neočekávaném formátu); data-layer enginy: YARA skenuje soubory případu,
  Sigma timeline události; pravidla ve feedu jako IoC druhů `yara_rule`/
  `sigma_tpl`; CLI `--yara DIR | --sigma FILE`; Web volitelné JSON tělo (bez
  těla = původní chování). Testy W2 **21/21** + regresní gate.

### P3-3 Automated Classification (`656ace8` / `b571d70`)

- W1: čistá doména `domain/classification.py` — uzavřená taxonomie 11
  kategorií, váhové pravidlo s entita corroboration (+0.1 u komunikačních),
  needs_review pod prahem 0.6, deterministické tie-breaking; výstup nese
  neprázdné `reasons[]`. Testy **27/27**.
- W2: v26 aditivní tabulka `classifications` (upsert per file, re-run
  deterministický); lidský override = aditivní sloupec + append-only audit
  hash chain → reverzibilní; data layer s re-derivací entit přes stejný
  `domain.entities.extract_entities`; CLI `stopa classify` (+ `--override/
  --category/--reason`) exit **0**/**2**; Web `/classifications`. Testy W1 27 + W2 22.

### P3-4 Evidence Storage Manager (`2a38079` / `6168549`)

- W1: čistá doména `domain/evidence_storage.py` — uzavřené stavy
  verified/corrupt/missing/no_reference; read-only rehash sémantika (I/O chyba
  = konzervativně missing); kapacitní rozpočet z DB metadata; Ed25519
  kanonický manifest s veřejným klíčem v podepsaném payloadu (self-contained
  trust anchor). Testy **68/68**.
- W2: data-layer `evidence_storage_repository.py` — kvarenténa = unie všech
  registrovaných zdrojů (`sources.path` + `files.rel_path`), streamovací rehash
  1 MiB chunky, originály neúpravné; **fail-closed export** (rehash před
  podpisem; missing/corrupt → manifest se nepodepíše) i fail-closed import
  cizího reference manifestu; perzistence do `meta` klíče bez DDL (bez v27).
  CLI `stopa evidence-storage verify <case> [--export F | --import F]` a
  `report <case> [--budget MB]`, exit **0**/**2**. Testy W1 68 + W2 25.

## Validace

- **Full regression: `5013 passed / 1 skipped`, exit 0** (~35 min; +93 testů
  vs. báze 4920p po P3-3 — přesně = nové P3-4 testy).
- Ruff clean repo-wide (line length 100, přísnější pravidla); rozpočet
  `src/stopa/data/db.py` **599 < 600 ř.** nedotčen.
- Golden povrchy: CLI aditivní (+`evidence-storage` subtree, +3 uzly), Web
  beze změny (**120 route** — P3-4 je dle návrhu CLI-only); PKG_COMPAT=0
  (`python -m stopa.cli`), entry point `stopa` bez změny.

## Známé limity

- **P3-5:** `yara-python` je volitelná závislost (extra `rules`) — bez ní
  YARA/Sigma matching hází explicitní `RuntimeError` (graceful degradation, ne
  tichý výsledek); Sigma ve YAML vyžaduje PyYAML.
- **P3-4:** řádky bez referenčního hashu končí ve stavu `no_reference`, který
  není fatální pro exit code `verify` (konzervativní, nikoli implicitně
  verified); export manifestu nepodepíše položky s missing/corrupt stavem.
- **P3-1:** pokročilé vyhledávání je case-scoped (v rámci jednoho případu) —
  instance-wide fulltext je nad rámě schváleného návrhu.
