# STOPA 2.1 — Bezpečnostní threat model (P0-5)

Zdroj: `ROADMAP_2_1.md` §C P0-5; stav kódu commit `c314435`. Každý nálezen má
stav ověření (VERIFIED = v kódu/testu, PARTIALLY VERIFIED = částečně) a konkrétní
soubor/řádek. Metodika: STRIDE-lite po hranicích důvěry (§2), ne „checklist bez kontextu“.

## 1. Souhrn nálezů (po dopadu)

| # | Hranice | Nález | Stav | Závažnost | Doporučení (P0.x) |
|---|---|---|---|---|---|
| T-1 | síť → web | Bootstrap/legacy okno: dokud neexistuje první uživatel, chráněné endpointy jsou otevřené | VERIFIED | MEDIUM | dokumentovat + volitelný `--require-user` flag (P0-2) |
| T-2 | síť → web | Lokální login bez hesla v bootstrap okně (jen username) | VERIFIED | LOW-MED | designové rozhodnutí; dokumentovat do deployment profilů |
| T-3 | OS user → host | `session_secret` = uuid4 persistovaný v `settings.json` (defaultní perms 0644) — lokální user foržuje tokeny (TTL 12 h) | VERIFIED | MEDIUM (sdílené prostředí) | CSPRNG + perms 0600 při prvním vytváření (P0-2) |
| T-4 | síť → web | Bind adresa přepisatelná (`--host`/settings.json); bez TLS na LAN = token v plaintextu (HMAC chrání integritu, ne důvěrnost) | VERIFIED | MEDIUM při použití / LOW default | warning v logu při bind ≠ 127.0.0.1 bez `--tls-note` (P0-4) |
| T-5 | host → AI | LM Studio na localhost:1234 bez auth — každý proces na hostu volá LLM a čte params nástrojů | VERIFIED | LOW (single-user forensika) | documentovat; volitelný API key env (P2) |
| T-6 | plugin → host | Neověřený kód běží pod stejným OS userem — rlimit/workdir izolují zdroje, ne soubory | VERIFIED (po P0-3) | MEDIUM | dedicated OS account / kontejner na úrovni servisu; `network_isolated` pro síť |
| T-7 | disk → důkazy | Evidence at rest bez šifrování; perms dědí OS user (SQLite + artefakty 0644) | VERIFIED | MEDIUM (sdílené prostředí) | deployment profil „hardened“: `chmod 750` case dir + dedicated account |
| T-8 | web → client | CSRF: server nestaví cookie (`set_cookie` v kódu nenalezeno) — token v localStorage + header; ochrana závisí na chování SPA | PARTIALLY VERIFIED | LOW-MED | ověřit ve validaci (P0-4); volitelně `SameSite=Strict` cookie fallback |
| T-9 | SSO → host | OIDC JWKS discovery = síťové volání při loginu (urllib, TLS); offline testovatelné přes `sso_fetcher` hook | VERIFIED | LOW | dokumentovat: legacy režim bez sítě funguje; SSO vyžaduje síť |
| T-10 | web → disk | Upload cesty (FastAPI `UploadFile`) — cílový write path + perms neověřeny systematicky | PARTIALLY VERIFIED | MEDIUM? | zařadit do P0-4 validačního labu (upload fuzzing) |

## 2. Hranice důvěry

```
┌────────────────────────── OS user „stopa" ──────────────────────────┐
│  web server (uvicorn, default bind 127.0.0.1:port)                  │
│   ├─ SPA (React) — token v localStorage, header X-Stopa-Token       │
│   ├─ case DB (SQLite) + artefakty na disku                           │
│   ├─ plugin sandbox (subprocess; P0-3: izol. workdir+rlimits)        │
│   └─ AI provider (LM Studio localhost:1234, HTTP bez auth)          │
│  SSO IdP (Keycloak/Okta) — RS256 JWKS / HS256 secret                │
└──────────────────────────────────────────────────────────────────────┘
```

## 3. Detail nálezů

### T-1 Bootstrap/legacy okno — VERIFIED
`src/stopa/data/user_repository.py:228` `multi_user_mode() = count_users() > 0`.
Dokud je počet uživatelů 0, multi-user režim (a s ním povinná session auth)
nenastal → endpointy jako `/api/users`, `/api/cases` přijmou neověřený request.
Test: `tests/test_f44_multitenant.py` (`make_user(client, "alice", "admin")  # legacy okno`).
**Dopad:** při bindu na LAN a pomalém vytvoření prvního admina může cizí user
zakládá org/role. **Mitigace dnes:** default bind 127.0.0.1 (`cli.py:3818`, E12).

### T-2 Lokální login bez hesla — VERIFIED
`src/stopa/web/app.py:2668` `auth_login`: větev `username` (bez `id_token`) je
povolená jen v bootstrap okně a ověří existence aktivního user záznamu —
žádné secret. Po nastoupení multi-user režimu → 401 „použijte SSO login“
(test F7, `tests/test_f44_multitenant.py:700`). **Design:** bootstrap je krátké
okno; při sdíleném hostu stačí znát username admina.

