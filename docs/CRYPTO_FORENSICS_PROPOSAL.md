# 🪙 FÁZE 7 — KRYPTOMĚNOVÁ FORENZNÍ SKUPINA (Crypto Forensics Unit)

**Verze:** 1.0.0
**Datum:** 2026-11-10
**Status:** Nová specializovaná jednotka (navrženo; re-scoping viz níže)
**Priorita:** `P0` (kritické pro moderní forenziku)

> **STOPA interní poznámka (re-scoping):** Tento návrh se implementuje jako nezávislá
> K-linka po dokončení F1.2 Memory Forensics a release 2.0, aby nedošlo k kolizi s
> ROADMAP V2 Fáze 0–6 a CK schedule. Bezpečnostní zásada: surové seed/klíče se do case DB
> **neukládají** — jen typ + fingerprint/hash tajnosti (case DB se kopíruje/backupuje).

---

## 🎯 VIZE A CÍL

Kryptoměnová forenzika je dnes **nejrychleji rostoucí oblast** digitálních důkazů. Ransomware, dark web trhy, NFT podvody, DeFi exploitace — vše se točí kolem blockchainů. STOPA musí být schopna:

1. **Detekovat** kryptoměnové stopy v jakémkoliv souboru/obrazu
2. **Extrahovat** klíče, adresy, wallet data, transakční historii
3. **Korelovat** entity napříč blockchainy a off-chain daty
4. **Vizualizovat** tok peněz (fund flow analysis)
5. **Generovat** soudně použitelné reporty pro krypto případy

---

## 🏗️ ARCHITEKTURA KRYPTO MODULU

### Struktura v rámci STOPA

```
domain/
├── crypto/
│   ├── addresses.py          # Adresní validátory (BTC, ETH, XMR, atd.)
│   ├── seeds.py              # BIP39 seed phrase detection + validation
│   ├── keys.py               # Private/public key extraction
│   ├── wallets.py            # Wallet file parsers
│   ├── transactions.py       # On-chain transaction analysis
│   ├── exchanges.py          # Exchange record parsers
│   ├── darkweb.py            # Marketplace data correlation
│   ├── defi.py               # DeFi protocol detection
│   └── correlation.py        # Cross-chain entity resolution

artifacts/
├── crypto/
│   ├── bitcoin.py            # Bitcoin specific extractors
│   ├── ethereum.py           # Ethereum + ERC-20 tokens
│   ├── monero.py             # Privacy coin analysis
│   ├── altcoins.py           # Generic altcoin support
│   ├── wallet_files.py       # Wallet file parsers (Electrum, MetaMask, atd.)
│   ├── exchange_exports.py   # CSV/JSON z burz
│   ├── browser_extensions.py # MetaMask, Phantom, atd.
│   └── mining.py             # Mining pool evidence

data/
├── crypto/
│   ├── blockchain_api.py     # Integrace s Blockchair, Etherscan, atd.
│   ├── address_clusters.py   # Heuristické shlukování adres
│   └── tx_graph.py           # Transakční graf (DuckDB)
```

---

## 🔍 DETEKČNÍ MATICE (Co hledáme)

### 1. Seed Phrases (BIP39) — **KRITICKÉ**

**Co hledáme:**
- 12, 18, 24 slov z BIP39 wordlistu (2048 slov)
- Formáty: plain text, v souborech (.txt, .md, .json), v paměti, v zálohách
- Šifrované seedy (password-protected)

**Implementace:**
```python
# domain/crypto/seeds.py
class BIP39Detector:
    WORDLIST = load_bip39_wordlist()  # 2048 slov

    def detect_in_text(self, text: str) -> list[SeedPhrase]:
        # Sliding window 12/18/24 slov
        # Validace checksum (poslední slovo)
        # Score: počet slov z wordlistu + checksum validita

    def detect_in_file(self, file_path: Path) -> list[SeedPhrase]:
        # Read file, split by whitespace/newlines
        # Apply detect_in_text

    def detect_in_memory(self, memory_dump: bytes) -> list[SeedPhrase]:
        # Regex + wordlist matching
        # Fuzzy matching pro OCR errors
```

**Akceptační kritéria:**
- Detekce 100 % validních seed phrases v testovacích fixture
- False positive rate < 0.1 % (náhodná slova nejsou seed)
- Podpora multicurrency seeds (BTC + ETH + XMR z jednoho seedu)

---

### 2. Private Keys — **KRITICKÉ**

**Formáty k detekci:**

