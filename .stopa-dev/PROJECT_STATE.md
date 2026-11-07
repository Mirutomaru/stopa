# STOPA — PROJECT STATE

## Základní údaje
- **Název projektu:** STOPA Digital Forensics (Unified Forensic Workbench)
- **Verze aplikace:** 0.1.0 (`pyproject.toml`)
- **Popis:** Python forenzní platforma pro analýzu diskových obrazů (E01/AFF4/RAW),
  extrakci artifactů, timeline, korelací entit a generování soudně použitelných reportů.
  Cíl: konkurence Magnet AXIOM / EnCase / Autopsy / X-Ways / Belkasoft.
- **Jazyk/runtime:** Python 3.10+ (venv `.venv`), FastAPI web GUI, vanilla JS SPA, SQLite FTS5.

## Aktuální architektura
Clean Architecture — 4 vrstvy:
- `src/stopa/domain/` — čistá doménová logika bez I/O (**35 modulů**, +timeline_intel)
- `src/stopa/artifacts/` — extraktory artifactů, I/O jen v entrypointech (**87 souborů**)
- `src/stopa/data/` — I/O vrstva: db.py (SQLite), TSK, libewf, image_pipeline, ingest
- `src/stopa/web/` + `cli.py` — prezentace (FastAPI 30 endpointů + CLI)
Pipeline = jediný `analyze()` s dispatchem magic signatur + name-based fallback,
ThreadPoolExecutor paralelizace, E3 resume/checkpointing.

