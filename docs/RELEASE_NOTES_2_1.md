# STOPA 2.1 — Release Notes

**Stav:** candidate — `main` lokálně na `77885d9` (+39 commitů před `origin/main`, push/tag čeká na schválení)
**Datum validace:** 2026-11-18 · **Referenční GA:** STOPA 2.0 (`4a3a867`)

## Shrnutí

STOPA 2.1 je release **bezpečnosti, integity a kvality**. Přidává kompletní
P0 vrstvu (provenience důkazů, klíčová správa pečetí, sandbox pluginů,
forenzní validační laboratoř, threat model) a P1 vrstvu (parser quality
framework s 100 % category coverage, AI orchestrátor, Evidence Graph) plus
hluboký refactoring čtyř god-files bez jediné změny chování. Žádné breaking
změny veřejného API, CLI povrchu ani datových formátů — všechny migrace
schémat jsou aditivní a idempotentní (v19→v20→v21→v22).

## Hlavní změny

### P0 — Bezpečnost & integrita

- **P0-1 Evidence Provenance Engine** — schema v21 (aditivní sloupce
  `hashed_at`, akviziční metadata custody, `parent_artifact_id`); čistá doména
  `provenance_chain.py` s deterministickým buildem řetězce a rozlišením
  *gaps* (tvrdé mezery) / *warnings* (legacy měkké mezery); CLI
  `stopa provenance <case> <artifact>` exit **0**=kompletní / **2**=mezery /
  **1**=chyba + Web endpoint.
- **P0-2 Klíčová správa a rotace Ed25519 integrity klíče** — AES-GCM (AES-256)
  obal soukromého klíče pod master secret z env `STOPA_INTEGRITY_MASTER_KEY`
  (base64, přesně 32 B; unset = legacy plaintext b64); každý kontrolní bod si
  nese `public_key_b64` → **rotace-safe ověření** i po rotaci; nové CLI
  `stopa integrity-keys` a `stopa rotate-key`; živý E2E: gen1→rotace→gen2,
  oba body ověřitelné.
- **P0-3 Plugin sandbox hardening** — `RLIMIT_CPU`, strop `max_output_mb`,
  síťová izolace `unshare --net` (při nedostupnosti výrazná chyba, ne tichý
  fallback), jednorázový izolovaný workdir per run (`STOPA_PLUGIN_RUNS_DIR`);
  opraven latentní bug `.exitcode → .returncode`.
- **P0-4 Forensic Verification Lab** — `stopa parser-status [--json]
  [--fail-on-unvalidated]` (exit 2 = CI gate) + sloupce v Validation Center;
  živý běh: **78/78 parserů validováno**; design doc
  `docs/DIFFERENTIAL_TESTING.md` (referenční nástroje per rodině, verdiktová
  sémantika 5 stavů).
- **P0-5 Security threat model** — `docs/SECURITY_THREAT_MODEL.md`
  (STRIDE-lite T-1..T-10) s důkazy v kódu a residual riziky.

### P1 — Funkce & kvalita

- **P1-1 Parser Quality Framework (uzavřeno)** — 8 standardních kategorií
  (`positive/negative/boundary/corrupted/tz/encoding/locale/size`), konvence
  `# quality:` markerů v testovacích souborech, deterministická
  `synthetic_factory` (stejné seed → identické bajty); **vlny 1–17**: 801
  markerů + per-parser quality sady pro všech 78 parserů →
  **category_coverage_pct = 100 % (624/624 párů)**; CLI `stopa parser-quality
  [--fail-below PCT]` exit 0/1/2 jako CI gate.
- **P1-2 AI Orchestrátor** — čistá doména s 8 agentními rolemi minimálních
  oprávnění (QA read-only), retry+backoff+jitter deterministický přes
  injektovaný RNG, token budget per session, prompt-injection ochrana
  (C0 neutralizace + ZWSP chráněné `[art:]` tokeny); case-level wiring nad LM
  Studio; CLI `stopa ai-run <case> --role ROLE` exit **0**=validovaný výstup /
  **2**=volání OK ale výstup nesplnil schema (QA signál) / **1**=chyba; Web
  `GET /api/ai/orchestrator-status` + `POST /api/cases/{id}/ai/run`; 74 testů.
- **P1-3 Evidence Graph** — unifikovaný graf důkazů (uzly
  `artifact/entity/event/finding/hypothesis`, hrany s polaritou
  `supports/contradicts/neutral` a **povinným důvodem**), derived hrany se
  počítají na letě, explicitní ruční/AI hrany v aditivní tabulce `graph_edges`
  (schema v22) s předností nad odvozenými; CLI `stopa graph <case> [--json]`
  exit 0/1 + Web `GET /api/cases/{id}/evidence-graph`; 43 testů.
