# STOPA — FEATURE REGISTRY (registr funkcí)

Rozlišení stavů: IMPLEMENTED ≠ TESTED ≠ VERIFIED.
- **impl:** implementováno | **test:** testováno (unit/integration) | **verif:** nezávisle ověřeno (plná sada + ruff + commit)
Stavy: plně funkční / částečně funkční / experimentální / nefunkční
Verze = verze parseru v C3 registry (`PARSER_VALIDATIONS`) u verzovaných parserů, jinak verze aplikace 0.1.0.

## Evidence & Integrity (P0 Core C1–C4)

| Feature ID | Název | Popis | Modul | Verze | impl | test | verif | Stav | Omezení | Úkoly |
|---|---|---|---|---|---|---|---|---|---|---|
| F-001 | Evidence Model + Lineage | Důkazní model s provenancí a lineage řetězem artifact→zdroj | domain/evidence_model.py, lineage.py | 0.1.0 | ✓ | ✓ (26) | ✓ `943753b` | plně funkční | — | STP-001 |
| F-002 | Integrity SHA-256/MD5 + Ed25519 | Hashování důkazů, tamper detekce, kryptografické podpisy | domain/integrity.py, hashing.py | 0.1.0 | ✓ | ✓ (29) | ✓ `8b09071` | plně funkční | SHA-512 chybí | STP-002, STP-022 |
| F-003 | Audit log s hash chainingem | Append-only audit log s hash řetězem (tamper-proof) | data/db.py | 0.1.0 | ✓ | ✓ (sada) | ✓ `a0e4577` | plně funkční | — | STP-003 |
| F-004 | Reproducibility Engine | Reprodukovatelné operace s DB + idempotentní migrace | domain/reproducibility.py, data/db.py | 0.1.0 | ✓ | ✓ (20) | ✓ `a554a20` | plně funkční | — | STP-004 |

## Export & Report (C5, L)

| Feature ID | Název | Popis | Modul | Verze | impl | test | verif | Stav | Omezení | Úkoly |
|---|---|---|---|---|---|---|---|---|---|---|
| F-005 | Export CSV/JSON + manifest | Export artifactů/timeline/korelací s SHA-256 manifestem pro reprodukovatelnost | domain/export.py, cli.py | 0.1.0 | ✓ | ✓ (sada) | ✓ `5b10a95` | plně funkční | chybí STIX/UCO/Plaso/JSONL/XML | STP-005, STP-023 |
| F-006 | HTML report 9 sekcí + PDF | Soudně použitelný report: chain of custody, artifacty, findings, manifest+podpis, audit trail, timeline, korelace | presentation/case_report.py | 0.1.0 | ✓ | ✓ (16) | ✓ `42ade02` | plně funkční | 9/20 sekcí; PDF volitelné (weasyprint) | STP-020 |

## Benchmark & Validation (C6, I)

| Feature ID | Název | Popis | Modul | Verze | impl | test | verif | Stav | Omezení | Úkoly |
|---|---|---|---|---|---|---|---|---|---|---|
| F-007 | Benchmark Engine + detekce regresí >20% | Deterministické workloads, měření času/RAM, regresní detekce proti baseline | domain/benchmark.py, data/benchmark_engine.py | 0.1.0 | ✓ | ✓ (18) | ✓ `42ade02` | plně funkční | neběží v CI | STP-006 |
| F-008 | C3 Parser Validation Registry (13 parserů) | ID+verze+formáty+omezení každého parseru; 1:1 sync s pipeline vynucen build_registry() | domain/validation_registry.py | 0.1.0 | ✓ | ✓ (10) | ✓ `afc49a0` | plně funkční | — | STP-006, STP-013..015 |

## Disk images & Filesystems (B, C)

| Feature ID | Název | Popis | Modul | Verze | impl | test | verif | Stav | Omezení | Úkoly |
|---|---|---|---|---|---|---|---|---|---|---|
| F-010 | EWF/libewf (E01) | Čtení E01/EWF kontejnerů přes libewf | data/ewf_container.py, image_pipeline.py | 0.1.0 | ✓ | ✓ (41) | ✓ sada | plně funkční | `EWF available: True` ověřeno | — |
| F-011 | RAW/IMG přes TSK + carving volného prostoru | Filesystem analýza (NTFS/FAT/APFS), MFT, carving ukrytých souborů | data/tsk*.py, domain/carving.py | 0.1.0 | ✓ | ✓ (35+21) | ✓ sada | plně funkční | — | — |
| F-012 | FDE dešifrování AES-CBC/FBE/LUKS | Dešifrování šifrovaných diskových obrazů | domain/fde*.py | 0.1.0 | ✓ | ✓ (50) | ✓ sada | plně funkční | — | — |

