"""CLI — reporty a analytické rodiny (profiles, report, onchain, darkweb, crypto-report, advanced).

P1-4 (refaktor god-file ``cli.py``): přesunuto bez změny chování;
facade ``stopa.cli`` re-exportuje implementace pro kompatibilitu.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from stopa.domain.profiles import PROFILES

from .._util import _db_dir, _open_db, _print_json


def cmd_profiles(args: argparse.Namespace) -> int:
    if getattr(args, "json", False):
        _print_json({
            name: {
                "compute_md5": p.compute_md5,
                "compute_sha1": p.compute_sha1,
                "compute_sha256": p.compute_sha256,
                "signature_analysis": bool(p.signature_analysis),
                "flag_bad_extensions": bool(p.flag_bad_extensions),
                "deduplicate": bool(p.deduplicate),
            }
            for name, p in sorted(PROFILES.items())
        })
        return 0
    print("Dostupné processing profily:")
    for name, p in sorted(PROFILES.items()):
        algs = "+".join(
            a for a, on in (("MD5", p.compute_md5), ("SHA1", p.compute_sha1), ("SHA256", p.compute_sha256)) if on
        ) or "—"
        print(f"  {name:10} hash={algs:8} signatury={'✓' if p.signature_analysis else '—'} "
              f"bad-ext={'✓' if p.flag_bad_extensions else '—'} dedupe={'✓' if p.deduplicate else '—'}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Forenzní report (FÁZE 7) — court-ready HTML/PDF + chain of custody."""
    from stopa.presentation.case_report import (
        default_report_name,
        generate_html_report,
        generate_pdf_report,
    )

    db = _open_db(args.case_id)
    out_dir = Path(args.out).expanduser() if args.out else _db_dir().parent / "reports"
    fmt = args.format
    lang = getattr(args, "lang", None)  # E10 i18n — výchozí cs řeší report vrstva
    try:
        if fmt == "pdf":
            path = generate_pdf_report(
                db, args.case_id, out_dir / default_report_name(args.case_id, "pdf"), lang=lang
            )
        else:
            path = generate_html_report(
                db, args.case_id, out_dir / default_report_name(args.case_id, "html"), lang=lang
            )
    except RuntimeError as e:
        if getattr(args, "json", False):
            _print_json({"error": str(e), "case_id": args.case_id})
        else:
            print(f"Report selhal: {e}", file=sys.stderr)
        db.close()
        return 2
    db.close()
    if getattr(args, "json", False):
        _print_json({"path": str(path), "format": fmt, "case_id": args.case_id})
        return 0
    print(f"Report vygenerován ({fmt.upper()}): {path}")
    return 0


_K3_CHAIN_MAP = {
    "bitcoin": "btc", "btc": "btc", "bitcoin-cash": "btc",
    "ethereum": "eth", "eth": "eth", "bsc": "eth", "polygon": "eth",
}


def _k3_norm_chain(chain: str | None) -> str:
    return _K3_CHAIN_MAP.get((chain or "").lower(), "unknown")


