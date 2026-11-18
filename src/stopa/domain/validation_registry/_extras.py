"""ETAPA B vlna 15 (SIM TPDU phonebook F1.6) + K2 crypto forensics
(wallets, exchange CSV, content scan).

P1-4 vlna E — datová sekce rejstříku; záznamy byte-přesně z monolitu.
"""

from __future__ import annotations

from ._types import ParserValidation

_PART = {
    # ── ETAPA B vlna 15 — AXIOM port: SIM TPDU phonebook (F1.6) ──
    "sim_tpdu": ParserValidation(
        parser_id="sim_tpdu",
        version="",
        formats=(
            "SIM TPDU phonebook textový export (AT+CPBR dump / CSV) — kontakty z SIM karty",
        ),
        limitations=(
            "detekce name-based (*.tpdu, *.cpbr, *.simdump, .csv + content check)",
            "kontakt = contact; dedup podle normalizovaného čísla; limit MAX_CONTACTS=500",
        ),
        test_files=("tests/test_sim_tpdu.py", "tests/test_p11_quality_capstone.py"),
    ),
    # K2 — crypto forensics (wallets, exchange CSV, content scan)
    "crypto_extract": ParserValidation(
        parser_id="crypto_extract",
        version="",
        formats=(
            "Electrum wallet JSON (3.x/4.x keystore + legacy ≤2.x)",
            "MetaMask vault JSON (AES-128-CTR, scrypt/pbkdf2-sha256 KDF)",
            "exchange CSV exporty (Binance deposits/withdrawals/trades, Coinbase transactions/balance, Kraken trades/funds)",
            "K1 content scan — vestěné klíče/seedy/adresy/transakční refy v libovolném textu",
        ),
        limitations=(
            "PII guard: seed slova a privátní klíče jen jako SHA-256 fingerprint (spec §7)",
            "MetaMask bez hesla → struktura (decrypted=False), účty až s heslem",
            "K1 content scan: text do 4 MiB; exchange záznamy strop 20 000/soubor",
            "wallet.dat (Berkeley DB) odložen — K2.1 deferred dle specu",
        ),
        test_files=(
            "tests/test_k2_crypto_wallets.py",
            "tests/test_k2_exchange_csv.py",
            "tests/test_k2_pipeline_integration.py",
            "tests/test_p11_quality_crypto_misc.py",
        ),
    ),
}
