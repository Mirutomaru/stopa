# STOPA — P4 návrhy (před implementací)

Podle pravidla v `ROADMAP_2_1.md`: **každá položka dostane návrh + prioritu + AK před
implementací; neimplementovat všechny automaticky.** Vytvořeno 2026-11-20 po release
**v2.3.0** (`7ca55f5`, P3 roadmap hotová 6/6, suite **5013p/1s**). Aktuální schéma case DB
**v26** + instance DB DDL (case_registry / cross_case) — návrhy používají pouze aditivní
migrace (**v27+**) tam, kde jsou potřeba; Clean Architecture (čistá domain / data I/O /
presentation), offline deterministické testy a zachování stávajícího veřejného API, CLI
povrchu i datových formátů.

**Zdroj požadavků:** `STOPA_ANALYZE.md` (nezávislá analýza release 2.0 GA) — §8 známý
technický dluh (10 položek) + §7 design otázky; stav ověřen v HEAD `7ca55f5`: plně vyřešeno
**2/10** (§8.1 god-files → P1-4, §8.6 db.py budget záměrně ponechán), částečné **5/10**,
otevřené **3/10**.

## Doporučené pořadí

| # | Položka | Priorita | Velikost | Proč na tomto místě |
|---|---------|----------|----------|---------------------|
| 1 | P4-1 CI matrix pro volitelné extras | **P0** | S | infrastrukturní jistota před dalším vývojem — pokrývá „bez X“ i „s X“ cesty; levná výhra |
| 2 | P4-3 Plugin API semvering + breaking change log | **P0** | S | stabilní kontrakt před sandbox prací (P4-2) a veřejnými pluginy |
| 3 | P4-2 Plugin sandbox hardening | **P0** | M | bezpečnost proti zlosťnému pluginu; dotýká se kódu, který právě P4-3 upravuje |
| 4 | P4-6 Sealing v2 — time hash chain + external witness | **P1** | S–M | soudní způsobilost (analýza §7.7); samostatná položka bez nových závislostí |
| 5 | P4-5 AI production robustness | **P1** | M | streaming/retry/token budget nad hotým P1-2 orchestrátorem + eval gate |
| 6 | P4-4 Frontend sjednocení — SPA kanonická | **P1** | L | největší strategická položka; až po CI jistotě (P4-1), aby migraci chránila regression |
| 7 | P4-9 Cross-platform a long-running stabilita | **P2** | M | Windows/macOS + leak canary před širší distribucí (P4-10) |
| 8 | P4-8 i18n CLI (+ legacy UI katalog) | **P2** | M | až po frontend rozhodnutí — pokud padne legacy v P5, neinvestovat tam zbytečně |
| 9 | P4-7 Multi-node readiness (DB event bus + registry lease) | **P2** | L | minimální cesta k multi-instance; potřebuje stabilní základ a hotou centrální registry (P2-2) |
| 10 | P4-10 Rust distribuce — manylinux wheels | **P2** | M | těsně před public release pushem; závisí na platformové práci (P4-9)

---

### P4-1 — CI matrix pro volitelné extras (priorita 1, P0)

**Cíl:** každá kódová cesta za volitelným extra se prověří v CI — i „bez X“ (graceful
degradation), i „s X“ (nainstalovaná funkčnost).
**Základ:** `.github/workflows/ci.yml` dnes instaluje jen `.[dev,web]`; 9 extras
(`pdf,fde,tsk,stix,xlsx,meta,net,analytics`) + yara-python v CI nepokryty; testy mají
importorskip/skipif → „s X“ cesty (např. Ed25519 manifest s `cryptography`) běží jen lokálně.

**Návrh:**
- Tři dependency profily v CI: `min` = stávající `.[dev,web]` (degradation baseline),
  `full` = všechny extras + yara-python (funkční cesty) a dokumentovaná matice skipů per
  profil (komentář v ci.yml).
- Žádné změny v src; jen workflow + případná oprava testů, která předpokládala extra
  (fail-closed: takový test = bug).
- `docs/EXTRAS_COVERAGE.md` — tabulka: extra → kódové cesty → který profil je pokrývá.

