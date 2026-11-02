# STOPA — FEATURE REGISTRY (registr funkcí)

Rozlišení stavů: IMPLEMENTED ≠ TESTED ≠ VERIFIED.
- **impl:** implementováno | **test:** testováno (unit/integration) | **verif:** nezávisle ověřeno (plná sada + ruff + commit)
Stavy: plně funkční / částečně funkční / experimentální / nefunkční

## Evidence & Integrity (P0 Core C1–C4)

| Feature ID | Název | Modul | impl | test | verif | Stav | Omezení | Úkoly |
|---|---|---|---|---|---|---|---|---|
| F-001 | Evidence Model + Lineage | domain/evidence_model.py, lineage.py | ✓ | ✓ (26) | ✓ `943753b` | plně funkční | — | STP-001 |
| F-002 | Integrity SHA-256/MD5 + Ed25519 | domain/integrity.py, hashing.py | ✓ | ✓ (29) | ✓ `8b09071` | plně funkční | SHA-512 chybí | STP-002, STP-022 |
| F-003 | Audit log s hash chainingem | data/db.py | ✓ | ✓ (sada) | ✓ `a0e4577` | plně funkční | — | STP-003 |
| F-004 | Reproducibility Engine | domain/reproducibility.py | ✓ | ✓ (20) | ✓ `a554a20` | plně funkční | — | STP-004 |

## Export & Report (C5, L)

| Feature ID | Název | Modul | impl | test | verif | Stav | Omezení | Úkoly |
|---|---|---|---|---|---|---|---|---|
| F-005 | Export CSV/JSON + manifest | domain/export.py, cli.py | ✓ | ✓ (sada) | ✓ `5b10a95` | plně funkční | chybí STIX/UCO/Plaso/JSONL/XML | STP-005, STP-023 |
| F-006 | HTML report 9 sekcí + PDF | presentation/case_report.py | ✓ | ✓ (16) | ✓ `42ade02` | plně funkční | 9/20 sekcí; PDF volitelné (weasyprint) | STP-020 |

## Benchmark & Validation (C6, I)

| Feature ID | Název | Modul | impl | test | verif | Stav | Omezení | Úkoly |
|---|---|---|---|---|---|---|---|---|
| F-007 | Benchmark Engine + detekce regresí >20% | domain/benchmark.py, data/benchmark_engine.py | ✓ | ✓ (18) | ✓ `42ade02` | plně funkční | neběží v CI | STP-006 |
| F-008 | C3 Parser Validation Registry (13 parserů) | domain/validation_registry.py | ✓ | ✓ (10) | ✓ `afc49a0` | plně funkční | 1:1 sync s pipeline vynucen build_registry() | STP-006, STP-013..015 |

## Disk images & Filesystems (B, C)

| Feature ID | Název | Modul | impl | test | verif | Stav | Omezení | Úkoly |
|---|---|---|---|---|---|---|---|---|
| F-010 | EWF/libewf (E01) | data/ewf_container.py, image_pipeline.py | ✓ | ✓ (41) | ✓ sada | plně funkční | `EWF available: True` ověřeno | — |
| F-011 | RAW/IMG přes TSK + carving volného prostoru | data/tsk*.py, domain/carving.py | ✓ | ✓ (35+21) | ✓ sada | plně funkční | — | — |
| F-012 | FDE dešifrování AES-CBC/FBE/LUKS | domain/fde*.py | ✓ | ✓ (50) | ✓ sada | plně funkční | — | — |

## Artifact Engine (D) — 20 parser modulů, C3 registry 13 verzovaných