## Aktuální fáze vývoje
**Oblast Q (Interop)** — **STP-059 DOKONČEN ★★ = Timesketch push hotový** (`data/timesketch_client.py` 253 ř. — HTTP klient po vzoru `LmStudioClient` s injektovatelným transportem: login flow s CSRF scrapem (`input#csrf_token`, fallback `<meta name="csrf-token">`), `create_sketch()` POST `/api/v1/sketches/` → 201 (ID z `objects[0].id`), `upload_timeline()` multipart `/api/v1/upload/` → `{timeline_id, task_id}`, `health()`, výjimky `TimesketchError`/`TimesketchUnavailable`, env override `STOPA_TIMESKETCH_URL/USER/PASSWORD`; `domain/timesketch_push.py` 83 ř. — čistá logika s injektovatelným klientem (`Protocol`), reuse `to_l2tcsv` + timeline records, název sketchu `STOPA <case> — <what>`, souhrn `{sketch_id, timeline_id, task_id, records}` pro audit bez přístupových údajů; CLI `stopa timesketch-push <case> --what artifacts|timeline|correlations`; web endpoint `POST /api/cases/{id}/timesketch-push` — RBAC `analysis.run`, 400 neplatný dataset, 503 nedostupná, 502 selhání pushu, audit log `timesketch_pushed` + integrity checkpoint; **oprava reálného bugu:** web `create_case` generuje Ed25519 klíč (dříve checkpointy ticho propadaly); 20 nových testů, full suite **2048 passed, 1 skipped**). Předtím: **Oblast O (User Interface) / Q (Interop)** — **STP-058 DOKONČEN ★ = Interop Export Center UI hotový** (`web/app.py` — endpoint `GET /api/cases/{id}/interop-export?what=&format=`: `what ∈ {artifacts, timeline, correlations}` × `format ∈ {csv, json, jsonl, xml, stix, uco, l2tcsv}`, dispatch na domain konvertory `to_csv`/`json.dumps`/`to_jsonl`/`to_xml`/`to_stix_bundle`/`to_uco_json`/`to_l2tcsv`, neplatný parametr → 400, download s Content-Disposition; každý export → audit log `interop_exported` + integrity checkpoint `interop-export`; SPA modul `js/components/interop.js` — sekce mod-interop s živými počty datasetů, výběrem datasetu × formátu, tlačítkem Stáhnout a tabulkou posledních 10 exportů z audit logu; registrace do sidebar.js + modules.js; 9 nových testů, full suite **2028 passed, 1 skipped**). Předtím: **Oblast Q (Interop)** — **STP-057 DOKONČEN ★★ = Plaso import hotový, oblast Q kompletní** (`domain/plaso_import.py` čistá logika bez IO: `parse_l2tcsv()` — 17 pevných polí log2timeline.pl → `PlasoEvent`y s rekonstrukcí UTC času z date MM/DD/YYYY + time HH:MM:SS + timezone „Z“ (nevalidní/chybějící čas → None, bez fiktivního času), sourcetype → event_type (fallback „plaso_event“), extra JSON → details = plná věrnost dat exportu STOPA, confidence ∈ [0,1], notes → anomaly flags; `import_l2tcsv()` — evidence source kind="file" + idempotentní upsert artifactů + timeline events pro řádky s časem (ts_origin="source"); CLI `stopa plaso-import <case_id> SOUBOR` s audit logem a Ed25519 kontrolním bodem; 14 nových testů, full suite **2019 passed, 1 skipped**). Předtím: **Oblast J (Case Management)** — **STP-056 DOKONČEN ★ = přepínač role v Settings hotový** (`domain/rbac.py` + `ROLE_LABELS`; nový endpoint `GET /api/roles` vrací matici rolí z permission matrix; SPA: topbar badge aktuální role, Settings preview panel oprávnění s živým přepínáním, modul `js/components/role.js` fail-safe; 8 nových testů, full suite **2005 passed, 1 skipped**). Předtím: **Oblast Q (Interop)** — **STP-055 DOKONČEN ★ = UCO mapping hotový** (`domain/uco.py` čistá logika bez IO: kurátorské mapování 66/66 KNOWN_ARTIFACT_TYPES na třídy oficiální UCO ontologie `ucoProject/UCO` — 52 mapped (observable/configuration/location/identity) + 14 explicitně unmapped; `map_artifact_to_uco()`, `uco_type_label()` → `<module>:<Class>` nebo `stopa:<typ>`, `to_uco_json()` JSON-LD dokument s @context UCO, name/time podmíněnost, x-stopa-id traceability, deterministický výstup; CLI `stopa export --format uco`; 22 nových testů, full suite **1997 passed, 1 skipped**). Předtím: **Oblast K (Export Engine) / Q (Interop)** — **STP-054 DOKONČEN ★ = Plaso interop formát l2tcsv hotový** (`domain/export.py::to_l2tcsv()` — 17 pevných polí log2timeline.pl, formát ověřen proti oficiální Plaso dokumentaci; CLI `stopa export --format l2tcsv`; export engine kompletní csv/json/jsonl/xml/stix/l2tcsv; 19 nových testů, full suite **1975 passed, 1 skipped**). Předtím: **Oblast J (Case Management) / M (Security)** — **STP-053 DOKONČEN ★ = RBAC permission matrix + enforcement hotový** (`domain/rbac.py` rozšířeno o matici role analyst/examiner/admin × 8 oprávnění, `can()` fail-closed, `require_permission()` → RBACDenied; `web/app.py` — `_require()` na mutující endpointy: case CRUD, sources, timeline/correlate/AI, file flag, PUT settings + validace role → 400; GET settings vrací `permissions`; default = examiner; bez auth vrstvy = operační guardrail; 29 nových testů, full suite **1956 passed, 1 skipped**). Předtím: **Oblast O (User Interface)** — **STP-052 DOKONČEN ★ = Audit Center hotový** (endpoint `GET /api/cases/{id}/audit` agreguje C4 integrity vrstvu: SHA-512 hash chain verifikace + Ed25519 kontrolní body s nezávislým ověřením podpisů + audit záznamy; SPA modul `mod-audit` s chain status badge, kontrolními body verified/invalid a tabulkou záznamů; 8 nových testů včetně tampering E2E — UPDATE detailu blokován append-only triggerem, po dropu odhalí chain broken index; full suite **1927 passed, 1 skipped**). Předtím: **Oblast G (File Intelligence)** — **STP-051 DOKONČEN ★** (`domain/file_preview.py` magic bytes klasifikace + `GET /api/files/{fid}/preview` inline media/text preview v inspectoru; 18 testů, full suite 1919 passed). Předtím: **Oblast I+O (Validation Center UI)** — **STP-050 DOKONČEN ★★** (UI Validation Center: endpointy `GET /api/cases/{id}/validation` = C6 validační report + `GET /api/validation/registry` = C3 registry, SPA modul `mod-validation` s coverage bar a per-artifact tabulkou; 10 nových testů, full suite **1901 passed, 1 skipped**). Předtím: **Oblast H (AI Copilot)** — **ETAPA H DOKONČENA ★★** (STP-049 = AI grounding + detekce rozporů mezi odpovědí LLM a daty citací: `domain/ai_grounding.py` čistá logika bez IO, zapojení do všech 3 AI režimů web endpointu — pole `grounding` v odpovědi, GUI ⚠ štítky citací + findings panel; 41 nových testů). Další oblast podle priority: K Export Engine (Plaso) / Q Interop. Předtím: **ETAPA E DOKONČENA ★★** (STP-046/047/048 = sandbox kontrakt + zapojení do pipeline + fix reálného hang bugu + E2E testy + dokumentace `docs/STOPA_SANDBOX.md`). Vlny ETAPY E: **vlna 1 ✅ STP-046** → **vlna 2 ✅ STP-047** → **vlna 3 ✅ STP-048** (testy + dokumentace = ETAPA E dokončena ★★). Předtím: **STP-045 hotový = ETAPA E ZAHÁJENA ★** (volba směru: audit kandidátů M/H/I+O; reálný hang prokázán — poškozený SQLite soubor visí >15 s v `sqlite_carver.recover_rows`; ROZHODNUTÍ = oblast M Security izolace parserů). Předtím: **STP-044 hotový = ETAPA D vlna 2 DOKONČENA ★ = CELÁ ETAPA D DOKONČENA ★★** (testy + dokumentace CI benchmark jobu: `tests/test_stp044_ci_benchmark_e2e.py` — **6 E2E subprocess testů** spouštějících `scripts/ci_benchmark.py` jako skutečný subprocess (první běh bez baseline, `--update-baseline`, běh proti vlastní baseline, umělá regrese → exit 1 + REGRESIE na stderr, poškozená baseline → exit 2, artifact výstup); nová dokumentace **`docs/STOPA_BENCHMARKS.md`** (workflow baseline update, prahy a proč — relativní 20 % + absolutní guard 0.5 ms, jak číst report/artifact, ukázkové hodnoty); README odkaz na benchmark docs; full suite **1813 passed, 1 skipped**). Předtím: **STP-043 hotový = ETAPA D vlna 1 DOKONČENA ★** (CI benchmark job proti baseline: `scripts/ci_benchmark.py` spustí engine suite=all / 77 položek, porovnání s versionovanou baseline přes domain API `detect_regressions(threshold=0.20)`, **CI noise guard** `--min-delta-ms 0.5` proti falešným pozitivním na sub-ms položkách; nový CI job `benchmark` v `.github/workflows/ci.yml` (needs lint+test, artifact upload, fail na regresi); inicializován artefakt `benchmarks/baseline.json`; full suite **1807 passed, 1 skipped**). Předtím: **STP-042 hotový = ETAPA D ZAHÁJENA ★** (volba směru + synchronizace roadmapy: audit reálného stavu všech kandidátských oblastí v kódu — **P QA**: benchmark engine hotový (`domain/benchmark.py` 95 ř. + `data/benchmark_engine.py` 267 ř., CLI `stopa benchmark`, detekce regresí >20 %), CI má lint+test+security ale benchmark chybí, baseline neexistuje; **M Security**: sandbox parserů neexistuje; **H AI Copilot**: citace existují, detekce rozporů chybí; **I+O Validation/Audit Center UI**: registry existuje, UI moduly chybí; **G/J/K/Q**: částečně/neexistují. **ROZHODNUTÍ: ETAPA D = oblast P (CI běh benchmarku proti baseline)** — jediný zbývající P1 úkol, nejmenší rozsah s největším dopadem; vlny 1–2 = STP-043/044). Předtím: **STP-041 hotový = ETAPA C vlna 3 DOKONČENA ★ = CELÁ ETAPA C DOKONČENA ★★** (finální rozklad monolitu `db.py`: vyčleněny **schema.py** a **migrations.py**; facade úklid; `db.py` 1011 → **476 řádků**; celkem ETAPA C: ~2090 → 476 = **−77 %**; full suite **1792 passed, 1 skipped**). Předtím: **STP-040 hotový = ETAPA C vlna 2 DOKONČENA ★** (vyčleněny **ArtifactRepository** + **EntityRepository**; `db.py` 1565 → 1011 řádků; full suite **1774 passed, 1 skipped**). Předtím: **STP-039 hotový = ETAPA C vlna 1 DOKONČENA ★** (vyčleněny **CaseRepository** + **FileRepository** + **AuditRepository**, sdílené konverze do `_helpers.py`; `db.py` 2090 → 1565 řádků; full suite **1757 passed, 1 skipped**). Předtím: **STP-038 hotový = ETAPA C ZAHÁJENA ★** (volba směru + synchronizace roadmapy: audit reálného stavu všech oblastí A–Q v kódu, oprava zastaralých „Nedokončeno" položek — E Timeline Intel 2.0 ✓ STP-018, L report **20 sekcí** ✓ STP-020, H PII redactor ✓ STP-019, J RBAC ✓ STP-022, K/Q STIX+JSONL/XML ✓ STP-023, N/O stream parsing + Processing Monitor ✓ STP-021; **ROZHODNUTÍ: ETAPA C = rozdělení monolitu `db.py` (~2090 ř., 67 metod) na doménová repozitáře** — vlny 1–3 = STP-039/040/041). Předtím: **STP-037 hotový = ETAPA B DOKONČENA... [truncated]
6 nových parserů / 19 AXIOM typů → NOT_SUPPORTED celkem **0 ★**; `_sns_prepass()` rozšířen o 6 vlna-14 detektorů). Předtím: **STP-035 ETAPA B vlna 13** (cloud-export Google II + Box/Dropbox/Mega,
4 nové parsery / 9 AXIOM typů + 11 čistých flipů; `_sns_prepass()` rozšířen o vlnu 13 detektory). Předtím: **STP-034 ETAPA B vlna 12** (cloud-export Microsoft + Amazon,
8 parserů / 12 AXIOM typů; `_sns_prepass()` rozšířen o 8 MS+Amazon detektorů bez kolizí). Předtím: **STP-033 ETAPA B vlna 11** (cloud SNS exporty — Twitter/X + Facebook warrant return,
4 parsery / 13 AXIOM typů; `_sns_prepass()` rozšířen o 4 detektory bez kolizí),
**STP-032 ETAPA B vlna 10** (cloud SNS exporty — Instagram/Snapchat warrant return, nový
`_sns_prepass()` na celé cestě PŘED basename chainem),
**STP-031 ETAPA B vlna 9** (memory forensics — procesy/spojení/handlery/moduly/hooks),
**STP-030 ETAPA B vlna 8** (Chrome prefs/sync + cloud Drive soubory + Google Voice WR + Windows drivers),
**STP-029 ETAPA B vlna 7** (Chrome Bookmarks/History/Autofill + Contacts + Skype WR),
**STP-028 ETAPA B vlna 6** (Google local profile/takeout + přílohy),
**STP-027 ETAPA B vlna 5** (Google Takeout rodina + Samsung voice),
**STP-026 ETAPA B vlna 4** (portable-local AXIOM porty),
**STP-023 Export JSONL/XML/STIX** (oblast K/Q),
**STP-022 Security: SHA-512 + RBAC minimální + pip-audit CI** (oblast M, P2),
**STP-021 stream parsing velkých E01 + web Processing Monitor**,
**STP-019 AI governance + PII redaktor**, **STP-020 Report engine 9→20 sekcí**,
**STP-018 Timeline Intelligence 2.0** a **ETAPA B vlny 1–3 hotové**.
Coverage matice: covered **198 / 232** unikátních typů; portable-local NOT_SUPPORTED = **0 ★**; memory NOT_SUPPORTED = **0 ★** (vyzerovala vlnou 9); cloud-export NOT_SUPPORTED = **0 ★** (vyčerpáno vlnou 14 — celá kategorie dokončena).

