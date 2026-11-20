"""STOPA CLI — argparse subpříkazy.

Použití:
  stopa case new "Karel Novák" --examiner "JUDr. M. Matúš"
  stopa add <case_id> /cesta/ke/zdroji [--profile forensic] [--hash-set bad.txt]
  stopa files <case_id> [--bad-ext] [--dups] [--family image] [--limit 50]
  stopa search <case_id> "dotaz" [--source ID]   # full-text (FTS5)
  stopa timeline <case_id> [--type browser_history] [--path text] [-v]
  stopa timeline-intel <case_id> [--json]    # P2-3 — pokročilá timeline intelligence (gapy/outliery/korelace/nejistota)
  stopa xcorr <case_a> <case_b>|--all [--entity email|tel|hash] [--user U] [--json]   # P2-6 — sdílené entity napříč případy
  stopa registry [--tenant ORG] [--user U] [--sync CASE_ID] [--json]   # P2-2 — centrální registr případů (instance DB)
  stopa intel import <case_id> --stix FILE|--ioc KIND:HODNOTA[,…] [--tlp TLP] [--source S] [--json]  # P2-5 — Threat Intel (IoC feed STIX 2.1)
  stopa intel match <case_id> [--json]    # P2-5 — deterministické matching IoC × artefakty/entities
  stopa exchange pack <case_id> [--out FILE] [--anon] [--key-file F] [--key-out F] [--json]  # P2-7 — Case Exchange bundle v1 (+ anonymizace)
  stopa exchange verify BUNDLE_FILE [--roots FILE] [--root LABEL=BASE64]... [--json]   # P2-7 — ověření bundle (trust roots)
  stopa image <case_id> /cesta/ke/obrazu.img       # disk image (TSK) [+ --no-carve]
  stopa mobile <case_id> /obraz.img [--password HESLO]  # mobilní FDE/FBE unlock + TSK
  stopa stats <case_id>
  stopa verify <case_id> [--limit N]                     # E1 — re-hash + kontrola integrity (SHA-256/MD5)
  stopa audit <case_id> [--limit N] [-v]                 # E1 — neměnná stopa operací
  stopa backup <case_id> [--out DIR]                     # E1 — záloha case DB (SQLite .backup + integrity)
  stopa report <case_id> [--format html|pdf] [--out DIR] [--lang cs|en]  # court-ready report + chain of custody
  stopa export <case_id> --what artifacts|timeline|correlations --format csv|json|jsonl|xml|stix|l2tcsv|uco [--limit N] [--out SOUBOR] [--bundle]
  stopa serve [--port 8473]                                 # web GUI (FastAPI)
  stopa profiles

DB: cases/<case_id>.db (přesaditelné přes STOPA_DB_DIR).
"""

from __future__ import annotations

import argparse
import logging
import sys

_log = logging.getLogger("stopa.cli")

from stopa.domain.investigation_workspace import TASK_STATUSES  # P2-4 — workspace task stavy
from stopa.domain.mem_forensics import DEFAULT_PLUGINS as _VOL_DEFAULT_PLUGINS
from stopa.domain.profiles import PROFILES
from stopa.domain.write_blocker import known_vendor_ids  # F5.4 — write-blocker API

# P1-4 — helpery přesunuty do cli/_util.py (re-export pro kompatibilitní povrch)
from ._util import (
    _add_json_flag,
    _db_dir,  # noqa: F401 — kompatibilitní povrch (testy importují ze stopa.cli)
    _load_timesketch_auto_push,  # noqa: F401 — kompatibilitní povrch (testy importují ze stopa.cli)
    _print_json,
)

# P1-4 — kvalita parserů/AI/reparse přesunuty do cli/commands/analysis.py (re-export)
from .commands.analysis import (
    cmd_ai_run,
    cmd_parser_quality,
    cmd_parser_status,
    cmd_reparse,
)

# P1-4 — rodina `case` přesunuta do cli/commands/case.py (re-export pro kompatibilitu)
from .commands.case import cmd_case_auto_export, cmd_case_auto_interval, cmd_case_new

# P1-4 — jádrové case operace přesunuty do cli/commands/core.py (re-export)
from .commands.core import (
    cmd_add,
    cmd_analytics,
    cmd_correlate,
    cmd_files,
    cmd_image,
    cmd_mobile,
    cmd_search,
    cmd_stats,
    cmd_timeline,
)

# P2-7 — Case Exchange bundle v1 v cli/commands/exchange.py
from .commands.exchange import cmd_exchange_pack, cmd_exchange_verify

# P1-4 — vývoz/integrace přesunuty do cli/commands/export.py (re-export;
# _write_export_manifest je součást kompatibilitního povrchu — testy ho importují)
from .commands.export import (
    _write_export_manifest,  # noqa: F401 — kompatibilitní povrch (testy importují ze stopa.cli)
    cmd_export,
    cmd_plaso_import,
    cmd_timesketch_push,
)

# P1-4 — forenzní analýzy přesunuty do cli/commands/forensics.py (re-export)
from .commands.forensics import (
    cmd_antiforensics,
    cmd_decrypt,
    cmd_import_mobile,
    cmd_memory_analyze,
    cmd_pcap_analyze,
)

# P1-4 — integrita/původ přesunuty do cli/commands/integrity.py (re-export)
from .commands.integrity import (
    cmd_graph,
    cmd_integrity_keys,
    cmd_provenance,
    cmd_rotate_key,
    cmd_seal,
    cmd_verify,
)

# P2-5 — Threat Intelligence Workspace v cli/commands/intel.py
from .commands.intel import cmd_intel_import, cmd_intel_match

# P1-4 — životní cyklus případu přesunut do cli/commands/lifecycle.py (re-export)
from .commands.lifecycle import cmd_analyze, cmd_audit, cmd_backup, cmd_validate

# P1-4 — plugin ekosystém přesunut do cli/commands/plugins.py (re-export)
from .commands.plugins import (
    cmd_plugin_info,
    cmd_plugin_list,
    cmd_plugin_run,
    cmd_plugin_run_entry,
    cmd_plugin_verify,
)

# P2-2 — Centrální registr případů v cli/commands/registry.py
from .commands.registry import cmd_registry

# P1-4 — reporty/analytické rodiny přesunuty do cli/commands/report.py (re-export)
from .commands.report import (
    cmd_advanced,
    cmd_crypto_report,
    cmd_darkweb,
    cmd_onchain,
    cmd_profiles,
    cmd_report,
)

# P1-4 — reprodukovatelnost přesunuta do cli/commands/repro.py (re-export)
from .commands.repro import cmd_benchmark, cmd_integrity, cmd_replay

# P1-4 — web GUI přesunut do cli/commands/serve.py (re-export)
from .commands.serve import cmd_serve

# P2-3 — Advanced Timeline Intelligence v cli/commands/timeline_adv.py
from .commands.timeline_adv import cmd_timeline_intel

# P1-4 — write-blocker/compliance přesunuty do cli/commands/wb.py (re-export)
from .commands.wb import (
    cmd_attack_map,
    cmd_compliance,
    cmd_daubert,
    cmd_wb_attach,
    cmd_wb_remove,
    cmd_wb_status,
)

# P2-4 — Investigation Workspace přesunut do cli/commands/workspace.py
from .commands.workspace import (
    cmd_workspace_hypo_rev_add,
    cmd_workspace_hypo_rev_list,
    cmd_workspace_note_add,
    cmd_workspace_note_list,
    cmd_workspace_task_add,
    cmd_workspace_task_list,
    cmd_workspace_task_set_status,
)

