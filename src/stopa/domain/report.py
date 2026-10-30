"""Forenzní report — court-ready HTML (+ PDF přes WeasyPrint).

ČISTÉ funkce nad daty — žádný IO → 100% offline testovatelné. IO wrapper
(čtení case DB + zápis souborů) žije v ``presentation/case_report.py``.

Obsah reportu (Belkasoft/FTK style):
- hlavička případu (název, ID, znalec, datum vytvoření, generování)
- **chain of custody** — evidence items: zdroj + každý soubor s SHA-256
  (hash manifest = důkaz integrity; re-ingest je idempotentní podle rel_path)
- processing summary (soubory, bajty, signatury, bad-ext, duplikáty, hash sets)
- přehled artifactů podle typu
- flagované soubory (BAD-EXT / DUP / HASHSET) — hlavní nálezy
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class CustodyItem:
    """Jeden řádek chain of custody — soubor s hashem (důkaz integrity)."""

    source_id: str
    rel_path: str
    size_bytes: int
    sha256: str | None
    md5: str | None = None


@dataclass(frozen=True)
class SourceInfo:
    """Evidence source — položka v chain of custody (zdrojová úroveň)."""

    id: str
    kind: str  # "folder" | "file"
    path: str
    added_at: datetime
    size_bytes: int | None = None


@dataclass(frozen=True)
class FlaggedFile:
    """Soubor s forenzním flagem — hlavní nálezy v reportu."""

    rel_path: str
    flags: tuple[str, ...]  # např. ("BAD-EXT", "HASHSET:bad")
    sha256: str | None = None


@dataclass(frozen=True)
class MarkedFile:
    """Soubor ručně označený v GUI (Evidence / Add to Report)."""

    rel_path: str
    flags: tuple[str, ...]  # ("evidence", "report")
    size_bytes: int = 0
    sha256: str | None = None


@dataclass(frozen=True)
class ReportData:
    """Všechny údaje pro report — presentation vrstva naplní z case DB."""

    case_id: str
    case_name: str
    examiner: str | None
    created_at: datetime
    notes: str | None = None
    generated_at: datetime | None = None  # None → čas volání build_html()
    sources: tuple[SourceInfo, ...] = ()
    per_source_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    totals: dict[str, int] = field(default_factory=dict)
    artifact_counts: dict[str, int] = field(default_factory=dict)
    custody_items: tuple[CustodyItem, ...] = ()
    flagged_files: tuple[FlaggedFile, ...] = ()
    marked_files: tuple[MarkedFile, ...] = ()  # ručně označené v GUI (Evidence/Report)


def _esc(v: object) -> str:
    return html.escape(str(v), quote=True)


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    # UTC normalizace — court-ready reporty mají jednoznačný časový údaj
    from datetime import timezone

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _fmt_bytes(n: float) -> str:
    """Lidsky čitelná velikost (B/KB/MB/GB)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.2f} {unit}"
        n /= 1024
    return f"{n:,.2f} TB"