## Celkový stav projektu
Stabilní — plná test suite zelená, ruff clean, deterministická coverage matice.

| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **49** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **0** (všechny STP-001..049 DONE; ETAPA H dokončena ★★ — další oblast = I+O Validation Center UI) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-049 — ETAPA H vlna 1–3: AI Copilot grounding = ETAPA H DOKONČENA ★★** (oblast H, P2)
První konkrétní realizace úrovně I5 pro existující E11 režimy. **(A)** `src/stopa/domain/ai_grounding.py` (nový, čistá logika bez IO): `extract_claims()` extrahuje tvrdění z odpovědi LLM (ISO + česká data, slovník 62 typů artifactů), `ground_answer(text, citations, artifacts_by_id)` → deterministický `GroundingReport` s třemi kategoriemi rozporu (`mismatch_date`, `mismatch_type`, `unverified_claim`) + `.verified_citations`; atribuce tvrdění k nejbližší citaci (vzdálenost znaků). **(B)** Zapojení do web endpointu: `_ground_answer_safe()` v `web/app.py` — všechny tři režimy (`nl_search`/`summary`/`explain`) vracejí pole `grounding`; GUI ⚠ štítky citací s rozporu + findings panel. **(C)** 41 nových testů (33 domain offline + 8 web E2E přes TestClient) + dokumentace `docs/STOPA_AI_ARCHITECTURE.md` §1.1. Full suite **1891 passed, 1 skipped** (+41), ruff clean.
Předtím: STP-048 (ETAPA E vlna 3 — sandbox E2E testy + corrupt-file regression EVTX/LNK + dokumentace `docs/STOPA_SANDBOX.md`; ETAPA E DOKONČENA ★★, `5965cb4`),
STP-047 (ETAPA E vlna 2 — zapojení sandboxu do pipeline + fix reálného hang bugu `sqlite_carver`; ETAPA E vlna 2 hotová ★, `3fc2dac`),
STP-046 (ETAPA E vlna 1 — parser sandbox kontrakt `domain/sandbox.py` + worker modul; ETAPA E vlna 1 hotová ★, `91854d8`),
STP-044 (ETAPA D vlna 2 — testy + dokumentace CI benchmark jobu; CELÁ ETAPA D DOKONČENA ★★, `ca93d58`),
STP-043 (ETAPA D vlna 1 — CI benchmark job proti baseline, `0136e91`),
STP-042 (volba ETAPY D + synchronizace roadmapy — ETAPA D ZAHÁJENA ★, `d87a677`),
STP-041 (ETAPA C vlna 3 — schema/migrations moduly + facade úklid; CELÁ ETAPA C DOKONČENA ★★, `824755d`),
STP-040 (ETAPA C vlna 2 — Artifact/Entity repozitáře, `28b6222`),
STP-039 (ETAPA C vlna 1 — Case/File/Audit repozitáře, `58628a9`),
STP-038 (ETAPA C volba směru + synchronizace roadmapy — ETAPA C ZAHÁJENA ★, `1292e72`),
STP-037 (ETAPA B vlna 15 závěrečný audit — ETAPA B dokončena ★, `166e42e`),
STP-036 (vlna 14 dokončení cloud-export kategorie, `496391b`),
STP-035 (vlna 13 cloud-export Google II + Box/Dropbox/Mega, `31bceb2`),
STP-034 (vlna 12 cloud-export Microsoft + Amazon, `47e7103`),
STP-033 (vlna 11 cloud SNS Twitter/X + Facebook WR, `bea2a25`),
STP-032 (vlna 10 cloud SNS Instagram/Snapchat WR, `da83a6f`),
STP-031 (vlna 9 memory forensics, `4747738`),
STP-030 (vlna 8 Chrome prefs/sync + cloud Drive soubory + Google Voice WR + Windows drivers, `1a3e007`),
STP-029 (vlna 7 Chrome Bookmarks/History/Autofill + Contacts + Skype WR, `5e47850`), STP-028 (vlna 6 Google local profile/takeout + přílohy, `9ffde5b`),
STP-027 (vlna 5 Google Takeout rodina + Samsung voice, `b786064`),
STP-026 (vlna 4 portable-local porty, `cd932e1`),
STP-023 (Export JSONL/XML/STIX, `210c370`),
STP-022 (Security SHA-512 + RBAC + pip-audit CI, `9707cd8`),
STP-021 (stream parsing E01 + Processing Monitor, `e0c34b3`),
STP-019 (AI governance + PII redaktor, `6d74ab3`), STP-020 (report engine 9→20 sekcí, `7360bab`),
STP-018 (Timeline Intel 2.0, `cd5aa25`), STP-017 (vlna 3), STP-016 (vlna 2), STP-012c (`2549ce6`),
STP-012b, STP-012 (`e227929`), STP-013..015 (vlna 1, `afc49a0`).

