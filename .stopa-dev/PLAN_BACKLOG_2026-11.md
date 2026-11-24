# PLAN BACKLOG — VYLEPŠENÍ STOPA (z forenzního/architektonického hodnocení, 2026-11)

Základ: `v2.6.0` + revizní vlny P1–P4 (`35c72a8`). Pracovní metoda: vždy jeden úkol,
před kódem popis změny → minimální implementace → cílené testy + ruff → záznam → další.

## Neporušitelné zásady
1. Determinismus a fail-closed integrita — neověřený důkaz se netichozelená
2. Čistota `domain/` (bez I/O; skládání v composition roots)
3. Žádný tichý únik chyb (each except+pass → log/audit/validační status, kromě odůvodněných C-bindingů)
4. Offline-first reprodukovatelnost (závěry bez sítě ani LLM volatility)
5. Žádné velké skoky — po každé změně relevantní testy + ruff

## Backlog (ID · priorita · velikost · zdroj · status)

### Fáze 1 — P0
| ID | Úkol | Zdroj | Stav |
|----|------|-------|------|
| B1 | Lockfile s hashi (uv/pip-tools) + CI kontrola verze a SHA-256 `stopa_core` pin v2.6.0 proti manifestu/release assetům | W1/Q10 · S | TODO |
| B2 | Rozdělení `data/db.py` (599/600 řádků) na funkční domény (schéma/připojení, soubory/artefakty, graf/entitní vztahy, integrita/audit, tenancy) — zpětná kompatibilita volání | W2/Q1 · M | TODO |
| B3 | Základ produkční multi-tenancy: AuthN/AuthZ (org/team/case role a oprávnění), vynucená tenant izolace napříč dotazy, nezávislý audit citlivých přístupů/exportů | Q12 · L | TODO |

### Fáze 2 — P1
| ID | Úkol | Zdroj | Stav |
|----|------|-------|------|
| B4 | CI build/test s aktivním Rust wheelem (vedle parity): instalace `[carving]`, běh s aktivním core, kontrola verze pinu | D3/Q3 · S | TODO |
| B5 | Minimální CI build/check Web SPA: node syntax/lint + typová kontrola JSDoc (`tsc --noEmit`), řízené sestavení výstupu pro wheel bez Node u uživatele | W6/Q7 · S | TODO |
| B6 | Statistická brána benchmark engine: percentily (≥P95) vedle mediánu + prahy tolerance (% drift + minimální absolutní práh) — šum se nehlásí, ocas latence se neskrývá | W4/Q11 · S | TODO |
| B7 | Zúžení/konsolidace 60 CLI subpříkazů: příbuzné pod jednotné kořeny s podakcemi + dočasné aliasy s DeprecationWarning (backward compat) | W5/Q4 · M | TODO |
| B8 | Determinismus kolem AI agentů: fixní parametry, přísná schémata výstupů, povinné citace ID důkazů z DB, ověření tvrzení proti případu, audit (prompt + verze modelu + hash vstupu) | D8/Q8 · M | TODO |
| B9 | Kompenzační/diagnostické mechanismy integrity: u řetězců/seal-chain/rotace klíčů přesná lokalizace místa a příčiny selhání, auditní záznam, řízená diagnostika/izolace úseku bez zatajení stavu | D4/Q9 · M | TODO |
| B10 | Strategie pro velké případy (stovky GB): prahy a postupy, archivace velkých payloadů, odlehčené režimy, oddělení centrálních serverových metadat/tenancy od přenosného SQLite kontejneru případu | D2/W8/Q2 · L | TODO |

### Fáze 3 — P2
| ID | Úkol | Zdroj | Stav |
|----|------|-------|------|
| B11 | i18n testy na schéma/proměnné/pokrytí (shoda klíčů cs↔en, placeholdery, pokrytí 341 klíčů) místo křehkých byte-goldens; byte-goldeny jen u nejkritičtějších výstupů | D7/Q6 · S | TODO |
| B12 | Práh přechodu FTS5 → dedikovaný search engine: jasné výkonnostní prahy (objem, složité dotazy, faceting/agregace) + navrh volitelné rozšiřující cesty nad FTS5 | Q5 · L | TODO |

### Průběžná forenzní hygiena (napříč fázemi)
| ID | Úkol | Stav |
|----|------|------|
| H1 | Audit zbývajících tichých `except+pass` (~20) → explicitní logování/validační status (mimo odůvodněné C-bindingy) | TODO |
| H2 | Čistota domain vrstvy: odstranit/izolovat 3 zbývající lazy `domain→data` vazby | TODO |
| H3 | Verzování výstupních schémat CLI/reportů (explicitní output schema version v exportech) | TODO |

## Pořadí realizace
P0: B1 → B2 → B3 · P1: B4 → B5 → B6 → B7 → B8 → B9 → B10 · P2: B11 → B12 · hygiena H1–H3 mezi vlnami.

## Protokol provedených úkolů
_(po každém úkolu doplnit: změněné soubory, výsledek testů/ruff, commit SHA)_
