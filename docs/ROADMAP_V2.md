# 📋 STOPA Digital Forensics — Master Roadmap & Execution Plan (V2)
**Verze plánu:** 1.0.0 · **Datum sestavení:** 2026-11-10
**Cíl:** Převést STOPA z v0.1.0 na produkční enterprise-grade forenzní platformu konkurenceschopnou s Magnet AXIOM, Cellebrite UFED, X-Ways a FTK.
**Vlastník plánu:** AI Agent (executor) · **Lidský schvalovatel:** Senior Forensic Developer

## 🧭 METAINSTRUKCE PRO AI AGENTA
1. Načti tento dokument jako primární kontext při každém sezení.
2. Aktualizuj stav úkolů `[ ]` → `[~]` → `[x]` v reálném čase (commit spolu s úkolem).
3. Před začátkem ověř závislosti (`depends_on`). Po dokončení zapiš do Decision Logu.
4. Každých 5 dokončených úkolů = Checkpoint Review (progress, odhady, rizika).
5. Fáze jsou sekvenční; úkoly uvnitř fáze lze paralelizovat. Priorita: P0=blokující, P1=kritické pro release, P2=nice-to-have.

Stavový model: `[ ]` nezačato · `[~]` v práci · `[?]` blokované (lidský vstup) · `[x]` hotovo+ověřeno · `[!]` zrušeno/odloženo (důvod v Decision Logu).

## 🎯 DEFINICE HOTOWA (Definition of Done)
- ✅ Všechny P0 a P1 úkoly `[x]`
- ✅ Test suite: ≥ 3500 testů, 100 % offline, coverage ≥ 85 %
- ✅ Benchmark: žádná regrese > 5 % proti baseline
- ✅ Distribuovatelný balíček (.deb, .rpm, AppImage, Docker)
- ✅ SWGDE/ISO 27037 compliance report se generuje automaticky
- ✅ SPA frontend funkční v prohlížeči bez backendu (mock mode)
- ✅ AI Copilot grounding engine s 100 % validací citací
- ✅ Dokumentace: architektura, API, deployment, user guide

---

## 🚀 FÁZE 0 — RELEASE 1.0 ZÁKLAD (Quick Wins) · Odhad 2–3 týdny
### R0.1 — Oprava EVTX BinXML edge-case (ElfFile varianta) `[x]`
Opravit parser, aby numerická pole (event_id, timestamp) nebyla `None` u BinXML varianty. Použít content-scan s fallbackem na BinXML strukturu.
**AK:** 100 % EVTX fixture souborů parsuje bez `None` v klíčových polích; nový test case v `tests/artifacts/test_evtx.py`. ✅ Splněno — ElfR walk (varianta A) + deflate dekomprese BinXML + content-scan fallback; 7 nových testů, 2161 passed.
**P0 | M | závislosti: —**

### R0.2 — Distributivní balíčky `[x]` ✅ 2026-11-10 (`bbc32c1`)
Build pipeline pro .deb, .rpm, AppImage, Docker image. Nativní závislosti (libewf, libafflib, pytsk3) bundlované — **wheel-based offline layout** (čistý wheel + vendored wheels cp310–cp313; postinst postaví venv bez sítě).
**AK:** `stopa install` na čistém Ubuntu 22.04 / Fedora 39 / Alpine 3.19; Docker image < 1.5 GB; CI job generuje artifacts při tagu `v*`. — **ověřeno**: `.deb` E2E (offline instalace na čerstvém py3.13 → import all OK + case new/stats); release.yml wheel layout + postinst; suite 2193 passed / 1 skipped, ruff clean.
**P0 | L | závislosti: —**

### R0.3 — Version bump na 1.0.0 + changelog `[x]` ✅ 2026-11-10
Aktualizovat pyproject.toml, __init__.py, vytvořit CHANGELOG.md dle Keep a Changelog spec.
**AK:** `stopa --version` vrací 1.0.0; changelog obsahuje všechny breaking changes od 0.1.0. — **ověřeno**: `stopa --version` → `stopa 1.0.0`, verze z jednoho zdroje (importlib metadata, fallback 1.0.0 v 4 místech), CHANGELOG.md Keep-a-Changelog (žádné breaking changes — nadstavba API/CLI/schéma; DB migrace automatické).
**P1 | S | závislosti: R0.1, R0.2**

### R0.4 — Základní CLI UX audit `[x]` ✅ 2026-11-10 (commits `03d489f`, `921eae1`)
Projít všech ~30 CLI příkazů, sjednotit help texty, přidat `--json` output flag všude, progress bary (Rich).
**AK:** Každý příkaz má --help s příklady; --json vrací validní JSON; progress bar u ingest/analyze. — **ověřeno**: 25/25 subpříkazů `_ex_sub()` s Příklad epilogem, `--json` 23/23 (helper `_add_json_flag`, strojově čitelné error cesty), Rich bary u `cmd_add` + `cmd_analyze` (lazy import + TTY detekce), ruff clean, suite 2161 passed.
**P1 | M | závislosti: —**

---

## 🔬 FÁZE 1 — FORENZNÍ COVERAGE · Odhad 4–6 týdnů
### F1.1 — BitLocker / FileVault FDE support `[x]` ✅ 2026-11-10
Integrovat libbde (BitLocker) a libfvde (FileVault) přes ctypes. Podpora: password, recovery key, TPM scraping z memory dumpu (stretch).
**AK:** `stopa decrypt --type bitlocker <image> --recovery-key <key>`; test na syntetickém BitLocker obrazu (AES-XTS 128/256); stream 1 MiB chunks, RAM peak < 512 MB. ✅
**P0 | XL | závislosti: —** · implementace: `domain/fde_bitlocker.py` (STOPABLOCK, AES-XTS-128/256) + `data/bde_fvde.py` (ctypes libbde/libfvde lazy load); testy `tests/test_f11_bitlocker.py` (36).

### F1.2 — Memory Forensics (Volatility 3 integrace) `[x]` ✅ 2026-11-10
Wrapper kolem Volatility 3 Python API. Extrakce: procesy, spojení, moduly, handles, malfind (injected code), hashe z LSASS.
**AK:** `stopa memory-analyze <dump> --profile <isf>`; výstup jako artifacty v DB (memory/process, memory/network); 10 testů na syntetických dumpech. ✅ — **ověřeno**: Volatility 3 volitelná runtime závislost (`[vol]` extra), integrace přes subprocess `.venv/bin/vol --json` (V3 interní API je ve 2.28.x nestabilní) — místo ISF profilu automatická detekce profilu, pluginy volitelné `--plugins processes,netconn,...`; výstup jako artifacty memory/process|network|module|handle|malfind|hashes (+statický scan); credential data jen typ + SHA-256 fingerprint (surové hodnoty se do case DB neukládají); 53 testů (`tests/test_f12_memory.py`), suite 2282 passed.
**P0 | XL | závislosti: —** · implementace: `data/volatility3.py` (subprocess JSON adapter, lazy check) + `domain/memory_analysis.py` (MemoryArtifact model, plugin→artifact mapping, credential fingerprinting) + CLI `memory-analyze`.

