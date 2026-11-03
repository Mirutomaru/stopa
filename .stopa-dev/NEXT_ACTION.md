# STOPA — NEXT ACTION

## Aktuální fáze
**STP-022 hotový** (Security: SHA-512 integrity vrstva + RBAC minimální + pip-audit CI) — oblast M.
Commit: ``9707cd8``; full suite **1149 passed, 1 skipped**, ruff clean.

## Další úkol
### STP-023 — Export: JSONL/XML/STIX formáty (oblast K/Q, P3)
**Popis:** Rozšíření export engine o JSONL, XML, STIX/UCO.

**Kontext pro start:**
- Existující export: `src/stopa/domain/export.py` — stabilní sloupcová schémata
  (`ARTIFACT_COLUMNS`, `TIMELINE_COLUMNS`, `CORRELATION_COLUMNS`) + `to_csv()` / `to_json()`.
- CLI: `stopa export <case> --what artifacts|timeline|correlations --format csv|json [--limit N] [--out SOUBOR]`
  (`src/stopa/cli.py`).
- Testy: `tests/test_e10.py` (17) — pattern pro nové formáty.

**Navrhovaný design:**
1. **JSONL** — `to_jsonl()` v `domain/export.py`: jeden JSON objekt na řádek
   (`json.dumps(..., ensure_ascii=False)`), deterministické pořadí klíčů podle schématu;
   CLI `--format jsonl`.
2. **XML** — `to_xml()`: ElementTree (stdlib), kořen `<stopa-export>`, sekce podle `--what`;
   atributy = sloupce, entity escapované; deterministický výstup (bez timestampů v hlavičce
   nebo s explicitním `generated_at` parametrem).
3. **STIX/UCO** — minimální mapping: artifact → STIX 2.1 `indicator`/`observed-data`,
   timeline event → `observed-data` s `first_observed/last_observed`; UCO jako nadstavba
   (cybox-like). Začít s `to_stix()` pro artifacts + timeline; correlations = `relationship`.
4. CLI: `--format jsonl|xml|stix` (rozšíření existujícího dispatche).
5. Testy: nový `tests/test_stp023.py` — roundtrip JSONL, XML parse-back, STIX struktura
   (validace klíčových polí), determinismus výstupů.

**Backward compat:** CSV/JSON nezměněné; nové formáty = opt-in přes `--format`.

## Hotové v této fázi (STP-022)
- SHA-512: audit chain (`algo=`, per-algorithm GENESIS), manifesty opt-in, pipeline one-pass
  (FORENSIC profil), sloupec `files.sha512` + migrace, dedupe + hash lookup.
- Report CoC: SHA-512 sloupec jen když existuje.
- RBAC minimální: `domain/rbac.py`, `log_operation(strict=)` — explicitní actor > examiner.
- CI: job `security` s pip-audit (PyPI Advisory DB).
- Testy: 32 nových (`tests/test_stp022.py`), full suite **1149 passed, 1 skipped**.

## Registry
- Feature: **F-053** SHA-512 integrity vrstva + RBAC minimální + pip-audit CI.
- Testy: **T-074** `tests/test_stp022.py` (32).

## Checklist dokončení STP-023
- [ ] Audit existujícího export engine (`domain/export.py`, CLI dispatch)
- [ ] Implementace JSONL + XML + STIX/UCO
- [ ] CLI `--format jsonl|xml|stix`
- [ ] Testy (nový soubor, roundtrip + determinismus)
- [ ] Docs: changelog, roadmap K/Q, DEV OS registry (F-054/T-075), checkpoint
- [ ] Verify: ruff clean + full suite ≥1149 + commit

## Poznámky
- Domain = čistá logika bez IO; XML/JSONL/STIX buildery patří do `domain/export.py`.
- Determinismus výstupů je klíčový (testy srovnávají hash) — žádné implicitní timestampy.
- STIX: neimplementovat celou specifikaci — jen minimální court-ready mapping.
