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
  stopa exchange pack <case_id> [--out FILE] [--anon] [--key-file F] [--key-out F] [--tlp LEVEL] [--json]  # P2-7 — Case Exchange bundle v1 (+ anonymizace, TLP)
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

from stopa.i18n import resolve_lang, set_lang, t

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
    cmd_ai_eval,
    cmd_ai_run,
    cmd_parser_quality,
    cmd_parser_status,
    cmd_reparse,
)

# P3-2 — Artifact Version Comparison (path JSON diff dvou verzí artefaktu)
from .commands.artifact_compare import cmd_compare_artifacts

# P1-4 — rodina `case` přesunuta do cli/commands/case.py (re-export pro kompatibilitu)
from .commands.case import cmd_case_auto_export, cmd_case_auto_interval, cmd_case_new

# P3-3 — Automated Classification (pravidlový klasifikátor souborů + override)
from .commands.classification import cmd_classify

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

# P3-4 — Evidence Storage Manager (kvarenténa originálů: inventář/rehash/rozpočet/manifest)
from .commands.evidence_storage import cmd_evidence_storage

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
    cmd_seal_chain,
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
    "new": "cli.h.001",
    "auto-export": "cli.h.002",
    "auto-interval": "cli.h.003",
    "add": "cli.h.004",
    "files": "cli.h.005",
    "search": "cli.h.006",
    "stats": "cli.h.007",
    "verify": "cli.h.008",
    "seal": "cli.h.009",
    "seal-chain": "cli.h.010",
    "integrity-keys": "cli.h.011",
    "rotate-key": "cli.h.012",
    "parser-status": "cli.h.013",
    "parser-quality": "cli.h.014",
    "ai-run": "cli.h.015",
    "ai-eval": "cli.h.016",
    "provenance": "cli.h.017",
    "graph": "cli.h.018",
    "compliance": "cli.h.019",
    "daubert": "cli.h.020",
    "attack-map": "cli.h.021",
    "reparse": "cli.h.022",
    "compare-artifacts": "cli.h.023",
    "classify": "cli.h.024",
    "evidence-storage": "cli.h.025",
    "wb": "cli.h.026",
    "integrity": "cli.h.027",
    "replay": "cli.h.028",
    "benchmark": "cli.h.029",
    "validate": "cli.h.030",
    "analyze": "cli.h.031",
    "audit": "cli.h.032",
    "backup": "cli.h.033",
    "timeline": "cli.h.034",
    "timeline-intel": "cli.h.035",
    "xcorr": "cli.h.036",
    "registry": "cli.h.037",
    "exchange": "cli.h.038",
    "correlate": "cli.h.039",
    "analytics": "cli.h.040",
    "image": "cli.h.041",
    "mobile": "cli.h.042",
    "memory-analyze": "cli.h.043",
    "pcap-analyze": "cli.h.044",
    "antiforensics-scan": "cli.h.045",
    "profiles": "cli.h.046",
    "report": "cli.h.047",
    "export": "cli.h.048",
    "plaso-import": "cli.h.049",
    "timesketch-push": "cli.h.050",
    "advanced": "cli.h.051",
    "decrypt": "cli.h.052",
    "import-mobile": "cli.h.053",
    "onchain": "cli.h.054",
    "darkweb": "cli.h.055",
    "crypto-report": "cli.h.056",
    "serve": "cli.h.057",
    "install": "cli.h.058",
}