# P2-6 — Cross-case Correlation v cli/commands/xcorr.py
from .commands.xcorr import cmd_xcorr

# R0.4 — příklady pro --help (AK: každý subpříkaz ukazuje reálný příklad)
_SUBCOMMAND_EXAMPLES = {
    "new": 'stopa case new "Případ 2026-014" --examiner M.Matúš',
    "auto-export": "stopa case auto-export case-abc on --interval 30",
    "auto-interval": "stopa case auto-interval case-abc 30   # nebo 'off'",
    "add": "stopa add case-abc /mnt/evidence --profile forensic --resume",
    "files": "stopa files case-abc --family image --limit 50",
    "search": 'stopa search case-abc "invoice OR *.pdf" --source src-1',
    "stats": "stopa stats case-abc",
    "verify": "stopa verify case-abc --limit 20",
    "seal": "stopa seal case-abc --reason 'před soudním předložením'",
    "integrity-keys": "stopa integrity-keys case-abc --json",
    "rotate-key": "stopa rotate-key case-abc --reason 'legace v týmu'",
    "parser-status": "stopa parser-status --format json",
    "parser-quality": "stopa parser-quality --json",
    "ai-run": "stopa ai-run <case_id> --role evidence --artifact art-1 --json",
    "provenance": "stopa provenance case-abc art-123 --json",
    "graph": "stopa graph case-abc --json   # P1-3 — Evidence Graph (hrany s důvodem a polaritou)",
    "compliance": "stopa compliance case-abc --out ./reports   # SWGDE/ISO 27037 report",
    "daubert": "stopa daubert case-abc   # F5.5 — Daubert pack (peer-reviewed reference + error rates)",
    "attack-map": "stopa attack-map case-abc --format stix --out ./map.json   # F6.3 — MITRE ATT&CK heat-mapa",
    "reparse": "stopa reparse case-abc --parser-version 2.4   # F5.3 — pinned verze + diff report",
    "wb": "stopa wb attach case-abc --device 'Tableau TBW-100'   # F5.4 — WB připojení + auto-detekce",
    "integrity": 'stopa integrity case-abc --init-key --checkpoint "před exportem"',
    "replay": "stopa replay case-abc op-123   # bez op = poslední extract",
    "benchmark": "stopa benchmark case-abc --suite all",
    "validate": "stopa validate case-abc",
    "analyze": 'stopa analyze case-abc "Kdo odeslal tento e-mail?"',
    "audit": "stopa audit case-abc -v --limit 50",
    "backup": "stopa backup case-abc --out /mnt/backup",
    "timeline": "stopa timeline case-abc --type browser_history --intel",
    "timeline-intel": "stopa timeline-intel case-abc --json   # P2-3 — gapy/outliery/korelace/nejistota",
    "xcorr": "stopa xcorr case-a case-b --entity email --user m.matous --json   # P2-6 — sdílené entity napříč případy",
    "registry": "stopa registry --user m.matous --json   # P2-2 — centrální registr případů (instance DB)",
    "exchange": "stopa exchange pack case-a --anon --key-out anon.key   # P2-7 — Case Exchange bundle v1 (+ anonymizace)",
    "correlate": "stopa correlate case-abc -v",
    "analytics": "stopa analytics case-abc --from-ts 2026-01-01T00:00:00Z --to-ts 2026-02-01T00:00:00Z",
    "image": "stopa image case-abc /path/disk.img --no-carve",
    "mobile": "stopa mobile case-abc /path/phone.img --password HESLO",
    "memory-analyze": "stopa memory-analyze case-abc /evidence/mem.raw --plugin windows.pslist",
    "pcap-analyze": "stopa pcap-analyze case-abc /evidence/capture.pcapng",
    "antiforensics-scan": "stopa antiforensics-scan case-abc [--image /evidence/disk.img]",
    "profiles": "stopa profiles",
    "report": "stopa report case-abc --format pdf --lang cs",
    "export": "stopa export case-abc --what timeline --format stix --bundle",
    "plaso-import": "stopa plaso-import case-abc /path/l2tcsv.txt",
    "timesketch-push": "stopa timesketch-push case-abc --what timeline --limit 1000",
    "advanced": "stopa advanced case-abc --file /tmp/tx.json",
    "decrypt": "stopa decrypt /path/vhd --type bitlocker --recovery-key KLIC",
    "import-mobile": "stopa import-mobile case-abc /tmp/export.zip --source adb",
    "onchain": "stopa onchain case-abc --etherscan-key KEY --depth 2",
    "darkweb": "stopa darkweb case-abc --file /tmp/tx.json",
    "crypto-report": "stopa crypto-report case-abc --format html",
    "serve": "stopa serve --port 8473",
    "install": "stopa install --dry-run   # nebo: stopa install (bez --dry-run)",
}


