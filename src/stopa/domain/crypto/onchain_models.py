"""K3 On-Chain Analysis — datové modely (offline-first).

Čisté Pydantic v2 modely + struktury pro transakční záznamy, clustery,
risk skóre a transakční graf. Žádné I/O v tomto modulu.

Konvence: čepy v nejmenších jednotkách řetězce (BTC = sats, ETH = wei).
Adresy se normalizují podle řetězců — ETH/BSC hex adresy lowercase
(EIP-55), base58/bech32 se zachovávají literálně (case-sensitive).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TxInput(BaseModel):
    """Vstup transakce. ``address=None`` = coinbase / op_return / neznámý."""

    address: str | None = None
    amount: int = 0


class TxOutput(BaseModel):
    """Výstup transakce (UTXO nebo ETH transfer)."""

    address: str | None = None
    amount: int = 0
    index: int = 0


class TxRecord(BaseModel):
    """Normalizovaný záznam jedné on-chain transakce (K3.1 schéma).

    Schéma je chain-agnostické; ``chain`` je lowercase identifikátor
    (``btc``, ``eth``, …) a částky v nejmenších jednotkách daného řetězce.
    """

    txid: str
    chain: str = "btc"
    timestamp: int | None = None  # unix epoch sekundy, None = neznámá
    inputs: list[TxInput] = Field(default_factory=list)
    outputs: list[TxOutput] = Field(default_factory=list)

    @property
    def total_in(self) -> int:
        return sum(i.amount for i in self.inputs)

    @property
    def total_out(self) -> int:
        return sum(o.amount for o in self.outputs)


class Cluster(BaseModel):
    """K3.2 — cluster adres přiřazených téže entitě (heuristika)."""

    cluster_id: int  # deterministické, pořadí prvního výskytu
    addresses: list[str] = Field(default_factory=list)  # setříděné, unikátní
    reason: str = "common_input"  # common_input | change_detection | mixed
    txids: list[str] = Field(default_factory=list)  # důkaz (omezeno)


class SanctionEntry(BaseModel):
    """K3.4 — položka bundlovaného sankčního seznamu."""

    address: str
    chain: str = "btc"
    entity: str = ""
    program: str = ""
    listed_date: str | None = None
    source: str = ""
    tags: list[str] = Field(default_factory=list)


class RiskScore(BaseModel):
    """K3.4 — deterministické risk skóre jedné adresy (0–100)."""

    address: str
    score: int  # 0..100
    level: str  # none | low | medium | high | critical
    reasons: list[str] = Field(default_factory=list)
    entries: list[SanctionEntry] = Field(default_factory=list)


class GraphEdge(BaseModel):
    """K3.3 — orientovaný hrana grafu (posil od→do, částka)."""

    src: str
    dst: str
    amount: int = 0
    txid: str | None = None


class NodeStats(BaseModel):
    """K3.3 — agregované statistiky uzlu (adresy) v grafu."""

    in_amount: int = 0
    out_amount: int = 0
    tx_in: int = 0
    tx_out: int = 0

    @property
    def balance(self) -> int:
        """Saldo = přijaté − odeslané (negativní = čisté odeslání)."""
        return self.in_amount - self.out_amount


class TxGraph(BaseModel):
    """K3.3 — transakční graf: uzly + orientované hrany."""

    nodes: dict[str, NodeStats] = Field(default_factory=dict)
    edges: list[GraphEdge] = Field(default_factory=list)
