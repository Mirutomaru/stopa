# STOPA — CHECKPOINT (latest)

- **Datum:** 2026-11-05
- **HEAD:** `586e85a` (STP-045 volba ETAPY E = docs commit; předchozí HEAD `fe76901`)
- **Fáze:** Oblast M (Security) — **ETAPA E ZAHÁJENA ★** (volba směru hotová, čeká na vlnu 1)
- **Poslední dokončený úkol:** STP-045 — Volba ETAPY E: oblast M Security — izolace parserů (sandbox)

## Klíčové rozhodnutí
ETAPA E = **oblast M (Security): izolace parserů (sandbox)** — nejvyšší zbývající priorita P2 + největší dopad na spolehlivost. Audit prokázal reálný hang: poškozený SQLite soubor (garbage `db_size_pages` = 1.7 mld. stránek v 920 B) visí >15 s v `sqlite_carver.recover_rows`.

## Plán ETAPY E
- **Vlna 1 (STP-046):** `domain/sandbox.py` — sandbox kontrakt, timeout, JSON marshalling, backend detekce.
- **Vlna 2 (STP-047):** zapojení do pipeline (`_extract_artifacts_for` přes sandbox) + fix hang bugu v `sqlite_carver.recover_rows`.
- **Vlna 3 (STP-048):** testy (umělý hangující parser, corrupt-file regression) + `docs/STOPA_SANDBOX.md`.

## Stav
- Full suite: **1813 passed, 1 skipped** (~19s), ruff clean.
- C3 registry: **76 parserů**; covered **198 / 232 ★**.
- Git: clean po docs commitu.