def _ex_sub(subparsers, name: str, *args, example=None, **kwargs) -> argparse.ArgumentParser:
    """add_parser + epilog s příkladem (R0.4).

    Explicitní ``example`` má přednost před záznamem v tabulce podle jména
    (podřízené subpříkazy sdílejí holá jména napříč skupinami); bez příkladu
    vrací parser beze změny.
    """
    p = subparsers.add_parser(name, *args, **kwargs)
    if example is None:
        example = _SUBCOMMAND_EXAMPLES.get(name)
    if example:
        p.formatter_class = argparse.RawDescriptionHelpFormatter
        p.epilog = f"Příklad:\n  {example}"
    return p


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stopa", description=__doc__.splitlines()[0])
    # R0.3 — `stopa --version` vrací verzi balíčku (importlib metadata, dev fallback).
    try:
        from importlib.metadata import version as _pkg_version

        _ver = _pkg_version("stopa")
    except Exception:  # noqa: BLE001 — dev run bez instalace / chybějící metadata
        from stopa import __version__ as _ver
    parser.add_argument("--version", action="version", version=f"stopa {_ver}")
    sub = parser.add_subparsers(dest="command", required=True)

    case_p = _ex_sub(sub, "case", help="správa případů")
    case_sub = case_p.add_subparsers(dest="case_cmd", required=True)
    new_p = _ex_sub(case_sub, "new", help="vytvořit nový případ")
    new_p.add_argument("name", help="název případu")
    new_p.add_argument("--examiner", help="jméno znalce")
    new_p.add_argument("--notes", help="poznámky k případu")
    _add_json_flag(new_p)
    new_p.set_defaults(func=cmd_case_new)

    # STP-069 — opt-in automatický ZIP bundle po dokončení analýzy.
    autoexp_p = _ex_sub(case_sub, "auto-export", help="zapnout/vypnut automatický export (STP-069)"
    )
    autoexp_p.add_argument("case_id", help="ID případu")
    autoexp_p.add_argument("state", choices=["on", "off"], help="on = zapnout, off = vypnout")
    # STP-070 — volitelný interval periodického auto-bundle (minuty).
    autoexp_p.add_argument(
        "--interval",
        type=int,
        default=None,
        metavar="MINUTY",
        help="STP-070: interval periodického auto-bundle v minutách (5–43200)",
    )
    _add_json_flag(autoexp_p)
    autoexp_p.set_defaults(func=cmd_case_auto_export)

    # STP-070 — nastavení/vymazání intervalu periodického auto-bundle.
    autoint_p = _ex_sub(case_sub, "auto-interval", help="nastavit interval periodického auto-bundle (STP-070)"
    )
    autoint_p.add_argument("case_id", help="ID případu")
    autoint_p.add_argument(
        "minutes",
        help="interval v minutách (5–43200) nebo 'off' pro vymazání",
    )
    _add_json_flag(autoint_p)
    autoint_p.set_defaults(func=cmd_case_auto_interval)

    add_p = _ex_sub(sub, "add", help="přidat zdroj důkazů a zpracovat")
    add_p.add_argument("case_id", help="ID případu (z 'stopa case new')")
    add_p.add_argument("paths", nargs="+", help="složky nebo soubory ke zpracování")
    add_p.add_argument("--profile", default="forensic", choices=sorted(PROFILES),
                       help="processing profil (default: forensic)")
    add_p.add_argument("--hash-set", action="append", metavar="FILE",
                       help="known-bad hash set (text, 1 hash/řádek) — lze opakovat")
    add_p.add_argument("--custodian", default=None,
                       help="kdo nabytí důkazu eviduje (chain of custody)")
    add_p.add_argument("--method", default=None,
                       help="metoda nabytí (např. 'forensic copy', 'USB export')")
    add_p.add_argument("--resume", action="store_true",
                       help="E3 checkpointing — přeskočit soubory už v DB "
                            "(pokračovat po přerušeném běhu)")
    add_p.add_argument("--workers", type=int, default=None, metavar="N",
                       help="F2.4 počet worker procesů/vláken (default: min(8, jádra CPU))")
    add_p.add_argument("--pool", choices=["auto", "threads", "processes"], default="auto",
                       help="F2.4 typ poolu: auto = procesy pro N>1 (GIL), threads = E3 režim")
    add_p.add_argument("--disk-budget", type=int, default=0, metavar="MB",
                       help="P2-1 disk budget in-flight souborů v MB (kapacitní řízení; 0 = bez limitu)")
    _add_json_flag(add_p)
    add_p.set_defaults(func=cmd_add)

    files_p = _ex_sub(sub, "files", help="seznam souborů v případu")
    files_p.add_argument("case_id")
    files_p.add_argument("--bad-ext", action="store_true", help="jen soubory s rozpornou příponou")
    files_p.add_argument("--dups", action="store_true", help="jen duplikáty")
    files_p.add_argument("--family", choices=["image", "document", "audio", "video", "media",
                                              "archive", "executable", "database", "compound"],
                         help="filtr podle rodiny signatury")
    files_p.add_argument("--limit", type=int, default=100)
    _add_json_flag(files_p)
    files_p.set_defaults(func=cmd_files)

    search_p = _ex_sub(sub, "search", help="full-text search (FTS5) napříč případem")
    search_p.add_argument("case_id")
    search_p.add_argument(
        "query",
        help='dotaz — FTS5 syntaxe: "fráze", *.jpg, pdf OR docx; jinak implicitní AND',
    )
    search_p.add_argument("--source", help="filtr podle evidence source ID")
    search_p.add_argument("--limit", type=int, default=100)
    # P3-1 Advanced Search — volitelné strukturované filtry; bez flagů = stávající chování
    search_p.add_argument(
        "--kind", help="filtr podle signatury (soubory: signature_type, např. PDF)"
    )
    search_p.add_argument(
        "--entity", help="soubor s artefaktem přímo spojeným danou entitou (graf vztahů)"
    )
    search_p.add_argument("--size-min", type=int, help="minimální velikost v B (včetně)")
    search_p.add_argument("--size-max", type=int, help="maximální velikost v B (včetně)")
    search_p.add_argument("--mtime-from", help="od data (ISO 8601, včetně)")
    search_p.add_argument("--mtime-to", help="do data (ISO 8601, včetně)")
    search_p.add_argument(
        "--rel-depth",
        type=int,
        choices=(1, 2, 3),
        help="procházet graf vztahů od výsledků (hloubka 1..3)",
    )
    _add_json_flag(search_p)
    search_p.set_defaults(func=cmd_search)

    stats_p = _ex_sub(sub, "stats", help="shrnutí případu")
    stats_p.add_argument("case_id")
    _add_json_flag(stats_p)
    stats_p.set_defaults(func=cmd_stats)

    ver_p = _ex_sub(sub, "verify", help="E1 — re-hash všech souborů a kontrola integrity (SHA-256/MD5)")
    ver_p.add_argument("case_id")
    ver_p.add_argument("--limit", type=int, default=20,
                       help="max. počet zobrazených problémů (default: 20)")
    _add_json_flag(ver_p)
    ver_p.set_defaults(func=cmd_verify)

    seal_p = _ex_sub(sub, "seal",
                     help="F5.1 — Merkle zamčení případu (snapshot stavu zamčený podepsaným kořenem)")
    seal_p.add_argument("case_id")
    seal_p.add_argument("--reason", metavar="DUVOD", default=None,
                        help="důvod zamčení (např. 'před soudním předložením')")
    _add_json_flag(seal_p)
    seal_p.set_defaults(func=cmd_seal)

    ik_p = _ex_sub(sub, "integrity-keys",
                   help="P0-2 — export Ed25519 integrity klíče případu (nezávislá verifikace)")
    ik_p.add_argument("case_id")
    _add_json_flag(ik_p)
    ik_p.set_defaults(func=cmd_integrity_keys)

    rk_p = _ex_sub(sub, "rotate-key",
                   help="P0-2 — rotace Ed25519 integrity klíče (staré body zůstávají ověřitelné)")
    rk_p.add_argument("case_id")
    rk_p.add_argument("--reason", metavar="DUVOD", default=None,
                      help="důvod rotace (ukládá se do rotačního kontrolního bodu)")
    _add_json_flag(rk_p)
    rk_p.set_defaults(func=cmd_rotate_key)

    q_p = _ex_sub(sub, "parser-quality",
                  help="P1-1 — per-parser quality coverage (8 kategorií; exit 2 = pod --fail-below)")
    q_p.add_argument("--format", choices=["text", "json"], default="text",
                     help="formát výstupu (default: textová tabulka)")
    _add_json_flag(q_p)
    q_p.add_argument("--fail-below", type=float, metavar="PCT",
                     help="CI gate: exit 2, pokud category_coverage_pct < PCT (např. 60)")
    q_p.set_defaults(func=cmd_parser_quality)

    from stopa.domain.ai_orchestrator import ROLE_IDS as _AI_ROLE_IDS

    ai_p = _ex_sub(sub, "ai-run",
                   help="P1-2 — AI role agenta nad důkazy případu (LM Studio; exit 2 = výstup bez validace)")
    ai_p.add_argument("case_id")
    ai_p.add_argument("--role", required=True, choices=_AI_ROLE_IDS,
                      help="AI role (minimální oprávnění per doména)")
    ai_p.add_argument("--question", metavar="OTAZKA", default="",
                      help="otázka pro roli (volitelné; implicitní = analyzuj důkaz)")
    ai_p.add_argument("--artifact", action="append", metavar="ID",
                      help="explicitní artefakt jako důkaz (opakovatelné; "
                           "default = poslední 5 artefaktů chronologicky)")
    _add_json_flag(ai_p)
    ai_p.set_defaults(func=cmd_ai_run)

    ps_p = _ex_sub(sub, "parser-status",
                   help="P0-4 validation lab — per-parser validační status (C3 registry + testy)")
    ps_p.add_argument("--format", choices=["text", "json"], default="text",
                      help="formát výstupu (default: textová tabulka)")
    _add_json_flag(ps_p)
    ps_p.add_argument("--fail-on-unvalidated", action="store_true",
                      help="CI gate: exit 2, pokud existují unvalidované parserty")
    ps_p.set_defaults(func=cmd_parser_status)

    prov_p = _ex_sub(sub, "provenance",
                     help="P0-1 — řetězec provenience artefaktu (kroky + mezery; exit 2 = neúplný)")
    prov_p.add_argument("case_id")
    prov_p.add_argument("artifact_id")
    _add_json_flag(prov_p)
    prov_p.set_defaults(func=cmd_provenance)

    graph_p = _ex_sub(sub, "graph",
                      help="P1-3 — unifikovaný Evidence Graph (důkaz↔entita↔událost↔zjištění)")
    graph_p.add_argument("case_id")
    _add_json_flag(graph_p)
    graph_p.set_defaults(func=cmd_graph)

    # P2-4 — Investigation Workspace: poznámky / úkoly / revize hypotéz (hash chain)
    ws_p = sub.add_parser(
        "workspace", help="P2-4 — investigation workspace (note/task/hypo-rev)"
    )
    ws_sub = ws_p.add_subparsers(dest="workspace_cmd", required=True, metavar="<podprikaz>")

    # note — poznámky ukotvené na reference (druh:id)
    ws_note_p = ws_sub.add_parser("note", help="Poznámky ukotvené na artefakt/entity/událost")
    ws_note_sub = ws_note_p.add_subparsers(dest="note_cmd", required=True, metavar="<akce>")
    wna_p = _ex_sub(
        ws_note_sub, "add",
        help="přidat poznámku (reference druh:id)",
        example='stopa workspace note add case-abc --ref artifact:art-123 --text "poznamka" --author M.Matúš',
    )
    wna_p.add_argument("case_id")
    wna_p.add_argument("--ref", required=True, metavar="DRUH:ID",
                       help="ukotvení: artifact|entity|timeline_event : ID objektu")
    wna_p.add_argument("--text", required=True, help="text poznámky")
    wna_p.add_argument("--author", default=None, help="autor (volitelné)")
    _add_json_flag(wna_p)
    wna_p.set_defaults(func=cmd_workspace_note_add)
    wnl_p = _ex_sub(
        ws_note_sub, "list", help="seznam poznámek případu",
        example="stopa workspace note list case-abc --json",
    )
    wnl_p.add_argument("case_id")
    _add_json_flag(wnl_p)
    wnl_p.set_defaults(func=cmd_workspace_note_list)

    # task — úkoly se stavovým automatem open → in_progress → done
    ws_task_p = ws_sub.add_parser("task", help="Úkoly (open/in_progress/done)")
    ws_task_sub = ws_task_p.add_subparsers(dest="task_cmd", required=True, metavar="<akce>")
    wta_p = _ex_sub(
        ws_task_sub, "add", help="přidat úkol",
        example='stopa workspace task add case-abc --title "ověřit hash" --assignee M.Matúš --due 2026-12-31T23:59:59',
    )
    wta_p.add_argument("case_id")
    wta_p.add_argument("--title", required=True, help="název úkolu")
    wta_p.add_argument("--assignee", default=None, help="přidělený (volitelné)")
    wta_p.add_argument("--due", default=None, metavar="ISO", help="datum splatnosti ISO (volitelné)")
    _add_json_flag(wta_p)
    wta_p.set_defaults(func=cmd_workspace_task_add)
    wts_p = _ex_sub(
        ws_task_sub, "set-status", help="přepsat stav úkolu",
        example="stopa workspace task set-status case-abc --task 12 --status done",
    )
    wts_p.add_argument("case_id")
    wts_p.add_argument("--task", required=True, type=int, dest="task_id", metavar="ID", help="ID úkolu")
    wts_p.add_argument("--status", required=True, choices=TASK_STATUSES, help="nový stav")
    _add_json_flag(wts_p)
    wts_p.set_defaults(func=cmd_workspace_task_set_status)
    wtl_p = _ex_sub(
        ws_task_sub, "list", help="seznam úkolů případu",
        example="stopa workspace task list case-abc --json",
    )
    wtl_p.add_argument("case_id")
    _add_json_flag(wtl_p)
    wtl_p.set_defaults(func=cmd_workspace_task_list)

    # hypo-rev — revize hypotéz jako append-only hash chain
    ws_hr_p = ws_sub.add_parser(
        "hypo-rev", help="Revize hypotéz (append-only hash chain, tamper detekce)"
    )
    ws_hr_sub = ws_hr_p.add_subparsers(dest="hyporev_cmd", required=True, metavar="<akce>")
    wha_p = _ex_sub(
        ws_hr_sub, "add", help="přidat příští revizi hypotézy (claim → deterministický hash)",
        example='stopa workspace hypo-rev add case-abc --hypothesis hyp-1 --claim "uživatel online v 10:00" --author M.Matúš',
    )
    wha_p.add_argument("case_id")
    wha_p.add_argument("--hypothesis", required=True, metavar="ID", help="ID hypotézy")
    wha_p.add_argument("--claim", required=True, help="obsah revize (tvrzení)")
    wha_p.add_argument("--author", default=None, help="autor (volitelné)")
    _add_json_flag(wha_p)
    wha_p.set_defaults(func=cmd_workspace_hypo_rev_add)
    whl_p = _ex_sub(
        ws_hr_sub, "list", help="seznam revizí; --check-chain ověří hash chain (exit 2 = porušení)",
        example="stopa workspace hypo-rev list case-abc --hypothesis hyp-1 --check-chain",
    )
    whl_p.add_argument("case_id")
    whl_p.add_argument("--hypothesis", default=None, metavar="ID", help="filtr na jednu hypotézu (volitelné)")
    whl_p.add_argument("--check-chain", action="store_true",
                       help="ověřit append-only hash chain; exit 2 = porušený řetězec")
    _add_json_flag(whl_p)
    whl_p.set_defaults(func=cmd_workspace_hypo_rev_list)

    comp_p = _ex_sub(sub, "compliance",
                     help="F5.2 — SWGDE/ISO 27037 compliance report (JSON+PDF, Ed25519 podpis)")
    comp_p.add_argument("case_id")
    comp_p.add_argument("--out", metavar="DIR", default=None,
                        help="výstupní adresář (default: složka case DB)")
    _add_json_flag(comp_p)
    comp_p.set_defaults(func=cmd_compliance)

    daubert_p = _ex_sub(
        sub, "daubert",
        help="F5.5 — Daubert challenge preparedness pack (1-click JSON pro soud)",
    )
    daubert_p.add_argument("case_id")
    daubert_p.add_argument("--out", metavar="DIR", default=None,
                           help="výstupní adresář (default: složka case DB)")
    _add_json_flag(daubert_p)
    daubert_p.set_defaults(func=cmd_daubert)

    attack_map_p = _ex_sub(
        sub, "attack-map",
        help="F6.3 — MITRE ATT&CK mapping: heat-mapa taktik×technik + STIX intrusion-set",
    )
    attack_map_p.add_argument("case_id")
    attack_map_p.add_argument("--format", choices=["json", "stix"], default="json",
                              help="json = heat-mapa (default); stix = intrusion-set bundle")
    attack_map_p.add_argument("--out", metavar="FILE", default=None,
                              help="výstupní soubor (default: stdout)")
    _add_json_flag(attack_map_p)
    attack_map_p.set_defaults(func=cmd_attack_map)

    # F6.4 — Plugin ecosystem
    plg_p = sub.add_parser("plugin", help="F6.4 — plugin ecosystem (list/info/verify/run)")
    plg_sub = plg_p.add_subparsers(dest="plugin_cmd", required=True, metavar="<podprikaz>")
    plg_list = _ex_sub(
        plg_sub, "list", help="seznam detekovaných pluginů", example="stopa plugin list --json"
    )
    _add_json_flag(plg_list)
    plg_list.set_defaults(func=cmd_plugin_list)
    plg_info = _ex_sub(
        plg_sub, "info", help="detail jednoho pluginu", example="stopa plugin info myplug --json"
    )
    plg_info.add_argument("name")
    _add_json_flag(plg_info)
    plg_info.set_defaults(func=cmd_plugin_info)
    plg_verify = _ex_sub(
        plg_sub,
        "verify",
        help="správa allowlistu ověřených pluginů (settings.json plugins_verified)",
        example="stopa plugin verify myplug --add",
    )
    plg_verify.add_argument("name")
    _plg_vgroup = plg_verify.add_mutually_exclusive_group(required=True)
    _plg_vgroup.add_argument("--add", action="store_true", help="přidat do allowlistu (in-process)")
    _plg_vgroup.add_argument("--remove", action="store_true", help="odebrat ze allowlistu (sandbox)")
    plg_verify.set_defaults(func=cmd_plugin_verify)
    plg_run = _ex_sub(
        plg_sub,
        "run",
        help="běh kapacity pluginu (neověřený → sandbox)",
        example="stopa plugin run myplug --cap extractor --key K1 --file /tmp/f.txt",
    )
    plg_run.add_argument("name")

    def _plg_cap_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--cap", choices=["extractor", "triage_profile", "ai_tool"], required=True,
                       help="kapacita k běhu")
        p.add_argument("--key", default=None, help="klíč extractoru (pro --cap extractor)")
        p.add_argument("--file", dest="files", action="append", default=[], metavar="FILE",
                       help="soubor pro extractor (zopakovatelné; pro --cap extractor)")
        p.add_argument("--tool", default=None, help="jméno AI toolu (pro --cap ai_tool)")
        p.add_argument("--case-id", dest="case_id", default=None,
                       help="case ID (vyžadováno pro --cap ai_tool)")
        p.add_argument("--params", default="{}", help="JSON parametry AI toolu")

    _plg_cap_args(plg_run)
    _add_json_flag(plg_run)
    plg_run.set_defaults(func=cmd_plugin_run)

    # skrytý interní entry point pro sandbox subprocess (přímý běh, JSON stdout)
    prun_p = sub.add_parser("plugin-run", help=argparse.SUPPRESS)
    prun_p.add_argument("name")
    _plg_cap_args(prun_p)
    prun_p.set_defaults(func=cmd_plugin_run_entry)

    rp_p = _ex_sub(sub, "reparse",
                   help="F5.3 — re-run extrakce s deklarovánou verzí parseru + diff report")
    rp_p.add_argument("case_id")
    rp_p.add_argument("--source-id", default=None, metavar="ID",
                      help="zdroj (default: zdroj nejnovější extract operace)")
    rp_p.add_argument("--parser-version", required=True, metavar="V",
                      help="prokládaná verze parserové sady (pinned provenience)")
    rp_p.add_argument("--workdir", default=None, metavar="DIR",
                      help="umístění dočasné reparse DB (default: systémový tmp)")
    _add_json_flag(rp_p)
    rp_p.set_defaults(func=cmd_reparse)

    # F5.4 — write-blocker integration API (status/attach/remove + ingest gate)
    wb_p = _ex_sub(sub, "wb", help="F5.4 — write-blocker: status/attach/remove")
    wb_sub = wb_p.add_subparsers(dest="wb_cmd", required=True)
    wbs_p = _ex_sub(
        wb_sub, "status", help="aktuální WB stav + rozhodnutí brány (exit 2 = blokováno)",
        example="stopa wb status case-abc --json",
    )
    wbs_p.add_argument("case_id")
    _add_json_flag(wbs_p)
    wbs_p.set_defaults(func=cmd_wb_status)
    wba_p = _ex_sub(
        wb_sub, "attach", help="zaznamenat připojení WB (auto-detekce vendoru z --device)",
        example="stopa wb attach case-abc --device 'Tableau TBW-100'",
    )
    wba_p.add_argument("case_id")
    wba_p.add_argument("--device", default=None, metavar="DEV",
                       help="zařízení/product string (např. 'Tableau TBW-100')")
    wba_p.add_argument("--vendor", default=None, choices=known_vendor_ids(),
                       help="explicitní vendor (když auto-detekce nestačí)")
    wba_p.add_argument("--product", default=None, metavar="P",
                       help="model WB (volitelné)")
    wba_p.add_argument("--notes", default=None, metavar="N",
                       help="volný text poznámky")
    _add_json_flag(wba_p)
    wba_p.set_defaults(func=cmd_wb_attach)
    wbm_p = _ex_sub(
        wb_sub, "remove", help="zaznamenat odebrání WB", example="stopa wb remove case-abc"
    )
    wbm_p.add_argument("case_id")
    wbm_p.add_argument("--reason", default=None, metavar="R",
                       help="důvod odebrání (volitelné)")
    _add_json_flag(wbm_p)
    wbm_p.set_defaults(func=cmd_wb_remove)

    int_p = _ex_sub(sub, "integrity", help="P0 C4 — Evidence Integrity 2.0 (hash chaining + Ed25519 kontrolní body)"
    )
    int_p.add_argument("case_id")
    int_p.add_argument("--init-key", action="store_true",
                       help="vygenerovat Ed25519 klíčový pár případu (idempotentní)")
    int_p.add_argument("--checkpoint", metavar="DUVOD", default=None,
                       help="uložit nový kontrolní bod s uvedeným důvodem")
    _add_json_flag(int_p)
    int_p.set_defaults(func=cmd_integrity)

    rep_p = _ex_sub(sub, "replay", help="P0 C5 — Reproducibility Engine (opakovat operaci + porovnání výsledků)"
    )
    rep_p.add_argument("case_id")
    rep_p.add_argument("op", nargs="?", default=None,
                       help="ID operace (default: poslední extract)")
    _add_json_flag(rep_p)
    rep_p.set_defaults(func=cmd_replay)

    bm_p = _ex_sub(sub, "benchmark", help="P0 C6 — Benchmark Engine (deterministické benchmarky + regresní detekce)"
    )
    bm_p.add_argument("case_id", nargs="?", default=None,
                      help="případ pro historii/regrese (volitelné)")
    bm_p.add_argument("--suite", choices=["core", "parsers", "all"], default="core")
    _add_json_flag(bm_p)
    bm_p.set_defaults(func=cmd_benchmark)

    val_p = _ex_sub(sub, "validate", help="P0 C6 — Evidence Validation Report (parser × validace)"
    )
    val_p.add_argument("case_id")
    _add_json_flag(val_p)
    val_p.set_defaults(func=cmd_validate)

    ana_p = _ex_sub(sub, "analyze", help="P0 Intelligence I1 — AI orchestrace (5 agentů, auto/explicitní routing)"
    )
    ana_p.add_argument("case_id")
    ana_p.add_argument("question", help="analytický dotaz (čeština)")
    ana_p.add_argument(
        "--agent",
        choices=["case_analyst", "timeline_analyst", "artifact_analyst", "media_analyst", "report_analyst"],
        default=None,
        help="explicitní agent (default: auto-routing podle dotazu)",
    )
    _add_json_flag(ana_p)
    ana_p.set_defaults(func=cmd_analyze)

    aud_p = _ex_sub(sub, "audit", help="E1 — neměnná stopa operací (audit trail)")
    aud_p.add_argument("case_id")
    aud_p.add_argument("--limit", type=int, default=50,
                       help="max. počet záznamů (default: 50)")
    aud_p.add_argument("--offset", type=int, default=None,
                       help="posun od nejnovějšího záznamu")
    aud_p.add_argument("-v", "--verbose", action="store_true",
                       help="zobrazit i detaily operací (JSON)")
    _add_json_flag(aud_p)
    aud_p.set_defaults(func=cmd_audit)

    bak_p = _ex_sub(sub, "backup", help="E1 — záloha case DB (SQLite .backup, integrity check)")
    bak_p.add_argument("case_id")
    bak_p.add_argument("--out", metavar="DIR",
                       help="výstupní složka (default: backups/ vedle case DB)")
    _add_json_flag(bak_p)
    bak_p.set_defaults(func=cmd_backup)

    tl_p = _ex_sub(sub, "timeline", help="AXIOM-style timeline extrahovaných artifactů")
    tl_p.add_argument("case_id")
    tl_p.add_argument("--source", help="filtr podle evidence source ID")
    tl_p.add_argument("--type", dest="type", help="filtr podle typu artifactu (např. browser_history)")
    tl_p.add_argument("--path", help="filtr — cesta obsahuje text (LIKE %%text%%)")
    tl_p.add_argument("--limit", type=int, default=100)
    tl_p.add_argument("-v", "--verbose", action="store_true", help="zobrazit i zdrojové cesty")
    # STP-018 Timeline Intelligence 2.0 — post-pass: rozpory + duplikáty napříč zdroji
    tl_p.add_argument("--intel", action="store_true",
                      help="spustit Timeline Intelligence 2.0 (rozpory + duplikáty) a vypsat analytické skupiny")
    tl_p.add_argument("--window", type=float, default=60.0, metavar="SEC",
                      help="časové okno pro detekci rozporů v sekundách (default 60)")
    _add_json_flag(tl_p)
    tl_p.set_defaults(func=cmd_timeline)

    # P2-3 — Advanced Timeline Intelligence: IQR gapy/outliery + cross-source
    # korelace (E4 confidence) + vysvětlení nejistoty nad celou timeline.
    tli_p = _ex_sub(
        sub, "timeline-intel",
        help="P2-3 — pokročilá timeline intelligence (gapy/outliery/korelace/nejistota)",
    )
    tli_p.add_argument("case_id")
    _add_json_flag(tli_p)
    tli_p.set_defaults(func=cmd_timeline_intel)

    # P2-6 — Cross-case Correlation: sdílené entity napříč případy (read-only,
    # tenancy pravidla, audit hash chain). Exit 0 OK / 1 chyba / 2 bez oprávnění.
    xc_p = _ex_sub(
        sub, "xcorr",
        help="P2-6 — sdílené entity napříč případy (read-only + tenancy + audit)",
        example="stopa xcorr case-a case-b --entity email --json   # nebo: stopa xcorr --all --user m.matous",
    )
    xc_p.add_argument("case_a", nargs="?", help="první případ (pouze s case_b; jinak --all)")
    xc_p.add_argument("case_b", nargs="?", help="druhý případ")
    xc_p.add_argument("--all", action="store_true", dest="all",
                      help="dotázat všechny případy v STOPA_DB_DIR (min. 2)")
    xc_p.add_argument("--entity", choices=["email", "tel", "hash"], default=None,
                      help="filtr druhu entity (default: všechny)")
    xc_p.add_argument("--user", metavar="USERNAME", default=None,
                      help="identita multi-user režimu (bez ní fail-closed exit 2)")
    _add_json_flag(xc_p)
    xc_p.set_defaults(func=cmd_xcorr)

    # P2-2 — Centrální registr případů: instance-level seznam případů + tenancy
    # izolace (+ explicitní sync jednotlivého případu). Exit 0 OK / 1 chyba / 2 bez oprávnění.
    reg_p = _ex_sub(
        sub, "registry",
        help="P2-2 — centrální registr případů (instance DB; tenancy izolace)",
        example="stopa registry --user m.matous --json   # nebo: stopa registry --sync case-abc",
    )
    reg_p.add_argument("--tenant", metavar="ORG_ID", default=None,
                       help="filtr podle tenant organizace (org ID)")
    reg_p.add_argument("--user", metavar="USERNAME", default=None,
                       help="identita multi-user režimu (bez ní fail-closed exit 2)")
    reg_p.add_argument("--sync", metavar="CASE_ID", default=None,
                       help="explicitní sync jednoho případu do registru (idempotentní)")
    _add_json_flag(reg_p)
    reg_p.set_defaults(func=cmd_registry)

    # P2-5 — Threat Intelligence Workspace: per-případový IoC feed (STIX 2.1) +
    # deterministické matching × artefakty/entities. Exit 0 OK / 1 chyba/prázdný feed.
    intel_p = _ex_sub(
        sub, "intel",
        help="P2-5 — Threat Intelligence Workspace (IoC feed STIX 2.1 + matching)",
        example="stopa intel match case-abc --json",
    )
    intel_sub = intel_p.add_subparsers(dest="intel_cmd", required=True, metavar="<podprikaz>")

    ii_p = _ex_sub(
        intel_sub, "import",
        help="Import IoC do feedu případu (--stix FILE nebo --ioc KIND:HODNOTA[,…])",
        example="stopa intel import case-abc --ioc domain:evil.example.com,hash:aabbccdd --tlp AMBER --source feed-a --json",
    )
    ii_p.add_argument("case_id", help="ID případu")
    ii_p.add_argument("--stix", metavar="FILE", default=None,
                      help="STIX 2.1 bundle (soubor; import fail-closed)")
    ii_p.add_argument("--ioc", metavar="KIND:HODNOTA[,...]", default=None,
                      help="IoC ve tvaru KIND:HODNOTA (kind ∈ ip|domain|hash|url), čárkou oddělené")
    ii_p.add_argument("--tlp", choices=["WHITE", "GREEN", "AMBER", "RED"], default="GREEN",
                      help="TLP level pro položky --ioc (default GREEN)")
    ii_p.add_argument("--source", metavar="SOURCE", default=None,
                      help="zdroj intel datu (metadata feedu)")
    _add_json_flag(ii_p)
    ii_p.set_defaults(func=cmd_intel_import)

    im_p = _ex_sub(
        intel_sub, "match",
        help="Deterministické matching IoC feedu případu × artefakty/entities",
        example="stopa intel match case-abc --json",
    )
    im_p.add_argument("case_id", help="ID případu")
    _add_json_flag(im_p)
    im_p.set_defaults(func=cmd_intel_match)

    # P2-7 — Case Exchange bundle v1 (pack/verify, volitelná anonymizace). Exit 0 OK / 1 chyba.
    exchange_p = _ex_sub(
        sub, "exchange",
        help="P2-7 — Case Exchange bundle v1 (pack/verify marketplace, volitelná anonymizace)",
        example="stopa exchange pack case-a --anon --key-out anon.key   # nebo: stopa exchange verify bundle.json --root root=BASE64",
    )
    exchange_sub = exchange_p.add_subparsers(dest="exchange_cmd", required=True, metavar="<podprikaz>")

    ex_pack = _ex_sub(
        exchange_sub, "pack",
        help="Pack případu do exchange bundle v1 (volitelně anonymizovaný)",
        example="stopa exchange pack case-a --anon --key-out anon.key --out bundle.json",
    )
    ex_pack.add_argument("case_id", help="ID případu")
    ex_pack.add_argument("--out", metavar="FILE", default=None,
                         help="výstupní soubor (default stdout)")
    ex_pack.add_argument("--anon", action="store_true",
                         help="anonymizované entity (mapping se do bundle nedostává)")
    ex_pack.add_argument("--key-file", metavar="FILE", default=None,
                         help="soubor klíče anonymizace (base64)")
    ex_pack.add_argument("--key-out", metavar="FILE", default=None,
                         help="kam uložit nově vygenerovaný klíč (povinné pro --anon bez --key-file)")
    _add_json_flag(ex_pack)
    ex_pack.set_defaults(func=cmd_exchange_pack)

    ex_ver = _ex_sub(
        exchange_sub, "verify",
        help="Ověření bundle v1 proti trust rootům (tamper → exit 1)",
        example="stopa exchange verify bundle.json --root stopa-root=PUB_BASE64 --json",
    )
    ex_ver.add_argument("bundle_file", help="cesta k bundle (JSON)")
    ex_ver.add_argument("--roots", metavar="FILE", default=None,
                        help="soubor trust rootů (JSON {label: public_b64})")
    ex_ver.add_argument("--root", action="append", default=[], metavar="LABEL=BASE64",
                        help="trust kořen LABEL=public key base64 (opakovatelné)")
    _add_json_flag(ex_ver)
    ex_ver.set_defaults(func=cmd_exchange_verify)

    cor_p = _ex_sub(sub, "correlate", help="E4 — Entity + Correlation Engine (explicitní krok)")
    cor_p.add_argument("case_id")
    cor_p.add_argument("-v", "--verbose", action="store_true",
                       help="zobrazit detail propojení s evidence listy")
    _add_json_flag(cor_p)
    cor_p.set_defaults(func=cmd_correlate)

    an_p = _ex_sub(sub, "analytics", help="F2.2 — DuckDB OLAP analytics nad timeline (agregace, histogram)")
    an_p.add_argument("case_id")
    an_p.add_argument("--from-ts", dest="from_ts", metavar="ISO", help="začátek okna (UTC ISO 8601)")
    an_p.add_argument("--to-ts", dest="to_ts", metavar="ISO", help="konec okna (UTC ISO 8601)")
    an_p.add_argument("--type", dest="type", help="filtr podle typu události")
    an_p.add_argument("--limit", type=int, default=100)
    an_p.add_argument(
        "--dedupe", action="store_true",
        help="F2.3 — CDC bloky souborových zdrojů + úspora deduplikace (block_hashes)",
    )
    _add_json_flag(an_p)
    an_p.set_defaults(func=cmd_analytics)

    img_p = _ex_sub(sub, "image", help="disk image (RAW/E01) — TSK file systems + carving")
    img_p.add_argument("case_id")
    img_p.add_argument("path", help="cesta k diskovému obrazu (.img/.dd/.raw/.e01)")
    img_p.add_argument("--profile", default="forensic", choices=sorted(PROFILES),
                       help="processing profil (default: forensic)")
    img_p.add_argument("--no-carve", action="store_true",
                       help="přeskočit carving nealokovaného prostoru")
    _add_json_flag(img_p)
    img_p.set_defaults(func=cmd_image)

    mob_p = _ex_sub(sub, "mobile", help="mobilní physical obraz — FDE/FBE unlock + TSK")
    mob_p.add_argument("case_id")
    mob_p.add_argument("path", help="cesta k mobilnímu obrazu (.img/.dd, volitelně FDE)")
    mob_p.add_argument("--password", metavar="HESLO", default=None,
                       help="FDE/FBE heslo (pokud je obraz šifrovaný)")
    mob_p.add_argument("--keyfile", metavar="SOUBOR", default=None,
                       help="extrahovaný klíč / passphrase soubor (má prioritu před --password)")
    mob_p.add_argument("--fde-type", choices=["bitlocker", "filevault"], default=None,
                       help="F1.1 — explicitní typ reálného FDE obrazu (libbde/libfvde); "
                            "syntetické formáty se detekují z magic automaticky")
    mob_p.add_argument("--recovery-key", metavar="KLÍČ", default=None,
                       help="F1.1 — BitLocker recovery key (primární cesta dle ROADMAP V2)")
    mob_p.add_argument("--profile", default="forensic", choices=sorted(PROFILES),
                       help="processing profil (default: forensic)")
    mob_p.add_argument("--no-carve", action="store_true",
                       help="přeskočit carving nealokovaného prostoru")
    _add_json_flag(mob_p)
    mob_p.set_defaults(func=cmd_mobile)

    dec_p = _ex_sub(sub, "decrypt", help="F1.1 — BitLocker/FileVault dešifrování (libbde/libfvde + STOPABLOCK)")
    dec_p.add_argument("image", help="cesta k šifrovanému obrazu")
    dec_p.add_argument("--type", choices=["bitlocker", "filevault"], default=None,
                       help="typ FDE obrazu (pokud není detekován z magic STOPABLK)")
    dec_p.add_argument("--recovery-key", metavar="KLÍČ", default=None,
                       help="BitLocker recovery key (48místný; primární cesta dle ROADMAP V2)")
    dec_p.add_argument("--password", metavar="HESLO", default=None,
                       help="FDE/FBE heslo")
    dec_p.add_argument("--out", metavar="SOUBOR", default=None,
                       help="výstupní plaintext (default: <obraz>.decrypted.img)")
    _add_json_flag(dec_p)
    dec_p.set_defaults(func=cmd_decrypt)

    mem_p = _ex_sub(sub, "memory-analyze", help="F1.2 — Memory Forensics přes Volatility 3 (volitelná runtime závislost)")
    mem_p.add_argument("case_id", help="ID případu")
    mem_p.add_argument("dump", help="cesta k memory dumpu (raw/LZMA/pcap)")
    mem_p.add_argument("--plugin", action="append", metavar="PLUGIN", default=None,
                       help=f"vol plugin (lze opakovat; bez = výchozí {', '.join(_VOL_DEFAULT_PLUGINS)})")
    mem_p.add_argument("--with-defaults", action="store_true",
                       help="přidá výchozí sadu k explicitním --plugin volbám")
    mem_p.add_argument("--timeout", type=int, default=600, metavar="S",
                       help="deadline jednoho pluginu v sekundách (default: 600)")
    _add_json_flag(mem_p)
    mem_p.set_defaults(func=cmd_memory_analyze)

    mob_p = _ex_sub(sub, "import-mobile", help="F1.5 — Import mobilní extrakce (Cellebrite UFDR / MSAB VCF / ADB logical dump)")
    mob_p.add_argument("case_id", help="ID případu")
    mob_p.add_argument("dump", help="cesta k .ufd/.zip/složce s exportem")
    mob_p.add_argument("--source", choices=["cellebrite", "msab", "adb"], default="cellebrite",
                       help="typ zdroje (default: cellebrite)")
    _add_json_flag(mob_p)
    mob_p.set_defaults(func=cmd_import_mobile)

    pcap_p = _ex_sub(sub, "pcap-analyze", help="F1.3 — Síťová forenzika: PCAP parser + TCP reassembly + IoC (Scapy)")
    pcap_p.add_argument("case_id", help="ID případu")
    pcap_p.add_argument("pcap", help="cesta k capture (.pcap/.pcapng)")
    pcap_p.add_argument("--max-packets", type=int, default=50_000, metavar="N",
                        help="strop počtu paketů (guard proti OOM; default: 50000)")
    _add_json_flag(pcap_p)
    pcap_p.set_defaults(func=cmd_pcap_analyze)

    af_p = _ex_sub(sub, "antiforensics-scan", help="F1.4 — Anti-Forensics detekce: timestomping, log clearing, USN truncation, hidden partitions, LSB steganografie")
    af_p.add_argument("case_id", help="ID případu")
    af_p.add_argument("--image", metavar="PATH", default=None,
                      help="volitelný diskový obraz pro MBR/partition table + integrity kontrolu")
    _add_json_flag(af_p)
    af_p.set_defaults(func=cmd_antiforensics)

    prof_p = _ex_sub(sub, "profiles", help="seznam processing profilů")
    _add_json_flag(prof_p)
    prof_p.set_defaults(func=cmd_profiles)

    rep_p = _ex_sub(sub, "report", help="forenzní report (HTML/PDF) + chain of custody")
    rep_p.add_argument("case_id")
    rep_p.add_argument("--format", choices=["html", "pdf"], default="html",
                       help="výstupní formát (default: html; pdf vyžaduje weasyprint)")
    rep_p.add_argument("--out", metavar="DIR",
                       help="výstupní složka (default: reports/ vedle case DB)")
    rep_p.add_argument("--lang", choices=["cs", "en"], default=None,
                       help="jazyk reportu (E10 i18n; default: cs)")
    _add_json_flag(rep_p)
    rep_p.set_defaults(func=cmd_report)

    exp_p = _ex_sub(sub, "export", help="E10/STP-023 — export dat případu do CSV/JSON/JSONL/XML/STIX")
    exp_p.add_argument("case_id")
    exp_p.add_argument("--what", choices=["artifacts", "timeline", "correlations"],
                       default="artifacts",
                       help="co exportovat (default: artifacts)")
    exp_p.add_argument("--format", choices=["csv", "json", "jsonl", "xml", "stix", "l2tcsv", "timesketch", "uco"], default="csv",
                       help="výstupní formát (default: csv; STP-023: jsonl/xml/stix; STP-054: l2tcsv; F6.1: timesketch; STP-055: uco)")
    exp_p.add_argument("--limit", type=int, default=None,
                       help="max. počet záznamů (artifacts/timeline; default: vše)")
    exp_p.add_argument("--out", metavar="SOUBOR",
                       help="výstupní soubor (default: stdout)")
    exp_p.add_argument("--bundle", action="store_true",
                       help="STP-068 — ZIP bundle všech datasetů (manifest + SHA-256, deterministický)")
    exp_p.add_argument("--validate-stix", action="store_true", dest="validate_stix",
                       help="F6.2 — validovat STIX bundle stix2-validator (extras [stix]; "
                            "bez nainstalovaného stix2 se export nepropadá jen upozorní)")
    exp_p.set_defaults(func=cmd_export)

    oc_p = _ex_sub(sub, "onchain",
                   help="K3 On-chain analýza — clustering + graf transakcí + risk scoring (offline-first)")
    oc_p.add_argument("case_id")
    oc_p.add_argument("--api-key", default=None, metavar="KEY",
                      help="Blockchair API key — volitelná síť pro BTC (bez klíče jen cache + listy)")
    oc_p.add_argument("--etherscan-key", default=None, metavar="KEY",
                      help="Etherscan API key — volitelná síť pro ETH")
    oc_p.add_argument("--no-network", action="store_true",
                      help="použít jen cache + bundlované listy (ignorovat API klíče)")
    oc_p.add_argument("--depth", type=int, default=3,
                      help="hloubka expanze cest z high-risk adres v grafu (default: 3)")
    _add_json_flag(oc_p)
    oc_p.set_defaults(func=cmd_onchain)

    dw_p = _ex_sub(sub, "darkweb",
                   help="K4 Dark Web & Illicit Activity — ransom note + marketplace + mixer detektory")
    dw_p.add_argument("case_id")
    dw_p.add_argument("--file", action="append", default=None, metavar="SOUBOR",
                      help="skenovat konkrétní soubor (může být opakováno; default: textové zdroje případu)")
    _add_json_flag(dw_p)
    dw_p.set_defaults(func=cmd_darkweb)

    crp = _ex_sub(sub, "crypto-report",
                  help="K4.5 — SWGDE krypto report (10 sekcí; md|html|json + Ed25519 podpis)")
    crp.add_argument("case_id")
    crp.add_argument("--format", choices=["md", "html", "json"], default="md",
                     help="výstupní formát (default: md)")
    crp.add_argument("--out", metavar="SOUBOR",
                     help="výstupní soubor (default: <db_dir>/reports/<case>.crypto_report.<fmt>)")
    _add_json_flag(crp)
    crp.set_defaults(func=cmd_crypto_report)

    adv_p = _ex_sub(sub, "advanced",
                    help="K5 Advanced — DeFi + NFT + cross-chain bridge + privacy coins (+ AI copilot)")
    adv_p.add_argument("case_id")
    adv_p.add_argument("--file", action="append", default=None, metavar="SOUBOR",
                       help="skenovat konkrétní soubor (může být opakováno; default: textové zdroje případu)")
    _add_json_flag(adv_p)
    adv_p.set_defaults(func=cmd_advanced)

    pli_p = _ex_sub(sub, "plaso-import", help="STP-057 — Plaso import: l2tcsv soubor → case (source + artifacts + timeline)"
    )
    pli_p.add_argument("case_id")
    pli_p.add_argument("path", help="cesta k l2tcsv souboru (17 polí log2timeline.pl)")
    _add_json_flag(pli_p)
    pli_p.set_defaults(func=cmd_plaso_import)

    tsk_p = _ex_sub(sub, "timesketch-push",
        help="STP-059 — Timesketch push: case data → nový sketch + timeline (l2tcsv)",
    )
    tsk_p.add_argument("case_id")
    tsk_p.add_argument("--what", choices=["artifacts", "timeline", "correlations"],
                       default="timeline", help="dataset k pushnutí (default: timeline)")
    tsk_p.add_argument("--limit", type=int, default=None, metavar="N",
                       help="STP-065 — pushne jen první N záznamů datasetu (default: vše)")
    _add_json_flag(tsk_p)
    tsk_p.set_defaults(func=cmd_timesketch_push)

    srv_p = _ex_sub(sub, "serve", help="web GUI (FastAPI nad analyze())")
    srv_p.add_argument("--host", default=None,  # E12: None → settings.json → 127.0.0.1
                       help="bind address (default z Settings / 127.0.0.1)")
    srv_p.add_argument("--port", type=int, default=8473)
    srv_p.set_defaults(func=cmd_serve)

    # R0.2 — bootstrap installer: systémové závislosti + venv (detekce OS).
    ins_p = _ex_sub(sub, "install", help="R0.2 — nainstalovat systémové závislosti + venv (Ubuntu/Fedora/Alpine/macOS)")
    ins_p.add_argument("--dry-run", action="store_true",
                       help="jen vytisknout plán instalace, nic neinstalovat")
    ins_p.add_argument("--skip-system", action="store_true",
                       help="přeskočit systémové balíčky (jen venv + pip; bez sudo)")
    _add_json_flag(ins_p)
    ins_p.set_defaults(func=cmd_install)

    return parser


def cmd_install(args: argparse.Namespace) -> int:
    """R0.2 — ``stopa install``: detekce OS → plán → provedení (best-effort)."""
    from stopa import installer  # lazy — installer není v hot pathu CLI

    plan = installer.plan_install(skip_system=args.skip_system)
    if not getattr(args, "json", False):
        print(f"Detekováno: {plan.os_info.id} {plan.os_info.version}")
        for step in plan.steps:
            print(f"  - {step}")
        if args.dry_run:
            print("(dry-run — nic neinstalováno)")
            return 0
    rc = installer.run_plan(plan, dry_run=args.dry_run)
    _print_json({
        "ok": rc == 0,
        "os": plan.os_info.id,
        "version": plan.os_info.version,
        "package_manager": plan.package_manager,
        "system_packages": list(plan.system_packages),
        "needs_sudo": plan.needs_sudo,
        "venv_dir": str(plan.venv_dir),
        "dry_run": args.dry_run,
    })
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
