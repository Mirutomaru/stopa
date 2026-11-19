"""P2-7 Case Exchange — CLI příkazy (exchange pack/verify).

Bundle v1 (``domain/exchange``) + anonymizace (``domain/anonymize``); snapshot
case DB je v ``data/exchange_repository``. Tady je jen CLI hrana.

Příkazy:
  stopa exchange pack <case_id> [--out FILE] [--anon] [--key-file F] [--key-out F] [--json]
      Bundle do souboru nebo stdout; --anon = anonymizované entity (mapping se
      do bundle nedostává; nový klíč vyžaduje --key-out).
  stopa exchange verify BUNDLE_FILE [--roots FILE] [--root LABEL=BASE64]... [--json]
      Ověření proti trust rootům (AK: tamperovaný podpis → exit 1).

Exit kódy: 0 = OK/ověřeno; 1 = chyba / tampering / neznámý signaři.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone


def _now_iso() -> str:
    """Aktuální čas UTC jako ISO sekundy (packed_at)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _json_mode(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "json", False)) or getattr(args, "format", None) == "json"


def cmd_exchange_pack(args: argparse.Namespace) -> int:
    """Pack případu do exchange bundle v1 (volitelná anonymizace)."""
    from stopa.cli._util import _open_db
    from stopa.data.exchange_repository import pack_case_bundle
    from stopa.domain.anonymize import AnonKey, key_fingerprint, new_key

    anon_key: AnonKey | None = None
    generated = False
    key_file = getattr(args, "key_file", None)
    key_out = getattr(args, "key_out", None)
    if getattr(args, "anon", False):
        if key_file:
            try:
                with open(key_file, encoding="utf-8") as f:
                    raw = f.read().strip()
                if not raw:
                    raise ValueError("soubor klíče je prázdný")
            except OSError as exc:
                raise SystemExit(f"Čtení klíčového souboru {key_file!r} selhalo: {exc}") from None
            anon_key = AnonKey(secret_b64=raw)  # validace (fail-closed) proběhne v anonymize()
        else:
            if not key_out:
                raise SystemExit("--anon bez --key-file vyžaduje --key-out (kde uložit nový klíč)")
            anon_key = new_key()
            generated = True

    db = _open_db(args.case_id)
    try:
        bundle, anon_result = pack_case_bundle(
            db.conn, args.case_id, packed_at=_now_iso(), anon_key=anon_key
        )
    except (ValueError, TypeError) as exc:
        raise SystemExit(str(exc)) from None
    finally:
        db.close()

    out_path = getattr(args, "out", None)
    if generated and anon_key is not None and key_out:
        with open(key_out, "w", encoding="utf-8") as f:
            f.write(anon_key.secret_b64 + "\n")

    payload = dict(bundle)
    fingerprint: str | None = None
    if anon_result is not None and anon_key is not None:
        fingerprint = key_fingerprint(anon_key)
        payload["key_fingerprint"] = fingerprint

    c = bundle["counts"]
    summary = (
        f"Bundle {args.case_id}: files={c['files']} artifacts={c['artifacts']} "
        f"entities={c['entities']}" + (" [anon]" if fingerprint else "")
    )
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"{summary} → {out_path}")
        if fingerprint:
            print(f"Otisk klíče anonymizace: {fingerprint}")
    elif _json_mode(args):
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(summary)
        if fingerprint:
            print(f"Otisk klíče anonymizace: {fingerprint}")
    return 0


def cmd_exchange_verify(args: argparse.Namespace) -> int:
    """Ověření bundle v1 proti trust rootům (fail-closed; tamper → exit 1)."""
    from stopa.domain.exchange import verify_bundle

    try:
        with open(args.bundle_file, encoding="utf-8") as f:
            bundle = json.load(f)
    except OSError as exc:
        raise SystemExit(f"Čtení bundle {args.bundle_file!r} selhalo: {exc}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Bundle není platné JSON: {exc}") from None

    roots: dict[str, str] = {}
    roots_file = getattr(args, "roots", None)
    if roots_file:
        try:
            with open(roots_file, encoding="utf-8") as f:
                loaded = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Čtení trust rootů {roots_file!r} selhalo: {exc}") from None
        if not isinstance(loaded, dict):
            raise SystemExit("Soubor trust rootů musí být JSON objekt {label: public_b64}")
        roots.update({str(k): str(v) for k, v in loaded.items()})
    for spec in (getattr(args, "root", None) or []):
        label, sep, pub = spec.partition("=")
        if not sep or not label.strip() or not pub.strip():
            raise SystemExit(f"--root musí být LABEL=BASE64 (zadáno {spec!r})")
        roots[label.strip()] = pub.strip()

    result = verify_bundle(bundle, roots)  # ValueError jen non-Mapping → fail-closed níže
    if _json_mode(args):
        print(json.dumps({"ok": result.ok, "reasons": list(result.reasons)}, ensure_ascii=False))
    else:
        if result.ok:
            print("Bundle ověřeno (formát v1 + podpis platný).")
        else:
            print(f"Bundle NEověřeno: {', '.join(result.reasons)}")
    return 0 if result.ok else 1
