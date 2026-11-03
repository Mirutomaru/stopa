# STOPA — TEST REGISTRY (centrální evidence testování)

Výsledky: PASS | FAIL | PARTIAL | NOT_RUN | BLOCKED. Počty doloženy `pytest --collect-only`
dne 2026-11-03 (commit `afc49a0`). **Celkem: 896 testů = 895 passed + 1 skipped** (plná sada,
`.venv/bin/python -m pytest -q`, plně offline — syntetické fixtures, žádné externí API).

Povinná pole dle DEV OS promptu §3.7:
- **Datum:** 2026-11-03 pro všechny záznamy (poslední plný běh; starší běhy viz CHANGELOG.md)
- **Verze aplikace:** 0.1.0, commit `afc49a0` / `e227929`
- **Případná chyba:** sloupec Poznámka (aktuálně žádný FAIL — jediný skipped = volitelný backend bez nainstalované závislosti)
- **Odkaz na testovací protokol:** testovací soubor v `tests/` je protokolem; plný běh reprodukovatelný `.venv/bin/python -m pytest -q` (deterministická offline sada)

## Evidence & Integrity (P0 Core)

| ID | Soubor | Testovaná funkce | Scénář / dataset | Výsledek | Poznámka |
|---|---|---|---|---|---|
| T-001 | tests/test_evidence_model.py (14) | F-001 Evidence Model | syntetické findings + provenance | PASS | commit `943753b` |
| T-002 | tests/test_lineage.py (12) | F-001 Lineage chain | lineage artifact→zdroj | PASS | commit `943753b` |
| T-003 | tests/test_integrity.py (22) | F-002 Integrity/Ed25519 | hash + podpisy, tamper detekce | PASS | commit `8b09071` |
| T-004 | tests/test_hashing.py (7) | F-002 hashing helpery | SHA-256/MD5 vektory | PASS | — |
| T-005 | tests/test_reproducibility.py (20) | F-004 Reproducibility + migrace | DB operace, schema v11 | PASS | commit `a554a20` |
| T-006 | tests/test_audit_fixes.py (15) | F-003 audit log fixes | hash chaining edge cases | PASS | — |

## Benchmark & Validation (C3/C6)

| ID | Soubor | Testovaná funkce | Scénář / dataset | Výsledek | Poznámka |
|---|---|---|---|---|---|
| T-010 | tests/test_benchmark_engine.py (18) | F-007 Benchmark Engine | deterministické workloads, regresní detekce >20% | PASS | commit `42ade02` |
| T-011 | tests/test_validation_registry.py (10) | F-008 C3 registry | build_registry 1:1 sync, RegistryError, report řazení | PASS | aktualizováno po vlně 1 (9→len(PARSER_VALIDATIONS)) |

## Disk images & Filesystems (B/C)

| ID | Soubor | Testovaná funkce | Scénář / dataset | Výsledek | Poznámka |
|---|---|---|---|---|---|
| T-020 | tests/test_ewf_container.py (11) | F-010 EWF/libewf | syntetické EWF kontejnery | PASS | `EWF available: True` |
| T-021 | tests/test_image_phase5.py (30) | F-010/F-011 image pipeline | E01/AFF4/RAW, carving, MFT | PASS | — |
| T-022 | tests/test_tsk.py (22) + test_tsk_py.py (13) | F-011 TSK backendy | RAW/IMG obraz, NTFS/FAT/APFS | PASS | pytsk3 primární, CLI fallback |
| T-023 | tests/test_fde.py (18) + test_fde_b2.py (32) | F-012 FDE dešifrování | AES-CBC/FBE/LUKS syntetické obrazy | PASS | — |
| T-024 | tests/test_carving_zip_rar.py (13) | carving ZIP/RAR | syntetické obrazy s ukrytými archivy | PASS | — |

## Artifact Engine (D) — vlna 1 ETAPA B

