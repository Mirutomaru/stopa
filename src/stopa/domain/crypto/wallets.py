"""STOPA — K2.2/K2.3 wallet parsery (Electrum, MetaMask) — čistá doménová vrstva bez I/O.

Formáty (defenzivní parsování — skutečné soubory se liší verzí klientu):

- **Electrum** (``default_wallet`` atd.) — JSON:
  - moderní (3.x/4.x): ``keystore`` dict (type, xprv/xpub, derivation_path),
    top-level ``addresses``, volitelně ``labels``, ``use_encryption``,
    ``seed_version``;
  - legacy (≤2.x): top-level ``seed`` (mnemonika jako string) + ``keys``/``addresses``.

- **MetaMask** — vault JSON: ``{"dat": b64, "id": uuid, "dkty"/"kdfparams": …,
  "salt": b64, "v": 1}``. Šifrování AES-128-CTR (IV = první 16 B ``dat``), KDF buď
  scrypt nebo pbkdf2-sha256. Po dešifrování: JSON seznam hex privátních klíčů
  (default keyring) nebo objekt s polem ``keyrings``.

PII guard (spec §7): seed slova a privátní klíče jsou citlivý materiál — do artefaktů
chová jejich fingerprint (SHA-256), ne raw hodnotu; adresy/labely = veřejná data.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field

from stopa.domain.crypto._keccak import keccak256
from stopa.domain.crypto.bdb import BdbError, parse_bdb_btree  # noqa: F401

# ── modely ───────────────────────────────────────────────────────────────


def _fp(content: bytes | str) -> str:
    """SHA-256 fingerprint citlivého materiálu (64hex)."""

    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


class ElectrumWallet(BaseModel):
    """Vyextrahované metadata z Electrum wallet souboru (bez raw klíčů)."""

    format_version: str  # "modern" | "legacy" | "unknown"
    keystore_type: str | None = None  # bip32, bip44, hardware…
    derivation_path: str | None = None
    encrypted: bool = False
    addresses: list[str] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)  # adresa → label
    seed_words_count: int | None = None
    seed_fingerprint: str | None = None  # SHA-256 normalizované mnemoniky
    xprv_fingerprint: str | None = None  # SHA-256 xprv (raw nehraje do DB)
    xpubs: list[str] = Field(default_factory=list)  # veřejný materiál
    seed_version_hint: str | None = None
    warnings: list[str] = Field(default_factory=list)


class MetaMaskAccount(BaseModel):
    """Jeden účet v MetaMask vaultu — adresa + fingerprint privátního klíče."""

    address: str  # EIP-55 checksummed (odvozeno z klíče)
    private_key_fingerprint: str = ""  # SHA-256 hex klíče


class MetaMaskVaultData(BaseModel):
    """Metadata dešifrovaného / nadešifrovaného MetaMask vaultu."""

    kdf: str | None = None  # "scrypt" | "pbkdf2-sha256"
    decrypted: bool = False
    accounts: list[MetaMaskAccount] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class UnsupportedKDFError(ValueError):
    """Neznámý KDF v MetaMask vaultu."""


# ── Electrum ─────────────────────────────────────────────────────────────


def is_electrum_wallet(obj: Any) -> bool:
    """Heuristika: je JSON objekt Electrum wallet souborem?"""

    if not isinstance(obj, dict):
        return False
    ks = obj.get("keystore")
    has_modern_ks = (
        isinstance(ks, dict) and any(k in ks for k in ("xprv", "xpub", "derivation_path", "type"))
    )
    legacy_markers = ("seed" in obj or "keys" in obj) and "addresses" in obj
    return has_modern_ks or (legacy_markers and isinstance(obj.get("addresses"), dict))


def parse_electrum_wallet(raw: str | bytes | dict[str, Any]) -> ElectrumWallet | None:
    """Parsování JSON Electrum walletu → metadata; ne-wallet → ``None``.

    Defenzivní: chybějící pole = ``None``/prázdné, verze klienta se liší.
    Akceptuje i už-parsedý dict (pipeline unifikovaně dekoduje JSON).
    """

    try:
        obj = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not is_electrum_wallet(obj):
        return None

    w = ElectrumWallet(format_version="unknown")
    ks: dict[str, Any] | None = obj.get("keystore") if isinstance(obj.get("keystore"), dict) else None

    # ── adresy (top-level "addresses" — klíče dictu) ──
    addresses_raw = obj.get("addresses")
    if isinstance(addresses_raw, dict):
        for addr in addresses_raw:
            if isinstance(addr, str) and addr.strip():
                w.addresses.append(addr.strip())

    # ── labely: moderní top-level "labels" + legacy hodnoty v "addresses" ──
    labels = obj.get("labels")
    if isinstance(labels, dict):
        for k, v in labels.items():
            if isinstance(k, str) and isinstance(v, (str, int)):
                w.labels[k] = str(v)
    if isinstance(addresses_raw, dict):  # legacy: hodnota je label string
        for addr, val in addresses_raw.items():
            if isinstance(val, str) and val.strip() and addr not in w.labels:
                w.labels[addr] = val

    # ── keystore (moderní formát) ──
    if ks is not None:
        w.format_version = "modern"
        w.keystore_type = ks.get("type") if isinstance(ks.get("type"), str) else None
        dp = ks.get("derivation_path")
        w.derivation_path = dp if isinstance(dp, str) else None
        xprv = ks.get("xprv")
        if isinstance(xprv, str) and xprv:
            w.xprv_fingerprint = _fp(xprv)
        elif w.keystore_type in ("bip32", "bip44", None, "hardware"):
            # xprv chybí/null → buď šifrováný wallet, buď hardware keystore
            if obj.get("use_encryption"):
                w.encrypted = True
            elif w.keystore_type == "hardware":
                w.warnings.append("keystore=hardware — klíčový materiál mimo soubor")
            else:
                w.encrypted = True
                w.warnings.append("xprv chybí bez use_encryption — pravděpodobně šifrováný wallet")
        xpub = ks.get("xpub")
        if isinstance(xpub, str) and xpub:
            w.xpubs.append(xpub)
        # hardware keystore může nést více xpubs (list)
        xpubs_raw = ks.get("xpubs")
        if isinstance(xpubs_raw, list):
            for xp in xpubs_raw:
                if isinstance(xp, str) and xp.strip() and xp not in w.xpubs:
                    w.xpubs.append(xp)

    # ── legacy formát (seed jako string nahoře) ──
    seed_raw = obj.get("seed")
    if isinstance(seed_raw, str) and seed_raw.strip() and ks is None:
        w.format_version = "legacy"
        words = [t for t in seed_raw.split() if t]
        w.seed_words_count = len(words)
        w.seed_fingerprint = _fp(" ".join(w.lower() for w in words))
    elif isinstance(seed_raw, str) and seed_raw.strip():
        # moderní soubor s uloženou mnemonikou (starší 4.x) — citlivý materiál i tak
        words = [t for t in seed_raw.split() if t]
        w.seed_words_count = len(words)
        w.seed_fingerprint = _fp(" ".join(w.lower() for w in words))

    sv = obj.get("seed_version")
    w.seed_version_hint = str(sv) if sv is not None else None

    # ── šifrování (legacy use_encryption platí obě verze) ──
    if obj.get("use_encryption"):
        w.encrypted = True

    # soubor bez raw seedu → 0 slov; moderní BIP32 soubory zůstávají None
    # (seed tam fyzicky není — jen xprv/derivation)
    if w.format_version in ("legacy", "unknown") and w.seed_words_count is None:
        w.seed_words_count = 0

    return w


# ── MetaMask ─────────────────────────────────────────────────────────────


def _vault_material(
    obj: dict[str, Any],
) -> tuple[str | None, str | None, dict[str, Any], str]:
    """Unified access to the vault's crypto material — both layouts.

    - top-level (simplified): ``dat`` + ``dkty``/``kdfparams`` + ``salt``; IV = first 16 B of ``dat``;
    - nested (real MetaMask v3): ``crypto.ciphertext``, ``crypto.cipherparams.iv``,
      ``crypto.kdfparams`` — separate IV field.

    Returns ``(dat_b64, iv_b64 | None, kdf_params, kdf_name)``.
    """

    crypto_raw = obj.get("crypto")
    if isinstance(crypto_raw, dict):
        params_raw = crypto_raw.get("kdfparams")
        params: dict[str, Any] = params_raw if isinstance(params_raw, dict) else {}
        cipher_params_raw = crypto_raw.get("cipherparams")
        iv = (
            cipher_params_raw.get("iv")
            if isinstance(cipher_params_raw, dict)
            else None
        )
        ct = crypto_raw.get("ciphertext")
        return (
            ct if isinstance(ct, str) else None,
            iv if isinstance(iv, str) else None,
            params,
            str(crypto_raw.get("kdf") or "scrypt").lower(),
        )
    top_params_raw = obj.get("kdfparams")
    top_params: dict[str, Any] = top_params_raw if isinstance(top_params_raw, dict) else {}
    dat = obj.get("dat")
    return (
        dat if isinstance(dat, str) else None,
        None,
        top_params,
        str(obj.get("dkty") or "scrypt").lower(),
    )


def is_metamask_vault(obj: Any) -> bool:
    """Heuristic: is the JSON object a MetaMask vault? (top-level and nested ``crypto`` layout)"""

    if not isinstance(obj, dict):
        return False
    dat_b64, _iv_b64, params, kdf_name = _vault_material(obj)
    salt_b64 = obj.get("salt") or params.get("salt")
    has_salt = isinstance(salt_b64, str) and bool(kdf_name)
    return dat_b64 is not None and len(dat_b64) >= 32 and has_salt


def eip55_checksum_address(addr_hex: str) -> str:
    """Kanonická EIP-55 casing pro 40hex adresu (bez prefixu)."""

    h = addr_hex.lower()
    digest = keccak256(h.encode("ascii")).hex()
    out = "".join(
        c.upper() if (c.isalpha() and int(digest[i], 16) >= 8) else c for i, c in enumerate(h)
    )
    return "0x" + out


# řád křivky secp256k1 (BIP-0461 / SEC 2) — ověřeno nezávislými zdroji
_SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def eth_address_from_private_key(priv_hex: str) -> str | None:
    """ETH adresa z 32B privátního klíče (hex).

    secp256k1 → nekomprimovaný pub-key (bez prefixu) → Keccak-256[12:] → EIP-55.
    Platný klíč: přesně 32 B a ``1 ≤ k < N`` (řád křivky). Chybějící
    `cryptography` / špatný klíč → ``None`` (defenzivní).
    """

    try:
        from cryptography.hazmat.primitives.asymmetric import ec

        raw = priv_hex.strip()
        key_bytes = bytes.fromhex(raw)
        if len(key_bytes) != 32:
            return None
        key_int = int.from_bytes(key_bytes, "big")
        if not 1 <= key_int < _SECP256K1_N:
            return None
        priv = ec.derive_private_key(key_int, ec.SECP256K1())
        nums = priv.public_key().public_numbers()
        pub64 = nums.x.to_bytes(32, "big") + nums.y.to_bytes(32, "big")
        digest = keccak256(pub64)
        return eip55_checksum_address(digest[12:].hex())
    except Exception:  # noqa: BLE001 — defenzivní: libovolná chybná data → None
        return None


def _b64(value: Any) -> bytes | None:
    try:
        return base64.b64decode(value, validate=True)
    except Exception:  # noqa: BLE001 — pad/validate tolerantně
        try:
            return base64.b64decode(value + "=" * (-len(value) % 4))
        except Exception:  # noqa: BLE001
            return None


def _derive_vault_key(password: str, vault: dict[str, Any]) -> bytes:
    """KDF podle vault metadat — scrypt (default) nebo pbkdf2-sha256."""

    _dat_b64, _iv_b64, params, name = _vault_material(vault)
    salt_b64 = vault.get("salt") or params.get("salt")
    salt = _b64(salt_b64) if isinstance(salt_b64, str) else None
    if salt is None:
        raise UnsupportedKDFError("vault bez salt")
    dklen = int(params.get("dklen", 32))

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    pw = password.encode("utf-8")
    if name == "scrypt":
        n = int(params.get("n", 262144))
        r = int(params.get("r", 8))
        p = int(params.get("p", 8))
        return Scrypt(salt=salt, length=dklen, n=n, r=r, p=p).derive(pw)
    if name in ("pbkdf2-sha256", "pbkdf2"):
        c = int(params.get("c", 262144))
        return (
            PBKDF2HMAC(algorithm=hashes.SHA256(), length=dklen, salt=salt, iterations=c).derive(pw)
        )
    raise UnsupportedKDFError(f"neznámý KDF: {name!r}")


def decrypt_metamask_vault(raw: str | bytes | dict[str, Any], password: str) -> MetaMaskVaultData:
    """Dešifruje MetaMask vault heslem a extrahuje účty.

    Výjimky: ``UnsupportedKDFError`` (neznámý KDF), ``ValueError`` (špatný
    base64/hex, poškozené dat). Špatné heslo se projeví jako invalidní JSON
    payload → ValueError("…payload…").
    """

    try:
        obj = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"vault není JSON: {e}") from e
    if not is_metamask_vault(obj):
        raise ValueError("nevyhodí se struktura MetaMask vaultu")
    dat_b64, iv_b64, _params, kdf_name = _vault_material(obj)

    data = MetaMaskVaultData(kdf=kdf_name, decrypted=False)
    if iv_b64 is not None:
        # vnořený layout (reálný MetaMask v3): IV v cipherparams, dat = ciphertext
        iv = _b64(iv_b64)
        ciphertext = _b64(dat_b64) if isinstance(dat_b64, str) else None
        if iv is None or len(iv) != 16 or not ciphertext:
            raise ValueError("crypto.cipherparams.iv / ciphertext: špatný base64")
    else:
        # top-level layout: IV = první 16 B dat
        dat_bytes = _b64(dat_b64) if isinstance(dat_b64, str) else None
        if dat_bytes is None or len(dat_bytes) < 17:
            raise ValueError("dat: špatný base64 nebo příliš krátký")
        iv, ciphertext = dat_bytes[:16], dat_bytes[16:]

    key = _derive_vault_key(password, obj)

    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    dec = Cipher(algorithms.AES(key), modes.CTR(iv)).decryptor()
    plain = dec.update(ciphertext) + dec.finalize()
    try:
        payload = json.loads(plain.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"po dešifrování není JSON — špatné heslo? ({e})") from e

    data.decrypted = True
    keys: list[str] = []
    if isinstance(payload, list):  # default keyring — seznam hex klíčů
        for item in payload:
            if isinstance(item, str) and len(item) == 64:
                keys.append(item.lower())
            else:
                data.warnings.append("neznačovaný prvek v default keyringu")
    elif isinstance(payload, dict):  # více keyringů
        for kr in payload.get("keyrings", []):
            if not isinstance(kr, dict):
                continue
            if kr.get("type") == "private_key":
                keys.extend(
                    k.lower() for k in kr.get("accounts", []) if isinstance(k, str) and len(k) == 64
                )
            else:
                data.warnings.append(f"nepodporovaný keyring typ: {kr.get('type')!r}")

    seen: set[str] = set()
    for k in keys:
        addr = eth_address_from_private_key(k)
        if addr is None:
            data.warnings.append("klíč se nepodařilo převést na adresu")
            continue
        account = MetaMaskAccount(
            address=addr, private_key_fingerprint=_fp(bytes.fromhex(k))
        )
        if account.private_key_fingerprint not in seen:
            seen.add(account.private_key_fingerprint)
            data.accounts.append(account)
    return data


def parse_metamask_vault(
    raw: str | bytes | dict[str, Any], password: str | None = None
) -> MetaMaskVaultData | None:
    """Parsování MetaMask vaultu; bez hesla jen struktura (decrypted=False).

    Ne-vault → ``None``. Chyby dešifrování s daným heslem → ValueError (volající
    vrstva rozhodne, zda je to špatné heslo nebo poškozený soubor).
    """

    try:
        obj = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not is_metamask_vault(obj):
        return None
    if password is None:
        return MetaMaskVaultData(kdf=str(obj.get("dkty") or "scrypt").lower(), decrypted=False)
    return decrypt_metamask_vault(raw, password)


# ── K2.1: Bitcoin Core wallet.dat (BDB btree) ────────────────────────

#: Klíče Bitcoin Core v BDB — prefixy / formát klíčů (CWallet::Load*):
#:   name:<adresa>  → label; tx<32B txid> → CTxOutRef (UTXO); walletversion u32 LE;
#:   bestblock <32B hash>; crypted_key <64B> (přítomnost = šifrovaná peněženka).
_BTC_NAME_PREFIX = b"name:"
_BTC_TX_PREFIX = b"tx"


class BitcoinCoreWallet(BaseModel):
    """Vyextrahovaná metadata z Bitcoin Core ``wallet.dat`` (bez raw klíčů).

    Adresy a labely = veřejná data; privátní klíče se neukládají — jen počet
    záznamů (PII guard, spec §7). Transakční ID jsou on-chain data (veřejná).
    """

    encrypted: bool = False  # přítomnost záznamu crypted_key
    addresses: list[str] = Field(default_factory=list)  # name:<addr> klíče
    labels: dict[str, str] = Field(default_factory=dict)  # adresa → label (i "")
    transaction_ids: list[bytes] = Field(default_factory=list)  # tx<32B> klíče
    wallet_version: int | None = None  # u32 LE z "walletversion"
    best_block_hash_hex: str | None = None  # "bestblock" (32 B)
    private_key_count: int = 0  # heuristika CKey záznamů (klíč 0x02/0x03, value ≥45 B)
    record_count: int = 0  # celkový počet KV záznamů v DB
    warnings: list[str] = Field(default_factory=list)


def parse_bitcoin_core_wallet(data: bytes) -> BitcoinCoreWallet | None:
    """Parsování Bitcoin Core ``wallet.dat`` (BDB btree, logické jméno NULL).

    :param data: celý obsah souboru.
    :returns: extrahovaná metadata; ``None``, pokud btree neobsahuje žádné
      rozpoznatelné bitcoin záznamy (jiná aplikace stejný kontejner).
    :raises BdbError: strukturní poškození btree (volající kód → soubor mimo).

    Heuristika privátních klíčů: Bitcoin Core ukládá CKey pod klíčem = veřejný
    klíč, první byte value 0x02 (KEY_PRIVKEY) / 0x03 (WATCH_ONLY), délka ≥ 45 B.
    """

    records = parse_bdb_btree(data)
    wallet = BitcoinCoreWallet(record_count=len(records))
    recognized = False

    for key, value in records:
        if key.startswith(_BTC_NAME_PREFIX):
            addr = key[len(_BTC_NAME_PREFIX) :].decode("latin-1")
            label = value.decode("latin-1", "replace")
            if addr and addr not in wallet.labels:
                wallet.labels[addr] = label
                wallet.addresses.append(addr)
                recognized = True
        elif key.startswith(_BTC_TX_PREFIX) and len(key) == 2 + 32:
            wallet.transaction_ids.append(bytes(key[2:]))
            recognized = True
        elif key == b"walletversion":
            if len(value) >= 4:
                wallet.wallet_version = int.from_bytes(value[:4], "little")
                recognized = True
        elif key == b"bestblock" and len(value) == 32:
            wallet.best_block_hash_hex = value.hex()
            recognized = True
        elif key == b"crypted_key":
            wallet.encrypted = True
            recognized = True
        else:
            # CKey záznamy: klíč = veřejný klíč (první byte 0x02/0x03), value ≥ 45 B
            if len(key) >= 1 and key[0] in (0x02, 0x03) and len(value) >= 45:
                wallet.private_key_count += 1

    if not recognized:
        return None
    if wallet.encrypted:
        wallet.warnings.append(
            "peněženka je šifrovaná (crypted_key) — privátní klíče bez hesla nečitelné"
        )
    elif wallet.private_key_count > 0:
        wallet.warnings.append(
            f"{wallet.private_key_count} privátních klíčů v čistém textu "
            "(nesifrovaná peněženka)"
        )
    return wallet
