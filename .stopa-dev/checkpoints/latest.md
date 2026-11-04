# STOPA — Checkpoint (latest)

**Datum:** 2026-11-04
**Verze aplikace:** 0.1.0 (`pyproject.toml`)
**Commit:** ```bea2a25``` (předchozí: `9fa52dc` STP-032 docs, `da83a6f` STP-032 feature, `40c6305`, `4747738`)

## Co se stalo
**STP-033 — ETAPA B vlna 11: cloud SNS exporty (Twitter/X + Facebook warrant return) (4 parsery / 13 AXIOM typů)** (oblast D, P0) hotový.

### Nové parsery (`src/stopa/artifacts/`)
- `twitter_posts.py` — Twitter/X Posts (příspěvky author/text/created_at; tolerantní klíče tweet_id/from_user/body/date; retweety a odpovědi → `post_type=retweet/reply`); artifact type `sns_post`.
- `twitter_messages.py` — Twitter/X Direct Messages (DM konverzace sender/recipient/text/timestamp; konverzační formát participants/messages i plošný); artifact type `chat_message`.
- `twitter_users.py` — Twitter/X Users + sociální graf (screen_name/name/followers_count; vlastní účet → relationship=account, sekce followers/following → follower/following); artifact type `contact` s `mimetype=sns:twitter`.
- `facebook_wr.py` — Facebook Warrant Return (Messenger zprávy konverzace i flat formát, přátelé → contact sns:facebook, timeline příspěvky → sns_post post_type=timeline, info o profilu → contact relationship=account; auto-detekce sekcí podle struktury payloadu).

### Pipeline dispatch
- `_sns_prepass()` rozšířen o 4 nové detektory (pořadí twitter_posts → twitter_messages → twitter_users → facebook_wr) — bez kolizí s Instagram/Snapchat ani Google detektory.
- Dispatch verify: **20/20** nových basenames + 3/3 bez kolize (`Google/Messages.json`, `Drive/Files.json`, `Voice/Texts.json` → None).

### C3 registry
- 4 nové záznamy (`twitter_posts`/`twitter_messages`/`twitter_users`/`facebook_wr`) — `build_registry()` = **58 parserů** (předtím 54).

## Metriky
| Metrika | Předtím | Po vlně 11 |
|---------|---------|------------|
| Full suite | 1466 passed, 1 skipped | **1553 passed, 1 skipped** (+87) |
| C3 registry | 54 parserů | **58 parserů** |
| Coverage covered | 134 / 232 | **147 / 232 ★** |
| cloud-export NOT_SUPPORTED | 64 | **51** |
| memory NOT_SUPPORTED | 0 ★ | 0 ★ |
| portable-local NOT_SUPPORTED | 0 ★ | 0 ★ |

## Testy
- `tests/test_w11_parsers.py` — **87 syntetických offline testů**, ruff clean.
- Full suite: **1553 passed, 1 skipped**.

## Registry
- Feature: **F-062** ETAPA B vlna 11 — cloud SNS exporty (Twitter/X + Facebook warrant return).
- Testy: **T-083** `tests/test_w11_parsers.py` (87).
- Celkový stav TEST_REGISTRY: **1553 testů: 1552 PASS + 1 skipped**.

## Další krok
STP-034 — ETAPA B vlna 12 — cloud-export typy (Microsoft rodina, Amazon rodina) dle `.stopa-dev/NEXT_ACTION.md`.
