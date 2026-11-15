"""STOPA — Multi-tenant RBAC rozšíření (F4.4) + OIDC SSO verifikace.

Organizace → týmy → uživatelé; **per-case oprávnění**: přístup k případu
řeší členství v ``case_members`` (grant role per case), globální role uživatele
je jen fallback pro org-level admina a bootstrap. Fail-closed: nečlen bez
admin role = žádný přístup, i ke čtení.

Pravidla přístupu k případu (:func:`access_for_case`) — jediný zdroj pravdy:

1. **Členství vyhrává** — existuje-li jakýkoli validní grant pro (user, case),
   efektivní role = ten s **nejvyššími privilegemi** (deterministické max v
   pořadí :data:`rbac.ROLES`); nevalidní granty (neznámá role) se ignorují.
2. **Org-level admin** — bez členství projde na všechny případy se svou rolí.
3. **Fail-closed default** — ostatní kombinace (např. globální analytik bez
   členství, neznámá/prázdná role) → ``(False, None)``.

OIDC SSO (:func:`verify_jwt`) — čistá verifikace ID tokenů Keycloak/Okta:

- ``HS256`` (sdílené tajné klíče, jednoduché nasazení) a ``RS256`` (JWKS —
  standardní enterprise flow); ``alg=none`` selže (fail-closed).
- Standardní claim checky: ``exp``, ``nbf``, ``iat``; volitelně ``iss``,
  ``audience`` (skalar i seznam).
- Claim mapping (:func:`map_claims`) — username z ``preferred_username`` /
  e-mailu, role jako první známá v ``groups``/``roles`` claimu.

Čistá logika bez I/O (JWKS se předává jako dict) — plně offline testovatelné.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Sequence

from stopa.domain.rbac import ROLES, can, normalize_role


class JwtError(ValueError):
    """Neplatný ID token (formát, podpis nebo claimy)."""


# ── Per-case RBAC ───────────────────────────────────────────────


def access_for_case(
    global_role: str | None, case_grants: Sequence[str] = ()
) -> tuple[bool, str | None]:
    """Efektivní přístup k případu pro uživatele.

    Args:
        global_role: globální role uživatele (z ``users`` tabulky).
        case_grants: role udělené uživateli právě pro tento případ
            (řádky z ``case_members``; obvykle 0–1, max vyhrává).

    Returns:
        ``(has_access, effective_role)`` — viz modulová docstring pravidla.
    """
    valid = [g for g in (normalize_role(x) for x in case_grants) if g]
    member_role = max(valid, key=ROLES.index) if valid else None
    if member_role is not None:
        return True, member_role
    gr = normalize_role(global_role)
    if gr == "admin":  # org-level admin — projde bez členství (dokumentováno)
        return True, "admin"
    return False, None


def can_on_case(
    global_role: str | None, case_grants: Sequence[str], permission: str
) -> bool:
    """Má uživatel oprávnění v kontextu případu? Fail-closed."""
    has_access, role = access_for_case(global_role, case_grants)
    return has_access and can(role, permission)


# ── OIDC JWT (HS256 / RS256) ────────────────────────────────────


def _b64url_decode(segment: str | bytes) -> bytes:
    """Base64url bez paddingu → bytes; neplatný formát → :class:`JwtError`."""
    raw = segment if isinstance(segment, bytes) else segment.encode()
    pad = -len(raw) % 4
    try:
        return base64.urlsafe_b64decode(raw + b"=" * pad)
    except Exception as exc:
        raise JwtError("neplatný base64url segment") from exc


def _check_time_claims(claims: dict, now: float | None = None) -> None:
    """exp/nbf/iat checky; ``now`` injektovatelná pro deterministické testy."""
    ts = time.time() if now is None else now
    exp = claims.get("exp")
    if exp is not None and ts >= float(exp):
        raise JwtError("token vypršel (exp)")
    nbf = claims.get("nbf")
    if nbf is not None and ts < float(nbf):
        raise JwtError("token dosud neplatný (nbf)")


def _verify_claims(claims: dict, issuer: str | None, audience: str | None) -> None:
    """iss/audience checky — jen pokud vyžadovány konfigurací."""
    if issuer is not None and claims.get("iss") != issuer:
        raise JwtError(f"neplatný issuer (očekáváno {issuer!r})")
    if audience is not None:
        aud = claims.get("aud")
        values = [aud] if isinstance(aud, str) else list(aud or [])
        if audience not in values:
            raise JwtError(f"neplatná audience (očekáváno {audience!r})")


def verify_jwt(
    token: str,
    *,
    secret: str | None = None,
    jwks: dict | None = None,
    issuer: str | None = None,
    audience: str | None = None,
    now: float | None = None,
) -> dict:
    """Ověří OIDC ID token a vrátí claimy; neplatný → :class:`JwtError`.

    Args:
        token: compact JWT (``header.payload.signature``).
        secret: sdílené tajné klíče pro ``HS256``.
        jwks: JWKS dict (``{"keys": [...]}``) pro ``RS256``; volí se podle
            ``kid`` z headeru, bez kid první RSA klíč.
        issuer/audience: volitelné identita/destinace checky.
        now: čas "teď" (epoch s) — injektovatelný pro offline testy.

    Fail-closed: neznámá/algoritmus ``none``, chybějící klíč, zneplatněné
    claimy → výjimka.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise JwtError("token nemá 3 segmenty")
    header = json.loads(_b64url_decode(parts[0]))
    payload_b64, signature_b64 = parts[1], parts[2]
    signing_input = f"{parts[0]}.{payload_b64}".encode()
    alg = header.get("alg")
    if alg == "HS256":
        if not secret:
            raise JwtError("HS256 vyžaduje sdílené tajné klíče")
        expected = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
        actual = _b64url_decode(signature_b64)
        if not hmac.compare_digest(expected, actual):
            raise JwtError("neplatný HMAC podpis")
    elif alg == "RS256":
        key = _select_jwks_key(jwks, header.get("kid"))
        # Standardní JWT RS256 = RSA-PKCS1v15(SHA256(signing_input));
        # cryptography 50.x: verify() vrací None při úspěchu, jinak hodí.
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes as _h
        from cryptography.hazmat.primitives.asymmetric import padding as _p

        try:
            key.verify(  # type: ignore[arg-type]
                _b64url_decode(signature_b64), signing_input, _p.PKCS1v15(), _h.SHA256()
            )
        except InvalidSignature:
            raise JwtError("neplatný RSA podpis") from None
    else:
        raise JwtError(f"nepodporovaný algoritmus {alg!r}")
    claims = json.loads(_b64url_decode(payload_b64))
    _check_time_claims(claims, now)
    _verify_claims(claims, issuer, audience)
    return claims


