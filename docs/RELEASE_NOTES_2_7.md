# STOPA 2.7 — Release Notes (post-release develop vlna B1–B12 + H1–H3)

**Stav:** main = `d52e2d7` (docs vlna 17, lokální); tento release = bump + tag `v2.7.0` na vrchol main; reference GA = STOPA 2.6 (`55454ca`, tag `v2.6.0`)
**Datum validace:** 2026-11-26

## Shrnutí

Post-release develop vlna nad tagem `v2.6.0` (nad revizními vlnami P1+P3/P4): **dokončení PLAN_BACKLOG B1–B12 + H1–H3** — prioritizováno forenzní/architektonickou evaluační; metodika = jedna úloha za sebou, po každém kroku cílené testy + ruff (`All checks passed!`); priorita dle auditu: Forensic correctness > Data integrity > Security > Reliability > Performance > Convenience.

**Semver MINOR (2.7.0)** — zdůvodnění:
- nový CLI příkaz `stopa case scale <case_id> [--rebuild-fts]` + sekce search (B10/B12) — aditivní,
- **schéma case DB v28 → v29** (`sources.ingest_profile TEXT DEFAULT 'forensic'`, B10; čistě aditivní idempotentní migrace, legacy případy beze změny),
- konzolidace 19 plochých CLI příkazů do 5 skupin `integrity/import/forensic/crypto/court` (B7) — stará jména fungují dál jako skryté BC aliasy s byte-identickým dispatchem (+DeprecationWarning),
- verzovaný kontrakt výstupů `--json`: každý output nese `stopa_output_schema=1`; audit trail zabaleno do `{stopa_output_schema, items}` (H3) — konzumenti čtou explicitní verzi,
- Web: WS tenancy izolace + per-case RBAC + egress audit (B3) — aditivní hardening.

Veřejné Python API je čistě **aditivní**: nové domain moduly `case_scale`, `search_scale`, `output_schema`, neutrální vrstva `core/` (rust_core/diagnostics), doménové facade mixiny pro db.py; žádné odstranění/přejmenování existujících veřejných symbolů (`data.rust_core` / `data.diagnostics` zůstávají BC shimy = alias stejného modulového objektu, monkeypatch identity zachována).

## Hlavní změny

### B1 [P0·S] — Lockfile + Rust wheel pin (commit `392d335`)
- `uv.lock` s hashi pro všechny závislosti; fail-closed pin stopa_core wheels (SHA-256) v CI jobu `lockfile-rust-pin`; reprodukovatelnost instalace i volitelného Rust core.

### B2 [P0·M] — Rozříznutí `data/db.py` na doménové facade mixiny (commit `d352d65`)
- 599 → **88 řádků** v `db.py`; logika přesunuta do doménových facade mixynů; BC API beze změny (`StopaDB` = kompozice).

### B3 [P1·M] — Základ multi-tenancy ve Web vrstvě (commit `8a36e21`)
- WS tenancy izolace + per-case RBAC (fix NOCTX) + egress audit; tenancy separace F4.4 (instance DB vs case kontejner) doplněna o test pin portability.

### B4 [P1·M] — CI build/test s aktivním Rust wheelem (commit `b49a7e5`)
- `[carving]` extra v CI; nový job `test-active-core`: full suite běží s **aktivním** stopa_core wheel 0.1.0 (ne jen fallback); pin wheels v2.6.0.

### B5 [P1·M] — Minimální CI build/check Web SPA (commit `72ddd8c`)
- Nový job `web-spa`: `npm ci` s pinned lockem, **tsc --noEmit** (strict), `node --check public/sw.js`, **vitest run**, řízené sestavení s **freshness kontrolou** — vite build píše do `src/stopa/web/static/spa`; jakákoli změna proti commitnutému artefaktu = stale build → fail.

### B6 [P2·S] — Percentilová brána benchmark engine (commit `f7903e7`)
- Engine sbírá per-iterace vzorky; percentilová matematika = čistá domain funkce `percentile()` (linear interpolation); `BenchmarkResult.median_ms/p95_ms` (None u starých běhů = BC), `RegressionWarning.axis ∈ mean|median|p95`; regrese porovnává **každou osu nezávisle**; baseline v1→v2 in-place migrace (79 položek, konvence: z CI měření); CLI `repro benchmark` ukazuje med/p95.

### B7 [P2·M] — Konzolidace CLI subpříkazů do doménových skupin (commit `ad72b7b`)
- 19 plochých příkazů → **5 top-level skupin** (`integrity`, `import`, `forensic`, `crypto`, `court`); stará jména = skryté BC aliasy (`help=argparse.SUPPRESS`) s byte-identickým dispatchem; `main()` emituje DeprecationWarning pro stará jména + přepis legacy formy `stopa integrity <case_id>` → `integrity check`; goldeny p14/p48 přegenerovány jako čistý superset (+187/−0, +23/−0 cest).

