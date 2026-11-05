# STOPA — NEXT ACTION

## Po dokončení STP-045 (volba ETAPY E)

**ETAPA E ZAHÁJENA ★** — oblast M (Security): izolace parserů (sandbox).

### Hotové v ETAPĚ E zatím
- **STP-045:** volba směru + audit reálného stavu kandidátů (M/H/I+O) + synchronizace roadmapy.
  Klíčový nález: reálný hang `sqlite_carver.recover_rows` na poškozeném SQLite souboru (>15 s).

### Nejbližší úkol — STP-046 (ETAPA E vlna 1)
**`domain/sandbox.py`** — čistá doménová logika sandbox kontraktu:
- definice kontraktu: parser → subprocess s timeout + JSON marshalling výsledků,
- detekce dostupnosti backendu (subprocess fallback),
- konfigurace limitů (`timeout_s`, `max_result_bytes`).

Deterministické testy offline; full suite zelená po vlně; ruff clean.

### Následné vlny
- **STP-047 (vlna 2):** zapojení do pipeline + fix hang bugu v `sqlite_carver.recover_rows`.
- **STP-048 (vlna 3):** testy (umělý hangující parser, corrupt-file regression) + `docs/STOPA_SANDBOX.md`.

### Akceptační kritéria ETAPY E
Žádný parser nesmí zastavit pipeline (timeout + catch); poškozený soubor → `parser_error` artifact, ne crash; deterministické testy offline; full suite zelená po každé vlně; ruff clean.