## Artifact Engine (D) — 20 parser modulů, C3 registry 13 verzovaných

| Feature ID | Název | Popis | Modul | Verze | impl | test | verif | Stav | Omezení | Úkoly |
|---|---|---|---|---|---|---|---|---|---|---|
| F-020 | LNK shorthands v2.0 | Windows .lnk odkazy (cíle, timestamps) | artifacts/win_lnk.py | 2.0 | ✓ | ✓ (sada) | ✓ | plně funkční | — | — |
| F-021 | Prefetch | Záznamy o spuštění aplikací z Windows Prefetch | artifacts/win_prefetch.py | 1.0 | ✓ | ✓ (sada) | ✓ | plně funkční | C3 registrován | — |
| F-022 | Jump Lists | Nedávno používané soubory/programy | artifacts/win_jumplist.py | 1.0 | ✓ | ✓ (sada) | ✓ | plně funkční | — | — |
| F-023 | EVTX event log | Windows Event Log (Audit*, GoogleAccessLog) | artifacts/win_eventlog.py | 1.0 | ✓ | ✓ (sada) | ✓ | plně funkční | — | — |
| F-024 | Amcache + ShimCache (registry průchody) | Záznamy o spuštění aplikací z registry hivy | artifacts/win_amcache.py, win_shimcache.py | 1.0 | ✓ | ✓ (test_e7 21) | ✓ | plně funkční | sekundární průchod `_extract_registry_all` | — |
| F-025 | USN Journal | NTFS change journal (změny souborů) | artifacts/win_usn.py | 1.0 | ✓ | ✓ (sada) | ✓ | plně funkční | C3 registrován | — |
| F-026 | Registry hive generic (regipy) | Generická extrakce registry klíčů/hodnot | artifacts/registry_extract.py | 1.0 | ✓ | ✓ (13) | ✓ | plně funkční | C3 registrován | — |
| F-027 | Browser history/iMessage/SMS/hovory/WhatsApp (SQLite) | Extrakce z SQLite DB (prohlížeče, iMessage, SMS, WhatsApp) | artifacts/sqlite_extract.py | 1.0 | ✓ | ✓ (20) | ✓ | plně funkční | C3 registrován | — |
| F-028 | iCloud Messages CSV/XLSX | Parsery cloud exportů zpráv | artifacts/imessage_cloud.py | 1.0 | ✓ | ✓ (29) | ✓ | plně funkční | name-based detekce | — |
| F-029 | Mobilní logical exporty (Samsung contacts/sms/calllog) | Kontakty/SMS/hovory z mobilních logical exportů | artifacts/mobile_extract.py | 1.0 | ✓ | ✓ (10) | ✓ | plně funkční | — | — |
| F-030 | **Email mbox/EML** (ETAPA B vlna 1) | mbox+eml emaily, MIME body, UTF-8/16 | artifacts/email_mbox.py | 1.0 | ✓ | ✓ (17) | ✓ `afc49a0` | plně funkční | name/content-based detekce; MIME text/plain+html | STP-013 |
| F-031 | **WiFi WLAN profile XML** (ETAPA B vlna 1) | WLAN profily: SSID/auth/cipher | artifacts/win_wlan.py | 1.0 | ✓ | ✓ (12) | ✓ `afc49a0` | plně funkční | namespace-agnostický; C3 registrován | STP-013 |
| F-032 | **Scheduled Tasks XML** (ETAPA B vlna 1) | Task Scheduler XML: akce+triggery, UTF-16 LE/BE BOM | artifacts/win_schedtask.py | 1.0 | ✓ | ✓ (11) | ✓ `afc49a0` | plně funkční | C3 registrován | STP-014 |
| F-033 | **Netstat/connstat text** (ETAPA B vlna 1) | Síťové spojení z netstat/ss outputů (Windows+Unix, IPv4/IPv6/wildcard) | artifacts/net_connections.py | 1.0 | ✓ | ✓ (12) | ✓ `afc49a0` | plně funkční | token-based parser; C3 registrován | STP-014 |
| F-034 | **Clipboard registry** (ETAPA B vlna 1) | Obsah schránky z NTUSER.DAT, CF_* formáty, UTF-8/UTF-16LE detekce | artifacts/win_clipboard.py | 1.0 | ✓ | ✓ (12) | ✓ `afc49a0` | plně funkční | sekundární průchod NTUSER.DAT | STP-015 |
| F-035 | **SID extraction** (ETAPA B vlna 1) | Uživatelé SIDs z SAM/SECURITY + ProfileList, source_hint podle názvu souboru | artifacts/win_sids.py | 1.0 | ✓ | ✓ (12) | ✓ `afc49a0` | plně funkční | sekundární průchod registry hivy | STP-015 |

