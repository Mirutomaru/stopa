# STOPA — Next Action

## Hotové v této fázi
- ✅ **STP-049** (H AI Copilot) — ETAPA H DOKONČENA ★★
- ✅ **STP-050** (I+O Validation Center UI) — 10 testů, suite 1901p/1s
- ✅ **STP-051** (G File Intelligence) — file preview v UI, 18 testů, suite 1919p/1s
- ✅ **STP-052** (O Audit Center) — hash chain + Ed25519 kontrolní body, 8 testů, suite 1927p/1s
- ✅ **STP-053** (J/M RBAC enforcement) — permission matrix + fail-closed guardrails, 29 testů, suite 1956p/1s
- ✅ **STP-054** (K Export Engine) — Plaso interop formát l2tcsv (17 polí log2timeline.pl), 19 testů, suite 1975p/1s
- ✅ **STP-055** (Q Interop / UCO mapping) — `domain/uco.py` kurátorské mapování 66/66 STOPA typů na UCO třídy (52 mapped + 14 explicitně unmapped), JSON-LD export, CLI `--format uco`, 22 testů, suite 1997p/1s
- ✅ **STP-056** (J Case Mgmt 2.0 UI) — přepínač role v Settings: topbar badge + živý preview oprávnění + `GET /api/roles`, 8 testů, suite 2005p/1s
- ✅ **STP-057** (Q Interop / Plaso import) — `domain/plaso_import.py` (parse l2tcsv → events + rekonstrukce UTC času), CLI `stopa plaso-import <case_id> SOUBOR` (source + artifacts + timeline + audit + kontrolní bod), 14 testů, suite 2019p/1s

## Další úkoly (priority)
Oblast Q (Interop) je **hotová ★★** — UCO mapping (STP-055) + Plaso import (STP-057).
Další kandidáti dle ROADMAP: volba dalšího rozšiřování oblastí (např. UI pro interop exporty,
Timesketch push, nebo nová oblast dle priority uživatele).

## Stav
- HEAD: viz git log (STP-057 code + DEV OS commits)
- Full suite: **2019 passed, 1 skipped**, ruff clean
  (pozn.: `test_stp044_ci_benchmark_e2e` je timing-sensitive — pod zátěží plné suite může být flaky; izolovaně stabilně PASS)
- Checkpoint: `.stopa-dev/checkpoints/latest.md`
