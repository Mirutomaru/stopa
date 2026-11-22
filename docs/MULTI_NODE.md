# STOPA — Multi-node topology (P4-7)

Topologie pro běh více procesů STOPA nad jednou sdílenou instance DB.
Single source of truth: `src/stopa/data/cross_case_repository.py` (`open_instance()`),
`src/stopa/domain/event_bus.py`, `src/stopa/data/event_repository.py`,
`src/stopa/web/app.py` (polling worker).

## Přehled

| Prvek | Umístění | Mechanismus | Poznámka |
|---|---|---|---|
| Instance DB | `<db_dir>/stopa_instance.db` | SQLite **WAL** + `busy_timeout=5000 ms` (idempotentní PRAGMA v `open_instance()`) | sdílejí všechny procesy; čtení nezamyká zápis |
| Event bus | tabulka `events` v instance DB | monotónní `id` = pořadí (čas je jen diagnostika) | cross-process distribuce LiveEvent |
| Registry lease | sloupce `case_registry.node_id`, `.last_heartbeat` | monotónní sekvence beatů, **bez wall-clocku** (imunita vůči clock driftu) | liveness uzlů: alive / expired / unknown |
| Node identity | env `STOPA_NODE_ID`, jinak `socket.gethostname()` | textový identifikátor uzlu | headless uzel = libovolný unikátní řetězec |

## Event bus (W2)

Tabulka `events` v instance DB:

```sql
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- monotónní sekvence — deterministický pořad
    topic TEXT NOT NULL,                   -- case:{case_id} (domain.events.case_topic)
    payload_json TEXT NOT NULL,            -- kanonické JSON události (sort_keys, bez mezer)
    ts_utc TEXT NOT NULL                   -- ISO UTC (diagnostika; pořadí = id)
);
CREATE INDEX IF NOT EXISTS idx_events_topic_id ON events(topic, id);
```

- **Publisher** (`event_repository.publish_event`): insert + návrat `lastrowid`.
  Web proces publikuje každý LiveEvent zároveň do lokálního in-memory busu (WebSocket push
  pro vlastní klienty) a do DB.
- **Subscriber / polling worker** (`web/app.py`, interval `EVENT_POLL_INTERVAL_S = 0.25 s`):
  čte `WHERE id > cursor ORDER BY id LIMIT 500`, forwarduje události cizích procesů
  (deduplikace podle `_pid` v payloadu — vlastní události už šly lokálním busem).
- **Retence**: starší řádky se mažou `prune_old_events()` — retence
  `EVENT_BUS_RETENTION_H = 2 h`, frekvence `PRUNE_EVERY_CYCLES = 240` cyklů workeru
  (při 0,25 s ≈ jednou za 60 s). Best-effort: selhání pruningu nespálí cyklus.
- **Determinismus AK**: dva procesy nad jednou DB → události dorazí oběma subscriberům
  ve stejném pořadí (pořadí = `id`, ne timestamp).

## Registry lease / liveness (W3)

Sloupce `case_registry` (idempotentní migrace `apply_registry_lease_migration` —
instance DB nemá mechanismus verzovaných migrací):

```sql
node_id TEXT,                           -- který uzel naposledy heartbeatnul řádek
last_heartbeat INTEGER NOT NULL DEFAULT 0  -- monotónní seq lease (bez clock driftu)
```

- **Generace** = `MAX(last_heartbeat)` napříč uzly; jeden beat = jedno atomické zvýšení
  (`BEGIN IMMEDIATE` + `COALESCE(MAX(...), 0) + 1` pod SQLite writer lockem →
  přísně rostoucí napříč procesy, bez duplicit).
- **Stavy** (čistá doménová funkce `domain/case_registry.lease_status(entries)`):

  | Stav | Podmínka | Význam |
  |---|---|---|
  | `alive` | `generation − node_max < LEASE_WINDOW (8 beatů)` | uzel se nedávno hlásil |
  | `expired` | `generation − node_max ≥ 8` | uzel přestal heartbeatovat |
  | `unknown` | chybí `node_id`, nebo `generation == 0` | legacy řádek / claim bez beatu |

- **Fake clock v testech** = fiktivní řada heartbeatů (bez `freezegun`, deterministicky).
- **Web poller = automatický heartbeat**: běh polling workeru je liveness signál vlastního
  uzlu; každý cyklus bije beat pod `STOPA_NODE_ID`/hostname (busy/locked → debug log,
  pokračování v dalším cyklu).
- **Headless CLI**: `stopa registry --heartbeat NODE_ID [--json]` — vzájemně výhradní
  s `--sync`; tiskne novou globální generaci.

## Web povrch a konfigurace

| Cesta / parametr | Význam |
|---|---|
| `create_app(event_poll_interval_s=None)` | `None` = poller vypnutý (unit testy deterministické); produkce (`serve`, module-level app) používá 0,25 s |
| `app.state.ctx["_stop_event_poller"]` | test/inspection hook — `threading.Event`, jehož `.set()` worker čistě zastaví; `None` = poller vypnutý |
| `GET /api/registry` | vrací `{"entries": [...], "lease": {case_id: state}}` (lease = čistá doménová funkce nad vrácenými záznamy) |

## Omezení a další kroky

- **Jen SQLite** (dle AK); migrace na Postgres/Redis by vyžadovala nový `event_repository`.
- Distribuce je **polling, ne push** — latence ≈ interval workeru + busy_timeout.
- Pruning běží jen v web procesu; čistě headless topologie (bez `serve`) musí retenci
  řešit sama (např. periodic CLI úkol).
- Lease pokrývá **registry řádky**; liveness samostatných plugin workerů je nad rámec P4-7.
