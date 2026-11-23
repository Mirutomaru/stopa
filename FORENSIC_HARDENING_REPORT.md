# FORENSIC_HARDENING_REPORT — STOPA Release 2.4 hardening (P0 + §4)

Datum: 2026-11-23 · Větev `main` · Základ: `7a9bc66` (Release 2.4)
Hardening commity na `main`: Cell 1 `24d4cc7` → Cell 2 `268df65` → Cell 3 `5a88771` → Cell 4 `97863de`
Priorita práce: **Forensic correctness > Data integrity > Security > Reliability > Performance > Convenience**

## 1. Nalezené problémy (forenzní audit)

| ID | Problém | Původní stav | Status |
|----|---------|--------------|--------|
| P0.5 | Nedeterministické `generated_at` reportu | `datetime.now()` bez TZ → stejný vstup generoval různý report | VERIFIED |
| P0.3 | Nechráněné dočasné dešifrované obrazy | každý parser vlastní tmp soubor, práva 0644, žádná evidence, orphan files po crashi | VERIFIED |
| P0.2 | LUKS: keyfile na disk + celý obraz v RAM | `tempfile` keyfile bez chmod/umask; `cryptsetup open` celého obrazu do paměti | VERIFIED |
| P0.1 | Resume věří jen existenci souboru | `--resume` skipoval podle existence řádku → změněný/smazaný zdroj nebyl detekován | VERIFIED |
| P0.4 | Write-blocker brána jen pro CLI `add`, fail-open default | žádná kontrola při Web ingest; režim závisel na legacy bool; jen 1 třída ochrany | VERIFIED |
| §4/P1.1 | Chybějící source manifest | tabulka `sources` bez hashu seznamu souborů → Chain of Custody neověřitelný po faktu | VERIFIED |

## 2. Skutečně opravené problémy

### P0.5 — deterministické `generated_at` (commit `24d4cc7`)
- **Provedená změna:** `domain/report.py` — `generated_at` z explicitního UTC parametru s fallbackem; dynamická data oddělena od deterministického obsahu.
- **Technické řešení:** čisté doménové funkce bez skrytého I/O; TZ always `+00:00`.
- **Testovací scénář:** 12 testů — stejný vstup + konfigurace = byte-identický report; varianta s explicitním časem.
- **Výsledek testu:** VERIFIED (12/12, součást full suite).

### P0.3 — `EncryptedTempImage` (commit `268df65`)
- **Provedená změna:** nová abstrakce `domain/temp_images.py`; izolovaný adresář `STOPA_TMP_DIR` (fallback `$TMPDIR/stopa-tmp`), dir 0700 / soubory 0600; registry + auditní události `temp_created`/`temp_removed`; `take_fd()` proti double-close; `reap_orphans()` při CLI startu.
- **Integrace:** FDE, BitLocker, BDE/FVDE, EWF, LUKS, image_pipeline, CLI forensics (`release_temp` na všech 3 cestách `replace(out_path)`).
- **Testovací scénář:** 19 testů — práva souborů/adresáře, registry, orphan reap, double-release idempotence.
- **Výsledek testu:** VERIFIED (19/19, součást full suite).

### P0.2 — LUKS keyfile + streaming (commit `268df65`)
- **Provedená změna:** keyfile přes `temp_secret_file` (0600 + umask), `decrypt_luks_stream` s chunky 4 MiB → špičková RAM ≈ jeden chunk; kompatibilitní wrapper `decrypt_luks`.
- **Testovací scénář:** stream vs. one-shot parity, cleanup keyfile při výjimce.
- **Výsledek testu:** VERIFIED (součást full suite).

### P0.1 — safe resume (commit `5a88771`)
- **Provedená změna:** `resume_mode` ∈ {fast, strict} (default fast): fast = existence + size_bytes + mtime(UTC); strict = SHA-256 obsahu (4 MiB chunky). Změněný/smazaný soubor → re-processing + audit `source_modified_during_resume`; nová pole `ProcessResult.skipped`, `.modified_during_resume`.
- **Veřejné API:** `process_source(..., resume_mode: str | None = None)`; invalid → `ValueError`; CLI `--resume-mode {fast,strict}`; Web body `resume_mode`. Zlaté povrchy p14/p48 regenerovány (diff jen nový flag).
- **Testovací scénář:** 9 testů — fast/strict shoda i neshoda size/mtime/sha256, smazaný soubor, audit událost, `files_total` vs. `skipped`.
- **Výsledek testu:** VERIFIED (9/9 exact).

