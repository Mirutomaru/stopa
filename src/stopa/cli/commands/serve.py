"""CLI — web GUI (serve) + bind-address z settings.json.

P1-4 (refaktor god-file ``cli.py``): přesunuto bez změny chování;
facade ``stopa.cli`` re-exportuje implementaci pro kompatibilitu.
"""
from __future__ import annotations

import argparse
import os
import sys


def cmd_serve(args: argparse.Namespace) -> int:
    """Web GUI (FÁZE web) — FastAPI nad analyze(), uvicorn server."""
    try:
        import uvicorn
    except ImportError:
        print("Chybí uvicorn — nainstalujte: pip install 'uvicorn[standard]'", file=sys.stderr)
        return 2

    from stopa.web.app import create_app

    # E12: bind address — CLI flag > settings.json > default 127.0.0.1
    host = args.host or _settings_bind_address() or "127.0.0.1"

    app = create_app()
    print(f"STOPA web GUI → http://{host}:{args.port} (Ctrl+C pro ukončení)")
    uvicorn.run(app, host=host, port=args.port, log_level="warning")
    return 0


def _settings_bind_address() -> str | None:
    """E12 — bind address z settings.json (None pokud není nastaveno)."""
    import json
    from pathlib import Path

    p = Path(os.environ.get("STOPA_DB_DIR", "cases")) / "settings.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        val = data.get("bind_address") if isinstance(data, dict) else None
        return str(val) if val else None
    except (json.JSONDecodeError, OSError):
        return None