### T-3 session_secret v settings.json — VERIFIED
`src/stopa/web/app.py:456` `_session_secret()`: `uuid.uuid4().hex`, persist do
`settings.json`. uuid4 není CSPRNG (prakticky dostatečné pro HMAC, ale
dokumentovat); soubor má defaultní perms 0644 → jiný lokální user na hostu ho
přečte a foržuje platný token (TTL `_SESSION_TTL_S = 12 h`, `app.py:107`).
**Fix (P0-2):** při prvním vytváření `os.open(..., mode=0o600)` + volitelně
`secrets.token_hex(32)`.

### T-4 Bind adresa bez TLS — VERIFIED
`src/stopa/cli.py:3817-3822`: `host = args.host or _settings_bind_address() or "127.0.0.1"`,
`uvicorn.run(app, host=host, ...)`. Bez TLS terminátoru na LAN je HMAC token
viditelný (integrovanost ano, důvěrnost ne). **Fix (P0-4):** warning v start logu.

### T-5 AI provider bez auth — VERIFIED
`src/stopa/cli.py:3623` odkaz na LM Studio `localhost:1234`; HTTP bez auth tokenu.
V single-user forenzním workstationu akceptovatelné; params nástrojů (JSON) jsou
viditelné všem procesům na hostu.

### T-6 Plugin sandbox — VERIFIED (po P0-3, commit `c314435`)
Neověřený plugin běží pod stejným OS userem: rlimity (`RLIMIT_AS/CPU/NOFILE`),
izolovaný workdir a volitelné `unshare --net` chrání zdroje a síť, ale ne
souborový systém. **Doporučení:** STOPA běžet pod dedicated OS account; pro
tvrdou izolaci kontejner na úrovni servisu (systemd `DynamicUser=` / Docker).

### T-7 Evidence at rest — VERIFIED
Case DB = SQLite soubor + artefakty; bez šifrování, perms dědí umask spouštěcího
uživatele. Forenzní standardy to u interního nasazení akceptují (důkazní řetěz
je hash-based — `case_seals` Ed25519 + Merkle root), ale na sdíleném hostu je
čtení možné i pro cizí user. **Fix (P0-4):** deployment profil „hardened“.

### T-8 CSRF / cookie — PARTIALLY VERIFIED
Server nestaví cookie (`set_cookie` v `app.py` nenalezeno, 2026-11-18); token se
vrací v JSON těle a klient ho posílá headerem. Ochrana proti CSRF tedy závisí na
SPA (localStorage + header = typicky bezpečné). **Ověřit:** P0-4 lab.

### T-9 SSO síťová závislost — VERIFIED
`app.py:2687+` `_sso_verify_id_token`: discovery `{issuer}/.well-known/...` přes
`urllib.request.urlopen(timeout=10)`; RS256 přes JWKS nebo HS256 secret z env.
Testovací hook `sso_fetcher` → offline testy bez sítě (pravidlo 10 splněno).

### T-10 Upload cesty — PARTIALLY VERIFIED
FastAPI `UploadFile` např. `app.py:1916` (plaso import). Cílový write path,
perms a název souboru neověřeny systematicky → **P0-4 upload fuzzing**.

## 4. Co už chrání (mitigace v kódu)

| Mitigace | Důkaz |
|---|---|
| Fail-closed session auth (HMAC-SHA256, TTL 12 h, tamper → None) | `app.py:107-146`, test M5 |
| RBAC per permission (`_require("settings.read", ...)`) + globální admin fallback | `tests/test_f44_multitenant.py` A1–A6 |
| Audit log hash chain (append-only) | F5.x, `data/audit_log*` |
| Ed25519 case seals + Merkle root (tamper-evidence) | F5.1 `domain/case_seal.py` |
| Plugin sandbox P0-3: izol. workdir, RLIMIT_AS/CPU/NOFILE, output cap, unshare net | commit `c314435`, `tests/test_p03_sandbox_hardening.py` (60 testů) |
| Default bind 127.0.0.1 (E12) | `cli.py:3818` |
| AI graceful degradation — síť není povinná pro základní forensiku | F4.x, pravidlo 10 |

## 5. Deployment profily (doporučení)

| Profil | Podmínky | Residual risk |
|---|---|---|
| **workstation** (default) | bind 127.0.0.1, single OS user, LM Studio lokálně | LOW — T-3/T-6/T-7 omezeny na jeden user |
| **team LAN** | SSO povinné, admin vytvořen okamžitě, TLS terminátor (nginx) | MEDIUM → LOW po T-4 warningu + T-1 flagu |
| **hardened server** | dedicated OS account, case dir 0750, `network_isolated` pluginy, kontejner | LOW — T-6/T-7 uzavřené na úrovni OS |

## 6. Zbývající ověření (předání do P0-4 validační lab)
1. Upload fuzzing: název/cíl/perms uploadovaných souborů (T-10).
2. Cookie/CSRF chování SPA při `stopa_token` cookie fallbacku (T-8).
3. Práce s `settings.json` perms po T-3 fixu (regrese 0600).
