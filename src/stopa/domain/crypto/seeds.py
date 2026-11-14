"""Crypto Forensics Unit — BIP39 seed phrase detector (K1.1).

Detekce validních BIP39 mnemonic ve volném textu:
- **sliding window** nad maximalními běhy slov z wordlistu,
- standardní délky ``{12, 15, 18, 21, 24}`` slov (AK dle ROADMAPu zaměřen na
  12/18/24 — nejčastější v praxi),
- **checksum validace**: poslední ``E/32`` bitů musí odpovídat SHA-256(entropy) —
  eliminuje prakticky všechny false positive (náhodný text z wordlistu).

Wordlist: oficiální BIP39 english (2048 slov), bundlovaný v
``data/bip39_english.txt``. Bez externích závislostí.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

_WORDLIST_PATH = Path(__file__).resolve().parent / "data" / "bip39_english.txt"

# Standardní délky BIP39: (slova, entropy bitů) — checksum = entropy/32.
VALID_LENGTHS: tuple[tuple[int, int], ...] = (
    (12, 128),
    (15, 160),
    (18, 192),
    (21, 224),
    (24, 256),
)

_WORDLIST: tuple[str, ...] | None = None
_WORD_INDEX: dict[str, int] | None = None


def _load_wordlist() -> tuple[tuple[str, ...], dict[str, int]]:
    global _WORDLIST, _WORD_INDEX
    if _WORDLIST is None or _WORD_INDEX is None:
        words = [line.strip().lower() for line in _WORDLIST_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(words) != 2048 or len(set(words)) != 2048:
            raise ValueError(f"BIP39 wordlist musí mít přesně 2048 unikátních slov, má {len(set(words))}")
        _WORDLIST = tuple(words)
        _WORD_INDEX = {w: i for i, w in enumerate(words)}
    return _WORDLIST, _WORD_INDEX


def is_word_in_list(word: str) -> bool:
    """Je slovo v BIP39 wordlistu (case-insensitive)?"""

    _, index = _load_wordlist()
    return word.lower() in index


def validate_mnemonic(words: list[str] | tuple[str, ...]) -> bool:
    """Plná BIP39 validace mnemonic: délka + membership + checksum.

    Entropy bitů E z prvního ``E`` bitů; poslední ``C = E/32`` bitů musí být
    roven prvním C bitům SHA-256(entropy).
    """

    n = len(words)
    entropy_bits = next((e for ln, e in VALID_LENGTHS if ln == n), None)
    if entropy_bits is None:
        return False
    _, index = _load_wordlist()
    idxs: list[int] = []
    for w in words:
        i = index.get(w.lower())
        if i is None:
            return False
        idxs.append(i)

    bits = "".join(f"{i:011b}" for i in idxs)
    checksum_bits = entropy_bits // 32
    entropy_bytes = int(bits[:entropy_bits], 2).to_bytes(entropy_bits // 8, "big")
    # BIP-39: checksum = prvních C bitů SHA-256 (MSB-first), nikoli dolních!
    # Digest je vždy 256 bitů, bez ohledu na délku entropy.
    digest_int = int.from_bytes(hashlib.sha256(entropy_bytes).digest(), "big")
    expected = format(digest_int >> (256 - checksum_bits), f"0{checksum_bits}b")
    return bits[entropy_bits:] == expected


@dataclass(frozen=True)
class SeedMatch:
    """Detekovaná seed phrase v textu (raw materiál — do DB jen fingerprint).

    ``start``/``end`` = indexy tokenu ve zdrojovém tokenizovaném textu
    (polo-open interval); ``words`` je normalizovaný (malá písmena) tuple.
    """

    words: tuple[str, ...]
    length: int
    start: int
    end: int
    checksum_valid: bool = True
    fingerprint_sha256: str = field(default="")


def _fingerprint(words: tuple[str, ...]) -> str:
    return hashlib.sha256("|".join(words).encode("utf-8")).hexdigest()


def detect_in_text(text: str) -> list[SeedMatch]:
    """Najde všechny validní BIP39 seed phrase ve volném textu.

    Tokenizace = whitespace; hledá se v maximalních bězích slov z wordlistu,
    uvnitř nich sliding window o všech standardních délkách a každé okno se
    ověří checksumem. Vráceny všechny unikátní (start, words) shody.
    """

    _, index = _load_wordlist()
    tokens = text.lower().split()
    in_list = [index.get(t) is not None for t in tokens]

    matches: list[SeedMatch] = []
    seen: set[tuple[int, tuple[str, ...]]] = set()
    i = 0
    while i < len(tokens):
        if not in_list[i]:
            i += 1
            continue
        j = i
        while j < len(tokens) and in_list[j]:
            j += 1
        # běh tokens[i:j] — všechny jsou z wordlistu; zkoušej okna.
        run_len = j - i
        for length, _entropy in VALID_LENGTHS:
            if run_len >= length:
                for k in range(i, j - length + 1):
                    window = tuple(tokens[k : k + length])
                    key = (k, window)
                    if key not in seen and validate_mnemonic(window):
                        seen.add(key)
                        matches.append(SeedMatch(words=window, length=length, start=k, end=k + length, fingerprint_sha256=_fingerprint(window)))
        i = j

    # Deduplikace vnořených oken: kratší validní okno, které leží striktně uvnitř
    # rozpětí delšího validního shodu, reportujeme jen jednou (dlouhou) — např.
    # 12slovný substring uvnitř platné 24slovné fráze není prakticky samostatný seed.
    def _contained(m: SeedMatch) -> bool:
        return any(n is not m and n.start <= m.start and m.end <= n.end for n in matches)

    return [m for m in matches if not _contained(m)]
