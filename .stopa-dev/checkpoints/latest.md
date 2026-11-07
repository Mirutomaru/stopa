# STOPA — Checkpoint (2026-11-07)

## Hotovo
**STP-058 — Oblast O+Q: Interop Export Center UI ★ = GUI interop exporty hotové**
- `web/app.py` — nový endpoint `GET /api/cases/{id}/interop-export?what=&format=`: `what ∈ {artifacts, timeline, correlations}` (záznamy přes domain konvertory `artifact_records`/`timeline_records`/`correlation_records`), `format ∈ {csv, json, jsonl, xml, stix, uco, l2tcsv}` — dispatch na `to_csv`/`json.dumps`/`to_jsonl`/`to_xml`/`to_stix_bundle`/`to_uco_json`/`to_l2tcsv`; neplatný parametr → 400; download s `Content-Disposition: attachment` (filename `{case_id}_{what}.{ext}`, RFC 5987 quoting); každý export → audit log `interop_exported` (details what/format/records) + integrity checkpoint.
- SPA: nový modul `js/components/interop.js` — sekce `mod-interop` v index.html (datasety s živými počty z case detail + correlations, výběr datasetu × formátu, tlačítko Stáhnout → endpoint v novém okně, tabulka posledních 10 exportů z audit logu); registrace do `sidebar.js` (MODULES + ikona ⇩) a dispatch v `modules.js`.
- Testy: `tests/test_web.py::TestInteropExport` (9) — CSV header + Content-Disposition filename, l2tcsv 17 polí s source=STOPA, UCO JSON-LD (@context), STIX bundle (`type=bundle`), JSONL validní řádky, timeline/correlations datasety, neplatný dataset → 400, neplatný formát → 400, audit E2E `interop_exported`.

## Stav
- Full suite: **2028 passed, 1 skipped** (baseline 2019 + 9); ruff clean.
- Commit: `01b8a6e` feat(web): STP-058 interop export UI (l2tcsv + UCO mapping).

## Další
Oblast O rozšířena ★ — GUI interop exporty hotové; oblast Q zůstává kompletní ★★. Další kandidáti dle priority: viz NEXT_ACTION.md / TASKS.md roadmap (Timesketch push, nebo nová oblast dle priority uživatele).
