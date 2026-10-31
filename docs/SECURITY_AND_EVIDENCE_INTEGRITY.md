# STOPA — SECURITY & EVIDENCE INTEGRITY (2026-10-31)

**Nejvyšší priorita celého projektu** (master prompt §7). Cíl: každý nález dohledatelný ke zdroji, originály nedotčené, analýza reprodukovatelná.

## 1. Současný stav integrity (ověřeno v kódu)

| Mechanismus | Stav | Důkaz |
|---|---|---|
| SHA-256 + MD5 hashing | ✅ | `domain/hashing.py`, chunked 1 MiB; SHA-1 volitelný profilem |
| Dual-hash v CoC manifestu | ✅ | `report.py` — SHA-256+MD5 sloupce + zdroj souboru (commit `27d242e`) |
| Read-only čtení SQLite DB | ✅ | `_connect_readonly()` → `mode=ro` URI |
| Read-only E01/AFF4 | ✅ | `ewf_container.py` O_RDONLY |
| Dedupe napříč případem | ✅ | SHA-256 i MD5-only profily, seed z DB (idempotentní re-runy) |
| Known-bad hash sets | ✅ | FTK-style textové sady, detekce délky 32/40/64 hex |
| Verze nástroje v reportu | ✅ | `STOPA v0.1.0` v hlavičce (CoC audit) |
| **Audit log operací** | ❌ chybí | jen `meta` key-value tabulka |
| **Průběžná CoC evidence** | ⚠️ jen v reportu | CustodyItems se staví na letku při exportu, ne evidují se |
| **Verze parserů/knihoven** | ❌ chybí | jen verze nástroje; parsery nemají `PARSER_VERSION` |
| **Working copy mechanismus** | ⚠️ implicitní | pipeline čte přímo z evidence cesty (read-only v praxi, ale bez explicitní záruky) |
| **Neměnné custody záznamy** | ❌ chybí | žádná append-only tabulka |

## 2. Cílový model důkazní integrity

### 2.1 Tři úrovně přístupu k datům
```
ORIGINÁL (read-only)          WORKING COPY            CASE DB
/mnt/evidence/disk.E01   →    $STOPA_WORKSPACE/     →   cases/case-*.db
  • nikdy neupravovat           • extrakce RAW z E01      • upserty idempotentní
  • hash při přijetí            • plaintext FDE             • audit_log append-only
  • custody item #1             • carving výstupy           • custody items průběžně
```

### 2.2 Neměnný audit log (append-only)
- Tabulka `audit_log` s triggerem: `BEFORE UPDATE/DELETE ON audit_log → RAISE(ABORT)` (SQLite trigger = neměnnost na úrovni DB, ne jen konvence)
- Každá operace: `ts_utc + actor + action + target + details_json`
- **Actor identifikace:** CLI = `--examiner` parametr (default z case), web GUI = role z Settings; AI asistent = `ai-assistant`
- **Verze parserů a knihoven** v `details_json`: `{parser_versions: {imessage: "1.0", ...}, libs: {pytsk3: "20260715", cryptography: "50.0.2"}}` — sbíráno při startu pipeline (importlib.metadata)

### 2.3 Chain of Custody — průběžná evidence
- Každý source při přidání → custody item (acquired_by, method, hashy)
- Každá významná operace (FDE unlock, E01 extrakce, report export) → custody item
- Report čte z tabulky; **hash originálu se ověřuje při každém otevření** (CLI `stopa verify <case>` — přepočítá SHA-256 a porovná s custody)

### 2.4 Rozlišení důkazní síly (klíčové pro reporty)
Každý artifact nese `confidence`:
| Hodnota | Význam | Příklad |
|---|---|---|
| `extracted` | automaticky extrahováno, neověřeno | řádek z chat.db |
| `verified` | ověřeno druhým zdrojem / referenčním výsledkem | hash match + dedupe potvrzení; korelace se 2+ artifacty |
| `hypothesis` | analytickká hypotéza (AI, temporal overlap) | "stejná osoba na obou zařízeních" z časového překryvu |

Report tiskne štítek u každého nálezu; AI tvrzení jsou VŽDY `hypothesis`, dokud člověk neověří.

## 3. Bezpečnostní model aplikace

### 3.1 Lokální provoz (offline-first)
- Web GUI binduje na `127.0.0.1` (default; Settings → bind address pro síť)
- **Bez autentizace v lokálním režimu** — akceptovatelné riziko, dokumentované; při síťovém bindu = varování v Diagnostics
- PII maskování: volitelné (`--mask-pii`) v reportech; produkční výchozí = nemaskováno (forenzní kontext), ale Settings to přepne