| Typ | Formát | Příklad | Regex/Pattern |
|---|---|---|---|
| Bitcoin WIF | Base58Check | `5Kb8kLf9zgWQnogidDA76Mz...` | `[5KL][1-9A-HJ-NP-Za-km-z]{51,52}` |
| Bitcoin WIF compressed | Base58Check | `Kx983Dh...` | `[KL][1-9A-HJ-NP-Za-km-z]{51,52}` |
| Ethereum hex | 0x-prefixed | `0x1234...` (64 hex chars) | `0x[a-fA-F0-9]{64}` |
| Raw hex | 64 hex chars | `1234abcd...` | `[a-fA-F0-9]{64}` (context-sensitive) |
| Base64 | Base64 encoded | `SGVsbG8...` | Base64 decode → 32 bytes |
| PEM | PEM format | `-----BEGIN PRIVATE KEY-----` | PEM header + base64 body |
| Electrum seed | Electrum-specific | Electrum seed format | Electrum version check |

**Implementace:**
```python
# domain/crypto/keys.py
class PrivateKeyDetector:
    PATTERNS = {
        'btc_wif': r'[5KL][1-9A-HJ-NP-Za-km-z]{51,52}',
        'eth_hex': r'0x[a-fA-F0-9]{64}',
        'raw_hex': r'[a-fA-F0-9]{64}',
        'pem': r'-----BEGIN (?:EC )?PRIVATE KEY-----.*?-----END',
    }

    def detect(self, content: str | bytes) -> list[PrivateKey]:
        # Regex matching
        # Base58Check validation (BTC)
        # Checksum validation
        # Context analysis (je to opravdu klíč nebo jen hex string?)
```

**Akceptační kritéria:**
- Detekce všech výše uvedených formátů
- Validace checksum (WIF, Base58Check)
- Rozlišení "opravdový klíč" vs "náhodný hex string" (kontextuální analýza)

---

### 3. Adresy (Public Keys & Addresses)

**Podporované blockchainy:**

| Blockchain | Adresní formáty | Priorita |
|---|---|---|
| Bitcoin | Legacy (1...), SegWit (3...), Bech32 (bc1...) | P0 |
| Ethereum | 0x... (40 hex) | P0 |
| Monero | 95-char addresses, subaddresses | P0 |
| Litecoin | L..., M..., ltc1... | P1 |
| Bitcoin Cash | bitcoincash:q... | P1 |
| Dogecoin | D... | P2 |
| Solana | Base58 (32-44 chars) | P1 |
| Cardano | addr1... | P2 |
| Polkadot | 1... | P2 |
| Ripple | r... | P2 |

**Implementace:**
```python
# domain/crypto/addresses.py
class AddressValidator:
    VALIDATORS = {
        'btc_legacy': r'^1[a-km-zA-HJ-NP-Z1-9]{25,34}$',
        'btc_segwit': r'^3[a-km-zA-HJ-NP-Z1-9]{25,34}$',
        'btc_bech32': r'^bc1[a-z0-9]{39,59}$',
        'eth': r'^0x[a-fA-F0-9]{40}$',
        'xmr': r'^4[0-9AB][1-9A-HJ-NP-Za-km-z]{93}$',
        # ... další
    }

    def validate(self, address: str) -> AddressInfo | None:
        # Regex match
        # Checksum validation (Ethereum EIP-55, Bech32)
        # Return blockchain type + validity
```

**Akceptační kritéria:**
- Validace všech výše uvedených formátů
- Checksum validation tam, kde je dostupné
- Detekce nevalidních adres (typografické chyby)

---

### 4. Wallet Files

**Podporované wallet formáty:**

| Wallet | Souborový formát | Lokace | Parser |
|---|---|---|---|
| Bitcoin Core | `wallet.dat` (BDB) | `~/.bitcoin/wallets/` | BDB parser |
| Electrum | `default_wallet` (JSON) | `~/.electrum/wallets/` | JSON parser |
| Exodus | `exodus.conf` + seed | App data | Custom parser |
| MetaMask | Vault (encrypted JSON) | Browser extension storage | Vault decryptor |
| Ledger | (Hardware, no file) | N/A | API integration |
| Trezor | (Hardware, no file) | N/A | API integration |
| Trust Wallet | Encrypted DB | Mobile app | Mobile forensics |
| Phantom | Encrypted JSON | Browser extension storage | Vault decryptor |

**Implementace:**
```python
# artifacts/crypto/wallet_files.py
class WalletFileExtractor:
    def extract_bitcoin_core(self, wallet_dat: Path) -> WalletData:
        # Parse BDB (Berkeley DB)
        # Extract: addresses, labels, transactions, keys (if unencrypted)

    def extract_electrum(self, wallet_file: Path) -> WalletData:
        # Parse JSON
        # Extract: seed (if present), addresses, labels, keystore

    def extract_metamask(self, vault: dict) -> WalletData:
        # Decrypt vault (password required)
        # Extract: accounts, keyrings, network preferences
```