- **P1-4 God-files refactoring (uzavřeno)** — všechny čtyři god-files rozloženy
  s byte-přesným zachováním povrchu (golden snapshoty) a bez změny chování:

  | modul | před → po | commit |
  |---|---|---|
  | `cli.py` | 4871 ř. → balíček, facade **821 ř.** (−83 %), 60 příkazů byte-přesné | `ccda3a7` |
  | `web/app.py` | 3455 ř. → facade **1088 ř.** (−69 %) + `web/routers/` (7 modulů, ~2690 ř.), 94 rout byte-přesných | `d4fcabb`, `7435f89` |
  | `pipeline.py` | 1532 ř. → balíček 6 modulů + facade **86 ř.** | `45911f9`, `fc7cfcb` |
  | `validation_registry.py` | 1242 ř. → balíček 9 modulů (datové moduly per ETAPA B rodina) + facade **82 ř.** | `17cd27c`, `77885d9` |

- **Dokumentace** — `docs/ARCHITECTURE_AUDIT.md` (nálezy A-1..A-7),
  `docs/SECURITY_HARDENING.md`, `docs/FORENSIC_VALIDATION.md` (pětivrstvá
  hierarchie s ověřenými milníky).

## Volitelné závislosti (graceful degradation)

Bez nich běží jádro STOPA; funkce se degradují: `pdf` (WeasyPrint — PDF
reporty), `web` (FastAPI GUI), `fde` (cryptography — FDE obrazy), `tsk`
(nativní TSK bindingy), `stix` (STIX 2.1 validátor), `xlsx`, `meta` (Pillow
EXIF), `net` (scapy PCAP/reassembly), `analytics` (DuckDB OLAP).

## Validace (naměřeno na `main @ 77885d9`)

| Kontrola | Výsledek |
|---|---|
| Full regression suite25 (`pytest tests/ -q`, ~22 min) | **4278 passed / 1 skipped**, exit 0 |
| Ruff (repo-wide, line length 100) | clean |
| Golden povrchy P1-4 | CLI 60 příkazů + R0.4 epilogy 14/14; Web 94 rout byte-přesné; pipeline surface 3/3; validation_registry surface 5/5 (datový kontrakt 78 parserů) |
| CI benchmark vs `benchmarks/baseline.json` (práh +20 %, noise guard ≥0.5 ms) | **80/80 položek OK** — baseline regenerována v tomto release, viz „Známé limity“ |
| Rozpočet `src/stopa/data/db.py` | 599 < 600 ř. |
| Offline/determinismus | testy bez síťových služeb (LM Studio/stix2/WeasyPrint fake nebo `importorskip`) |

## Známé limity

1. **Benchmark baseline `pipeline.core` regenerována (dříve zastaralá)** —
   původní versionovaný údaj 37.476 ms (STP-046) vznikl *před* zařazením
   sandbox izolace parserů do pipeline (STP-047, subprocess per extraktor) a
   nebyl na vývojovém stroji reprodukovatelný (warm single-shot i na původním
   commitu `de18452` ≈ 810 ms). Párové měření origin/main vs HEAD prokázalo,
   že vlny P1-4 nepřidávají měřitelnou přirážku (běhy se kříží v šumu ±15 %).
   Baseline proto regenerována: `pipeline.core` = 1726.838 ms + doplněna
   chybějící položka `core.rust` (F21); verifikační běh proti nové baseline
   **80/80 bez regresí**. Pozor: při vysoké zátěži stroje může tato položka
   být na pokraji 20 % prahu — CI job to maskuje `continue-on-error`.
2. **P2 položky neimplementovány** (každá vlastní návrh + priorita + AK před
   implementací): timeline v2, plugin marketplace, multi-user kolaborace apod.
   — viz `docs/ROADMAP_2_1.md`.
3. **Frontend parity v průběhu** — legacy static UI je stále primární; SPA
   parity mapa S1–S10 definována (`docs/FRONTEND_MIGRATION.md`), kroky jsou
   samostatné releasovatelné celky.
4. **Bezpečnostní QA pipeline** — CI job `security` = pip-audit (známé
   zranitelnosti v závislostech); statická analýza kódu (Bandit/Semgrep) a
   kontejner scan (Grype) jsou plánovány, zatím neintegrované.

## Upgrade notes

- **Schéma**: case DB se při open automaticky migrují aditivně a idempotentně
  do v22 (`graph_edges` + index; dříve v21 provenance sloupce, v20 integrity
  `public_key_b64`) — stará data beze změny.
- **Nové env**: `STOPA_INTEGRITY_MASTER_KEY` (volitelný base64 master secret),
  `STOPA_PLUGIN_RUNS_DIR` (workdir plugin běhů, default `~/.stopa/plugin-runs/`).
- **CLI/Web/API**: žádné breaking změny; entry point `stopa = "stopa.cli:main"`
  a `python -m stopa.cli` fungují beze změny.