### B8 [P2·M] — Determinismus kolem AI agentů (commit `7fac9ac`)
- **Fixní sampling**: `temperature=0.2`, `top_p=1.0` explicitně v odchozím payloadu; klient nese `last_model` = auditní identita skutečně použitého modelu.
- **Přísné typy výstupů** (`ROLE_OUTPUT_TYPES`, numerická pole odmítají bool) + čisté funkce `extract_citation_ids()`/`validate_citation_ids()`.
- **Grounding citací**: role timeline/hypothesis/report bez jedné validní citace → `payload=None, grounded=False` (spekulace LLM se netichozelená); evidence odkazuje strukturálně přes `findings[].artifact_id`.
- **Auditní identita**: každý záznam nese `model` + `temperature` + SHA-256 promptu (`fingerprint_messages`) — stejný hash + model → srovnatelná odpověď.

### B9 [P0·M] — Diagnostické mechanismy integrity (commit `4634058`)
- **F-1 audit chain**: `ChainDefect(row_id, kind, message)` + kinds `hash_mismatch/link_broken/row_missing/genesis_mismatch`; `collect_all=True` proskenuje celý řetězec; po hash mismatch se linka čeká od uloženého hashu → každý tamperovaný řádek lokalizován zvlášť (bez kaskádového maskování).
- **F-2 seal v2**: čistá doménová `collect_chain_defects()`; report nese aditivně `"defects": [{seq, kind, message}]`; fail-closed BC beze změny.
- **F-3 rotace klíčů**: explicitní transakce (audit entry s otisky starého/nového pub + výměna páry + checkpoint) all-or-nothing; chybějící checkpoint → `ValueError`.
- **F-4 povrch**: CLI `integrity check` (human: všechny defekty na stderr, JSON aditivně `kind/defects`) a web `/api/cases/{id}/audit` — oba přes `collect_all=True`.

### B10 [P1·M] — Strategie pro velké případy (stovky GB) (commit `98c48df`)
- Čistá doména `domain/case_scale.py`: prahy 500k souborů / 100 GiB / 200k artefaktů → tier small|medium|large + doporučené postupy jako data.
- Data: read-only cross-table statistika `case_scale()` + `rebuild_fts()` (FTS5 REBUILD obou indexů + invalidace cache).
- **Migrace v29**: `sources.ingest_profile` (provenience gap — profil už nejeví jen v auditním entry, ale v tabulce; legacy = default 'forensic').
- CLI `stopa case scale <case_id> [--rebuild-fts] [--json]`; pipeline zapisuje skutečný profil na začátku zpracování.

### B11 [S] — i18n testy na schéma/proměnné/pokrytí (commit `152b090`)
- Test-only sada: schéma katalogu (flat, formát klíčů), **placeholder konzistence cs↔en** (doteď nechráněná — divergence = tiché `{x}` v runtime), pokrytí forward/reverse (žádný mrtvý/chybějící klíč), call-site parametry přes AST.

### B12 [P1·S] — Práh přechodu FTS5 → dedikovaný search engine (commit `5a7a138`)
- Čistá doména `domain/search_scale.py`: prahy 500k/200k/50k řádků (graph_edges = naměřená O(A·E) stěna); tier `fts_ok|fts_watch|engine_candidate` (max ratio, watch 0.1).
- Read-only facade `search_workload()`; CLI `case scale` rozšířeno o sekci search (JSON + lidský výstup). Rozšiřující cesta (SearchBackend/sidecar engine) = navrh bez implementace — až tier se v praxi objeví.

### H1 [hygiena] — Tiché `except+pass` (commit `b5383f8`)
- AST audit: bucket A = přesně 20 pass-only handlerů; **7 lokací tiché degradující data dostalo explicitní log** (case_repository warning, evidence_storage/mobile_forensics/plaso_import/sqlite_carver debug); 4 odůvodněné no-op fallbacky doplnily komentáře.
- **AST guard test** pinuje auditní stav + brzda proti novým tichým regrese; behavior testy pro opravené lokace; latentní bug stp057 (16 polí místo 17) opraven.

### H2 [čistota vrstev] — Izolace 3 lazy `domain→data` vazeb (commit `6657d5a`)
- Nový balíček **`src/stopa/core/`** = neutrální runtime capability vrstva: `rust_core.py` + `diagnostics.py` přesunuty z `data/` (obsah beze změny, git rename 100 %).
- BC shimy v `data/` = **alias stejného modulového objektu** (silnější než re-export — podmínka funkčnosti monkeypatche F21); domain mění jen 3 import řádky; chování bitově identické.
- Guard test: AST scan domain bez importů do `stopa.data.*` + shim identity pin + behavior pin fallback cest.