def _ex_sub(subparsers, name: str, *args, example=None, **kwargs) -> argparse.ArgumentParser:
    """add_parser + epilog s příkladem (R0.4).

    Explicitní ``example`` má přednost před záznamem v tabulce podle jména
    (podřízené subpříkazy sdílejí holá jména napříč skupinami); bez příkladu
    vrací parser beze změny.
    """
    p = subparsers.add_parser(name, *args, **kwargs)
    if example is None:
        key = _SUBCOMMAND_EXAMPLES.get(name)  # P4-8 — hodnota tabulky je klíč i18n katalogu
        example = t(key) if key else None
    if example:
        p.formatter_class = argparse.RawDescriptionHelpFormatter
        p.epilog = f"{t('cli.example_header')}:\n  {example}"
    return p


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stopa", description=t("cli.top.description"))
    # R0.3 — `stopa --version` vrací verzi balíčku (importlib metadata, dev fallback).
    try:
        from importlib.metadata import version as _pkg_version

        _ver = _pkg_version("stopa")
    except Exception:  # noqa: BLE001 — dev run bez instalace / chybějící metadata
        from stopa import __version__ as _ver
    parser.add_argument("--version", action="version", version=f"stopa {_ver}")
    sub = parser.add_subparsers(dest="command", required=True)

    case_p = _ex_sub(sub, "case", help=t("cli.h.059"))
    case_sub = case_p.add_subparsers(dest="case_cmd", required=True)
    new_p = _ex_sub(case_sub, "new", help=t("cli.h.060"))
    new_p.add_argument("name", help=t("cli.h.061"))
    new_p.add_argument("--examiner", help=t("cli.h.062"))
    new_p.add_argument("--notes", help=t("cli.h.063"))
    _add_json_flag(new_p)
    new_p.set_defaults(func=cmd_case_new)

    # STP-069 — opt-in automatický ZIP bundle po dokončení analýzy.
    autoexp_p = _ex_sub(case_sub, "auto-export", help=t("cli.h.064")
    )
    autoexp_p.add_argument("case_id", help=t("cli.h.065"))
    autoexp_p.add_argument("state", choices=["on", "off"], help=t("cli.h.066"))
    # STP-070 — volitelný interval periodického auto-bundle (minuty).
    autoexp_p.add_argument(
        "--interval",
        type=int,
        default=None,
        metavar=t("cli.mv.minutes"),
        help=t("cli.h.067"),
    )
    _add_json_flag(autoexp_p)
    autoexp_p.set_defaults(func=cmd_case_auto_export)

    # STP-070 — nastavení/vymazání intervalu periodického auto-bundle.
    autoint_p = _ex_sub(case_sub, "auto-interval", help=t("cli.h.068")
    )
    autoint_p.add_argument("case_id", help=t("cli.h.065"))
    autoint_p.add_argument(
        "minutes",
        help=t("cli.h.069"),
    )
    _add_json_flag(autoint_p)
    autoint_p.set_defaults(func=cmd_case_auto_interval)

    add_p = _ex_sub(sub, "add", help=t("cli.h.070"))
    add_p.add_argument("case_id", help=t("cli.h.071"))
    add_p.add_argument("paths", nargs="+", help=t("cli.h.072"))
    add_p.add_argument("--profile", default="forensic", choices=sorted(PROFILES),
                       help=t("cli.h.073"))
    add_p.add_argument("--hash-set", action="append", metavar="FILE",
                       help=t("cli.h.074"))
    add_p.add_argument("--custodian", default=None,
                       help=t("cli.h.075"))
    add_p.add_argument("--method", default=None,
                       help=t("cli.h.076"))
    add_p.add_argument("--resume", action="store_true",
                       help=t("cli.h.077"))
    add_p.add_argument("--workers", type=int, default=None, metavar="N",
                       help=t("cli.h.078"))
    add_p.add_argument("--pool", choices=["auto", "threads", "processes"], default="auto",
                       help=t("cli.h.079"))
    add_p.add_argument("--disk-budget", type=int, default=0, metavar="MB",
                       help=t("cli.h.080"))
    _add_json_flag(add_p)
    add_p.set_defaults(func=cmd_add)

    files_p = _ex_sub(sub, "files", help=t("cli.h.081"))
    files_p.add_argument("case_id")
    files_p.add_argument("--bad-ext", action="store_true", help=t("cli.h.082"))
    files_p.add_argument("--dups", action="store_true", help=t("cli.h.083"))
    files_p.add_argument("--family", choices=["image", "document", "audio", "video", "media",
                                              "archive", "executable", "database", "compound"],
                         help=t("cli.h.084"))
    files_p.add_argument("--limit", type=int, default=100)
    _add_json_flag(files_p)
    files_p.set_defaults(func=cmd_files)

    search_p = _ex_sub(sub, "search", help=t("cli.h.085"))
    search_p.add_argument("case_id")
    search_p.add_argument(
        "query",
        help=t("cli.h.086"),
    )
    search_p.add_argument("--source", help=t("cli.h.087"))
    search_p.add_argument("--limit", type=int, default=100)
    # P3-1 Advanced Search — volitelné strukturované filtry; bez flagů = stávající chování
    search_p.add_argument(
        "--kind", help=t("cli.h.088")
    )
    search_p.add_argument(
        "--entity", help=t("cli.h.089")
    )
    search_p.add_argument("--size-min", type=int, help=t("cli.h.090"))
    search_p.add_argument("--size-max", type=int, help=t("cli.h.091"))
    search_p.add_argument("--mtime-from", help=t("cli.h.092"))
    search_p.add_argument("--mtime-to", help=t("cli.h.093"))
    search_p.add_argument(
        "--rel-depth",
        type=int,
        choices=(1, 2, 3),
        help=t("cli.h.094"),
    )
    _add_json_flag(search_p)
    search_p.set_defaults(func=cmd_search)

    stats_p = _ex_sub(sub, "stats", help=t("cli.h.095"))
    stats_p.add_argument("case_id")
    _add_json_flag(stats_p)
    stats_p.set_defaults(func=cmd_stats)

    ver_p = _ex_sub(sub, "verify", help=t("cli.h.096"))
    ver_p.add_argument("case_id")
    ver_p.add_argument("--limit", type=int, default=20,
                       help=t("cli.h.097"))
    _add_json_flag(ver_p)
    ver_p.set_defaults(func=cmd_verify)

    seal_p = _ex_sub(sub, "seal",
                     help=t("cli.h.098"))
    seal_p.add_argument("case_id")
    seal_p.add_argument("--reason", metavar=t("cli.mv.reason"), default=None,
                        help=t("cli.h.099"))
    seal_p.add_argument("--witness", metavar='JSON', default=None,
                        help=(t("cli.h.100")))
    _add_json_flag(seal_p)
    seal_p.set_defaults(func=cmd_seal)

    sc_p = _ex_sub(sub, "seal-chain",
                   help=t("cli.h.101"))
    sc_p.add_argument("case_id")
    _add_json_flag(sc_p)
    sc_p.set_defaults(func=cmd_seal_chain)

    ik_p = _ex_sub(sub, "integrity-keys",
                   help=t("cli.h.102"))
    ik_p.add_argument("case_id")
    _add_json_flag(ik_p)
    ik_p.set_defaults(func=cmd_integrity_keys)

    rk_p = _ex_sub(sub, "rotate-key",
                   help=t("cli.h.103"))
    rk_p.add_argument("case_id")
    rk_p.add_argument("--reason", metavar=t("cli.mv.reason"), default=None,
                      help=t("cli.h.104"))
    _add_json_flag(rk_p)
    rk_p.set_defaults(func=cmd_rotate_key)

    q_p = _ex_sub(sub, "parser-quality",
                  help=t("cli.h.105"))
    q_p.add_argument("--format", choices=["text", "json"], default="text",
                     help=t("cli.h.106"))
    _add_json_flag(q_p)
    q_p.add_argument("--fail-below", type=float, metavar="PCT",
                     help=t("cli.h.107"))
    q_p.set_defaults(func=cmd_parser_quality)

    from stopa.domain.ai_orchestrator import ROLE_IDS as _AI_ROLE_IDS

    ai_p = _ex_sub(sub, "ai-run",
                   help=t("cli.h.108"))
    ai_p.add_argument("case_id")
    ai_p.add_argument("--role", required=True, choices=_AI_ROLE_IDS,
                      help=t("cli.h.109"))
    ai_p.add_argument("--question", metavar=t("cli.mv.question"), default="",
                      help=t("cli.h.110"))
    ai_p.add_argument("--artifact", action="append", metavar="ID",
                      help=t("cli.h.111"))
    _add_json_flag(ai_p)
    ai_p.set_defaults(func=cmd_ai_run)

    # P4-5 — AI eval gate (offline zlatá suita rolí; nevyžaduje case DB ani LM Studio)
    ai_e_p = _ex_sub(
        sub, "ai-eval",
        help=t("cli.h.112"),
    )
    ai_e_p.add_argument("--suite", default="gold", choices=["gold"],
                        help=t("cli.h.113"))
    _add_json_flag(ai_e_p)
    ai_e_p.set_defaults(func=cmd_ai_eval)

    ps_p = _ex_sub(sub, "parser-status",
                   help=t("cli.h.114"))
    ps_p.add_argument("--format", choices=["text", "json"], default="text",
                      help=t("cli.h.106"))
    _add_json_flag(ps_p)
    ps_p.add_argument("--fail-on-unvalidated", action="store_true",
                      help=t("cli.h.115"))
    ps_p.set_defaults(func=cmd_parser_status)

    prov_p = _ex_sub(sub, "provenance",
                     help=t("cli.h.116"))
    prov_p.add_argument("case_id")
    prov_p.add_argument("artifact_id")
    _add_json_flag(prov_p)
    prov_p.set_defaults(func=cmd_provenance)

    graph_p = _ex_sub(sub, "graph",
                      help=t("cli.h.117"))
    graph_p.add_argument("case_id")
    _add_json_flag(graph_p)
    graph_p.set_defaults(func=cmd_graph)

    # P2-4 — Investigation Workspace: poznámky / úkoly / revize hypotéz (hash chain)
    ws_p = sub.add_parser(
        "workspace", help=t("cli.h.118")
    )
    ws_sub = ws_p.add_subparsers(dest="workspace_cmd", required=True, metavar="<podprikaz>")

    # note — poznámky ukotvené na reference (druh:id)
    ws_note_p = ws_sub.add_parser("note", help=t("cli.h.119"))
    ws_note_sub = ws_note_p.add_subparsers(dest="note_cmd", required=True, metavar="<akce>")
    wna_p = _ex_sub(
        ws_note_sub, "add",
        help=t("cli.h.120"),
        example=t("cli.h.121"),
    )
    wna_p.add_argument("case_id")
    wna_p.add_argument("--ref", required=True, metavar="DRUH:ID",
                       help=t("cli.h.122"))
    wna_p.add_argument("--text", required=True, help=t("cli.h.123"))
    wna_p.add_argument("--author", default=None, help=t("cli.h.124"))
    _add_json_flag(wna_p)
    wna_p.set_defaults(func=cmd_workspace_note_add)
    wnl_p = _ex_sub(
        ws_note_sub, "list", help=t("cli.h.125"),
        example=t("cli.h.126"),
    )
    wnl_p.add_argument("case_id")
    _add_json_flag(wnl_p)
    wnl_p.set_defaults(func=cmd_workspace_note_list)

    # task — úkoly se stavovým automatem open → in_progress → done
    ws_task_p = ws_sub.add_parser("task", help=t("cli.h.127"))
    ws_task_sub = ws_task_p.add_subparsers(dest="task_cmd", required=True, metavar="<akce>")
    wta_p = _ex_sub(
        ws_task_sub, "add", help=t("cli.h.128"),
        example=t("cli.h.129"),
    )
    wta_p.add_argument("case_id")
    wta_p.add_argument("--title", required=True, help=t("cli.h.130"))
    wta_p.add_argument("--assignee", default=None, help=t("cli.h.131"))
    wta_p.add_argument("--due", default=None, metavar="ISO", help=t("cli.h.132"))
    _add_json_flag(wta_p)
    wta_p.set_defaults(func=cmd_workspace_task_add)
    wts_p = _ex_sub(
        ws_task_sub, "set-status", help=t("cli.h.133"),
        example=t("cli.h.134"),
    )
    wts_p.add_argument("case_id")
    wts_p.add_argument("--task", required=True, type=int, dest="task_id", metavar="ID", help=t("cli.h.135"))
    wts_p.add_argument("--status", required=True, choices=TASK_STATUSES, help=t("cli.h.136"))
    _add_json_flag(wts_p)
    wts_p.set_defaults(func=cmd_workspace_task_set_status)
    wtl_p = _ex_sub(
        ws_task_sub, "list", help=t("cli.h.137"),
        example=t("cli.h.138"),
    )
    wtl_p.add_argument("case_id")
    _add_json_flag(wtl_p)
    wtl_p.set_defaults(func=cmd_workspace_task_list)

    # hypo-rev — revize hypotéz jako append-only hash chain
    ws_hr_p = ws_sub.add_parser(
        "hypo-rev", help=t("cli.h.139")
    )
    ws_hr_sub = ws_hr_p.add_subparsers(dest="hyporev_cmd", required=True, metavar="<akce>")
    wha_p = _ex_sub(
        ws_hr_sub, "add", help=t("cli.h.140"),
        example=t("cli.h.141"),
    )
    wha_p.add_argument("case_id")
    wha_p.add_argument("--hypothesis", required=True, metavar="ID", help=t("cli.h.142"))
    wha_p.add_argument("--claim", required=True, help=t("cli.h.143"))
    wha_p.add_argument("--author", default=None, help=t("cli.h.124"))
    _add_json_flag(wha_p)
    wha_p.set_defaults(func=cmd_workspace_hypo_rev_add)
    whl_p = _ex_sub(
        ws_hr_sub, "list", help=t("cli.h.144"),
        example=t("cli.h.145"),
    )
    whl_p.add_argument("case_id")
    whl_p.add_argument("--hypothesis", default=None, metavar="ID", help=t("cli.h.146"))
    whl_p.add_argument("--check-chain", action="store_true",
                       help=t("cli.h.147"))
    _add_json_flag(whl_p)
    whl_p.set_defaults(func=cmd_workspace_hypo_rev_list)

    comp_p = _ex_sub(sub, "compliance",
                     help=t("cli.h.148"))
    comp_p.add_argument("case_id")
    comp_p.add_argument("--out", metavar="DIR", default=None,
                        help=t("cli.h.149"))
    _add_json_flag(comp_p)
    comp_p.set_defaults(func=cmd_compliance)

    daubert_p = _ex_sub(
        sub, "daubert",
        help=t("cli.h.150"),
    )
    daubert_p.add_argument("case_id")
    daubert_p.add_argument("--out", metavar="DIR", default=None,
                           help=t("cli.h.149"))
    _add_json_flag(daubert_p)
    daubert_p.set_defaults(func=cmd_daubert)

    attack_map_p = _ex_sub(
        sub, "attack-map",
        help=t("cli.h.151"),
    )
    attack_map_p.add_argument("case_id")
    attack_map_p.add_argument("--format", choices=["json", "stix"], default="json",
                              help=t("cli.h.152"))
    attack_map_p.add_argument("--out", metavar="FILE", default=None,
                              help=t("cli.h.153"))
    _add_json_flag(attack_map_p)
    attack_map_p.set_defaults(func=cmd_attack_map)

    # F6.4 — Plugin ecosystem
    plg_p = sub.add_parser("plugin", help=t("cli.h.154"))
    plg_sub = plg_p.add_subparsers(dest="plugin_cmd", required=True, metavar="<podprikaz>")
    plg_list = _ex_sub(
        plg_sub, "list", help=t("cli.h.155"), example=t("cli.h.156")
    )
    _add_json_flag(plg_list)
    plg_list.set_defaults(func=cmd_plugin_list)
    plg_info = _ex_sub(
        plg_sub, "info", help=t("cli.h.157"), example=t("cli.h.158")
    )
    plg_info.add_argument("name")
    _add_json_flag(plg_info)
    plg_info.set_defaults(func=cmd_plugin_info)
    plg_verify = _ex_sub(
        plg_sub,
        "verify",
        help=t("cli.h.159"),
        example=t("cli.h.160"),
    )
    plg_verify.add_argument("name")
    _plg_vgroup = plg_verify.add_mutually_exclusive_group(required=True)
    _plg_vgroup.add_argument("--add", action="store_true", help=t("cli.h.161"))
    _plg_vgroup.add_argument("--remove", action="store_true", help=t("cli.h.162"))
    plg_verify.set_defaults(func=cmd_plugin_verify)
    plg_run = _ex_sub(
        plg_sub,
        "run",
        help=t("cli.h.163"),
        example=t("cli.h.164"),
    )
    plg_run.add_argument("name")

    def _plg_cap_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--cap", choices=["extractor", "triage_profile", "ai_tool"], required=True,
                       help=t("cli.h.324"))
        p.add_argument("--key", default=None, help=t("cli.h.325"))
        p.add_argument("--file", dest="files", action="append", default=[], metavar="FILE",
                       help=t("cli.h.326"))
        p.add_argument("--tool", default=None, help=t("cli.h.327"))
        p.add_argument("--case-id", dest="case_id", default=None,
                       help=t("cli.h.328"))
        p.add_argument("--params", default="{}", help=t("cli.h.329"))

    _plg_cap_args(plg_run)
    plg_run.add_argument(
        "--sandbox",
        choices=["default", "strict"],
        default="default",
        help=(
            t("cli.h.165")
        ),
    )
    _add_json_flag(plg_run)
    plg_run.set_defaults(func=cmd_plugin_run)

    # skrytý interní entry point pro sandbox subprocess (přímý běh, JSON stdout)
    prun_p = sub.add_parser("plugin-run", help=argparse.SUPPRESS)
    prun_p.add_argument("name")
    _plg_cap_args(prun_p)
    prun_p.set_defaults(func=cmd_plugin_run_entry)

    rp_p = _ex_sub(sub, "reparse",
                   help=t("cli.h.166"))
    rp_p.add_argument("case_id")
    rp_p.add_argument("--source-id", default=None, metavar="ID",
                      help=t("cli.h.167"))
    rp_p.add_argument("--parser-version", required=True, metavar="V",
                      help=t("cli.h.168"))
    rp_p.add_argument("--workdir", default=None, metavar="DIR",
                      help=t("cli.h.169"))
    _add_json_flag(rp_p)
    rp_p.set_defaults(func=cmd_reparse)

    # P3-2 — Artifact Version Comparison: path JSON diff dvou verzí téhož artefaktu
    ca_p = _ex_sub(sub, "compare-artifacts",
                   help=t("cli.h.170"))
    ca_p.add_argument("case_id")
    ca_p.add_argument("id_a", metavar="ID_A", help=t("cli.h.171"))
    ca_p.add_argument("id_b", metavar="ID_B", help=t("cli.h.172"))
    _add_json_flag(ca_p)
    ca_p.set_defaults(func=cmd_compare_artifacts)

    # P3-3 — Automated Classification: pravidlový klasifikátor + lidský override
    cl_p = _ex_sub(sub, "classify",
                   help=t("cli.h.173"))
    cl_p.add_argument("case_id")
    cl_p.add_argument("--override", default=None, metavar="ID",
                      help=t("cli.h.174"))
    cl_p.add_argument("--category", default=None, metavar="CAT",
                      help=t("cli.h.175"))
    cl_p.add_argument("--reason", default=None, metavar="R",
                      help=t("cli.h.176"))
    cl_p.add_argument("--actor", default=None, metavar="ACTOR",
                      help=t("cli.h.177"))
    _add_json_flag(cl_p)
    cl_p.set_defaults(func=cmd_classify)

    # P3-4 — Evidence Storage Manager: kvarenténa originálů (inventář/rozpočet/manifest)
    ev_p = _ex_sub(
        sub, "evidence-storage",
        help=t("cli.h.178"),
    )
    ev_sub = ev_p.add_subparsers(dest="evidence_cmd", required=True, metavar="<podprikaz>")

    evv_p = _ex_sub(
        ev_sub, "verify",
        help=t("cli.h.179"),
        example=t("cli.h.180"),
    )
    evv_p.add_argument("case_id", help=t("cli.h.065"))
    evv_p.add_argument("--export", metavar="FILE", default=None,
                       help=t("cli.h.181"))
    evv_p.add_argument("--import", dest="import_file", metavar="FILE", default=None,
                       help=t("cli.h.182"))
    _add_json_flag(evv_p)
    evv_p.set_defaults(func=cmd_evidence_storage, action="verify")

    evr_p = _ex_sub(
        ev_sub, "report",
        help=t("cli.h.183"),
        example=t("cli.h.184"),
    )
    evr_p.add_argument("case_id", help=t("cli.h.065"))
    evr_p.add_argument("--budget", metavar="MB", type=float, default=None,
                       help=t("cli.h.185"))
    _add_json_flag(evr_p)
    evr_p.set_defaults(func=cmd_evidence_storage, action="report")

    # F5.4 — write-blocker integration API (status/attach/remove + ingest gate)
    wb_p = _ex_sub(sub, "wb", help=t("cli.h.186"))
    wb_sub = wb_p.add_subparsers(dest="wb_cmd", required=True)
    wbs_p = _ex_sub(
        wb_sub, "status", help=t("cli.h.187"),
        example=t("cli.h.188"),
    )
    wbs_p.add_argument("case_id")
    _add_json_flag(wbs_p)
    wbs_p.set_defaults(func=cmd_wb_status)
    wba_p = _ex_sub(
        wb_sub, "attach", help=t("cli.h.189"),
        example=t("cli.h.190"),
    )
    wba_p.add_argument("case_id")
    wba_p.add_argument("--device", default=None, metavar="DEV",
                       help=t("cli.h.191"))
    wba_p.add_argument("--vendor", default=None, choices=known_vendor_ids(),
                       help=t("cli.h.192"))
    wba_p.add_argument("--product", default=None, metavar="P",
                       help=t("cli.h.193"))
    wba_p.add_argument("--notes", default=None, metavar="N",
                       help=t("cli.h.194"))
    _add_json_flag(wba_p)
    wba_p.set_defaults(func=cmd_wb_attach)
    wbm_p = _ex_sub(
        wb_sub, "remove", help=t("cli.h.195"), example=t("cli.h.196")
    )
    wbm_p.add_argument("case_id")
    wbm_p.add_argument("--reason", default=None, metavar="R",
                       help=t("cli.h.197"))
    _add_json_flag(wbm_p)
    wbm_p.set_defaults(func=cmd_wb_remove)

    int_p = _ex_sub(sub, "integrity", help=t("cli.h.198")
    )
    int_p.add_argument("case_id")
    int_p.add_argument("--init-key", action="store_true",
                       help=t("cli.h.199"))
    int_p.add_argument("--checkpoint", metavar=t("cli.mv.reason"), default=None,
                       help=t("cli.h.200"))
    _add_json_flag(int_p)
    int_p.set_defaults(func=cmd_integrity)

    rep_p = _ex_sub(sub, "replay", help=t("cli.h.201")
    )
    rep_p.add_argument("case_id")
    rep_p.add_argument("op", nargs="?", default=None,
                       help=t("cli.h.202"))
    _add_json_flag(rep_p)
    rep_p.set_defaults(func=cmd_replay)

    bm_p = _ex_sub(sub, "benchmark", help=t("cli.h.203")
    )
    bm_p.add_argument("case_id", nargs="?", default=None,
                      help=t("cli.h.204"))
    bm_p.add_argument("--suite", choices=["core", "parsers", "all"], default="core")
    _add_json_flag(bm_p)
    bm_p.set_defaults(func=cmd_benchmark)

    val_p = _ex_sub(sub, "validate", help=t("cli.h.205")
    )
    val_p.add_argument("case_id")
    _add_json_flag(val_p)
    val_p.set_defaults(func=cmd_validate)

    ana_p = _ex_sub(sub, "analyze", help=t("cli.h.206")
    )
    ana_p.add_argument("case_id")
    ana_p.add_argument("question", help=t("cli.h.207"))
    ana_p.add_argument(
        "--agent",
        choices=["case_analyst", "timeline_analyst", "artifact_analyst", "media_analyst", "report_analyst"],
        default=None,
        help=t("cli.h.208"),
    )
    _add_json_flag(ana_p)
    ana_p.set_defaults(func=cmd_analyze)

    aud_p = _ex_sub(sub, "audit", help=t("cli.h.209"))
    aud_p.add_argument("case_id")
    aud_p.add_argument("--limit", type=int, default=50,
                       help=t("cli.h.210"))
    aud_p.add_argument("--offset", type=int, default=None,
                       help=t("cli.h.211"))
    aud_p.add_argument("-v", "--verbose", action="store_true",
                       help=t("cli.h.212"))
    _add_json_flag(aud_p)
    aud_p.set_defaults(func=cmd_audit)

    bak_p = _ex_sub(sub, "backup", help=t("cli.h.213"))
    bak_p.add_argument("case_id")
    bak_p.add_argument("--out", metavar="DIR",
                       help=t("cli.h.214"))
    _add_json_flag(bak_p)
    bak_p.set_defaults(func=cmd_backup)

    tl_p = _ex_sub(sub, "timeline", help=t("cli.h.215"))
    tl_p.add_argument("case_id")
    tl_p.add_argument("--source", help=t("cli.h.087"))
    tl_p.add_argument("--type", dest="type", help=t("cli.h.216"))
    tl_p.add_argument("--path", help=t("cli.h.217"))
    tl_p.add_argument("--limit", type=int, default=100)
    tl_p.add_argument("-v", "--verbose", action="store_true", help=t("cli.h.218"))
    # STP-018 Timeline Intelligence 2.0 — post-pass: rozpory + duplikáty napříč zdroji
    tl_p.add_argument("--intel", action="store_true",
                      help=t("cli.h.219"))
    tl_p.add_argument("--window", type=float, default=60.0, metavar="SEC",
                      help=t("cli.h.220"))
    _add_json_flag(tl_p)
    tl_p.set_defaults(func=cmd_timeline)

    # P2-3 — Advanced Timeline Intelligence: IQR gapy/outliery + cross-source
    # korelace (E4 confidence) + vysvětlení nejistoty nad celou timeline.
    tli_p = _ex_sub(
        sub, "timeline-intel",
        help=t("cli.h.221"),
    )
    tli_p.add_argument("case_id")
    _add_json_flag(tli_p)
    tli_p.set_defaults(func=cmd_timeline_intel)

    # P2-6 — Cross-case Correlation: sdílené entity napříč případy (read-only,
    # tenancy pravidla, audit hash chain). Exit 0 OK / 1 chyba / 2 bez oprávnění.
    xc_p = _ex_sub(
        sub, "xcorr",
        help=t("cli.h.222"),
        example=t("cli.h.223"),
    )
    xc_p.add_argument("case_a", nargs="?", help=t("cli.h.224"))
    xc_p.add_argument("case_b", nargs="?", help=t("cli.h.225"))
    xc_p.add_argument("--all", action="store_true", dest="all",
                      help=t("cli.h.226"))
    xc_p.add_argument("--entity", choices=["email", "tel", "hash"], default=None,
                      help=t("cli.h.227"))
    xc_p.add_argument("--user", metavar="USERNAME", default=None,
                      help=t("cli.h.228"))
    _add_json_flag(xc_p)
    xc_p.set_defaults(func=cmd_xcorr)

    # P2-2 — Centrální registr případů: instance-level seznam případů + tenancy
    # izolace (+ explicitní sync jednotlivého případu). Exit 0 OK / 1 chyba / 2 bez oprávnění.
    reg_p = _ex_sub(
        sub, "registry",
        help=t("cli.h.229"),
        example=t("cli.h.230"),
    )
    reg_p.add_argument("--tenant", metavar="ORG_ID", default=None,
                       help=t("cli.h.231"))
    reg_p.add_argument("--user", metavar="USERNAME", default=None,
                       help=t("cli.h.228"))
    reg_p.add_argument("--sync", metavar="CASE_ID", default=None,
                       help=t("cli.h.232"))
    _add_json_flag(reg_p)
    reg_p.set_defaults(func=cmd_registry)

    # P2-5 — Threat Intelligence Workspace: per-případový IoC feed (STIX 2.1) +
    # deterministické matching × artefakty/entities. Exit 0 OK / 1 chyba/prázdný feed.
    intel_p = _ex_sub(
        sub, "intel",
        help=t("cli.h.233"),
        example=t("cli.h.234"),
    )
    intel_sub = intel_p.add_subparsers(dest="intel_cmd", required=True, metavar="<podprikaz>")

    ii_p = _ex_sub(
        intel_sub, "import",
        help=t("cli.h.235"),
        example=t("cli.h.236"),
    )
    ii_p.add_argument("case_id", help=t("cli.h.065"))
    ii_p.add_argument("--stix", metavar="FILE", default=None,
                      help=t("cli.h.237"))
    ii_p.add_argument("--ioc", metavar="KIND:HODNOTA[,...]", default=None,
                      help=t("cli.h.238"))
    ii_p.add_argument("--tlp", choices=["WHITE", "GREEN", "AMBER", "RED"], default="GREEN",
                      help=t("cli.h.239"))
    ii_p.add_argument("--source", metavar="SOURCE", default=None,
                      help=t("cli.h.240"))
    _add_json_flag(ii_p)
    ii_p.set_defaults(func=cmd_intel_import)

    im_p = _ex_sub(
        intel_sub, "match",
        help=t("cli.h.241"),
        example=t("cli.h.234"),
    )
    im_p.add_argument("case_id", help=t("cli.h.065"))
    im_p.add_argument(
        "--yara", metavar="DIR", default=None,
        help=t("cli.h.242"),
    )
    im_p.add_argument(
        "--sigma", metavar="FILE", default=None,
        help=t("cli.h.243"),
    )
    _add_json_flag(im_p)
    im_p.set_defaults(func=cmd_intel_match)

    # P2-7 — Case Exchange bundle v1 (pack/verify, volitelná anonymizace). Exit 0 OK / 1 chyba.
    exchange_p = _ex_sub(
        sub, "exchange",
        help=t("cli.h.244"),
        example=t("cli.h.245"),
    )
    exchange_sub = exchange_p.add_subparsers(dest="exchange_cmd", required=True, metavar="<podprikaz>")

    ex_pack = _ex_sub(
        exchange_sub, "pack",
        help=t("cli.h.246"),
        example=t("cli.h.247"),
    )
    ex_pack.add_argument("case_id", help=t("cli.h.065"))
    ex_pack.add_argument("--out", metavar="FILE", default=None,
                         help=t("cli.h.248"))
    ex_pack.add_argument("--anon", action="store_true",
                         help=t("cli.h.249"))
    ex_pack.add_argument("--key-file", metavar="FILE", default=None,
                         help=t("cli.h.250"))
    ex_pack.add_argument("--key-out", metavar="FILE", default=None,
                         help=t("cli.h.251"))
    ex_pack.add_argument(
        "--tlp", choices=("CLEAR", "GREEN", "AMBER", "RED", "WHITE"), default=None,
        help=t("cli.h.252"),
    )
    _add_json_flag(ex_pack)
    ex_pack.set_defaults(func=cmd_exchange_pack)

    ex_ver = _ex_sub(
        exchange_sub, "verify",
        help=t("cli.h.253"),
        example=t("cli.h.254"),
    )
    ex_ver.add_argument("bundle_file", help=t("cli.h.255"))
    ex_ver.add_argument("--roots", metavar="FILE", default=None,
                        help=t("cli.h.256"))
    ex_ver.add_argument("--root", action="append", default=[], metavar="LABEL=BASE64",
                        help=t("cli.h.257"))
    _add_json_flag(ex_ver)
    ex_ver.set_defaults(func=cmd_exchange_verify)

    cor_p = _ex_sub(sub, "correlate", help=t("cli.h.258"))
    cor_p.add_argument("case_id")
    cor_p.add_argument("-v", "--verbose", action="store_true",
                       help=t("cli.h.259"))
    _add_json_flag(cor_p)
    cor_p.set_defaults(func=cmd_correlate)

    an_p = _ex_sub(sub, "analytics", help=t("cli.h.260"))
    an_p.add_argument("case_id")
    an_p.add_argument("--from-ts", dest="from_ts", metavar="ISO", help=t("cli.h.261"))
    an_p.add_argument("--to-ts", dest="to_ts", metavar="ISO", help=t("cli.h.262"))
    an_p.add_argument("--type", dest="type", help=t("cli.h.263"))
    an_p.add_argument("--limit", type=int, default=100)
    an_p.add_argument(
        "--dedupe", action="store_true",
        help=t("cli.h.264"),
    )
    _add_json_flag(an_p)
    an_p.set_defaults(func=cmd_analytics)

    img_p = _ex_sub(sub, "image", help=t("cli.h.265"))
    img_p.add_argument("case_id")
    img_p.add_argument("path", help=t("cli.h.266"))
    img_p.add_argument("--profile", default="forensic", choices=sorted(PROFILES),
                       help=t("cli.h.073"))
    img_p.add_argument("--no-carve", action="store_true",
                       help=t("cli.h.267"))
    _add_json_flag(img_p)
    img_p.set_defaults(func=cmd_image)

    mob_p = _ex_sub(sub, "mobile", help=t("cli.h.268"))
    mob_p.add_argument("case_id")
    mob_p.add_argument("path", help=t("cli.h.269"))
    mob_p.add_argument("--password", metavar=t("cli.mv.password"), default=None,
                       help=t("cli.h.270"))
    mob_p.add_argument("--keyfile", metavar=t("cli.mv.file"), default=None,
                       help=t("cli.h.271"))
    mob_p.add_argument("--fde-type", choices=["bitlocker", "filevault"], default=None,
                       help=t("cli.h.272"))
    mob_p.add_argument("--recovery-key", metavar=t("cli.mv.key"), default=None,
                       help=t("cli.h.273"))
    mob_p.add_argument("--profile", default="forensic", choices=sorted(PROFILES),
                       help=t("cli.h.073"))
    mob_p.add_argument("--no-carve", action="store_true",
                       help=t("cli.h.267"))
    _add_json_flag(mob_p)
    mob_p.set_defaults(func=cmd_mobile)

    dec_p = _ex_sub(sub, "decrypt", help=t("cli.h.274"))
    dec_p.add_argument("image", help=t("cli.h.275"))
    dec_p.add_argument("--type", choices=["bitlocker", "filevault"], default=None,
                       help=t("cli.h.276"))
    dec_p.add_argument("--recovery-key", metavar=t("cli.mv.key"), default=None,
                       help=t("cli.h.277"))
    dec_p.add_argument("--password", metavar=t("cli.mv.password"), default=None,
                       help=t("cli.h.278"))
    dec_p.add_argument("--out", metavar=t("cli.mv.file"), default=None,
                       help=t("cli.h.279"))
    _add_json_flag(dec_p)
    dec_p.set_defaults(func=cmd_decrypt)

    mem_p = _ex_sub(sub, "memory-analyze", help=t("cli.h.280"))
    mem_p.add_argument("case_id", help=t("cli.h.065"))
    mem_p.add_argument("dump", help=t("cli.h.281"))
    mem_p.add_argument("--plugin", action="append", metavar="PLUGIN", default=None,
                       help=t("cli.h.330", defaults=", ".join(_VOL_DEFAULT_PLUGINS)))
    mem_p.add_argument("--with-defaults", action="store_true",
                       help=t("cli.h.282"))
    mem_p.add_argument("--timeout", type=int, default=600, metavar="S",
                       help=t("cli.h.283"))
    _add_json_flag(mem_p)
    mem_p.set_defaults(func=cmd_memory_analyze)

    mob_p = _ex_sub(sub, "import-mobile", help=t("cli.h.284"))
    mob_p.add_argument("case_id", help=t("cli.h.065"))
    mob_p.add_argument("dump", help=t("cli.h.285"))
    mob_p.add_argument("--source", choices=["cellebrite", "msab", "adb"], default="cellebrite",
                       help=t("cli.h.286"))
    _add_json_flag(mob_p)
    mob_p.set_defaults(func=cmd_import_mobile)

    pcap_p = _ex_sub(sub, "pcap-analyze", help=t("cli.h.287"))
    pcap_p.add_argument("case_id", help=t("cli.h.065"))
    pcap_p.add_argument("pcap", help=t("cli.h.288"))
    pcap_p.add_argument("--max-packets", type=int, default=50_000, metavar="N",
                        help=t("cli.h.289"))
    _add_json_flag(pcap_p)
    pcap_p.set_defaults(func=cmd_pcap_analyze)

    af_p = _ex_sub(sub, "antiforensics-scan", help=t("cli.h.290"))
    af_p.add_argument("case_id", help=t("cli.h.065"))
    af_p.add_argument("--image", metavar="PATH", default=None,
                      help=t("cli.h.291"))
    _add_json_flag(af_p)
    af_p.set_defaults(func=cmd_antiforensics)

    prof_p = _ex_sub(sub, "profiles", help=t("cli.h.292"))
    _add_json_flag(prof_p)
    prof_p.set_defaults(func=cmd_profiles)

    rep_p = _ex_sub(sub, "report", help=t("cli.h.293"))
    rep_p.add_argument("case_id")
    rep_p.add_argument("--format", choices=["html", "pdf"], default="html",
                       help=t("cli.h.294"))
    rep_p.add_argument("--out", metavar="DIR",
                       help=t("cli.h.295"))
    rep_p.add_argument("--lang", choices=["cs", "en"], default=None,
                       help=t("cli.h.296"))
    _add_json_flag(rep_p)
    rep_p.set_defaults(func=cmd_report)

    exp_p = _ex_sub(sub, "export", help=t("cli.h.297"))
    exp_p.add_argument("case_id")
    exp_p.add_argument("--what", choices=["artifacts", "timeline", "correlations"],
                       default="artifacts",
                       help=t("cli.h.298"))
    exp_p.add_argument("--format", choices=["csv", "json", "jsonl", "xml", "stix", "l2tcsv", "timesketch", "uco"], default="csv",
                       help=t("cli.h.299"))
    exp_p.add_argument("--limit", type=int, default=None,
                       help=t("cli.h.300"))
    exp_p.add_argument("--out", metavar=t("cli.mv.file"),
                       help=t("cli.h.153"))
    exp_p.add_argument("--bundle", action="store_true",
                       help=t("cli.h.301"))
    exp_p.add_argument("--validate-stix", action="store_true", dest="validate_stix",
                       help=t("cli.h.302"))
    exp_p.set_defaults(func=cmd_export)

    oc_p = _ex_sub(sub, "onchain",
                   help=t("cli.h.303"))
    oc_p.add_argument("case_id")
    oc_p.add_argument("--api-key", default=None, metavar="KEY",
                      help=t("cli.h.304"))
    oc_p.add_argument("--etherscan-key", default=None, metavar="KEY",
                      help=t("cli.h.305"))
    oc_p.add_argument("--no-network", action="store_true",
                      help=t("cli.h.306"))
    oc_p.add_argument("--depth", type=int, default=3,
                      help=t("cli.h.307"))
    _add_json_flag(oc_p)
    oc_p.set_defaults(func=cmd_onchain)

    dw_p = _ex_sub(sub, "darkweb",
                   help=t("cli.h.308"))
    dw_p.add_argument("case_id")
    dw_p.add_argument("--file", action="append", default=None, metavar=t("cli.mv.file"),
                      help=t("cli.h.309"))
    _add_json_flag(dw_p)
    dw_p.set_defaults(func=cmd_darkweb)

    crp = _ex_sub(sub, "crypto-report",
                  help=t("cli.h.310"))
    crp.add_argument("case_id")
    crp.add_argument("--format", choices=["md", "html", "json"], default="md",
                     help=t("cli.h.311"))
    crp.add_argument("--out", metavar=t("cli.mv.file"),
                     help=t("cli.h.312"))
    _add_json_flag(crp)
    crp.set_defaults(func=cmd_crypto_report)

    adv_p = _ex_sub(sub, "advanced",
                    help=t("cli.h.313"))
    adv_p.add_argument("case_id")
    adv_p.add_argument("--file", action="append", default=None, metavar=t("cli.mv.file"),
                       help=t("cli.h.309"))
    _add_json_flag(adv_p)
    adv_p.set_defaults(func=cmd_advanced)

    pli_p = _ex_sub(sub, "plaso-import", help=t("cli.h.314")
    )
    pli_p.add_argument("case_id")
    pli_p.add_argument("path", help=t("cli.h.315"))
    _add_json_flag(pli_p)
    pli_p.set_defaults(func=cmd_plaso_import)

    tsk_p = _ex_sub(sub, "timesketch-push",
        help=t("cli.h.316"),
    )
    tsk_p.add_argument("case_id")
    tsk_p.add_argument("--what", choices=["artifacts", "timeline", "correlations"],
                       default="timeline", help=t("cli.h.317"))
    tsk_p.add_argument("--limit", type=int, default=None, metavar="N",
                       help=t("cli.h.318"))
    _add_json_flag(tsk_p)
    tsk_p.set_defaults(func=cmd_timesketch_push)

    srv_p = _ex_sub(sub, "serve", help=t("cli.h.319"))
    srv_p.add_argument("--host", default=None,  # E12: None → settings.json → 127.0.0.1
                       help=t("cli.h.320"))
    srv_p.add_argument("--port", type=int, default=8473)
    srv_p.set_defaults(func=cmd_serve)

    # R0.2 — bootstrap installer: systémové závislosti + venv (detekce OS).
    ins_p = _ex_sub(sub, "install", help=t("cli.h.321"))
    ins_p.add_argument("--dry-run", action="store_true",
                       help=t("cli.h.322"))
    ins_p.add_argument("--skip-system", action="store_true",
                       help=t("cli.h.323"))
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
    """Entry point — P4-8: nejdřív vyřešit jazyk (--lang/STOPA_LANG), pak build parseru."""
    raw = argv if argv is not None else sys.argv[1:]
    try:
        lang, rest = resolve_lang(list(raw))
    except ValueError as exc:
        print(f"stopa: {exc}", file=sys.stderr)
        return 2
    set_lang(lang)
    parser = build_parser()
    args = parser.parse_args(rest)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