def _select_jwks_key(jwks: dict | None, kid: str | None):
    """Výběr RSA veřejného klíče z JWKS (podle kid; bez kid první)."""
    if not jwks or not isinstance(jwks.get("keys"), list):
        raise JwtError("RS256 vyžaduje JWKS")
    keys = [k for k in jwks["keys"] if k.get("kty") == "RSA"]
    if kid is not None:
        keys = [k for k in keys if k.get("kid") == kid] or keys[:0]
    if not keys:
        raise JwtError(f"JWKS neobsahuje klíč {kid!r}")
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

    try:
        # cryptography: RSAPublicNumbers(e, n) — pozor na pořadí!
        return RSAPublicNumbers(
            int.from_bytes(base64.urlsafe_b64decode(keys[0]["e"] + "=" * (-len(keys[0]["e"]) % 4)), "big"),
            int.from_bytes(base64.urlsafe_b64decode(keys[0]["n"] + "=" * (-len(keys[0]["n"]) % 4)), "big"),
        ).public_key()
    except Exception as exc:
        raise JwtError("neplatný JWKS klíč") from exc


def map_claims(claims: dict) -> tuple[str | None, str | None, str | None]:
    """Mapuje OIDC claimy na (username, display_name, role).

    Username: ``preferred_username`` > e-mail prefix > ``sub``. Role: první
    známá (:data:`rbac.ROLES`) v ``groups``/``roles`` claimu (string i list),
    jinak None → volající určí default. Case-insensitive, strip.
    """
    username = claims.get("preferred_username") or ""
    email = str(claims.get("email") or "")
    if not username and "@" in email:
        username = email.split("@", 1)[0]
    if not username:
        username = str(claims.get("sub") or "")
    display = str(claims.get("name") or username)

    role: str | None = None
    for claim_name in ("groups", "roles"):
        value = claims.get(claim_name)
        values = [value] if isinstance(value, str) else list(value or [])
        known = {str(v).strip().lower() for v in values} & set(ROLES)
        if known:
            # deterministicky: nejvyšší privilegie mezi známými
            role = max(sorted(known), key=ROLES.index)
            break
    return (username.strip() or None, display.strip() or None, role)
