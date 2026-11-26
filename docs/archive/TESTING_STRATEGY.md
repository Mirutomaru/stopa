# STOPA — TESTING STRATEGY (2026-10-31)

**Aktuální stav:** 402 passed / 1 skipped, offline, ~1.8 s · poměr test/kód 0.68 · každý parser má vlastní sadu (6–32 testů).

## 1. Testovací pyramidu STOPA

```
            ┌─────────────┐
            │   E2E GUI   │  29 testů — FastAPI TestClient + DOM flowy
           ┌┴─────────────┴┐
           │  E2E pipeline │  image phase5, mobile IO, ewf roundtrip
          ┌┴───────────────┴┐
          │   Integrace DB  │  FTS5 triggery, upsert idempotence, migrace
         ┌┴─────────────────┴┐
         │    Unit (domain)  │  ~300 testů — čistá logika, žádné IO
         └───────────────────┘
```

**Princip:** domain = čisté funkce → testy bez fixture souborů; IO vrstvy = minimální binární fixture generované v testu (deterministicky); E2E = malé syntetické obrazy (FAT16 4 MB, ext4 přes mke2fs).

## 2. Pravidla pro nové testy (každá etapa ROADMAPu)

### 2.1 Každý parser má referenční sadu
- **Binární fixture generovaná v testu** (ne stažená z netu — offline-first): např. LNK soubor se známým cílem, .evtx s 3 recordy, amcache hive s 2 klíči
- **Known-good očekávání:** přesné hodnoty artifactů (title, timestamp, details) — ne jen "vrátil >0 záznamů"
- **Negativní testy:** poškozená fixture → graceful `[]` + warning, ne výjimka; cizí formát s příponou parseru → detekce magic selže

### 2.2 Determinismus
- Časy: fixní epochy v fixturech (CFAbsoluteTime pitfall — viz skill)
- Hashy: SHA-256/MD5 deterministické; benchmarky s `pytest.mark.bench` (výchozí skip, explicitní spuštění)
- Paralelizace test: **stejný vstup → stejná multiset artifactů** (pořadí nerespektujeme, obsah ano)

### 2.3 Offline-first
- Všechny testy běží bez sítě; LM Studio mock = lokální FastAPI fixture na `127.0.0.1:0` (ephemeral port)
- Volitelné extras (`[tsk]`, `[fde]`, `[xlsx]`, `[pdf]`) → `pytest.importorskip` + skip bez závislosti (aktuálně 1 skipped = LUKS E2E bez cryptsetup/rootu)

### 2.4 DB migrace
- Každá nová tabulka/kolona: test "staré schéma → upgrade" (vytvoř DB se starou verzí, otevři s novým kódem, ověř `schema_version` + data intact)
- Idempotence: dvojnásobné spuštění migrace = žádný efekt

## 3. Testovací matice modulů (cíl po ROADMAPu)

| Modul | Unit | Integrace | E2E | Reference sada |
|---|---|---|---|---|
| pipeline + hashing | ✅ existuje | ✅ | ✅ | ✅ (hashy známých souborů) |
| FTS5 search | ✅ 14 testů | ✅ triggery | ✅ Cmd+K flow | — |
| sqlite_extract (7 typů) | ✅ 20 | ✅ | ✅ chat.db fixture | ✅ iMessage epocha |
| imessage_cloud | ✅ 29 | ✅ pipeline fallback | ✅ XLSX warrant return | ✅ RLEAPP ground truth |
| registry/plist | ✅ 13+13 | ✅ | ✅ reálné hives (D: drive) | — |
| sqlite_recover | ✅ 23 | ✅ WAL fixture | ✅ | ✅ freelist/WAL formát |
| TSK (pytsk3+CLI) | ✅ 13+10 | ✅ FAT16 E2E | ✅ ext4 probe | ✅ mmls/fls parity |
| E01/AFF4 | ✅ 11 | ✅ roundtrip | ✅ pipeline extract | ✅ reálné magics |
| FDE (LUKS/FBE/STOPAFDE) | ✅ 32 | ✅ keyfile | ⚠️ LUKS skip bez rootu | ✅ AES-XTS roundtrip |
| carving ZIP/RAR | ✅ 13 | ✅ | ✅ .docx/.xlsx obnova | ✅ EOCD ground truth |
| **audit_log/custody (E1)** | +8 | +4 | +3 | — |
| **timeline/anomaly (E2)** | +10 | +5 | +3 | ✅ TZ konverze |
| **paralelizace (E3)** | +4 | +2 | +2 (determinismus) | — |
| **entities/correlation (E4)** | +10 | +4 | +2 | — |
| **graph GUI (E5)** | — | +6 | +2 | — |
| **win LNK/Prefetch/JumpList (E6)** | +14 | +4 | +3 | ✅ MS-LNK/MS-PREFETCH spec |
| **win EventLog/Amcache/USN (E7)** | +12 | +4 | +2 | — |
| **file_meta EXIF/PDF/OOXML (E8)** | +10 | +2 | +2 | ✅ docProps ground truth |
| **search ext. (E9)** | +6 | +3 | +1 | — |
| **reporting ext. (E10)** | +8 | +2 | +2 | — |
| **AI assistant (E11)** | +6 | +3 | +1 | ✅ mock LM Studio |
| **GUI doplnění (E12)** | +4 | +4 | +2 | — |

