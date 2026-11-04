# STOPA — Checkpoint (latest)

**Datum:** 2026-11-04
**Verze aplikace:** 0.1.0 (`pyproject.toml`)
**Commit:** ```496391b``` (předchozí: `587a1ac` STP-035 docs, `31bceb2` STP-035 feature)

## Co se stalo
**STP-036 — ETAPA B vlna 14: dokončení cloud-export kategorie (6 nových parserů / 19 AXIOM typů → NOT_SUPPORTED celkem 0 ★)** (oblast D, P0) hotový.

### Nové parsery (`src/stopa/artifacts/`)
- `apple_cloud.py` — Apple Cloud rodina: Contacts (`contact`, tolerantní klíče + `_list_of_str` pro listy dictů), Keychain (`credential` label/account/type/data), Mail (`email_message`, body do `details`), Photos (`media_asset`), Backup (`file_metadata`); **auto-detekce podtypu `_detect_kind()`**; detektor vyžaduje `.json` příponu (nekrade iMessage TSV `[Apple_Request]-MessagesInICloud-1.csv`).
- `google_2025_wr.py` — Google 2025 WR: AccessLogDevices (`event_log_entry`), AccountTargetAssociation (`contact` relationship=account_target), Calls (`call_record` from/to/duration); **klíčová slova bez podtržítek** (accesslog/targetassoc/call) pro CamelCase exporty; call fallback `from`/`to` klíče.
- `whatsapp_cloud.py` — WhatsApp Chats (`chat_message`, body do `details["text"]`) + Backups (`file_metadata` backupDate/version/sizeBytes); auto-detekce kind chat|backup.
- `cloud_generic.py` — generic cloud metadata: AccountsInfo (accountName fallback), ConnectedApps, RecentDevices, Timeline, Passwords, AndroidBackups, AzureVM snapshots; **nejobecnější detektor** — v `_sns_prepass()` poslední, aby nekradl cizí soubory.
- `gmail_messages.py` — Gmail Messages (`email_message`, tolerantní klíče).
- `maps_labeled_places.py` — Google Maps Labeled Places WR (`location_point`).

### Pipeline dispatch
- `_sns_prepass()` rozšířen o 6 vlna-14 detektorů (pořadí: **specifické PŘED obecným `cloud_generic`**); docstring ETAPA B vlna 10/11/12/13/14.
- `NAME_BASED_EXTRACTORS` +6 položek; imports v abecedním pořadí (apple_cloud před bebo_chat, cloud_generic před ddg_current_tabs, gmail_messages/google_2025_wr v Google bloku, maps_labeled_places za mailru_agent, whatsapp_cloud před win_amcache).

### C3 registry
- 6 nových záznamů (`apple_cloud`/`google_2025_wr`/`whatsapp_cloud`/`cloud_generic`/`gmail_messages`/`maps_labeled_places`) — `build_registry()` = **76 parserů** (předtím 70).

## Metriky
| Metrika | Předtím | Po vlně 14 |
|---------|---------|------------|
| Full suite | 1671 passed, 1 skipped | **1729 passed, 1 skipped** (+58) |
| C3 registry | 70 parserů | **76 parserů** |
| Coverage covered | 179 / 232 | **198 / 232 ★** |
| cloud-export NOT_SUPPORTED | 19 | **0 ★ (vyčerpána)** |
| NOT_SUPPORTED celkem | 19 | **0** (base-class 34 = rozhraní) |
| memory NOT_SUPPORTED | 0 ★ | 0 ★ |
| portable-local NOT_SUPPORTED | 0 ★ | 0 ★ |

## Testy
- `tests/test_w14_parsers.py` — **58 syntetických offline testů** (6 parserů + dispatch pre-pass routing), ruff clean.
- Full suite: **1729 passed, 1 skipped**.

## Registry
- Feature: **F-065** ETAPA B vlna 14 — dokončení cloud-export kategorie (6 nových parserů / 19 typů → NOT_SUPPORTED celkem 0 ★).
- Testy: **T-086** `tests/test_w14_parsers.py` (58).
- Celkový stav TEST_REGISTRY: **1729 testů: 1728 PASS + 1 skipped**.