## Aktuální úkol
Žádný aktivní — **ETAPA H dokončena ★★** (STP-049); čeká na start další oblasti.

## Nejbližší následující úkol
**Oblast I+O — Validation Center UI** (P2). C3 Parser Validation Registry existuje; chybí UI modul pro zobrazení validačních reportů per-artifact + audit center. Další po I+O: G File Intelligence → J Case Management 2.0 → K Export Engine (Plaso) → Q Interoperability (UCO/STIX).

## Poslední úspěšné testování
- **2026-11-06:** `.venv/bin/python -m pytest -q` → **1891 passed, 1 skipped** (~47s) — po STP-049 ETAPA H (+41 testů: `test_stp049_grounding.py` 33 domain + `test_stp049_grounding_e2e.py` 8 web E2E; AI grounding zapojen do všech 3 AI režimů); ruff clean
- **2026-11-06:** `.venv/bin/python -m pytest -q` → **1850 passed, 1 skipped** (~46s) — po STP-048 vlna 3 (+4 E2E testy `test_stp048_sandbox_e2e.py`; hangující parser přes celou pipeline + corrupt EVTX/LNK regression); ruff clean
- **2026-11-06:** `.venv/bin/python -m pytest -q` → **1846 passed, 1 skipped** (~45s) — po STP-047 vlna 2 (+12 testů; sandbox zapojen do pipeline + fix hang bugu `sqlite_carver`)
- **2026-11-05:** `.venv/bin/python -m pytest -q` → **1834 passed, 1 skipped** (~20s) — po STP-046 vlna 1 (+21 testů `test_stp046_sandbox.py`; E2E přes reálný subprocess: timeout/crash/bad_payload/truncated)
- **2026-11-05:** `.venv/bin/python -m pytest -q` → **1813 passed, 1 skipped** (~19s) — po STP-045 (volba ETAPY E = docs); empirický probe prokázal reálný hang `sqlite_carver.recover_rows` na poškozeném souboru (>15 s)
- **2026-11-04:** `.venv/bin/python -m pytest -q` → **1813 passed, 1 skipped** (~19s) — po STP-044 vlna 2 (+6 E2E testů `test_stp044_ci_benchmark_e2e.py`)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!
- Coverage matice deterministická (SHA-256 diff ✓), covered **198 / 232 ★**, portable-local NOT_SUPPORTED = **0 ★**, cloud-export NOT_SUPPORTED = **0 ★**