**Cíl: ~580+ testů, všechny offline, < 10 s celková doba.**

## 4. Regresní a benchmark strategie

### 4.1 Regrese
- **Zlatá sada:** `tests/fixtures/golden/` — 20–30 reálných (anonymizovaných) souborů s zamrzlými očekáváním artifactů; běží v CI jako první vrstva
- **Snapshot testy reportu:** HTML report z fixního case DB → hash obsahu (detekce nechtěných změn layoutu); při schválené změně = explicitní re-snapshot commit

### 4.2 Benchmarky (`tests/benchmarks/`)
| Benchmark | Metrika | Cíl |
|---|---|---|
| 1k souborů (mix text/bin) | soubory/s, RAM peak | >500 soub./s na NVMe; RAM < 200 MB |
| 500 MB RAW obraz | minuty, RAM peak | carving mmap: RAM < 300 MB |
| FTS5 search 100k files | ms/query | p95 < 50 ms |
| Timeline 50k events | ms/render (server) | p95 < 100 ms |

Benchmarks = `pytest.mark.bench` (výchozí skip), výstup do `docs/benchmark-<date>.md`.

### 4.3 SWGDE / NIST CFTT validace
- **Ne certifikace, ale validace metodik** (pravidlo master promptu §7): pro každý parser dokumentovat v `docs/validation.md`:
  - jaký referenční zdroj byl použit (spec MS-LNK, SQLite formát doc, RLEAPP ground truth...)
  - které testy to pokrývají
  - co ZŮSTÁVÁ neověřeno (např. LUKS E2E bez rootu)
- **Nikdy netvrď "certifikováno"** — jen "validováno referenčními výsledky v rozsahu X"

## 5. CI/CD (lokální, offline)

```bash
# ./test.sh — jeden příkaz pro plnou validaci
set -e
cd /home/ai/Prace/projekty/stopa
.venv/bin/ruff check src tests          # lint gate
.venv/bin/pytest -q                      # 402+ testů, offline
.venv/bin/pytest -m bench --bench-report docs/benchmark.md  # volitelné
```

**Gate před commitem (už dodržováno):** ruff clean + celá suite zelená + konventionální commit message.

## 6. Známé mezí testování (poctivě)

| Meze | Důvod | Mitigace |
|---|---|---|
| LUKS E2E skip | cryptsetup potřebuje loop device + root | header parsing plně testováno; E2E na mašině s rootem |
| NTFS/exFAT/HFS+ bez E2E | pytsk3 je čte, ale fixture vyžaduje root (mkfs.ntfs) | FAT16 E2E jako reference; NTFS probe ručně |
| GUI testy = TestClient, ne reálný browser | Playwright by potřeboval sítě pro instalaci | DOM flowy pokryty; vizuální regression ručně |
| AI asistent = mock LM Studio | lokální model není deterministický | testujeme kontrakt (JSON schema + citace), ne obsah odpovědi |