def cmd_onchain(args: argparse.Namespace) -> int:
    """K3 On-chain analýza — clustering + graf transakcí + risk scoring (offline-first).

    Vstup: adresy extrahované z crypto artefaktů případu. Síť je opt-in
    (--api-key / --etherscan-key); jinak jen bundlované sankční listy + cache.
    """
    from stopa.domain.crypto.clustering import cluster_common_input, detect_change_addresses
    from stopa.domain.crypto.onchain_api import (
        BlockchairClient,
        EtherscanClient,
        OnchainApiError,
        TxCache,
    )
    from stopa.domain.crypto.risk_scoring import score_addresses as k3_score
    from stopa.domain.crypto.tx_graph import (
        build_graph,
        detect_cycles,
        expand_paths,
        top_recipients,
        top_senders,
    )

    db = _open_db(args.case_id)
    try:
        # 1) sběr adres z crypto artefaktů (value → chain; první detekce má přednost)
        addrs: dict[str, str] = {}
        for atype in ("crypto_detection", "crypto_wallet"):
            for art in db.list_artifacts(artifact_type=atype):
                d = art.details or {}
                for a in d.get("addresses") or []:  # AddressValidation dump
                    if not isinstance(a, dict):
                        continue
                    v = (a.get("raw_value") or "").strip()
                    if v and v not in addrs:
                        addrs[v] = _k3_norm_chain(a.get("chain"))
                for w in d.get("wallets") or []:  # WalletDetection dump
                    for v in w.get("public_addresses") or []:
                        if isinstance(v, str) and v.strip() and v not in addrs:
                            addrs[v] = "unknown"

        # 2) risk scoring — bundlované OFAC/EU listy (offline, deterministické)
        scores = k3_score(list(addrs))

        # 3) transakce: cache + volitelná síť
        cache_path = _db_dir() / f"{args.case_id}.txcache.json"
        cache = TxCache(cache_path)
        txs_by_addr = cache.load() or {}
        warnings: list[str] = []

        clients: dict[str, object] = {}
        if not args.no_network and args.api_key:
            try:
                clients["btc"] = BlockchairClient(args.api_key)
            except OnchainApiError as exc:
                warnings.append(f"blockchair: {exc}")
        if not args.no_network and getattr(args, "etherscan_key", None):
            try:
                clients["eth"] = EtherscanClient(args.etherscan_key)
            except OnchainApiError as exc:
                warnings.append(f"etherscan: {exc}")

        for addr in sorted(addrs):
            if addr in txs_by_addr:
                continue  # cache hit — offline-first
            chain = addrs[addr]
            client = clients.get(chain)
            if client is None:
                continue  # bez klienta (nebo neznámý chain) zůstáváme offline
            try:
                txs_by_addr[addr] = client.fetch_address_txs(addr)  # type: ignore[union-attr]
            except OnchainApiError as exc:
                warnings.append(f"{addr[:16]}…: {exc}")

        if clients and not args.no_network:
            try:
                cache.save(txs_by_addr)
            except OnchainApiError as exc:
                warnings.append(str(exc))

        all_txs = list({t.txid: t for tx_list in txs_by_addr.values() for t in tx_list}.values())

        # 4) clustering + graf (jen pokud jsou transakce k dispozici)
        clusters_out: list[dict] = []
        graph_out: dict | None = None
        cycles: list[list[str]] = []
        paths_from_risk: dict[str, list[list[str]]] = {}
        change: set[str] = set()

        if all_txs:
            clusters = cluster_common_input(all_txs)
            own_all = set(addrs)  # všechny adresy případu = „vlastní" pro change-detekci
            change = detect_change_addresses(all_txs, own_all)
            ranked = sorted(
                clusters, key=lambda c: (-len(c.addresses), c.cluster_id)
            )[:50]
            clusters_out = [c.model_dump() for c in ranked]

            graph = build_graph(all_txs)
            cycles = detect_cycles(graph, max_len=4)
            risky = [a for a in sorted(addrs) if scores[a].level in ("high", "critical")]
            for a in risky:
                paths_from_risk[a] = expand_paths(graph, a, depth=args.depth)[:20]

            graph_out = {
                "nodes_total": len(graph.nodes),
                "edges_total": len(graph.edges),
                "top_senders": [list(x) for x in top_senders(graph)],
                "top_recipients": [list(x) for x in top_recipients(graph)],
            }

        result = {
            "case_id": args.case_id,
            "addresses_total": len(addrs),
            "address_scores": [
                {
                    "address": a,
                    "chain": addrs[a],
                    "score": scores[a].score,
                    "level": scores[a].level,
                    "reasons": scores[a].reasons,
                }
                for a in sorted(addrs)
            ],
            "high_risk_count": sum(1 for s in scores.values() if s.level in ("high", "critical")),
            "transactions_loaded": len(all_txs),
            "clusters": clusters_out,
            "change_addresses": sorted(change) if all_txs else [],
            "graph": graph_out,
            "cycles": cycles,
            "paths_from_risk": paths_from_risk,
            "cache_path": str(cache_path),
            "cache_last_error": cache.last_error,
            "warnings": warnings,
        }

        if getattr(args, "json", False):
            _print_json(result)
            return 0

        print(f"K3 on-chain: {args.case_id}")
        print(f"  adres v případě: {len(addrs)} (high/critical: {result['high_risk_count']})")
        for a in sorted(addrs):
            s = scores[a]
            if s.level != "none":
                print(f"  [{s.level}] {a} — score={s.score}")
                for r in s.reasons[:2]:
                    print(f"      {r}")
        if all_txs:
            print(f"  transakcí načteno: {len(all_txs)} (cache: {cache_path})")
            print(f"  clusterů: {len(clusters_out)}, cyklů: {len(cycles)}")
            for c in clusters_out[:10]:
                print(f"    C{c['cluster_id']}: {', '.join(c['addresses'])} [{'; '.join(c['txids'][:3])}]")
        else:
            print("  transakce bez cache/sítě — clustering nebyl proveden (offline scoring OK)")
        for w in warnings:
            print(f"  warning: {w}", file=sys.stderr)
        return 0
    finally:
        db.close()


