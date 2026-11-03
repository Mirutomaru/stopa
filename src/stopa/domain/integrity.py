"""STOPA — Evidence Integrity 2.0 (P0 Core, C4).

Tři vrstvy integrity důkazů:

1. **Hash chaining audit logu** — každý řádek nese ``prev_hash`` a vlastní
   ``hash = SHA-256(prev_hash || ts || action || actor || details_json)``.
   První řádek odkazuje na GENESIS (0×64). Jakákoli změna starého řádku
   rozbití řetězec → ověřitelné bez soukromého klíče.

2. **Ed25519 kontrolní body** — klíčový pár generovaný při vytvoření případu
   (soukromý v case DB, veřejný do reportu). Kontrolní bod = podpis hashu
   posledního audit řádku; ukládá se po operacích měnících důkazy + na požádání.

3. **Export manifesty** — soubory exportu + jejich SHA-256 + zdroj; manifest má
   vlastní deterministický hash (stejný vstup + verze STOPA = stejný hash) a je
   podepsán Ed25519.

Čistá logika bez I/O; Ed25519 přes lazy import ``cryptography`` (volitelná
závislost — graceful degradation, viz FDE). Hash chaining je čistý hashlib.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

# GENESIS — prev_hash prvního audit řádku (0×64). STP-022: per-algorithm genesis.
GENESIS = "0" * 64  # SHA-256 (backward compat — původní výchozí)
_GENESIS_BY_ALGO = {"sha256": GENESIS, "sha512": "0" * 128}


def _genesis(algo: str) -> str:
    """Genesis prev_hash pro daný algoritmus (SHA-256 → 0×64, SHA-512 → 0×128)."""
    try:
        return _GENESIS_BY_ALGO[algo]
    except KeyError:
        raise ValueError(f"Neznámý hash algoritmus '{algo}' (dostupné: {', '.join(sorted(_GENESIS_BY_ALGO))})") from None


def compute_audit_hash(
    prev_hash: str, ts: str, action: str, actor: str | None, details_json: str, *, algo: str = "sha256"
) -> str:
    """Hash řetězce audit řádku — deterministický (kanonické pořadí polí).

    STP-022: ``algo`` — "sha256" (výchozí, backward compat) nebo "sha512".
    Neznámý algoritmus → :class:`ValueError` (fail fast přes ``_genesis``).
    """
    _genesis(algo)  # validace algoritmu (neznámý → ValueError)
    payload = "\x1f".join(
        [prev_hash, ts, action, actor or "", details_json]
    )
    return hashlib.new(algo, payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChainRow:
    """Jeden řádek audit logu pro ověření řetězce (bez I/O)."""

    id: int
    ts: str
    action: str
    actor: str | None
    details_json: str
    prev_hash: str
    hash: str


@dataclass(frozen=True)
class ChainReport:
    """Výsledek ověření hash řetězce audit logu."""

    ok: bool
    rows_checked: int
    broken_at_id: int | None = None  # ID prvního rozbitého řádku (None = v pořádku)
    reason: str | None = None


def verify_chain(rows: list[ChainRow], *, algo: str = "sha256") -> ChainReport:
    """Přepočítá celý hash řetězec a ověří propojení.

    Řádky musí být seřazené vzestupně podle ``id`` (chronologicky). Ověření:
    - první ``prev_hash`` == GENESIS pro daný algoritmus
    - každý ``hash`` == přepočtený hash z polí řádku
    - každý následující ``prev_hash`` == předchozí ``hash``

    STP-022: ``algo`` — "sha256" (výchozí, backward compat) nebo "sha512".
    Vrací :class:`ChainReport` s ID prvního rozbitého řádku (pro report).
    """
    genesis = _genesis(algo)  # fail fast na neznámý algoritmus
    if not rows:
        return ChainReport(ok=True, rows_checked=0)

    prev = genesis
    for row in rows:
        expected = compute_audit_hash(row.prev_hash, row.ts, row.action, row.actor, row.details_json, algo=algo)
        if row.hash != expected:
            return ChainReport(
                ok=False,
                rows_checked=row.id,
                broken_at_id=row.id,
                reason=f"hash řádku {row.id} neodpovídá přepočtu",
            )
        if row.prev_hash != prev:
            return ChainReport(
                ok=False,
                rows_checked=row.id,
                broken_at_id=row.id,
                reason=f"prev_hash řádku {row.id} nesejde s hash předchozího řádku",
            )
        prev = row.hash

    first = rows[0]
    if first.prev_hash != genesis:
        return ChainReport(
            ok=False,
            rows_checked=first.id,
            broken_at_id=first.id,
            reason="první řádek neodkazuje na GENESIS",
        )
    return ChainReport(ok=True, rows_checked=len(rows))


# ── Ed25519 kontrolní body (lazy cryptography) ─────────────────────────────

def _ed25519():
    """Lazy import Ed25519 — volitelná závislost ``cryptography``."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # type: ignore[import-untyped]
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )

        return Ed25519PrivateKey, Ed25519PublicKey
    except ImportError as e:  # pragma: no cover — závisí na instalaci extras
        raise RuntimeError(
            "Ed25519 vyžaduje balík 'cryptography' (pip install cryptography)"
        ) from e


