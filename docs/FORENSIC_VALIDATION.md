# FORENSIC VALIDATION — STOPA 2.1

Jak je forenzní správnost aplikace ověřována a co je k tomu dnes reálně hotové.
Princip z master promptu: **AI výstupy nejsou automaticky potvrzená fakta** —
každý validační mechanismus má test, měřitelnou metriku a doložený důkaz v kódu.

## 1. Vrstvy validace (od nejnižší)

### Vrstva 1 — Testy parserů (C3 registry)
- `domain/validation_registry.py`: **78/78 parserů má deklarované test files**
  a všechny soubory existují (ověřeno programovým průzkumem registry).
- CLI `stopa parser-status` (P0-4): stav validace per parser, exit code pro CI;
  live E2E potvrdilo **78/78 validováno**.
- Testy plně offline a deterministické — síť není povinná.

### Vrstva 2 — Parser Quality Framework (P1-1)
Každý parser musí pokrýt 8 kategorií vstupů: `positive, negative, boundary,
corrupted, tz, encoding, locale, size`.
- Konvence: řádek `# quality: <kategorie...>` v testovacím souboru deklaruje
  pokrytí (regex `_MARKER_RE` v `domain/parser_quality.py`).
- Metriky v reportu/JSON: `coverage_pct` (plně kompletní parsery) a
  `category_coverage_pct` (jemnější progress metrika — podíl pokrytých
  parser×kategorie párů). CLI gate: `stopa parser-quality --fail-below PCT`.
- **Syntetická data** (`data/synthetic_factory.py`): deterministická per seed,
  anonymizovaná; generátory pro Chrome/Edge history (µs od Windows epochy),
  Firefox places (ms od Unix epochy), iMessage chat.db (CFAbsoluteTime od 2001)
  a mbox (Date hlavičky v různých offsetech + RFC 2047 B64/Q předměty).
- Stav: pilotní sady pro **sqlite** a **email_mbox** pokrývají všech 8 kategorií;
  bázisové markry pro všechny parsery doplněné (vlna 1, 801 markerů ve 33
  souborech); aktuální `category_coverage_pct` sleduje CLI/ROADMAP.

### Vrstva 3 — Evidence Provenance (P0-1)
- Řetězec původu artefaktů: `parent_artifact_id`, `hashed_at` (schéma v21,
  aditivní sloupce, idempotentní migrace).
- Doménová logika `domain/provenance_chain.py`: kontrola kontinuity řetězce,
  hash shoda; CLI `stopa provenance <case> <artifact>` s exit codes
  **0 = kompletní řetězec / 2 = neúplný (gaps) / 1 = chyba nebo neznámý artefakt**
  — live E2E ověřeno pro všechny tři kódy.
- Web endpoint `GET /api/cases/{id}/artifacts/{id}/provenance`.

### Vrstva 4 — Integrity a reprodukovatelnost (F5.x + P0-2)
- **Ed25519 checkpoints** (`domain/integrity.py`): každý checkpoint podepsán;
  veřejný klíč per-checkpoint v `public_key_b64` (schéma v20).
- **Merkle seal** over artefaktů: deterministický root, detekce změny důkazů.
- **Master key management** (P0-2): privátní klíč šifrovaný AES-GCM klíčem z
  `STOPA_INTEGRITY_MASTER_KEY`; fail-fast na neplatném base64/délce; backward
  compat se starým plaintext b64.
- **Reproducibility engine** (F5.x): verze parserů + re-run analytického
  pipeline s porovnáním výstupů.

### Vrstva 5 — AI validace (P1-2)
- `domain/ai_grounding.py`: každý claim AI odpovědi musí mít citaci artefaktu,
  která existuje v případě (`ground_answer` → `GroundingReport`).
- PII redakce promptů (`_maybe_redact`, e-maily/adresy).
- Role agentů s minimálními oprávněními + validace strukturovaných výstupů
  per role (`ROLE_OUTPUT_SCHEMA`) — AI výstup bez povinných polí = chyba.

## 2. Diferenciální testování

`docs/DIFFERENTIAL_TESTING.md`: reference datasety vs výstupy parserů;
kriteria shody a formát reportu. Reference datasets se postupně doplňují v
C3 registry (`reference_dataset` pole).

## 3. Ověřené výsledky (výběr)

- Release 2.0 GA baseline: **3652 passed / 1 skipped** (full regression, commit `4a3a867`).
- P1-1 framework + pilotní sady: **44 testů green**, Ruff clean; live CLI JSON
  kontrakt ověřen (count=78).
- Vlna 1 quality markerů: **905 testů** v dotčených souborech green, Ruff clean.
- P0-1 provenance: 23/23 standalone + live E2E exit codes 0/2/1.
- P0-2 seal keys: 77/77 cíleně; rotace klíčů E2E (starý klíč zůstává čitelný).

Živé aktuální počty testů a coverage sleduje `stopa parser-quality` a ROADMAP —
tento dokument uvádí jen stabilní ověřené milníky.

## 4. Co zbývá (doplnit do 2.1)

- Per-parser fixture pro chybějící kategorie (tz/encoding/locale/size) u zbývajících
  parserů — viz P1-1 v `ROADMAP_2_1.md`.
- Reference datasety (`reference_dataset` v C3 registry) — zatím doplněny jen
  pilotně; cíl: každý formát s aspoň jedním referenčním vzorkem.
- Upload fuzzing do validačního labu (T-10).