def cmd_darkweb(args: argparse.Namespace) -> int:
    """K4 Dark Web & Illicit Activity — ransom note + marketplace + mixer detektory.

    Skenuje textové soubory zdrojů případu (kind=file, podporované extenze,
    ≤ 4 MB); výsledek = ransom note šablony, marketplace důkazy a zmínky mixerů.
    """
    from stopa.domain.crypto.darkweb import (
        detect_marketplace_data,
        detect_mixer_mentions,
        detect_ransom_note,
    )

    _text_exts = {".txt", ".md", ".log", ".html", ".htm", ".csv"}
    max_bytes = 4 * 1024 * 1024

    db = _open_db(args.case_id)
    try:
        files_to_scan: list[tuple[str, str]] = []  # (label, abspath)
        if args.file:
            for p in args.file:
                files_to_scan.append((p, os.path.abspath(p)))
        else:
            for src in db.list_sources(args.case_id):
                if src.kind != "file":
                    continue
                ap = os.path.abspath(src.path)
                ext = os.path.splitext(ap)[1].lower()
                if ext not in _text_exts or not os.path.isfile(ap):
                    continue
                try:
                    if os.path.getsize(ap) > max_bytes:
                        continue
                except OSError:
                    continue
                files_to_scan.append((src.id, ap))

        notes_found: list[dict] = []
        marketplace_found: list[dict] = []
        mixer_mentions: set[str] = set()
        scanned: list[str] = []
        for label, path in sorted(files_to_scan):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read(max_bytes)
            except OSError as exc:
                print(f"  warning: {path}: {exc}", file=sys.stderr)
                continue
            scanned.append(label)
            rn = detect_ransom_note(text)
            if rn.is_ransom_note:
                notes_found.append(
                    {"file": label, **rn.model_dump()}
                )
            mp = detect_marketplace_data(text)
            if mp.is_marketplace:
                marketplace_found.append({"file": label, **mp.model_dump()})
            mixer_mentions.update(detect_mixer_mentions(text))

        result = {
            "case_id": args.case_id,
            "files_scanned": len(scanned),
            "ransom_notes": notes_found,
            "marketplace_evidence": marketplace_found,
            "mixer_mentions": sorted(mixer_mentions),
        }
        if getattr(args, "json", False):
            _print_json(result)
            return 0

        print(f"K4 dark web: {args.case_id} (naskenováno souborů: {len(scanned)})")
        for n in notes_found:
            fam = f" [{n['family']}]" if n["family"] else ""
            print(
                f"  RANSOM NOTE → {n['file']}{fam} "
                f"(score={n['score']}, adresy={len(n['addresses'])})"
            )
            for a in n["addresses"]:
                print(f"    - {a}")
        for m in marketplace_found:
            print(
                f"  MARKETPLACE → {m['file']} (score={m['score']}, "
                f"pgp={m['pgp_keys']}, adresy={len(m['addresses'])})"
            )
            for a in m["addresses"]:
                print(f"    - {a}")
        if mixer_mentions:
            print(f"  MIXER ZMÍNKY: {', '.join(sorted(mixer_mentions))}")
        if not notes_found and not marketplace_found and not mixer_mentions:
            print("  žádné ransom/marketplace/mixer indikátory nenalezeny")
        return 0
    finally:
        db.close()