**AK:**
- Všechny profily exit 0 na main; sada skipnutých testů per profil stabilní a dokumentovaná.
- P3-4 manifest cesta „s cryptography“ projde v `full` bez skipu.
- Žádné chování src/ se nemění (diff = CI + docs).

**Velikost/riziko:** S / nízké — YAML práce; riziko flaky full instalace (pin verzí).

---

### P4-3 — Plugin API semvering + breaking change log (priorita 2, P0)

**Cíl:** stabilní dokumentovaný plugin kontrakt s explicitním versioningem a klasifikací
změn.
**Základ:** `docs/PLUGINS_API.md` — manifest má `min_stopa_version`; chybí `api_version`,
seznam breaking/non-breaking změn; F6.4 je nové (analýza §8.9).

**Návrh:**
- Manifest: volitelné pole `api_version: "1"` (default 1 = aktuální kontrakt); validátor
  akceptuje a varuje při neshodě se supported range [1, 1].
- PLUGINS_API.md: sekce „Stabilita kontraktu“ — tabulka stabilních vs. experimentálních
  povrchů (`detect_fn/extract_fn/parser_version`, triage factory, ToolSpec factory) +
  pravidla klasifikace (co je breaking / non-breaking).
- CHANGELOG pravidlo: změny plugin kontraktu nesou marker `!plugins:` v subjectu commitu;
  dedikovaná podsekce je akumuluje.

**AK:** testy manifest validace pro api_version matici (chybějící/1/budoucí →
accept/warn/reject); publikované docs se seznamem stabilních povrchů; žádné chování
stávajících pluginů se nemění (api_version volitelné).

**Velikost/riziko:** S / nízké — dokumentace kontraktu + 1 validátor pole.

---

### P4-2 — Plugin sandbox hardening (priorita 3, P0)

**Cíl:** dostatečná izolace neověřeného (potenciálně zlosťného) pluginu na Linux desktopu
bez root práv.
**Základ:** aktuální stav = subprocess + `RLIMIT_AS` + timeout + JSON envelope (P0-3);
analýza §7.4 ptá se na seccomp/namespaces.

**Návrh:**
- Profil **default** (backward compatible): stávající RLIMIT_AS/timeout + nové rlimits —
  `RLIMIT_NPROC`, `RLIMIT_NOFILE`, `RLIMIT_CPU`, `RLIMIT_FSIZE` (fork bomb / fd únik /
  CPU hog / obrovský soubor).
- Profil **strict** (`stopa plugin run --sandbox=strict`): navíc seccomp-bpf allowlist
  přes ctypes (bez nové závislosti) — minimální syscall sada pro čistě Python pluginy;
  volitelný user namespace wrapper pokud `unshare` dostupný.
- Zbytkové riziko dokumentováno v SECURITY_THREAT_MODEL.md (side channels SME/TSX mimo
  scope).

**AK:** adversariální testy: fork bomb, fd únik, CPU hog, zápis souboru ven z working diru,
blokováný syscall → vše zachyceno ve strict profilu; default profil byte-kompatibilní se
stávajícím chováním pro slušné pluginy.

**Velikost/riziko:** M / střední — seccomp allowlist je audit per Python verze (ctypes +
kernel rozhraní); mitigace = profily (default zůstává konzervativně původní).

---

### P4-6 — Sealing v2: time hash chain + external witness (priorita 4, P1)

**Cíl:** tamper-evidentní historie pečetí napříč více pečatením + volitelný out-of-band
důkaz (analýza §7.7).
**Základ:** F5.1 = Merkle tree s fixed table ordering + Ed25519 signatura — point-in-time;
žádné propojení mezi po sobě jdoucimi pečetěmi, žádný external witness.

**Návrh:**
- Domain `domain/seal_chain.py`: řetězový záznam `H(prev_root || case_id || ts_iso ||
  merkle_root)` (SHA-256); genesis = první seal root; verifikace = recompute celého řetězu
  + validace každé Ed25519 signatury. Čistá logika, žádné I/O.
- Data: aditivní v27 tabulka `seal_chain` (case_id FK CASCADE, seq UNIQUE) — rozhodnutí
  W2 (tabulka pro dotazovatelnost vs. meta klíč); CLI `stopa seal --chain` + Web GET
  `/api/cases/{id}/seals/chain`.
