# STOPA 2.4 — Release Notes

**Stav:** připraveno k pushi — `main` lokálně (11 commitů před `origin/main`; push/tag v tomto releasu)
**Datum validace:** 2026-11-22 · **Referenční GA:** STOPA 2.3 (`7ca55f5`, tag `v2.3.0`)

## Shrnutí

Post-release roadmap P4 (zdroj: `STOPA_ANALYZE.md` §8 známý dluh) kompletní — všech 10 položek
hotových: CI matrix pro volitelné extras, semvering Plugin API, hardening plugin sandboxu,
Sealing v2 (time hash chain + externí witness), AI production robustness, sjednocení frontendu
(SPA kanonická), cross-platform a long-running stabilita, i18n CLI (+ legacy UI katalog),
multi-node readiness a Rust distribuce (manylinux wheels).

Kompatibility: veřejné API/CLI/formáty beze změny; CS CLI help byte-kompatibilní (p48 guard);
aditivní migrace case DB **v26→v27** (P4-6 `seal_chain`) + instance DB (idempotentní lease
sloupce registrů a tabulka `events`, P4-7). Nové volitelné extra **carving** — bez něj
čisté-Python fallback beze změny.

## Hlavní změny

### P4-1 CI matrix pro volitelné extras (`eae3417`)
Dva profily per push: `test` = min instalace bez optional extras (**min profil**
4609 passed / 336 skipped, exit 0; ≈31 min — referenční cesta) + nový job `test-full`
(všechny extras nainstalovány; yara-python 4.5.4 v CI).
Audit odhalil ~20 implicitních závislostí na volitelných balících → fail-open fallbacky místo
tichého selhání.

### P4-3 Plugin API semvering + breaking change log (`1d913f9`)
`docs/PLUGIN_API.md` — verzování API, uzavřená smlouva (entrypoint, context, kapacity),
breaking change log; volitelné manifest pole `api_version` + validace hostem.

### P4-2 Plugin sandbox hardening (`5bfb3a5`)
W1 audit (seccomp konstanty/RET/jump opravy; ABI tabulky cross-check x86_64 73/73 + aarch64
65/65), W2 seccomp-BPF whitelist + rlimit, W3 strict mode fail-closed.

### P4-6 Sealing v2 — time hash chain + externí witness (`d170209`)
W1 čistá doména `domain/seal_chain.py` (každý záznam vazí předchozí Merkle kořen — řetěz,
fail-closed ověření), W2 migrace **v27** `seal_chain` (case DB), W3 CLI `stopa seal chain ...` +
Web `/api/cases/{id}/seals/chain`, W4 docs, W5 26 testů.

### P4-5 AI production robustness (`0dacd1c`)
W1–W5: retry/backoff pro LLM volání, timeouty, SSE stream endpoint; validace 69p + p12 regrese 9p.

### P4-4 Frontend sjednocení — SPA kanonická (`06b7c45`)
Kořen `/` = kanonická SPA (React build), legacy GUI non-kanonické pod `?ui=legacy` s deprecation
bannerem; nové SPA view `/attack` (ATT&CK heat-mapa) + `/reports`; graceful degradation na legacy
bez SPA buildu. Frontend: Vitest 6 files/20 tests, tsc clean, vite build OK.

### P4-9 Cross-platform a long-running stabilita (`1b9c2f2`)
W1 audit cross-platform readiness, W2 leak canary (deterministický ingest loop), W3 CI jobs
Windows + macOS smoke s kurátorovaným portability core (15 souborů) bez Rust wheelu → carving
čisté-Python cestou; full suite zůstává Ubuntu-only. W4 `docs/PLATFORM_MATRIX.md`.

### P4-8 i18n CLI (+ legacy UI katalog) (`763d2b2`)
cs/en katalogy (339 klíčů), fail-open `t()`, flag/env/default priorita `--lang` / `STOPA_LANG`;
CS byte-kompatibilní CLI help (87/87 cest), EN AK clean (top help + 100 % epilogů anglicky);
Web `/api/i18n/{lang}` rout. Testy 23p, min profil 27p.

### P4-7 Multi-node readiness (`7e4c0b3`)
W2 DB event bus (tabulka `events`, monotónní pořadí, retence 2 h) + WAL/busy_timeout v
`open_instance()`, W3 registry lease/heartbeat (LEASE_WINDOW=8), web poller auto-heartbeat,
CLI `stopa registry --heartbeat NODE_ID`; `docs/MULTI_NODE.md`. Cílené 124p, min profil 28p.

### P4-10 Rust distribuce (`1cbda7b`)
`stopa_core` s PyO3 **abi3-py310** (jeden wheel per platforma pro Python ≥ 3.10); release job
`rust-wheels` v manylinux_2_28 kontejneru (x86_64 nativně, aarch64 cross `maturin --zig`,
verifikace přesného tagu proti degradaci na `linux_*`); CI parity gate `rust-parity`; nové extra
**carving** pinuje wheels z tohoto release. Lokální E2E: wheel cp310-abi3 → čisté venv, F2.1
parity 17/17.

## Validace

- Full regression: **`5155 passed / 1 skipped`, exit 0** (36:31; +142 testů vs báze 5013p na STOPA 2.3).
- Ruff clean repo-wide, rozpočet `db.py` **599/600**, PKG_COMPAT OK (`python -m stopa.cli --version` exit 0; bez subcommandu čistý argparse exit 2 bez tracebacke).
- Povrchové goldeny: CLI povrch 87 cest bez změny (CS byte-kompatibilita p48; P4-7 jen text registry), Web **123 rout** (+`seals/chain`, +SSE `ai/run/stream`, +`/api/i18n/{lang}`).
- Lokální E2E P4-10: wheel cp310-abi3 → čisté venv, F2.1 parity 17/17; .venv aktualizováno na nový wheel.

## Známé limity

- Extra **carving** = jen Linux x86_64/aarch64 (glibc ≥ 2.28); Windows/macOS/jiná arch =
  úmyslná referenční cesta (čisté Python). Wheels se generují od release v2.4.0 (job `rust-wheels`).
- yara-python zůstává volitelný (extra `rules`); bez něj YARA matching explicitně RuntimeError.
- Multi-node: jen SQLite; event bus = polling 250 ms ne push; lease posuzuje monotónní generace,
  ne wall-clock.
- SPA je kanonická na `/`; legacy UI dostupné pod `?ui=legacy` (deprecation banner).