def cmd_crypto_report(args: argparse.Namespace) -> int:
    """K4.5 — SWGDE krypto report (10 sekcí, md|html|json, Ed25519 podpis)."""
    from stopa.domain.crypto.onchain_api import TxCache
    from stopa.presentation.crypto_report import generate_crypto_report

    db = _open_db(args.case_id)
    try:
        # on-chain TX z K3 cache (pokud existuje) → timeline + fund-flow sekce
        txs_by_addr: dict[str, list] | None = None
        cache_path = _db_dir() / f"{args.case_id}.txcache.json"
        if cache_path.exists():
            try:
                cache = TxCache(cache_path)
                txs_by_addr = cache.load() or None
            except Exception as exc:  # noqa: BLE001 — report jde i bez cache
                print(f"  warning: TxCache {cache_path}: {exc}", file=sys.stderr)

        out: Path | None = None
        if args.out:
            out = Path(args.out).expanduser().resolve()
        else:
            default_name = f"crypto_report.{args.format}"
            out = (_db_dir() / "reports" / f"{args.case_id}.{default_name}")

        res = generate_crypto_report(
            db, args.case_id, args.format, out=out, txs_by_addr=txs_by_addr
        )
        if getattr(args, "json", False):
            payload = {k: v for k, v in res.model_dump().items() if k != "content"}
            payload["out"] = str(out)
            _print_json(payload)
            return 0

        print(f"K4.5 SWGDE report: {args.case_id} [{res.format}]")
        for k, v in sorted(res.stats.items()):
            print(f"  {k}: {v}")
        if res.sha256_hex:
            print(f"  sha256: {res.sha256_hex[:16]}…")
        print(f"  podpis: {'Ed25519 OK' if res.signature_b64 else 'nepodepsán (graceful)'}")
        print(f"  → {out}")
        return 0
    finally:
        db.close()


