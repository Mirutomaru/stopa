# STOPA — Checkpoint (latest)

**Datum:** 2026-11-04
**Verze aplikace:** 0.1.0 (`pyproject.toml`)
**Commit:** ```da83a6f``` (předchozí: `40c6305` STP-031 docs, `4747738` STP-031 feature, `96cf2b9`, `1a3e007`)

## Co se stalo
**STP-032 — ETAPA B vlna 10: cloud SNS exporty (Instagram/Snapchat warrant return) (4 parsery / 20 AXIOM typů)** (oblast D, P0) hotový.

### Nové parsery (`src/stopa/artifacts/`)
- `instagram_messages.py` — Instagram Direct Messages (DM konverzace participants/messages; tolerantní klíče sender/from + text/body; sdílená média → `message_type=share` + media_url); artifact type `chat_message`.
- `instagram_posts.py` — Instagram Posts/Media/Photos/Stories/Comments (`sns_post`/`sns_comment`, stories detekce `is_story=True`; klíčové slovo `stor` chytí i `Stories.json`).
- `instagram_account.py` — Instagram Account Actions/History/FollowersAndFollowing (akce účtu login/password/device/IP → `event_log_entry`; followery/following → `contact` s `mimetype=sns:instagram`).
- `snapchat_wr.py` — Snapchat Warrant Return (6 subtypů s auto-detekcí podle obsahu: zprávy WR + skupinové chaty, přátelé, geolokace, IP historie, info o účtu); artifact types `chat_message`/`contact`/`location_data`/`network_connection`.

### Pipeline dispatch
- **Nový `_sns_prepass()` na celé cestě PŘED basename chainem** — generic basenames (`photos.json`, `messages.json`) kolidují s Google detektory, které dostávají jen `name`.
- Pořadí pre-passu: instagram_messages → instagram_account (PŘED posts — „AccountHistory" obsahuje substring „stor(y)") → instagram_posts → snapchat_wr.

### C3 registry
- 4 nové záznamy (`instagram_messages`/`instagram_posts`/`instagram_account`/`snapchat_wr`) — `build_registry()` = **54 parserů** (předtím 50).

## Metriky
| Metrika | Předtím | Po vlně 10 |
|---------|---------|------------|
| Full suite | 1385 passed, 1 skipped | **1466 passed, 1 skipped** (+81) |
| C3 registry | 50 parserů | **54 parserů** |
| Coverage covered | 114 / 232 | **134 / 232 ★** |
| cloud-export NOT_SUPPORTED | 84 | **64 ★ největší jednorázový skok v ETAPA B** |
| memory NOT_SUPPORTED | 0 ★ | 0 ★ |
| portable-local NOT_SUPPORTED | 0 ★ | 0 ★ |

## Testy
- `tests/test_w10_parsers.py` — **81 syntetických offline testů**, ruff clean.
- Full suite: **1466 passed, 1 skipped**.

## Registry
- Feature: **F-061** ETAPA B vlna 10 — cloud SNS exporty (Instagram/Snapchat warrant return).
- Testy: **T-082** `tests/test_w10_parsers.py` (81).
- Celkový stav TEST_REGISTRY: **1466 testů: 1465 PASS + 1 skipped**.

## Další krok
ETAPA B vlna 11 — cloud-export typy (Google Docs/Sheets/Slides, Microsoft Graph) dle `.stopa-dev/NEXT_ACTION.md`.
