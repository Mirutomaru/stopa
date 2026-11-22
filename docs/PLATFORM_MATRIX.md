# STOPA — Platform matrix (P4-9)

Podpora a pokrytí testování per platforma. Single source of truth: `.github/workflows/ci.yml`;
tento dokument popisuje, **co se kde testuje** a které cesty jsou platformově omezené.

## Matice

| Platforma | CI runner | Python | Pokrytí | Rust wheel (carving) | Poznámka |
|---|---|---|---|---|---|
| Linux x86_64 (Ubuntu) | `ubuntu-latest` | 3.9–3.12 (matrix) | **full suite** (`test`) + všechny extras (`test-full`) + benchmark baseline | ✅ **distribuce od P4-10**: manylinux_2_28 wheels x86_64/aarch64 (release job `rust-wheels`, aarch64 cross `maturin --zig`); CI parity gate `rust-parity`; min profil `test` bez wheelu = referenční cesta | kanonická platforma; sem patří full regrese + benchmark |
| Windows | `windows-latest` | 3.12 | **portability core** (domain+data subset, viz níže) | ❌ — carving běží na referenční čisté-Python cestě | P4-9 smoke: instalovatelnost + portabilita domény/datové vrstvy |
| macOS | `macos-latest` (arm64) | 3.12 | **portability core** (stejný subset) | ❌ — referenční cesta | P4-9 smoke; x86_64 macOS v CI netestován (viz gaps) |

## Portability core (Windows + macOS)

Kurátorovaný explicitní seznam souborů v `ci.yml` (jobs `windows`, `macos`) —
deterministický, verzí pod kontrolou; globby by se posouvaly s růstem suite.

- **domain** (11 souborů): `test_p21_work_queue_domain.py`, `test_p22_case_registry_domain.py`,
  `test_p25_threat_intel_domain.py`, `test_p26_cross_case_domain.py`,
  `test_p27_exchange_bundle_domain.py`, `test_p27_exchange_domain.py`,
  `test_p31_search_adv_domain.py`, `test_p32_artifact_compare_domain.py`,
  `test_p33_classification_domain.py`, `test_p34_evidence_storage_domain.py`,
  `test_p35_yara_sigma_domain.py`
- **data** (4 soubory): `test_p02_seal_keys.py`, `test_p03_sandbox_hardening.py`,
  `test_f64_plugins.py`, `test_p42_sandbox_strict.py`
- **long-running**: `test_p49_leak_canary.py` (leak canary — viz níže)

Pravidlo pro rozšiřování: nový test doménové/datové vrstvy, který nemá platformově
specifické závislosti (signály, binárky, chmod/symlink semantika), se přidá do seznamu v
`ci.yml` **a** do tohoto dokumentu.

## Platformově omezené cesty (graceful degradation)

| Cesta | Kde funguje | Jinak | Mechanismus |
|---|---|---|---|
| Rust carving wheel (`stopa_core`) | Ubuntu CI build; libovolná platforma s nainstalovaným wheelu | referenční čisté-Python carving (stejné výstupy) | lazy import + `is_available()` fallback v `data/rust_core.py` |
| Strict plugin sandbox (seccomp-bpf) | Linux x86_64/aarch64 s podporou seccomp | fail-closed (`ValueError`) — plugin běží default profilem | `_build_seccomp_strict_filter()` per-arch tabulky; testy gate `STRICT_LIVE` (posix+linux) |
| User namespace mount izolace | Linux + `unshare --user --map-root-user --mount` dostupné | seccomp-only strict (graceful degradace) | `_unshare_userns_available()` probe |
| `preexec_fn` rlimity pluginů | POSIX (`os.name == "posix"`) | bez limitů (subprocess běží, limity = wall-clock timeout + output strop) | guard v `data/plugin_loader.py` |
| EWF/FDE system knihovny (libewf) | ruční instalace (Linux: `/tmp/ewflibs/ext/usr/lib/x86_64-linux-gnu`, `~/.ewf-install/lib`, env `STOPA_EWF_LIB`) | EWF kontejnery = „parser nedostupný“ (graceful) | `data/ewf_container.py` `_find_lib_dir()` |
| Multiprocessing pool | všechny platformy | — | spawn context (`pipeline/core.py`) — žádné fork semantiky |

## Leak canary (long-running stabilita)

`tests/test_p49_leak_canary.py` — deterministický ingest loop: fixní korpus (~5 MB,
~23k text/CSV záznamů, obsah odvozen z indexů — bez RNG/sítě), 1 warmup + 16 měřených
iterací do jednoho případu (`max_workers=1` → in-process, vše vidí tracemalloc).

- **Prah**: růst Python paměti < **100 MiB** po celém loopu (design AK P4-9).
- **Citlivost**: chytne leak ≥ ~6 MiB/iteraci (per-file) nebo ≥ ~300 B/záznam
  (per-record); menší úniky vyžadují vyšší N — při podezření na leak spustit s větším
  `ITERATIONS` lokálně.
