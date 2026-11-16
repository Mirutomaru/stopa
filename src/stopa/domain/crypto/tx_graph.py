"""K3.3 — Transakční graf + detekce cyklů (offline, deterministické).

Graf se staví z normalizovaných ``TxRecord``: uzel = adresa, orientovaná
hrana = posil (src→dst) s částkou a txid. Agregace na uzlech (přijaté /
odeslané / saldo) slouží pro rychlou identifikaci „horkých" adres.

AK dle K3.3: *graf transakcí s detekcí cyklů*. DFS expanze drží visited
množinu → cykly nemohou způsobit nekonečnou smyčku; pořadí sousedů je
deterministické (lexikograficky seřazené).
"""

from __future__ import annotations

import json
from collections import defaultdict

from stopa.domain.crypto.onchain_models import GraphEdge, NodeStats, TxGraph, TxRecord


def build_graph(txs: list[TxRecord]) -> TxGraph:
    """Sestaví transakční graf z normalizovaných záznamů.

    Uzel = adresa (``None`` — coinbase/op_return — se nepočítá).
    Node statistiky jsou přesné; **částka hrany** je poměrný odhad:
    ``output.amount * input.amount / total_in`` (pro single-input tx =
    celá částka výstupu). Deterministické zaokrouhlení dolů.
    """
    stats: dict[str, NodeStats] = defaultdict(NodeStats)
    edges: list[GraphEdge] = []
    edge_index: dict[tuple[str, str], GraphEdge] = {}

    def node(addr: str) -> NodeStats:
        return stats.setdefault(addr, NodeStats())

    for tx in txs:
        known_inputs = [(i.address, i.amount) for i in tx.inputs if i.address]
        total_in = sum(amt for _, amt in known_inputs)
        outputs_known = [(o.address, o.amount) for o in tx.outputs if o.address]

        for addr, amt in outputs_known:
            node(addr).in_amount += amt
            node(addr).tx_in += 1

        for i_addr, i_amt in known_inputs:
            a = node(i_addr)
            a.out_amount += i_amt
            a.tx_out += 1
            if not total_in or not outputs_known:
                continue
            for o_addr, o_amt in outputs_known:
                share = (o_amt * i_amt) // total_in
                key = (i_addr, o_addr)
                edge = edge_index.get(key)
                if edge is None:
                    edge = GraphEdge(src=i_addr, dst=o_addr, amount=0, txid=tx.txid)
                    edge_index[key] = edge
                    edges.append(edge)
                edge.amount += share

    return TxGraph(nodes=dict(stats), edges=edges)


def expand_paths(
    graph: TxGraph,
    start: str,
    depth: int = 3,
) -> list[list[str]]:
    """Všechny cesty z ``start`` do hloubky ``depth`` (DFS + cycle guard).

    Deterministické: sousedé se navštěvují v lexikografickém pořadí.
    Cesta obsahuje start i cíl; ``depth=1`` = přímí příjemci.
    """
    if depth < 1 or start not in graph.nodes:
        return []
    adj: dict[str, list[str]] = defaultdict(list)
    for e in graph.edges:
        adj[e.src].append(e.dst)
    for k in tuple(adj):
        adj[k] = sorted(set(adj[k]))

    paths: list[list[str]] = []
    stack: list[tuple[str, list[str], set[str]]] = [(start, [start], {start})]
    while stack:
        cur, path, visited = stack.pop()
        if len(path) - 1 >= depth:
            continue
        for nxt in adj.get(cur, []):
            new_path = path + [nxt]
            paths.append(new_path)
            if nxt not in visited and len(new_path) - 1 < depth:
                stack.append((nxt, new_path, visited | {nxt}))
    return sorted(paths)


def detect_cycles(graph: TxGraph, max_len: int = 6) -> list[list[str]]:
    """Detekce cyklů (self-loop i delší) — AK K3.3.

    Vrátí seřazené cykly jako seznamy adres (start = lexikograficky
    nejmenší adresa cyklu, bez opakovaného startu na konci). Omezeno na
    délku ``max_len`` pro deterministickou omezenou DFS.
    """
    adj: dict[str, list[str]] = defaultdict(list)
    for e in graph.edges:
        adj[e.src].append(e.dst)
    nodes = sorted(set(adj) | set(graph.nodes))

    cycles: set[tuple[str, ...]] = set()
    # explicitní self-loopy (X→X)
    for n in nodes:
        if n in adj.get(n, []):
            cycles.add((n,))

    def canonical(path: list[str]) -> tuple[str, ...]:
        """Rotace tak, aby cyklus startoval lexikograficky nejmenší adresou."""
        m = min(range(len(path)), key=lambda i: path[i])
        return tuple(path[m:] + path[:m])

    for start in nodes:
        stack: list[list[str]] = [[start]]
        while stack:
            path = stack.pop()
            cur = path[-1]
            if len(path) > max_len:
                continue
            for nxt in sorted(set(adj.get(cur, []))):
                if nxt == start and len(path) >= 2:
                    cycles.add(canonical(path))  # uzavřený cyklus od startu
                elif nxt not in path:
                    stack.append(path + [nxt])

    return [list(c) for c in sorted(cycles)]


def top_senders(graph: TxGraph, n: int = 10) -> list[tuple[str, int]]:
    """Top-N odesílatelů podle odeslané částky (tie-break: adresa vzestupně)."""
    items = [(a, s.out_amount) for a, s in graph.nodes.items()]
    return sorted(items, key=lambda x: (-x[1], x[0]))[:n]


def top_recipients(graph: TxGraph, n: int = 10) -> list[tuple[str, int]]:
    """Top-N příjemců podle přijaté částky (tie-break: adresa vzestupně)."""
    items = [(a, s.in_amount) for a, s in graph.nodes.items()]
    return sorted(items, key=lambda x: (-x[1], x[0]))[:n]


def to_json_dict(graph: TxGraph) -> dict:
    """JSON-safe reprezentace grafu pro reporty (bez cyklických odkazů)."""
    return {
        "nodes": {
            a: {
                "in_amount": s.in_amount,
                "out_amount": s.out_amount,
                "balance": s.balance,
                "tx_in": s.tx_in,
                "tx_out": s.tx_out,
            }
            for a, s in sorted(graph.nodes.items())
        },
        "edges": [e.model_dump() for e in graph.edges],
    }


def to_mermaid(graph: TxGraph) -> str:
    """Mermaid `graph LR` export pro offline vizualizaci (AK K3.3)."""
    lines = ["graph LR"]
    used_ids: dict[str, int] = {}

    def node_id(addr: str) -> str:
        i = used_ids.get(addr)
        if i is None:
            i = len(used_ids)
            used_ids[addr] = i
        return f"n{i}"

    for e in graph.edges:
        sid, did = node_id(e.src), node_id(e.dst)
        lines.append(f'  {sid}["{e.src[:12]}…"] -->|"{e.amount}"| {did}["{e.dst[:12]}…"]')
    return "\n".join(lines)


def graph_to_json(graph: TxGraph, **extra) -> str:
    """Serializace grafu do JSON string (deterministické klíče)."""
    data = to_json_dict(graph)
    data.update(extra)
    return json.dumps(data, indent=2, sort_keys=True)
