# ARCHITECTURE AUDIT — STOPA (stav k 2.1)

Audit dle master promptu Fáze 1: **nejdřív audit, pak změny**. Každý nález je doložen
souborem/modulem; rozdělení P0/P1/P2 viz `ROADMAP_2_1.md`. Dokument odpovídá
**skutečnému stavu kódu**, ne plánu.

## 1. Metoda

- Statická inventarizace vrstev (LOC, počty modulů) + kontrola závislostí (`pyproject.toml`).
- Kontrola dodržování Clean Architecture: `domain/` = čistá logika bez I/O,
  `data/` = SQLite/I-O repozitáře a služby, `artifacts/` = parsery,
  `web/` + `presentation/` + `cli.py` = prezentace.
- Ověření veřejných kontraktů: CLI příkazy, Web endpointy, databázové schéma
  (`SCHEMA_VERSION = 21` v `src/stopa/data/schema.py`).

## 2. Vrstvy a velikost (měřeno `wc -l`)

| Vrstva | Soubory | Řádků | Poznámka |
|---|---:|---:|---|
| `domain/` | 83 | 19 080 | čistá logika; bez I/O (konvence, testováno importy) |
| `artifacts/` | 91 | 22 478 | 78 parserů (C3 registry: `domain/validation_registry.py`) |
| `data/` | 38 | 9 328 | SQLite facade, repozitáře, služby (parser_status, provenance…) |
| `web/` | 2 | 3 349 | Flask app (`app.py`) + static UI |
| `presentation/` | 5 | 1 172 | prezentace pro CLI/GUI sdílené helpery |
| `cli.py` (root) | 1 | 4 727 | argparse monolit — viz nález A-3 |
| **tests/** | 161 | 48 406 | plně offline a deterministické |

## 3. Závislosti

**Hard dependency jen 3** (`pyproject.toml`): `pydantic>=2.5`, `regipy>=6`,
`rich>=13`. Volitelné extras s graceful degradací (testy přes
`pytest.importorskip` / try-import): `cryptography` (Ed25519 seals),
`stix2` (F6.2 export), `weasyprint` (PDF report). Síť není pro základní
forenzní práci povinná — LM Studio klient (`data/lmstudio_client.py`) se
degraduje na `LmStudioUnavailable` → HTTP 503.

## 4. Klíčové moduly a jejich role (ověřeno v kódu)

- **Provenance**: `domain/provenance_chain.py` + `data/provenance_repository.py`
  — řetězec původu artefaktů, CLI `stopa provenance` exit codes 0/1/2.
- **Integrita**: `domain/integrity.py` (Ed25519 checkpoints, AES-GCM master key
  `STOPA_INTEGRITY_MASTER_KEY`, Merkle seal) + rotace klíčů v CLI.
- **Pluginy**: `domain/plugins.py` + `data/plugin_loader.py` — sandbox s rlimits
  a izolovaným workdir (P0-3), API `docs/PLUGINS_API.md`.
- **Validace parserů**: C3 registry (`validation_registry.py`, 78 parserů se
  `test_files`) + `domain/parser_quality.py` (P1-1, 8 kategorií kvality).
- **AI**: `domain/ai_assistant.py` (prompt buildery E11), `domain/ai_grounding.py`
  (grounding claimů na artefakty), `domain/ai_orchestrator.py` (P1-2 role agentů).

## 5. Nálezy auditu

| # | Priorita | Nález | Důkaz / dopad | Stav |
|---|---|---|---|---|
| A-1 | P0→hotovo | Pluginy běží bez sandbox limitů (CPU/output/síť) | `data/plugin_loader.py` — opraveno v P0-3 (`_rlimit_factory`, `_isolated_workdir`) | ✅ hotovo |
| A-2 | P0→hotovo | Privátní seal klíč v plaintextu b64 bez master keye | `domain/integrity.py` — opraveno v P0-2 (AES-GCM, fail-fast ValueError) | ✅ hotovo |
| A-3 | P1 | `cli.py` je monolit 4 727 řádků | jeden soubor; rozdělení do `cli/` package = refactor bez změny chování — riziko regresí při ručním přepisování | 🟡 na plánu (etapa E) |
| A-4 | P1 | Databázová facade `data/db.py` u budgetu 599/600 řádků | měřeno po GA; nové metody přidávat opatrně, preferovat repozitáře | 🟡 sledovat |
| A-5 | P2 | Frontend: dvě UI generace (legacy static + React SPA) | `web/static` vs `frontend/`; parity mapa `docs/FRONTEND_MIGRATION.md`, kroky S1–S10 | 🟡 na plánu (P0-6 migrace) |
| A-6 | P2 | Benchmark flaky pod CPU zátěží (stp044) | suite12: `pipeline.core` +75.4 % mezi dvěma běhy; standalone 6/6 green — nutno stabilizovat prahy | 🟡 na plánu |
| A-7 | P0→hotovo | Chybějící evidence provenance (parent_artifact_id, hashed_at) | `schema.py` v21 + `migrations.py` idempotentní migrace | ✅ hotovo (P0-1) |

## 6. Závěr auditu

Architektura drží Clean Architecture konvenci; největší rizika jsou velikost
`cli.py` (A-3), rozpočet `db.py` (A-4) a dvojí frontend (A-5). Všechny P0
nálezy byly v 2.1 opravené malými kontrolovanými změnami s testy; viz
`ROADMAP_2_1.md` a `STOPA_CHANGELOG.md`.
