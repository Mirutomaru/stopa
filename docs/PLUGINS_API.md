# STOPA Plugin API (F6.4)

**Verze:** 1.0 · **Minimální STOPA:** 2.0.0 · **Stav:** GA s Fázi 6

Pluginy rozšiřují STOPA o vlastní **extractory**, **triage profily** a
**AI tools**. Kontrakt zrcadlí vestavěnou infrastrukturu (parsery, F3.2
triage, F3.1 agent framework) — třetí strana píše jen deklarativní manifest
a malé moduly bez závislostí na STOPA vnitřnostech.

---

## 1. Struktura pluginu

Plugin je **adresář** s manifestem `plugin.json` a Python moduly:

```
plugins/muj-plugin/
├── plugin.json            # manifest (deklarace)
└── muj_plugin.py          # kód (importuje se až při použití)
```

### Manifest (`plugin.json`)

| Pole | Povinné | Výchozí | Popis |
|---|---|---|---|
| `name` | ✅ | — | slug `[a-z0-9._-]`, 2–64 znaků, unikátní napříč pluginy |
| `version` | ✅ | — | verze pluginu (semver) |
| `description` | | `""` | lidský popis |
| `author` | | `""` | autor |
| `min_stopa_version` | | `"2.0.0"` | kompatibilita; vyšší = upozornění v `plugin list` |
| `extractors` | | `[]` | seznam extractor kapacit (max 50) |
| `triage_profiles` | | `[]` | seznam triage profilů (max 50) |
| `ai_tools` | | `[]` | seznam AI toolů (max 50) |

Kapacita bez jakéhokoli záznamu = plugin je stub (validní, ale s upozorněním).

### Extractor kapacita

```json
{
  "key": "accesslog",
  "module": "example_accesslog_plugin",
  "detect_fn": "is_access_log_file",
  "extract_fn": "extract_artifacts",
  "parser_version": "1.0.0",
  "extensions": [".log"]
}
```

| Pole | Popis |
|---|---|
| `key` | unikátní uvnitř pluginu; namespace pro parser versioning (F5.3) |
| `module` | Python modul uvnitř plugin adresáře |
| `detect_fn` | funkce `(path: Path) -> bool`; prázdný = detekce jen podle `extensions` (name-based fallback, viz pipeline `_name_based_match`) |
| `extract_fn` | funkce `(path: Path) -> list[Artifact]`; default `extract_artifacts` |
| `parser_version` | verze parseru pro provenience artefaktů (F5.3 reproducibilita); default `"1.0.0"` |
| `extensions` | rozšíření souborů pro name-based detekci (lowercase, s tečkou) |

### Triage profil kapacita

```json
{ "module": "crypto_triage_plugin", "factory": "build_profile" }
```

Factory vrací **`stopa.intelligence.triage.TriageProfile`** (frozen dataclass).
Signály definuje `SignalSpec` — druhy: `artifact_type`, `artifact_text`,
`timeline_flag`, `file_pattern`, `entity_pattern`.

### AI tool kapacita

```json
{ "module": "case_stats_tool", "factory": "build_tools" }
```

Factory vrací **`list[stopa.intelligence.tool_agent.ToolSpec]`**. Handler podpis:
`(db: CaseDB, case_id: str, params: dict) -> Any` (JSON-serializovatelné).
Výjimka `ToolError` = observation pro LLM (smyčka může opravit), ne crash.

---

## 2. Kde pluginy hledá STOPA

Řazení zdrojů adresářů (první výhra při kolizi jména):

1. settings klíč **`plugins_dirs`** (seznam absolutních cest v `settings.json`)
2. environment **`STOPA_PLUGINS_DIR`** (oddělovač `os.pathsep`)
3. defaultní **`~/.stopa/plugins/`**

Ukázkové pluginy jsou v repozitáři pod `plugins/` — napojíte je přes
`STOPA_PLUGINS_DIR=$PWD/plugins` nebo zkopírováním do `~/.stopa/plugins/`.

---

## 3. Ověřené vs neověřené + sandbox

| Stav | Význam | Běh |
|---|---|---|
| **ověřený** | jméno v settings klíči **`plugins_verified`** (seznam stringů) | import přímo do hlavního procesu (rychle, plná API) |
| **neověřeny** | nikde v allowlistu | **sandbox**: entry point běží jako subprocess s limity |

Sandbox limity (settings klíč `plugin_sandbox`, defaulty):

| Pole | Default | Popis |
|---|---|---|
| `timeout_s` | 120 | wall-clock limit subprocessu |
| `max_mem_mb` | 512 | RLIMIT_AS (Linux) — fyzická strop paměti |
| `extra_env` | `{}` | dodatečné env pro sandbox proces |

Sandbox běh izoluje: výjimky pluginu nepadají hlavní proces, paměťová
exploze je omezená RLIMITem, únik času řeší timeout. Výsledek se vrací jako
JSON (artefakty serializované přes `model_dump`).

Správa allowlistu: `stopa plugin verify <name> --add / --remove`.

---

## 4. CLI příkazy

```bash
stopa plugin list [--json]              # manifesty + ověření + kapacity
stopa plugin info <name> [--json]       # detail jednoho pluginu
stopa plugin verify <name> --add        # přidat do allowlistu (settings.json)
stopa plugin verify <name> --remove     # odebrat ze sandboxu
stopa plugin run <name> --cap extractor --key <key> --file <file>   # běh extractoru (sandbox pokud neověřený)
stopa plugin run <name> --cap triage_profile                        # profily jako JSON
stopa plugin run <name> --cap ai_tool --case-id <cid> [--tool T] [--params '{}']
```

Web: `GET /api/plugins` — stejný payload jako `plugin list --json`.

---

## 5. Ukázkové pluginy (`plugins/`)

| Plugin | Kapacita | Co demonstruje |
|---|---|---|
| `example-accesslog` | extractor | Nginx/Apache combined log → `event_log_entry`; agregace per (ip, method, path), deterministické pořadí, kapce 500 skupin; detekce vzorkem řádků |
| `example-crypto-triage` | triage_profile | profil **crypto_exfiltration** — K-LINKA artefakty + wallet kontejnery + exchange exporty; komplementární ke vestavěnému RANSOMWARE |
| `example-ai-tool` | ai_tool | tool **artifact_type_breakdown** pro F3.1 agenta; `ToolError` sémantika, explicitní kapce s `truncated` flagem |

---

## 6. Doporučení pro autory pluginů

* **Defenzivní parsing** — entrypoint nikdy nevyhazuje výjimku doven
  (OSError/ValueError → log + prázdný výsledek), viz vestavěné parsery.
* **Determinismus** — stabilní řazení, žádné `set()` iterace bez sortu,
  časy v UTC ISO; parser version bumpujte u každé změny výstupu (F5.3).
* **Bez I/O mimo entrypoint** — čistá funkce na datech = testovatelnost.
* **Pouze veřejné STOPA API** — `stopa.models`, `stopa.data.db.CaseDB`,
  `stopa.intelligence.triage`, `stopa.intelligence.tool_agent`.