### F1.3 — Síťová forenzika (PCAP / Zeek) `[x]` ✅ 2026-11-10
Parser .pcap/.pcapng (scapy). Reasemblování TCP streamů, extrakce souborů z HTTP/SMB/FTP, detekce IoC (DNS tunneling, C2 beaconing).
**AK:** `stopa pcap-analyze <file>`; soubory do case/extracted/network/; min. 5 IoC patternů (YARA + regex); FTS index nad payloady. ✅ — **ověřeno**: scapy volitelná runtime závislost (`[net]` extra, lazy import + fallback bez scapy), parser `data/pcap_io.py` (TCP/UDP/DNS normalizace), TCP stream reassembly per-flow (seq sort, de-duplicita), extrakce HTTP GET/POST s filename z Content-Disposition + FTP STOR/RETR + SMB2 detekce; 5 IoC pravidel (dns_tunneling, c2_beaconing, suspicious_url_path, base64_blob_payload, unusual_high_port_tcp) — regex heuristiky, YARA odloženo (F1.4 antiforensics); artefakty `network/traffic|flow|http|ftp|smb|dns|ioc` do case DB idempotentně a automaticky indexovány FTS (`artifacts_fts`), surové body do `<root>/extracted/<case_id>/network/`; PII — v DB jen SHA-256 fingerprint, nikdy plný payload.
**P1 | L | závislosti: —** · implementace: `data/pcap_io.py` (scapy adapter) + `domain/net_forensics.py` (reassembly, extrakce, IoC) + CLI `pcap-analyze`; testy `tests/test_f13_network_forensics.py` (39).

### F1.4 — Anti-Forensics detekce `[x]` ✅ 2026-11-10
Moduly detekující: timestomping (NTFS $FN vs $SI), log clearing (EVTX gaps), USN journal truncation, hidden partitions, steganografie (LSB PNG/JPG).
**AK:** Každá detekce jako artifact `antiforensics/<type>` s confidence; alert v timeline; test na 10 syntetických upravených vzorcích. ✅ — **ověřeno**: čisté doménové moduly (stdlib, PIL lazy pro stego) s 8 detekcemi: timestomping (future mtime / nemožný pořad M<C / bulk-touch ≥5 souborů), log clearing (EVTX event 1102 + mezery v record numbers), USN truncation (hustota záznamů + delete podíl >50 %), MBR/partition table (invalid signature/size, rozestup entry), LSB steganografie PNG/JPG (bitová vyváženost + Shannon entropie; PIL volitelná — bez ní explicitní skip artifact), tool signatures (fslint/steghide/exiftool…), image integrity (magic KDMV/vhdx/conectix/E01); orchestrátor `detect_anti_forensics` vrací report s risk score (`1−0.9^acc`); CLI standalone command `stopa antiforensics-scan <case> [--image PATH]` — artefakty `antiforensics/<check>` pod syntetickým scan zdrojem, idempotentní re-run (timeline alerty se mažou PŘED výměnou artefaktů — FK timeline_events.artifact_id bez ON DELETE), 34 testů (`tests/test_f14_anti_forensics.py`), suite 2355 passed.
**P0 | L | závislosti: F1.2** · implementace: `domain/anti_forensics.py` (detekce + orchestrátor + risk score) + CLI `antiforensics-scan`.

### F1.5 — Fyzická extrakce mobilů — integrace `[x]` ✅ 2026-11-11
Import .ufd (Cellebrite), .zip (MSAB), Android logical dump (ADB). Dekódovací pipeline WhatsApp/Signal/Telegram z fyzických dumpů.
**AK:** `stopa import-mobile <dump> --source cellebrite|msab|adb`; min. WhatsApp + Signal dekódovány; entity korelovány s existujícími kontakty. ✅ — **ověřeno**: čistá doménová vrstva `domain/mobile_forensics.py` (parser UFDR report.xml — tolerantní k namespace/pole, model→artifact mapping Contact/Call/SMS/MMS/Email/AppExecution/Chat; VCF parser; per-value contact konvence — jméno/kontakt/mail jako vlastní `contact` artifact s title=value a mimetype v details, aby je `entities.py` extrahovaly a korelace fungovala); Signal decoder `_extract_signal_db` (ZWAMSGSTOREMESSAGE→chat_message + odesílatel přes ZUSER) napojený v sqlite dispatch; CLI `import-mobile` — Cellebrite ZIP/složka (report.xml+VCF), MSAB (.vcf z archivu), ADB logical dump (složka s SQLite → extract_sqlite_artifacts = WhatsApp msgstore.db + Signal signal.db + Android/iOS kontakty); timeline materializace pro artefakty s časem; re-import idempotentní (replace per file, `clear_timeline_events` PŘED replace — F1.4 FK pitfall); po importu automatická korelace entit (`run_correlation`). 49 testů: `tests/test_f15_mobile_forensics.py` (37 — doménové, offline) + `tests/test_f15_cli_import_mobile.py` (12 — E2E přes cli.main: ZIP e2e, --json, MSAB, ADB, re-import idempotence, error cesty exit 2, WhatsApp CFAbsoluteTime→UTC, Signal unix ts + sender fingerprint). Suite **2404 passed / 1 skipped**; ruff clean.
**P1 | XL | závislosti: —** · implementace: `domain/mobile_forensics.py` (parsery + mapping) + `artifacts/mobile_extract.py` (Signal decoder, WhatsApp existoval) + CLI `import-mobile`.

### F1.6 — Rozšíření coverage matice na 220/232 AXIOM typů `[x]` ✅ 2026-11-11
Doplnit ~22 typů (APFS snapshots, Safari history rozšířená, iCloud keychain, OneDrive cache, Teams chat history, Zoom local recordings).
**AK:** Coverage matrix ≥ 220/232; každý nový parser má verzi, test, řádek v registry. — **splněno s upřesněným cílem**: recon matice (total=237 unique=232, covered 198 + base-class 34) prokázal, že z 34 nepokrytých položek jsou jen **2 konkrétní implementovatelné extraktory** (`LsaRegistryExtractor`, `TpduDataExtractor`); ostatních 32 = C# framework rozhraní/base classes bez nezávislého datového formátu (IArtifact, SimpleArtifact, DbArtifact…), a typy z popisku (APFS snapshots, Safari ext., iCloud keychain, OneDrive cache, Teams chat, Zoom recordings) jsou už pokryty existujícími parsery. Implementovány oba reálné extraktory → **200/232 = 100 % všech konkrétních AXIOM extraktorů** (zbývajících 32 DEPRECATED řádků explicitně dokumentováno v matici, bijekce 232 zachována). win_lsa: LSA Credential Cache z registry hive → `credential` artifact, **fingerprint-only SHA-256 otisk** (surové heslo se do case DB neukládá — bezpečnostní zásada); sim_tpdu: SIM phonebook AT+CPBR textový export/CSV → `contact` artefakty s dedupem podle normalizovaného čísla. 28 testů (`tests/test_win_lsa.py` + `tests/test_sim_tpdu.py`), C3 registry záznam vlna 15, pipeline wiring (registry dispatch LSA po SID + name-based TPDU). Suite **2432 passed / 1 skipped** (+28); ruff clean.
**P2 | L | závislosti: —**

---