def cmd_advanced(args: argparse.Namespace) -> int:
    """K5 Advanced — DeFi + NFT + cross-chain bridge + privacy coins (+ copilot).

    Skenuje textové soubory zdrojů případu (jako K4 darkweb); cross-chain analýza
    běží nad K3 TxCache (pokud existuje); AI copilot = deterministický fallback
    (LLM v CLI bez explicitního klíče nevolejeme).
    """
    from stopa.domain.crypto.bridges import analyze_cross_chain, detect_bridge_in_text
    from stopa.domain.crypto.defi import detect_defi_in_text
    from stopa.domain.crypto.nft import detect_nft_in_text
    from stopa.domain.crypto.onchain_api import TxCache
    from stopa.domain.crypto.privacy_coins import detect_privacy_in_text
    from stopa.intelligence.crypto_copilot import run_crypto_copilot

    _text_exts = {".txt", ".md", ".log", ".html", ".htm", ".csv"}
    max_bytes = 4 * 1024 * 1024

    db = _open_db(args.case_id)
    try:
        files_to_scan: list[tuple[str, str]] = []
        if args.file:
            for p in args.file:
                files_to_scan.append((p, os.path.abspath(p)))
        else:
            for src in db.list_sources(args.case_id):
                if src.kind != "file":
                    continue
                ap = os.path.abspath(src.path)
                ext = os.path.splitext(ap)[1].lower()
                if ext not in _text_exts or not os.path.isfile(ap):
                    continue
                try:
                    if os.path.getsize(ap) > max_bytes:
                        continue
                except OSError:
                    continue
                files_to_scan.append((src.id, ap))

        defi_findings = []
        nft_findings = []
        bridge_mentions = []
        privacy_findings = []
        scanned: list[str] = []
        for label, path in sorted(files_to_scan):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read(max_bytes)
            except OSError as exc:
                print(f"  warning: {path}: {exc}", file=sys.stderr)
                continue
            scanned.append(label)
            defi_findings.extend(detect_defi_in_text(text, origin=label))
            nf = detect_nft_in_text(text, origin=label)
            if nf is not None:
                nft_findings.append(nf.model_dump())
            bf = detect_bridge_in_text(text, origin=label)
            if bf is not None:
                bridge_mentions.append(bf.model_dump())
            privacy_findings.extend(detect_privacy_in_text(text, origin=label))

        # cross-chain analýza nad K3 TxCache (adresy per chain)
        per_chain: dict[str, set[str]] = {}
        cache_path = _db_dir() / f"{args.case_id}.txcache.json"
        if cache_path.exists():
            try:
                txs_by_addr = TxCache(cache_path).load() or {}
                for addr, txs in txs_by_addr.items():
                    for t in txs:
                        per_chain.setdefault(t.chain.lower(), set()).add(addr)
            except Exception as exc:  # noqa: BLE001 — jde i bez cache
                print(f"  warning: TxCache {cache_path}: {exc}", file=sys.stderr)
        bridge_links = analyze_cross_chain({c: sorted(a) for c, a in per_chain.items()})

        # kritické sankční shody z K3 (adresy crypto artefaktů) — pro copilota
        critical_sanctions = 0
        from stopa.domain.crypto.risk_scoring import score_addresses as k3_score

        addrs: set[str] = set()
        for art in db.list_artifacts(artifact_type="crypto_detection"):
            d = art.details or {}
            for a in d.get("addresses") or []:
                if isinstance(a, dict) and (a.get("raw_value") or "").strip():
                    addrs.add((a["raw_value"] or "").strip())
        if addrs:
            critical_sanctions = sum(1 for sc in k3_score(sorted(addrs)).values() if sc.score >= 100)

        summary = {
            "case_id": args.case_id,
            "defi_findings": len(defi_findings),
            "nft_findings": len(nft_findings),
            "bridge_links": len(bridge_links),
            "privacy_findings": len(privacy_findings),
            "critical_sanctions": critical_sanctions,
        }
        copilot = run_crypto_copilot(None, summary)

        result = {
            "case_id": args.case_id,
            "files_scanned": len(scanned),
            "defi_findings": [f.model_dump() for f in defi_findings],
            "nft_findings": nft_findings,
            "bridge_text_mentions": bridge_mentions,
            "cross_chain_links": [l.model_dump() for l in bridge_links],
            "privacy_findings": [f.model_dump() for f in privacy_findings],
            "copilot": copilot.to_dict(),
        }
        if getattr(args, "json", False):
            _print_json(result)
            return 0

        print(f"K5 advanced: {args.case_id} (naskenováno souborů: {len(scanned)})")
        for f in defi_findings:
            terms = ", ".join(f.matched_terms) or "—"
            addrs_txt = f", adresy={', '.join(f.matched_addresses)}" if f.matched_addresses else ""
            print(
                f"  DEFI → {f.protocol} [{f.origin}] (score={f.score}, termíny: {terms}{addrs_txt})"
            )
        for nf in nft_findings:
            coll = ", ".join(nf["collections"]) or "—"
            mkt = ", ".join(nf["marketplaces"]) or "—"
            tids = ",".join(str(t) for t in nf["token_ids"]) or "—"
            print(
                f"  NFT → [{nf['origin']}] (score={nf['score']}, sbírky: {coll}, "
                f"marketplaces: {mkt}, token_id: {tids})"
            )
        for bf in bridge_mentions:
            print(f"  BRIDGE TEXT → [{bf['origin']}]: {', '.join(bf['bridges'])}")
        for l in bridge_links:
            bn = f" ({l.bridge_name})" if l.bridge_name else ""
            print(
                f"  CROSS-CHAIN LINK → {l.entity} chains={','.join(l.chains)} "
                f"[{l.evidence}{bn}]"
            )
        for pf in privacy_findings:
            val = pf.value if pf.evidence_kind != "text_term" else ""
            print(
                f"  PRIVACY → {pf.coin}:{pf.evidence_kind}"
                + (f" {val}" if val else "")
                + f" [{pf.origin}]"
            )
        c = copilot.to_dict()
        print(f"  COPILOT: risk={c['risk_level']} (source={c['source']})")
        for kf in c["key_findings"]:
            print(f"    - {kf}")
        if not defi_findings and not nft_findings and not bridge_mentions \
                and not bridge_links and not privacy_findings:
            print("  žádné K5 indikátory nenalezeny")
        return 0
    finally:
        db.close()


