# STOPA 2.6 — Release Notes

**Stav:** `main` = `39da653` (pushnuto, GitHub CI plně green); tento release = bump + tag `v2.6.0`
**Datum validace:** 2026-11-24 · **Referenční GA:** STOPA 2.5 (`881a121`, tag `v2.5.0`)

## Shrnutí

Post-release hardening vlny P2+P3 nad tagem `v2.5.0` (zdroj: `FORENSIC_HARDENING_REPORT.md`
§9/§10), každá buňka s testy a cílenou regresí před commitem. Prioritní pořadí dle auditu:
**Forensic correctness > Data integrity > Security > Reliability > Performance > Convenience**.

Čtyři hardening commity (`874c044`, `6f4f8f1`, `51b0018`, `b509e7c`) + dokumentační commit;
po vlně **žádné z auditních reziduálních rizik neotevřené** (P0–P3 uzavřeny).

Kompatibilita: veřejné API čistě aditivní (nové doménové moduly `domain/archive_budget`,
`domain/json_bounded`; nová výjimka `JsonLimitError(ValueError)`); CLI beze změny (p48 CS
byte-guard bez diffu), case DB schéma beze změny (v28). Behavior fix: ADB branch import-mobile
je poprvé pod limity archivu; installer se už neschytí na mrtvé síti/repo.

## Hlavní změny

### P2 A Sdílená ArchiveBudget logika (`874c044`)
Nový čistý doménový modul `domain/archive_budget.py` (`ArchiveBudget`, limity přes konstruktor;
produkční defaults = P1 globály `_MAX_ARCHIVE_*` v době volání → monkeypatch kontrakt zachován).
ZIP/složková i **ADB branch** import-mobile pod společnými limity archivu (per-member 256 MiB /
celkem 4 GiB / 20 000 členů); ADB per-member limit jen `.vcf`, DB streamované po cestě; ZIP
sémantika a P1 warning zprávy byte-identické. Testy 10p + regrese p1_zip + f15 import-mobile 27p.

### P2 B Benchmark medián proti šumu (`6f4f8f1`)
`scripts/ci_benchmark.py --runs N` (default 1 = CI job bez změny runtime; N>1 = `statistics.median`
per scénář, baseline i current na stejné úrovni, report pole `"runs"`); stp044 self-baseline
`--runs 3` — šum musí zatížit > polovinu měření (flake +21.9 % vs prah 20 % vyřešen); oprava
regrese stp043 fake engine. Testy 6p/103s.

### P3 A Bounded JSON parse nedůvěryhodných vstupů (`51b0018`)
Nový doménový modul `domain/json_bounded.py` — `bounded_json_loads()` s hloubkovým limitem 200
(počet vnořených `{[` kontejnerů, root = level 1; reálné důkazy <30); fast path: celkový počet
otevíracích závorek ≤ limit → přímé `json.loads`, jinak lineární C-level scan přes regex nad
tokeny „řetězec | závorka“. `JsonLimitError(ValueError)` — parser kontrakt „Raises: ValueError“
zůstává platný, pipeline chytá broad Exception. Staged rollout přes celý povrch nedůvěryhodných
dat: **57 artifact parserů (68 call sites)** + STIX bundle upload (`threat_intel.py`) +
uživatelské plaso záznamy (`plaso_import.py`); AST guard test brání holým `json.loads/json.load(`
v povrchu. Testy 26p + cílená regrese dotčených parserů **1192 passed in 13.74s**.

### P3 B Installer subprocess timeouty (`b509e7c`)
Jediná díra auditu (network má už `urlopen`/`httpx` timeouty; volatility/tsk/luks/sandbox/
plugin_loader explicitní `timeout=`): `_subprocess(cmd, *, timeout_s=900)` → TimeoutExpired =
exit 124 + warning, FileNotFoundError = exit 127; vytvoření venvu pod samostatným limitem 300 s.
AST sken celé `src/stopa` vyžaduje explicitní `timeout=` u každého blokovacího volání
subprocess.run/Popen/call/check_output (regrese). Testy 6p + regrese installeru celkem 28p.

## Validace

- Full regression nad celou P2+P3 vlnou: **`5311 passed / 1 skipped`, exit 0** (37:47;
  delta +32 vs báze 5279p po P2 = nové P3 testy). Ruff clean repo-wide, rozpočet `db.py`
  **599/600**, PKG_COMPAT OK (`python -m stopa.cli --version` exit 0).
- Cílená regrese dotčených parserů (57 artifact + threat_intel + plaso): **1192 passed in 13.74s**.
- Benchmark vs baseline: **ok=true, regressions=[]** (`pipeline.core` lokálně 1625 ms vs CI
  baseline 4241 ms); gate >20 % a ≥0.5 ms beze změny; stp044 self-baseline `--runs 3`.
- GitHub CI: na `601867f` **8/8 jobů green** (jediné selhání = capacity flake macOS arm64 hosted
  runneru „no hosted-type runner could acquire the job“ → re-run #3 zelený bez změny workflow);
  na `39da653` **8/8 jobů green** (run 45291515347).
- Závěrečný report: `FORENSIC_HARDENING_REPORT.md` (§2 P2 A/B + P3 A/B; §7 finální výsledky;
  §9 „Zbývající reziduální rizika: žádná“).

## Známé limity / reziduální rizika

- Bounded XML: dokumenty s uživatelskými entity deklaracemi selhávají fail-closed (hloubka
  default 200, konfigurovatelná) — uvědomělý limit, dokumentován.
- Extra `carving` pinuje wheels z tagu **v2.4.0** (URL fungují); Rust core se v této vlně neměnil
  (`stopa_core` 0.1.0) → update pinu až s novým Rust kódem.
- macOS arm64 hosted runner capacity flake (GitHub infrastruktura): dosud stačilo re-run bez
  změny workflow; fallback = pin jobu na `macos-15-intel` + update PLATFORM_MATRIX.md
  (připraven, nepoužit).