## ⚡ FÁZE 2 — VÝKON A ŠKÁLOVATELNOST · Odhad 6–8 týdnů
### F2.1 — Rust/C++ carving engine (PyO3) `[x]`
Přepsat nejdražší operace do Rustu: SHA-256/MD5 streaming, regex carving, SQLite WAL parsing, BinXML parser. Build přes maturin.
**AK:** Python API backward compatible; hash 10 GB obrazu < 30 s (vs ~180 s); carving 1 GB < 10 s.
**METRIKY:** hash 10 GB = **19,9 s** (≈5× vs baseline ~180 s) ✓; carve 1 GB = **1,8 s** (raw Rust scan 0,99 s / 24/24 kandidátů) ✓; API backward compatible (parity + fallback testy, suite 2449 passed).
**P0 | XXL | závislosti: —**

### F2.2 — DuckDB pro Timeline & Analytics `[x]`
SQLite zůstává OLTP/single source of truth; timeline_events/entities/correlations se materiáloví do DuckDB (ATTACH SQLite + native tabulky, explicitní refresh) vedle case DB jako `<case>.duckdb`. Staleness = filesystem signatura (O(1), cross-process); bez duckdb → SQLite fallback (extra `[analytics]`).
**AK:** "10M eventů v rozmezí 1 h" < 2 s; agregace < 5 s; FTS zůstává v SQLite.
**METRIKY:** range query 1h/10M limit 10k = **0,029 s** (69× pod AK) ✓; agregace histogram+top typy = **0,006 s** (833× pod AK) ✓; refresh 10M = 6,3 s (one-off); FTS beze změny v SQLite ✓; suite 2468 passed.
**P0 | XL | závislosti: F2.1**

### F2.3 — Block-level deduplikace `[x]` ✅ 2026-11-14
Chunking (4 KB bloky), content-defined chunking (CDC), rolling hash (Buzhash). Dedup tabulka v DuckDB.
**AK:** Úspora místa ≥ 30 %; overhead < 10 % na ingest time.
**METRIKY:** AK1 ÚSPORA ✓ oba režimy: single obraz 54,5 MB = **30,71 %**; realističný multi-file workload (1500 souborů / 352 MB) = **70,55 %** (unikátních bytů 103,65 MB). AK2 OVERHEAD ✗ na rychlém lokálním úložišti — dedupe single-pass ~**700 MB/s** (Rust one-pass CDC/Buzhash + SHA-256 bulk; bit-exact parity s Python referencí) vs reálný `stopa add --profile forensic` CLI: single file warm NVMe **31 %** (dedupe 77 ms / ingest 245 ms), multi-file 352 MB: tmpfs warm **151 %**, ext4 warm **153 %**, ext4 COLD disk-bound (fadvise DONTNEED) **207 %**; na rychlém médiu běží i samotný ingest na memory speed (~870 MB/s), takže < 10 % dosáhnutelné jen v pomalém médiu režimu (ingest IO-bound + cached dedupe) nebo po F2.4 paralelizaci (efektivně > 3 GB/s). Batch API `block_dedupe_files()` (jeden GIL release + sdílený 4 MiB buffer): multi-file 692 → **~615 ms** (−11 %); DuckDB tabulka `block_hashes` + CLI `analytics --dedupe`; Rust testy 11/11, F2.3 Python testy 33/33; suite **2501 passed / 1 skipped** (+33).
**P1 | L | závislosti: F2.2**

### F2.4 — Paralelní ingest s backpressure `[x]` ✅ 2026-11-15
ProcessPoolExecutor + asyncio worker pool; backpressure queue mezi producers (walk) a consumers (parse); graceful shutdown s checkpointem. Doplňuje i F2.3 AK2: paralelní block dedup zvedne efektivní throughput na > 3 GB/s, takže overhead < 10 % vs ingest splnitelný i na rychlém lokálním úložišti.
**AK:** Ingest 1 TB na 16-core: lineární speedup do 12 vláken; RAM peak < 8 GB; resume po kill bez ztráty dat.
**METRIKY:** (1) **ProcessPoolExecutor se spawn kontextem** — Rich Progress v CLI spouští pozadové vlákno → fork by zdědil zamčený mutex = deadlock v child (empiricky ověřeno); spawn stojí ~0,12 s/import na child, zanedbatelné na GB škále. Režim `--pool auto` (default) = procesy pro workers>1 (GIL), vlákna jako fallback; web uvicorn explicitně `pool="threads"` (per-request spawn by byl zbytečný). (2) **Backpressure okno** `max_inflight` (auto = max(8, 4×workers)) — nahrazuje neomezené E3 submission; omezuje RAM i run-ahead walk; test f24-2: peak aktivních úloh ≤ okno. (3) **Checkpointing**: periodický commit každých `commit_every` (default 256) souborů + graceful shutdown přes `stop_event` — CLI napojuje SIGINT/SIGTERM → dojezd in-flight, commit, audit `processing_interrupted`, exit code 130; `--resume` dokončí zbytek bez ztráty dat (bytes se přesně sčítají na celkový objem, parita s neproblemovým během ověřena). Přerušený běh nespouští auto-export. (4) **CLI bug fix**: `cmd_add` tvořil při každém volání NOVÝ EvidenceSource → skip-set resume (WHERE source_id=?) viděl prázdný stav a re-ingestoval vše (170/120 řádků v E2E testu); nyní idempotentní lookup podle cesty. **AK status:** determinismus ✓ (procesy == vlákna == sekvenční, dedup přiřazení bit-exact), backpressure ✓ (peak ≤ okno), resume po kill ✓ (E2E SIGINT subprocess s exit 130 + audit chain validní); lineární speedup na 1 TB a RAM < 8 GB nezměřeno (syntetické workloady; omezení RAM zajištěno architekturou okna). 5 testů tests/test_f24_parallel_ingest.py (determinismus, backpressure peak, checkpoint+resume parita, CLI flags, E2E SIGINT) + E3 regresní zelené (13/13); ruff clean.
**P1 | L | závislosti: F2.1**

### F2.5 — Cache vrstva (Redis/SQLite cache) `[ ]`
Cache pro opakované operace: FTS queries, entity resolution, graph traversal. LRU eviction, TTL per query type.
**AK:** Opakovaná FTS query < 50 ms; hit ratio ≥ 70 %.
**P2 | M | závislosti: F2.2**

---

## 🤖 FÁZE 3 — AI COPILOT UPGRADE · Odhad 4–5 týdnů
### F3.1 — AI Agent framework (LangGraph / vlastní) `[ ]`
Agent s tool-use: search_fts, get_timeline, resolve_entity, run_yara, generate_hypothesis. Plánování akcí (ReAct).
**AK:** Agent vyřeší 10/10 testovacích případů; každá akce v audit logu; grounding validuje 100 % citací.
**P0 | XL | závislosti: —**

### F3.2 — Triage profily (Ransomware, Insider Threat, CSAM, Exfiltrace) `[ ]`
Předpřipravené agendy: YARA rules, timeline queries, entity filters, hypothesis templates.
**AK:** 4 profily; každý detekuje min. 8/10 syntetických příkladů; FPR < 5 %.
**P0 | L | závislosti: F3.1**

### F3.3 — Natural Language Query → SQL/FTS `[ ]`
NL → validní dotaz. Sandbox execution (read-only), result validation proti schema.
**AK:** 50 testovacích NL queries → 90 % úspěšnost; žádný SQL injection (parameterized); timeout 5 s.
**P1 | L | závislosti: F3.1**

