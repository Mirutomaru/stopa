# Differential Testing — design doc (P0-4 / Parser Quality Framework)

**Stav:** návrh ke schválení · **Datum:** 2026-11-18 · **Závislost:** P0-4 (parser-status), rozšíří P1-1
**Princip:** *ani STOPA ani reference automaticky nemají pravdu* — rozdíl je podnět k
lidskému rozhodnutí, ne automatický verdikt.

## 1. Motivace

`stopa parser-status` (P0-4) dokazuje, že každý z 78 parserů **má testy**, ale testy
ověřují chování vůči očekávání, která jsme napsali my — tedy jen vlastní konzistenci.
Differential testing porovnává výstup STOPA s nezávislým referenčním nástrojem na
stejném vstupu a odhaluje:

- **systematické chyby** (obojí chybí / oba se shodují ve špatném výsledku),
- **regrese po změnách** parseru nebo pipeline,
- **rozdíly v sémantice** (epochy, časová pásma, kódování, řazení) — nejčastější zdroj
  tichých chyb forenzních nástrojů.

Dnešní gap: `reference_dataset` je nastaven u **0/78** parserů — pole v registry existuje,
datové sady ne. Tento návrh definuje workflow, jak je budovat a používat.

## 2. Referenční nástroje (kandidáti ke schválení)

Výběr kritéria: (a) nezávislost od STOPA kódu, (b) reprodukovatelnost verze,
(c) legální využití v offline režimu, (d) pokrytí formátové rodiny.

| Rodina formátů | Parsery (výběr z registry) | Referenční nástroj | Poznámka |
|---|---|---|---|
| SQLite DB (Chrome/Firefox/iMessage/…) | `sqlite`, `chrome_history_wr`, `contacts_wr`… | `sqlite3 .dump` + SQL očekávání (referenční dotazy) | dump je deterministický; srovnáváme tabulky, ne řádkové pořadí |
| PDF | `pdf` | `pdftotext`/poppler (případně pdfminer.six jako 2. reference) | textová vrstva; metadata samostatná komparace |
| Office (docx/xlsx/pptx) | `office_docs`… | `python-docx`/`openpyxl` čtení (nezávislá knihovna) | XML ground truth přímo z ZIP |
| E-mail (mbox/eml) | `email_mbox`, `eml` | `mailparser` + ručně ověřené hlavičky | hlavičky = deterministický subset |
| Windows registry | `registry_hive`… | `regipy` dump klíčů/hodnot | srovnání struktury, ne binární data |
| Logy/syslog/access | `syslog`, `access_log`… | referenční parser (př. `goaccess` pro access log) | jen normalizované pole |
| Zbývající rodiny | — | **k schválení** — pilotní výběr viz §7 | nevybíráme „první dostupný" nástroj |

Každá reference musí mít **zamčenou verzi v `pyproject.toml` extras `[diffref]`**
(graceful degradation: bez instalace → parser zůstává `validated`, jen se nedosáhne
stavu `differentially_validated`).

## 3. Normalizační vrstva (klíčová)

Bez normalizace je diff plný šumu. Pravidla (čistá doménová funkce, testovaná):

1. **Čas:** vše → Unix epoch sekundy UTC; CFAbsoluteTime/Win epoch se přepočítávají
   deklarovanou konverzí (tabulka epoch patří do parseru, normalizace jen validuje typ).
2. **Řazení:** soubory záznamů se řadí deterministicky (typ → ts → stabilní klíč);
   pořadí v surovém výstupu se nepočítá jako rozdíl.
3. **Kódování/locale:** vše → UTF-8, NFKC normalizace textových polí; `None`/prázdný
   string se rozlišují explicitně (chybějící pole ≠ prázdné pole).
4. **Identita záznamu (join key):** každý typ artefaktu má deklarovaný join key
   (např. URL pro visits, from+subject+ts pro e-mail). Bez join key se komparace
   nespustí — lépe selže explicitně než srovná řádky po sobě.
5. **Canonical record:** normalizovaný záznam = `{type, ts_epoch, fields{...}}` —
   jediný tvar, který vidí komparační engine (nezáleží na formátu vstupního nástroje).

## 4. Komparační engine a report rozdílných polí

Vstup: dvě sady canonical records (STOPA, reference) + join key deklarace.
Výstup (deterministický JSON):

