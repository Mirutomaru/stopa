# STOPA — Technický audit (FÁZE 1, MASTER PROMPT)

**Datum:** 2026-11-02 · **Commit:** `2244d95` · **Základní zadání:** `udelej.md` (master prompt)
**Metoda:** každé tvrzení ověřeno zdrojovým kódem, testem nebo živým spuštěním — ne deklarací.

## 0. Baseline (nezávisle ověřeno)

| Metrika | Hodnota | Důkaz |
|---|---|---|
| Testy | **819 passed, 1 skipped** (48 test souborů) | `.venv/bin/python -m pytest -q` |
| Ruff | clean | `ruff check src/stopa tests` → All checks passed! |
| SCHEMA_VERSION | **11** | `data/db.py:29` |
| Řádků src / tests | 17 032 / 11 308 | `wc -l` |
| Moduly | domain 32 souborů (5 832 ř.), data 13 (4 007), artifacts 14 (3 146), web 2 (1 016), intelligence 5 (878), presentation 2 (239) | `find`/`wc -l` |
| CLI příkazy | **21** (case new, add, files, stats, search, timeline, correlate, image, mobile, profiles, report, export, verify, integrity, replay, benchmark, validate, analyze, audit, backup, serve) | `cli.py` |
| Web endpointy | **30** (`@app.get`) | `web/app.py` |
| Magic signatur | **25** | `domain/signatures.py` |
| Parsery s verzí | **12** (imessage_cloud, mobile_extract, plist_extract, registry_extract, sqlite_extract, win_amcache, win_eventlog, win_jumplist, win_lnk v2.0, win_prefetch, win_shimcache, win_usn) | `artifacts/*.py` |
| C3 Parser Validation Registry | **9 parserů** registrováno + 1:1 sync s pipeline (RegistryError při nesouladu) | `domain/validation_registry.py`, živý import |
| E01/AFF4 (libewf) | **dostupná** | `ewf_container.ewf_available() → True` |
| The Sleuth Kit | **dostupný** (pytsk3 primární, CLI fallback) | `data/tsk.py TSK_AVAILABLE → True` |
| Závislosti | povinné: pydantic, regipy; volitelné: weasyprint (PDF), fastapi/uvicorn/httpx (web), cryptography (FDE), pytsk3 (TSK), openpyxl (XLSX), Pillow (EXIF) | `pyproject.toml` |
| Test fixtures | 29 MB, plně offline | `du -sh tests/` |

### Architektura (Clean Architecture — drží se)

```
src/stopa/
├── models.py            # Pydantic v2 boundary modely (Artifact, FileRecord, …)
├── domain/              # 32 modulů — čistá logika bez IO (offline testovatelné)
│   ├── signatures, bad_extension, dedupe, hashing, profiles, times, i18n
│   ├── image_types, carving, sqlite_parser/carver/formatter/recover
│   ├── fde, fde_fbe, fde_luks, file_meta, correlation, entities, entity_resolution
│   ├── timeline_anomaly, report, export, ai_assistant
│   └── P0 Core: evidence_model, lineage, validation_registry, integrity, reproducibility, benchmark
├── artifacts/           # 14 extraktorů (IO jen v entrypointech) — viz §2
├── data/                # IO vrstva: db (schema v11), ingest, tsk/tsk_cli/tsk_py,
│                        # image_pipeline, ewf_container, lmstudio_client, diagnostics, benchmark_engine
├── intelligence/        # P0 I1 AI orchestrace (5 agentů) + I2 Forensic RAG (3 vrstvy)
├── pipeline.py          # jediný analyze() entrypoint: ARTIFACT_EXTRACTORS (magic) + NAME_BASED_EXTRACTORS fallback, ThreadPoolExecutor, E3 resume/checkpointing
├── cli.py               # argparse subpříkazy (21)
└── web/                 # FastAPI (30 endpointů) + vanilla JS SPA (~2 000 LOC, dark mode)
```