def generate_keypair() -> tuple[str, str]:
    """Vygeneruje Ed25519 klíčový pár. Vrací ``(private_b64, public_b64)``."""
    priv_cls, _ = _ed25519()
    private = priv_cls.generate()
    pub = private.public_key()
    from cryptography.hazmat.primitives import serialization  # type: ignore[import-untyped]

    priv_b64 = base64.b64encode(
        private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode("ascii")
    pub_b64 = base64.b64encode(
        pub.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    return priv_b64, pub_b64


def sign_hash(private_b64: str, digest: str) -> str:
    """Podpis SHA-256 hex řetězce soukromým klíčem. Vrací base64 podpisu."""
    priv_cls, _ = _ed25519()

    key = priv_cls.from_private_bytes(base64.b64decode(private_b64))
    sig = key.sign(bytes.fromhex(digest))
    return base64.b64encode(sig).decode("ascii")


def verify_signature(public_b64: str, digest: str, signature_b64: str) -> bool:
    """Ověří podpis veřejným klíčem (nezávislá kontrola bez soukromého klíče)."""
    _, pub_cls = _ed25519()

    key = pub_cls.from_public_bytes(base64.b64decode(public_b64))
    try:
        key.verify(base64.b64decode(signature_b64), bytes.fromhex(digest))
        return True
    except Exception:  # noqa: BLE001 — InvalidSignature a podobné → neplatný podpis
        return False


# ── Export manifesty (deterministický hash + podpis) ───────────────────────

@dataclass(frozen=True)
class ManifestEntry:
    """Jeden soubor v exportním manifestu."""

    name: str  # název / rel. cesta souboru
    sha256: str  # SHA-256 obsahu
    size: int = 0
    sha512: str | None = None  # STP-022 — volitelný SHA-512 (integrity vrstva)


@dataclass(frozen=True)
class ExportManifest:
    """Exportní manifest — soubory + hashy + zdroj; deterministický hash."""

    case_id: str
    tool_version: str
    entries: tuple[ManifestEntry, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


def build_manifest(
    case_id: str,
    tool_version: str,
    files: list[tuple[str, bytes]],
    extra: dict[str, Any] | None = None,
    *,
    include_sha512: bool = False,  # STP-022 — SHA-512 v manifestu (opt-in)
) -> ExportManifest:
    """Sestaví manifest z exportních souborů (název + obsah → SHA-256).

    STP-022: ``include_sha512=True`` doplní i SHA-512 (deterministický hash
    manifestu se změní — volitelné rozšíření integrity vrstvy).
    """
    entries = tuple(
        ManifestEntry(
            name=name,
            sha256=hashlib.sha256(content).hexdigest(),
            size=len(content),
            sha512=hashlib.sha512(content).hexdigest() if include_sha512 else None,
        )
        for name, content in sorted(files)
    )
    return ExportManifest(case_id=case_id, tool_version=tool_version, entries=entries, extra=extra or {})


def manifest_hash(manifest: ExportManifest) -> str:
    """Deterministický SHA-256 manifestu — kanonické JSON (seřazené klíče).

    Stejný vstup + verze STOPA = stejný hash (reprodukovatelnost exportu).
    STP-022: SHA-512 entry se do kanonického payloadu počítá jen když je
    přítomné (backward compat — staré manifesty bez sha512 mají stejný hash).
    """
    canonical = {
        "case_id": manifest.case_id,
        "tool_version": manifest.tool_version,
        "entries": [
            {"name": e.name, "sha256": e.sha256, "size": e.size} | ({"sha512": e.sha512} if e.sha512 else {})
            for e in manifest.entries
        ],
        "extra": manifest.extra,
    }
    payload = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sign_manifest(manifest: ExportManifest, private_b64: str) -> str:
    """Podpis manifestu Ed25519 (base64)."""
    return sign_hash(private_b64, manifest_hash(manifest))