```json
{
  "parser": "sqlite", "input_sha256": "…", "reference_tool": "sqlite3-dump@1.1.x",
  "stopa_records": 120, "ref_records": 118,
  "differences": [
    {"kind": "missing_in_ref",   "join_key": "visits:https://…"},
    {"kind": "extra_in_stopa",   "join_key": "…"},
    {"kind": "field_differs",    "join_key": "…", "field": "ts_epoch",
     "stopa_value": 1700000002, "ref_value": 1700000000}
  ],
  "identical_pct": 98.3
}
```

- `kind` ∈ {missing_in_ref, extra_in_stopa, field_differs} — třídí se podle
  sémantiky, ne podle toho, „kdo má víc".
- Report je **neměnný artefakt** (hash + uložení do případu) — opakovaný běh na
  stejný vstup musí dát bitově shodný report (determinismus: pevné řazení, bez
  timestampů běhu kromě deklarovaného `run_id`).

## 5. Sémantika verdiktů („ani jeden automaticky nemá pravdu")

Každý rozdíl má stav rozhodnutí:

| Stav | Význam |
|---|---|
| `UNADJUDICATED` | default — rozdíl čeká na člověka |
| `STOPA_WRONG` | reference je správně (dokumentováno proč) → bug ticket parseru |
| `REF_WRONG` | chyba reference/doplnění (např. nástroj ignoruje variantu formátu) |
| `SEMANTIC_DIFF` | oba „pravdiví", jiná sémantika — dokumentuje se, není to regrese |
| `AMBIGUOUS` | vstup poškozený/ambiguózní — rozhodnutí zůstává otevřené |

**Zlatá pravda (golden)** vzniká až po adjudikaci: opravené/reference ověřené záznamy
se ukládají do `tests/reference_datasets/<parser>/` jako ground truth. Od té chvíle
parser běží i proti golden sadě (rychlý režim bez referenčního nástroje) — to je
most k P1-1 regresní sadě.

## 6. Workflow (schválený proces)

```
1. výběr vstupního fixture        (anonymizovaný, hash zafixován v manifestu)
2. běh STOPA parseru              (pipeline, výstup → canonical records)
3. běh referenčního nástroje      (verze zamčená, výstup → canonical records)
4. normalizace obou stran         (§3 — sdílený modul, testovaný samostatně)
5. komparace                      (§4 → report rozdílných polí, neměnný artefakt)
6. adjudikace člověkem            (každý rozdíl → stav z §5 + zdůvodnění)
7. update reference_dataset       (golden sady do tests/reference_datasets/)
8. parser-status: validated → differentially_validated  (nový stav, aditivní)
```

CLI návrh: `stopa differential <parser> --input FILE [--tool NAME] [--format json]`
(exit 0 = shoda, 3 = pouze `SEMANTIC_DIFF`, 1 = neadjudikované rozdíly).
Zatím **design** — implementace po schválení (malý celek: normalizace + engine + CLI).

## 7. Pilotní výběr a rozvoj (rozložení rizika)

- **Vlna 1 (pilot, ~2 týdny):** `sqlite` (nejširší rodina, deterministický dump)
  + jeden textový formát (`syslog` nebo `access_log`) — ověřit workflow end-to-end.
- **Vlna 2:** PDF + Office rodiny (normalizace metadata).
- **Vlna 3+:** dle priority forenzního dopadu a dostupnosti referencí; každá vlna =
  samostatný releasovatelný celek s AK: „N parserů má `differentially_validated`".

Rozšíření stavu `validated → differentially_validated` je **aditivní** (nové hodnotové
sémantikum, ne přepis) — kompatibilita CLI/Web reportů zachována.

## 8. Akceptační kritéria design doc

1. Workflow §6 schválený (uživatelský souhlas nebo explicitní „pokračuj" v autonomním režimu).
2. Normalizační pravidla §3 pokryta unit testy (epochy, řazení, NFKC, join key fail-fast).
3. Report §4 deterministický — dva běhy na stejný vstup = bitově shodný JSON.
4. Pilotní sada parserů (§7 vlna 1) vybrána a reference zamčené verzemi.

## 9. Známe limity návrhu

- Referenční nástroje jsou **externí závislosti** — offline režim vyžaduje jejich
  předinstalaci (extras `[diffref]`), jinak zůstává jen `validated`.
- Adjudikace je lidská práce — bez ní se stav nezvyšuje; cílem není automatizovat
  pravdu, ale ji **doložitelně** evidovat.
- Join key deklarace je nová povinnost pro každou typologii artefaktů (rozšíření
  `KNOWN_ARTIFACT_TYPES` — aditivní pole).
