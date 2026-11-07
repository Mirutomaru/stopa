# STOPA — Next Action

## Hotové v této fázi
- ✅ **STP-049** (H AI Copilot) — ETAPA H DOKONČENA ★★
- ✅ **STP-050** (I+O Validation Center UI) — 10 testů, suite 1901p/1s
- ✅ **STP-051** (G File Intelligence) — file preview v UI, 18 testů, suite 1919p/1s
- ✅ **STP-052** (O Audit Center) — hash chain + Ed25519 kontrolní body, 8 testů, suite 1927p/1s
- ✅ **STP-053** (J/M RBAC enforcement) — permission matrix + fail-closed guardrails, 29 testů, suite 1956p/1s
- ✅ **STP-054** (K Export Engine) — Plaso interop formát l2tcsv (17 polí log2timeline.pl), 19 testů, suite 1975p/1s
- ✅ **STP-055** (Q Interop / UCO mapping) — `domain/uco.py` kurátorské mapování 66/66 STOPA typů na UCO třídy (52 mapped + 14 explicitně unmapped), JSON-LD export, CLI `--format uco`, 22 testů, suite 1997p/1s

## Další úkoly (priority)
1. **J Case Mgmt 2.0 UI** — přepínač role v Settings (RBAC enforcement hotový STP-053, chybí jen UI ovládání)
2. **Q Interop / Plaso import** — poslední nedokončená položka oblasti Q

## Stav
- HEAD: viz git log (STP-055 code + DEV OS commits)
- Full suite: **1997 passed, 1 skipped**, ruff clean
- Checkpoint: `.stopa-dev/checkpoints/latest.md`