- External witness (volitelný): `stopa seal witness <soubor|url>` — POST merkle_root na URL
  (nebo čtení lokálního souboru), response uložen jako důkaz u řetězového záznamu; offline =
  manuální import witness souboru.

**AK:** re-seal bez změny → nový řetězový záznam, staré ověřitelné; manipulace s jakýmkoli
minulým rootem → selhání verifikace (fail-closed ValueError); witness round-trip test na
lokálním HTTP fixture; full suite green.

**Velikost/riziko:** S–M / nízké — čistá domain + aditivní DDL; jediné riziko = migrace v27
(testy obnovení per konvencí).

---

### P4-5 — AI production robustness (priorita 5, P1)

**Cíl:** vlastní ToolSpec agent (P1-2 orchestrátor) na produkční úroveň: streaming, retry,
token budget, eval gate.
**Základ:** analýza §8.7 — chybí streaming tokenů, jednoduché retry politiky; eval sada z
P1-2 existuje, ale není CI gate.

**Návrh:**
- Streaming: async generator `run_stream()` se stejným finálním výsledkem jako
  non-streaming (backward compatible); Web SSE endpoint `/api/cases/{id}/ai/run/stream`.
- Retry/backoff: exponenciální + deterministický jitter (seeded), konfigurovatelné
  max_attempts; klasifikace chyb LLM volání (transient vs. permanent).
- Token budget: hard limit per run → explicitní status `budget_exceeded` s truncation
  markerem, ne crash.
- Eval gate: CLI `stopa ai-eval [--suite gold]` nad stávající zlaté scenáře P1-2; volitelný
  CI job na PR dotýkající se `intelligence/`.

**AK:** streaming a non-streaming produkují identický finální výsledek (mock LLM); retry
respektuje max_attempts a je deterministický při fixním seedu; budget exceeded → status ne
exception; eval gate selže na regression zlatého scénáře.

**Velikost/riziko:** M / střední — dotýká se AI jádra; mitigace = stávající offline mocky +
74-testová báze P1-2.

---

### P4-4 — Frontend sjednocení: SPA kanonická (priorita 6, P1)

**Cíl:** jeden kanonický frontend pro 2.x+ = React SPA; controlled retirement legacy UI
(analýza §8.2).
**Základ:** oba fronty koexistují (`frontend/` → `web/static/spa/` + legacy
`web/static/app.js`, `js/components/`); P0-6 parity mapa S1–S10 existuje, ale nedotažena;
část funkcí jen v legacy (ATT&CK heat-mapa, Daubert tlačítka).

**Návrh:**
- W1 — gap audit: feature matice legacy vs SPA (auto-generovaná z rout + DOM markerů),
  výstup `docs/FRONTEND_PARITY_STATUS.md`.
- W2 — implementace chybějících view v SPA (ATT&CK heat-mapa, Daubert tlačítka, zbývající
  gap) s vitest per view.
- W3 — legacy za flag: default = SPA; `?ui=legacy` drží starý UI + console warning
  „non-canonical“; docs + release notes. Finální odstranění legacy = P5 (po releasovém
  cyklu).

**AK:** parity test pro každý migrovaný view (vitest + Web surface golden beze změny);
legacy byte-identické až do W3; SPA default dosažitelné z root URL bez flagu.

**Velikost/riziko:** L / střední — největší položka P4; riziko UI regression mitigováno
vitest per vlna + nedotčený legacy fallback.

---

### P4-9 — Cross-platform a long-running stabilita (priorita 7, P2)

**Cíl:** doplnit slepé skvrny z analýzy §8.8 — Windows/macOS + memory leaky v dlouhých
spuštěních.
**Základ:** vývoj primárně Linux; Rust wheel = lokální maturin build (fallback cesty
netestované jinde); žádný leak canary.

**Návrh:**
- CI job `windows` — pytest subset (domain + data, bez Rust wheelu → referenční cesta);
  macOS smoke job (install + core suite).