**Databázové schéma:** SQLite, `SCHEMA_VERSION = 11`, tabulky: cases, sources, files (+FTS5), artifacts (+FTS5), timeline_events, entities (CHECK confidence v4 úrovních), correlations (first_seen/last_seen), meta, evidence_marks, audit_log (append-only triggery), custody_items, lineage_events, analysis_operations, integrity_checkpoints. Migrační mechanismus: idempotentní `CREATE TABLE IF NOT EXISTS` + verziované migrace (`_migrate_entity_resolution()` v10→v11 s rebuildem tabulek pro změnu CHECK constraintů).

---

## 1. Architektura a moduly

**Současný stav:** Clean Architecture se striktním oddělením domain (bez IO) / artifacts (IO jen entrypointy) / data (IO vrstva) / web+cli (presentační). Pipeline je jediný analyze() entrypoint s dispatchem signatura→extraktor a name-based fallbackem.

**Funguje:** závislosti tečou jedním směrem; domain testovatelný 100% offline; C3 registry vynucuje 1:1 synchronizaci parserů mezi pipeline a validačním registrem (RegistryError při driftu).

**Neúplné / dluh:**
- `domain/` má 5 832 řádků v 32 modulech — největší modul je `db.py` (data vrstva, ~1 900 ř.) s migracemi i dotazy; při dalším růstu rozdělit na `migrations.py`.
- Web SPA (~2 000 LOC vanilla JS) bez build kroku a bez testů UI logiky (jen API testy přes TestClient).

**Rizika:** nízká. **Doporučení:** db.py rozdělit při příští změně schématu; pro UI přidat minimálně smoke testy (Playwright volitelně). **Priorita:** P2.

## 2. Artifact Engine (parsery)

**Současný stav — implementováno a otestováno (14 souborů, 12 verzovaných parserů):**

| Parser | Typy artifactů | Platforma |
|---|---|---|
| win_lnk v2.0 | shell_link (+metadata, cíle) | Windows |
| win_prefetch | app_execution (spuštění aplikací) | Windows |
| win_jumplist | jump_list (nedávné soubory/aplikace) | Windows |
| win_eventlog | event_log_entry (EVTX binární parser) | Windows |
| win_amcache | amcache (AppCompatCache) | Windows |
| win_shimcache | shimcache (SRUM-like) | Windows |
| win_usn | usn_journal (USN Journal NTFS) | Windows |
| registry_extract | registry_hive (+Amcache/ShimCache detekce), regipy | Windows |
| plist_extract | property_list, plist_date | macOS |
| sqlite_extract | browser_history (Chrome/Firefox), imessage, sms_message, call_log, contact, whatsapp_message, sqlite_database | multi |
| imessage_cloud | iCloud Messages export (CSV/XLSX warrant return) | iOS cloud |
| mobile_extract | mobilní logical exporty | Android/iOS |

**Funguje:** každý parser má PARSER_VERSION, testovací sadu, evidenci zdroje nálezu; dispatch přes 25 magic signatur + name-based fallback (AXIOM Hunter pattern); C3 registry s validací vstupů a confidence.

**Neúplné (proti FÁZE 2 master promptu):**
- **Windows chybí:** SRUM, MFT (přímo — jen přes TSK), Recycle Bin metadata, Windows Search index, Browser Downloads/Cookies/Sessions/Bookmarks (jen History), Defender logs, Scheduled Tasks, Services, UserAssist, Shellbags, Thumbnail Cache, Firewall logs, RDP artifacts, USB device history, Installed applications, Notification DB.
- **Browser:** Chrome/Firefox History ✓; Edge/Opera/Brave/Safari ✗; Downloads/Cookies/Sessions/Extensions/Autofill/Search history/Cache metadata — jen částečně (sqlite_extract pokrývá historii).
- **Linux:** systemd journal, syslog, auth logs, bash history, SSH config, cron, package manager — ✗ (jen obecný file_meta + carving).
- **macOS:** Unified Logs, FSEvents, Spotlight, Quarantine, KnowledgeC, Recent Items, Launch Agents — ✗ (jen plist).
- **Mobile/messaging:** WhatsApp/iMessage/SMS/hovory ✓; Telegram/Signal/Discord/Teams/Skype/Outlook/Thunderbird — částečně (whatsapp_message přes sqlite; ostatní čekají na port AXIOM cloud-export extraktorů).

