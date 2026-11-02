"""Forenzní report — court-ready HTML (+ PDF přes WeasyPrint).

ČISTÉ funkce nad daty — žádný IO → 100% offline testovatelné. IO wrapper
(čtení case DB + zápis souborů) žije v ``presentation/case_report.py``.

Obsah reportu (Belkasoft/FTK style):
- hlavička případu (název, ID, znalec, datum vytvoření, generování)
- **chain of custody** — evidence items: zdroj + každý soubor s SHA-256/MD5
  (hash manifest = důkaz integrity; re-ingest je idempotentní podle rel_path)
- processing summary (soubory, bajty, signatury, bad-ext, duplikáty, hash sets)
- přehled artifactů podle typu
- flagované soubory (BAD-EXT / DUP / HASHSET) — hlavní nálezy
- ručně označené soubory (Evidence / Report z GUI)
- audit trail (neměnná stopa operací, E1)
- **E10: timeline** — chronologické události (UTC + lokální čas case TZ)
  s confidence štítky a detekovanými nesrovnalostmi
- **E10: korelace entity** — propojení s evidence odkazy (rel_path + detail)

**E10 i18n:** všechny viditelné texty jdou přes ``domain/i18n.py`` (cs/en);
výchozí jazyk je čeština, přepnutí přes parametr ``lang``.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime

from stopa.domain.i18n import normalize_lang, t, t_fmt


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
class AuditEntry:
    """Jeden záznam neměnného audit logu (E1 Evidence Manager)."""

    ts: str
    action: str
    actor: str | None = None
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TimelineEvent:
    """Jedna timeline událost pro report (E10).

    ``ts_utc`` je ISO řetězec z case DB; lokální čas počítá build_html()
    přes ``ReportData.timezone_name`` (case TZ, default Europe/Prague).
    """

    ts_utc: str | None
    event_type: str
    title: str | None = None
    rel_path: str | None = None
    confidence: float | None = None
    anomaly_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class CorrelationRow:
    """Jedno propojení entity pro report (E10) — s evidence odkazy."""

    entity_a: str
    entity_b: str
    relation: str
    confidence: str  # "verified" | "inferred"
    evidence: tuple[dict[str, object], ...] = ()


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
    audit_entries: tuple[AuditEntry, ...] = ()  # E1 — neměnná stopa operací
    custody_metadata: dict[str, dict[str, str | None]] = field(default_factory=dict)
    # E10 — timeline + korelace (UTC ISO z DB; lokální čas počítá build_html):
    timeline_events: tuple[TimelineEvent, ...] = ()
    correlations: tuple[CorrelationRow, ...] = ()
    timezone_name: str = "Europe/Prague"


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


def _audit_details_str(details: dict[str, object]) -> str:
    """Detaily audit záznamu — kompaktní `k=v` řetězec (bez JSON šumu)."""
    parts = []
    for k, v in details.items():
        if isinstance(v, str) or v is not None:
            parts.append(f"{k}={v}")
    return " ".join(parts)


def _parse_iso(s: str | None) -> datetime | None:
    """ISO řetězec z DB → datetime (neplatný formát → None, report nepadá)."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _fmt_local(ts_utc_iso: str | None, tz_name: str) -> str:
    """UTC ISO → lokální čas v case TZ (E10 timeline; fallback UTC)."""
    from stopa.domain.times import to_local_iso

    dt = _parse_iso(ts_utc_iso)
    if dt is None:
        return "—"
    local = to_local_iso(dt, tz_name)
    if not local:
        return "—"
    # ISO → "YYYY-MM-DD HH:MM:SS" (bez offsetu — TZ je v hlavičce sloupce)
    d = _parse_iso(local)
    return d.strftime("%Y-%m-%d %H:%M:%S") if d else local


def confidence_label(confidence: float | None) -> str:
    """E10 — confidence → štítek důvěryhodnosti (i18n klíč).

    Třírové škálování podle hodnoty ``Artifact.confidence`` (0.0–1.0):
    - **≥ 0.8** → ``conf_verified`` [ověřeno] — výsledek s vysokou spolehlivostí
      (křížově ověřený / plná provenience)
    - **0.5 – 0.8** → ``conf_extracted`` [extrahováno] — přímá extrakce,
      střední spolehlivost
    - **< 0.5 nebo nevyhodnoceno (None)** → ``conf_hypothesis`` [hypotéza] —
      odvozený výsledek / bez explicitního skóre = nejslabší tvrzení
    """
    if confidence is None or confidence < 0.5:
        return "conf_hypothesis"
    if confidence >= 0.8:
        return "conf_verified"
    return "conf_extracted"


