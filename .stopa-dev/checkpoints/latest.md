# STOPA — Checkpoint (2026-11-07)

## Hotovo
**STP-055 — Oblast Q Interop: UCO mapping ★**
- `domain/uco.py` (čistá logika bez IO): kurátorské mapování 66/66 KNOWN_ARTIFACT_TYPES na třídy oficiální UCO ontologie (`ucoProject/UCO`, ověřeno z TTL) — 52 mapped (observable/configuration/location/identity) + 14 explicitně unmapped.
- `map_artifact_to_uco()` → (class, module) | None; `uco_type_label()` → `<module>:<Class>` nebo `stopa:<typ>`.
- `to_uco_json(records, dataset)` — JSON-LD dokument: @context UCO, per-záznam objekty s @type/name/title|rel_path/time/x-stopa-id (traceability)/x-stopa (bez None); deterministický výstup.
- CLI `stopa export <case_id> --what ... --format uco [--limit N] [--out SOUBOR]`.
- Testy: `tests/test_stp055.py` (22) — map, type label, struktura, name fallback, time podmíněnost, x-stopa filtrace, pokrytí 66/66 bez overlapu, determinita, CLI export.

## Stav
- Full suite: **1997 passed, 1 skipped** (baseline 1975 + 22); ruff clean.
- HEAD před commitem: `9017f58` (docs devos STP-054). STP-055 commit hash viz git log.

## Další
J Case Mgmt 2.0 UI — přepínač role v Settings (RBAC enforcement hotový STP-053, chybí jen UI ovládání); pak Q Plaso import (poslední nedokončená položka oblasti Q).
