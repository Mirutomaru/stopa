# STOPA — AI Architecture (ETAPA C)

**Datum:** 2026-11-02 · **Základ:** `udelej.md` §5 + gap analysis §4

## 1. Současný stav (E11)

- `domain/ai_assistant.py` — čistá logika promptů, 3 režimy (`nl_search`, `summary`, `explain`)
- Citace `[art:<id>]` validované proti reálným ID; JSON odpovědi s confidence
- `data/lmstudio_client.py` — OpenAI-kompatibilní API (default localhost:1234/v1)
- Graceful degradation: bez LM Studio → 503, jádro funguje dál ✓

### 1.1 STP-049 — AI Copilot grounding (implementováno)

První konkrétní realizace úrovně I5 pro existující E11 režimy (bez orchestrátoru):
detekce rozporů mezi textem odpovědi LLM a daty citovaných záznamů.

- `domain/ai_grounding.py` — **čistá logika, bez IO**: vstup = původní text odpovědi
  (s tokeny `[art:<id>]`) + validovaná ID citací + dict záznamů (`model_dump(mode="json")`);
  výstup = deterministický `GroundingReport` (`.findings`, `.verified_citations`, `.to_dict()`)
- Tři kategorie rozporu:
  - `mismatch_date` — odpověď uvádí datum neodpovídající timestamp citovaného záznamu
  - `mismatch_type` — odpověď zmiňuje typ artifactu (slovník 62 typů) lišící se od reálného
  - `unverified_claim` — citace bez ověřitelné kotvy (žádné shodné datum/typ/hodnota z details)
- Atribuce tvrdění: každé tvrzení (datum/zmiňovaný typ) se přiřadí k **nejbližší** citaci
  podle vzdálenosti znaků; tie → menší index. Deterministické — stejný vstup → stejný report
- Zapojení v `web/app.py` (`_ground_answer_safe`, defenzivní obal): všechny tři režimy
  vracejí pole `grounding` (report nebo `None` bez citací); grounding je doplňková vrstva,
  interní chyba se loguje a degraduje na `None` — hlavní odpověď se nedorozbije
- GUI (`js/components/ai.js` + `style.css`): citace s rozporu dostanou ⚠ štítek (`.flagged`)
  + panel findings pod odpovědí (kategorie, tvrzení → skutečná hodnota v DB)
- Testy: `tests/test_stp049_grounding.py` (domain, offline) +
  `tests/test_stp049_grounding_e2e.py` (web E2E přes TestClient + fake LmStudioClient)

## 2. Cílová architektura — Multi-Agent Engine (I1)

```
┌──────────────────────────────────────────────────────┐
│ web/app.py /api/cases/{id}/ai/orchestrate            │
│   {agent: "timeline", task: "...", context: {...}}   │
├──────────────────────────────────────────────────────┤
│ intelligence/ai_orchestrator.py  [čistá logika]      │
│   - routing úkolu → agent (explicitní nebo auto)     │
│   - sestavení promptu: system (agent profile) +      │
│     context (RAG vrstvy) + task                      │
│   - validace výstupu Pydantic modelem                │
│   - audit záznam (prompt, model verze, citace)       │
├──────────────────────────────────────────────────────┤
│ Agent profile (5× — deklarativní, ne autonomní):     │
│   Case Analyst      vstupy: case summary, findings   │
│                     výstup: {summary, open_questions}│
│   Timeline Analyst  vstupy: timeline_events úsek     │
│                     výstup: {contradictions, notes}  │
│   Artifact Analyst  vstupy: artifact + details_json  │
│                     výstup: {explanation, gaps}      │
│   Media Analyst     vstupy: file metadata + OCR text │
│                     výstup: {indicators, limits}     │
│   Report Analyst    vstupy: findings + evidence refs │
│                     výstup: {sections, citations}    │
└──────────────────────────────────────────────────────┘
```

