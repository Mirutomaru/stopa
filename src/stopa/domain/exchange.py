"""P2-7 — Case Exchange bundle v1 (čistá doména).

Formát ``stopa-exchange/v1`` = deterministické JSON s obsahem:

- ``case_id``, ``title``, ``packed_at`` (ISO UTC, součást podepsaného obsahu),
- ``counts`` — počty {files, artifacts, entities} (deterministický snapshot),
- ``entities`` — seřazené + deduplikované záznamy ``{kind, value}``; hodnota je
  buď kanonická entita, nebo pseudonym z :mod:`stopa.domain.anonymize`
  (anonymizaci volající provede předem — mapping klíče se do bundle nedostává),
- ``provenance`` — volitelný souhrn P0-1 řetězců (agregované statistiky),
- ``signature`` — volitelný Ed25519 podpis nad digistem bundle bez tohoto klíče.

Podpisovaný obsah = kanonické JSON (sort_keys, pevné separátory) všech klíčů
kromě ``signature``; deterministický cross-platform. Ověřování je fail-closed:
deformovaný vstup vrací :class:`VerifyResult` s důvody místo výjimky
(výjimka jen u nesprávného typu bundle — ne-Mapping).

Sémantika důvěry (AK P2-7):
- bez podpisu = validní formát (podpis je volitelný),
- se podpisem a prázdnými ``trust_roots`` → ``no_trust_roots``,
- label podepsatele není v kořenech → ``untrusted_signature``,
- podpis neodpovídá digestu u kořene → ``signature_mismatch``.

Bez I/O a bez sítě — offline testovatelnost (AK P2-7).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from stopa.domain.integrity import sign_hash, verify_signature

#: Verze formátu — změna struktury = nová verze.
FORMAT_V1 = "stopa-exchange/v1"

#: Povinné klíče sekce ``counts`` (přísnost formátu v1).
COUNT_KEYS: tuple[str, ...] = ("files", "artifacts", "entities")


@dataclass(frozen=True)
class VerifyResult:
    """Výsledek ověření bundle — ``ok=False`` + neduplikované důvody."""

    ok: bool
    reasons: tuple[str, ...] = ()  # prázdné = ověřeno


def _canonical_payload(bundle: Mapping[str, Any]) -> str:
    """Kanonické JSON podepsaného obsahu (bez klíče ``signature``)."""
    payload = {k: v for k, v in bundle.items() if k != "signature"}
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def bundle_digest(bundle: Mapping[str, Any]) -> str:
    """SHA-256 hex digestu podepsaného obsahu (deterministický)."""
    if not isinstance(bundle, Mapping):
        raise TypeError("bundle musí být mapping")
    return hashlib.sha256(_canonical_payload(bundle).encode("utf-8")).hexdigest()


def _normalize_entities(entities: Any) -> list[tuple[str, str]]:
    """Validace + kanonizace vstupních entit (fail-closed).

    Akceptuje sekvenci dvojic ``(kind, value)`` nebo mappingů ``{kind, value}``.
    Prázdné kind/value po stripu → ``ValueError``; špatný typ → ``TypeError``.
    """
    if isinstance(entities, Mapping):
        raise TypeError("entities musí být sekvence, ne mapping")
    try:
        items = list(entities)
    except TypeError as exc:  # fail-closed
        raise TypeError(f"entities musí být sekvence, dostal {type(entities).__name__}") from exc

    out: list[tuple[str, str]] = []
    for item in items:
        if isinstance(item, Mapping):
            kind = item.get("kind")
            value = item.get("value")
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            kind, value = item
        else:
            raise TypeError(f"entita musí být dvojice nebo {{kind,value}}, dostal {item!r}")
        if not isinstance(kind, str) or not isinstance(value, str):
            raise TypeError("entity kind/value musí být řetězce")
        kind_s = kind.strip()
        value_s = value.strip()
        if not kind_s:
            raise ValueError("prázdný entity kind")
        if not value_s:
            raise ValueError(f"prázdná hodnota pro entity {kind_s!r}")
        out.append((kind_s, value_s))
    return out


def build_bundle(
    *,
    case_id: str,
    packed_at: str,
    counts: Mapping[str, Any],
    entities: Sequence[Any] = (),
    title: str | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Sestaví bundle v1 (deterministický).

    - ``counts`` musí mít přesně klíče :data:`COUNT_KEYS` s nezápornými inty.
    - Entity se deduplikují a seřadí podle ``(kind, value)``; hodnoty jsou
      už ve finálním tvaru (kanonické nebo pseudonym — viz anonymize).
    - ``provenance`` = libovolné JSON-serializovatelné mapping (souhrn P0-1).

    Chybová sémantika: semantická chyba → ``ValueError``, typová → ``TypeError``.
    """
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("case_id musí být neprázdný řetězec")
    if not isinstance(packed_at, str) or not packed_at:
        raise ValueError("packed_at musí být neprázdný ISO řetězec")

    count_dict: dict[str, int] = {}
    if not isinstance(counts, Mapping) or set(counts.keys()) != set(COUNT_KEYS):
        raise ValueError("counts musí mít přesně klíče files/artifacts/entities")
    for key in COUNT_KEYS:
        val = counts.get(key)
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            raise ValueError(f"counts[{key!r}] musí být nezáporné celé číslo")
        count_dict[key] = val

    pairs = _normalize_entities(entities)
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for kind_s, value_s in sorted(set(pairs)):
        if (kind_s, value_s) not in seen:
            seen.add((kind_s, value_s))
            unique.append({"kind": kind_s, "value": value_s})

    bundle: dict[str, Any] = {
        "format": FORMAT_V1,
        "case_id": case_id.strip(),
        "title": title.strip() if isinstance(title, str) and title.strip() else None,
        "packed_at": packed_at,
        "counts": count_dict,
        "entities": unique,
    }
    if provenance is not None:
        if not isinstance(provenance, Mapping):
            raise TypeError("provenance musí být mapping")
        bundle["provenance"] = {str(k): v for k, v in provenance.items()}
    return bundle