### 3.2 AI asistent a PII
- Cíl AI = explicitní URL v Settings (default `localhost:1234` LM Studio)
- **Žádný automatický odesíl do ext. služeb** — při ne-lokálním cíli Diagnostics ukazuje varování
- AI čte přes read-only API; nikdy nepíše do case DB (citace = odkazy, ne kopie dat)

### 3.3 Práce se soubory
| Pravidlo | Implementace |
|---|---|
| Originály nikdy neupravovat | pipeline čte `O_RDONLY`; working copy pro výstupy; test E2E ověřuje hash originálu po běhu |
| Working copy oddělená | `$STOPA_WORKSPACE` (default `./workspace/<case_id>/`) — FDE plaintext, E01 RAW extrakce, carving výstupy |
| Dočasné soubory uklízené | `tempfile` + try/finally cleanup (už v image_pipeline — rozšířit na všechny cesty) |
| Práva k souborům | case DB `chmod 600`; workspace `700` (nové, E12) |

### 3.4 Defenzivní programování (existující konvence)
- IO vrstvy: try/except s logováním (structured logging s correlation ID = source_id/file_id)
- Parsery: blind Exception + `[]` fallback na korupci (ne crash celého běhu) — ale **každý fallback se loguje do audit_log** (nové, E1)
- Pydantic validace modelů (Artifact, FileRecord) — strict typing

## 4. Reprodukce analýzy

**Cíl:** stejný originál + stejná verze STOPA = stejné artifacty.

1. **Verze nástroje** v reportu i audit_log (`STOPA vX.Y.Z` + git SHA při dev build)
2. **Verze parserů** per artifact (`parser_version` sloupec)
3. **Verze knihoven** v `details_json` audit záznamu (pytsk3, cryptography, openpyxl...)
4. **Deterministické epochy/konverze** — `domain/times.py` čisté funkce s testy
5. **Profil zpracování** v audit_log (`forensic` = které hashy/signatury/parsery)
6. **CLI pro reprodukcí:** `stopa replay <case> --profile forensic` (nové, E10) — přeběhne pipeline s tímto profilem a porovná artifacty (hash multiset)

## 5. SWGDE / NIST CFTT — co tvrdíme a co ne

| Metodika | Co STOPA splňuje | Co nesplňuje (poctivě) |
|---|---|---|
| **SWGDE** (důkazní integrita, dokumentace) | ✅ SHA-256+MD5 dual-hash, CoC manifest, read-only originály, verze nástroje, audit log (E1) | ⚠️ formální SWGDE review metodik nebyl proveden — "validováno v duchu SWGDE", ne "podle SWGDE" |
| **NIST CFTT** (Computer Forensics Tool Testing) | ✅ referenční testovací sady per parser, deterministické fixture, negativní testy | ⚠️ plný NIST CFTT protokol (validace na reálných diskách, cross-tool parity) = E13 roadmap |

**Pravidlo:** v reportech a dokumentaci nikdy "certifikováno" — jen "validováno referenčními výsledky v rozsahu X" + odkaz na `docs/validation.md`.

## 6. Kontrolní seznam integrity (checklist pro každý release)

- [ ] SHA-256 všech originálů ověřeno (`stopa verify`)
- [ ] Audit log obsahuje všechny operace od posledního release
- [ ] Verze parserů + knihoven zapsány v audit_log
- [ ] Report obsahuje: identifikaci případu, důkazy, nástroje, verze, časové pásmo, hashy, artifacty s confidence štítky, timeline, korelace, chyby/omezení, CoC, odkazy na zdroje
- [ ] Originály po analýze = stejné hashy jako před analýzou (E2E test)
- [ ] Working copy oddělená od evidence cesty
- [ ] Dočasné soubory uklizené

## 7. Změny k implementaci (mapa na ROADMAP etapy)

| Změna | Etapa |
|---|---|
| `audit_log` + trigger append-only + `schema_version` | E1 |
| `custody_items` tabulka + průběžná evidence | E1 |
| `PARSER_VERSION` v extraktorech + registrace verzí | E1 |
| Working copy mechanismus (`$STOPA_WORKSPACE`) | E1/E3 |
| `stopa verify <case>` (hash ověření originálů) | E1 |
| `confidence` sloupec v artifacts | E2 |
| `extracted_at` + TZ evidence | E2 |
| AI PII model (read-only, cíl v Settings) | E11/E12 |
| Práva k souborům 600/700 | E12 |
| `stopa replay` reprodukcí | E10 |
| `docs/validation.md` + referenční sady | E13 |
