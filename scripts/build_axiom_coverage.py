"""STOPA — AXIOM coverage matrix generator.

Datově klasifikuje všech 237 položek z ``docs/re-axiom/axiom-artifact-extractors.json``
do kategorií podle toho, co STOPA už pokrývá a co je portovatelné:

- **covered**        — STOPA umí (existující parser / artifact_type)
- **portable-local** — lokálně portovatelný (čistý Python, bez cloud API)
- **cloud-export**   — JSON export / warrant return (Google/Microsoft/Twitter/…)
- **memory**         — live forensics (potřebuje paměťový dump)
- **base-class**     — rozhraní / základní třída (ne extraktor jako takový)

Výstup: ``docs/re-axiom/AXIOM_COVERAGE.md`` + ``AXIOM_COVERAGE.json``
+ ``STOPA_COVERAGE_MATRIX.csv`` (FÁZE 15 — centrální matice v kořeni).
Deterministický — stejný vstup = stejná matice (žádné časy/ID).
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "re-axiom" / "axiom-artifact-extractors.json"
OUT_MD = ROOT / "docs" / "re-axiom" / "AXIOM_COVERAGE.md"
OUT_JSON = ROOT / "docs" / "re-axiom" / "AXIOM_COVERAGE.json"
OUT_CSV = ROOT / "STOPA_COVERAGE_MATRIX.csv"  # FÁZE 15 — centrální matice v kořeni

# FÁZE 15 stavy implementace (z kategorie portu)
_STATUS_BY_CAT = {
    "covered": ("SUPPORTED", "testováno"),
    "portable-local": ("NOT_SUPPORTED", "plánovaný port (čistý Python)"),
    "cloud-export": ("NOT_SUPPORTED", "čeká na exportní modul (JSON/warrant return)"),
    "memory": ("NOT_SUPPORTED", "live forensics — potřebuje paměťový dump"),
    "base-class": ("DEPRECATED", "rozhraní / základní třída, ne extraktor"),
}

# ── STOPA pokrytí: AXIOM typ → (stav, STOPA mechanismus) ────────────────────
# covered = existující parser; portable-local = první vlna portu.
COVERED: dict[str, str] = {
    "AppleIMessageArtifact": "covered",  # sqlite_extract imessage
    "CallLogsArtifact": "covered",  # sqlite_extract call_log
    "JumpListsArtifact": "covered",  # win_jumplist
    "IeTypedUrlArtifact": "covered",  # browser_history (chrome/firefox)
    "GoogleBrowsingHistoryArtifact": "covered",  # browser_history
    "CloudGoogleChromeBrowserHistoryArtifact": "covered",  # browser_history
    "TimelineArtifact": "covered",  # timeline engine
    "MapArtifact": "covered",  # timeline/map
    "WorldMapArtifact": "covered",  # world map (timeline)
    "MftArtifact": "covered",  # TSK disk image MFT
    "OfficeArtifact": "covered",  # OOXML document
    "DocumentMetadataExtractor": "covered",  # OOXML metadata
    "ImageInfoArtifact": "covered",  # magic bytes image info
    "MediaMetadataExtractor": "covered",  # media family
    "SamsungContactArtifact": "covered",  # mobile_extract contacts2
    "SamsungMessagesArtifact": "covered",  # mobile_extract sms
    "SamsungConnectionsArtifact": "covered",  # mobile_extract calllog
    "MicrosoftTeamsMessagesArtifact": "covered",  # sqlite generic (teams.db)
    "MicrosoftTeamsMessagesBaseArtifact": "covered",
    "MicrosoftTeamsMessagesComputerArtifact": "covered",
    "CloudMboxEmailArtifact": "portable-local",  # mbox parser (vlna 1)
    "OfflineGmailArtifact": "portable-local",  # mbox parser (vlna 1)
}

# base-class / rozhraní — ne extraktor jako takový
BASE_CLASSES = {
    "IArtifact", "ICloudArtifact", "ICustomArtifact", "ILegacyArtifact",
    "IWorldMapArtifact", "SimpleArtifact", "Artifact", "CloudArtifact",
    "CustomArtifact", "LegacyArtifact", "MappedArtifact", "DbArtifact",
    "XmlArtifact", "MessageArtifact", "ChannelArtifact", "LabelArtifact",
    "ServerArtifact", "UserArtifact", "DevicesArtifact", "DllArtifact",
    "MemoryArtifact", "IAttachmentExtractor", "BinaryTextExtractor",
    "EventExtractor", "IconExtractor", "LsaRegistryExtractor",
    "TpduDataExtractor", "IUnifiedLogsExtractor", "ICustomXmlArtifact",
    "ILsaRegistryExtractor", "ITpduDataExtractor", "IContainerEnabledArtifact",
    "CaseAmendingTestArtifact", "MappedLegacyEmailArtifact",
}

# memory / live forensics (Volatility-style) — potřebuje paměťový dump
MEMORY = {
    "ApiHooksArtifact", "CallbacksArtifact", "ExecutiveObjectCallbacksArtifact",
    "MalfindArtifact", "ModScanArtifact", "ProcessListArtifact",
    "ProcessScanArtifact", "ProcessesArtifact", "SocketsArtifact",
    "OpenConnectionsArtifact", "OpenHandlesArtifact", "HandlesArtifact",
    "NetworkConnectionsArtifact", "DriversArtifact", "PsxViewArtifact",
}

# cloud-export / warrant return — JSON export (Google/Microsoft/Twitter/FB/…)
CLOUD_PREFIXES = ("Cloud",)
CLOUD_MARKERS = ("WarrantReturn", "2025", "2026", "Takeout")


def classify(name: str, dll: str) -> tuple[str, str]:
    """Vrátí (kategorie, mechanismus/popis)."""
    if name in COVERED:
        return COVERED[name], _covered_desc(name)
    if name in BASE_CLASSES:
        return "base-class", "rozhraní / základní třída"
    if name in MEMORY:
        return "memory", "live forensics (paměťový dump)"
    # cloud export — prefix Cloud* nebo warrant-return marker
    if any(name.startswith(p) for p in CLOUD_PREFIXES):
        return "cloud-export", "JSON export / warrant return"
    if any(m in name for m in CLOUD_MARKERS):
        return "cloud-export", "warrant return (JSON)"
    # Google* bez Cloud prefixu = lokální profil / takeout
    if name.startswith("Google"):
        return "portable-local", "lokální profil / takeout"
    # Samsung/Kik/MailRu/Bebo/Chatroulette/Limewire — legacy mobile/messenger (sqlite)
    if any(name.startswith(p) for p in ("Samsung", "Kik", "MailRu", "Bebo", "Chatroulette", "Limewire", "Limerunner", "Luckywire")):
        return "portable-local", "legacy mobile / messenger (SQLite)"
    # Instagram/Snapchat lokální (ne Cloud) — sqlite/DB export
    if name.startswith(("Instagram", "Snapchat")):
        return "cloud-export", "JSON/DB export"
    # Windows registry-based (Clipboard/WiFi/ScheduledTasks/Audit*)
    if name in ("ClipboardArtifact", "WiFiLocationsArtifact", "ScheduledTasksArtifact"):
        return "portable-local", "Windows registry / XML profil"
    if name.startswith(("Audit", "GoogleAccessLog")):
        return "covered", "EVTX event log (evtx parser)"
    # browser cookies / bookmarks lokální
    if "Cookies" in name or "Bookmarks" in name:
        return "portable-local", "browser cookies/bookmarks"
    # network scan text output
    if name in ("ConnscanArtifact", "NetScanArtifact", "SockscanArtifact"):
        return "portable-local", "text output (connstat/netstat)"
    # SID
    if name in ("GetsidsArtifact", "SidsArtifact", "UserSidsArtifact"):
        return "portable-local", "registry SAM/Security"
    # Skype warrant return
    if name.startswith("SkypeWarrantReturn"):
        return "cloud-export", "warrant return (JSON)"
    # default — lokálně portovatelný
    return "portable-local", "lokální parser (čistý Python)"


def _covered_desc(name: str) -> str:
    m = {
        "AppleIMessageArtifact": "sqlite_extract → imessage",
        "CallLogsArtifact": "sqlite_extract → call_log",
        "JumpListsArtifact": "win_jumplist parser",
        "IeTypedUrlArtifact": "browser_history (chrome/firefox)",
        "GoogleBrowsingHistoryArtifact": "browser_history",
        "CloudGoogleChromeBrowserHistoryArtifact": "browser_history",
        "TimelineArtifact": "timeline engine",
        "MapArtifact": "timeline / map",
        "WorldMapArtifact": "world map (timeline)",
        "MftArtifact": "TSK disk image MFT",
        "OfficeArtifact": "OOXML document parser",
        "DocumentMetadataExtractor": "OOXML metadata",
        "ImageInfoArtifact": "magic bytes → image info",
        "MediaMetadataExtractor": "media family",
        "SamsungContactArtifact": "mobile_extract → contacts2",
        "SamsungMessagesArtifact": "mobile_extract → sms",
        "SamsungConnectionsArtifact": "mobile_extract → calllog",
        "MicrosoftTeamsMessagesArtifact": "sqlite generic (teams.db)",
        "MicrosoftTeamsMessagesBaseArtifact": "sqlite generic",
        "MicrosoftTeamsMessagesComputerArtifact": "sqlite generic",
    }
    return m.get(name, "existující parser")


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for x in data:
        name = x["type"].split(".")[-1]
        cat, desc = classify(name, x["dll"])
        rows.append({"name": name, "category": cat, "mechanism": desc})

    # dedupe (některé typy se opakují napříč DLL) — zachovat pořadí prvního výskytu
    seen: set[str] = set()
    unique: list[dict] = []
    for r in rows:
        if r["name"] not in seen:
            seen.add(r["name"])
            unique.append(r)

    counts = Counter(r["category"] for r in unique)
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in unique:
        by_cat[r["category"]].append(r)

    # ── JSON výstup ──
    OUT_JSON.write_text(
        json.dumps(
            {
                "total_entries": len(data),
                "unique_types": len(unique),
                "counts": dict(counts),
                "by_category": {k: [r["name"] for r in sorted(v, key=lambda x: x["name"])] for k, v in by_cat.items()},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # ── Markdown matice ──
    order = ["covered", "portable-local", "cloud-export", "memory", "base-class"]
    titles = {
        "covered": "✅ COVERED — STOPA už umí (existující parser)",
        "portable-local": "🔧 PORTABLE-LOCAL — lokálně portovatelný (čistý Python)",
        "cloud-export": "☁️ CLOUD-EXPORT — JSON export / warrant return",
        "memory": "💾 MEMORY — live forensics (paměťový dump)",
        "base-class": "🧩 BASE-CLASS — rozhraní / základní třída",
    }
    lines = [
        "# STOPA × Magnet AXIOM — pokryvací matice extraktorů",
        "",
        f"Zdroj: `axiom-artifact-extractors.json` ({len(data)} položek, {len(unique)} unikátních typů).",
        "Klasifikace je datová (deterministická) — generováno `scripts/build_axiom_coverage.py`.",
        "",
        "## Souhrn",
        "",
    ]
    for cat in order:
        lines.append(f"- **{titles[cat].split('—')[0].strip()}**: {counts.get(cat, 0)}")
    lines += ["", "---", ""]
    for cat in order:
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines.append(f"## {titles[cat]} ({len(items)})")
        lines.append("")
        for r in sorted(items, key=lambda x: x["name"]):
            lines.append(f"- `{r['name']}` — {r['mechanism']}")
        lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    # ── FÁZE 15 — centrální matice v kořeni (CSV) ──
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "artifact_type",
                "platforma",
                "zdroj_dat",
                "parser_stopa",
                "stav_implementace",
                "stav_testovani",
                "verze",
                "znamá_omezeni",
                "referencni_dataset",
                "vysledek_validace",
            ]
        )
        for r in sorted(unique, key=lambda x: (x["category"], x["name"])):
            status, test_state = _STATUS_BY_CAT[r["category"]]
            w.writerow(
                [
                    r["name"],
                    "multi" if r["category"] != "memory" else "windows-memory",
                    r["mechanism"],
                    r["mechanism"] if r["category"] == "covered" else "",
                    status,
                    test_state,
                    "",  # verze parseru — doplní se při portu z PARSER_VERSION
                    "",  # známá omezení
                    "",  # referenční dataset (syntetický fixture)
                    "",  # výsledek validace (C6 benchmark report)
                ]
            )

    print(f"total={len(data)} unique={len(unique)}")
    for cat in order:
        print(f"  {cat}: {counts.get(cat, 0)}")


if __name__ == "__main__":
    main()
