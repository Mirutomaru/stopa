# STOPA — NEXT ACTION

## Aktuální stav (2026-11-06)
**STP-049 + STP-050 + STP-051 + STP-052 + STP-053 DOKONČENY ★★★★★** — ETAPA H (AI grounding), oblast I+O Validation Center UI, oblast G File Preview v UI, **oblast O Audit Center a oblast J Case Mgmt 2.0 (RBAC enforcement) hotové.**

## Hotové
- **STP-053:** RBAC permission matrix + enforcement — `domain/rbac.py` rozšířeno o matici role analyst/examiner/admin × 8 oprávnění (`case.read/analysis.run/file.flag/case.create/case.update/case.delete/source.add/settings.write`), `can()` fail-closed (neznámá role → jen case.read, neznámé oprávnění → False), `require_permission()` → RBACDenied, `permissions_for()`, `normalize_role()`; default = examiner. `web/app.py` — `_require()` na mutující endpointy: POST/PATCH/DELETE cases, POST sources, timeline/correlate/AI query+analyze (analysis.run), file flag, PUT settings (settings.write + validace role → 400); GET settings vrací `permissions`. Bez auth vrstvy = operační guardrail. Full suite **1956 passed, 1 skipped** (+29), ruff clean. **Oblast J rozšířena ★.**
- **STP-052:** Audit Center modul (`mod-audit`) — endpoint `GET /api/cases/{id}/audit` agreguje C4 integrity vrstvu: `verify_audit_chain()` (SHA-512 hash chain, first/last hash, broken index), Ed25519 kontrolní body + nezávislé ověření podpisů (`verify_integrity_checkpoints`), public key (base64), audit záznamy; SPA `js/components/audit.js`. Full suite 1927 passed (+8). **Oblast O dokončena ★.**
- **STP-051:** File Preview v UI — `domain/file_preview.py` + endpoint `GET /api/files/{fid}/preview`; SPA sekce PREVIEW. Commit `11d80e4`. **Oblast G dokončena ★.**
- **STP-050:** Validation Center v GUI — endpointy `GET /api/cases/{id}/validation` + `GET /api/validation/registry`; SPA modul `mod-validation`. Commit `0b761ab`.
- **STP-049:** AI grounding — `domain/ai_grounding.py`, zapojení do všech 3 AI režimů. Commit `1c107ba`.

## Další krok — výběr oblasti (pořadí podle priority)
1. **K Export Engine** — Plaso formát (volitelné; JSONL/XML/STIX 2.1 hotové STP-023).
2. **Q Interop / UCO mapping** — volitelné rozšíření exportu.
3. **J Case Mgmt 2.0 UI** — přepínač role v Settings (RBAC enforcement hotový, chybí jen UI ovládání).