| Feature ID | Název | Modul | impl | test | verif | Stav | Omezení | Úkoly |
|---|---|---|---|---|---|---|---|---|
| F-020 | LNK shorthands v2.0 | artifacts/win_lnk.py | ✓ | ✓ (sada) | ✓ | plně funkční | — | — |
| F-021 | Prefetch | artifacts/win_prefetch.py | ✓ | ✓ (sada) | ✓ | plně funkční | C3 registrován | — |
| F-022 | Jump Lists | artifacts/win_jumplist.py | ✓ | ✓ (sada) | ✓ | plně funkční | — | — |
| F-023 | EVTX event log | artifacts/win_eventlog.py | ✓ | ✓ (sada) | ✓ | plně funkční | Audit*/GoogleAccessLog covered | — |
| F-024 | Amcache + ShimCache (registry průchody) | artifacts/win_amcache.py, win_shimcache.py | ✓ | ✓ (test_e7 21) | ✓ | plně funkční | sekundární průchod `_extract_registry_all` | — |
| F-025 | USN Journal | artifacts/win_usn.py | ✓ | ✓ (sada) | ✓ | plně funkční | C3 registrován | — |
| F-026 | Registry hive generic (regipy) | artifacts/registry_extract.py | ✓ | ✓ (13) | ✓ | plně funkční | C3 registrován | — |
| F-027 | Browser history/iMessage/SMS/hovory/WhatsApp (SQLite) | artifacts/sqlite_extract.py | ✓ | ✓ (20) | ✓ | plně funkční | C3 registrován | — |
| F-028 | iCloud Messages CSV/XLSX | artifacts/imessage_cloud.py | ✓ | ✓ (29) | ✓ | plně funkční | name-based detekce | — |
| F-029 | Mobilní logical exporty (Samsung contacts/sms/calllog) | artifacts/mobile_extract.py | ✓ | ✓ (10) | ✓ | plně funkční | — | — |
| F-030 | **Email mbox/EML** (ETAPA B vlna 1) | artifacts/email_mbox.py | ✓ | ✓ (17) | ✓ `afc49a0` | plně funkční | name/content-based detekce; MIME body text/plain+html | STP-013 |
| F-031 | **WiFi WLAN profile XML** (ETAPA B vlna 1) | artifacts/win_wlan.py | ✓ | ✓ (12) | ✓ `afc49a0` | plně funkční | namespace-agnostický; C3 registrován | STP-013 |
| F-032 | **Scheduled Tasks XML** (ETAPA B vlna 1) | artifacts/win_schedtask.py | ✓ | ✓ (11) | ✓ `afc49a0` | plně funkční | UTF-16 LE/BE BOM; C3 registrován | STP-014 |
| F-033 | **Netstat/connstat text** (ETAPA B vlna 1) | artifacts/net_connections.py | ✓ | ✓ (12) | ✓ `afc49a0` | plně funkční | token-based; Windows+Unix, IPv4/IPv6/wildcard; C3 registrován | STP-014 |
| F-034 | **Clipboard registry** (ETAPA B vlna 1) | artifacts/win_clipboard.py | ✓ | ✓ (12) | ✓ `afc49a0` | plně funkční | sekundární průchod NTUSER.DAT; CF_* formáty, UTF-8/UTF-16LE detekce | STP-015 |
| F-035 | **SID extraction** (ETAPA B vlna 1) | artifacts/win_sids.py | ✓ | ✓ (12) | ✓ `afc49a0` | plně funkční | sekundární průchod SAM/SECURITY + ProfileList; source_hint podle názvu souboru | STP-015 |

## Analytika & AI (E, F, H)

| Feature ID | Název | Modul | impl | test | verif | Stav | Omezení | Úkoly |
|---|---|---|---|---|---|---|---|---|
| F-040 | Timeline + anomálie | domain/timeline_anomaly.py | ✓ | ✓ (sada) | ✓ | plně funkční | — | STP-018 |
| F-041 | Entity Resolution 2.0 (4 confidence, normalizace, merge candidates) | domain/entity_resolution.py, entities.py, correlation.py | ✓ | ✓ (26+e4/e5/e10) | ✓ `2244d95` | plně funkční | schéma v11; backward compat mapping | STP-009 |
| F-042 | AI orchestrace — 5 agentů, routing, fail-closed validace | intelligence/agents.py, ai_orchestrator.py | ✓ | ✓ (25) | ✓ `61f9a03` | plně funkční | AI volitelná; LM Studio port 1234 | STP-007 |
| F-043 | Forensic RAG — 3 vrstvy, citace, prompt injection ochrana | intelligence/rag.py | ✓ | ✓ (30) | ✓ `97cd4d6` | plně funkční | docs/formats + docs/methodology volitelné/prázdné | STP-008 |
| F-044 | AI governance + PII redaktor | — | ✗ | — | — | nefunkční (chybí) | STOPA_AI_GOVERNANCE.md neexistuje | STP-019 |

## UI & Performance (N, O)

| Feature ID | Název | Modul | impl | test | verif | Stav | Omezení | Úkoly |
|---|---|---|---|---|---|---|---|---|
| F-050 | Web UI — FastAPI 30 endpointů + vanilla JS SPA (dark mode) | web/app.py, static/ | ✓ | ✓ (29) | ✓ sada | plně funkční | chybí Processing/Validation/Audit Center | STP-021 |
| F-051 | Paralelizace pipeline (ThreadPoolExecutor) + E3 resume | pipeline.py | ✓ | ✓ (sada) | ✓ | plně funkční | RAM peak u velkých E01 — chybí stream parsing | STP-021 |

## Coverage AXIOM (D)
- **covered 33 / 232** unikátních typů (po vlně 1; předtím 22). Matice: `STOPA_COVERAGE_MATRIX.csv` + `docs/re-axiom/AXIOM_COVERAGE.{md,json}`.
- Zbývá: portable-local **38**, cloud-export **112**, memory **15**, base-class **34**.