**Akceptační kritéria:**
- Parsování všech výše uvedených formátů
- Extrakce adres, labelů, transakcí
- Detekce šifrovaných walletů (varování v reportu)

---

### 5. Exchange Records

**Podporované burzy:**

| Exchange | Formát exportu | Co extrahujeme |
|---|---|---|
| Binance | CSV | Trades, deposits, withdrawals, P2P |
| Coinbase | CSV | Transactions, balances, tax report |
| Kraken | CSV | Trades, ledger, deposits/withdrawals |
| KuCoin | CSV | Trade history, order history |
| Bybit | CSV | Trade history, order history |
| OKX | CSV | Trade history, bill details |
| Gemini | CSV | Transactions, transfers |

**Implementace:**
```python
# artifacts/crypto/exchange_exports.py
class ExchangeExtractor:
    PARSERS = {
        'binance': BinanceCSVParser,
        'coinbase': CoinbaseCSVParser,
        'kraken': KrakenCSVParser,
        # ...
    }

    def extract(self, csv_file: Path, exchange: str) -> ExchangeData:
        # Parse CSV
        # Normalize to common schema
        # Extract: timestamps, amounts, addresses, fees
```

**Akceptační kritéria:**
- Parsování CSV z 10+ hlavních burz
- Normalizace do společného schematu
- Detekce chybějících záznamů (gaps v timeline)

---

### 6. On-Chain Analysis

**Co děláme:**
- **Address clustering:** Heuristické shlukování adres (common-input, change-address detection)
- **Transaction graph:** Vizualizace toku peněz
- **Entity tagging:** Označení adres (exchange, darknet market, mixer, atd.)
- **Risk scoring:** Scoring rizikovosti adres (sanctions, illicit activity)

**Integrace s externími API:**
```python
# data/crypto/blockchain_api.py
class BlockchainAPI:
    def __init__(self, api_key: str):
        self.blockchair = BlockchairClient(api_key)
        self.etherscan = EtherscanClient(api_key)

    def get_address_info(self, address: str) -> AddressInfo:
        # Balance, transaction count, first/last seen
        # Tags: exchange, mixer, darknet, sanctioned

    def get_transaction_graph(self, tx_hash: str, depth: int = 3) -> TxGraph:
        # Input/output addresses
        # Amounts, timestamps
        # Recursive expansion

    def cluster_addresses(self, addresses: list[str]) -> list[Cluster]:
        # Common-input heuristic
        # Change-address detection
        # Return clusters of related addresses
```

**Akceptační kritéria:**
- Integrace s Blockchair (multi-chain) a Etherscan (ETH)
- Address clustering s přesností > 80 %
- Risk scoring na základě veřejných blacklistů (OFAC, EU sanctions)

---

### 7. Dark Web & Illicit Activity

**Co detekujeme:**
- **Marketplace data:** Vendor names, product listings, PGP keys
- **Forum posts:** Bitcoin addresses v příspěvcích, escrow references
- **Ransomware notes:** Wallet addresses v ransom notes
- **Mixer/Tumbler usage:** Detekce použití CoinJoin, Wasabi, Samourai

**Implementace:**
```python
# domain/crypto/darkweb.py
class DarkWebDetector:
    def detect_marketplace_data(self, text: str) -> MarketplaceEvidence:
        # Regex: PGP keys, vendor names, product codes
        # NLP: entity extraction (drug names, quantities)

    def detect_ransom_note(self, file: Path) -> RansomNote:
        # Detect ransom note templates (LockBit, Conti, atd.)
        # Extract: wallet address, amount, deadline

    def detect_mixer_usage(self, transactions: list[Transaction]) -> bool:
        # CoinJoin pattern detection
        # Wasabi/Samourai transaction patterns
```

**Akceptační kritéria:**
- Detekce 5+ ransomware templates
- Extraktion wallet adres z ransom notes
- Detekce CoinJoin patterns (≥ 70 % přesnost)

---

## 📊 VIZUALIZACE A REPORTING

### 1. Fund Flow Diagram

**Co zobrazujeme:**
- Graf transakcí (nodes = adresy, edges = transakce)
- Časová osa (x-axis = time, y-axis = amount)
- Barevné kódování (exchange, darknet, mixer, unknown)
- Interaktivní zoom in/out

