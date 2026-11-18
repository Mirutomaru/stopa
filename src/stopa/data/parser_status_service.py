"""P0-4 validation lab — data service pro parser status (I/O vrstva).

Propojuje C3 registry s čtením testovacích souborů a dodává hotový JSON report
pro CLI ``stopa parser-status`` a Web endpoint ``/api/parser-status``.
Doména (`domain.parser_status`) zůstává čistá — zde je I/O (čtení zdrojů +
mtime jako metadata pro ``last_validated_ts``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def _repo_anchor() -> Path:
    """Kořen projektu, kde leží `tests/` (anchor pro relativní cesty registry).

    Editovatelná instalace → kořen repo přes umístění balíku; fallback CWD.
    """
    from stopa import __file__ as _pkg  # noqa: WPS433 — jednorázová rezoluce

    candidate = Path(_pkg).resolve().parents[2]
    if (candidate / "tests").is_dir():
        return candidate
    return Path.cwd()


def _test_file_loader(anchor: Path | None = None):
    """Loader pro `domain.parser_status.build_parser_status`."""
    root = anchor or _repo_anchor()

    def load(rel_path: str) -> str | None:
        try:
            return (root / rel_path).read_text(encoding="utf-8")
        except OSError:
            return None

    return load


def _file_stamp_loader(anchor: Path | None = None):
    """mtime souboru → ISO UTC (metadata, ne forenzní jádro)."""
    root = anchor or _repo_anchor()

    def stamp(rel_path: str) -> str | None:
        try:
            mt = (root / rel_path).stat().st_mtime
        except OSError:
            return None
        return datetime.fromtimestamp(mt, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return stamp


def load_parser_status(anchor: Path | None = None) -> dict:
    """Hotový report per-parser validačního statusu (P0-4)."""
    from stopa.domain.parser_status import build_parser_status, parser_status_report
    from stopa.domain.validation_registry import build_registry

    records = build_parser_status(
        build_registry(),
        _test_file_loader(anchor),
        stamp_loader=_file_stamp_loader(anchor),
    )
    return parser_status_report(records)
