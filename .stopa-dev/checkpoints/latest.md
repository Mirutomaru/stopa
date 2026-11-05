# STOPA — CHECKPOINT (latest)

- **Datum:** 2026-11-05
- **HEAD:** `de18452` (STP-046 ETAPA E vlna 1: feature commit `91854d8`, docs commit `67049e8`, fix benchmark stabilizace `de18452`; předchozí HEAD `5fdf53c`)
- **Fáze:** Oblast M (Security) — **ETAPA E vlna 1 hotová ★** (sandbox kontrakt, čeká na vlnu 2)
- **Poslední dokončený úkol:** STP-046 — ETAPA E vlna 1: parser sandbox kontrakt (`domain/sandbox.py`)

## Klíčové rozhodnutí
Sandbox kontrakt jako čistá doménová logika (`domain/sandbox.py`) + tenký IO wrapper (subprocess). Dceřiný proces `stopa.sandbox_worker` = stdout POUZE JSON array artifactů, exit 0/1. Klasifikace selhání s prioritou: timeout > truncated > bad_payload > crash. RLIMIT_CPU backstop na POSIX.

## Plán ETAPY E
- **Vlna 1 (STP-046):** ✅ `domain/sandbox.py` + worker modul — kontrakt, timeout, JSON marshalling, backend detekce.
- **Vlna 2 (STP-047):** zapojení do pipeline (`_extract_artifacts_for` přes sandbox) + fix hang bugu v `sqlite_carver.recover_rows`.
- **Vlna 3 (STP-048):** testy (umělý hangující parser, corrupt-file regression) + `docs/STOPA_SANDBOX.md`.

## Stav
- Full suite: **1834 passed, 1 skipped** (~20s), ruff clean.
- C3 registry: **76 parserů**; covered **198 / 232 ★**.
- Git: clean po docs commitu.
