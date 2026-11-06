# STOPA — NEXT ACTION

## Aktuální stav (2026-11-06)
**STP-049 + STP-050 + STP-051 DOKONČENY ★★★** — ETAPA H (AI grounding), oblast I+O Validation Center UI a oblast G File Preview v UI hotové.

## Hotové
- **STP-051:** File Preview v UI — `domain/file_preview.py` (čistá logika: `classify_preview()` magic bytes PNG/JPEG/GIF/WebP/BMP/WAV/RIFF-WMA/FLAC/MP3/ID3/MP4 + příponový fallback, `extract_text_preview()` UTF-8+BOM/NUL→binární/truncace 4000, `preview_media_type()`); endpoint `GET /api/files/{fid}/preview` (media inline / text JSON {text,truncated} / 415 neznámý typ / 404 chybějící soubor); SPA sekce PREVIEW v inspectoru (`loadPreview()`, object URL lifecycle, styling). Full suite **1919 passed, 1 skipped** (+18), ruff clean. **Oblast G dokončena ★.**
- **STP-050:** Validation Center v GUI — endpointy `GET /api/cases/{id}/validation` (C6 report) + `GET /api/validation/registry` (C3 registry); SPA modul `mod-validation`. Full suite 1901 passed, ruff clean. Commit `0b761ab`.
- **STP-049:** AI grounding — `domain/ai_grounding.py`, zapojení do všech 3 AI režimů (pole `grounding`), GUI ⚠ štítky citací + findings panel; dokumentace `docs/STOPA_AI_ARCHITECTURE.md` §1.1. Commit `1c107ba`.
- **STP-048:** sandbox E2E testy + corrupt-file regression EVTX/LNK + dokumentace `docs/STOPA_SANDBOX.md` (ETAPA M uzavřena).

## Další krok — výběr oblasti (pořadí podle priority)
1. **O Audit Center modul** — UI pro audit trail (doplní oblast O po Validation Centeru; nejbližší logická navázání na STP-050).
2. **J Case Management 2.0** — rozšíření RBAC.
3. **K Export Engine** — Plaso formát (volitelné).