**Dluh:** 12 parserů v C3 registry vs. 9 registrovaných — `sqlite_extract`, `imessage_cloud`, `mobile_extract` nejsou v validačním registru (fungují, ale bez C3 validace vstupů). **Rizika:** nízká (parsery jsou izolované, fail-safe try/except). **Doporučení:** portovat po skupinách podle pokryvací matice (`docs/re-axiom/AXIOM_COVERAGE.md`: 22 covered / 49 portable-local / 112 cloud-export / 15 memory / 34 base-class); doplnit chybějící parsery do C3 registry. **Priorita:** P0 (hlavní gap oproti AXIOM).

## 3. Processing pipeline a diskové obrazy

**Funguje:** E01/AFF4 přes libewf ✓, RAW/IMG přes TSK (pytsk3 primární + CLI fallback) ✓, NTFS/FAT/APFS ✓, FDE workflow (AES-256-CBC mobilní FDE, FBE, LUKS) ✓, file carving (magic bytes) ✓, volný prostor (`--carve-free`) ✓, **paralelizace** (ThreadPoolExecutor, `max_workers`) ✓, **resume/checkpointing** (E3 — přeskočí soubory už v DB) ✓.

**Neúplné:** progress monitoring jen v CLI (web nemá live stav zpracování); stream processing chybí (soubor se načte do paměti pro parsing — u velkých obrazů RAM peak, zmírněno chunkingem v ewf_container). **Dluh:** determinismus paralelního běhu je zajištěn deterministickým řazením při ukládání, ale není explicitně testován pod load. **Rizika:** střední (RAM u velkých E01). **Doporučení:** FÁZE 11 — progress endpoint + stream parsing pro soubory >1 GB. **Priorita:** P1.

## 4. Hashování a integrita

**Funguje:** SHA-256 + MD5 všech souborů ✓, re-hash `stopa verify` ✓, hash manifesty exportů ✓, **Ed25519 podpisy** (kontrolní body integrity C4) ✓, hash chaining audit logu ✓, duplikáty podle hashů ✓, hash set management (hit/miss v reportu) ✓.

**Neúplné:** SHA-512 chybí (master prompt FÁZE 7); verifikace podpisů exportů je v `stopa verify`, ale web UI ji neukazuje. **Rizika:** nízká. **Doporučení:** přidat SHA-512 do hashing pipeline (backward compat — nová kolona). **Priorita:** P2.

## 5. Chain of Custody a audit log

**Funguje:** custody_items s metadata ✓, append-only audit_log s triggery RAISE(IGNORE) ✓, `stopa audit` CLI ✓, audit trail v reportu (sekce 7) ✓, AI dotazy auditované (`analysis_operations`, op_type=ai_query, verze modelu + SHA-256 promptu) ✓.

**Neúplné:** RBAC chybí — actor je volitelný řetězec bez ověření identity; audit přístupů k web API není (jen operace). **Rizika:** střední pro multi-analytik provoz. **Doporučení:** FÁZE 12 — minimálně actor povinný + session token. **Priorita:** P2.

## 6. Exportní systém

**Funguje:** CSV/JSON (artifacts, timeline, correlations) ✓, manifest s deterministickým hashem + Ed25519 podpisem u každého exportu ✓, kontrolní bod integrity po exportu ✓, i18n hlaviček ✓.

**Neúplné (FÁZE 9):** STIX 2.1 ✗, CASE/UCO ✗, Plaso-compatible ✗, LEF ✗, JSONL ✗, XML ✗, SQLite export ✗; standardizované schéma s verzí schématu v manifestu — částečně (verze modulu ano, verze schématu ne). **Rizika:** nízká. **Doporučení:** nejdřív JSONL + XML (levné), STIX/UCO až při konkrétním požadavku interoperability. **Priorita:** P2.