def _correlation_confidence_label(confidence: str) -> str:
    """E10 — korelační confidence (verified/inferred) → i18n klíč."""
    if confidence == "verified":
        return "conf_verified"
    if confidence == "inferred":
        return "conf_inferred"
    return confidence  # neznámá hodnota → zobrazení tak, jak je


def _evidence_str(evidence: tuple[dict[str, object], ...]) -> str:
    """Evidence list korelace → kompaktní řetězec `detail (rel_path)`."""
    parts = []
    for ev in evidence[:10]:  # limit — report nenechává utéct buňku
        detail = str(ev.get("detail") or "")
        path = str(ev.get("rel_path") or "")
        parts.append(f"{detail} ({path})" if path else detail)
    s = "; ".join(p for p in parts if p)
    return s or "—"


def build_html(data: ReportData, lang: str | None = None) -> str:
    """Vygeneruje celý HTML dokument reportu (inline CSS, print-friendly).

    ``lang`` — jazyk reportu (E10 i18n): "cs" (výchozí) nebo "en".
    """
    from stopa import __version__  # lazy — verze nástroje pro court-ready hlavičku

    L = normalize_lang(lang)
    generated = data.generated_at or datetime.now()
    from datetime import timezone

    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)

    parts: list[str] = []
    parts.append(
        f"<!DOCTYPE html>\n<html lang='{L}'><head><meta charset='utf-8'>"
        f"<title>{t('report_title', L)} — {_esc(data.case_name)}</title>"
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
        ".conf{font-size:7.5pt;color:#444;white-space:nowrap}"
        ".mono{font-family:'DejaVu Sans Mono',monospace;font-size:8pt;word-break:break-all}"
        ".small{font-size:8pt;color:#555}"
        "@page{size:A4;margin:2cm 1.6cm}@media print{"
        "h2{page-break-after:avoid}table{page-break-inside:auto}"
        "tr{page-break-inside:avoid}}"
        "</style></head><body>"
    )

    # ── hlavička případu ───────────────────────────────────────
    parts.append(f"<h1>{t('report_title', L)} — {_esc(data.case_name)}</h1>")
    parts.append("<table class='meta'>")
    rows = [
        (t("meta_case_id", L), data.case_id),
        (t("meta_examiner", L), data.examiner or "—"),
        (t("meta_created", L), _fmt_dt(data.created_at)),
        (t("meta_notes", L), data.notes or "—"),
        (t("meta_generated", L), _fmt_dt(generated)),
        (t("meta_tool", L), f"STOPA v{__version__} (unifikovaná forenzní workbench)"),
    ]
    for k, v in rows:
        parts.append(f"<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>")
    parts.append("</table>")

    # ── chain of custody — evidence sources ────────────────────
    parts.append(f"<h2>1. {t('sec_coc', L)}</h2>")
    if data.sources:
        parts.append(
            f"<table><tr><th>#</th><th>{t('th_source', L)}</th>"
            f"<th>{t('th_type', L)}</th>"
            f"<th>{t('th_added_utc', L)}</th>"
            f"<th>{t('th_size', L)}</th>"
            f"<th>{t('th_method', L)}</th>"
            f"<th>{t('th_custodian', L)}</th></tr>"
        )
        for i, s in enumerate(data.sources, 1):
            size = _fmt_bytes(s.size_bytes) if s.size_bytes is not None else "—"
            cust = data.custody_metadata.get(s.id, {})
            method = cust.get("method") or "—"
            custodian = cust.get("custodian") or "—"
            parts.append(
                f"<tr><td>{i}</td><td class='mono'>{_esc(s.path)}</td>"
                f"<td>{_esc(s.kind)}</td><td>{_fmt_dt(s.added_at)}</td>"
                f"<td>{size}</td><td>{_esc(method)}</td><td>{_esc(custodian)}</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append(f"<p class='small'>{t('empty_sources', L)}</p>")

    # ── processing summary ─────────────────────────────────────
    t_ = data.totals
    parts.append(f"<h2>2. {t('sec_processing', L)}</h2>")
    if data.sources:
        parts.append(
            f"<table><tr><th>{t('th_source', L)}</th>"
            f"<th>{t('th_files', L)}</th><th>{t('th_bytes', L)}</th>"
            f"<th>{t('th_signatures', L)}</th>"
            f"<th>{t('th_bad_ext', L)}</th>"
            f"<th>{t('th_dups', L)}</th></tr>"
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
    total_line = t_fmt(
        "total_line", L,
        files=f"{t_.get('files', 0):,}",
        bytes=_fmt_bytes(t_.get("bytes", 0)),
        signed=t_.get("signed", 0),
        bad_ext=t_.get("bad_ext", 0),
        dups=t_.get("dups", 0),
    )
    parts.append(f"<p>{total_line}</p>")

    # ── artifacts přehled ──────────────────────────────────────
    parts.append(f"<h2>3. {t('sec_artifacts', L)}</h2>")
    if data.artifact_counts:
        total = sum(data.artifact_counts.values())
        parts.append(
            f"<p>{t_fmt('artifacts_total', L, total=f'{total:,}')} "
            f"</p><table><tr><th>{t('th_type', L)}</th>"
            f"<th>{t('th_count', L)}</th></tr>"
        )
        for typ, n in sorted(data.artifact_counts.items(), key=lambda kv: -kv[1]):
            parts.append(f"<tr><td>{_esc(typ)}</td><td>{n:,}</td></tr>")
        parts.append("</table>")
    else:
        parts.append(f"<p class='small'>{t('empty_artifacts', L)}</p>")

    # ── flagované soubory (hlavní nálezy) ──────────────────────
    parts.append(f"<h2>4. {t('sec_findings', L)}</h2>")
    if data.flagged_files:
        parts.append(
            f"<table><tr><th>{t('th_file', L)}</th>"
            f"<th>{t('th_flags', L)}</th><th>SHA-256</th></tr>"
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
                t_fmt("truncated_flagged", L, n=f"{len(data.flagged_files):,}")
            )
    else:
        parts.append(f"<p class='small'>{t('empty_flagged', L)}</p>")

    # ── ručně označené soubory (GUI File Inspector) ────────────
    parts.append(f"<h2>5. {t('sec_marked', L)}</h2>")
    if data.marked_files:
        parts.append(
            f"<table><tr><th>{t('th_file', L)}</th>"
            f"<th>{t('th_marks', L)}</th>"
            f"<th>{t('th_size', L)}</th><th>SHA-256</th></tr>"
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
        parts.append(f"<p class='small'>{t('empty_marked', L)}</p>")

    # ── hash manifest (důkaz integrity) ────────────────────────
    parts.append(f"<h2>6. {t('sec_manifest', L)}</h2>")
    if data.custody_items:
        src_path = {s.id: s.path for s in data.sources}  # zdrojová úroveň CoC
        parts.append(
            f"<table><tr><th>{t('th_source', L)}</th>"
            f"<th>{t('th_file', L)}</th>"
            f"<th>{t('th_size', L)}</th><th>SHA-256</th><th>MD5</th></tr>"
        )
        for c in data.custody_items[:5000]:  # limit — manifest může být velký
            sha = f"<td class='mono'>{_esc(c.sha256)}</td>" if c.sha256 else "<td>—</td>"
            md5 = f"<td class='mono'>{_esc(c.md5)}</td>" if c.md5 else "<td>—</td>"
            parts.append(
                f"<tr><td class='mono'>{_esc(src_path.get(c.source_id, c.source_id))}</td>"
                f"<td class='mono'>{_esc(c.rel_path)}</td>"
                f"<td>{c.size_bytes:,}</td>{sha}{md5}</tr>"
            )
        parts.append("</table>")
        if len(data.custody_items) > 5000:
            parts.append(
                t_fmt("truncated_manifest", L, n=f"{len(data.custody_items):,}")
            )
    else:
        parts.append(f"<p class='small'>{t('empty_manifest', L)}</p>")

    # ── E1 Evidence Manager: audit trail (neměnná stopa operací) ──
    parts.append(f"<h2>7. {t('sec_audit', L)}</h2>")
    if data.audit_entries:
        parts.append(
            f"<table><tr><th>#</th>"
            f"<th>{t('th_time_utc', L)}</th>"
            f"<th>{t('th_action', L)}</th>"
            f"<th>{t('th_actor', L)}</th>"
            f"<th>{t('th_details', L)}</th></tr>"
        )
        for i, e in enumerate(data.audit_entries[:500], 1):  # limit — court-ready
            det = _esc(_audit_details_str(e.details)) if e.details else "—"
            parts.append(
                f"<tr><td>{i}</td><td class='mono'>{_esc(e.ts)}</td>"
                f"<td>{_esc(e.action)}</td><td>{_esc(e.actor or '—')}</td>"
                f"<td class='mono small'>{det}</td></tr>"
            )
        parts.append("</table>")
        if len(data.audit_entries) > 500:
            parts.append(
                t_fmt("truncated_audit", L, n=f"{len(data.audit_entries):,}")
            )
    else:
        parts.append(f"<p class='small'>{t('empty_audit', L)}</p>")

    # ── E10: timeline (UTC + lokální čas case TZ) ──────────────
    parts.append(f"<h2>8. {t('sec_timeline', L)}</h2>")
    if data.timeline_events:
        tz_label = t("th_time_local", L).format(tz=data.timezone_name)
        parts.append(
            f"<table><tr>"
            f"<th>{t('th_time_utc', L)}</th>"
            f"<th>{_esc(tz_label)}</th>"
            f"<th>{t('th_event_type', L)}</th>"
            f"<th>{t('th_event', L)}</th>"
            f"<th>{t('th_file', L)}</th>"
            f"<th>{t('th_confidence', L)}</th>"
            f"<th>{t('th_anomalies', L)}</th></tr>"
        )
        for ev in data.timeline_events[:500]:  # limit — court-ready
            conf = t(confidence_label(ev.confidence), L)
            conf_cell = (
                f"[{_esc(conf)}] {ev.confidence:.2f}" if ev.confidence is not None
                else f"[{_esc(conf)}]"
            )
            anomalies = ", ".join(ev.anomaly_flags) or "—"
            parts.append(
                f"<tr><td class='mono'>{_esc(_fmt_dt(_parse_iso(ev.ts_utc)))}</td>"
                f"<td class='mono'>{_esc(_fmt_local(ev.ts_utc, data.timezone_name))}</td>"
                f"<td>{_esc(ev.event_type)}</td>"
                f"<td>{_esc((ev.title or '')[:120])}</td>"
                f"<td class='mono small'>{_esc(ev.rel_path or '—')}</td>"
                f"<td class='conf'>{conf_cell}</td>"
                f"<td class='small'>{_esc(anomalies)}</td></tr>"
            )
        parts.append("</table>")
        if len(data.timeline_events) > 500:
            parts.append(
                t_fmt("truncated_timeline", L, limit=500, n=f"{len(data.timeline_events):,}")
            )
    else:
        parts.append(f"<p class='small'>{t('empty_timeline', L)}</p>")

    # ── E10: korelace entity (s evidence odkazy) ───────────────
    parts.append(f"<h2>9. {t('sec_correlations', L)}</h2>")
    if data.correlations:
        parts.append(
            f"<table><tr>"
            f"<th>{t('th_entity_a', L)}</th>"
            f"<th>{t('th_entity_b', L)}</th>"
            f"<th>{t('th_relation', L)}</th>"
            f"<th>{t('th_confidence', L)}</th>"
            f"<th>{t('th_evidence', L)}</th></tr>"
        )
        for c in data.correlations[:500]:  # limit — court-ready
            conf = t(_correlation_confidence_label(c.confidence), L)
            parts.append(
                f"<tr><td class='mono'>{_esc(c.entity_a)}</td>"
                f"<td class='mono'>{_esc(c.entity_b)}</td>"
                f"<td>{_esc(c.relation)}</td>"
                f"<td class='conf'>[{_esc(conf)}]</td>"
                f"<td class='small'>{_esc(_evidence_str(c.evidence))}</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append(f"<p class='small'>{t('empty_correlations', L)}</p>")

    # ── patička ────────────────────────────────────────────────
    parts.append(
        f"<p class='small' style='margin-top:2em;border-top:1px solid #999;"
        f"padding-top:6px'>{t_fmt('footer', L, case_id=_esc(data.case_id), ts=_fmt_dt(generated))}</p>"
    )
    parts.append("</body></html>")
    return "\n".join(parts)
