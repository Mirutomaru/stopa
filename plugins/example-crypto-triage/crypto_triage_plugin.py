"""Ukázkový plugin F6.4 — triage profil „Exfiltrace kryptomajetku“.

Komplementární ke vestavěnému RANSOMWARE profilu: zatímco ten hledá
zamykání souborů, tento signálizuje odnášení krypto peněženek/klíčů a
pohyb prostředků (K-LINKA artefakty + wallet kontejnery + exchange exporty).

Kontrakt dle ``docs/PLUGINS_API.md``: factory ``build_profile()`` vrací
``TriageProfile`` (frozen dataclass z ``stopa.intelligence.triage``).
"""

from __future__ import annotations

from stopa.intelligence.triage import SignalSpec, TriageProfile


def build_profile() -> TriageProfile:
    """Vytvoří triage profil crypto_exfiltration."""
    return TriageProfile(
        key="crypto_exfiltration",
        title="Exfiltrace kryptomajetku",
        description=(
            "Odnášení krypto peněženek a privátních klíčů z obrazu: více "
            "detekovaných tajností, wallet kontejnery na disku (wallet.dat / "
            "MetaMask keychain) a exchange exporty indikující pohyb prostředků."
        ),
        signals=(
            SignalSpec(
                key="crypto_secrets", weight=3, kind="artifact_type",
                patterns=("crypto_wallet", "crypto_detection", "private_key"),
                min_count=2,
                description="≥ 2 krypto tajnosti na obrazu (K-LINKA detekce)",
            ),
            SignalSpec(
                key="wallet_containers", weight=3, kind="file_pattern",
                pattern=r"(?i)(^|/)(wallet\.dat|keychain)\b",
                description="wallet kontejnery na disku (Bitcoin Core / MetaMask)",
            ),
            SignalSpec(
                key="exchange_exports", weight=2, kind="file_pattern",
                pattern=r"(?i)(binance|coinbase|kraken)[\w./-]*\.(csv|xlsx)$",
                description="exchange exporty (pohyb prostředků)",
            ),
            SignalSpec(
                key="mnemonic_text", weight=2, kind="artifact_text",
                pattern=r"(?i)(BIP39|seed phrase|m/44')",
                description="mnemonická fráze / derivace cesty v textu artefaktu",
            ),
        ),
        threshold=7,
        min_signals=2,
        hypothesis_template=(
            "Case {case_id}: podezření na exfiltrace kryptomajetku "
            "(skóre {score}, signály: {signals}) — prověřit wallet kontejnery "
            "a exchange historii."
        ),
    )
