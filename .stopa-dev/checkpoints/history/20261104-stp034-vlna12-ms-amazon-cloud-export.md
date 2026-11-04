# STOPA — Checkpoint (latest)

**Datum:** 2026-11-04
**Verze aplikace:** 0.1.0 (`pyproject.toml`)
**Commit:** ```47e7103``` (předchozí: `bea2a25` STP-033 feature, `9fa52dc` STP-032 docs, `da83a6f` STP-032 feature)

## Co se stalo
**STP-034 — ETAPA B vlna 12: cloud-export Microsoft + Amazon (8 parserů / 12 AXIOM typů)** (oblast D, P0) hotový.

### Nové parsery (`src/stopa/artifacts/`)
- `ms_contacts.py` — Microsoft Graph/Outlook kontakty (displayName/email/phone; tolerantní klíče; vlastní účet → relationship=account); artifact type `contact`.
- `ms_mail_pst.py` — Outlook mail PST export (from/to/subject/body/date; konverzační i flat formát); artifact type `email_message`.
- `ms_teams_conversations.py` — Teams konverzace/zprávy (senderDisplayName/from, body, date; konverzační i plochý formát); artifact type `chat_message`.
- `ms_teams_teams.py` — Teams týmy + členové (team name/description, členové s rolí owner/member → contact sns:microsoft:teams); artifact type `contact`.
- `ms_outlook_calendar.py` — Outlook kalendář události (subject/organizer/start/end/location; tolerantní klíče); artifact type `calendar_event`.
- `sharepoint_wr.py` — SharePoint Warrant Return (strany → `web_page`, dokumenty → `file_metadata`; auto-detekce kind page/document podle struktury).
- `amazon_cloudtrail.py` — Amazon CloudTrail API akce (eventName/userIdentity/sourceIPAddress; explicitní isinstance fallback pro userIdentity); artifact type `event_log_entry`.
- `amazon_ec2_s3.py` — Amazon EC2 instance + S3 objekty (instance → `network_connection`, S3 key/size/bucket → `file_metadata`; union detekce podle struktury).

### Pipeline dispatch
- `_sns_prepass()` rozšířen o 8 MS+Amazon detektorů (pořadí: specifické PŘED obecnými — ms_mail_pst → ms_contacts → ms_outlook_calendar → ms_teams_conversations PŘED ms_teams_teams → sharepoint_wr → amazon_cloudtrail → amazon_ec2_s3) — bez kolizí s Google contacts ani Twitter/SNS detektory.
- `NAME_BASED_EXTRACTORS` +8 položek; imports v abecedním pořadí (Amazon před bebo_chat, MS mezi mem_scan a msn_messenger, SharePoint mezi registry_extract a skype_warrant_return).

### C3 registry
- 8 nových záznamů (`ms_contacts`/`ms_mail_pst`/`ms_teams_conversations`/`ms_teams_teams`/`ms_outlook_calendar`/`sharepoint_wr`/`amazon_cloudtrail`/`amazon_ec2_s3`) — `build_registry()` = **66 parserů** (předtím 58). Limity v textu srovnány s reálnými konstantami parserů (5000).

## Metriky
| Metrika | Předtím | Po vlně 12 |
|---------|---------|------------|
| Full suite | 1553 passed, 1 skipped | **1626 passed, 1 skipped** (+73) |
| C3 registry | 58 parserů | **66 parserů** |
| Coverage covered | 147 / 232 | **159 / 232 ★** |
| cloud-export NOT_SUPPORTED | 51 | **39** |
| memory NOT_SUPPORTED | 0 ★ | 0 ★ |
| portable-local NOT_SUPPORTED | 0 ★ | 0 ★ |

## Testy
- `tests/test_w12_parsers.py` — **73 syntetických offline testů**, ruff clean.
- Full suite: **1626 passed, 1 skipped**.

## Registry
- Feature: **F-063** ETAPA B vlna 12 — cloud-export Microsoft + Amazon (8 parserů / 12 AXIOM typů).
- Testy: **T-084** `tests/test_w12_parsers.py` (73).
- Celkový stav TEST_REGISTRY: **1626 testů: 1625 PASS + 1 skipped**.