## 7. Report engine

**Funguje:** HTML vždy, PDF volitelně (weasyprint) ✓, i18n cs/en ✓, **9 sekcí**: chain of custody, průběh zpracování, artifacty, findings, označené soubory, manifest (SHA-256+Ed25519), audit trail, timeline, korelace ✓; lineage reportu do DB (`_log_report_lineage`) ✓.

**Neúplné (FÁZE 10 — 20 sekcí):** chybí titulní strana s identifikací případu a rozsahem analýzy, metodika zpracování, použité nástroje+verze (částečně v manifestu), technická omezení, chyby/neúplnosti zpracování (jsou v auditu, ale ne jako samostatná sekce), závěrečné shrnutí, přílohy. **Rizika:** nízká. **Doporučení:** doplnit chybějící sekce z dat, která už v DB jsou (nástroje+verze = C3 registry + benchmark; omezení = coverage matrix). **Priorita:** P1.

## 8. Timeline Intelligence

**Funguje:** unified timeline z všech zdrojů ✓, časová normalizace (UTC + lokální čas přes case timezone_name) ✓, `timeline_anomaly` detekce anomálií (označeny jako analytický podnět, ne důkaz) ✓, AXIOM-style timeline CLI ✓, web timeline view s filtry ✓.

**Neúplné (FÁZE 3):** porovnání více časových období ✗, export vybraného úseku (export je celkový) ✗, rozlišení přesnosti časových údajů (timestamp precision) — částečně; vizualizace je tabulková, ne interaktivní osa. **Rizika:** nízká. **Doporučení:** m-d10 Timeline Intelligence 2.0 (rozpory, duplikáty, přesnost timestampů) — už v roadmapě. **Priorita:** P1.

## 9. Evidence Graph / Entity Resolution

**Funguje:** entity + korelace engine ✓, **Entity Resolution 2.0** (I3): 4 confidence levels (confirmed/strong_candidate/possible/unverified), normalizace telefonů/mailů/platformních účtů, WhatsApp JID→E164, merge candidates s důvody, časové rozmezí vztahů first_seen/last_seen ✓; SVG graf v web UI s barvami podle druhu entity a tloušťkou hran podle confidence ✓.

**Neúplné (FÁZE 4):** cross-artifact correlation je heuristická (same_contact, hash_match, temporal_overlap) — chybí detekce vztahů mezi událostmi vyššího řádu; vizuální navigace je statický SVG (bez zoom/pan/filtru hran); každý vztah má zdroj+metodu+confidence ✓, ale verzi analytického algoritmu ne. **Rizika:** nízká. **Doporučení:** přidat `algorithm_version` do correlations; interaktivní graf (zoom/pan) jako UX vylepšení. **Priorita:** P2.

## 10. Forensic AI Copilot

**Funguje:** I1 orchestrace — 5 deklarativních agentů (case/timeline/artifact/media/report analyst), auto/explicitní routing, fail-closed validace LLM výstupu + citace ✓; I2 Forensic RAG — tři znalostní vrstvy (Case/Technical/Knowledge), chunking markdown, FTS5 sanitizace, prompt injection ochrana `<untrusted_source>` ✓; E11 LM Studio klient (localhost:1234, OpenAI-kompatibilní) s graceful degradation ✓; offline-first ✓; audit AI dotazů s verzí modelu + SHA-256 promptu ✓.

**Neúplné (FÁZE 5):** redakce citlivých údajů před odesláním do LLM ✗; oddělení případů je implicitní (RAG čte jen aktivní případ) ale není explicitně testováno; AI nesmí označovat pachatele — pravidlo je v promptu agentů, ne vynuceno validátorem. **Rizika:** střední (data mohou jít do lokálního LLM bez redakce). **Doporučení:** STOPA_AI_GOVERNANCE.md + redaktor PII před inference; explicitní test oddělení případů. **Priorita:** P1.