## Analytika & AI (E, F, H)

| Feature ID | Název | Popis | Modul | Verze | impl | test | verif | Stav | Omezení | Úkoly |
|---|---|---|---|---|---|---|---|---|---|---|
| F-040 | Timeline + anomálie | Unifikovaná timeline s detekcí anomálií a rozporů | domain/timeline_anomaly.py | 0.1.0 | ✓ | ✓ (sada) | ✓ | plně funkční | — | STP-018 |
| F-041 | Entity Resolution 2.0 (4 confidence, normalizace, merge candidates) | Normalizace účtů/čísel/mailů, 4 úrovně confidence, detekce duplicit entit | domain/entity_resolution.py, entities.py, correlation.py | 0.1.0 | ✓ | ✓ (26+e4/e5/e10) | ✓ `2244d95` | plně funkční | schéma v11; backward compat mapping | STP-009 |
| F-042 | AI orchestrace — 5 agentů, routing, fail-closed validace | Deklarativní analytické agenty s Pydantic validací a citacemi ke zdrojům | intelligence/agents.py, ai_orchestrator.py | 0.1.0 | ✓ | ✓ (25) | ✓ `61f9a03` | plně funkční | AI volitelná; LM Studio port 1234 | STP-007 |
| F-043 | Forensic RAG — 3 vrstvy, citace, prompt injection ochrana | Retrieval napříč case/technical/knowledge vrstvami s `<untrusted_source>` izolací | intelligence/rag.py | 0.1.0 | ✓ | ✓ (30) | ✓ `97cd4d6` | plně funkční | docs/formats + docs/methodology volitelné/prázdné | STP-008 |
| F-044 | AI governance + PII redaktor | Governance dokumentace + PII redakce před inference + audit modelových volání | domain/pii_redaction.py, ai_orchestrator.py, ai_assistant.py, web/app.py, cli.py | 0.1.0 | ✓ | ✓ (23) | ✓ (tento commit) | plně funkční | toggle `ai_redact_pii` default ON; audit E11+I1 do analysis_operations | STP-019 |

## UI & Performance (N, O)

| Feature ID | Název | Popis | Modul | Verze | impl | test | verif | Stav | Omezení | Úkoly |
|---|---|---|---|---|---|---|---|---|---|---|
| F-050 | Web UI — FastAPI 30 endpointů + vanilla JS SPA (dark mode) | Interaktivní GUI pro případy, timeline, graf entit, reporty | web/app.py, static/ | 0.1.0 | ✓ | ✓ (29) | ✓ sada | plně funkční | chybí Processing/Validation/Audit Center | STP-021 |
| F-051 | Paralelizace pipeline (ThreadPoolExecutor) + E3 resume | Paralelní zpracování souborů, checkpointing a obnovení přerušené analýzy | pipeline.py | 0.1.0 | ✓ | ✓ (sada) | ✓ | plně funkční | RAM peak u velkých E01 — chybí stream parsing | STP-021 |

## Coverage AXIOM (D)
- **covered 33 / 232** unikátních typů (po vlně 1; předtím 22). Matice: `STOPA_COVERAGE_MATRIX.csv` + `docs/re-axiom/AXIOM_COVERAGE.{md,json}`.
- Zbývá: portable-local **38**, cloud-export **112**, memory **15**, base-class **34**.
