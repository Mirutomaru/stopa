# SECURITY HARDENING — STOPA 2.1

Souhrn bezpečnostního zpevnění provedeného v cyklu 2.1 a aktuální stav ochrany.
Detailní nálezy s důkazy v kódu: `SECURITY_THREAT_MODEL.md` (T-1..T-10, STRIDE-lite).
Každá změna doložena commit + testy (viz `STOPA_CHANGELOG.md`).

## 1. Zpevnění provedené v 2.1

### P0-3 — Plugin sandbox hardening (`commit c314435`)
Neověřený plugin kód běží pod stejným OS userem; přidány zdrojové limity:
- **CPU limit** (RLIMIT_CPU), **output limit** (max bajtů stdout/stderr) v
  `SandboxLimits` + `_rlimit_factory()` (`data/plugin_loader.py`).
- **Izolovaný workdir**: každý běh dostane vlastní run-dir pod
  `$STOPA_PLUGIN_RUNS_DIR` (default `~/.stopa/plugin-runs/`) — plugin nevidí
  ostatní běhy a nepsá do case dir.
- Síťová izolace volitelná (`network_isolated`).
- Testy: `tests/test_p03_sandbox_hardening.py`.

### P0-2 — Seal key management (`domain/integrity.py`)
Privátní Ed25519 klíč integrity checkpointů předtím ležel v plaintextu base64
v `meta`. Nyní:
- **AES-GCM šifrování** privátního klíče master secret z env
  `STOPA_INTEGRITY_MASTER_KEY` (base64, 32 bajtů).
- **Fail-fast**: neplatný base64 / decoded délka ≠ 32 → `ValueError`.
- **Backward compatibility**: staré DB bez klíče čtou legacy plaintext b64;
  veřejný klíč se per-checkpoint ukládá do nové sloupce `public_key_b64`
  (schéma v20) — rotace klíčů nezničí staré checkpoints.
- Testy: `tests/test_p02_seal_keys.py`.

### P1-2 — AI prompt-injection ochrana (`domain/ai_orchestrator.py`)
- Důkazní texty před vložením do promptu procházejí `sanitize_evidence_text()`:
  C0 control znaky → mezernice, citace token `[art:` zneutralizován zero-width
  space (divoká citace v textu se neshoduje s reálným ID při validaci).
- Evidence bloky v delimitorech `<<<STOPA-EVIDENCE id=...>>>`; system prompt
  říká modelu, že text uvnitř je data, ne instrukce.
- Role agentů s **minimálními oprávněními** (read-only nástroje per role).
- Testy: `tests/test_p12_ai_orchestrator.py`.

## 2. Co už chrání (mitigace v kódu — stav po 2.1)

| Oblast | Ochrana | Důkaz |
|---|---|---|
| Integrity checkpointy | Ed25519 signature per checkpoint + Merkle seal; master key AES-GCM | `domain/integrity.py` |
| Provenance řetězec | parent_artifact_id + hashed_at (schéma v21), CLI exit codes 0/1/2 | `domain/provenance_chain.py` |
| Pluginy | sandbox rlimits + izolovaný workdir + volitelná síťová izolace | `data/plugin_loader.py` |
| AI PII | `_maybe_redact` rediguje e-maily/adresy v promptech | `domain/ai_assistant.py` |
| AI výstupy | grounding claimů na artefakty (citations musí existovat) | `domain/ai_grounding.py` |
| Tokeny web UI | HMAC tokeny s TTL; `session_secret` CSPRNG | `web/app.py`, settings |
| SSO | OIDC s offline fallbackem (legacy login bez sítě funguje) | T-9 v threat modelu |

## 3. Zbývající rizika a doporučení

| Riziko | Požadavek | Priorita |
|---|---|---|
| Bootstrap okno (T-1/T-2): endpointy otevřené dokud neexistuje první uživatel | volitelný `--require-user` flag + dokumentace deployment profilů | P1 |
| `session_secret` perms 0644 v settings.json (T-3) | CSPRNG + `chmod 0600` při prvním vytváření | P1 |
| Bind ≠ 127.0.0.1 bez TLS (T-4) | warning v logu + deployment profil | P1 |
| Evidence at rest bez šifrování, perms 0644 (T-7) | hardened profil: `chmod 750` case dir + dedicated OS účet | P2 |
| Plugin kód pod stejným OS userem (T-6) | kontejner / dedicated account; síť přes `network_isolated` | P2 |
| LM Studio bez auth na localhost (T-5) | volitelný API key env var | P2 |
| Upload cesty neověřeny systematicky (T-10) | upload fuzzing do validačního labu (P0-4 infrastruktura) | P2 |

Deployment profily („default“ / „hardened“) — doporučení v `SECURITY_THREAT_MODEL.md` §5.

## 4. Závěr

Všechny P0 bezpečnostní položky 2.1 hotové a testované (P0-2, P0-3). Hlavní
zbývající riziko v sdíleném prostředí: evidence at rest + session_secret perms
(obojí řeší „hardened“ deployment profil — P1/P2 na ROADMAP).
