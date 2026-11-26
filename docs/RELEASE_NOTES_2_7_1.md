# STOPA 2.7.1 — Release Notes (post-release maintenance vlny F + F6)

**Stav:** main = `8295426` (docs vlna 24, pushnuto); tento release = bump + tag `v2.7.1` na vrchol main; reference GA = STOPA 2.7 (`1307a23`, tag `v2.7.0`)
**Datum validace:** 2026-11-26

## Shrnutí

Post-release maintenance vlny nad tagem `v2.7.0`: **F-4 + F1/F2 (docs) + F3 (re-pin wheels) + F5 (post-push audit) + F6 (docs hygiene)** — žádné nové funkce, žádný nový CLI příkaz/flag, žádná DB migrace, žádné změny veřejného Python API. Cíl = readiness pro další release + uzavření reziduálních nálezů z review v2.6.

**Semver PATCH (2.7.1)** — zdůvodnění:
- **F3 re-pin stopa_core wheels v2.6.0 → v2.7.0** (`pyproject.toml [carving]`, `requirements.lock`, `.github/wheel_pins.json`) — forenzní srovnání wheelů prokázalo **byte-identický `.so` payload** na x86_64 i aarch64 (core 0.1.0; rozdíly jen build-time metadata SBOM/RECORD) → behaviorálně neutrální, ale mění reprodukovatelnou instalační cestu ⇒ patch release, ne jen commit.
- F-4 = explicitní log konfigurace CI gate `scripts/ci_benchmark.py` (není součástí app runtime chování) + 2 testy.
- F1/F2 = snapshot údržba ROADMAP/PROJECT_STATE/TEST_REGISTRY/FEATURE_REGISTRY (verze 2.7.0, řádek STP-070, sekce release 2.7).
- F5/F6 = audit + changelog `[Unreleased]` sekce + docs archive/banner/mirror sync + 2 nové offline testy.

Veřejné Python API i výstupní schémata (`stopa_output_schema=1`) **beze změny**; case DB zůstává na v29; BC formáty exportů beze změny.

## Hlavní změny

### F-4 [reliabilita] — Explicitní log konfigurace CI benchmark gate (commit `ee2a817`)
- Current-only položky benchmark baseline (`core.rust` při aktivním Rust core) procházely porovnáním bez stopu: domain API warning hlásilo, ale chování nebylo nikde pinováno; CI gate spoléhal na Python lastResort handler.
- Oprava: explicitní `logging.basicConfig(level=WARNING)` v `main()` + 2 deterministické caplog testy (current-only → warning bez regresí; baseline-only → bez regresí).

### F1/F2 [docs] — Post-release údržba registry a stavových dokumentů (commity `12ff23f`, `66a9931`)
- Verze 2.6.0 → **2.7.0** v hlavičkách `STOPA_ROADMAP.md` + `.stopa-dev/PROJECT_STATE.md` + `.stopa-dev/TEST_REGISTRY.md`; fáze log PROJECT_STATE entry „RELEASE 2.7 VYDANÝ“.
- FEATURE_REGISTRY: re-stamp 21 app-verzových řádků na 2.7.0; chybějící řádek **F-096 = STP-070** (periodický plánovač auto-bundle, commit `e37b328`); nová sekce „Release 2.7 — post-release backlog“ F-097..F-109; opraveno 8 zastaralých Omezení s cross-reference.

### F3 [build] — Re-pin stopa_core wheels na release v2.7.0 (commit `ed54536`)
- URL + komentář v `pyproject.toml`; `requirements.lock` regenerováno uv 0.11.13 (minimální diff = 4 řádky stopa-core); `.github/wheel_pins.json` přes oficiální `--update-manifest` (nové SHA: x86_64=`6295b709…`/360752 B, aarch64=`4c0f4522…`/307993 B); komentář v `ci.yml`.
- Ověřeno: `verify_rust_wheel.py --platforms x86_64 aarch64` PASS; wheel nainstalován z pinned URL, `--installed` PASS + `rust_core.is_available()=True`; lock determinismus OK.

### F5 [audit] — Post-push údržbový audit (commit `15db1c5`)
- 0 reálných TODO/FIXME/HACK v src/+scripts/; B9 open item uzavřen na řádkové úrovni (jediný programový konzument `ChainReport` = `repro.py::cmd_integrity`); hygiena repa OK (0 committed .pyc, web/ bez hardcoded verzí); stale `v2.6*` referencí v live doku historicky správné.
- Changelog: nová `[Unreleased]` sekce dokumentující post-release vlny F pro release notes tohoto vydání.

### F6 [hygiena] — Docs sprawl cleanup + changelog mirror resync (commit `8295426`)
- 8 stale dokumentů → `docs/archive/` (nulové živé reference; pravidlo: živý reference = banner, jinak archiv) — TESTING_STRATEGY, FORENSIC_VALIDATION, SECURITY_HARDENING, SECURITY_AND_EVIDENCE_INTEGRITY, SYSTEM_BLUEPRINT.md+.html, ARCHITECTURE_PROPOSAL, STOPA_VALIDATION_STRATEGY.
- 4 superseded bannery na retenovaných doku (3× ETAPA C návrhová dokumentace referencovaná README + SECURITY_THREAT_MODEL snapshot c314435 → ukazatel na `FORENSIC_HARDENING_REPORT.md`).
- **Changelog mirror resync:** `docs/STOPA_CHANGELOG.md` se od 2026-11-17 desynkronizoval (chyběly všechny sekce releases 2.1→2.7, 40 vs 52 sekcí) → resync z kořene + nový guard `tests/test_docs_changelog_mirror_sync.py` (mirror ≡ root modulo poznámka).
- DIFFERENTIAL_TESTING zaregistrován v PLAN_BACKLOG jako PENDING (reference_dataset nastaveno u 0/78 parserů; návrh ke schválení).

## Validace

- **Fresh full suite (po F-4/F2, HEAD `66a9931`):** **5486 passed, 2 skipped**, EXIT=0 — deterministická a offline; Rust core = aktivní wheel.
- **GitHub CI na pushi vlny F (`10e1fc7`) i F5 (`15db1c5`): 11/11 success** (včetně `Lockfile + Rust wheel pin (SHA-256)` a `Aktivní Rust wheel ([carving] + full suite)` — produkční cesta s aktivním core z v2.7.0 wheels).
- **F6 gates:** mirror guard testy **2 passed**; ruff clean (`src tests scripts`); plná markdown-link kontrola (docs/**+kořen) = **0 broken links** po archive movech.
- Tento release: version-sensitive testy + ruff clean; editable install regenerován po bumpu.

## Známé limity / reziduální rizika

1. **macOS arm64 capacity flake** — připravený fallback: pin `runs-on: macos-15-intel` + aktualizace PLATFORM_MATRIX.md (neaplikován, jen při opakování; CI na 2.7 vlnách zatím bez výpadku).
2. **Lokální kontejnerová inspekce**: `docker` chybí, `podman` blokovaný na `libsubid.so.5` (instalace nesouhlasena) — dotýká se jen lokálního dev ověření Docker image jobu.
3. **DIFFERENTIAL_TESTING PENDING** — schválení referenčních nástrojů + build reference datasetů (0/78 parserů); návrh `docs/DIFFERENTIAL_TESTING.md` platný, závislost P0-4 hotová.