- **Pokrytí**: běží na všech třech platformách — ubuntu plnou discoverií (`test` job)
  a explicitně v jobs `windows`/`macos`.
- Měření: `tracemalloc` + `gc.collect()` na hranicích iterací; při selhání křivka
  per-iterace + top-5 kategorií růstu (snapshot diff) pro debug.

## Rust core distribuce (P4-10)

`stopa_core` (Rust, PyO3 0.26 + **abi3-py310**) se dříve distribuoval jen jako zdroj (`rust/`) —
uživatel bez maturinu dostával čisté-Python fallback. Od P4-10:

| Platforma | Wheel (release asset) | Instalace |
|---|---|---|
| Linux x86_64 (glibc ≥ 2.28) | `stopa_core-0.1.0-cp310-abi3-manylinux_2_28_x86_64.whl` (od release **v2.4.0**) | `pip install stopa[carving]` |
| Linux aarch64 (glibc ≥ 2.28) | `stopa_core-0.1.0-cp310-abi3-manylinux_2_28_aarch64.whl` (od release **v2.4.0**) | `pip install stopa[carving]` |
| Windows / macOS / jiná arch | ❌ (úmyslně — referenční cesta) | `pip install stopa` (fallback) nebo build ze zdroje |

- **abi3-py310**: jeden wheel per platforma pokrývá všechny Python ≥ 3.10 (`requires-python`) —
  žádné cross-verze `.so` v offline instalačních wheels; aarch64 wheel je cross-sdílený s ARM Macy
  jen přes `pip` s kompatibilním markerem (úmyslně neaktivní, viz matice).
- **Build pipeline** (`release.yml` job `rust-wheels`, matrix x86_64/aarch64): x86_64 nativně v
  `quay.io/pypa/manylinux_2_28_x86_64` (maturin + auto auditwheel repair na tag manylinux_2_28);
  aarch64 cross-compilace **bez ARM runneru/QEMU** (`maturin --zig` — zig dodává target libc).
  Verify step porovnává přesný tag `cp310-abi3-manylinux_2_28_<arch>.whl` → chrání proti tiché
  degradaci na `linux_*`. Native build mimo manylinux kontejner **neplatí** pro distribuci (novější
  glibc symboly; lokálně jen pro parity E2E).
- **Parity gate per push** (`ci.yml` job `rust-parity`): wheel se builduje v manylinux_2_28 kontejneru,
  nainstaluje do izolovaného venv a F2.1 parity testy ověří bitovou shodu Rust core vs Python referenční
  cesty (hashing + carving) na fixním korpusu — bez gate by se Rust regrese projevila až v release buildu.
- **Fallback beze změny**: `data/rust_core.py` lazy import + `is_available()` → bez wheelu carving běží
  referenční čistou-Python cestou (bitově stejné výstupy, viz matice).
- **Developři**: lokální cesta beze změny — `cd rust && maturin develop` / `maturin build`.

## Known gaps (stav P4-9, 2026-11)

1. **Full suite jen na Linuxu** — Windows/macOS běží portability core; platformní
   quirk ve web/CLI/pipeline vrstvě se projeví až explicitním rozšířením subset
   (design P4-9: „platform quirks may surface → opravit jako samostatné commity“).
2. **Zrychlený carving se v CI netestuje na Win/mac** — wheels jsou úmyslně jen Linux manylinux_2_28 (x86_64/aarch64, P4-10); Win/mac běží na referenční cestě (bitově shodná, viz matice).
3. **macOS x86_64 netestován** — `macos-latest` je od 2025 arm64; Intel macOS běží
   na referenční cestě bez CI signálu (niské riziko: čisté Python + stdlib sqlite).
4. **Windows file-locking / path quirk** pokryt jen portability core — SQLite na
   Windows drží zámek otevřených DB agresivněji; testy subsetu DB správně zavírají,
   ale web/CLI dlouhé běhy s konkrétním Windows runnerem se netestují.
5. **Benchmark baseline jen Linux x86_64** — jiné platformy nemají porovnatelný
   referenční bod (úmyslně; benchmark = regresní ochrana kanonické platformy).

## Historie

- **P4-9 (2026-11)**: přidány CI jobs `windows` + `macos` (portability core), leak
  canary `test_p49_leak_canary.py`, tento dokument. Před P4-9 běžela celá suite
  pouze na `ubuntu-latest`.
- **P4-10 (2026-11)**: Rust core distribuce — abi3-py310 manylinux_2_28 wheels x86_64/aarch64 (release job `rust-wheels`, aarch64 cross `maturin --zig`), extra `carving` s pinned release asset URL, CI parity gate `rust-parity`, nová sekce „Rust core distribuce“ v tomto dokumentu.
