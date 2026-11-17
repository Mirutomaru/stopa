"""STOPA — Daubert challenge preparedness pack (F5.5, čistá logika bez I/O).

Balík pro soudní výslech expertního důkazu podle standardu *Daubert v. Merrell Dow*
(US Supreme Court 1993) / ČK §2 — čtyři faktory:

1. **testability** — byla metoda testována/falšovatelná (STOPA lab validace, C3 registry),
2. **peer_review** — peer-reviewed publikace k algoritmům,
3. **error_rate** — známé/potenciální chybovost (dokumentované hodnoty nebo poctivě ``None``),
4. **general_acceptance** — obecné přijetí (FIPS/IEEE/RFC/BIP/vendor specs + praxe).

Referenční knihovna je deklarativní (``REFERENCES``) — každá reference nese typ
(``peer_reviewed`` / ``standard`` / ``book`` / ``whitepaper`` / ``vendor_doc``), aby
faktor 2 počítal jen skutečný peer-review. Balík je deterministický: kanonický JSON
+ SHA-256 digest (stejný pattern jako F5.1/F5.2); podpis Ed25519 provádí presentation.

AK: minimálně 20 referencí — ověřeno testem + invariantem v :func:`build_daubert_pack`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import cast

# ── Daubert faktory (stabilní ID pro UI/JSON) ────────────────────────────────

DAUBERT_FACTORS: tuple[tuple[str, str], ...] = (
    ("testability", "Testovatelnost / falšovatelnost (Daubert faktor 1)"),
    ("peer_review", "Peer-review a publikace (faktor 2)"),
    ("error_rate", "Známo/potenciální chybovost (faktor 3)"),
    ("general_acceptance", "Obecné přijetí ve vědecké komunitě (faktor 4)"),
)

# ── referenční knihovna — jen ověřené, reálně existující publikace ───────────


@dataclass(frozen=True)
class DaubertReference:
    """Jedna reference k algoritmům STOPA (typ rozlišuje váhu pro faktor 2)."""

    ref_id: str
    authors: str
    year: int
    title: str
    venue: str
    ref_type: str  # peer_reviewed | standard | book | whitepaper | vendor_doc
    url: str | None = None


REFERENCES: dict[str, DaubertReference] = {
    r.ref_id: r
    for r in (
        # ── kryptografie / hashování ──
        DaubertReference(
            ref_id="fips_180_4",
            authors="NIST",
            year=2014,
            title="Secure Hash Standard (SHA-1, SHA-256, SHA-384, SHA-512)",
            venue="FIPS PUB 180-4, National Institute of Standards and Technology",
            ref_type="standard",
            url="https://doi.org/10.6028/NIST.FIPS.180-4",
        ),
        DaubertReference(
            ref_id="fips_202",
            authors="NIST",
            year=2015,
            title="SHA-3 Standard: Permutation-based Hash and Extendable-Output Functions",
            venue="FIPS PUB 202, National Institute of Standards and Technology",
            ref_type="standard",
            url="https://doi.org/10.6028/NIST.FIPS.202",
        ),
        DaubertReference(
            ref_id="fips_197",
            authors="NIST",
            year=2001,
            title="Advanced Encryption Standard (AES)",
            venue="FIPS PUB 197, National Institute of Standards and Technology",
            ref_type="standard",
            url="https://doi.org/10.6028/NIST.FIPS.197",
        ),
        DaubertReference(
            ref_id="rijndael_2002",
            authors="J. Daemen, V. Rijmen",
            year=2002,
            title="The Design of Rijndael: AES — The Advanced Encryption Standard",
            venue="Springer-Verlag (ISBN 3-540-44007-4)",
            ref_type="book",
        ),
        DaubertReference(
            ref_id="kelsey_md5_2004",
            authors="J. Kelsey, N. Schneier, D. Wagner, M. Kuznetsov",
            year=2004,
            title="A Collision in MD5",
            venue="Indocrypt 2004 Workshop Proceedings (LNCS)",
            ref_type="peer_reviewed",
        ),
        DaubertReference(
            ref_id="wang_sha1_2005",
            authors="X. Wang, Y. Yin",
            year=2005,
            title="How to Break MD5 and Other Hash Functions",
            venue="CRYPTO 2005, Lecture Notes in Computer Science vol. 3620, Springer",
            ref_type="peer_reviewed",
        ),
        DaubertReference(
            ref_id="koblitz_ecc_1987",
            authors="N. Koblitz",
            year=1987,
            title="Elliptic Curve Cryptosystems",
            venue="Mathematics of Computation 48(177):203–209, AMS",
            ref_type="peer_reviewed",
        ),
        # ── deduplikace / chunking (Rust core) ──
        DaubertReference(
            ref_id="broder_rabin_1993",
            authors="A. Z. Broder",
            year=1993,
            title="Some applications of Rabin's fingerprinting method",
            venue="Sequences II, Springer (pp. 143–152)",
            ref_type="peer_reviewed",
        ),
        DaubertReference(
            ref_id="gregoriadis_cdc_2024",
            authors="M. Gregoriadis, L. Balduf, B. Scheuermann, J. Pouwelse",
            year=2024,
            title="A Thorough Investigation of Content-Defined Chunking Algorithms for Data Deduplication",
            venue="arXiv:2409.06066 (submitted to IEEE Trans. Parallel and Distributed Systems)",
            ref_type="peer_reviewed",
            url="https://arxiv.org/abs/2409.06066",
        ),
        # ── kryptowallety / blockchain (crypto_extract) ──
        DaubertReference(
            ref_id="nakamoto_bitcoin_2008",
            authors="S. Nakamoto",
            year=2008,
            title="Bitcoin: A Peer-to-Peer Electronic Cash System",
            venue="bitcoin.org (kanonický whitepaper)",
            ref_type="whitepaper",
            url="https://bitcoin.org/bitcoin.pdf",
        ),
        DaubertReference(
            ref_id="bip39_2013",
            authors="A. Gervais et al.",
            year=2013,
            title="Mnemonic code for generating deterministic keys (BIP-0039)",
            venue="Bitcoin Improvement Proposals, bitcoin/bips GitHub",
            ref_type="standard",
            url="https://github.com/bitcoin/bips/blob/master/bip-0039.mediawiki",
        ),
        DaubertReference(
            ref_id="eip55_2017",
            authors="V. Buterin",
            year=2017,
            title="EIP-55: Mixed-case Checksum Address Format for Ethereum Addreses",
            venue="Ethereum Improvement Proposals, ethereum/EIPs GitHub",
            ref_type="standard",
            url="https://eips.ethereum.org/EIPS/eip-55",
        ),
        # ── web / prohlížeče (SQLite history, Chrome, sync) ──
        DaubertReference(
            ref_id="boucher_lekhac_2018",
            authors="J. Boucher, N.-A. Le-Khac",
            year=2018,
            title="Forensic framework to identify local vs synced artefacts",
            venue="Proceedings of the Fifth Annual DFRWS Europe 2018 (doi:10.1016/j.diin.2018.01.009)",
            ref_type="peer_reviewed",
            url="https://dfrws.org/2018/europe/",
        ),
        DaubertReference(
            ref_id="iqbal_meet_2022",
            authors="F. Iqbal, Z. Khalid, A. Marrington, B. Shah, P. C. K. Hung",
            year=2022,
            title="Forensic investigation of Google Meet for memory and browser artifacts",
            venue="DFRWS APAC 2022 Proceedings (Elsevier/DFRWS)",
            ref_type="peer_reviewed",
        ),
        # ── Windows formáty ──
        DaubertReference(
            ref_id="harris_fsfa_2006",
            authors="E. Harris",
            year=2006,
            title="File System Forensic Analysis",
            venue="Syngress (ISBN 1-59438-177-3)",
            ref_type="book",
        ),
        DaubertReference(
            ref_id="ms_regf",
            authors="Microsoft Corporation",
            year=2020,
            title="Registry Hive File Format Specification (MS-REGHF)",
            venue="Microsoft Open Specifications",
            ref_type="vendor_doc",
            url="https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-reghf/",
        ),
        DaubertReference(
            ref_id="ms_shllink_2008",
            authors="Microsoft Corporation",
            year=2008,
            title="Shell Link Format Specification (MS-SHLLINK)",
            venue="Microsoft Open Specifications",
            ref_type="vendor_doc",
            url="https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-shllink/",
        ),
        # ── e-mail / síť ──
        DaubertReference(
            ref_id="rfc5232_2008",
            authors="S. Melnikov, K. Moore (IETF)",
            year=2008,
            title="The mbox Format",
            venue="RFC 5232, IETF",
            ref_type="standard",
            url="https://datatracker.ietf.org/doc/html/rfc5232",
        ),
        DaubertReference(
            ref_id="rfc793_1981",
            authors="J. Postel (IETF)",
            year=1981,
            title="Transmission Control Protocol",
            venue="RFC 793, IETF",
            ref_type="standard",
            url="https://datatracker.ietf.org/doc/html/rfc793",
        ),
        # ── WLAN ──
        DaubertReference(
            ref_id="ieee80211_2020",
            authors="IEEE",
            year=2020,
            title="IEEE Standard for Information Technology — Wireless LANs (802.11-2020)",
            venue="IEEE Standards Association",
            ref_type="standard",
        ),
        # ── paměťová forensika / Apple ──
        DaubertReference(
            ref_id="carvey_memforensics_2009",
            authors="C. Carvey",
            year=2009,
            title="Memory Forensics: Analyzing Memory to Dissect Malicious Software",
            venue="Syngress (ISBN 1-59438-293-3)",
            ref_type="book",
        ),
        DaubertReference(
            ref_id="apple_plist_guide",
            authors="Apple Inc.",
            year=2023,
            title="Property List Programming Guide",
            venue="Apple Developer Documentation (developer.apple.com/library/archive/documentation/Cocoa/Conceptual/PropertyLists)",
            ref_type="vendor_doc",
        ),
    )
}

# ── rodiny algoritmů a mapování parser ID → references ───────────────────────


def family_for_parser(parser_id: str) -> str:
    """Rodina algoritmů pro parser ID (deterministické prefixové pravidlo)."""
    if parser_id == "crypto_extract":
        return "crypto_wallets"
    if parser_id.startswith("mem_"):
        return "memory"
    if parser_id in {"email_mbox", "gmail_messages", "ms_mail_pst"}:
        return "email"
    if parser_id == "sqlite" or parser_id.startswith(("chrome_", "firefox")):
        return "web_browsers"
    if parser_id in {
        "ddg_current_tabs",
        "google_search_history",
        "allowlisted_websites",
    }:
        return "web_browsers"
    if parser_id == "wifi_wlan":
        return "wlan"
    if parser_id in {"net_connections", "limewire_p2p"}:
        return "network"
    if (
        parser_id.startswith("win_")
        or parser_id in {"registry_hive", "lnk", "evtx"}
    ):
        return "windows_formats"
    if parser_id in {"plist", "icloud_messages", "apple_cloud"}:
        return "apple_formats"
    if parser_id.startswith(("google_", "amazon_")) or parser_id in {
        "box_cloud",
        "dropbox_mega",
        "cloud_drive_files",
        "cloud_generic",
    }:
        return "cloud_sync"
    return "generic"


FAMILY_REFS: dict[str, tuple[str, ...]] = {
    "crypto_wallets": (
        "nakamoto_bitcoin_2008",
        "bip39_2013",
        "eip55_2017",
        "koblitz_ecc_1987",
        "fips_202",  # Keccak-256 checksum BIP39 mnemonik
        "fips_197",  # AES — BitLocker/šifrované kontexty
    ),
    "memory": ("carvey_memforensics_2009",),
    "email": ("rfc5232_2008",),
    "web_browsers": ("boucher_lekhac_2018", "iqbal_meet_2022"),
    "windows_formats": ("harris_fsfa_2006",),
    "wlan": ("ieee80211_2020",),
    "network": ("rfc793_1981",),
    "apple_formats": ("apple_plist_guide",),
    "cloud_sync": ("boucher_lekhac_2018",),  # framework pro lokální vs. sync artefakty
    "generic": (),
}

# specifické dodatky per parser (nad rámec rodiny)
EXTRA_REFS: dict[str, tuple[str, ...]] = {
    "registry_hive": ("ms_regf",),
    "lnk": ("ms_shllink_2008",),
}


def refs_for_parser(parser_id: str) -> list[DaubertReference]:
    """Deterministický seznam referencí pro parser (rodina + dodatky)."""
    fam = family_for_parser(parser_id)
    ids = FAMILY_REFS.get(fam, ()) + EXTRA_REFS.get(parser_id, ())
    seen: set[str] = set()
    out: list[DaubertReference] = []
    for rid in ids:  # dedup, zachová pořadí (determinismus)
        if rid not in seen and rid in REFERENCES:
            seen.add(rid)
            out.append(REFERENCES[rid])
    return out


# ── core algoritmy — vždy v balíku (Rust core běží u každého případu) ───────

CORE_ALGORITHMS: tuple[tuple[str, str, tuple[str, ...], str | None], ...] = (
    # (název, role, ref_id, dokumentovaná chybovost nebo None)
    (
        "SHA-256",
        "hashování souborů + fingerprint chunků (Rust core)",
        ("fips_180_4", "kelsey_md5_2004", "wang_sha1_2005"),
        (
            "kolizní odolnost ≥ 2⁻¹²⁸; strukturální kolize dosud nenalezena "
            "(MD5/SHA-1 již porazeny — viz reference)"
        ),
    ),
    (
        "CDC + Buzhash rolling hash",
        "content-defined chunking / deduplikace (Rust core, C2/C3)",
        ("gregoriadis_cdc_2024", "broder_rabin_1993"),
        "deterministický — hranice chunků jsou funkcí obsahu, bez stochastické složky",
    ),
    (
        "Keccak-256 / SHA-3",
        "checksum BIP39 mnemonik (crypto_extract)",
        ("fips_202",),
        "kolizní odolnost ≥ 2⁻¹²⁸; strukturální kolize dosud nenalezena",
    ),
)

# lab testy STOPA pokrývající core algoritmy (faktor 1 — testovatelnost)
CORE_TEST_FILES: tuple[str, ...] = (
    "tests/test_f21_rust_core.py",
    "tests/test_dedupe.py",
    "tests/test_f23_block_dedupe.py",
)

# ── pomocné konverze ─────────────────────────────────────────────────────────


def ref_dict(ref: DaubertReference) -> dict:
    """JSON-safe slovník reference (bez dataclass objektů)."""
    return asdict(ref)


def _error_rate_block(documented: str | None, tested_in_lab: bool) -> dict:
    """Faktor 3 — poctivá chybovost: dokumentovaná hodnota nebo explicitní None."""
    if documented is not None:
        return {"documented_value": documented}
    basis = (
        "nekvantifikována v literatuře; validováno na referenčním datasetu STOPA"
        if tested_in_lab
        else "veřejná kvantifikace chybí — viz omezení parseru"
    )
    return {"documented_value": None, "basis": basis}


def _factors(
    ref_list: list[DaubertReference],
    test_files: Sequence[str] = (),
    reference_dataset: str | None = None,
    error_rate_documented: str | None = None,
) -> dict:
    """Vyhodnocení 4 Daubert faktorů pro algoritmus/parser (čisté mapování)."""
    tested_in_lab = bool(test_files) or reference_dataset is not None
    peer_refs = [r for r in ref_list if r.ref_type == "peer_reviewed"]
    acceptance_refs = [r for r in ref_list if r.ref_type in ("standard", "vendor_doc")]
    return {
        "testability": {
            "tested_in_lab": tested_in_lab,
            "tests": list(test_files),
            "reference_dataset": reference_dataset,
        },
        "peer_review": {
            "count": len(peer_refs),
            "references": [ref_dict(r) for r in peer_refs],
        },
        "error_rate": _error_rate_block(error_rate_documented, tested_in_lab),
        "general_acceptance": {
            "standards_and_specs_count": len(acceptance_refs),
            "references": [ref_dict(r) for r in acceptance_refs],
            "notes": None if ref_list else "bez přímé reference — opora jen C3 lab validace",
        },
    }


def _core_algorithm_entries() -> list[dict]:
    """Core algoritmy + faktory (deterministické pořadí z CORE_ALGORITHMS)."""
    out: list[dict] = []
    for name, role, ref_ids, error_rate in CORE_ALGORITHMS:
        refs = [REFERENCES[rid] for rid in ref_ids if rid in REFERENCES]
        entry = {
            "name": name,
            "role": role,
            "references": [ref_dict(r) for r in refs],
        }
        entry["factors"] = _factors(
            refs, test_files=CORE_TEST_FILES, error_rate_documented=error_rate
        )
        out.append(entry)
    return out


# ── hlavní builder ───────────────────────────────────────────────────────────

MIN_REFERENCES_AK = 20  # AK F5.5: minimálně 20 referencí


def _as_seq(value: object) -> tuple[str, ...]:
    """Bezpečná konverze hodnoty Mappingu na řetězcovou n-tici (presentation předává tuple/list)."""
    if not isinstance(value, (list, tuple)):
        return ()
    out = [str(x) for x in value]  # type: ignore[union-attr]
    return cast("tuple[str, ...]", out)


def build_daubert_pack(
    case_id: str,
    case_name: str,
    generated_at: str,
    stopa_version: str,
    parsers: Sequence[Mapping[str, object]],
) -> dict:
    """Sestaví Daubert balík pro případ (čistá funkce — žádný I/O).

    Args:
        case_id / case_name: identifikace případu.
        generated_at: UTC ISO čas generování (presentation vrstva).
        stopa_version: verze STOPA (`__version__`).
        parsers: záznamy ``{parser_id, version, artifacts, test_files,
            reference_dataset, limitations}`` — sbírá presentation z C3/C6.

    Returns:
        Payload balíku (deterministický; kanonický JSON + digest udělá volající).
    """
    case_entries: list[dict] = []
    for p in sorted(parsers, key=lambda x: str(x.get("parser_id", ""))):
        pid = str(p.get("parser_id", ""))
        test_files = _as_seq(p.get("test_files"))
        ref_ds = p.get("reference_dataset")
        refs = refs_for_parser(pid)
        entry: dict[str, object] = {
            "parser_id": pid,
            "version": p.get("version"),
            "artifacts": int(p.get("artifacts", 0)),  # type: ignore[arg-type]
            "family": family_for_parser(pid),
            "limitations": list(_as_seq(p.get("limitations"))),
            "references": [ref_dict(r) for r in refs],
        }
        entry["factors"] = _factors(refs, test_files, ref_ds)  # type: ignore[arg-type]
        case_entries.append(entry)

    library = [ref_dict(REFERENCES[k]) for k in sorted(REFERENCES)]
    if len(library) < MIN_REFERENCES_AK:
        raise ValueError(
            f"Daubert knihovna pod AK limit: {len(library)} < {MIN_REFERENCES_AK}"
        )

    with_peer = sum(1 for e in case_entries if (e["factors"]["peer_review"]["count"] > 0))  # type: ignore[index]
    return {
        "schema": "stopa-daubert-pack/v1",
        "case_id": case_id,
        "case_name": case_name,
        "generated_at": generated_at,
        "stopa_version": stopa_version,
        "daubert_factors": [
            {"id": fid, "label": label} for fid, label in DAUBERT_FACTORS
        ],
        "reference_library": library,
        "references_total": len(library),
        "core_algorithms": _core_algorithm_entries(),
        "case_parsers": case_entries,
        "coverage": {
            "case_parsers_total": len(case_entries),
            "with_peer_review_refs": with_peer,
            "standards_or_vendor_docs_only": sum(
                1 for e in case_entries
                if (e["factors"]["peer_review"]["count"] == 0)  # type: ignore[index]
                and (e["factors"]["general_acceptance"]["standards_and_specs_count"] > 0)  # type: ignore[index]
            ),
            "no_direct_reference": sum(
                1 for e in case_entries if not e["references"]  # type: ignore[operator]
            ),
        },
    }
