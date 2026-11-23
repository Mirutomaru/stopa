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

### P1 S1 — bounded XML parse důkazových souborů (commit `f20d56f`)
- **Provedená změna:** nová čistá doménová vrstva `domain/xml_bounded.py` (`bounded_xml_parse`, `XmlLimitError(ValueError)`). Manuální wiring přes pyexpat — C `_elementtree` maskuje interní expat a ElementTree si `EntityDeclHandler` sám nepropojí. Depth limit (default 200, konfigurovatelný), zákaz uživatelských entit (billion laughs) při průchodu předdefinovaných (`&amp;` apod.), 64 KiB streaming file-like vstupů, `ordered_attributes=1`. Call sites: ODF `content.xml`, OOXML docProps (+ per-member limit 256 KiB), Windows Scheduled Task XML, WLAN profile XML, UFED `report.xml`.
- **Výsledek testu:** VERIFIED — `tests/test_p1_xml_bounded.py` **18 passed in 0.06s**; ekvivalence s `ET.fromstring` probe 3/3 (namespace atributy, entity, UTF-8); regrese dotčených parserů **255 passed**.

### P1 S2 — limity ZIP bomb pro import-mobile archívy (commit `42a97b9`)
- **Provedená změna:** `_archive_members` v `cli/commands/forensics.py` měl jen per-member limit 256 MiB; přidány celkové limity jako module globály `_MAX_ARCHIVE_MEMBER/_TOTAL/_MEMBERS` (256 MiB / 4 GiB / 20 000 — legitimní UFED/ADB exporty < 1 GB). Počtový limit → warning + konec sběru; velikostní limit → skip konkrétních členů (forenzní pokrytí co nejširší); prázdný výsledek → exit 2.
- **Výsledek testu:** VERIFIED — `tests/test_p1_zip_bounded.py` **5 passed in 8.53s** (offline E2E přes `cli.main`, limity monkeypatchovány).

### P1 S3 — path traversal validace v `_last_export_path` (commit `b6d1655`)
- **Provedená změna:** audit §6 (path traversal / symlinks / TOCTOU) potvrdil solidní politiku: strict regex case_id `^[A-Za-z0-9_-]+$` (bez tečky i lomítka), enum `what`/`format`, DB lookup před cache přístupem; ingest symlink policy (`followlinks=False` + per-file `is_symlink()` skip); atomický tmp→rename. Zbývající mezera — `_last_export_path` důvěřoval volajícím endpointům — uzavřena vlastní validací (defense in depth, 400).
- **Výsledek testu:** VERIFIED — `tests/test_p1_path_traversal.py` **6 passed**; regrese export cache endpointů (stp067/068/069) **35 passed**.

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

**Cell S1 `f20d56f`** (P1 bounded XML, 7 souborů):
- nová `domain/xml_bounded.py` (114 řádků) + `tests/test_p1_xml_bounded.py` (18 testů)
- call sites: `artifacts/openoffice_base.py`, `artifacts/win_schedtask.py`, `artifacts/win_wlan.py`, `domain/file_meta.py` (OOXML docProps), `domain/mobile_forensics.py` (UFED report.xml)

**Cell S2 `42a97b9`** (P1 ZIP bomb): `cli/commands/forensics.py` (limity archívu v `_archive_members`) + nový `tests/test_p1_zip_bounded.py` (5 testů).

**Cell S3 `b6d1655`** (P1 path traversal): `web/app.py` (validace v `_last_export_path`) + nový `tests/test_p1_path_traversal.py` (6 testů).

