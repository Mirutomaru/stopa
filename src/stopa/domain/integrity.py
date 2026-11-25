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
import os as _os
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
    kind: str | None = None          # B9 — typ prvního defektu (CHAIN_*)
    defects: tuple[ChainDefect, ...] = ()  # B9 — všechny defekty (collect_all)


# B9 — strojově čitelné typy defektů (diagnostika/kompenzace bez parsingu textu).
CHAIN_HASH_MISMATCH = "hash_mismatch"        # uložený hash != přepočet z obsahu
CHAIN_LINK_BROKEN = "link_broken"            # prev_hash != hash předchozího řádku
CHAIN_ROW_MISSING = "row_missing"            # mezera v ID (řádek byl smazán)
CHAIN_GENESIS_MISMATCH = "genesis_mismatch"  # první řádek neodkazuje na GENESIS


@dataclass(frozen=True)
class ChainDefect:
    """B9 — jeden defekt řetězce s přesnou lokalizací (řádek + typ + zpráva)."""

    row_id: int | None  # None = mezera viz message; jinak ID postiženého řádku
    kind: str           # CHAIN_* konstanta
    message: str


def verify_chain(
    rows: list[ChainRow], *, algo: str = "sha256", collect_all: bool = False
) -> ChainReport:
    """Přepočítá celý hash řetězec a ověří propojení.

    Řádky musí být seřazené vzestupně podle ``id`` (chronologicky). Ověření:
    - první ``prev_hash`` == GENESIS pro daný algoritmus
    - každý ``hash`` == přepočtený hash z polí řádku
    - každý následující ``prev_hash`` == předchozí ``hash``

    STP-022: ``algo`` — "sha256" (výchozí, backward compat) nebo "sha512".
    Vrací :class:`ChainReport` s ID prvního rozbitého řádku (pro report).

    B9 — ``collect_all=False`` (BC): vrací na prvním defektu, ``defects`` nese
    jen tento jeden záznam a ``kind`` jeho typ. ``collect_all=True``: proskenuje
    celý řetězec a shrne **všechny** defekty do ``report.defects`` — po hash
    mismatch se očekávání linky pokračuje od *uloženého* hashu (každý tamperovaný
    řádek se lokalizuje zvlášť, bez kaskády) a navíc detekuje mezery v ID
    (``CHAIN_ROW_MISSING`` — smazaný řádek ≠ tampering). U prvního řádku dostává
    genesis rozbití vlastní kind ``CHAIN_GENESIS_MISMATCH`` s jasnou zprávou.
    """
    genesis = _genesis(algo)  # fail fast na neznámý algoritmus
    if not rows:
        return ChainReport(ok=True, rows_checked=0)

    defects: list[ChainDefect] = []
    prev_id: int | None = None
    prev = genesis

    for row in rows:
        expected = compute_audit_hash(
            row.prev_hash, row.ts, row.action, row.actor, row.details_json, algo=algo
        )
        if row.hash != expected:
            d = ChainDefect(row_id=row.id, kind=CHAIN_HASH_MISMATCH,
                            message=f"hash řádku {row.id} neodpovídá přepočtu")
            defects.append(d)
            if not collect_all:
                return ChainReport(ok=False, rows_checked=row.id, broken_at_id=row.id,
                                   reason=d.message, kind=d.kind, defects=tuple(defects))
        if row.prev_hash != prev:
            if prev_id is None:  # první řádek — genesis, ne „předchozí řádek“
                d = ChainDefect(row_id=row.id, kind=CHAIN_GENESIS_MISMATCH,
                                message=f"první řádek {row.id} neodkazuje na GENESIS")
            else:
                d = ChainDefect(row_id=row.id, kind=CHAIN_LINK_BROKEN,
                                message=f"prev_hash řádku {row.id} nesejde s hash předchozího řádku")
            defects.append(d)
            if not collect_all:
                return ChainReport(ok=False, rows_checked=row.id, broken_at_id=row.id,
                                   reason=d.message, kind=d.kind, defects=tuple(defects))
        # B9 — mezera v ID (smazaný řádek): linka je přerušena i přes prev_hash,
        # ale příčina = chybějící záznam. V BC režimu ji maskuje LINK_BROKEN výše;
        # collect_all hlásí obě skutečnosti.
        if prev_id is not None and row.id != prev_id + 1:
            d = ChainDefect(row_id=row.id, kind=CHAIN_ROW_MISSING,
                            message=f"po řádku {prev_id} chybí řádek(y) do id {row.id - 1}")
            defects.append(d)
            if not collect_all:
                return ChainReport(ok=False, rows_checked=row.id, broken_at_id=row.id,
                                   reason=d.message, kind=d.kind, defects=tuple(defects))
        prev_id = row.id
        # Očekávání pro další iteraci = uložený hash (ne přepočet) → jeden
        # tamperovaný řádek nevyvolává kaskádové link defekty v collect_all.
        prev = row.hash

    if defects:  # B9 — collect_all proscenul celý řetězec; první defekt určuje BC pole
        first = defects[0]
        return ChainReport(ok=False, rows_checked=len(rows), broken_at_id=first.row_id,
                           reason=first.message, kind=first.kind, defects=tuple(defects))
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