## 11. File Intelligence

**Funguje:** rozpoznávání skutečných typů (magic bytes, 25 signatur) ✓, MIME vs přípona (`bad_extension` flag) ✓, duplikáty podle hashů ✓, hash sety ✓, metadata extraction: EXIF (Pillow volitelné), PDF/OOXML/ID3/MP4 bez závislostí ✓, file provenance (lineage C2) ✓.

**Neúplné (FÁZE 6):** file similarity ✗; preview v web UI = hex view + metadata (obrázky/PDF/text náhled chybí); detekce poškozených souborů je jen implicitní (parser fail). **Rizika:** nízká. **Doporučení:** bezpečný image/PDF preview (data URL z DB, bez sandboxu — akceptovatelné pro desktop GUI) + explicitní `corrupted` flag v files tabulce. **Priorita:** P2.

## 12. Validation Engine (P0 Core C1–C6 — hotové)

**Funguje:** C1 Unified Evidence Model (provenance, findings, confidence) ✓; C2 Lineage Engine (lineage_events v8, chain traversal) ✓; **C3 Parser Validation Registry** (9 parserů, 1:1 sync s pipeline, shoda verzí) ✓; C4 Integrity 2.0 (hash chaining, Ed25519 kontrolní body, manifesty) ✓; C5 Reproducibility Engine (záznam operací, `stopa replay`, porovnání výsledků) ✓; C6 Benchmark Engine (deterministické workloads, měření času + špičková RAM, validační reporty per-parser s ID+verzí+confidence+provenance) ✓.

**Neúplné:** kontrola konzistence databáze je v `stopa integrity`, ale ne automaticky po každém zpracování; evidence nepodporovaných formátů — částečně (fallback generic file). **Rizika:** nízká. **Doporučení:** automatický integrity checkpoint na konci analyze(). **Priorita:** P2.

## 13. Case Management

**Funguje:** více zdrojů v jednom případě ✓, více diskových obrazů ✓, evidence marks (ruční označování) ✓, findings management ✓, audit trail rozhodnutí ✓, backup (SQLite .backup + integrity check) ✓, CRUD případů v web UI ✓.

**Neúplné (FÁZE 8):** osoby a role ✗, štítky na artifactech ✗ (jen marks), přiřazování úkolů ✗, případové šablony ✗, porovnání více případů ✗, archivace s pozdější verifikací integrity — backup existuje, ale „archive + verify" workflow ne. **Rizika:** nízká (single-analytik provoz). **Doporučení:** osoby+role až při multi-user; štítky levné doplnit. **Priorita:** P2–P3.

## 14. Performance

**Funguje:** paralelní parsery (ThreadPoolExecutor) ✓, resume/checkpointing ✓, FTS5 indexy ✓, stránkování API (LIMIT/OFFSET) ✓, benchmark engine s RAM měřením ✓.

**Neúplné (FÁZE 11):** processing queue ✗, progress monitoring v web UI ✗, cache ✗, stream processing pro velké soubory ✗. **Rizika:** střední (RAM peak u velkých E01). **Doporučení:** progress endpoint + stream parsing; benchmark baseline commitovat do DB pro detekci regresí (C6 to umí — jen napojit na CI). **Priorita:** P1.

## 15. Security

**Funguje:** Pydantic validace vstupů ✓, oddělení případů (samostatné DB) ✓, Ed25519 podpisy ✓, prompt injection ochrana v RAG ✓, path traversal opraveny (E-audit) ✓, graceful degradation AI ✓.

**Neúplné (FÁZE 12):** RBAC ✗, šifrování citlivých dat v DB ✗, izolace parserů (sandbox) ✗ — parser běží s právy procesu; zranitelnostní skenování závislostí ✗ (žádné dependabot/pip-audit); bezpečné aktualizace ✗. **Rizika:** střední (nedůvěryhodné dokumenty parsuje stejný proces). **Doporučení:** pip-audit do CI; sandbox parserů až při multi-user; RBAC minimálně actor+token. **Priorita:** P2.