- Leak canary: deterministický ingest loop N iterací s tracemalloc prahem (růst < 100 MiB
  na fixním input korpusu) — `tests/test_p49_leak_canary.py`.
- `docs/PLATFORM_MATRIX.md` — podporované platformy, testované cesty, známé mezery.

**AK:** Windows job green na Rust-fallback cestě; leak canary deterministický a passing na
HEAD; matice doc sedí s CI realitou.

**Velikost/riziko:** M / střední — platformové quirk (pathy, line endings) se mohou
projevit v stávajících testech → opravy jako samostatné commity s AK per platforma.

---

### P4-8 — i18n CLI (+ legacy UI katalog) (priorita 8, P2)

**Cíl:** ukončit hardcodované češtinu v CLI a legacy UI (analýza §8.10); SPA má i18n už.
**Základ:** všechny CLI výstupy hardcodované cs; legacy static JS stejně; žádná katalogová
infrastruktura.

**Návrh:**
- Lehký katalog: `src/stopa/i18n/{cs,en}.json` + helper `t(key, **params)` (bez nové
  závislosti); env `STOPA_LANG` / flag `--lang`, default **cs** = byte-kompatibilní výstup.
- CLI: extrakce top-level help + všechny epilogy/zprávy do katalogu; golden test pro cs a en
  (`--help` povrch).
- Legacy UI: JSON katalog přes `/api/i18n/{lang}` (aditivní Web route); SPA si drží vlastní
  i18n (bez změny).

**AK:** default `stopa --help` byte-identické s aktuálním stavem (cs golden); en pokrývá
100 % top-level help + epilogů; žádné chování se nemění.

**Velikost/riziko:** M / nízké–střední — mechanická, ale velká plocha (stovky řetězců);
vlny per command rodina, každá s golden testem.

---

### P4-7 — Multi-node readiness: DB event bus + registry lease (priorita 9, P2)

**Cíl:** minimální cesta k multi-instance nasazení bez Redis (analýza §8.3).
**Základ:** LiveEventBus = in-process; LRU cache in-memory; case_registry centrální od
P2-2, ale bez node liveness/lease.

**Návrh:**
- DB event bus: aditivní tabulka `events` v instance DB + polling worker (long-poll /
  notify); cross-process distribuce LiveEvent událostí; per-case WS zůstává lokální.
- Registry lease: sloupce `last_heartbeat`, `node_id` na case_registry + expirace lease →
  deterministický liveness pohled (bez clock driftu: monotónní seq).
- Deployment topology doc: single-node vs multi-node, které funkce co vyžadují.

**AK:** dva procesy nad jednou instance DB dodají události oběma subscriberům
deterministicky; lease expirace test s fake clockem; žádná nová hard závislost (základ =
jen SQLite).

**Velikost/riziko:** L / střední–vysoké — konkurence v SQLite (WAL audit) + polling latence;
mitigace = postup (nejdřív bus, pak lease).

---

### P4-10 — Rust distribuce: manylinux wheels (priorita 10, P2)

**Cíl:** vyřešit build komplexitu PyO3 pro uživatele (analýza §8.5) — instalovatelné wheel
místo lokálního maturin buildu.
**Základ:** `rust/` + maturin → lokální wheel `stopa_core`; Python facade s fallbackem
existuje (`data/rust_core.py`).

**Návrh:**
- GHA matrix: manylinux_2_28 x86_64/aarch64 (+ volitelně musl) přes maturin; upload jako
  release assets (release.yml).
- Nové extra `carving` = pinnutý wheel per platforma (`pip install stopa[carving]`); source
  instalace bez wheelu = dokumentovaný fallback.
- Wheel parity test v CI kontejneru: Rust vs Python referenční cesta na fixním korpusu
  (re-use F2.1 parity testů).

**AK:** wheels green v CI + parity passing; lokální maturin cesta pro developery nedotčená;
distribuční docs aktualizováno (RELEASE_NOTES).

**Velikost/riziko:** M / střední — údržba manylinux obrazců; mitigace = stávající Rust test
sada + parity gate.

---

*Všechny položky = samostatné releasovatelné jednotky; implementace až po explicitním
schválení každé položky nebo celého P4 setu.*