| ID | Soubor | Testovaná funkce | Scénář / dataset | Výsledek | Poznámka |
|---|---|---|---|---|---|
| T-030 | tests/test_email_mbox.py (17) | F-030 email mbox/EML | syntetické mbox/eml, MIME body, UTF-8/16 | PASS | commit `afc49a0` |
| T-031 | tests/test_win_wlan.py (12) | F-031 WiFi WLAN XML | syntetické profile XML s xmlns; ValueError ne-XML | PASS | commit `afc49a0` |
| T-032 | tests/test_win_schedtask.py (11) | F-032 Scheduled Tasks XML | UTF-16 LE BOM fixture; akce+triggery | PASS | commit `afc49a0` |
| T-033 | tests/test_net_connections.py (12) | F-033 netstat/connstat text | Windows uppercase + Unix ss/netstat, IPv4/IPv6/wildcard | PASS | commit `afc49a0` |
| T-034 | tests/test_win_clipboard.py (12) | F-034 Clipboard registry | fake hive (monkeypatch regipy), CF_* formáty, binární hex preview | PASS | commit `afc49a0` |
| T-035 | tests/test_win_sids.py (12) | F-035 SID extraction | fake hive SAM/SECURITY + ProfileList; source_hint | PASS | commit `afc49a0` |
| T-036 | tests/test_e7.py (21) | F-024 Amcache/ShimCache | registry hive fixtures | PASS | — |
| T-037 | tests/test_registry_extract.py (13) | F-026 Registry generic | regipy hive fixtures | PASS | — |
| T-038 | tests/test_sqlite_extract.py (20) | F-027 SQLite browser/iMessage/SMS | syntetické DB | PASS | — |
| T-039 | tests/test_imessage_cloud.py (29) | F-028 iCloud Messages CSV/XLSX | cloud export fixtures | PASS | — |
| T-040 | tests/test_mobile_extract.py (6) + test_mobile_image_io.py (4) | F-029 mobilní logical exporty | Samsung contacts/sms/calllog | PASS | — |
| T-041 | tests/test_plist_extract.py (14) | plist extrakce | syntetické .plist | PASS | — |

## Analytika & AI (E/F/H)

| ID | Soubor | Testovaná funkce | Scénář / dataset | Výsledek | Poznámka |
|---|---|---|---|---|---|
| T-050 | tests/test_timeline_engine.py (41) | F-040 timeline + anomálie | syntetické timeline s rozporovými body | PASS | — |
| T-051 | tests/test_entity_resolution.py (26) | F-041 Entity Resolution 2.0 | confidence levels, JID→E164, merge candidates, migrace v10→v11, web endpoint | PASS | commit `2244d95` |
| T-052 | tests/test_e4.py (21) + test_e5.py (6) | F-041 korelace entit | same_contact/hash_match confirmed, temporal_overlap possible | PASS | aktualizováno pro I3 |
| T-053 | tests/test_intelligence.py (25) | F-042 AI orchestrace | 5 agentů, routing, fail-closed validace + citace | PASS | commit `61f9a03` |
| T-054 | tests/test_rag.py (30) | F-043 Forensic RAG | 3 vrstvy, chunking, prompt injection ochrana | PASS | commit `97cd4d6` |
| T-055 | tests/test_e11.py (19) | LM Studio klient | mockovaný LLM endpoint port 1234 | PASS | — |
| T-072 | tests/test_pii_redaction.py (23) | F-044 PII redaktor + audit AI volání | maskování phone/email/JID/handle, I1 orchestrace, E11 buildery, web E2E s mock LM Studio, toggle ai_redact_pii | PASS | STP-019 (tento commit) |

## Pipeline & UI & ostatní

| ID | Soubor | Testovaná funkce | Scénář / dataset | Výsledek | Poznámka |
|---|---|---|---|---|---|
| T-060 | tests/test_pipeline.py (16) | pipeline dispatch + E3 resume | signatury, name-based fallback, checkpointing | PASS | — |
| T-061 | tests/test_signatures.py (29) | magic-bytes detekce | 25+ signatur | PASS | — |
| T-062 | tests/test_web.py (29) | F-050 web API (30 endpointů) | FastAPI TestClient | PASS | — |
| T-063 | tests/test_report.py (16) | F-006 report engine 9 sekcí | HTML generace, confidence labely | PASS | — |
| T-064 | tests/test_evidence_manager.py (19) + test_e3.py (8) | evidence management | ingest + chain of custody | PASS | — |
| T-065 | tests/test_bad_extension.py (26) | detekce špatných přípon | magic vs ext rozpor | PASS | — |
| T-066 | tests/test_dedupe.py (8) | deduplikace | hash duplicit | PASS | — |
| T-067 | tests/test_search.py (14) | search filters | FTS5 dotazy | PASS | — |
| T-068 | tests/test_profiles.py (6) | profily případů | preset konfigurace | PASS | — |
| T-069 | tests/test_times.py (7) | časové helpery | FILETIME/Unix/ISO konverze | PASS | — |
| T-070 | tests/test_sqlite_recover.py (13) + test_sqlite_recover_io.py (8) | SQLite carving z volného prostoru | syntetické obrazy | PASS | — |
| T-071 | tests/test_e6.py (23), test_e8.py (16), test_e9.py (22), test_e10.py (17), test_e12.py (11) | E-fáze (file meta, report, export, CLI, benchmark CLI) | end-to-end scénáře | PASS | — |

## Celkový stav
- **896 testů: 895 PASS + 1 skipped** (skipped = volitelný backend bez nainstalované závislosti).
- Ruff: `All checks passed!` pro `src/stopa tests scripts`.
- Determinismus coverage matice: SHA-256 diff ✓.
- NOT_RUN: benchmark engine v CI (neběží automaticky — ručně `stopa benchmark`).
