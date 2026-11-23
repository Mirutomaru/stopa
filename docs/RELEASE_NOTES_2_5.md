# STOPA 2.5 — Release Notes

**Stav:** `main` = `d332824` (pushnuto, GitHub CI plně green po re-runu benchmark jobu); tento release = bump + tag `v2.5.0`
**Datum validace:** 2026-11-23 · **Referenční GA:** STOPA 2.4 (`7a9bc66`, tag `v2.4.0`)

## Shrnutí

Post-release forenzní integritní hardening po logických celcích (zdroj: `FORENSIC_HARDENING_REPORT.md`),
každý celek s testy a cílenou regresí před commitem. Prioritní pořadí dle auditu:
**Forensic correctness > Data integrity > Security > Reliability > Performance > Convenience**.

Dvě vlny: **P0** (5 buněk + uzavírací FDE vlna) — determinismus reportů, správa dočasných
dešifrovaných obrazů, safe resume s ověřením identity zdrojů, fail-closed write-blocker brána se
zdrojovým manifestem a chybové cesty FDE parserů; **P1 security** (S1–S3) — bounded XML parse,
limity ZIP bomb a path traversal defense in depth.

Kompatibilita: veřejné API/formáty beze změny; CLI čistě aditivní (nový flag `--resume-mode`,
p48 CS byte-guard regenerován s diffem omezeným na nový flag); case DB schéma **v27→v28**
(přidání zdrojového manifestu, idempotentní migrace — legacy případy bez změny chování).

## Hlavní změny

### P0.5 Deterministické `generated_at` (`24d4cc7`)
Explicitní TZ v reportech místo implicitního systémového času — stejný stav = byte-identický
report (forenzní reprodukovatelnost).

### P0.2/P0.3 `EncryptedTempImage` — jednotná správa dočasných obrazů (`268df65`)
Jediný životní cyklus pro dešifrované dočasné obrazy (LUKS/BitLocker): vytvoření, použití,
garantované odstranění včetně chybových cest; read-only přístup k originálním důkazům zachován.

### P0.1 Safe resume s ověřením identity zdrojových soubolů (`5a88771`)
Při `--resume` se ověří, že registrované zdroje jsou identické (hash/velikost/mtime) — změněný
zdroj = explicitní stav (`skipped`/`modified_during_resume`), ne tiché přeparsování. Nový CLI flag
`--resume-mode` (průběžná sémantika); zlaté povrchy regenerovány, diff omezen na nový flag.

### P0.4 Write-blocker fail-closed brána + zdrojový manifest (`97863de`)
Fail-closed ověření write-protection (mód/profile) před zápisem do důkazového prostoru; nová tabulka
zdrojového manifestu v case DB (**schéma v28**, 28 sloupců, čistě aditivní a idempotentní).

### FDE chybové cesty — uzavírací vlna (`a6ee280`)
BDE/FVDE read-loop error cesty (fake lib `_obj` int handle) + LUKS open-failure pokrytí;
validace 89 passed / 1 skipped.

### P1 S1 Bounded XML parse důkazových souborů (`f20d56f`)
Nový modul `domain/xml_bounded.py`: ruční pyexpat wiring (C `_elementtree` maskuje interní expat),
**depth limit default 200** (konfigurovatelný), zákaz uživatelských entit (billion laughs fail-closed),
streaming 64 KiB. Call sites: ODF `content.xml`, OOXML docProps, Windows Scheduled Task, WLAN profile,
UFED `report.xml`. Testy 18p + regrese dotčených parserů 255p.

### P1 S2 Limity ZIP bomb pro import-mobile archívy (`42a97b9`)
`_archive_members`: per-member **256 MiB** (existující) + celkové limity **4 GiB / 20 000 členů**
(module globály, monkeypatchovatelné testy); OOXML docProps s per-member limitem. Testy 5p.

### P1 S3 Path traversal validace v `_last_export_path` (`b6d1655`)
Audit potvrdil silnou existující politiku (strict regex case_id `^[A-Za-z0-9_-]+$`, enum what/format,
DB lookup před cache, atomický tmp→rename); helper si nyní ověřuje `case_id` sám — budoucí endpointy
nejen implicitně obnoví traversal. Testy 6p + regrese export endpointů (stp067/068/069) 35p.

## Validace

- Full regression: **`5269 passed / 1 skipped`, exit 0** (36:47; +32 testů vs báze po 2.4 =
  +3 FDE uzavírací vlna + 29 P1 testů).
- Benchmark vs baseline: **ok=true, regressions=[], noise_filtered=0**, `pipeline.core` = 1634 ms
  (CI baseline 4241 ms); gate >20 % a ≥0.5 ms beze změny.
- Ruff clean repo-wide; rozpočet `db.py` **599/600**.
- GitHub CI na `d332824`: **8/8 jobů green** (pytest + JS DOM, test-full, Rust wheel parity, Lint,
  macOS smoke, Windows portability, pip-audit, Benchmark) — jediné selhání prvních běhů = šum
  shared runneru u `parser.email_mbox` (+54.5 %, absolutně 0.86 ms; soubor `email_mbox.py` v diffu
  není) → re-run jobu zelený.
- Závěrečný report: `FORENSIC_HARDENING_REPORT.md` (P0 = `a661cae`, P1 + finální výsledky = `d332824`).

## Známé limity / reziduální rizika

- **ADB branch** v import-mobile (`--source adb`) má vlastní rglob smyčku mimo `_archive_members`
  → bez celkových limitů archivu (odůvodněno: ADB export = soubory na disku zpracovávané
  jednotlivě; sdílená budget logika plánována do P2 vlny).
- Benchmark E2E (`test_stp044`) je citlivý na zatížení runneru — baseline z mediánu 3 CI měření
  to míří; volitelné posílení (třetí měření) v P2.
- Bounded XML: dokumenty s uživatelskými entity deklaracemi selhávají fail-closed (hloubka default
  200, konfigurovatelná).

> **Post-release update (2026-11-24):** položky 1–2 uzavřeny v P2+P3 hardening vlně nad tagem
> `v2.5.0` (commity `874c044`, `6f4f8f1`, `51b0018`, `b509e7c`): ADB branch pod sdílenou
> ArchiveBudget, benchmark medián `--runs N`, bounded JSON depth limit 200 u nedůvěryhodných
> vstupů a installer subprocess timeouty. Detail: `STOPA_CHANGELOG.md` +
> `FORENSIC_HARDENING_REPORT.md`.
