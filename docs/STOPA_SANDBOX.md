# STOPA — Parser Sandbox (ETAPA E / izolace parserů)

Izolace artifact extraktorů od hlavního procesu pipeline. Poškozený vstupní soubor
nesmí **viset** ani **crashnout** celou analýzu — každý parser běží v dceřiném
procesu s timeoutem a limitem velikosti výsledku, výsledek se marshalluje jako JSON.

Původ: nález auditu STP-045 — `sqlite_carver` visel >15 s na garbage
`db_size_pages` = 1,7 mld. stránek v 920 B souboru (bez jakéhokoli limitu).

---

## Součásti

| Soubor | Role |
|--------|------|
| `src/stopa/domain/sandbox.py` | Kontrakt — čisté funkce + tenký IO wrapper (`run_extractor_sandboxed`) |
| `src/stopa/sandbox_worker.py` | Dceřiný proces (entrypoint `python -m stopa.sandbox_worker`) |
| `src/stopa/pipeline.py` | Zapojení — `_run_extractor()` dispatchuje každý extraktor přes sandbox |

---

## Kontrakt workeru

Worker se spouští:

```
python -m stopa.sandbox_worker <module_name> <func_name> <path>
```

| Kanál / stav | Kontrakt |
|--------------|----------|
| **stdout** | POUZE JSON array artifactů (`model_dump(mode="json")`) — nic jiného. Parsery nesmí psát na stdout (žádné `print()` v `src/stopa/artifacts`). |
| **stderr** | Logy a traceback — konzument čte jen při crashi (posledních 512 B). |
| **exit 0** | Úspěch — payload na stdout je platný. |
| **exit 1** | Parser selhal (jakákoli výjimka → kategorie `crash`). |

Worker aplikuje **RLIMIT_CPU backstop** (POSIX): CPU limit = `2 × STOPA_SANDBOX_TIMEOUT`.
I kdyby externí timeout selhal, proces zemře po N CPU sekundách. Na platformě bez
`resource` modulu (Windows) backstop chybí a spoléháme jen na wall-clock timeout.

---

## Limity (`SandboxConfig`)

| Parametr | Default | Popis |
|----------|---------|-------|
| `timeout_s` | **30 s** | Maximální doba běhu dceřiného procesu (wall-clock). Musí být > 0. |
| `max_result_bytes` | **16 MiB** | Maximální velikost JSON payloadu na stdout. Musí být ≥ 1. |

Defaults jsou dostatečné pro reálné parsery (iCloud XLSX, registry hives) a krátké
proti neomezenému CPU spinu. Pipeline používá `SANDBOX_CONFIG = SandboxConfig()`
(defaultní limity). Testy mohou timeout zkrátit (`SandboxConfig(timeout_s=1.5)`),
aby byly deterministické bez čekání 30 s.

---

## Kategorie selhání (stabilní řetězce pro audit log)

Klasifikace `failure_category()` — **priorita: timeout > truncated > bad_payload > crash**.

| Kategorie | Význam | Kdy nastane |
|-----------|--------|-------------|
| `timeout` | Parser přesáhl `timeout_s` | `subprocess.TimeoutExpired` (wall-clock) |
| `truncated` | Payload přesáhl `max_result_bytes` | `len(stdout) > max_result_bytes` |
| `bad_payload` | Platný JSON, ale nesplňuje kontrakt | Ne-array / položka neobjekt / chybí `artifact_type`; nebo Pydantic `ValidationError` při `Artifact.model_validate` |
| `crash` | Dceřiný proces padl | `returncode != 0` (výjimka v parseru) nebo zabit signálem (`returncode=None`) bez timeoutu |

Každé selhání se stane **`parser_error` artifact** (pipeline nepadne):

```python
Artifact(
    artifact_type="parser_error",
    title="parser selhal (<category>)",
    details={
        "category": <timeout|truncated|bad_payload|crash>,
        "error": <lidsky čitelná chyba>,
        "parser": "<module>.<func>",   # audit log — který parser selhal
    },
    parser_version=<verze extraktoru>,
)
```

---

## Fallback bez sandboxu

`_run_extractor()` volá sandbox jen když `SANDBOX_ENABLED and sandbox_available()`:

- **`SANDBOX_ENABLED`** = `os.environ.get("STOPA_SANDBOX", "1") != "0"` — vypnutí přes
  env `STOPA_SANDBOX=0`.
- **`sandbox_available()`** = worker modul je importovatelný (`importlib.util.find_spec`).

Jinak **fallback = přímé in-process volání** `fn(path)` (původní chování před ETAPou E).
To znamená: sandbox vypnutý nebo worker nedostupný → parser běží v hlavním procesu,
bez izolace (ale pipeline funguje).

---

## Jak přidat parser do sandboxu

Parser **automaticky** běží přes sandbox, když je registrovaný v jedné z dveh map
v `pipeline.py` — žádná další úprava není potřeba:

1. **Podle signatury (magic bytes)** → `ARTIFACT_EXTRACTORS[signature_type] = (fn, version)`
2. **Podle názvu souboru** → `NAME_BASED_EXTRACTORS[name_key] = (fn, version)`

Obě cesty `_extract_artifacts_for()` vedou přes `_run_extractor()`, který dispatchuje
do sandboxu. Požadavky na funkci:

- Signatura: **`def fn(path: Path) -> list[Artifact]`** — bere `Path`, vrací list artifactů.
- Modul musí být importovatelný jménem (worker dělá `importlib.import_module(module_name)`).
- Funkce nesmí psát na stdout (poruší JSON kontrakt) — loguje přes `logging`.

Verze extraktoru (`version`) se eviduje na každém artifactu (E2 provenience /
reprodukovatelnost) a v audit logu při selhání.

---

## Testy

| Soubor | Pokrytí |
|--------|---------|
| `tests/test_stp046_sandbox.py` | Kontrakt — čisté funkce (config, validace payloadu, klasifikace, worker command) |
| `tests/test_stp047_sandbox_integration.py` | Zapojení do pipeline — `_run_extractor` přes reálný subprocess (úspěch / fallback / crash / timeout), corrupt SQLite regression |
| `tests/test_stp048_sandbox_e2e.py` | E2E — hangující parser přes celou `process_source` → `parser_error` v DB; corrupt EVTX/LNK regression |

Sandbox cesty spouštějí **reálný subprocess** (`python -m stopa.sandbox_worker`),
takže jsou pomalejší než unit testy, ale ověřují skutečný kontrakt end-to-end.
Vše offline a deterministické (timeouty zkrácené na ~1,5 s).
