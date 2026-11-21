# STOPA — Pokrytí volitelných extras v CI (P4-1)

Tento dokument mapuje každé volitelné extra na jeho kódové cesty a testovací pokrytí.
Základ: automatický audit lazy/direktních importů (2026-11-20, HEAD po P4-1 W1).

## CI profily závislostí

| Profil | Instalace | Cíl |
|--------|-----------|-----|
| **min** (job `test`) | `-e ".[dev,web]"` | degradation baseline — vše bez volitelných extras musí projít (skipy, ne faily) |
| **full** (job `test-full`) | `-e ".[dev,web,pdf,fde,tsk,stix,rules,xlsx,meta,net,analytics]"` | funkční cesty — testy za každým extra běží bez skipu |

Min profil = stávající chování CI. Full profil je nová vlna P4-1: poprvé prověří
„s X“ cesty (např. Ed25519 manifest s `cryptography`, YARA matching, DuckDB OLAP).

## Matice extra → kódové cesty → testy

| Extra | Balík(yp) | Kódové cesty v src/ | Testovací pokrytí | Profil |
|-------|-----------|--------------------|-------------------|--------|
| `web` (baseline obou profilů) | fastapi, uvicorn, httpx, python-multipart | `web/app.py` + 13 routerů (`web/routers/*`), `cli/commands/serve.py`, `data/lmstudio_client.py`, `data/timesketch_client.py` | ~40 test souborů s TestClient; přímé importy fastapi/httpx (v baseline, guard nevyžaduje) | min + full |
| `pdf` | weasyprint | `presentation/case_report.py`, `presentation/compliance_report.py`, `intelligence/hypothesis_graph.py`, `web/routers/reports.py` | find_spec/importorskip guardy; PDF cesty bez skipu jen v **full** (vyžaduje system lib pango) | min: skip, full: běh |
| `fde` | cryptography | `domain/fde.py`, `domain/fde_bitlocker.py`, `domain/fde_fbe.py`, `domain/integrity.py`, `domain/multitenant.py`, `domain/crypto/wallets.py` | module-level try/except (test_e3, test_k2), importorskip (test_fde); **P4-1 W1 oprava**: test_k2 měl nechráněný module-level import + class-scope parametrize; **W2**: guardy doplněny na dalších 13 souborech (p27_exchange_domain/bundle/cli_web, mobile_image_io, k4_darkweb, f44_multitenant, f52_compliance_report, p36_tlp_policy, f34_legal_docs + existující markery aplikovány v fde_b2, p02_seal_keys, p34_evidence_storage_domain/w2) | min: skip, full: běh |
| `tsk` | pytsk3 | `data/tsk_py.py` (nativní TSK bindingy; fallback na CLI binárky) | guarded testy; referenční Python cesta pokryta i v min | min: fallback, full: nativní |
| `stix` | stix2 | `domain/export.py` (STIX 2.1 validace) | importorskip guard (test_f62_stix_uco); bez balíku graceful degradation na vlastní validátor | min: skip, full: běh |
| `rules` | yara-python | `domain/yara_sigma.py` (YARA/Sigma matching, P3-5) | per-test importorskip("yara") (test_p35_*); bez balíku explicitní RuntimeError, ne tichý 0 | min: skip, full: běh |
| `xlsx` | openpyxl | `artifacts/imessage_cloud.py` (XLSX iCloud Messages export) | guarded test (test_imessage_cloud) | min: skip, full: běh |
| `meta` | Pillow | `domain/anti_forensics.py` (LSB stego), `domain/file_meta.py` (EXIF) | **P4-1 oprava**: test_f14 dostal HAS_PIL guardy (fixture testy + profil-nezávislý missing_path test); ostatní cesty degradační (bez PIL = explicitní no_pil finding) | min: skip, full: běh |
| `net` | scapy | `data/pcap_io.py` (PCAP parser; fallback na statický scanner bez scapy) | **P4-1 oprava**: test_f13 měl nechráněný module-level import → celý soubor je teď skipif v min | min: skip, full: běh |
| `analytics` | duckdb | `data/analytics.py` (DuckDB OLAP; fallback na SQLite) | guarded testy (test_f22_analytics); SQLite fallback pokryt i v min | min: fallback, full: běh |
| `stopa_core` (Rust wheel, ne extra) | PyO3 maturin build | `data/rust_core.py` (facade), carving/hash parity | **P4-1 W2 oprava**: test_f21_rust_core dostal `HAS_CORE = rc.is_available()` + skipif na 4 parity/availability testech; referenční Python cesta pokryta i v min | min: fallback, full+wheel: běh |

## P4-1 W1 nálezy (fail-closed opraveno 2026-11-20)

Min profil (= přesně to, co CI instaloval dosud) odhalil 3 soubory s předpokladem
volitelného balíku bez guardu:

