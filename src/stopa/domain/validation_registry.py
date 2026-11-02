"""STOPA — Parser Validation Registry (P0 Core, C3).

Deklarativní registry všech parserů: identifikátor, verze, podporované formáty,
známá omezení a referenční datasety. Zdroj pravdy pro verze je pipeline
(``ARTIFACT_EXTRACTORS`` / ``NAME_BASED_EXTRACTORS``) — registry se s ním
synchronizuje v ``build_registry()`` (každý extraktor má záznam a naopak,
verze se shodují).

Čistá logika bez I/O; verze pipeline se načítají lazy (domain → pipeline je
směr jen u konvenční funkce, ne při importu modulu).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class ParserValidation:
    """Validační záznam jednoho parseru (C3 zadání §4.2)."""

    parser_id: str  # např. "win_prefetch" — klíč v pipeline extraktorech
    version: str  # synchronizováno s pipeline (ověřeno build_registry)
    formats: tuple[str, ...]  # podporované formáty/varianty
    limitations: tuple[str, ...] = ()  # známá omezení parseru
    reference_dataset: str | None = None  # cesta do tests/reference_datasets/
    expected_results: dict = field(default_factory=dict)  # očekáv. počty na datasetu
    test_files: tuple[str, ...] = ()  # testové soubory pokrývající parser


class RegistryError(Exception):
    """Nesoulad registry a pipeline (chybějící záznam / rozdílná verze)."""


# ── deklarativní registry — formáty/omezení dle docstringů parserů ─────────

PARSER_VALIDATIONS: dict[str, ParserValidation] = {
    "sqlite": ParserValidation(
        parser_id="sqlite",
        version="",  # doplní build_registry z pipeline
        formats=(
            "Chrome/Edge/Opera (urls+visits, µs od Win epochy)",
            "Firefox (moz_places, ms od Unix epochy)",
            "Apple iMessage chat.db (CFAbsoluteTime od 2001)",
            "Android mmssms.db / calllog.db (unix ms)",
        ),
        limitations=(
            "časové epochy se liší dle databáze — detekce podle schématu",
            "smazané řádky vyžadují sqlite_recover (samostatný parser)",
        ),
        test_files=("tests/test_sqlite_extract.py",),
    ),
    "registry_hive": ParserValidation(
        parser_id="registry_hive",
        version="",
        formats=("Windows registry hive (.regf) — Run/RunOnce, MountedDevices, identita"),
        limitations=(
            "běží generic + Amcache + ShimCache + Clipboard + SID (sdílená regf magic)",
            "závislost na regipy pro dekompozici klíčů",
        ),
        test_files=("tests/test_registry_extract.py",),
    ),
    "plist": ParserValidation(
        parser_id="plist",
        version="",
        formats=("Apple property list — binární bplist00 i XML"),
        limitations=(
            "datetime listy → artifact plist_date; top-level struktura jen triage",
        ),
        test_files=("tests/test_plist_extract.py",),
    ),
    "lnk": ParserValidation(
        parser_id="lnk",
        version="",
        formats=("MS-LNK [MS-LNK] — hlavička 76 B + volitelné bloky podle flags"),
        limitations=(
            "bloky se čtou jen v kanonickém pořadí dle specifikace",
        ),
        test_files=("tests/test_e6.py",),
    ),
    "win_prefetch": ParserValidation(
        parser_id="win_prefetch",
        version="",
        formats=("MS-PREFETCH (MAM) — verze 30-variant-2 / 31, LZXPRESS payload"),
        limitations=(
            "LZXPRESS Huffman dekomprese (MS-XCA §2.2.4)",
            "starší klasické .pf formáty (pre-MAM) nepodporovány",
        ),
        test_files=("tests/test_e6.py",),
    ),
    "evtx": ParserValidation(
        parser_id="evtx",
        version="",
        formats=(
            "EVTX — file magic EVTX, chunk magic CHUN (BinXML payload)",
            "ElfFile varianta — magic ElfFile\\0 / ElfChnk\\0 (ground-truth disk)",
        ),
        limitations=("chunked struktura s BinXML — poškozený chunk = ztráta událostí"),
        test_files=("tests/test_e7.py",),
    ),
    "icloud_messages": ParserValidation(
        parser_id="icloud_messages",
        version="",
        formats=(
            (
                "iCloud Messages export (MessagesInICloud.csv — ve skutečnosti XLSX "
                "nebo delimited text)"
            ),
        ),
        limitations=(
            "detekce podle NÁZVU souboru (AXIOM Hunter) — magic bytes nestačí",
        ),
        test_files=("tests/test_imessage_cloud.py",),
    ),
    "win_jumplist": ParserValidation(
        parser_id="win_jumplist",
        version="",
        formats=(
            ".customDestinations-ms kontejnery (u32 version=2) s vloženými MS-LNK",
        ),
        limitations=(
            "empiricky ověřeno na 16 reálných souborech z Win11 image",
            "detekce name-based — kontejner nemá spolehlivou magic",
        ),
        test_files=("tests/test_e6.py",),
    ),
    "win_usn": ParserValidation(
        parser_id="win_usn",
        version="",
        formats=(
            "NTFS USN Journal ($Extend\\$UsnJrnl) — záznamy o změnách FS",
        ),
        limitations=(
            "detekce name-based (header verze 2 kontextově ověřen parserem)",
        ),
        test_files=("tests/test_e7.py",),
    ),
    # ── ETAPA B vlna 1 — AXIOM port: email / WiFi / Scheduled Tasks / netstat ──
    "email_mbox": ParserValidation(
        parser_id="email_mbox",
        version="",
        formats=(
            "mbox (Unix mailbox) — více zpráv, oddělené From řádky",
            "EML/MSG — jednotlivé zprávy (RFC 822)",
        ),
        limitations=(
            "detekce name-based (.eml/.mbox) + content check (From header)",
            "Date parsování přes email.utils — neplatné datum → None",
            "Body se truncuje na MAX_BODY_LEN pro detaily",
        ),
        test_files=("tests/test_email_mbox.py",),
    ),
    "wifi_wlan": ParserValidation(
        parser_id="wifi_wlan",
        version="",
        formats=(
            "Windows WLAN profile XML (C:\\ProgramData\\Microsoft\\WLAN\\Profile)",
        ),
        limitations=(
            "detekce name-based (*.xml s WLANProfile root elementem)",
            "SSID/autentizace z <network><SSIDConfig> a <authentication>",
        ),
        test_files=("tests/test_win_wlan.py",),
    ),
    "win_schedtask": ParserValidation(
        parser_id="win_schedtask",
        version="",
        formats=(
            "Windows Task Scheduler XML (C:\\Windows\\System32\\Tasks\\*.xml)",
        ),
        limitations=(
            "detekce name-based (*.xml s Task root elementem)",
            "Trigger/Action/Principal z <Triggers>/<Actions>/<Principal>",
        ),
        test_files=("tests/test_win_schedtask.py",),
    ),
    "net_connections": ParserValidation(
        parser_id="net_connections",
        version="",
        formats=(
            "Windows netstat -ano textový výstup",
            "Unix ss/netstat -an textový výstup",
        ),
        limitations=(
            "detekce name-based (netstat/connections/sockets) + content check (hlavička)",
            "snapshot bez časového razítka — timestamp=None",
            "limit MAX_CONNECTIONS_PER_FILE=5000 spojení",
        ),
        test_files=("tests/test_net_connections.py",),
    ),
}


def build_registry(versions: dict[str, str] | None = None) -> dict[str, ParserValidation]:
    """Synchronizuje registry s pipeline a vrací kompletní registry.

    ``versions`` — verze parserů (výchozí: lazy import z ``stopa.pipeline``).
    Ověření: každý extraktor v pipeline má záznam v registry a naopak;
    verze se shodují. Nesoulad → :class:`RegistryError`.
    """
    if versions is None:  # lazy — domain bez tvrdé závislosti na pipeline při importu
        from stopa.pipeline import parser_versions

        versions = parser_versions()

    out: dict[str, ParserValidation] = {}
    for pid, pv in PARSER_VALIDATIONS.items():
        if pid not in versions:
            raise RegistryError(f"registry {pid!r} nemá odpovídající extraktor v pipeline")
        out[pid] = pv if pv.version else replace(pv, version=versions[pid])

    for pid, ver in versions.items():
        if pid not in PARSER_VALIDATIONS:
            raise RegistryError(f"pipeline extraktor {pid!r} nemá záznam v registry")
        elif out[pid].version != ver:
            raise RegistryError(
                f"verze parseru {pid!r}: pipeline={ver!r}, registry={out[pid].version!r}"
            )
    return out


def registry_report(registry: dict[str, ParserValidation] | None = None) -> list[dict]:
    """Shrnutí registry pro CLI/GUI — řádky s identitou a validací parserů."""
    if registry is None:
        registry = build_registry()
    return [
        {
            "parser_id": pv.parser_id,
            "version": pv.version,
            "formats": list(pv.formats),
            "limitations": list(pv.limitations),
            "reference_dataset": pv.reference_dataset,
            "test_files": list(pv.test_files),
        }
        for pv in sorted(registry.values(), key=lambda p: p.parser_id)
    ]