## 4. Nové moduly
- `src/stopa/domain/temp_images.py` (P0.3, commit Cell 2)
- `src/stopa/domain/source_manifest.py` (Cell 4, 133 řádků, čistá doménová vrstva bez I/O)
- `src/stopa/domain/xml_bounded.py` (P1 S1, 114 řádků, čistá doménová vrstva; pyexpat wiring s depth limit a zákazem uživatelských entit)

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
| `test_f11_bitlocker.py::TestBdeReadLoopP03` (+ `_FakeBdeLib`) | +2 | BDE read-loop: mid-stream selhání → BdeError + úklid; masking test (úklid nesmí potlačit původní chybu) |
| `test_fde_b2.py::test_luks_open_failure_…` | +1 | LUKS open selže → FdeError (poslední řádek stderr), passphrase mimo zprávu, keyfile uklizen |
| `tests/test_p1_xml_bounded.py` | 18 | P1 S1 bounded XML: depth bomba, billion laughs, předdefinované entity, streaming file-like, ekvivalence s ET, call-site integrace (ODF/OOXML/Win sched/WLAN/UFED) |
| `tests/test_p1_zip_bounded.py` | 5 | P1 S2 ZIP bomb import-mobile: per-member / celková velikost / počet členů; prázdný výsledek → exit 2 (E2E přes cli.main, limity monkeypatchovány) |
| `tests/test_p1_path_traversal.py` | 6 | P1 S3 path traversal: strict regex case_id, `_last_export_path` defense in depth (přes app.state.ctx), E2E endpoint 400 + negativní 404 |

Upravené: `test_f54_write_blocker.py` (piny nové sémantiky), web test fixtures (laboratorní `wb_gate_mode=warn_only` — 10 souborů), piny schématu v27→v28 (5 souborů), zlaté povrchy `p14_cli_surface.json`, `p48_cli_help_cs.json`, `p14_pipeline_surface.json`.

## 7. Výsledky testů
- P0.1: **9 passed in 16.02s** (exact)
- P0.4 combined: **39 passed in 6.87s**, Ruff `All checks passed!` (exact)
- Quick regression batch: **90 passed, 1 warning in 245.96s** (exit 0)
- Re-run všech dosud selhavajících souborů po regresních opravách: **359 passed, 1 warning in 364.67s** (exit 0) — 21 souborů / 84 původních selhání
- **Finální full suite (po obou commitech):** `5236 passed, 1 skipped in 2231.27s` — proti starému stavu `84 failed / 5153 passed` a baseline před hardeningem `5189 passed, 1 skipped`.
- Jediné selhání v full suite: `test_stp044_ci_benchmark_e2e.py::test_run_against_own_baseline_passes` — **měřicí šum pod plným zatížením**: test měří stejný kód dvakrát za sebou a druhý průběh vyšel +21,9 % (práh 20 %) na `pipeline.core`. Samostatný re-run: **6 passed in 67.57s** (exit 0). Proti komitovanému baseline (viz sekce 8) je `pipeline.core` stabilně pod gate.

### P1 security vlna
- S1 bounded XML: **18 passed in 0.06s**; regrese dotčených parserů (10 souborů): **255 passed, 1 warning in 17.62s**
- S2 ZIP bomb: **5 passed in 8.53s**
- S3 path traversal: **6 passed in 0.61s**; regrese export cache endpointů (stp067/068/069): **35 passed, 1 warning in 61.75s**
- Kombinovaný běh všech tří P1 testových souborů: **23 passed in 8.85s**; Ruff `All checks passed!`
- **Finální full suite (po celé P1 vlně):** `5269 passed, 1 skipped in 2207.25s`, **exit 0 — nula selhání** (předchozí stav: 5236 passed / 1 failed E2E flake; delta +32 testů = +3 FDE uzavírací vlna + 29 P1). `test_stp044_ci_benchmark_e2e.py` tentokrát green.

## 8. Výsledky benchmarků

Lokální běh `scripts/ci_benchmark.py --baseline benchmarks/baseline.json --threshold 0.20 --min-delta-ms 0.5` (stejný příkaz jako CI job `benchmark`):
- **Výsledek: exit 0, `ok=true`, `regressions=[]`, `noise_filtered=0`** — žádná výkonová regrese nad gate (>20 % a ≥0,5 ms).
- `pipeline.core`: lokálně **1827,3 ms** vs. CI baseline **4241,4 ms** (medián ze 3 CI měření; lokální stroj rychlejší než GHA runner) — pod gate i s velkou rezervou. Manifest blok se počítá až za finálním commitem ingestu a do hot-path parserů nezahálí.
- Aktuálně se měří **80 položek**; baseline obsahuje 79 — nová položka `core.rust` (přidána po vytvoření baseline) se proti ničemu neporovnává, bez dopadu na gate.
- Kontext: quick regression batch (90 testů kolem ingest/pipeline) = 245,96 s; full suite 2231,27 s (srovnatelné s předchozími běhy ~2217 s).