### H3 [verzování schémat] — Explicitní verze výstupních schémat CLI --json + HTML report (commit `82135d5`)
- Jediný zdroj pravdy = čistá domain konstanta `domain/output_schema.py`: `OUTPUT_SCHEMA_VERSION=1`, klíč `stopa_output_schema`.
- **CLI**: všech 89 výstupů přes chokepoint `_print_json()` — dict dostává verzi aditivně; audit trail (jediný list) zabaleno do `{stopa_output_schema, items}`.
- **Report**: `<meta name='stopa-output-schema'>` v `<head>` + cover řádek „Verze výstupního schématu: v1" (court-ready). Souborové exporty = ustálené BC formáty beze změny.

## Validace

- **Full suite #1 (pre-fix, HEAD `d52e2d7`):** `5478 passed, 6 failed` — šest zastaralých pinů/flakes odhaleno po vlně H3/B; oprava `a6bceee` (test-only, chování beze změny):
  - `test_p47_multi_node` + `test_p22_registry_cli_web` — **H3**: všechny `--json` výstupy nesou `stopa_output_schema` (dict aditivně; audit trail zabaleno do `{stopa_output_schema, items}`) → strict piny aktualizovány.
  - `test_stp044_ci_benchmark_e2e` ×2 — **B6**: baseline formát v1→v2 (`{median_ms,p95_ms}`), stderr `REGRESIE[axis] name`; self-comparace na hlučném dev stroji s `--threshold 0.5` (citlivost prokazují umělá regrese +100 % a deterministický stp043).
  - `tests/golden/p48_cli_help_cs.json` — **B7/H3**: help 5 grupových příkazů dostal „Příklad:“; přesně těch 5 klíčů přegenerováno, sada klíčů bez změny.
  - `test_fde::test_corrupt_ciphertext_raises` — latentní flake (~0,4 %): poškození jen C[-1] dává uniformně náhodný poslední blok (PKCS7 padding může zůstat validní); nyní poslední bajt C_prev → deterministicky pad=243 → FdeError.
- **Full suite #2 (release evidence):** `5484 passed, 2 skipped in 2382.67s (0:39:42)`, exit 0 — vše zelené; deterministická a offline; Rust core = aktivní wheel 0.1.0 z `.venv` (B4), WeasyPrint/stix2/yara optionální extras nainstalovány.
- Cílené baterie podle úloh (záznamy v `.stopa-dev/PLAN_BACKLOG_2026-11.md`): B7 BC batch **387+164 passed** (+p48 50); B8 AI baterie **99 passed** + regresní **113 passed**; B9 BC **72 passed**; B10 **238 passed**; B11 **58 passed**; B12 **107 passed**; H1 **340 passed**; H2 **104 passed, 1 skipped**; H3 **141 passed** (+b7_cli_groups 19, b11+r04 20)
- Ruff clean po celém repu (`ruff check src tests` = `All checks passed!`); PKG_COMPAT OK (Python 3.13 / pydantic v2 / SQLAlchemy 2.x)
- Reference `v2.6.0`: Release workflow run `45335108982` = success (6/6), wheels x86_64/aarch64 publikovány na GitHub Releases; wheel E2E OK (`rust_version()=0.1.0`)
- GitHub CI (nyní **11 jobů**: +`web-spa` B5, +`test-active-core`, +`lockfile-rust-pin` B1/B4) a Release workflow `v2.7.0`: validováno po pushi (viz post-release monitoring)

## Známé limity / reziduální rizika

1. **B9 F-4 consumer coverage** — `cmd_rotate_key` v `cli/commands/integrity.py` není na řádkové úrovni plně ověřeno, že spotřebuje `verify_audit_chain`/`ChainReport`; rotace sama je pokryta B9 DB testy (atomicita + audit entry).
2. **macOS arm64 capacity flake** — může se opakovat v CI (P2 vyžadoval re-run #3); připravený fallback: pin `runs-on: macos-15-intel` + aktualizace PLATFORM_MATRIX.md (neaplikován, jen při opakování).
3. **B10 odsun**: disk-based offload velkých `artifacts.details_json` payloadů — dokud `case scale` neprokáže reálný růst (anti-overengineering rozhodnutí).
4. **B12 rozšiřující cesta** (SearchBackend/sidecar engine) = navrh bez implementace — až tier `engine_candidate` se v praxi objeví.
5. **Lokální kontejnerová inspekce**: `docker` chybí, `podman` blokovaný na `libsubid.so.5` (instalace nesouhlasena) — dotýká se jen lokálního dev ověření Docker image jobu.