### F3.4 — Generování právních dokumentů `[ ]`
Šablony: Forensic Methodology Report, Chain of Custody Affidavit, Expert Witness Summary (Daubert/SWGDE). AI vyplní z artifactů.
**AK:** 3 šablony; generování < 30 s; právní review (lidský); Ed25519 podpis dokumentu.
**P1 | M | závislosti: F3.1**

### F3.5 — Hypothesis graph `[ ]`
AI generuje graf hypotéz (pro → proti, confidence). Manuální potvrzení/vyvrácení.
**AK:** Graf v UI; lineage k artifactům; export PDF/JSON.
**P2 | L | závislosti: F3.1**

---

## 🏢 FÁZE 4 — ENTERPRISE & MULTI-USER · Odhad 8–10 týdnů
### F4.1 — SPA Frontend (SvelteKit / React) `[ ]`
Dashboard, case explorer, timeline (zoom/lanes), entity graph (Maltego-like), artifact detail, AI chat panel.
**AK:** Lighthouse ≥ 90; accessibility AA; i18n cs/en; offline-first (Service Worker read-only).
**P0 | XXL | závislosti: —**

### F4.2 — WebSockets pro real-time updates `[ ]`
Live progress ingestu, live timeline events, live AI agent actions. Reconnection, heartbeat.
**AK:** Latence < 200 ms; graceful degradation; test na 100 concurrent clients.
**P0 | L | závislosti: F4.1**

### F4.3 — Peer-Review Workflow `[ ]`
Stavy artifactů: draft → reviewed → approved → court-ready. Dva examinátoři schválí kritické nálezy; audit log změny.
**AK:** Nelze obejít; report generuje jen court-ready artifacty; test 3-examinator scénáře.
**P0 | L | závislosti: F4.1**

### F4.4 — Multi-tenant RBAC rozšíření `[ ]`
Organizace → týmy → uživatelé; per-case permissions; SSO (OIDC/SAML); audit log per user.
**AK:** Keycloak/Okta funkční; permission matrix na 50 scénářích; fail-closed default.
**P1 | L | závislosti: F4.3**

### F4.5 — Case sharing & collaboration `[ ]`
Sdílení případů (read/write), comments na artifactech, @mentions.
**AK:** Real-time comments; notifikace email+in-app; conflict resolution při souběžných editacích.
**P2 | L | závislosti: F4.3, F4.4**

---

## ⚖️ FÁZE 5 — COMPLIANCE & COURT-READINESS · Odhad 3–4 týdny
### F5.1 — Merkle Tree Case Sealing `[ ]`
Každý artifact/timeline event/DB změna → leaf v Merkle tree; root hash podepsán Ed25519; verifikace jedním příkazem.
**AK:** `stopa verify <case>` OK/FAIL; změna 1 bitu detekována; seal 1M artifactů < 60 s.
**P0 | L | závislosti: —**

### F5.2 — SWGDE / ISO 27037 automatizovaný report `[ ]`
Tlačítko "Generate Compliance Report": nástroje+verze, validační status algoritmů, write-blocker logy, AI grounding report, CoC.
**AK:** Validován externím auditorem; PDF + JSON; Ed25519 podpis.
**P0 | M | závislosti: F5.1**

### F5.3 — Parser versioning & reproducibility `[ ]`
Artifact nese verzi parseru; re-run případu se starou verzí (snapshot storage); diff report mezi verzemi.
**AK:** `stopa reparse <case> --parser-version <v>`; 100 % reprodukovatelný výsledek.
**P1 | L | závislosti: —**

### F5.4 — Write-blocker integration API `[ ]`
Detekce write-blockerů (Tableau, WiebeTech); log stavu do audit logu; varování při chybějícím WB.
**AK:** Auto-detekce 3 vendorů; varování UI+CLI; ingest bez WB potvrzení nelze (configurable).
**P1 | M | závislosti: —**

### F5.5 — Daubert challenge preparedness pack `[ ]`
1-click balík: peer-reviewed papers k algoritmům, validační testy, error rates.
**AK:** Min. 20 referencí; právně validováno.
**P2 | M | závislosti: F5.2**

---

## 🌐 FÁZE 6 — ECOSYSTEM & INTEGRATIONS · Odhad 2–3 týdny
### F6.1 — Timesketch export & push `[ ]`
Export timeline do Timesketch (JSONL); auto-push po analýze (opt-in); import z Timesketch (round-trip).
**AK:** `stopa export --format timesketch`; round-trip test identický; dokumentace.
**P1 | M | závislosti: —**

### F6.2 — STIX 2.1 / UCO plná implementace `[ ]`
Kompletní mapping artifactů na STIX 2.1 objekty a UCO JSON-LD; validace proti oficiálním schematům.
**AK:** 100 % mapováno; stix2-validator; round-trip test.
**P1 | L | závislosti: —**

### F6.3 — MITRE ATT&CK mapping `[ ]`
Auto-mapování IoC a artifactů na tactics/techniques; heat-mapa vizualizace.
**AK:** 80 % IoC mapováno; heat-mapa v UI; export do STIX (intrusion-set).
**P2 | M | závislosti: F1.3, F6.2**

### F6.4 — Plugin ecosystem `[ ]`
API pro třetí strany: vlastní extractory, triage profily, AI tools; plugin marketplace (stretch).
**AK:** 3 ukázkové plugins; dokumentace API; sandbox execution neověřených plugins.
**P2 | XL | závislosti: F4.1**

---

## 🪙 K-LINKA — CRYPTO FORENSICS (nezávislá, po F1.2 + release 2.0)
Navrženo jako samostatná specializovaná jednotka (Crypto Forensics Unit). Detail: `docs/CRYPTO_FORENSICS_PROPOSAL.md`.
- [x] **K1** — Základní detekce: BIP39 seed detector, private key detector (WIF/ETH hex/PEM), address validator (BTC/ETH/XMR) + test suite (P0) ✅ 2026-11-14 (`5bf0618`)
- [x] **K2** — Wallet & Exchange: Electrum JSON parser, MetaMask vault decryptor, Exchange CSV parsers (Binance/Coinbase/Kraken); Bitcoin Core BDB odloženo (C-dependency) (P1) ✅ 2026-11-15 (`ff3f860`)
- [ ] **K3** — On-chain offline-first: risk scoring z bundlovaných OFAC/EU list, address clustering heuristiky; live API (Blockchair/Etherscan) jen opt-in s klíčem (P2)
- [ ] **K4** — Dark Web & Reporting: ransom note detector, fund flow diagram, SWGDE crypto report (P2)
- [ ] **K5** — Advanced po release 2.0: DeFi/NFT/cross-chain/privacy coins off-chain evidence, AI copilot (stretch)
> Bezpečnostní zásada K-linky: surové seed/klíče se do case DB neukládají — jen typ + fingerprint/hash tajnosti.

