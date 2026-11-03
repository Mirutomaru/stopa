# STOPA — Checkpoint (latest)

**Datum:** 2026-11-03
**Verze aplikace:** 0.1.0 (`pyproject.toml`)
**Commit:** ```210c370``` (předchozí: `5c08679` STP-022 docs, `9707cd8` STP-022 feature, `e0c34b3`, `1ab3488`, `5f964f5`, `6d74ab3`, `7360bab`, `1437927`, `cd5aa25`)

## Co se stalo
**STP-023 — Export: JSONL/XML/STIX formáty** (oblast K/Q, P3) hotový.
Rozšíření export engine o tři nové formáty nad stávajícím `domain/export.py`:
- **JSONL** (`to_jsonl`) — 1 objekt/řádek, streamovací, deterministické pořadí klíčů podle schématu.
- **XML** (`to_xml(records, dataset=)`) — deterministický ElementTree (stdlib), UTF-8 deklarace,
  kořen `stopa_<dataset>`, záznamy `<artifact>/<event>/<correlation>`, None vynechány, dict/list jako JSON.
- **STIX 2.1** (`to_stix_bundle(records, dataset=)`) — bundle: artefakty → objekty `file`/`message`
  (konzervativní mapa `_STIX_TYPE_MAP`), ostatní datasety → `x-stopa-record`, původní záznamy v rozšíření
  `x-stopa`; **deterministická UUIDv5 ID** ze `STIX_NAMESPACE` pro C4 reprodukovatelnost.
- CLI: `stopa export --format csv|json|jsonl|xml|stix` (dispatch + argparse).

## Změněné soubory
- `src/stopa/domain/export.py` — +`to_jsonl`, `to_xml`, `to_stix_bundle`, `_stix_name`, `STIX_NAMESPACE`, `_STIX_TYPE_MAP`.
- `src/stopa/cli.py` — `cmd_export` dispatch jsonl/xml/stix, argparse `--format`, module docstring + parser help.
- `tests/test_stp023.py` — **nový soubor, 17 testů** (JSONL/XML/STIX domain + CLI roundtrip).
- `STOPA_CHANGELOG.md` (+docs zrcadlo), `STOPA_ROADMAP.md` (K ✅ hotovo, Q +STIX 2.1).

## Testy
- Nové: `.venv/bin/python -m pytest tests/test_stp023.py -q` → **17 passed in 0.13s**.
- Full suite: `.venv/bin/python -m pytest -q` → **1166 passed, 1 skipped** (baseline 1149 + 17).
- Ruff: `All checks passed!` pro `src/stopa tests scripts`.

## Registry
- Feature: **F-054** Export JSONL/XML/STIX 2.1 formáty.
- Testy: **T-075** `tests/test_stp023.py` (17).
- Celkový stav TEST_REGISTRY: **1166 testů: 1165 PASS + 1 skipped**.

## Coverage matice
covered **51 / 232** unikátních typů (bez změny — export engine, ne nové extraktory).

## Další krok
**ETAPA B vlna 4 — Artifact Engine: portable-local typy** (oblast D, P0) — pokrytí dalších ~6–10
portable-local typů (prefetch, jumplist/.lnk, recent/MRU, USB/device, print spooler, DNS cache/hosts,
taskbar/startmenu). Detail v `NEXT_ACTION.md`.