## 9. Nevyřešená rizika
P1 security vlna (§6 master promptu) je **uzavřena** — auditní pokrytí všech témat:

| Téma §6 | Stav |
|---------|------|
| Path traversal | VERIFIED + fix (S3): strict regex case_id, enum what/format, DB lookup před cache; `_last_export_path` nyní validuje sám |
| Symbolic links | VERIFIED bez změny: ingest `followlinks=False` + per-file `is_symlink()` skip |
| Race/TOCTOU | VERIFIED bez změny: atomický tmp→rename u export cache i FDE outputů |
| XML bomb | FIXED (S1): bounded parse na 5 call sitech (depth 200, zákaz uživatelských entit) |
| ZIP bomb | FIXED (S2): celková velikost + počet členů archívů import-mobile; OOXML docProps per-member limit 256 KiB |
| Deserialization | VERIFIED bez změny: pickle/yaml = 0 hitů v `src/stopa` |
| Neomezené zdroje | FIXED (S2): limity 256 MiB / 4 GiB / 20 000 členů; XML streaming 64 KiB chunky (S1) |
| seccomp | VERIFIED bez změny: P4-2 strict profil, empiricky ověřeno strace |

Zbývající reziduální rizika (uvědomělá, s odůvodněním):
1. **ADB branch `--source adb`** v import-mobile má vlastní rglob smyčku (nechází přes `_archive_members`) — bez celkových limitů. Odůvodnění: ADB export = živý dump z připojeného zařízení, ne soubor od třetí strany; limity by se aplikovaly na rozbalený výstup a měnily by chování bez jasně definovaného rozpočtu. Doporučení: sdílená budget logika v P2 vlně.
2. **`test_stp044_ci_benchmark_e2e.py`** — citlivost na zatížení (viz sekce 7); pod plným loadem full suite může dojít k flaknutí +21,9 % vs. práh 20 %.

Vyřešeno v uzavírací vlně (`fix(fde)` commit `a6ee280`):
- **LUKS cryptsetup open failure** — dedikovaný test (mockovaný `subprocess.run` → `CalledProcessError`): FdeError s posledním řádkem stderr, passphrase se nedostává do zprávy, dočasný keyfile uklizen i při selhání open.
- **BDE/FVDE `except Exception:` kolem ctypes read loopu** — VERIFIED: re-raise zachovává původní typ výjimky (BdeError/FvdeError) pro volající; ostatní broad catche jsou doloženě nekritické cleanupy (jen log). Reziduální riziko, že `release_temp` v except bloku sám zvedne a maskuje původní chybu → uzavřeno try/except + log + masking testem.
- **Třetí CLI cesta `replace(out_path)`** — VERIFIED řádek za řádkem: 3× `release_temp` po replace (forensics.py L67/L80/L96) s OSError guardem před re-raise.

## 10. Doporučené další kroky
1. Push `main` přes SSH (`id_ed25519_gh`) po souhlasu; tag zůstává `v2.4.0` na `7a9bc66`, dokud se hardening nepropíše do release vlny (P0 + P1 celky jsou lokálně hotové a otestované).
2. P2 vlna: sdílená budget logika pro ADB branch import-mobile (viz sekce 9, riziko 1), případně timeouty parserů a limit hloubky JSON u neomezených vstupů.
3. Volitelné: zvýšit práh `test_stp044_ci_benchmark_e2e.py` nebo přidat třetí měření (medián) pro odolnost proti šumu pod loadem (viz sekce 9, riziko 2).