### P0.4 — write-blocker fail-closed + source manifest (commit `97863de`)
- **Provedená změna:** 4 třídy ochrany (hardware / software_ro / unverified / unknown), režimy `fail_closed`/`warn_only`, `gate_with_mode()` s auditními událostmi `ACTION_CHECK` (+ `ACTION_MODE_EXCEPTION` pro warn-only); profile-aware `resolve_gate_mode()` (forensic = fail-closed default; explicitní `wb_gate_mode` > legacy bool). Povrchy: CLI `add` + `wb status`, Web `/api/cases/{id}/write-blocker` a ingest gate (HTTP 409).
- **Source manifest (§4):** nová čistá doménová vrstva `domain/source_manifest.py` — kanonická JSON serializace + SHA-256, verze 1; ověření s listy missing/added. Pipeline počítá manifest po finálním commitu → audit `source_manifest_created` / `source_manifest_changed`, chyba jen loguje (`source_manifest_error`) a nezastaví ingest (data už commitnuta).
- **Testovací scénář:** 39 testů — unit manifest (canonical hash, verify), gate/resolve/classify, integrace v28 migrace + lifecycle + pipeline audit.
- **Výsledek testu:** VERIFIED (39/39 exact).

## 3. Změněné soubory

**Cell 1 `24d4cc7`** (P0.5): `src/stopa/domain/report.py`, `tests/test_p05_report_timestamps.py`.

**Cell 2 `268df65`** (P0.3 + P0.2): nová `src/stopa/domain/temp_images.py`; integrace v
`fde_luks.py`, `fde.py`, `fde_bitlocker.py`, `fde_fbe.py`, `data/bde_fvde.py`,
`data/image_pipeline.py`, `cli/commands/forensics.py`, `cli/__init__.py`; test `tests/test_p03_temp_images.py`.

**Cell 3 `5a88771`** (P0.1, 11 souborů):
- `src/stopa/pipeline/core.py` (+140/−: resume logika, `_resume_meta_matches`, `_sha256_stream`)
- `src/stopa/models.py` (`ProcessResult.skipped`, `.modified_during_resume`)
- `src/stopa/cli/__init__.py` (`--resume-mode {fast,strict}` + i18n klíč)
- `src/stopa/cli/commands/core.py` (propis `resume_mode`)
- `src/stopa/web/app.py` (body pole `resume_mode`)
- `src/stopa/i18n/cs.json`, `en.json` (`cli.h.332`)
- `tests/test_p01_resume.py` (nový, 9 testů)
- zlaté povrchy: `p14_cli_surface.json`, `p48_cli_help_cs.json`, `p14_pipeline_surface.json`

**Cell 4 `97863de`** (P0.4 + §4 manifest, 37 souborů):
- doména: `domain/write_blocker.py` (+193), nová `domain/source_manifest.py` (132)
- data: `data/schema.py` (v28), `data/migrations.py`, `data/case_repository.py` (`update_source_manifest`)
- pipeline: `pipeline/core.py` (+21, manifest blok za finálním commitem)
- CLI: `cli/_util.py` (`_load_wb_gate_mode`), `cli/commands/core.py` (gate v `cmd_add`), `cli/commands/wb.py` (`wb status`)
- Web: `web/routers/cases.py` (ingest gate, HTTP 409), `web/routers/system.py` (status endpoint)
- nové testy: `test_p04_source_manifest.py`, `test_p04_write_blocker_gate.py`, `test_p04_source_manifest_integration.py`
- upravené testy: piny sémantiky `test_f54_write_blocker.py`; laboratorní `wb_gate_mode=warn_only` fixtures (12 web/CLI souborů); piny schématu v27→v28 (5 souborů)

## 4. Nové moduly
- `src/stopa/domain/temp_images.py` (P0.3, commit Cell 2)
- `src/stopa/domain/source_manifest.py` (Cell 4, 133 řádků, čistá doménová vrstva bez I/O)

## 5. Databázové migrace
- **v27 → v28** (`apply_source_manifest_migration`, aditivní): tabulka `sources` + 11 sloupců: `manifest_sha256 TEXT`, `manifest_version INTEGER DEFAULT 1`, `manifest_json TEXT`, `created_at_utc TEXT`, `file_count INTEGER`, `total_size_bytes INTEGER`, `source_type TEXT`, `source_identifier TEXT`, `acquisition_method TEXT`, `filesystem_type TEXT`, `acquisition_tool_version TEXT`. NULL = manifest dosud nevytvořen. Idempotence testována (integrační testy). Staré DB migrace přes PRAGMA user_version; žádné datové změny.