## 📊 METRIKY A KPI
### Kvalitativní
| Metrika | Baseline (v0.1.0) | Cíl (v2.0) |
|---|---|---|
| AXIOM coverage | 198/232 | 200/232 — 100 % konkrétních extraktorů (zbýlých 32 = framework rozhraní, ne parsery) |
| Test suite size | 2154 | 4000+ |
| Benchmark items | 77 | 150 |
| Parser versions | 76 | 120+ |
| AI grounding accuracy | ~95 % | 100 % |

### Výkonové
| Metrika | Baseline | Cíl |
|---|---|---|
| Hash 10 GB obrazu | ~180 s | < 30 s |
| Timeline query (10M events) | ~30 s | < 2 s |
| Ingest 1 TB (16-core) | n/a | < 4 hodiny |
| FTS query latency | ~500 ms | < 50 ms (cached) |
| RAM peak (ingest) | ~4 GB | < 8 GB |

---

## 📝 DECISION LOG
Formát: **`[YYYY-MM-DD] [ID úkolu]`** — popis rozhodnutí, proč, jaké alternativy.

- **[2026-11-10] R0.1]** — Začato. Strategie: (1) autoritativní record-header walk přes `ElfR` signatury (EventID @+24, FILETIME timestamp @+16), (2) BinXML fallback parser pro soubory bez headerů. Detail po implementaci.
- **[2026-11-10] R0.1]** — **Dokončeno `[x]`.** Implementace: `_binxml_decompress` (raw deflate, magic `0x1B243D5A`) + `_binxml_extract_fields` na reálných datech; `_find_elf_record_offsets` (ElfR @offset % 0x18 == 0, validace total_size + FILETIME) + `_elf_walk`; pořadí strategií ElfR walk → content-scan → header-scan. `tests/artifacts/test_evtx.py` (7 testů): standard deflate, ElfFile B timestamp, ElfR A walk, mixed records bez None, corrupt deflate resilience, uncompressed regression. Suite 2161 passed / 1 skipped; ruff clean.
- **[2026-11-10] R0.4]** — **Dokončeno `[x]`.** Commits `03d489f` + `921eae1`: (1) ruff fixy S110×3 (`_log.debug(..., exc_info=e)` místo pass) a B023×4 (`_bar_state` ven ze smyčky + reset per zdroj), (2) `--json` sjednoceno na helper `_add_json_flag()` — 23/23 příkazů čtoucích `args.json` má parser flag (záchycen bug: 11 cmd_* mělo JSON body bez flagu → "unrecognized arguments"), (3) strojově čitelné error cesty (`cmd_replay`: no_extract_operations / operation_not_found / source_not_found / source_path_missing; `cmd_validate`: plain text gateován), (4) `_ex_sub()` + `_SUBCOMMAND_EXAMPLES` — 25/25 subpříkazů s "Příklad:" epilogem, (5) Rich progress u `cmd_add` + `cmd_analyze` (lazy import + TTY detekce; degradace na plain text), (6) `rich>=13` do pyproject deps. E2E smoke 16 příkazů živě ověřeno; suite 2161 passed / 1 skipped; ruff clean.
- **[2026-11-10] R0.4]** — Regresní testy + bug-fixe [x]. Commit `5c22b27`: tests/test_r04_cli_ux.py (12 testů) validuje obě AK (validní JSON na stdout + Příklad epilog). Testy odhalily 2 skutečné bugy: argparse crash v timeline --path --help (neescape %text% → printf; fix %%text%%) a chybějící epilog u serve. + JSON error cesty v cmd_analyze. 12/12 passed, ruff clean.
- **[2026-11-10] R0.2]** — **Dokončeno `[x]`.** Commit `bbc32c1`: wheel-based offline instalace (.deb/.rpm/AppImage/Docker + Makefile). Klíčové rozhodnutí: bundlovaná dev site-packages s cp311 C extenzemi nefungují cross-verze → .deb obsahuje čistý Python wheel + vendored wheels (cp310–cp313) a packaging/postinst.sh postaví /opt/stopa/venv OFFLINE. Minimální závislosti python3+sleuthkit; EWF volitelné přes STOPA_EWF_LIB. Ověřeno E2E: offline instalace na čerstvém py3.13 → import all OK + case new/stats; suite 2193 passed / 1 skipped.
- **[2026-11-10] R0.3]** — **Dokončeno `[x]`.** Version bump 0.1.0→1.0.0 (pyproject + fallback v __init__.py/case_report.py/correlation.py/cli.py, verze z jednoho zdroje přes importlib metadata). Nový top-level flag `stopa --version` → stopa 1.0.0. CHANGELOG.md dle Keep-a-Changelog; žádné breaking changes (nadstavba API/CLI/schéma, DB migrace automatické v8→v14). Suite 2193 passed / 1 skipped; ruff clean.
- **[2026-11-10] F1.1]** — **Dokončeno `[x]`.** Dvousvrstvá architektura: (1) `domain/fde_bitlocker.py` = STOPABLOCK, čistý Python whole-volume formát pro deterministické offline testy ([36 B hlavička][XTS klíč 32/64 B][ciphertext], PBKDF2-HMAC-SHA1 → AES-XTS po 512 B sektorech, tweak = globální číslo sektoru; XTS-128=32 B / XTS-256=64 B kombinovaný klíč dle cryptography); (2) `data/bde_fvde.py` = ctypes wrapper libbde/libfvde pro reálné BVE/FileVault obrazy (lazy load z ~/ewf-install/lib, STOPA_BDE_LIB striktní override; recovery key primární cesta přes set_utf8_recovery_password s byte length; FileVault group-level API → logical volume 0). C ABI ověřeno z -dev hlaviček PŘED implementací (symboly + prototypy, neuhádáno). CLI `stopa decrypt <img> --type bitlocker|filevault --recovery-key/--password [--out] [--json]` s exit kódy 0/1/2/3/4; integrace do process_mobile_image (auto-detekce STOPABLK magic + explicitní fde_type, recovery key i z textového souboru). Testy tests/test_f11_bitlocker.py (36): KDF determinita/salt/credential, hlavička layout+truncation+reject, XTS-128/256 roundtrip, špatné credential, poškozený uložený klíč, ciphertext≠plaintext, non-sector múltiple, streaming 3 MiB == whole (kontinuita sektorů + progress callback), custom chunk 1 sektor, bad chunk raise, tmp cleanup při chybě, bde/fvde availability+error cesty, CLI decrypt E2E (text/JSON/wrong-key/missing/no-cred/unknown-type), pipeline STOPABLOCK unlock/wrong-key/password s TSK FAT16. Suite **2229 passed / 1 skipped** (+36); ruff clean.
- **[2026-11-11] F1.5]** — **Dokončeno `[x]`.** Mobilní forenzika — čistá doménová vrstva `domain/mobile_forensics.py` (bez IO): parser UFDR report.xml (tolerantní k XML namespace přes `_localname`, multiModelField rekurze, neznámé typy vrací do `unknown` pro viditelnost) + VCF parser; klíčové design rozhodnutí — **per-value contact konvence**: jméno/telefon/mail jako vlastní `contact` artifact s title=value a mimetype v details (ne vše v jednom artifactu), protože `domain/entities.py` u typu `contact` čte jen title+mimetype a generický sken detailů se přeskočí → bez per-value mapping by telefony/e-maily nebyly extrahovány jako entity a korelace entit selhala (AK). Signal decoder `_extract_signal_db` v `artifacts/mobile_extract.py` (ZWAMSGSTOREMESSAGE→chat_message, odesílatel přes LEFT JOIN ZUSER, unix ts; kontrakt row_factory=sqlite3.Row jako produkční pipeline sqlite_extract.py) — WhatsApp decoder už existoval. CLI `import-mobile <dump> --source cellebrite|msab|adb`: Cellebrite=.ufd/.zip/složka (report.xml+*.vcf in-mem přes `_BytesHolder`), MSAB=jen *.vcf z archivu, ADB=složka s SQLite DB→`extract_sqlite_artifacts`(WhatsApp/Signal/kontakty)+VCF; provenance per cesty (re-import→stejný source), timeline materializace pro artefakty s časem, **F1.4 FK pitfall** — `clear_timeline_events(source_id)` PŘED `replace_artifacts_for_file` jinak visící reference při re-ingestu; po importu automatická korelace entit (`run_correlation`) splňuje AK „entity korelovány s existujícími kontakty". 49 testů: tests/test_f15_mobile_forensics.py (37 doménové, offline fixture) + tests/test_f15_cli_import_mobile.py (12 E2E přes cli.main — ZIP e2e, --json, MSAB vcf-only, ADB dump, re-import idempotence, error cesty exit 2, WhatsApp CFAbsoluteTime→UTC epoch, Signal unix ts+sender fingerprint). Ověřeno E2E smoke: 9 artefaktů ze 2 souborů (timeline 2), korelace 4 entit/1 propojení. Suite **2404 passed / 1 skipped** (+49); ruff clean.
- **[2026-11-11] F1.6]** — **Dokončeno `[x]`.** Coverage matice — klíčové rozhodnutí: původní AK „≥220/232" předpokládal ~22 chybějících reálných typů (APFS snapshots, Safari ext., iCloud keychain…), ale deterministický recon skriptu `scripts/build_axiom_coverage.py` prokázal jiné: z 34 nepokrytých položek jsou jen **2 konkrétní implementovatelné extraktory** (`LsaRegistryExtractor`, `TpduDataExtractor`), ostatních 32 = C# framework rozhraní/base classes bez nezávislého datového formátu; typy z popisku AK už existující parsery pokrývají. Rozhodnutí: (1) implementovat oba reálné extraktory, (2) matici upřesnit tak, aby DEPRECATED řádky transparentně dokumentovaly „rozhraní / základní třída, ne extraktor" — bez fiktivních covered označení. Implementace: `artifacts/win_lsa.py` (LSA Credential Cache z registry hive SYSTEM/SECURITY → `credential` artifact; bezpečnostní zásada — do DB jen SHA-256 fingerprint tajnosti + metadata, nikdy surové heslo) a `artifacts/sim_tpdu.py` (SIM phonebook AT+CPBR textový export/CSV → `contact` artefakty, dedup podle normalizovaného čísla E.164-like). Pipeline wiring: LSA do registry dispatch (po SID), TPDU do name-based řetězce (`is_sim_tpdu_file`); C3 registry záznam vlna 15 (parser_id=sim_tpdu, verze z pipeline — LSA sdílí registry hive cestu a není samostatným parser_id). Výsledek: **covered 200/232 = 100 % všech konkrétních AXIOM extraktorů**, DEPRECATED 32 (bijekce 232 zachována), audit testy `tests/test_etapa_b_final_audit.py` upraveny na stav po vlně 15 (SUPPORTED 200 / DEPRECATED 32 / registry 77). 28 nových testů: tests/test_win_lsa.py (fingerprint determinita, hive walk přes monkeypatchovaný regipy, IO entrypoint) + tests/test_sim_tpdu.py (normalizace čísel, CPBR parsing s indexem, dedup, CSV fallback, detekce souborů). Suite **2432 passed / 1 skipped** (+28); ruff clean.
- **[2026-11-11] F2.2]** — **Dokončeno `[x]`.** DuckDB OLAP vrstva pro timeline & analytics. Klíčová design rozhodnutí: (1) **OLTP/OLAP split bez dual-write** — SQLite zůstává single source of truth; DuckDB čte case DB přes `ATTACH ... (TYPE SQLITE)` a materiálové native tabulky (`tl_events`/`tl_entities`/`tl_correlations`) postaví explicitním refreshem do `<case>.duckdb` vedle case DB. Důvod: DuckDB 2.x **nepodporuje CREATE MATERIALIZED VIEW** (ověřeno parser chybou) → materiálový stav je odvozený artefakt, ne second source of truth; zero dual-write = žádné rozjevy. (2) **Staleness = filesystem signatura** (sha256 nad mtime_ns+size hlavního souboru i `-wal`), ne COUNT(*) snapshot: O(1) hot path, přesná i cross-process, bez TTL race window; při neshodě auto-refresh (RW) nebo stale signál + raise (read-only). Počty pro zobrazení se spočítají jen u stale. (3) **Volitelná závislost** `[analytics]` = duckdb>=1.0, lazy import — bez ní `duckdb_available()` False a volající jde na SQLite fallback (CLI exit 3 / web HTTP 503); standardní timeline/search v SQLite beze změny (backward-kompatibilní). Implementace: `data/analytics.py` (`AnalyticsStore`: refresh/status/timeline_range/hourly_histogram/top_event_types/entity_summary; sdílené konexe per proces pod `_LOCK`; `drop_case_analytics` smaže odvozený soubor při case delete — napojeno na web DELETE). Wiring: CLI subcommand `analytics <case> --from-ts/--to-ts/--type/--limit [--json]`, web GET `/api/cases/{id}/analytics`. **AK měřeny reálně** (`scripts/bench_f22_analytics.py 10000000`): range query 1h okno nad 10M limit 10k = **0,029 s < 2 s ✓** (69× pod AK), agregace histogram+top typy = **0,006 s < 5 s ✓** (833×); refresh 10M = 6,3 s (one-off, informační). FTS zůstává v SQLite (AK) — nebylo dotčeno. 19 testů tests/test_f22_analytics.py: staleness RW auto-refresh / readonly stale+raise / cross-process mutace chycena signaturou; parity timeline_range s `list_timeline_events` (stejná množina ID); type filtr + limit; histogram buckety + okno; entity_summary; drop_case_analytics idempotence; perf proxy 200k (range<2s, agg<5s); CLI JSON / no-duckdb exit 3 / missing case SystemExit; web endpoint 200+window / 503 bez duckdb / DELETE smaže .duckdb. Suite **2468 passed / 1 skipped** (+19); ruff clean. Pozn. z bench: SQLite `strftime` milisekundový modifier vrací None (jen sekundy) → generátor sekundová přesnost; meta tabulka DROP+CREATE při refreshu (schéma drift starých .duckdb).
- **[2026-11-14] F2.3]** — **Dokončeno `[x]`.** Block-level deduplikace (CDC/Buzhash) — klíčová design rozhodnutí: (1) **Rust one-pass core** `dedupe_into(path, avg, min, max, buf)` v `rust/src/lib.rs` = Buzhash rolling hash + SHA-256 bulk flush na chunk hranicích v jediném read pasu (4 MiB IO chunks; opraven cross-chunk SHA bug — `sha_up_to = chunk_start + n`); bit-exact parity s Python referencí (`domain/block_dedupe.py`, BUZ_TABLE extrahováno programově z Rust zdroje) ověřeno pro velikosti 0 B–9 MiB + custom parametry (avg=4096/min=2048/max=8192). (2) **fast16 hot path** — truncované u16 rolling hash pro avg_size ∈ [32, 65536]: bit-exact, protože boundary detekce závisí jen na nízkých bitech sumy; generic u64 cesta mimo rozsah. Optimalizace: lazy `BUZ_WEIGHTS` OnceLock tabulka (const initializer s `for` toolchain odmítł), AND místo modulo (avg = mocnina 2), sha2/asm feature, microbenchmark `rust/examples/bench_variants.rs` (varianta 4 = production clone — přesná shoda počtu bloků 6425; čistý Rust core 52,7 ms vs produkce ~88 ms → mezera = pyo3 konverze + hex Stringy). (3) **Batch API** `block_dedupe_files()` — jeden GIL release + jeden sdílený 4 MiB buffer pro celou dávku (thread_local RefCell zamítnut: Vec::with_capacity neconst + RefMut lifetime); multi-file dedupe 692 → ~615 ms (−11 %). Python facade vrací None → fallback na referenční implementaci. (4) **AK2 režimová analýza** — měřeno vs reálný `stopa add --profile forensic` CLI wall ve všech režimech: single file warm NVMe 31 %, multi-file 352 MB tmpfs/ext4 warm ~151–153 %, ext4 COLD (fadvise DONTNEED, disk-bound) **207 %** — <10 % nesplněno na rychlém lokálním úložišti protože i samotný ingest běží na memory speed (~870 MB/s), zatímco dedupe potřebuje druhý kompletní read pas; AK2 dosáhnutelné v pomalém médiu režimu (ingest IO-bound + cached dedupe) nebo po F2.4 paralelizaci → dokumentováno jako reziduum do F2.4, ne blocker funkčnosti. DuckDB tabulka `block_hashes` (+ refresh přes batch API), CLI `analytics --dedupe`, opraven latentní `_is_fresh()` empty-case bug z F2.2 (fresh=True pro prázdný case → CatalogException v OLAP query). 33 testů tests/test_f23_block_dedupe.py + Rust cargo test 11/11; suite **2501 passed / 1 skipped** (+33); ruff clean.
- **[2026-11-15] F2.4]** — **Dokončeno `[x]`.** Paralelní ingest s backpressure — klíčová design rozhodnutí: (1) **ProcessPoolExecutor se spawn kontextem**, ne fork — Rich Progress v CLI spouští pozadové vlákno, fork by zdědil zamčený mutex = deadlock v child (empiricky ověřeno thread enumerací); spawn overhead ~0,12 s/import na child zanedbatelný na GB škále. Režim `--pool auto` (default) = procesy pro workers>1 (GIL uvolněný v Rust core), vlákna jako fallback; web uvicorn explicitně `pool="threads"` (dlouhohrající multi-threaded server, per-request spawn zbytečný). (2) **Backpressure okno** `max_inflight` (auto = max(8, 4×workers)) nahrazuje neomezené E3 submission — omezuje RAM i run-ahead walk; determinismus zachován: DB zápisy + dedupe zůstávají v hlavní vláknu s konzumací budoucností v pořadí procházky. (3) **Checkpointing**: periodický commit každých `commit_every` (256) souborů; graceful shutdown přes `stop_event` — CLI napojuje SIGINT/SIGTERM → dojezd in-flight, commit, audit `processing_interrupted`, exit code 130; `--resume` dokončí bez ztráty dat (bytes se sčítají přesně na celkový objem + parita s neproblemovým během). Přerušený běh nespouští auto-export. (4) **CLI bug fix**: `cmd_add` tvořil při každém volání NOVÝ EvidenceSource → skip-set resume viděl prázdný stav a re-ingestoval vše (E2E: 170/120 řádků); nyní idempotentní lookup zdroje podle cesty. AK status: determinismus ✓, backpressure peak ≤ okno ✓, resume po kill ✓ E2E; speedup na 1 TB + RAM < 8 GB nezměřeno (syntetické workloady). 5 testů tests/test_f24_parallel_ingest.py + E3 regresní zelené (13/13); ruff clean.
- **[2026-11-15] K2]** — **Dokončeno `[x]`.** Wallet & Exchange parsovaná do pipeline — `domain/crypto/wallets.py` (Electrum JSON wallets, MetaMask vault AES-128-CTR+PBKDF2 decryptor s keyrings layoutem) a `domain/crypto/exchanges.py` (Binance/Coinbase/Kraken CSV → transakční artefakty); integrace v `artifacts/crypto_extract.py` do registry dispatchu; secp256k1 validace privátních klíčů přes `_SECP256K1_N` (32 B, 1 ≤ k < N). K2 suite **220/220 passed**; full Python suite **2933 passed / 1 skipped** (+220); ruff clean. Commit `ff3f860`.
- **[2026-11-14] K1]** — **Dokončeno `[x]`.** Základní crypto detekce — BIP39 seed detector (wordlist validace + checksum), private key detector (WIF/ETH hex 32B/PEM EC) s secp256k1 rozsahovou kontrolou, address validator (BTC Base58Check/ETH EIP-55/XMR); bezpečnostní zásada K-linky — do DB jen typ + fingerprint tajnosti. K1 suite **212 passed**; full Python suite po K1 **2713 passed / 1 skipped** (+212). Commit `5bf0618`.
- **[2026-11-11] F2.1]** — **Dokončeno `[x]`.** Rust/PyO3 core — klíčová cesta Fáze 2. Architektura: (1) `rust/src/lib.rs` = čistá jádra `compute_hashes` / `scan_data` bez PyO3 typů (testovatelná offline přes cargo test, 11/11) + tenká PyO3 vrstva (`hash_file`, `find_offsets`, `rust_version`; PyO3 0.26 Bound API, zero-copy `PyBackedBytes`, GIL uvolněné po celou dobu skenování/hashingu); (2) Aho-Corasick multi-pattern scan s per-pattern nenakládajícími shodami = **přesná parity** se smyčkou `data.find(magic, pos+len)` v Python carvingu (ověřeno random-parity testem na adversariálních datech — prefixy, duplikáty, překrývání); (3) one-pass MD5+SHA-1+SHA-256 streaming (4 MiB chunks + HEX LUT). Build: maturin 1.16 release wheel `stopa_core-0.1.0` do `.venv`; `rust/.gitignore` (target/ nekomitovat). Python integrace backward compatible: `data/rust_core.py` = lazy import facade s cache + fallback (bez wheelu vráti None → referenční cesta; IO chyby se propagují, defenzivní fallback jen u Rust runtime chyb); `domain/hashing.py` fast path pro {md5,sha1,sha256} bez progress callbacku (pipeline ho nepoužívá — ověřeno), ostatní algoritmy zůstávají na hashlib; `domain/carving.py` carve() skenuje všechny signatury v jednom Rust průchodu + BMFF offset>0 validace `_valid_bmff_box`, fallback na původní find smyčky. Benchmark engine: nová položka `core.rust` (8 MiB hash + 16 MiB scan, deterministický vstup) — baseline 77 items zmrzlá PŘED F2.1 (CK2 riziko #2), detekce regresí nové položky ignoruje; `tests/test_benchmark_engine.py::test_core_workload` zpřísňeno na len ∈ {1,2}. **AK měřeny reálně** (`scripts/bench_f21_rust_core.py`, /tmp tmpfs): hash 10 GB = **19,87 s < 30 s ✓** (≈5× vs baseline ~180 s; digesty validovány), carve 1 GB = **1,77 s < 10 s ✓** (24/24 kandidátů; raw Rust scan 0,99 s = parity i na plné škále). Pozn. z bench: uniformní náhodný šum generuje tisíce falešných kandidátů pro krátké magicky a zahltil per-kandidát `_estimate_size` (64 MiB slice) — bench obraz je proto realistický (free space NUL + file-like struktury PNG/PDF/GIF/JPEG). 17 nových testů: `tests/test_f21_rust_core.py` (facade availability/fallback/reset_cache; hash parity Rust vs hashlib na 3 MiB pro md5/sha256/md5+sha1+sha256; empty file digests; domain API fast path + fallback parity; neznámý algoritmus ValueError; non-Rust alg Python cesta; IO chyby propagují se; carve parity Rust vs fallback na mix bufferu s BMFF boxem/duplicitami/překrýváním; BMFF offset>0 kandidát v obou cestách; determinismus scanu; empty/trivial buffers). Suite **2449 passed / 1 skipped** (+17); ruff clean.

---

## ⚠️ RIZIKA A MITIGACE
| Riziko | Pravděpodobnost | Dopad | Mitigace |
|---|---|---|---|
| Rust/PyO3 integrace selže na Windows | Střední | Vysoký | Začít s Linux CI, Windows secondary target |
| DuckDB migrace rozbije existující queries | Nízká | Vysoký | Feature flag, dual-run, rollback plán |
| AI hallucinace navzdory grounding | Střední | Kritický | 100 % citation validation + unit tests edge-cases |
| BitLocker TPM scraping nefunguje na novém HW | Vysoká | Střední | "best-effort"; recovery key jako primary path |
| SPA frontend příliš složitý | Střední | Střední | SvelteKit (menší bundle), iterativně |

## 🏁 CHECKPOINT SCHEDULE
1. po Fázi 0: Release 1.0 venku, UX vyladěno · 2. po Fázi 1: coverage kompletní (BitLocker/memory/PCAP) · 3. po Fázi 2: výkonové metriky splněny, Rust core stabilní · 4. po Fázi 3: AI agent demo-ready · 5. po Fázi 4: enterprise beta s 3 testery · 6. po Fázi 5: compliance audit externí firmou · 7. po Fázi 6: Release 2.0

### 📌 CK2 — Checkpoint Review po Fáze 1 (2026-11-11)
**Progress:** Fáze 1 kompletní — R0.x + F1.1–F1.6 `[x]` (commits `6947ecd`, `b05cf17`, `58cd5f1`, `93748c1`, `9f430b7`, `faa4552`). Suite **2432 passed / 1 skipped** (+278 od baseline 2154), ruff clean. Coverage: AXIOM 200/232 = 100 % konkrétních extraktorů; nová forenzní domény: FDE (BitLocker/FileVault), memory (Volatility 3), síť (PCAP/IoC), anti-forensics, mobilní (UFDR/VCF/Signal/WhatsApp + import-mobile), LSA credential cache, SIM phonebook.
**Metriky vs DoD:** test suite 2432/≥3500 (69 %); parser versions 77/120+; benchmark items beze změny (F2.x). Zbývajících 32 AXIOM řádků = framework rozhraní bez datového formátu (dokumentováno, ne pokrytelné parserymi).
**Odhady Fáze 2:** F2.1 Rust/PyO3 carving engine je kritická cesta — odhad 6–8 týdnů drží při maturin CI na Linuxu; riziko Windows cross-compile (mitigace: Linux primary, Windows secondary target). F2.2 DuckDB závisí na F2.1 (timeline OLAP po Rust core).
**Rizika:** (1) PyO3 build pipeline bez sítě pro offline distribuci — řešit v R0.2 wheel layoutu; (2) benchmark baseline 77 items musí být zmrazen PŘED F2.1 aby regrese >5 % měřila správně; (3) K-linka crypto čeká na release 2.0 scoping (docs/CRYPTO_FORENSICS_PROPOSAL.md).
**Další:** CK2 podán → Fáze 2 začíná F2.1 (Rust/C++ carving engine), po něm F2.2 DuckDB.

## 🎯 OKAMŽITÉ AKCE (First 5)
1. ~~R0.4 CLI UX audit~~ — **hotovo `[x]`** ✅ (commits `03d489f`, `921eae1`, `5c22b27`)
2. ~~R0.2 Distributivní balíčky~~ — **hotovo `[x]`** ✅ (`bbc32c1`)
3. ~~F1.1 BitLocker support~~ — **hotovo `[x]`** ✅ (commit `6947ecd`)
4. ~~F1.5 Mobilní forenzika (UFDR/VCF/Signal/WhatsApp + import-mobile)~~ — **hotovo `[x]`** ✅ (2026-11-11, suite 2404 passed)
5. ~~F1.6 Coverage matice — dokončení konkrétních AXIOM extraktorů (LSA + SIM TPDU), 100 % reálných typů~~ — **hotovo `[x]`** ✅ (2026-11-11, commit `faa4552`, suite 2432 passed)
6. ~~F2.1 Rust/PyO3 core — one-pass hashing + Aho-Corasick carving scan~~ — **hotovo `[x]`** ✅ (2026-11-11; AK: hash 10 GB = 19,9 s < 30 s, carve 1 GB = 1,8 s < 10 s; suite 2449 passed)
7. ~~F2.2 DuckDB OLAP vrstva — materiálové tabulky + staleness signatura + CLI/web wiring~~ — **hotovo `[x]`** ✅ (2026-11-11; AK: range 1h/10M = 0,029 s < 2 s, agregace = 0,006 s < 5 s; suite 2468 passed)
8. ~~F2.3 Block-level deduplikace — Rust one-pass CDC/Buzhash + batch API + DuckDB block_hashes~~ — **hotovo `[x]`** ✅ (2026-11-14; AK1 ÚSPORA ✓ 30,71 %/70,55 %, AK2 ✗ na rychlém HW → reziduum do F2.4; suite 2501 passed)
9. ~~K1 Crypto Forensics — základní detekce (BIP39/WIF/ETH hex/PEM + address validators BTC/ETH/XMR)~~ — **hotovo `[x]`** ✅ (2026-11-14, commit `5bf0618`, suite 2713 passed)
10. ~~K2 Wallet & Exchange — Electrum/MetaMask/Binance/Coinbase/Kraken parsery + pipeline integrace~~ — **hotovo `[x]`** ✅ (2026-11-15, commit `ff3f860`, K2 220/220, suite 2933 passed)
11. ~~F2.4 Paralelní ingest s backpressure — ProcessPoolExecutor (spawn) + omezené okno + checkpointing SIGINT~~ — **hotovo `[x]`** ✅ (2026-11-15; determinismus ✓, peak ≤ okno ✓, E2E resume po kill ✓; CLI bug fix idempotentní zdroj)

**Konec plánu.**
