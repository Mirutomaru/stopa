# STOPA — SECURITY REPORT (kořenový výstup MASTER PROMPT)

**Datum:** 2026-11-03 · **Commit:** `e227929` · **Verze aplikace:** 0.1.0
Základ: `docs/STOPA_SECURITY_MODEL.md` + `docs/SECURITY_AND_EVIDENCE_INTEGRITY.md`, aktualizováno na aktuální stav (ETAPA B vlna 1, P0 Core C1–C6).

## 1. Hrozby a jejich pokrytí

| # | Hrozbа | Mitigace | Stav |
|---|--------|----------|------|
| T1 | Ztráta integrity důkazů (úprava souboru po ingestu) | SHA-256 + MD5 všech souborů při ingestu; `stopa verify` re-hash a porovnání | ✅ |
| T2 | Tampering audit logu | **Hash chaining** (`prev_hash`/`hash`, GENESIS → …), append-only triggery SQLite (RAISE(IGNORE)), `verify_chain()` detekuje rozbití + ID prvního špatného řádku | ✅ |
| T3 | Nedůvěryhodný export / report | **Ed25519 podpisy** kontrolních bodů; podepsaný manifest u každého exportu (deterministický `manifest_hash` — stejný vstup = stejný hash) | ✅ |
| T4 | Prompt injection přes importované dokumenty (AI) | RAG obaluje dokumenty do `<untrusted_source layer="…">` bloku s instrukcí „data, ne příkazy“; FTS5 query sanitizace (každé slovo = citovaný term) | ✅ |
| T5 | Path traversal přes case_id / rel_path | `validate_case_id()` regex v `open_db`/`delete_case`; `resolve()` + prefix check u rel_path; RFC 5987 Content-Disposition + CRLF hardening (E-audit, 15 testů) | ✅ |
| T6 | Nevalidní výstup LLM jako forenzní záznam | **Fail-closed validace**: JSON → Pydantic model agenta; nevalidní = chyba (web 502), nikdy implicitní default | ✅ |
| T7 | AI jako skrytá povinná závislost | LM Studio klient s graceful degradation (localhost:1234); bez LLM = fallback na pravidla; `llm_call` injektovatelný → offline testy | ✅ |
| T8 | RAM peak u velkých E01 obrazů | chunked čtení EWF (O_RDONLY, libewf); ranged read exportu (seek+read místo read_bytes) — BLK-001 zůstává pro extrémní velikosti | 🔧 |
| T9 | Chybějící RBAC | actor je volitelný řetězec v audit logu; role/permissions chybí (BLK-004) | ⚠️ P2 |
| T10 | Zranitelné závislosti | pip-audit zatím mimo CI | ⚠️ P2 |

## 2. Evidence Integrity 2.0 (P0 Core C4 — hotovo)
- **Hash chaining audit logu:** každý záznam nese `prev_hash` + vlastní `hash`; migrace v8→v9 s backfillem řetězce od GENESIS pro staré DB (triggery append-only dočasně zrušeny a obnoveny).
- **Ed25519 kontrolní body:** lazy import `cryptography` (volitelná závislost, graceful degradation jako FDE); klíč generován při `case new`; kontrolní body automaticky po ingest / correlate / export; `stopa integrity <case>` ověří řetězec + klíč + body.
- **Export manifesty:** `build_manifest()` + deterministický `manifest_hash` + Ed25519 podpis — každý export je reprodukovatelný a podepsaný.

## 3. AI bezpečnost (P0 Intelligence I1–I2)
- Fail-closed validace LLM výstupu proti Pydantic modelu každého agenta (žádné implicitní defaulty).
- Citace `[art:<id>]`/`[file:<id>]` — každý AI závazek musí odkazovat na konkrétní záznam případu.
- Tři izolované RAG vrstvy (Case/Technical/Knowledge) s přísnou izolací podle `case_id`.
- Audit každého AI dotazu: `analysis_operations` (op_type=`ai_query`) s verzí modelu, SHA-256 promptu a použitými citacemi.

## 4. Web API bezpečnost
FastAPI + Pydantic validace vstupů; per-request CaseDB; path traversal opraveny (T5); CRLF hardening u Content-Disposition; vanilla JS SPA bez build kroku (menší attack surface, žádné node_modules).

## 5. Důvěryhodnost vstupů
- Magic bytes detekce (25 signatur) — ne spolehnout se na příponu (`bad_extension` flaguje rozpor MIME vs přípona).
- Registry hive parsery: `regipy` s fake objekty v testech; sekundární průchody (Clipboard/SID) sdílejí regf magic.
- XML formáty bez magiky → name-based detekce + obsahová validace (WLAN profile, Scheduled Tasks).

## 6. Kontrolní seznam commitů (z SECURITY_MODEL)
1. Plná testová sada zelená (`895 passed`) · 2. ruff clean · 3. nové parsery = C3 záznam + testy + coverage řádek · 4. determinismus exportu (SHA-256 diff) · 5. audit log chain nezlomil.

## 7. Zbývající dluh
| Položka | Priorita | Úkol |
|---|---|---|
| RBAC minimální (role + oprávnění, actor povinný) | P2 | BLK-004 / STP-019 souvislost |
| pip-audit v CI | P2 | — |
| Izolace parserů (sandbox pro neznámé formáty) | P3 | — |
| Šifrování citlivých dat v DB (PII) | P2 | STP-019 (AI governance) |
