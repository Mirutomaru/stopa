# STOPA — NEXT ACTION

## Aktuální stav (2026-11-06)
**STP-049 + STP-050 + STP-051 + STP-052 DOKONČENY ★★★★** — ETAPA H (AI grounding), oblast I+O Validation Center UI, oblast G File Preview v UI a **oblast O Audit Center hotové.**

## Hotové
- **STP-052:** Audit Center modul (`mod-audit`) — endpoint `GET /api/cases/{id}/audit` agreguje C4 integrity vrstvu: `verify_audit_chain()` (SHA-512 hash chain, first/last hash, broken index), Ed25519 kontrolní body + nezávislé ověření podpisů (`verify_integrity_checkpoints`), public key (base64), audit záznamy; SPA `js/components/audit.js` (`renderAuditCenter()` — stat karty, chain status badge valid/broken, kontrolní body verified/invalid, tabulka záznamů); registrace modules.js/sidebar.js (🛡). Full suite **1927 passed, 1 skipped** (+8), ruff clean. **Oblast O dokončena ★.**
- **STP-051:** File Preview v UI — `domain/file_preview.py` (magic bytes PNG/JPEG/GIF/WebP/BMP/WAV/RIFF-WMA/FLAC/MP3/ID3/MP4 + příponový fallback, UTF-8+BOM/NUL→binární/truncace 4000); endpoint `GET /api/files/{fid}/preview` (media inline / text JSON / 415 / 404); SPA sekce PREVIEW v inspectoru. Full suite 1919 passed, ruff clean. Commit `11d80e4`. **Oblast G dokončena ★.**
- **STP-050:** Validation Center v GUI — endpointy `GET /api/cases/{id}/validation` (C6 report) + `GET /api/validation/registry` (C3 registry); SPA modul `mod-validation`. Full suite 1901 passed, ruff clean. Commit `0b761ab`.
- **STP-049:** AI grounding — `domain/ai_grounding.py`, zapojení do všech 3 AI režimů (pole `grounding`), GUI ⚠ štítky citací + findings panel; dokumentace `docs/STOPA_AI_ARCHITECTURE.md` §1.1. Commit `1c107ba`.
- **STP-048:** sandbox E2E testy + corrupt-file regression EVTX/LNK + dokumentace `docs/STOPA_SANDBOX.md` (ETAPA M uzavřena).

## Další krok — výběr oblasti (pořadí podle priority)
1. **J Case Management 2.0** — rozšíření RBAC (P3; základ RBAC hotový STP-022, chybí rozšíření pro case management workflow).
2. **K Export Engine** — Plaso formát (volitelné; JSONL/XML/STIX 2.1 hotové STP-023).
3. **Q Interop / UCO mapping** — volitelné rozšíření exportu.
