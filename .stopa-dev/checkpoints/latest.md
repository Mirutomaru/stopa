# STOPA — Checkpoint (latest)

**Datum:** 2026-11-03
**Verze aplikace:** 0.1.0 (`pyproject.toml`)
**Commit:** ``9707cd8`` (předchozí: `e0c34b3` STP-021, `5f964f5`, `6d74ab3`, `7360bab`, `cd5aa25`)

## Hotovo v tomto checkpointu
**STP-022 — Security: SHA-512 integrity vrstva + RBAC minimální + pip-audit CI** (oblast M, P2)

### Změny
- `domain/integrity.py` — `compute_audit_hash(..., algo=)` / `verify_chain(rows, algo=)`;
  per-algorithm GENESIS (`_GENESIS_BY_ALGO`: sha256 = 0×64, sha512 = 0×128) + fail-fast validace;
  `build_manifest(include_sha512=True)` opt-in, `ManifestEntry.sha512` (default None).
- nový `domain/rbac.py` — čistá logika: `normalize_actor`, `require_actor` (+`ActorError`),
  `resolve_actor`; `db.log_operation(strict=)` — atribuce explicitní actor > case examiner > None.
- `models.py` — `FileRecord.sha512`, `ProcessingProfile.compute_sha512`.
- `domain/profiles.py` — FORENSIC `compute_sha512=True` (ediscovery/quick ne).
- `data/db.py` — sloupec `files.sha512` v SCHEMA + idempotentní migrace; `upsert_file`,
  `row_to_record` defenzivně, `search_by_hash()` přes SHA-256/SHA-512/MD5.
- `pipeline.py` — one-pass hashing +SHA-512 podle profilu (hashlib multi-hash); dedupe seed/check.
- `domain/report.py` + `presentation/case_report.py` — CoC manifest +SHA-512 sloupec (jen když existuje).
- `.github/workflows/ci.yml` — nový job `security` s pip-audit
  (`pip freeze | grep -v "^-e \|^stopa @\|^stopa==" > requirements.txt && pip-audit --no-deps -r requirements.txt`).

### Testy
- **32 nových testů** (`tests/test_stp022.py`) — všechny zelené.
- Full suite: **1149 passed, 1 skipped** (baseline 1117 + 32). Ruff clean.

### Registry / docs
- F-053 (FEATURE_REGISTRY), T-074 (TEST_REGISTRY), TASKS STP-022 DONE,
  PROJECT_STATE aktualizován, NEXT_ACTION → STP-023, changelogy (kořen + zrcadlo) + DEV OS CHANGELOG.

## Další krok
**STP-023 — Export: JSONL/XML/STIX formáty** (oblast K/Q, P3) — viz `NEXT_ACTION.md`.