## Známé kritické problémy
Žádné blokující. Technický dluh viz `docs/STOPA_TECHNICAL_AUDIT.md`:
- ~~`db.py` monolit~~ — **vyřešeno v ETAPĚ C (STP-039/040/041)**: 2090 → **476 řádků** (−77 %); `CaseDB` = tenký agregátor 5 repozitářů + `schema.py` + `migrations.py`
- izolace parserů (sandbox) — **ETAPA E DOKONČENA ★★ (STP-046/047/048)**: kontrakt `domain/sandbox.py` + worker modul + zapojení do pipeline (`_run_extractor`) + fix hang bugu + E2E testy + dokumentace `docs/STOPA_SANDBOX.md`
- ~~**Reálný hang bug (nalezen v auditu STP-045):**~~ `sqlite_carver.recover_rows` — poškozený SQLite soubor s garbage `db_size_pages` (1.7 mld. stránek v 920 B) → smyčka visela >15 s; **vyřešeno ve vlně 2 (STP-047)** + sandbox timeout jako druhá ochrana

## Datum poslední aktualizace
**2026-11-06** — po dokončení STP-049 (**ETAPA H DOKONČENA ★★**; AI Copilot grounding: `domain/ai_grounding.py` + zapojení do všech 3 AI režimů web endpointu (pole `grounding`) + GUI ⚠ štítky citací a findings panel, full suite **1891 passed, 1 skipped**, ruff clean).