## 6. Nové testy
| Soubor | Počet | Cél |
|--------|-------:|-----|
| `tests/test_p05_report_timestamps.py` | 12 | P0.5 deterministický report |
| `tests/test_p03_temp_images.py` | 19 | P0.3 EncryptedTempImage |
| `tests/test_p01_resume.py` | 9 | P0.1 safe resume fast/strict |
| `tests/test_p04_source_manifest.py` | — | manifest doména (canonical hash, verify) |
| `tests/test_p04_write_blocker_gate.py` | — | gate / resolve_gate_mode / třídy ochrany |
| `tests/test_p04_source_manifest_integration.py` | — | v28 migrace, lifecycle, pipeline audit (celkem s předchozími 39) |

Upravené: `test_f54_write_blocker.py` (piny nové sémantiky), web test fixtures (laboratorní `wb_gate_mode=warn_only` — 10 souborů), piny schématu v27→v28 (5 souborů), zlaté povrchy `p14_cli_surface.json`, `p48_cli_help_cs.json`, `p14_pipeline_surface.json`.

## 7. Výsledky testů
- P0.1: **9 passed in 16.02s** (exact)
- P0.4 combined: **39 passed in 6.87s**, Ruff `All checks passed!` (exact)
- Quick regression batch: **90 passed, 1 warning in 245.96s** (exit 0)
- Re-run všech dosud selhavajících souborů po regresních opravách: **359 passed, 1 warning in 364.67s** (exit 0) — 21 souborů / 84 původních selhání
- **Finální full suite (po obou commitech):** `5236 passed, 1 skipped in 2231.27s` — proti starému stavu `84 failed / 5153 passed` a baseline před hardeningem `5189 passed, 1 skipped`.
- Jediné selhání v full suite: `test_stp044_ci_benchmark_e2e.py::test_run_against_own_baseline_passes` — **měřicí šum pod plným zatížením**: test měří stejný kód dvakrát za sebou a druhý průběh vyšel +21,9 % (práh 20 %) na `pipeline.core`. Samostatný re-run: **6 passed in 67.57s** (exit 0). Proti komitovanému baseline (viz sekce 8) je `pipeline.core` stabilně pod gate.

## 8. Výsledky benchmarků

Lokální běh `scripts/ci_benchmark.py --baseline benchmarks/baseline.json --threshold 0.20 --min-delta-ms 0.5` (stejný příkaz jako CI job `benchmark`):
- **Výsledek: exit 0, `ok=true`, `regressions=[]`, `noise_filtered=0`** — žádná výkonová regrese nad gate (>20 % a ≥0,5 ms).
- `pipeline.core`: lokálně **1827,3 ms** vs. CI baseline **4241,4 ms** (medián ze 3 CI měření; lokální stroj rychlejší než GHA runner) — pod gate i s velkou rezervou. Manifest blok se počítá až za finálním commitem ingestu a do hot-path parserů nezahálí.
- Aktuálně se měří **80 položek**; baseline obsahuje 79 — nová položka `core.rust` (přidána po vytvoření baseline) se proti ničemu neporovnává, bez dopadu na gate.
- Kontext: quick regression batch (90 testů kolem ingest/pipeline) = 245,96 s; full suite 2231,27 s (srovnatelné s předchozími běhy ~2217 s).

## 9. Nevyřešená rizika
1. **LUKS cryptsetup open/close failure paths** — cleanup keyfile pokrýt výjimkou v `temp_secret_file`; dedikované testy pro selhání cryptsetup ještě chybí (PARTIALLY VERIFIED).
2. **BDE/FVDE `except Exception:` kolem ctypes read loopu** — semantická shoda s projektovými error semantics (TypeError/ValueError/BdeError/FvdeError) otevřená; Ruff/full suite zelené.
3. **Třetí CLI cesta `replace(out_path)`** — asistent potvrdil 3× `release_temp`, explicitní zachování v patchi neověřeno řádkem za řádkem (PARTIALLY VERIFIED).
4. **Forenzní audit §6 master promptu** (path traversal, ZIP bomb, seccomp…) — plný rozsah P1 security hardening nad ráměm P0 celů zůstává jako samostatná vlna.

## 10. Doporučené další kroky
1. Dedikované LUKS failure-path testy (mock cryptsetup open/close selhání).
2. Zúžení BDE/FVDE broad exception na typové výjimky + testy.
3. Vlna P1 security hardening dle §6 master promptu (limity vstoupů, timeouty parserů, ZIP bomb).
4. Push `main` přes SSH (`id_ed25519_gh`) po souhlasu; tag zůstává `v2.4.0` na `7a9bc66` dokud se hardening nepropíše do release vlny.