# ── P0-2: obalování soukromého klíče (AES-GCM pod master secret) ───────────────

_WRAPPED_FORMAT_VERSION = 1


def wrap_private_key(private_b64: str, master_secret: bytes) -> str:
    """P0-2: AES-GCM obal soukromého klíče master secretem.

    Vrací JSON ``{"v":1,"nonce":b64,"ct":b64}``. Master secret musí mít 32 B
    (AES-256); jinak ValueError. Vyžaduje balík ``cryptography``.
    """
    if len(master_secret) != 32:
        raise ValueError(f"master secret musí mít 32 bajtů, má {len(master_secret)}")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore[import-untyped]

    nonce = _os.urandom(12)
    ct = AESGCM(master_secret).encrypt(nonce, base64.b64decode(private_b64), None)
    return json.dumps(
        {
            "v": _WRAPPED_FORMAT_VERSION,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ct": base64.b64encode(ct).decode("ascii"),
        },
        sort_keys=True,
    )


def unwrap_private_key(stored: str, master_secret: bytes | None = None) -> str:
    """P0-2: dekoduje uložený soukromý klíč (obalený JSON nebo legacy plaintext).

    Legacy (ne-JSON base64) → vrací se bez změny, ``master_secret`` se nepoužije
    (backward compat s DB před P0-2). Obalený formát vyžaduje 32B secret;
    chybějící secret / poškozený obal → ValueError. Typový nesoulad struktury
    → TypeError.
    """
    # Base64 abeceda neobsahuje "{" ani "[" → oba znaky znamenají JSON obal.
    if stored[0] not in "{[":
        return stored  # legacy plaintext b64
    try:
        obj = json.loads(stored)
    except json.JSONDecodeError as e:
        raise ValueError("obalený klíč: poškozené JSON") from e
    if not isinstance(obj, dict):
        raise TypeError(f"obalený klíč: očekáván objekt, dostal {type(obj).__name__}")
    if obj.get("v") != _WRAPPED_FORMAT_VERSION:
        raise ValueError(f"neznámá verze obalu: {obj.get('v')!r}")
    if master_secret is None:
        raise ValueError(
            "klíč je obalený, ale chybí STOPA_INTEGRITY_MASTER_KEY (32 B base64)"
        )
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore[import-untyped]

        nonce = base64.b64decode(obj["nonce"])
        ct = base64.b64decode(obj["ct"])
    except (KeyError, TypeError) as e:
        raise ValueError(f"obalený klíč: chybí pole ({e})") from e
    try:
        raw = AESGCM(master_secret).decrypt(nonce, ct, None)
    except Exception as e:  # InvalidTag apod. → špatný secret/ct
        raise ValueError("obalený klíč: dešifrování selhalo (špatný master secret?)") from e
    return base64.b64encode(raw).decode("ascii")


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