## 16. UI

**Funguje:** dark mode ✓, moduly: dashboard, disk-image, file-system, partition-map, system-recovery, sql-recovery, messaging-chat (chronologický chat), deletion-check, artifacts, entity-graph ✓; File Inspector s hex view + metadata ✓; AI panel (ai.js) ✓.

**Neúplné (FÁZE 13 — 14 obrazovek):** chybí samostatné: Processing Monitor (live stav), Validation Center, Audit Center, Report Center (report je endpoint, ne modul), File Intelligence jako modul; globální filtr a rychlé vyhledávání jsou částečné. **Rizika:** nízká. **Doporučení:** doplnit chybějící moduly z existujících API (všechna data už v DB jsou — jen UI vrstva). **Priorita:** P2.

## 17. QA a testy

**Funguje:** 819 testů, plně offline (magic bytes + SQLite + FTS5 + registry/plist + messaging + disk images/carving + Windows parsery + E-fáze + P0 Core + P0 Intelligence) ✓; syntetické fixtures 29 MB ✓; benchmark report ✓; ruff clean ✓.

**Neúplné (FÁZE 14):** performance tests jsou v C6, ale ne běží automaticky při každém commitu; security tests ✗ (jen ad-hoc); recovery tests — E3 resume testováno, ale „poškozený obraz" fixture chybí; porovnání s nezávislými referenčními nástroji ✗. **Rizika:** nízká. **Doporučení:** benchmark do CI (s prahem regresí >20% — C6 `detect_regressions()` to umí); přidat fixture poškozeného obrazu. **Priorita:** P2.

## 18. Coverage Matrix

**Funguje:** `docs/re-axiom/AXIOM_COVERAGE.md` + `.json` (generátor `scripts/build_axiom_coverage.py`) — všech 237 AXIOM položek klasifikováno: **22 covered / 49 portable-local / 112 cloud-export / 15 memory / 34 base-class** ✓.

**Neúplné (FÁZE 15):** chybí `STOPA_COVERAGE_MATRIX.csv` v kořeni; stavy jsou kategorie portu, ne SUPPORTED/PARTIALLY_SUPPORTED/EXPERIMENTAL/NOT_SUPPORTED/DEPRECATED; u každého typu chybí: referenční dataset + výsledek validace (C6 to generuje — jen napojit). **Rizika:** nízká. **Doporučení:** rozšířit generátor matice o požadované sloupce a export CSV. **Priorita:** P1 (levné, vysoká viditelnost).

---

## Souhrn priorit

| Priorita | Položky |
|---|---|
| **P0** | Port AXIOM extraktorů po skupinách (49 portable-local nejprve); doplnit chybějící parsery do C3 registry |
| **P1** | Report engine — doplnit 20 sekcí; Timeline Intelligence 2.0 (m-d10); AI governance + PII redaktor; progress monitoring + stream parsing; coverage matrix CSV s plnými stavy |
| **P2** | SHA-512; export JSONL/XML/STIX; file preview + similarity; RBAC minimální; UI moduly (Processing/Validation/Audit Center); benchmark do CI; pip-audit |
| **P3** | Case Management 2.0 (osoby, role, šablony); sandbox parserů; porovnání případů |

## Návrh cílové architektury a implementačního plánu

Viz `docs/STOPA_TARGET_ARCHITECTURE.md` + `docs/DEVELOPMENT_ROADMAP.md` (aktualizovat o tento audit). Implementace po etapách A–M master promptu; **ETAPY A–C hotové** (audit, gap analysis, target architecture), P0 Core C1–C6 a P0 Intelligence I1–I3 commitnuté.

## Testovací strategie

Plně offline sada (819) + syntetické fixtures + benchmark engine s detekcí regresí; cíl: každý nový parser = unit testy na syntetickém fixture + záznam v C3 registry + řádek v coverage matrix.