def sign_bundle(
    bundle: Mapping[str, Any], private_b64: str, issuer: str = "stopa-marketplace"
) -> dict[str, Any]:
    """Vrátí kopii bundle s blokem ``signature`` (Ed25519 nad digistem).

    Deformovaný soukromý klíč → výjimka z :func:`integrity.sign_hash`
    (volající = signující strana, může selhat explicitně).
    """
    if not isinstance(issuer, str) or not issuer.strip():
        raise ValueError("issuer musí být neprázdný řetězec")
    out = dict(bundle)
    sig_b64 = sign_hash(private_b64, bundle_digest(bundle))
    out["signature"] = {"issuer": issuer.strip(), "sig_b64": sig_b64}
    return out


def _normalize_roots(roots: Mapping[str, str] | Sequence[tuple[str, str]]) -> dict[str, str]:
    """Normalizace trust roots na mapping label→public key b64 (deterministický)."""
    if isinstance(roots, Mapping):
        return {str(k): str(v) for k, v in roots.items() if isinstance(v, str) and v}
    out: dict[str, str] = {}
    for item in roots:
        try:
            label, pub = item  # type: ignore[misc]
        except (TypeError, ValueError):
            continue
        if isinstance(label, str) and isinstance(pub, str) and pub:
            out[label] = pub
    return out


def verify_bundle(
    bundle: Any,
    trust_roots: Mapping[str, str] | Sequence[tuple[str, str]] = (),
) -> VerifyResult:
    """Fail-closed ověření bundle v1; důvody jsou stabilní kódy.

    Důvody (neexhaustivní): ``missing_format``/``unknown_format``,
    ``missing_case_id``, ``bad_packed_at``, ``bad_counts``, ``bad_entities``,
    ``bad_entity``, ``duplicate_entity``, ``bad_provenance``,
    ``bad_signature_block``, ``no_trust_roots``, ``untrusted_signature``,
    ``signature_mismatch``.

    ``trust_roots`` = mapping label→public key b64 (nebo sekvence dvojic).
    """
    if not isinstance(bundle, Mapping):
        return VerifyResult(False, ("not_mapping",))

    reasons: list[str] = []

    fmt = bundle.get("format")
    if fmt != FORMAT_V1:
        reasons.append("unknown_format" if fmt is not None else "missing_format")

    case_id = bundle.get("case_id")
    if not isinstance(case_id, str) or not case_id.strip():
        reasons.append("missing_case_id")

    packed_at = bundle.get("packed_at")
    if not isinstance(packed_at, str) or not packed_at:
        reasons.append("bad_packed_at")

    counts = bundle.get("counts")
    if (
        not isinstance(counts, Mapping)
        or set(counts.keys()) != set(COUNT_KEYS)
        or any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in counts.values())
    ):
        reasons.append("bad_counts")

    entities = bundle.get("entities")
    if not isinstance(entities, list):
        reasons.append("bad_entities")
    else:
        seen_pairs: set[tuple[str, str]] = set()
        for ent in entities:
            if (
                not isinstance(ent, Mapping)
                or not isinstance(ent.get("kind"), str)
                or not ent.get("kind", "").strip()
                or not isinstance(ent.get("value"), str)
                or not ent.get("value", "").strip()
            ):
                reasons.append("bad_entity")
                break
            pair = (str(ent["kind"]).strip(), str(ent["value"]).strip())
            if pair in seen_pairs:
                reasons.append("duplicate_entity")
                break
            seen_pairs.add(pair)

    if "provenance" in bundle and not isinstance(bundle.get("provenance"), Mapping):
        reasons.append("bad_provenance")

    sig = bundle.get("signature")
    if sig is not None:
        issuer = str(sig.get("issuer", "")).strip() if isinstance(sig, Mapping) else ""
        sig_b64 = sig.get("sig_b64") if isinstance(sig, Mapping) else None
        if not issuer or not isinstance(sig_b64, str) or not sig_b64:
            reasons.append("bad_signature_block")
        else:
            roots_map = _normalize_roots(trust_roots)
            root = roots_map.get(issuer)
            if root is None:
                # fail-closed: podpis bez dostupného kořene (prázdné roots nebo
                # neznámý label) se nedá ověřit → rozlišené důvody.
                reasons.append("no_trust_roots" if not roots_map else "untrusted_signature")
            else:
                try:
                    valid = verify_signature(root, bundle_digest(bundle), sig_b64)
                except (ValueError, TypeError):
                    # deformovaný kořenový klíč → neověřitelný podpis
                    valid = False
                if not valid:
                    reasons.append("signature_mismatch")

    return VerifyResult(not reasons, tuple(reasons))