**Implementace:**
```python
# web/crypto/flow_diagram.py
class FundFlowDiagram:
    def generate(self, case_id: str) -> FlowDiagram:
        # Query DuckDB for transactions
        # Build graph (nodes + edges)
        # Apply layout algorithm (force-directed)
        # Return D3.js-compatible JSON

    def render_interactive(self, diagram: FlowDiagram) -> HTML:
        # D3.js rendering
        # Zoom, pan, click-to-expand
        # Export to PNG/SVG/PDF
```

### 2. Krypto Report (SWGDE Compliant)

**Obsah reportu:**
1. **Executive Summary:** Shrnutí krypto stop
2. **Wallet Discovery:** Nalezené wallety, seeds, keys
3. **Address Inventory:** Všechny nalezené adresy (tabulka)
4. **Transaction Timeline:** Chronologický přehled transakcí
5. **Fund Flow Analysis:** Vizualizace toku peněz
6. **Exchange Correlation:** Propojení s exchange records
7. **Entity Attribution:** Identifikované entity (exchanges, mixers, atd.)
8. **Risk Assessment:** Scoring rizikovosti
9. **Methodology:** Použité nástroje a metody
10. **Chain of Custody:** Audit log

**Implementace:**
```python
# reporting/crypto_report.py
class CryptoReportGenerator:
    def generate(self, case_id: str) -> PDFReport:
        # Query all crypto artifacts
        # Generate fund flow diagram
        # Build transaction timeline
        # Apply SWGDE template
        # Sign with Ed25519
        # Return PDF + JSON
```

---

## 🧪 TESTOVACÍ STRATEGIE

### Testovací fixture

**1. Seed Phrases:**
- 100 validních BIP39 seed phrases (12/18/24 slov)
- 50 invalidních (špatný checksum, cizí slova)
- 20 edge-cases (OCR errors, multiline, v HTML)

**2. Private Keys:**
- 50 Bitcoin WIF keys (compressed + uncompressed)
- 50 Ethereum private keys
- 20 PEM encoded keys
- 30 "false positives" (náhodné hex strings)

**3. Wallet Files:**
- Bitcoin Core `wallet.dat` (encrypted + unencrypted)
- Electrum wallet files
- MetaMask vaults (různé verze)
- Exodus wallets

**4. Exchange CSVs:**
- 10 CSV z každé hlavní burzy (Binance, Coinbase, Kraken, atd.)
- Edge-cases: chybějící sloupce, špatné formátování

**5. On-Chain Data:**
- 1000 transakcí z Blockchair API (cached)
- Address clusters (known exchanges, mixers)
- Ransomware notes (LockBit, Conti, atd.)

### Test cases

```python
# tests/crypto/test_seeds.py
def test_bip39_detection():
    detector = BIP39Detector()

    # Valid seeds
    assert len(detector.detect("abandon abandon abandon ... about")) == 1
    assert len(detector.detect_in_file(fixture("seed.txt"))) == 1

    # Invalid seeds
    assert len(detector.detect("random words that are not a seed")) == 0
    assert len(detector.detect("abandon abandon abandon ... wrong")) == 0  # bad checksum

    # Edge cases
    assert len(detector.detect("abandon\nabandon\nabandon\n...")) == 1  # multiline

# tests/crypto/test_addresses.py
def test_address_validation():
    validator = AddressValidator()

    # Bitcoin
    assert validator.validate("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa").blockchain == 'btc'
    assert validator.validate("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq").blockchain == 'btc'

    # Ethereum
    assert validator.validate("0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb").blockchain == 'eth'

    # Invalid
    assert validator.validate("not_an_address") is None
```

---

## 🔗 INTEGRACE S EXISTUJÍCÍ PIPELINE

### Jak to zapadne do STOPA

```
1. Ingest (stopa add <case>)
   ↓
2. File walk + hashing
   ↓
3. Signature detection (magic bytes)
   ↓
4. Dispatch → crypto extractors (pokud detekován wallet file, CSV, atd.)
   ↓
5. Content scanning (všechny soubory):
   - Regex pro seeds, keys, addresses
   - NLP pro dark web data
   ↓
6. Artifact creation:
   - crypto/seed_phrase
   - crypto/private_key
   - crypto/address
   - crypto/wallet
   - crypto/exchange_record
   - crypto/transaction
   ↓
7. Entity correlation:
   - Address clustering
   - Cross-chain correlation
   - Exchange ↔ on-chain matching
   ↓
8. Timeline materialization
   ↓
9. Fund flow graph generation
   ↓
10. Report generation (SWGDE compliant)
```

### Nové artifact typy

> **Poznámka:** STOPA konvence = snake_case bez lomítek → `crypto_seed_phrase`,
> `crypto_private_key`, ... (viz re-scoping výše).

