"""P2-7 Case Exchange — Web marketplace sekce (pack/verify bundle v1).

Routy:
  POST /api/exchange/pack   {case_id, anon?, key_b64?, tlp?} → {bundle, key_fingerprint?, key_b64?}
      --anon bez key_b64 → vygeneruje se nový klíč a vrátí se v base64 (UI ho musí
      uložit — s ním je mapping re-anonymizovatelný) + fingerprint.
      tlp (P3-6) = distribuční úroveň bundle; neplatná → 400.
  POST /api/exchange/verify {bundle: {...}, roots?: {label: pub_b64}} → {ok, reasons, warnings}
      warnings (P3-6) = TLP porušení per entity (nemění ok).

Logika žije v ``domain/exchange`` (+ ``data/exchange_repository``); tady jen API hrana.
Konvence: 404 = neznámý případ (z ``ctx["open_db"]``); 400 = semantická chyba domény.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field


class PackIn(BaseModel):
    case_id: str
    anon: bool = False
    key_b64: str | None = Field(None, description="klíč anonymizace (base64); bez něj → nový klíč")
    tlp: str | None = Field(
        None, description="P3-6 — TLP distribuční úroveň bundle (CLEAR/GREEN/AMBER/RED/WHITE)"
    )


class VerifyIn(BaseModel):
    bundle: dict[str, Any]
    roots: dict[str, str] | None = None


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def register(app, ctx) -> None:
    """Přidá P2-7 exchange routy do aplikace (volá se z ``create_app``)."""
    open_db = ctx["open_db"]

    @app.post("/api/exchange/pack")
    def exchange_pack(body: PackIn):
        from stopa.data.exchange_repository import pack_case_bundle
        from stopa.domain.anonymize import AnonKey, key_fingerprint, new_key

        anon_key = None
        generated = False
        if body.anon:
            if body.key_b64 is not None:
                anon_key = AnonKey(secret_b64=body.key_b64.strip())
            else:
                anon_key = new_key()
                generated = True

        db = open_db(body.case_id)  # neznámý případ → 404 (konvence ctx)
        try:
            bundle, anon_result = pack_case_bundle(
                db.conn, body.case_id, packed_at=_now_iso(),
                anon_key=anon_key, tlp=body.tlp,
            )
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            db.close()

        out: dict[str, Any] = {"bundle": bundle}
        if anon_result is not None and anon_key is not None:
            out["key_fingerprint"] = key_fingerprint(anon_key)
            if generated:
                out["key_b64"] = anon_key.secret_b64  # nový klíč → UI ho uloží
        return out

    @app.post("/api/exchange/verify")
    def exchange_verify(body: VerifyIn):
        from stopa.domain.exchange import verify_bundle

        try:
            result = verify_bundle(body.bundle, body.roots or {})
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc  # defenzivní — pydantic zajistí Mapping
        return {
            "ok": result.ok,
            "reasons": list(result.reasons),
            "warnings": list(result.warnings),  # P3-6 — TLP porušení (nemění ok)
        }
