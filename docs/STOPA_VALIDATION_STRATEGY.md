# STOPA — Validation Strategy (ETAPA C)

**Datum:** 2026-11-02 · **Základ:** `docs/prompts/udelej.md` §13 (Forensic Validation Laboratory) + E13 backlog

## 1. Principy

1. **Unit test ≠ forenzní validace.** Parser prochází unit testy = funkční; je *forenzně
   validovaný* až po ověření na referenčním datasetu s očekávanými výsledky (NIST/SWGDE-style).
2. **Každý parser má identitu** — ID, verzi, formáty, omezení, referenční dataset, očekávané
   výsledky. Bez identity = `NEEDS VALIDATION`.
3. **Determinismus** — benchmarky a regresní sada běží na fixních datech; výsledek je reprodukovatelný.

## 2. Parser Validation Registry (C3)

Deklarativní registry v `domain/validation_registry.py`:

```python
@dataclass(frozen=True)
class ParserValidation:
    parser_id: str            # např. "win_prefetch"
    version: str              # např. "1.0.0" (synchronizováno s pipeline ARTIFACT_EXTRACTORS)
    formats: tuple[str, ...]  # podporované formáty ("prefetch v2/v3")
    limitations: tuple[str, ...]  # známá omezení
    reference_dataset: str | None   # cesta do tests/reference_datasets/
    expected_results: dict      # očekávané počty/typy artefaktů na referenčním datasetu
    positive_tests: int         # počet pozitivních testů
    negative_tests: int         # počet negativních testů (poškozený soubor → [])
    edge_case_tests: int        # edge-case testy
```

**Zdroj pravdy:** registry se generuje z `pipeline.ARTIFACT_EXTRACTORS` + `NAME_BASED_EXTRACTORS`
(verze parseru už existují) a doplní se o formáty/omezení/referenční datasety. Test ověří, že
každý extraktor v pipeline má záznam (a naopak).

## 3. Referenční datasety (`tests/reference_datasets/`)

- Malé syntetické soubory pro každý parser (generované skriptem, commitované do repo)
- Každý dataset: `README.md` (původ, jak generován) + `expected.json` (očekávané artefakty)
- Negativní varianty: poškozené/krátké soubory → očekává se `[]` bez výjimky

## 4. Benchmark Engine (C6)

`data/benchmark_engine.py`:
- **Vstupy:** referenční datasety + syntetické velké sady (např. 10k souborů, 1 GB obraz)
- **Metriky:** čas zpracování, RAM peak (tracemalloc), počet artefaktů
- **Determinismus:** fixní seed, `timeit` nad čistými moduly; IO benchmarky volitelné
- **Historie:** výsledky se ukládají do `meta` (benchmark_history) → trendová detekce regresí
- **CLI:** `stopa benchmark [--suite core|parsers|images]`

## 5. Regression Test Engine

- Existujících 642 testů = základní regresní sada ✓
- Nové: `tests/test_validation_registry.py` (registry vs pipeline), `tests/test_benchmark_engine.py`,
  `tests/test_migrations_v7.py` (v6→v7)
- **CI:** ruff + pytest + JS DOM testy (existuje); benchmark jako volitelný job (neblocking, jen trend)

## 6. Test Coverage Dashboard

- `stopa coverage-report` → HTML/JSON přehled: parser × (positive/negative/edge/reference)
- Data z Validation Registry + výsledků posledního běhu
- GUI: sekce v System Diagnostics (P2 workspace)

## 7. Performance Benchmarking

- Baseline naměřený při C6; každý nový parser přidá benchmark entry
- Regresní práh: >20% zpomalení na referenčním datasetu = warning v reportu

## 8. Evidence Validation Reports

- `stopa validate <case_id>` → report: pro každý artifact — parser ID+verze, validation status,
  confidence, provenance; souhrn coverage (kolik artefaktů je z validovaných parserů)
- Export CSV/JSON (existující export mechanismus) + HTML (report engine)

## 9. Reference zdroje

- **NIST** — Computer Forensics Tool Validation (CFToolVal) metodika
- **SWGDE** — Scientific Working Group on Digital Evidence best practices
- Dokumentace formátů: Microsoft docs (LNK/Prefetch/EVTX/USN), SQLite file format, plist spec,
  C2PA spec, Volatility 3 docs

## 10. Kritéria validace parseru

Parser je **forenzně validovaný** pokud:
1. Má záznam v Validation Registry (ID, verze, formáty, omezení) ✓
2. Prochází pozitivními testy na referenčním datasetu s očekávanými výsledky ✓
3. Prochází negativními testy (poškozený soubor → `[]`, ne výjimka) ✓
4. Má edge-case testy (prázdný soubor, maximální velikost, neplatné encodingy) ✓
5. Má regresní test (změna parseru = změna očekávaného výsledku je explicitně zaznamenána) ✓

Bez bodu 2–3 = `NEEDS VALIDATION` (funkční, ale netvrzeno jako forenzně validovaný).
