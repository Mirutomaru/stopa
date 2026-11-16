"""K3.2 — Deterministické clustering adres (bez ML, bez sítě).

Dvě standardní forenzní heuristiky:

1. **common-input** (společný vstup): transakce s 2+ vstupy z *různých*
   adres předpokládá, že všechny tyto adresy patří téže entitě — klasická
   „consolidation" detekce. Implementace přes union-find; cluster ID je
   deterministické (pořadí prvního výskytu adres v sekvenci transakcí).

2. **change-detection**: výstup na *známou vlastní* adresu, jehož částka
   přesně odpovídá zbytku (total_in − součet ostatních výstupů), je
   kandidát na change adresu. Podmínky: 2+ různé výstupní adresy a cíl
   není vstupem téže transakce (eliminuje prostý „refund" pattern).

Obě funkce jsou čisté (stejný vstup → stejný výstup, deterministické
seřazení) — AK dle K3.2: *deterministický clustering bez ML*.
"""

from __future__ import annotations

from stopa.domain.crypto.onchain_models import Cluster, TxRecord

#: Maximální počet důkazových txid na cluster (držím artefakty malé).
MAX_EVIDENCE_TXIDS = 50


class _UnionFind:
    """Minimální union-find s path compression — deterministické kořeny."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        root = x
        while self._parent.get(root, root) != root:
            root = self._parent[root]
        while self._parent.get(x, x) != root:  # path compression
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        # deterministický kořen: lexicograficky menší adresa
        if ra < rb:
            self._parent[rb] = ra
        else:
            self._parent[ra] = rb


def cluster_common_input(txs: list[TxRecord]) -> list[Cluster]:
    """Common-input heuristika: vstupy téže transakce → jeden cluster.

    Transakce s <2 různými vstupními adresami nic nepřispěje (coinbase,
    single-input). Výsledek je seřazený podle cluster_id (první výskyt).
    """
    uf = _UnionFind()
    evidence: dict[str, list[str]] = {}  # root -> txids (v pořadí)
    order: list[str] = []  # první výskyt adres v sekvenci

    for tx in txs:
        addrs = [i.address for i in tx.inputs if i.address]
        uniq = sorted(set(addrs))
        if len(uniq) < 2:
            continue
        for a in uniq:
            if a not in order:
                order.append(a)
        # spojit všechny vstupy téže tx do jednoho clusteru
        for a in uniq[1:]:
            uf.union(uniq[0], a)
        # důkaz pod stabilním klíčem: uniq[0] = nejmenší adresa tx,
        # která zůstane členem finálního clusteru (klíč se uniony nemění)
        if tx.txid not in evidence.get(uniq[0], []):
            evidence.setdefault(uniq[0], []).append(tx.txid)

    # seskupit podle finálního kořene (po všech union + path compression)
    groups: dict[str, list[str]] = {}
    for a in order:
        root = uf.find(a)
        groups.setdefault(root, []).append(a)

    ordered_groups = sorted(
        groups.values(), key=lambda m: min(_order_idx(order, x) for x in m)
    )
    clusters: list[Cluster] = []
    for cid, members in enumerate(ordered_groups):
        addrs = sorted(members)
        clusters.append(
            Cluster(
                cluster_id=cid,
                addresses=addrs,
                reason="common_input",
                txids=_evid_for(evidence, members),
            )
        )
    return clusters


def _order_idx(order: list[str], x: str) -> int:
    try:
        return order.index(x)
    except ValueError:
        return len(order)


def _evid_for(evidence: dict[str, list[str]], members: list[str]) -> list[str]:
    """Důkazové txidy clusteru — spojení evidencí všech členů (deterministické)."""
    out: list[str] = []
    seen: set[str] = set()
    for m in sorted(members):
        for t in evidence.get(m, []):
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out[:MAX_EVIDENCE_TXIDS]


def detect_change_addresses(
    txs: list[TxRecord],
    known: set[str],
) -> set[str]:
    """Change-detection heuristika nad známými vlastními adresami.

    Vrátí množinu adres z ``known``, které se chovají jako change výstupy.
    Deterministické; bez ML (AK K3.2).
    """
    changes: set[str] = set()
    for tx in txs:
        out_addrs = [o.address for o in tx.outputs if o.address]
        uniq_outs = set(out_addrs)
        if len(uniq_outs) < 2:
            continue
        inputs = {i.address for i in tx.inputs if i.address}
        total_in = tx.total_in
        if total_in <= 0:
            continue
        for o in tx.outputs:
            if not o.address or o.address not in known:
                continue
            if o.address in inputs:
                continue  # vstup→výstup téže tx není change signatura
            rest = sum(x.amount for x in tx.outputs if x is not o)
            if o.amount == total_in - rest and o.amount > 0:
                changes.add(o.address)
    return changes


def cluster_addresses(
    txs: list[TxRecord],
    seed: set[str] | None = None,
) -> list[Cluster]:
    """Kombinuje common-input + change-detection do jednoho výstupu.

    ``seed`` = známo vlastní adresy (pro change detekci). Change-only
    cluster vznikne pouze pro adresu, která už není v žádném common-input
    clusteru; jinak se reason doplní na ``mixed`` a adresa přidá do
    existujícího clusteru. Výsledek deterministicky seřazený.
    """
    clusters = cluster_common_input(txs)
    by_addr: dict[str, Cluster] = {a: c for c in clusters for a in c.addresses}

    changes = detect_change_addresses(txs, seed or set())
    for addr in sorted(changes):
        existing = by_addr.get(addr)
        if existing is not None:
            if existing.reason == "common_input":
                existing.reason = "mixed"
            continue
        cid = len(clusters)
        clusters.append(
            Cluster(cluster_id=cid, addresses=[addr], reason="change_detection")
        )
        by_addr[addr] = clusters[-1]

    for c in clusters:  # stabilní ID po doplnění
        c.addresses = sorted(c.addresses)
    return clusters