def build_html(data: ReportData) -> str:
    """Vygeneruje celý HTML dokument reportu (inline CSS, print-friendly)."""
    generated = data.generated_at or datetime.now()
    from datetime import timezone

    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)

    parts: list[str] = []
    parts.append(
        "<!DOCTYPE html>\n<html lang='cs'><head><meta charset='utf-8'>"
        f"<title>STOPA report — {_esc(data.case_name)}</title>"
        "<style>"
        "body{font-family:'DejaVu Serif',Georgia,serif;font-size:10pt;color:#1a1a1a;"
        "margin:2.5cm 2cm;line-height:1.45}"
        "h1{font-size:16pt;border-bottom:3px solid #1a1a1a;padding-bottom:4px;margin-top:0}"
        "h2{font-size:12pt;border-bottom:1px solid #999;padding-bottom:2px;margin-top:1.4em;"
        "page-break-after:avoid}"
        "table{border-collapse:collapse;width:100%;margin:8px 0;font-size:8.5pt}"
        "th,td{border:1px solid #999;padding:3px 6px;text-align:left;vertical-align:top}"
        "th{background:#eee;font-weight:bold}"
        "tr:nth-child(even) td{background:#f7f7f7}"
        ".meta td:first-child{font-weight:bold;width:180px;background:#f2f2f2}"
        ".flag{color:#a00;font-weight:bold}"
        ".mono{font-family:'DejaVu Sans Mono',monospace;font-size:8pt;word-break:break-all}"
        ".small{font-size:8pt;color:#555}"
        "@page{size:A4;margin:2cm 1.6cm}@media print{"
        "h2{page-break-after:avoid}table{page-break-inside:auto}"
        "tr{page-break-inside:avoid}}"
        "</style></head><body>"
    )

    # ── hlavička případu ───────────────────────────────────────
    parts.append(f"<h1>Forenzní report — {_esc(data.case_name)}</h1>")
    parts.append("<table class='meta'>")
    rows = [
        ("ID případu", data.case_id),
        ("Znalec / zpracovatel", data.examiner or "—"),
        ("Datum vytvoření případu", _fmt_dt(data.created_at)),
        ("Poznámky", data.notes or "—"),
        ("Report vygenerován", _fmt_dt(generated)),
        ("Nástroj", "STOPA (unifikovaná forenzní workbench)"),
    ]
    for k, v in rows:
        parts.append(f"<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>")
    parts.append("</table>")

    # ── chain of custody — evidence sources ────────────────────
    parts.append("<h2>1. Chain of custody — evidence sources</h2>")
    if data.sources:
        parts.append(
            "<table><tr><th>#</th><th>Zdroj</th><th>Typ</th>"
            "<th>Přidáno (UTC)</th><th>Velikost</th></tr>"
        )
        for i, s in enumerate(data.sources, 1):
            size = _fmt_bytes(s.size_bytes) if s.size_bytes is not None else "—"
            parts.append(
                f"<tr><td>{i}</td><td class='mono'>{_esc(s.path)}</td>"
                f"<td>{_esc(s.kind)}</td><td>{_fmt_dt(s.added_at)}</td>"
                f"<td>{size}</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append("<p class='small'>Žádné evidence sources.</p>")

    # ── processing summary ─────────────────────────────────────
    t = data.totals
    parts.append("<h2>2. Processing summary</h2>")
    if data.sources:
        parts.append(
            "<table><tr><th>Zdroj</th><th>Soubory</th><th>Bajty</th>"
            "<th>Signatury</th><th>Bad-ext</th><th>Duplikáty</th></tr>"
        )
        for s in data.sources:
            st = data.per_source_stats.get(s.id, {})
            parts.append(
                f"<tr><td class='mono'>{_esc(s.path)}</td>"
                f"<td>{st.get('files', 0):,}</td>"
                f"<td>{_fmt_bytes(st.get('bytes', 0))}</td>"
                f"<td>{st.get('signed', 0):,}</td>"
                f"<td>{st.get('bad_ext', 0):,}</td>"
                f"<td>{st.get('dups', 0):,}</td></tr>"
            )
        parts.append("</table>")
    parts.append(
        f"<p>CELKEM: <b>{t.get('files', 0):,}</b> souborů, "
        f"<b>{_fmt_bytes(t.get('bytes', 0))}</b>, signatury {t.get('signed', 0):,}, "
        f"bad-ext {t.get('bad_ext', 0):,}, duplikáty {t.get('dups', 0):,}.</p>"
    )

    # ── artifacts přehled ──────────────────────────────────────
    parts.append("<h2>3. Extrahované artifacty</h2>")
    if data.artifact_counts:
        total = sum(data.artifact_counts.values())
        parts.append(
            f"<p>Celkem <b>{total:,}</b> artifactů. Rozložení podle typu:</p>"
            "<table><tr><th>Typ</th><th>Počet</th></tr>"
        )
        for typ, n in sorted(data.artifact_counts.items(), key=lambda kv: -kv[1]):
            parts.append(f"<tr><td>{_esc(typ)}</td><td>{n:,}</td></tr>")
        parts.append("</table>")
    else:
        parts.append("<p class='small'>Žádné extrahované artifacty.</p>")

    # ── flagované soubory (hlavní nálezy) ──────────────────────
    parts.append("<h2>4. Hlavní nálezy — flagované soubory</h2>")
    if data.flagged_files:
        parts.append(
            "<table><tr><th>Soubor</th><th>Flagy</th><th>SHA-256</th></tr>"
        )
        for f in data.flagged_files[:500]:  # court-ready — nevtěsnat 10k řádků
            flags = " ".join(f"<span class='flag'>{_esc(x)}</span>" for x in f.flags)
            sha = f"<td class='mono'>{_esc(f.sha256 or '—')}</td>" if f.sha256 else "<td>—</td>"
            parts.append(
                f"<tr><td class='mono'>{_esc(f.rel_path)}</td><td>{flags}</td>{sha}</tr>"
            )
        parts.append("</table>")
        if len(data.flagged_files) > 500:
            parts.append(
                f"<p class='small'>Zobrazeno prvních 500 z {len(data.flagged_files):,} "
                "flagovaných souborů.</p>"
            )
    else:
        parts.append("<p class='small'>Žádné flagované soubory (bad-ext / duplikáty / hash sets).</p>")

    # ── ručně označené soubory (GUI File Inspector) ────────────
    parts.append("<h2>5. Ručně označené soubory (Evidence / Report)</h2>")
    if data.marked_files:
        parts.append(
            "<table><tr><th>Soubor</th><th>Označení</th><th>Velikost</th>"
            "<th>SHA-256</th></tr>"
        )
        for m in data.marked_files[:500]:
            labels = " ".join(
                f"<span class='flag'>{_esc('EVIDENCE' if x == 'evidence' else 'REPORT')}</span>"
                for x in m.flags
            )
            sha = (
                f"<td class='mono'>{_esc(m.sha256)}</td>" if m.sha256 else "<td>—</td>"
            )
            parts.append(
                f"<tr><td class='mono'>{_esc(m.rel_path)}</td><td>{labels}</td>"
                f"<td>{m.size_bytes:,}</td>{sha}</tr>"
            )
        parts.append("</table>")
    else:
        parts.append("<p class='small'>Žádné ručně označené soubory.</p>")

    # ── hash manifest (důkaz integrity) ────────────────────────
    parts.append("<h2>6. Hash manifest — SHA-256</h2>")
    if data.custody_items:
        parts.append(
            "<table><tr><th>Soubor</th><th>Velikost</th><th>SHA-256</th></tr>"
        )
        for c in data.custody_items[:5000]:  # limit — manifest může být velký
            sha = f"<td class='mono'>{_esc(c.sha256)}</td>" if c.sha256 else "<td>—</td>"
            parts.append(
                f"<tr><td class='mono'>{_esc(c.rel_path)}</td>"
                f"<td>{c.size_bytes:,}</td>{sha}</tr>"
            )
        parts.append("</table>")
        if len(data.custody_items) > 5000:
            parts.append(
                f"<p class='small'>Zobrazeno prvních 5 000 z {len(data.custody_items):,} "
                "souborů (plný manifest v case DB).</p>"
            )
    else:
        parts.append("<p class='small'>Žádné soubory s hashem.</p>")

    # ── patička ────────────────────────────────────────────────
    parts.append(
        f"<p class='small' style='margin-top:2em;border-top:1px solid #999;"
        f"padding-top:6px'>STOPA report — případ <b>{_esc(data.case_id)}</b>, "
        f"vygenerován {_fmt_dt(generated)}. Hash manifest slouží jako důkaz integrity "
        "(SHA-256); re-ingest je idempotentní podle (source, rel_path).</p>"
    )
    parts.append("</body></html>")
    return "\n".join(parts)
