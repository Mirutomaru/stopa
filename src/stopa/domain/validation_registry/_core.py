"""Core parsoři — sqlite, registry hive, plist, lnk, prefetch, evtx, mbox a další.

P1-4 vlna E — datová sekce rejstříku; záznamy byte-přesně z monolitu.
"""

from __future__ import annotations

from ._types import ParserValidation

_PART = {
    "sqlite": ParserValidation(
        parser_id="sqlite",
        version="",  # doplní build_registry z pipeline
        reference_dataset=(
            "sqlite/chrome_history/"  # STP-073 (pilot vlna 1, design §6.1) — Chrome/Edge History varianta; ostatní varianty = další vlny §7
        ),
        formats=(
            "Chrome/Edge/Opera (urls+visits, µs od Win epochy)",
            "Firefox (moz_places, ms od Unix epochy)",
            "Apple iMessage chat.db (CFAbsoluteTime od 2001)",
            "Android mmssms.db / calllog.db (unix ms)",
            "DuckDuckGo cookies — Chromium `cookies` schéma (ETAPA B vlna 4)",
            "iOS voicemail.db (`voicemail`, unix s + CFAbsoluteTime) (ETAPA B vlna 4)",
            "iOS Local.sqlite parked car locations (`ZRTVEHICLEEVENTMO`) (ETAPA B vlna 4)",
            "Samsung Voice Recording (voice_recorder DB, epoch ms) (ETAPA B vlna 5)",
            "Chrome/Edge search_terms — omnibox dotazy z lišty (GoogleBarArtifact) (ETAPA B vlna 6)",
        ),
        limitations=(
            "časové epochy se liší dle databáze — detekce podle schématu",
            "smazané řádky vyžadují sqlite_recover (samostatný parser)",
        ),
        test_files=("tests/test_sqlite_extract.py", "tests/test_p11_quality_sqlite.py"),
    ),
    "registry_hive": ParserValidation(
        parser_id="registry_hive",
        version="",
        formats=(
            "Windows registry hive (.regf) — Run/RunOnce, MountedDevices, identita",
            "UserAssist MRU (NTUSER.DAT — spuštěné aplikace / dokumenty) (ETAPA B vlna 4)",
        ),
        limitations=(
            "běží generic + Amcache + ShimCache + Clipboard + SID + UserAssist (sdílená regf magic)",
            "závislost na regipy pro dekompozici klíčů",
        ),
        test_files=("tests/test_registry_extract.py", "tests/test_p11_quality_syscore.py"),
    ),
    "plist": ParserValidation(
        parser_id="plist",
        version="",
        formats=("Apple property list — binární bplist00 i XML"),
        limitations=(
            "datetime listy → artifact plist_date; top-level struktura jen triage",
        ),
        test_files=("tests/test_plist_extract.py", "tests/test_p11_quality_syscore.py"),
    ),
    "lnk": ParserValidation(
        parser_id="lnk",
        version="",
        formats=("MS-LNK [MS-LNK] — hlavička 76 B + volitelné bloky podle flags"),
        limitations=(
            "bloky se čtou jen v kanonickém pořadí dle specifikace",
        ),
        test_files=("tests/test_e6.py", "tests/test_p11_quality_syscore.py"),
    ),
    "win_prefetch": ParserValidation(
        parser_id="win_prefetch",
        version="",
        formats=("MS-PREFETCH (MAM) — verze 30-variant-2 / 31, LZXPRESS payload"),
        limitations=(
            "LZXPRESS Huffman dekomprese (MS-XCA §2.2.4)",
            "starší klasické .pf formáty (pre-MAM) nepodporovány",
        ),
        test_files=("tests/test_e6.py", "tests/test_p11_quality_windows.py"),
    ),
    "evtx": ParserValidation(
        parser_id="evtx",
        version="",
        formats=(
            "EVTX — file magic EVTX, chunk magic CHUN (BinXML payload)",
            "ElfFile varianta — magic ElfFile\\0 / ElfChnk\\0 (ground-truth disk)",
        ),
        limitations=("chunked struktura s BinXML — poškozený chunk = ztráta událostí"),
        test_files=("tests/test_e7.py", "tests/test_p11_quality_syscore.py"),
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
        test_files=("tests/test_imessage_cloud.py", "tests/test_p11_quality_cloud_exports.py"),
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
        test_files=("tests/test_e6.py", "tests/test_p11_quality_windows.py"),
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
        test_files=("tests/test_e7.py", "tests/test_p11_quality_windows.py"),
    ),
    # STP-075 / vlna 31 — E8 file metadata pipeline wrapper (pilot vlna 2, design §7)
    "file_meta": ParserValidation(
        parser_id="file_meta",
        version="",  # doplní build_registry z pipeline
        reference_dataset=(
            "filemeta/"  # STP-075 (pilot vlna 2, design §7) — PDF /Info + OOXML docProps varianta; ID3v2/MP4/EXIF = další vlny §7
        ),
        formats=(
            "PDF /Info slovník (Title/Author/Creator/Producer/CreationDate/ModDate)",
            "OOXML docProps — docx/xlsx/pptx (core.xml Dublin Core + app.xml statistiky)",
            "ID3v2 textové frameworky (TIT2/TPE1/TALB/TRCK/TDRC|TYER/TCON/TBPM) [doménová utilita]",
            "MP4/iTunes atomy (©nam/©ART/aart/©alb/©day/©gen/trkn) [doménová utilita]",
            "EXIF přes PIL (Make/Model/DateTimeOriginal/Artist/Copyright) [meta]",
        ),
        limitations=(
            "PDF /Info = heuristický byte sken — první platný string token za klíčem vyhrává",
            "OOXML docProps členy omezeny 256 KiB + bounded XML parse (hloubka/počet prvků)",
            "ID3v2: TDRC má prioritu před TYER; MP4: jen textové atomy, trkn binární; EXIF vyžaduje Pillow [meta]",
            "vlna 31 reference dataset pokrývá PDF /Info + OOXML docProps; ID3v2/MP4/EXIF = další vlny §7",
        ),
        test_files=(
            "tests/test_e8.py",
            "tests/test_p11_quality_file_meta.py",  # P1-1 vlna 31 — quality sada file_meta
        ),
    ),
}