```python
# domain/crypto/artifact_types.py
CRYPTO_ARTIFACT_TYPES = [
    'crypto/seed_phrase',
    'crypto/private_key',
    'crypto/public_key',
    'crypto/address',
    'crypto/wallet_file',
    'crypto/exchange_record',
    'crypto/transaction',
    'crypto/ransom_note',
    'crypto/marketplace_listing',
    'crypto/mixer_usage',
]
```

---

## 📈 METRIKY A KPI

| Metrika | Cíl |
|---|---|
| Seed phrase detection rate | 100 % (valid seeds) |
| Private key detection rate | 95 % (všechny formáty) |
| Address validation accuracy | 99 % |
| Wallet file parsing coverage | 10 hlavních walletů |
| Exchange CSV parsers | 10+ burz |
| On-chain API latency | < 2 s per query |
| Address clustering precision | > 80 % |
| Fund flow diagram render time | < 5 s (1000 tx) |
| Crypto report generation time | < 30 s |

---

## 🚀 ROADMAPA KRYPTO MODULU

### Fáze K1 — Základní detekce
- [ ] **K1.1** BIP39 seed phrase detector
- [ ] **K1.2** Private key detector (BTC WIF, ETH hex, PEM)
- [ ] **K1.3** Address validator (BTC, ETH, XMR)
- [ ] **K1.4** Test suite (500+ test cases)

### Fáze K2 — Wallet & Exchange
- [ ] **K2.1** Bitcoin Core wallet.dat parser *(re-scoping: odložit, BDB = samostatný C-dependency)*
- [ ] **K2.2** Electrum wallet parser
- [ ] **K2.3** MetaMask vault decryptor
- [ ] **K2.4** Exchange CSV parsers (Binance, Coinbase, Kraken)
- [ ] **K2.5** Test suite (300+ test cases)

### Fáze K3 — On-Chain Analysis *(re-scoping: offline-first; API jen opt-in)*
- [ ] **K3.1** Blockchain API integrace (Blockchair, Etherscan)
- [ ] **K3.2** Address clustering algorithm
- [ ] **K3.3** Transaction graph builder
- [ ] **K3.4** Risk scoring (OFAC, EU sanctions) — offline static listy
- [ ] **K3.5** Test suite (200+ test cases)

### Fáze K4 — Dark Web & Reporting
- [ ] **K4.1** Ransomware note detector
- [ ] **K4.2** Marketplace data extractor
- [ ] **K4.3** Mixer/Tumbler usage detection
- [ ] **K4.4** Fund flow diagram (D3.js)
- [ ] **K4.5** SWGDE-compliant crypto report generator
- [ ] **K4.6** Test suite (200+ test cases)

### Fáze K5 — Advanced Features *(re-scoping: po release 2.0, stretch)*
- [ ] **K5.1** DeFi protocol detection (Uniswap, Aave, atd.)
- [ ] **K5.2** NFT ownership tracking
- [ ] **K5.3** Cross-chain bridge analysis
- [ ] **K5.4** Privacy coin analysis (Monero, Zcash) — off-chain evidence only
- [ ] **K5.5** AI-powered krypto copilot (specializované prompty)
- [ ] **K5.6** Test suite (300+ test cases)

---

## ⚠️ SPECIFICKÁ RIZIKA KRYPTO MODULU

| Riziko | Pravděpodobnost | Dopad | Mitigace |
|---|---|---|---|
| False positives u hex strings | Vysoká | Střední | Kontextuální analýza (je to v wallet file? v browser history?) |
| Šifrované wallety nelze parsovat | Vysoká | Střední | Detekovat šifrování, varovat uživatele, nabídnout brute-force (stretch) |
| Blockchain API rate limits | Střední | Vysoký | Cache vrstva, batch requests, fallback na offline mode |
| Nové blockchainy/address formats | Vysoká | Nízký | Plugin architecture pro snadné přidávání nových chainů |
| Privacy coins (Monero) nelze trackovat | Vysoká | Střední | Dokumentovat jako limitaci, focus on off-chain evidence |

---

## 🎯 OKAMŽITÉ AKCE (První 5 úkolů — re-scoped pořadí po F1.2)

1. **K1.1** — BIP39 seed phrase detector (P0)
2. **K1.2** — Private key detector (P0)
3. **K1.3** — Address validator (P0)
4. **K1.4** — Test suite pro K1.1–K1.3 (P0)
5. **K2.2/K2.3** — Electrum + MetaMask detekce (BDB wallet.dat odložit)

---

**Konec krypto modulu.**
*Navrženo jako nezávislá K-linka za F1.2 Memory Forensics a release 2.0.*
