# STOPA — Security Model (ETAPA C)

> 📜 **NAVRHOVÁ DOKUMENTACE ETAPY C (2026-11-02)** — historický záznam návrhu, ne aktuální stav. Aktuální stav ochrany viz `FORENSIC_HARDENING_REPORT.md` (kořen repa). Referencován README, proto banner místo archivace.

**Datum:** 2026-11-02 · **Základ:** `docs/prompts/udelej.md` §14, §23 + E-audit (`docs/archive/AUDIT-2026-11.md`)

## 1. Hrozby a předpoklady

| Předpoklad | Důsledek |
|---|---|
| Single-user offline provoz (default) | Web API na localhost bez auth = akceptovatelné; P2 přidá volitelnou auth |
| Důkazní data jsou citlivá (soukromí osob) | Žádný automatický přenos dat ven; každý externí přenos evidován |
| AI model (LM Studio) běží lokálně | Model = nedůvěryhodný interpret, ne důkaz; výstupy označeny jako analytické |
| Importované soubory jsou nedůvěryhodné vstup | Defenzivní parsing (poškozený → `[]`), izolace od AI kontextu |

## 2. Současný stav (ověřeno)

- **Path traversal:** opraveno v E-auditu — case_id regex validace (`validate_case_id`),
  rel_path resolve()+prefix check, CRLF/RFC 5987 v exportu ✓
- **Audit log:** append-only triggery RAISE(IGNORE) — UPDATE/DELETE se tichom ignorují (slabina:
  neviditelná ztráta; Integrity 2.0 přidá hash chaining + kontrolní body)
- **AI:** graceful degradation, citace validované proti reálným ID ✓
- **Závislosti:** 2 povinné (pydantic, regipy); volitelné extras izolují riziko ✓

## 3. Integrity 2.0 (C4) — návrh

### 3.1 Hash chaining audit logu

```
audit_log: id, ts, action, actor, details_json, prev_hash, hash
hash = SHA-256(prev_hash || ts || action || actor || details_json)
první řádek: prev_hash = GENESIS (0×64)
```

- Ověření: `/api/cases/{id}/integrity/check` přepočítá celý řetězec; rozbití = report s ID řádku
- Migrace starých DB: backfill hashů při prvním otevření (meta-flaga `audit_chained=1`)

### 3.2 Ed25519 kontrolní body

- Klíčový pár generován při `case new` (soukromý v case DB, veřejný do reportu)
- Kontrolní bod = podpis hash posledního audit řádku; ukládá se pravidelně (po každé operaci
  měnící důkazy: ingest, correlate, export) + na požádání
- Nezávislá kontrola: veřejný klíč + kontrolní body stačí k ověření integrity bez soukromého klíče

### 3.3 Hashování exportních manifestů

- Report manifest (soubory + hashy + zdroj) dostane vlastní SHA-256; podepsaný Ed25519
- Reprodukovatelnost: stejný vstup + verze STOPA = stejný manifest hash

## 4. AI bezpečnost (§23)

| Hrozba | Ochrana |
|---|---|
| Prompt injection v importovaných dokumentech | Dokumenty do AI kontextu obaleny do izolovaného bloku s instrukcí „data, ne příkazy"; citace z nich značeny `unverified` (I2) |
| Přenos dat mezi případy | RAG vrstva Case = jen aktuální case ID; test: dotaz v case A neuvidí data case B |
| Automatický cloud AI | LM Studio URL explicitní konfigurace; default localhost; každý externí přenos do audit_log (action=ai_external_call) |
| API klíče | env proměnné, ne config soubor; volitelné extras = volitelné služby |
| AI mění důkazy | AI endpointy read-only nad case DB; zápis jen do `findings` (analytical observations) |

## 5. Web API bezpečnost

- **P0:** CORS explicitně konfigurovatelný (default: same-origin); health endpoint bez dat
- **P2 (E2):** volitelná token auth (Bearer), RBAC role (examiner/reviewer/admin), audit přístupu
- **P2 (E3):** API klíče pro externí systémy + rate limiting; šifrování citlivých dat v klidovém stavu (volitelné)

## 6. Důvěryhodnost vstupů

| Vstup | Nedůvěryhodnost | Ochrana |
|---|---|---|
| Evidence soubory | vysoká (cizí data) | defenzivní parsery, read-only přístup, hash při ingestu |
| Disk obrazy | vysoká | TSK/pytsk3 izolace, E01/AFF4 validace hlaviček |
| Cloud exporty | střední–vysoká | normalizace + provenance záznam; CSV/XLSX s citacemi do AI = unverified |
| AI výstupy | střední (interpret) | grounding štítky, citace validované, nikdy ne Direct Evidence |

## 7. Kontrolní seznam pro každý commit měnící bezpečnost

1. Nový vstup zvenčí → je validovaný? (regex/Pydantic/range check)
2. Nová cesta k souboru → resolve()+prefix check?
3. Nový header/response → quoting (RFC 5987 / JSON escape)?
4. Nová AI citace → validovaná proti reálným ID?
5. Nový externí přenos → evidován v audit_log?
6. Testy: pozitivní + negativní (poškozený vstup) + edge case?