1. `tests/test_f13_network_forensics.py` — module-level `from scapy...` → **collection error** v min. Oprava: try/except `HAS_SCAPY` + `pytestmark = skipif`.
2. `tests/test_k2_crypto_wallets.py` — module-level `from cryptography...` → **collection error**; navíc class-scope hodnocení parametrizované listy (`make_top_vault(...)` v definici třídy) → NameError i po guardu importů. Oprava: try/except `HAS_CRYPTO` + `pytestmark` + podmíněná konstanta `_HEURISTIC_VAULTS`.
3. `tests/test_f14_anti_forensics.py` — PIL ve fixturech (runtime error) a `test_missing_path_returns_empty` čekal `[]`, ale bez PIL vrací explicitní `no_pil` skip finding. Oprava: try/except `HAS_PIL` + skipif na 3 testech + profil-nezávislá aserc missing_path testu.

Žádné změny v src/ — všechny opravy jsou test-only (soulad s P4-1 návrhem).

## P4-1 W2 nálezy (plný min-suite, opraveno 2026-11-21)

Průběžný min-profile běh celé suite odhalil dalších **58 failed + 18 errors** ve 19
souborech — stejný typ fail-closed bugu (test předpokládá volitelný balík bez guardu):

| Kořen | Soubory | Oprava |
|-------|---------|--------|
| `cryptography` ([fde]) | test_p27_exchange_domain.py, test_p27_exchange_bundle_domain.py, test_p27_exchange_cli_web.py, test_mobile_image_io.py, test_k4_darkweb.py, test_f44_multitenant.py (RS256/JWT), test_f52_compliance_report.py, test_p36_tlp_policy.py, test_f34_legal_docs.py | `HAS_CRYPTO` try/except + `@requires_crypto` na šifrovacích třídách/testech; tam kde soubor guard už měl (fde_b2, p02_seal_keys, p34_evidence_storage_domain/w2), aplikován existující marker jen na doposud nechráněné testy |
| Rust wheel `stopa_core` | test_f21_rust_core.py | `HAS_CORE = rc.is_available()` + skipif na 4 parity/availability testech (fallback cesta zůstává pokrytá i v min) |
| `stix2` ([stix]) | test_f63_mitre_attack.py | `pytest.importorskip("stix2")` u CLI testu s STIX validátorem |
| `weasyprint` ([pdf]) | test_report.py, test_web.py | `pytest.importorskip("weasyprint")` u PDF generování/stahování |

Pozn. k `test_f52_compliance_report.py`: soubor už obsahoval vlastní `HAS_CRYPTO` guard;
duplicitní blok odstrašen a doplněn jen chybějící marker `requires_crypto`.

## P4-1 W3 nálezy (re-run plného min-suite po W2, opraveno 2026-11-21)

Re-run plného min-suite po W2 opravách snížil selhání z **58 failed + 18 errors**
na **4 failed** — stejný typ fail-closed bugu v rodině testů, kterou prvním
mapováním kořenů přehlédli:

| Kořen | Soubory | Oprava |
|-------|---------|--------|
| `cryptography` ([fde]) — Ed25519 integrity checkpointy (`AuditRepository.add_integrity_checkpoint()` bez klíče degraduje na `None`, dokumentovaná graceful degradation) | test_stp057_plaso_import.py, test_stp059.py (timesketch push), test_stp063.py (plaso import GUI), test_stp068.py (export audit/checkpoint) | `HAS_CRYPTO` try/except + `@requires_crypto` na 4 testech asertujících existenci checkpointu; samotné audit řádky (append-only log) běží i v min — skip je na úrovni testu, protože checkpointová asercie sdílí stejný blok |

Celkem P4-1: **24 test souborů** opraveno test-only (W1 3 + W2 17 + W3 4), src/ beze změny.

## Finální validace (min + full profil, 2026-11-21)

| Běh | Profil | Výsledek |
|-----|--------|----------|
| min báze (před P4-1) | `.[dev,web]` | **58 failed + 18 errors** / 4609 passed / 260 skipped — fail-closed bugy souborů W1/W2 |
| min po W2 | `.[dev,web]` | **4 failed** (jen stp checkpoint rodina) / 4609 passed / 332 skipped |
| min po W3 (suite #3) | `.[dev,web]` | 1 failed = benchmark noise v test_stp044_ci_benchmark_e2e (**mimo P4-1 changeset**; standalone ×3 green) / 4608 passed / 336 skipped |
| **min finální (suite #4)** | `.[dev,web]` | ✅ **4609 passed / 336 skipped — exit 0** (30:51) |
| full target (.venv se všemi extras) | všechny extras + yara | ✅ W2 soubory **748 passed / 1 skipped**; stp rodina **53 passed / 0 skipped** — žádné over-skipping |

- Job `test` (min): exit 0, sada skipů stabilní a dokumentovaná výše.
- Job `test-full` (full): funkční cesty za extras běží bez skipu (ověřeno lokálně v full prostředí).
- Ruff clean repo-wide; db.py 599/600 (src beze změny); PKG_COMPAT beze změny.
- Regenerace auditu: grep lazy importů (`find_spec`, `__import__`) + přímých importů per
  balík; tabulku udržovat při každém novém extra.