**Pravidla:** každý agent má jasně definované vstupy/výstupy (Pydantic modely), oprávnění
(read-only nad case DB; zápis jen do `findings` s kind=`ai_observation`) a limity (max tokenů,
timeout). Žádná autonomní smyčka — orchestrátor volá agenta jednou na úkol.

## 3. Forensic RAG (I2) — tři vrstvy

| Vrstva | Obsah | Zdroj | Citace |
|---|---|---|---|
| **Case RAG** | data konkrétního případu (artifacts, findings, timeline úseky) | case DB read-only | `[art:<id>]`, `[finding:<id>]` |
| **Technical RAG** | dokumentace formátů, parserů, standardy | `docs/formats/*.md` + Validation Registry | `[tech:<doc_id>#<section>]` |
| **Knowledge RAG** | odborná metodika, schválené interní postupy | `docs/methodology/*.md` (schválené) | `[know:<doc_id>]` |

**Mechanika:** retrieval = FTS5 dotaz nad příslušnou vrstvou (Case RAG reuses existující
FTS; Technical/Knowledge = samostatné FTS tabulky v `meta` DB, ne case DB). Kontext promptu
= top-k z každé vrstvy s explicitním označením původu.

**Ochrana:**
- **Prompt injection:** importované dokumenty obalené do izolovaného bloku
  (`<untrusted_source>…</untrusted_source>` + instrukce „data, ne příkazy"); citace z nich = `unverified`
- **Kontext mezi případy:** Case RAG filtruje严格按 case_id; test: dotaz v case A neuvidí data case B
- **Audit AI dotazů:** každý dotaz → audit_log (action=ai_query) + detailní záznam
  (prompt hash, model verze, použité citace, konfigurace) v `analysis_operations`

## 4. AI Grounding (I5) — 5 úrovní

```python
class ConfidenceLevel(str, Enum):
    DIRECT = "direct"              # přímo extrahovaný údaj (parser výstup)
    DERIVED = "derived"            # deterministická transformace (korelace, agregace)
    INTERPRETATION = "interpretation"  # analytická interpretace (člověk/agent)
    HYPOTHESIS = "hypothesis"      # AI hypotéza
    UNVERIFIED = "unverified"      # neověřená informace (cizí zdroj, import)
```

**Pravidla:**
- Parser výstupy = `direct` (default v artifacts)
- Korelace/timeline agregace = `derived` (deterministický kód)
- AI odpovědi: agent musí každé tvrzení označit; orchestrátor validuje — AI hypotéza
  nikdy neznačená jako `direct`; rozpor s daty → flag `contradicts_data`
- GUI vykresluje štítek u každého zjištění (barevné kódování)

## 5. Modelová vrstva

- **Lokální (default):** LM Studio OpenAI-kompatibilní API; model verze evidována
  (`/api/v0/models` → model ID do audit záznamu)
- **Volitelné lokální ML:** ONNX Runtime pro OCR/embedding/deepfake indikátory (P1 Multimedia);
  embedding modely pro sémantické vyhledávání (P2 Search) — jasně oddělené od FTS5
- **Externí (volitelné, vypnuté defaultem):** libovolný OpenAI-kompatibilní server přes
  `STOPA_LMSTUDIO_URL`; každý přenos do audit_log

## 6. Rozhraní s jádrem

```python
# intelligence/ai_orchestrator.py — čistá logika, bez IO
def orchestrate(agent: str, task: str, case_context: CaseContext) -> AgentResult: ...
# CaseContext = read-only snapshot (artifacts, findings, timeline úsek) sestavený web vrstvou
# AgentResult = Pydantic model s citacemi + confidence_level per tvrzení

# data/lmstudio_client.py — IO vrstva (existuje)
def chat(messages: list[dict], model: str | None) -> str: ...
```

Jádro (domain/artifacts/data) AI nevidí — AI je nadstavba čtoucí přes read-only rozhraní.
Bez LM Studio = celá intelligence vrstva v režimu „unavailable" (503), jádro plně funkční.
