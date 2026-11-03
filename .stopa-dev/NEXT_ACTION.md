# STOPA — NEXT ACTION

## Aktuální fáze
Oblast N/O (Performance/UI) — **STP-021 hotový** (stream parsing velkých E01 + web Processing Monitor);
předtím STP-019 AI governance, STP-020 report engine 9→20 sekcí, STP-018 Timeline Intelligence 2.0,
ETAPA B vlny 1–3 hotové.

## ID aktuálního úkolu
**STP-022** (READY — čeká na zahájení)

## Název úkolu
Security: SHA-512 + RBAC minimální + pip-audit CI (oblast M, priorita P2)

## Proč se úkol provádí
Integrity vrstva má jen SHA-256/MD5 — chybí SHA-512 pro moderní požadavky. RBAC je minimální
(actor není povinný u všech operací). pip-audit běží ručně, ne v CI. Oblast M, priorita **P2**.

## Co již bylo provedeno (STP-021)
- `data/ewf_container.py` — `_ewf_read()`/`_aff_read()` refaktorovány na chunked generátory
  `_ewf_chunks()`/`_aff_chunks()`; nové veřejné API `stream_to_raw(path, typ, dest, progress=None)`
  (1 MiB chunky přímo z kontejneru do RAW souboru — **RAM peak z GB na ~1 MiB**);
  `read_container()` = tenký wrapper pro backward compat.
- `data/image_pipeline.py` — `process_disk_image()` + keyword-only `extract_progress`;
  extrakce E01/AFF4 přes `stream_to_raw(..., progress=...)`.
- `web/app.py` — job registry `_jobs` + lock; `SourceIn.background: bool = False` (default sync);
  async ingest = daemon thread s vlastním DB spojením (per-thread `sqlite3.connect` → thread-safe);
  nový endpoint `GET /api/cases/{case_id}/processing` (aktivní běh + poslední 10).
- GUI — checkbox „pozadí" ve formuláři zdroje; async ingest polluje `/processing` každých 500 ms,
  status bar zobrazuje živý progress („Zpracovávám zdroj: … — done/total").
- **7 nových testů** (`tests/test_stp021.py`); full suite **1117 passed, 1 skipped**, ruff clean.

## Které soubory byly změněny (STP-021)
`src/stopa/data/ewf_container.py`, `src/stopa/data/image_pipeline.py`, `src/stopa/web/app.py`,
`src/stopa/web/static/index.html`, `src/stopa/web/static/js/components/modules.js`,
`tests/test_stp021.py` (nový), STOPA_CHANGELOG.md (+docs zrcadlo), STOPA_ROADMAP.md, `.stopa-dev/*`.

## Které soubory je potřeba prostudovat (před STP-022)
1. `src/stopa/domain/integrity.py` — aktuální hash vrstva (SHA-256/MD5 + Ed25519)
2. `src/stopa/data/db.py` — audit log operací (`log_operation`) — kde je actor povinný/nebo ne
3. `.github/workflows/ci.yml` — aktuální CI (ruff + pytest + jsdom)

## Co zbývá dokončit (STP-022)
1. SHA-512 v integrity vrstvě (hashing + manifesty + report)
2. Minimální RBAC: actor povinný u všech auditovaných operací
3. pip-audit do CI workflowu

## Jaké testy spustit
```bash
.venv/bin/python -m pytest tests/test_stp021.py -q   # stream + monitor (STP-021)
.venv/bin/ruff check src/stopa tests scripts         # lint (musí být clean)
.venv/bin/python -m pytest -q                        # plná sada (baseline 1117 passed, 1 skipped)
```

## Jak poznat úspěšné dokončení
- SHA-512 v integrity vrstvě + manifestech
- Actor povinný u auditovaných operací (RBAC minimální)
- pip-audit běží v CI
- Ruff clean na `src/stopa tests scripts`
- Plná sada bez regresí (≥ baseline 1117 passed, 1 skipped)
- Commit `feat(security): STP-022 — SHA-512 + RBAC minimální + pip-audit CI ...`

## Co nesmí být změněno
- Stream parsing E01/AFF4 (STP-021) — backward compat `read_container()` wrapper
- Web Processing Monitor (STP-021) — sync default ingest, job registry kontrakt
- C3 registry: `build_registry()` vynucuje 1:1 sync s pipeline + shodu verzí, jinak `RegistryError`
- Neodstraňovat existující testy kvůli zelenému výsledku; nepoužívat mockování místo kritické logiky
- Originální důkazní data zůstávají neměnná

## Další úkol po STP-022
STP-023 (Export: JSONL/XML/STIX formáty, P3).
