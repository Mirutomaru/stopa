# Changelog

Všechno významné změny v STOPA jsou dokumentovány v tomto souboru.

Formát následuje [Keep a Changelog](https://keepachangelog.com/cs/1.0.0/) a projekt
respektuje [Semantické verzování](https://semver.org/lang/cs/).

## [Unreleased]

### Přidáno (Added)

#### F1.2 Memory Forensics — Volatility 3 integrace
- CLI `stopa memory-analyze <case> <dump>`: spuštění Volatility 3 jako subprocess
  (`.venv/bin/vol -q -r json -f <dump> <plugin>`), výchozí sada pluginů
  pslist/netscan/ldrmodules/malfind, opakovaný `--plugin` + `--with-defaults`,
  idempotentní re-analýza (reuse EvidenceSource + výměna artefaktů).
- Výstup = kanonické Artifacty s typy `memory_v3_process/connection/module/injected/sid`
  v CASE DB, cross-plugin anomaly flags (C2 candidate, RWX injected code…).
- Volitelná runtime závislost `volatility3` (bez ní graceful „není nainstalovaná",
  statický scanner zůstává).
- Safety: surové credential data se do DB neukládají — jen typ + SHA-256 fingerprint.

#### F1.3 Síťová forenzika — PCAP analýza (scapy)
- CLI `stopa pcap-analyze <case> <capture>`: parser .pcap/.pcapng přes scapy
  (volitelná runtime závislost `[net]` extra, lazy import + fallback bez scapy).
- TCP stream reassembly per-flow (seq sort, de-duplicita), UDP/DNS normalizace;
  extrakce HTTP GET/POST s filename z Content-Disposition, FTP STOR/RETR, SMB2 detekce.
- IoC detekce — 5 pravidel: dns_tunneling, c2_beaconing, suspicious_url_path,
  base64_blob_payload, unusual_high_port_tcp (regex heuristiky; YARA odloženo na F1.4).
- Artefakty `network/traffic|flow|http|ftp|smb|dns|ioc` do case DB idempotentně,
  automaticky indexovány FTS (`artifacts_fts`); surové body do `<root>/extracted/<case_id>/network/`.
- Safety: v DB jen SHA-256 fingerprint payloadů — nikdy plný obsah.

#### F1.4 Anti-Forensics detekce
- CLI `stopa antiforensics-scan <case> [--image PATH]`: standalone command nad
  čistým doménovým modulem (stdlib; PIL jen lazy pro steganografii, volitelná).
- 8 detekcí: timestomping (future mtime / nemožný pořad M<C / bulk-touch ≥5),
  log clearing (EVTX event 1102 + mezery v record numbers), USN journal truncation
  (hustota záznamů + delete podíl >50 %), MBR/partition table, LSB steganografie
  PNG/JPG (bitová vyváženost + Shannon entropie), tool signatures, image integrity.
- Orchestrátor `detect_anti_forensics` vrací report s risk score (`1−0.9^acc`).
- Artefakty `antiforensics/<check>` pod syntetickým scan zdrojem + timeline alerty;
  idempotentní re-run (timeline se mažou PŘED výměnou artefaktů — FK bez ON DELETE).
- 34 testů (`tests/test_f14_anti_forensics.py`); suite 2355 passed.

#### F2.5 Cache vrstva — procesní LRU + TTL per query type
- `src/stopa/data/query_cache.py`: thread-safe (RLock) LRU cache s TTL per typ
  (`fts` 5 min, `entities`/`correlations` 10 min), scope = `os.path.realpath`
  case DB souboru; procesní singleton `PROCESS_CACHE` sdílený všemi CaseDB
  instancemi téhož souboru (web GUI běží per-request connectiony).
- Cacheované operace: `CaseDB.search` (FTS), `list_entities`, `list_correlations`.
- Explicitní invalidace na mutačních bodech facade (upsert_file, artifact/entity/
  correlation upserty, replace/delete, delete_case) — O(1) přes reverzní index;
  TTL = bezpečnostní síť proti přehlédnutému bodu.
- Diagnostika: `/api/diagnostics.query_cache` (hits/misses/hit_ratio).
- AK ověřeno testy: opakovaná FTS query < 50 ms ✓, hit ratio ≥ 70 % ✓ —
  19 testů `tests/test_f25_query_cache.py`; suite 2957 passed / 1 skipped.

#### F3.1 AI Agent framework — ReAct tool-use nad živým case DB
- `src/stopa/intelligence/tool_agent.py`: vlastní ReAct smyčka (bez nových
  externích závislostí — dle ROADMAP volby „LangGraph / vlastní"): LLM plánuje
  kroky JSON (`thought` + přesně jeden z `action`/`final_answer`), runtime
  spouští nástroj, observation se vrací do smyčky; terminace = `final_answer`
  nebo `max_steps`.
- 5 deterministických nástrojů `(db, case_id, params) -> dict`: `search_fts`,
  `get_timeline` (time-range + anomalies_only), `resolve_entity` (+ korelace),
  `run_yara` (WIF/BTC/ETH/BIP-39 bez yara-python; BIP-39 přes K1 `detect_in_text`,
  do výstupu jen SHA-256 fingerprint — raw seed ne), `generate_hypothesis`
  (confidence ∝ počet podpůrných dokazových prvků).
- Auditovatelnost: každá akce → `audit_log` action=`ai_agent_action`
  (append-only hash chain; details = step/tool/params/observation_chars/elapsed_ms).
- Grounding: ve final answer se validuje **100 % citací** `[art:id]`/`[file:id]`
  proti case DB — jediná nevalidní = fail-closed `GroundingError`.
- Guardrails: XOR action/final_answer (Pydantic), `max_steps`, PII redaction
  default ON (STP-019), tolerance markdown fence, neznámý nástroj = observation
  s chybou (agent může opravit). LLM injektovatelná (`llm_call`) → offline
  deterministické testy bez LM Studio.
- AK: agent vyřeší 10/10 testovacích případů ✓; každá akce v audit logu ✓;
  grounding validuje 100 % citací ✓ — 15 testů `tests/test_f31_tool_agent.py`
  (5 unit + 10 AK scénářů s FakeLLM). Ruff + Pyright clean.

#### F3.2 Triage profily — předpřipravené agendy pro typické případy
- `src/stopa/intelligence/triage.py`: deterministický signálový engine nad case DB
  (bez LLM, bez nových externích závislostí). 4 profily: **Ransomware** (timestomping,
  ransom extenze/poznámky, kryptowallety, C2), **Insider threat** (USN truncation,
  timestomping, odpojitelná média, osobní schránky), **CSAM/média** (steganografie,
  obrázkové cluster ≥5, audio nahrávky, skryté partice), **Exfiltrace** (base64 bloby,
  hromadné přílohy ≥3, cloud bulk upload ≥5, mazání po kopírování).
- Signály = 5 druhů dotazů na case DB: `artifact_type`, `artifact_text` (IoC pravidla),
  `timeline_flag` (kanonické flagy nesrovnalostí), `file_pattern` (regex + min_count),
  `entity_pattern`. Detekce = score ≥ threshold **a** min. 2 různé signály (FPR guard);
  každý zapálený signál nese důkazová ID (max 5).
- Hypotézy: vyplnitelné template `{case_id}/{score}/{signals}` — kompatibilní s F3.1
  `generate_hypothesis` a připravené pro report vrstvu. API: `evaluate_profile`,
  `run_triage` (výstupy seřazené dle skóre), `get_profile`.
- AK ✓: 4 profily; každý detekuje ≥8/10 syntetických pozitiv; FPR < 5 % — 14 testů
  `tests/test_f32_triage_profiles.py` (8 parametrizovaných AK + 6 unit). Ruff + Pyright clean.

#### F3.3 Natural Language Query → SQL/FTS — dotazování do případu přirozeným jazykem
- `src/stopa/intelligence/nl_query.py`: NL text → **parametrizovaný SELECT** nad case DB
  (bez nových externích závislostí; LLM injektovatelná jako `llm_call(nl_text, schema_context)`,
  offline testy s FakeLLM).
- Pipeline: živé schéma z DB (`build_schema_context`, FTS shadow tabulky vynechány) →
  validace (jedno vyjádření SELECT/WITH, zakázaná slova INSERT/UPDATE/DELETE/DROP/ALTER/
  CREATE/PRAGMA/REPLACE, whitelist tabulek z `sqlite_master`, počet placeholderů = počet
  parametrů; jinak `InvalidQueryError`) → **read-only sandbox** samostatné spojení
  `file:<case>.db?mode=ro` (dotaz nemůže mutovat case DB) → **timeout 5 s** přes
  `set_progress_handler(callback, 250_000)` (`QueryTimeoutError`) → výstup omezen na
  `MAX_ROWS_HARD_CAP` řádků (`truncated=True`). Každý dotaz → `audit_log` (action=`nl_query`).
- API: `run_nl_query`, `execute_sandboxed`, `build_schema_context`, `known_tables`.
- AK ✓: 50 testovacích NL queries = **50/50 (100 % ≥ 90 %)**; žádný SQL injection
  (parameterized — explicitní scénář s `'; DROP TABLE files; --`); timeout 5 s —
  19 testů `tests/test_f33_nl_query.py`. Ruff + Pyright clean.

#### F3.4 Generování právních dokumentů — Forensic Methodology / Chain of Custody / Expert Witness
- `src/stopa/intelligence/legal_docs.py`: tři šablony vyplněné z case DB (bez nových dep):
  **forensic_methodology** (rozsah, metodika, statistika, reprodukovatelnost),
  **chain_of_custody** (affidavit + řetěz úlohy z append-only audit logu s hash chainingem),
  **expert_witness** (Daubert/SWGDE kritéria, hlavní nálezy, expertní tvrzení).
- AI narrative sekce přes injektovatelné `llm_call(prompt) -> str`; bez LLM nebo při jejím
  selhání deterministický fallback text (dokument se neztrácí).
- **Ed25519 podpis dokumentu:** re-use `domain/integrity.py` (`sign_hash`, `verify_signature`)
  + klíč případu `db.ensure_integrity_key()`; lazy import `cryptography` → graceful degradation
  (nepodepsaný dokument s poznámkou). Podpis na SHA-256 kanonického obsahu (`signed_content`),
  integritní blok s hashem+podpisem připojen za obsah.
- Nezávislé ověření `verify_legal_doc()` bez soukromého klíče (tampering dokumentu → False).
  Právní review = explicitní sekce „Právní review“ v každé šabloně (lidský krok dle AK).
- API: `generate_legal_doc(db, case_id, doc_type, llm_call=None)`, `verify_legal_doc(result)`,
  `LEGAL_DOC_TYPES` (3), `LegalDocResult`.
- AK ✓: 3 šablony; generování < 30 s (ms v praxi, měřeno testem); Ed25519 sign/verify round-trip
  + tamper detekce — **14/14** testů `tests/test_f34_legal_docs.py`. Ruff + Pyright clean.

#### F3.5 Hypothesis graph — AI graf hypotéz s ručním potvrzením/vyvrácením
- `src/stopa/intelligence/hypothesis_graph.py` (bez nových dep): uzel = claim + confidence
  (**0.1–0.9** CHECK constraint) + status **pending/confirmed/refuted** + důkazy PRO/PROTI
  jako ID artefaktů; strom podhypotéz přes `parent_id`. Nová tabulka `hypotheses` (schéma v15),
  `data/hypothesis_repository.py` + CaseDB facade (`add_hypothesis`, `list_hypotheses`,
  `get_hypothesis`, `set_hypothesis_status`).
- Generování: **(a) AI** — injektovatelné `llm_call(prompt) -> str` vracející JSON pole uzlů;
  **(b) deterministický fallback** z triage F3.2 (detekované profily → hypotézy, bez LLM).
  Fail-closed na neplatný LLM výstup (`HypothesisGraphError`); fail-soft grounding citace
  (neexistující artefakty se vyřadí). Limity: `MAX_NODES`, `EVIDENCE_CAP_PER_SIDE`,
  confidence clamp, parent-index mapping odolné vůči vyřazeným prvkům.
- **Lineage:** `graph_payload()` rozřeší citace na existující artefakty (id/type/title) +
  hrany `parent`/`support`/`against`. **Export PDF/JSON** — JSON round-trip; PDF přes
  WeasyPrint (lazy import → graceful `RuntimeError`). Audit akce `hypothesis_graph_generated`.
- Web API: `GET /api/cases/{id}/hypotheses`, `POST .../generate` (AI/fallback, 503 bez LM Studio),
  `POST .../hypotheses/{hid}/status` (**ruční potvrzení/vyvrácení — AK**),
  `GET .../export?format=json|pdf`. UI: panel „Hypothesis Graph“ v AI modulu (strom s confidence,
  status ✓/✗ akce, klikací důkazové citace).
- AK ✓: graf v UI; lineage k artifactům; export PDF/JSON — **20/20** testů
  `tests/test_f35_hypothesis_graph.py` (včetně web E2E přes TestClient). Ruff + Pyright clean.

#### F4.1 SPA Frontend — React 18 + TypeScript + Vite na `/spa`
- Rozhodnutí: **React 18 + TS + Vite** jako čistý static build servírovaný existujícím
  FastAPI (bez SSR/Node serveru v produkci → zachován single-process model). Kód v `frontend/`,
  build → `src/stopa/web/static/spa`; mount `/spa` v `app.py`, legacy vanilla JS GUI na `/`
  zůstává s odkazem „SPA →“ (přechodová doba).
- **Views**: Dashboard (případy + creation), File System grid (paginace, family filtr),
  Artifact detail, Timeline (zoom = časové okno, lanes podle typu události, anomaly flagy),
  Entity graph (SVG kruhový layout, barva = kind — Maltego-like), AI Copilot chat
  (`nl_search`/`summary` přes `POST /ai/query`), Hypothesis Graph (F3.5 UI: generování
  fallback/AI, ✓ potvrdit / ✗ vyvrátit, export JSON/PDF).
- **Typovaný API klient** `frontend/src/lib/api.ts` proti endpointům FastAPI
  (CaseSummary/FileRow/TimelineRow/EntityRow/HypoGraphPayload + ApiError s detail z těla).
- **i18n CS/EN** context (persist v localStorage) — AK ✓. **Offline-first Service Worker**
  `sw.js`: static cache-first, API network-first + cache fallback = read-only režim — AK ✓.
- **Lighthouse (Playwright Chromium)**: performance **100** / accessibility **100** /
  best-practices **96** / SEO **90**, LCP 0.8 s → AK „≥ 90“ splněn ve všech kategoriích.
- Testy: vitest **10/10** (API klient, i18n toggle+persist, Dashboard smoke), Python
  `tests/test_f41_spa.py` **5/5** (mount `/spa`, sw.js, assety, legacy `/`). TSC strict 0 chyb.

#### F4.2 WebSockets — real-time updates na `/api/cases/{id}/ws`
- **`src/stopa/domain/events.py`**: `LiveEventBus` — in-process pub/sub **bez Redis**
  (single-process model), téma ``case:{case_id}``, bounded queue per subscriber
  (`maxsize=256`), publish nablokující (pomalý konzument ztrácí nejstarší, pipeline
  se nezastaví); thread-safe.
- **Hooky `CaseDB.on_event`** (`data/db.py`): emit v `add_timeline_event` →
  `timeline.event`, v `log_operation` → `ai.action` jen pro prefix `ai_`; defenzivní
  try/except (diagnostický kanál nesmí rozbít API cestu).
- **Web**: `_bus` v closure `create_app()`, factory parametr `ws_heartbeat_s=15.0`,
  helper `_attach_live_events()` napojuje hook na obě cesty (sync ingest i background
  worker), `ingest.progress` s throttlem per job. Endpoint `GET /api/cases/{id}/ws`:
  okamžité `hello`, stream `ingest.progress`/`timeline.event`/`ai.action`, heartbeat,
  neznámý case → close code **4004**.
- **Frontend**: singleton `LiveClient` (backoff 500 ms→8 s, disconnect na `pagehide`),
  hooky `useLiveConnection`/`useLiveEvent`, `LiveBadge` LIVE/OFFLINE v sidebaru;
  Dashboard/CaseFiles/Entities obnova po hotovém ingestu, Timeline auto-refresh,
  AiPanel posledních 5 AI akcí. Graceful degradation: bez WS klientů vše přes REST.
- AK ✓: latence < 200 ms (pytest měří delivery publish→klient; E2E smoke na živém
  uvicornu naměřil **140 ms** včetně celého synchronního ingestu přes reálný TCP);
  graceful degradation testováno; **100/100** současných klientů dostalo událost.
- Testy: `tests/test_f42_ws.py` **15/15**; vitest 10/10; TSC strict 0 chyb; ruff clean.

#### F4.3 Peer-Review Workflow — stavový automat + kvorum + audit trail
- **`src/stopa/domain/review.py`**: čistý stavový automat `draft → reviewed → approved
  → court_ready`; přechod vždy přesně o jeden krok vpřed (přeskočení i zpětný přechod
  selže); kritický artefakt vyžaduje k schválení **minimálně 2 distinct examinátorů** —
  stejný člověk se nepočítá dvakrát.
- **Schéma v15 → v16**: `artifacts.review_state` + tabulka `artifact_reviews`
  (neměnná historie review akcí pro soudní doložitelnost: kdo, kdy, na co); legacy
  migrace doplní sloupec do starých DB.
- **Kritičnost** je deterministická: analytický nález odkazující na soubor artefaktu
  (`findings.provenance_json` přes `json_extract`, bez LIKE zkratkovitostí).
- **Web API**: `GET /api/cases/{id}/artifacts` (listing s review_state),
  `POST .../artifacts/{aid}/review` → 201 / 409 neplatný přechod nebo kvorum /
  404 artefakt; `GET .../reviews` → kritičnost + historie. RBAC oprávnění
  `case.review` (analyst/examiner/admin).
- **Audit trail**: každá review akce = audit log `artifact.review` (hash chaining)
  + řádek v `artifact_reviews`; při neplatném přechodu DB nedotčená.
- **Report filtr**: běží-li workflow, report timeline obsahuje jen události od
  court-ready artefaktů; bez review akcí backward compat (kompletní report).
- Každý přechod emituje WS událost `review.state` (F4.2 live push).
- Testy: `tests/test_f43_review.py` **25/25** (včetně 3-examinátor scénáře a live WS);
  stp041 aktualizován na v16; ruff clean.

#### F4.4 Multi-tenant RBAC — orgs/týmy/uživatelé, per-case oprávnění, SSO OIDC
- **`src/stopa/domain/multitenant.py`**: čistá doménová vrstva — `access_for_case()`
  (role v případě vyhrává nad globální; admin = fallback; fail-closed default),
  `map_claims()` (role z JWT claims `groups`/`roles`, nejvyšší privilegium mezi
  známými rolemi), `verify_jwt()` — **HS256** (Keycloak) a **RS256 + JWKS** (Okta);
  `alg=none` fail-closed, kontrola `exp`/`nbf`/`iat`, volitelně `iss`/audience;
  RS256 = RSA-PKCS1v15(SHA256) přes existující `cryptography 50.0.2` (bez nové závislosti);
  JWKS fetch injektovatelný pro offline testy.
- **Schéma v16 → v17**: `_SCHEMA_CORE` + `MULTITENANT_DDL` — tabulky `orgs`, `teams`,
  `users`, `case_members` (+ stub `cases(id)` pro instance DB); idempotentní legacy migrace.
- **`UserRepository`** (nový): CRUD orgs/týmů/uživatelé/členství, deterministické ID,
  `user_memberships()` + `member_case_ids()`, `_ensure_case()` (FK na case-*.db ID).
- **Web vrstva**: instance DB `stopa_instance.db`; session tokeny HMAC-SHA256 `body.sig`
  (TTL 12 h, fail-closed), header `X-Stopa-Token`; `_require(..., case_id=...)` — v case
  kontextu členství vyhrává + fail-closed 403; legacy režim (bez uživatelů) = settings role.
- **Endpointy**: `/auth/login` (SSO id_token XOR username), `/auth/me` (+ členství),
  CRUD `/api/orgs|teams|users`, per-case `POST/DELETE/GET /api/cases/{id}/members`,
  audit `?actor=`, settings + `multi_user_mode`/`user`. Nové oprávnění `settings.read`.
- **Fail-closed**: bez tokenu 401; nečlen bez admin role 403 i na read; unknown role v
  grantu → 400 + CHECK constraint; smazání case kaskádně odstraní členství.
- Testy: `tests/test_f44_multitenant.py` — **permission matrix 60 scénářů (≥ AK 50)**,
  skupiny L/M/A/B/C/D/E/F/G včetně RS256 přes JWKS hook a audit per user; stp041 na v17;
  db.py 599 řádků (budget <600); ruff clean.

#### F4.5 Case sharing & collaboration — komentáře, @mentions, notifikace
- **`src/stopa/domain/collab.py`**: čistá doménová vrstva — `parse_mentions()`
  (e-mail `x@y.z` mention netvoří; deduplikace v pořadí prvního výskytu),
  `validate_comment_body()` (strip, max 4000 znaků), `case_access_level()` —
  read/write úroveň sdílení přes F4.4 `access_for_case`: examiner/admin → write,
  analyst → read, bez přístupu None (fail-closed).
- **Schéma v17 → v18**: `COLLAB_DDL` pro case DB — `artifact_comments`
  (FK ON DELETE CASCADE na artefakt, CHECK délky, `mentions_json`, `revision`
  pro optimistic locking) + `notifications` (inbox per uživatel); idempotentní
  legacy migrace do starých case DB. Instance DB zůstává na MULTITENANT_DDL.
- **`CollabRepository`** (nový): CRUD komentářů — editace bumpne `revision`,
  mismatch `expected_revision` → ValueError (**konflikt = HTTP 409**) — a
  notifikace (unread, mark_read, mark_all_read).
- **Web API**: `POST/GET /api/cases/{id}/artifacts/{aid}/comments`;
  `PUT/DELETE .../comments/{cid}` (jen autor → jinak 403); `GET .../sharing`
  (členové + read/write úroveň); inbox `GET/POST .../notifications`.
  Nové oprávnění `comment.post` (examiner/admin — píše jen write-úroveň).
- **Notifikace**: grant členství → „případ sdílen s vámi"; @mention → in-app +
  e-mail pro každého zmíněného existujícího uživatele; `create_app(mail_backend=)`
  injektovatelný transport, selhání mailu API cestu nerozbije (graceful degradation).
- **Real-time**: WS push `comment.new`/`comment.updated`/`comment.deleted` na téma case.
- Testy: `tests/test_f45_collab.py` **33/33** (doména, repozitář, E2E — SSO HS256,
  read/write tokéní, mention filtr, konflikt 409, live WS, mail backend); stp041 na v18;
  db.py 599 řádků (budget <600); ruff clean.

#### K2.1 Bitcoin Core wallet.dat parser — čistě Python BDB btree čtečka
- **`src/stopa/domain/crypto/bdb.py`** — nová doménová vrstva, **čistě Python bez nové
  runtime závislosti** (jen stdlib `struct`, žádné I/O): BDB btree reader dle
  `db_page.h` libdb **5.3.21 i 4.8.30** (`DB_BTREEMAGIC=0x053162` @offset 12 meta
  stránky, `DB_BTREEVERSION=9` — konstanty identické v obou verzích → parser pokrývá
  staré wallet.dat). PAGE header přesně 26 B + u16 index tabulka; leaf/internal/overflow
  walk; item type: **1=B_KEYDATA** (data @off+3), **3=B_OVERFLOW** (řetězec overflow
  stránek). API: `is_bdb_btree(data)` levný gate, `parse_bdb_btree(bytes) -> list[(key,value)]`
  v pořadí stromu; jakákoli strukturní nekonzistence → `BdbError` (defenzivně).
- **Doménový model** `BitcoinCoreWallet` + `parse_bitcoin_core_wallet` (`wallets.py`):
  klíčové vzory CWallet::Load* — `name:<addr>`→label, `tx<32B txid>`→CTxOutRef,
  **přítomnost `crypted_key` = šifrovaná peněženka** (warning), `walletversion`,
  `bestblock`; heuristika CKey jen count (PII guard — raw klíče se do DB neukládají).
- **Pipeline** (`crypto_extract.py`): větev před K1 content scan, detekce podle obsahu
  (magic) ne názvu souboru; limit `CRYPTO_BDB_MAX_BYTES=64 MB`; artefakt `crypto_wallet`,
  confidence **0.95**, `details["bitcoin_core"]` = encrypted/wallet_version/best_block/
  private_key_count + labely a txids se stropy.
- Fixture: C generátor libdb-5.3 → `tests/data/wallet_{small,big}.dat`; cross-validace
  Python parser vs C cursor dump = byte-for-byte match. **PITFALL:** logické DB jméno
  při `db->open` = NULL; PyPI `bdb` = stdlib breakpoint debugger, ne BerkeleyDB.
- Testy: `tests/test_k21_wallet_dat.py` **21/21**; suite **3183 passed / 1 skipped** (+21); ruff clean.

#### K3 On-chain offline-first analýza — clustering, graf transakcí, risk scoring
- **Bundlované sankční listy** `src/stopa/domain/crypto/data/sanctions_{ofac,eu}.json` —
  OFAC **44 záznamů** (Tornado Cash CYBER 2022-08-08: mixer×32 ETH; Garantex + cyber BTC) a
  EU **6 záznamů** (269/2014 konsolidovaný text, entry 541 Garantex: BTC×3+ETH+BSC+TRX);
  všechny ověřeny proti primárním zdrojům (`ofac.treasury.gov/recent-actions/*`, EUR-Lex).
- **`domain/crypto/onchain_models.py`** — Pydantic v2 modely (`TxRecord`/`Cluster`/`RiskScore`…);
  částky v minimálních jednotkách (BTC=sats, ETH=wei); normalizace: ETH/BSC hex → lowercase
  (EIP-55 je checksum, ne formát adresy), base58/bech32 literálně.
- **K3.2 `clustering.py`** — deterministické common-input union-find + change-detection
  (residual rule: výstup == total_in − ostatní výstupy; ≥2 různé výstupní adresy; refund
  input→output téže tx vyloučen); důkazy pod stabilním klíčem (nejmenší adresa tx — union kořen
  se může změnit) a strop **50 txids**.
- **K3.3 `tx_graph.py`** — přesné node stats + poměrný model částek hran
  (`share = output.amount * input.amount / total_in`; jediný vstup = plná částka); DFS detekce
  cyklů s kanonizací rotací (lex. nejmenší adresa první → dedup z více startů) + explicitní
  self-loopy; omezené cesty `expand_paths` (depth); Mermaid/JSON export.
- **K3.4 `risk_scoring.py`** — deterministická tabulka: bez shody **0/none**, exchange/individual
  **95/high**, mixer/darknet_market **100/critical**; více shod → max skóre + důvody z obou listů;
  lazy `lru_cache` loader.
- **K3.1 `onchain_api.py`** — Blockchair/Etherscan klienti **jen opt-in** (explicitní API klíč);
  injektovatelný transport → plně offline testy; defenzivní normalizace wire schémat
  (nedict items skip, ISO-8601→epoch); `TxCache` JSON schema v1 s atomickým zápisem (tmp+rename),
  poškozená cache/neodpovídající schema → `{}` + `last_error` (graceful degradation).
- **CLI** `stopa onchain <case> [--api-key KEY] [--etherscan-key KEY] [--no-network]
  [--depth N] [--json]` — adresy z crypto artefaktů případu; síť opt-in, jinak cache + listy.
- Testy: `tests/test_k3_onchain.py` **97/97** (unit všech 5 modulů + parametrizovaný smoke všech
  bundlovaných záznamů OFAC/EU + CLI E2E human/JSON/prázdný case); suite **3280 passed / 1 skipped** (+97); ruff clean.

#### K4 Dark Web & Reporting — ransom note, marketplace, mixer, fund flow, SWGDE report
- **`domain/crypto/darkweb.py`** (nová) — K4.1 ransom note detector: 7 rodin (LockBit, Conti, REvil,
  DarkSide, BlackMatter, WannaCry, Petya/GoldenEye), částky BTC/USD, deadline, adresy; deterministické
  skórování + tiebreak (lexikograficky první). K4.2 marketplace extractor: PGP bloky, vendor/product/escrow
  termíny; pravidlo „PGP + validní adresa“ se počítá i bez skóre ≥ 4. K4.3 mixer detekce: CoinJoin heuristika
  (`n_in ≥ 8` a `n_out ≥ max(2, n_in//2)`), bundlované mixer adresy z OFAC/EU list (tagy), textové zmínky;
  důvody s txid + počty. Extrakce adres reusing K1 pattern z `artifacts/crypto_extract.py`
  (token regex + `validate_address`) → směr závislosti domain ← artifacts zachován.
- **`domain/crypto/fund_flow.py`** (nová) — K4.4 fund flow diagram: D3-kompatibilní JSON + self-contained
  HTML/SVG **bez CDN**; deterministický kruh seřazený `(-out_amount, id)`; kategorie uzlu prioritou
  mixer > darknet_market > exchange; **KPI render < 5 s pro 1000 TX** ověřeno testem (naměřeno ms).
- **`presentation/crypto_report.py`** (nová) — K4.5 SWGDE-kompatibilní report: 10 sekcí, formáty `md|html|json`;
  Ed25519 podpis + SHA-256 dle legal_docs konvencí (`db.ensure_integrity_key()` + `integrity.sign_hash`),
  graceful degradation bez kryptobackendu (podpis None, digest zůstává); částky v minimálních jednotkách.
- **CLI**: `stopa darkweb <case> [--file PATH …] [--json]` — sken textových zdrojů případu
  (.txt/.md/.log/.html/.htm/.csv ≤ 4 MB) + K3 TxCache; `stopa crypto-report <case> --format md|html|json`.
- Testy: `tests/test_k4_darkweb.py` **85/85** (unit všech modulů + CLI E2E darkweb/crypto-report human/JSON);
  suite **3365 passed / 1 skipped** (+85); ruff clean.

#### K5 Advanced — DeFi, NFT, cross-chain bridges, privacy coins, AI copilot
- **`domain/crypto/defi.py`** (nová) + registry `data/defi_protocols.json` — K5.1 DeFi detekce: 8 protokolů
  (Uniswap v2/v3, Aave, Compound, Curve, Maker/Sky, Lido, Yearn, dYdX), adresy ověřeny proti primárním
  zdrojům (oficiální deployments); skóre = 2× unikátní termín + 5× známá adresa (EIP-55 je checksum →
  porovnání case-insensitive).
- **`domain/crypto/nft.py`** (nová) + registry `data/nft_contracts.json` — K5.2 NFT tracking: sbírky
  CryptoPunks/BAYC (CryptoPunks ověřeno vs larvalabs readme), marketplaces (OpenSea/Rarible/LooksRare/Blur);
  flexibilní normalizace EVM exportů, ownership chain deterministicky `(block_number, tx_index)`,
  mint = první držitel od ZERO_ADDRESS.
- **`domain/crypto/bridges.py`** (nová) + registry `data/bridges.json` — K5.3 cross-chain bridge analýza:
  Wormhole multi-chain kontrakty (ETH/BSC/Polygon/Avalanche, ověřeno vs xdapp-book), Binance-Peg honestně
  `verified=false`; heuristika = adresa na ≥ 2 chainách bez přímého transferu (`multi_chain_presence`) +
  explicitní shoda kontraktu z registry.
- **`domain/crypto/privacy_coins.py`** (nová) — K5.4 privacy coins off-chain: XMR plnou K1 validací
  (chain MONERO; standard 95 / integrated 106 znaků), Zcash t-addr strukturovaně (`t1` + base32 body 74–80,
  checksum offline neověřen → poznámka), payment ID jen v kontextu ±80 znaků kolem monero termínu.
- **`intelligence/crypto_copilot.py`** (nová) — K5.5 AI copilot dle F3.x patternu: injektovatelné
  `llm_call(prompt) -> str`, LLM výstup = data ne autorita (strict validace risk_level), deterministický
  fallback při jakékoli chybě (práha critical_sanctions>0=critical · defi+nft+bridges≥4 nebo privacy≥5=high).
- **CLI**: `stopa advanced <case> [--file PATH …] [--json]` — sken textových zdrojů případu (konvence K4,
  ≤ 4 MB) + cross-chain analýza nad K3 TxCache; v CLI deterministický fallback.
- Testy: `tests/test_k5_advanced.py` **91/91** (registry, unit všech 5 modulů, CLI E2E human/JSON,
  determinismus end-to-end); suite **3456 passed / 1 skipped** (+91); ruff clean.

## [1.0.0] — 2026-11-10

První stabilní release. Konsoliduje celý vývoj od vývojové verze 0.1.0 (září–listopad
2026). **Žádné breaking changes** — veřejné API, CLI i DB schéma jsou nadstavbou;
DB migrace běží automaticky při otevření starších případů (v8→v14).

### Přidáno (Added)

#### Jádro a pipeline
- Unifikovaný forenzní ingest: case DB (SQLite), hashing SHA-256/MD5, signatury souborů,
  bad-extension detekce, deduplikace, hash sety, profily.
- Paralelizace ingestu (`process_source(max_workers=)`) + checkpointing `add --resume`.
- Disk images: detekce typu (E01/AFF4/RAW-DD), TSK file systems přes **pytsk3** s fallbackem
  na CLI binárky, streaming carving (mmap sliding window).
- E01/AFF4 kontejnery přes ctypes (`libewf`/`libafflib`, `STOPA_EWF_LIB`).
- Mobilní extrakce: logická (kontakty, WhatsApp, iOS Safari) + physical/FDE.

#### Forenzní formáty (FDE / šifrování)
- STOPAFDE + Android FBE (AES-256-XTS sektorová šifra) v čistém Pythonu.
- LUKS1/2 detekce a dešifrování (cryptsetup, vyžaduje root).
- Keyfile import pro FDE/FBE/LUKS (`mobile --keyfile`).
- Streaming FDE dekódování (peak RAM ~420→~17 MB na 100 MB obrazu).

#### Artefaktové extraktory (88)
- Windows: MS-LNK, MS-PREFETCH (MAM + LZXPRESS Huffman), Jump Lists, Event Log `.evtx`
  (EVTX/CHUNK i `ElfFile` varianta s BinXML deflate dekomprezi), AppCompatCache, ShimCache,
  NTFS `$UsnJrnl`.
- Registry hives (regf/regipy) + Apple plists (binární i XML).
- SQLite extraktoři: browser history, messaging (iMessage `chat.db`, Android SMS, call logy),
  iCloud Messages warrant return.
- Port AXIOM extraktorů (ETAPA B): email, WiFi, ScheduledTasks, netstat, Google Takeout,
  Chrome profily/sync, cloud SNS exporty (Instagram/Snapchat/Twitter/X/Facebook/Box/Dropbox/Mega),
  Microsoft+Amazon cloud, memory forensics.
- File metadata: PDF/OOXML/ID3v2/MP4/EXIF + porovnání (`diff_metadata`).

#### Analýza a inteligence
- Full-text search FTS5 (external-content index) + rozšířené filtry
  (`size:>1MB`, `mtime:A..B`, `ext:jpg`, hash lookup, `in-artifact:X`).
- Timeline Engine: materializovaná timeline, TZ konverze, detekce nesrovnalostí a duplikátů.
- Entity + Correlation Engine (normalizace entit, 3 korelační pravidla) + SVG entity graph GUI.
- Evidence Manager: audit log (neměnná SWGDE-style stopa), custody items, verze parserů.
- Unified Evidence Model + Lineage Engine + Parser Validation Registry.
- AI Forensic Assistant (LM Studio): 3 režimy, **100 % validace citací** proti DB,
  grounding engine (ověřování tvrzení vs data citovaných artifactů), PII redaktor.

#### Reporting a export
- Court-ready HTML/PDF reporty s chain of custody (SHA-256+MD5 manifest).
- Report rozšířen na 20 sekcí + i18n cs/en + confidence štítky [ověřeno/odvozeno/hypotéza].
- Export: CSV/JSON/JSONL/XML/**STIX 2.1** + interop formáty (Plaso `l2tcsv`, UCO mapping).
- Interop: Plaso import/export, Timesketch push (klient + UI polling status), ZIP bundle,
  plánované/periodické auto-bundle exporty (`--auto-export`).

#### Web GUI
- FastAPI backend + vanilla JS SPA bez build kroku; 47 endpointů.
- 3-pane desktop layout, File Inspector (hex dump + metadata + porovnání), partition map.
- Cmd+K FTS5 search, data grid s nekonečným scrollováním a klávesovou navigací.
- Entity Graph + Correlation sekce, AI Assistant panel, Audit Center, Diagnostics, Settings.
- RBAC (role-based access control) + role switch UI.

#### Bezpečnost a integrity
- Evidence Integrity 2.0: hash chaining, Ed25519 kontrolní body, manifesty.
- Reproducibility Engine: záznam operací, replay, porovnání výsledků.
- SHA-512 integrity vrstva + minimální RBAC + pip-audit CI.
- Parser sandbox kontrakt (izolace parserů, fix hang bugu sqlite_carver).
- Opravy path traversal (case_id validace, `_read_file_bytes` resolve+prefix check).

#### Distribuce a CLI
- **R0.2 — distributivní balíčky**: `.deb`/`.rpm`/AppImage/Docker image (<1.5 GB) + wheel/sdist;
  offline instalace přes vendored wheels (cp310–cp313), `postinst.sh` postaví venv bez sítě.
- **R0.4 — CLI UX**: `--json` na všech subpříkazách (validní JSON i error cesty),
  Rich progress bary, `--help` s příklady u každého subpříkazu.
- Nový top-level flag `stopa --version`.

### Změněno (Changed)
- DB schéma migrace v8→v14 (automatické, backward-kompatibilní).
- EVTX parser verze 1.0→1.1: ElfFile varianta už nevrací `None` v event_id/timestamp
  (ElfR walk + BinXML deflate dekomprese + timestamp z MS-EVLOG headeru).
- Rozdělení monolitu `data/db.py` na repozitáře (Case/File/Audit/Artifact/Entity) + facade.

### Opraveno (Fixed)
- Argparse crash v `timeline --path --help` (neescape `%text%`).
- Chybějící help epilog u subpříkazu `serve`.
- JSON error cesty v `analyze` (plain text narušoval validitu stdout).
- RAM peak při streamingu FDE a velkých E01.

### Bezpečnostní opravy (Security)
- Path traversal ×2 (case_id + čtení souborů ven z kořene zdroje).
- PII redaktor pro AI odpovědi; ochrana proti prompt injection v RAG.

## [0.1.0] — 2026-09/10 (vývojová)
Počáteční vývoj: case DB, ingest pipeline, SQLite extraktoři, FTS5 search, disk images,
mobilní extrakce, web GUI a court-ready reporty. Podrobnosti viz commit historie
(`git log`); od 1.0.0 se všechny změny evidují v tomto souboru.

[Unreleased]: https://github.com/Mirutomaru/stopa/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Mirutomaru/stopa/releases/tag/v1.0.0
