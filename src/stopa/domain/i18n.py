"""E10 — Internationalizace reportu (cs/en).

ČISTÁ logika bez IO — tabulky překladů + lookup s fallbackem na češtinu.
Report se generuje výchozí v češtině; ``--lang en`` přepne všechny klíče.

Pravidla:
- Každý viditelný text reportu má klíč (žádné hardcoded řetězce v build_html).
- Neznámý jazyk → fallback na cs (report nikdy nepadne kvůli jazyku).
- Neznámý klíč → vrátí se klíč sám (chyba je viditelná při testování).
"""

from __future__ import annotations

SUPPORTED_LANGS: tuple[str, ...] = ("cs", "en")
DEFAULT_LANG = "cs"

# key → (česky, anglicky) — pořadí odpovídá SUPPORTED_LANGS.
_STRINGS: dict[str, tuple[str, str]] = {
    # ── hlavička případu ───────────────────────────────────────
    "report_title": ("Forenzní report", "Forensic Report"),
    "meta_case_id": ("ID případu", "Case ID"),
    "meta_examiner": ("Znalec / zpracovatel", "Examiner / processor"),
    "meta_created": ("Datum vytvoření případu", "Case creation date"),
    "meta_notes": ("Poznámky", "Notes"),
    "meta_generated": ("Report vygenerován", "Report generated"),
    "meta_tool": ("Nástroj", "Tool"),
    # ── sekce 1 — chain of custody ─────────────────────────────
    "sec_coc": (
        "Chain of custody — evidence sources",
        "Chain of custody — evidence sources",
    ),
    "th_source": ("Zdroj", "Source"),
    "th_type": ("Typ", "Type"),
    "th_added_utc": ("Přidáno (UTC)", "Added (UTC)"),
    "th_size": ("Velikost", "Size"),
    "th_method": ("Metoda nabytí", "Acquisition method"),
    "th_custodian": ("Evidoval", "Recorded by"),
    "empty_sources": ("Žádné evidence sources.", "No evidence sources."),
    # ── sekce 2 — processing summary ───────────────────────────
    "sec_processing": ("Processing summary", "Processing summary"),
    "th_files": ("Soubory", "Files"),
    "th_bytes": ("Bajty", "Bytes"),
    "th_signatures": ("Signatury", "Signatures"),
    "th_bad_ext": ("Bad-ext", "Bad-ext"),
    "th_dups": ("Duplikáty", "Duplicates"),
    "total_line": (
        ("CELKEM: {files} souborů, {bytes}, signatury {signed}, "
         "bad-ext {bad_ext}, duplikáty {dups}."),
        ("TOTAL: {files} files, {bytes}, signatures {signed}, "
         "bad-ext {bad_ext}, duplicates {dups}."),
    ),
    # ── sekce 3 — artifacty ────────────────────────────────────
    "sec_artifacts": ("Extrahované artifacty", "Extracted artifacts"),
    "artifacts_total": (
        "Celkem {total} artifactů. Rozložení podle typu:",
        "Total {total} artifacts. Distribution by type:",
    ),
    "th_count": ("Počet", "Count"),
    "empty_artifacts": (
        "Žádné extrahované artifacty.",
        "No extracted artifacts.",
    ),
    # ── sekce 4 — hlavní nálezy ────────────────────────────────
    "sec_findings": (
        "Hlavní nálezy — flagované soubory",
        "Key findings — flagged files",
    ),
    "th_file": ("Soubor", "File"),
    "th_flags": ("Flagy", "Flags"),
    "truncated_flagged": (
        "Zobrazeno prvních 500 z {n} flagovaných souborů.",
        "Showing first 500 of {n} flagged files.",
    ),
    "empty_flagged": (
        "Žádné flagované soubory (bad-ext / duplikáty / hash sets).",
        "No flagged files (bad-ext / duplicates / hash sets).",
    ),
    # ── sekce 5 — ručně označené soubory ───────────────────────
    "sec_marked": (
        "Ručně označené soubory (Evidence / Report)",
        "Manually marked files (Evidence / Report)",
    ),
    "th_marks": ("Označení", "Marks"),
    "empty_marked": (
        "Žádné ručně označené soubory.",
        "No manually marked files.",
    ),
    # ── sekce 6 — hash manifest ────────────────────────────────
    "sec_manifest": ("Hash manifest — SHA-256 / MD5", "Hash manifest — SHA-256 / MD5"),
    "truncated_manifest": (
        "Zobrazeno prvních 5 000 z {n} souborů (plný manifest v case DB).",
        "Showing first 5,000 of {n} files (full manifest in the case DB).",
    ),
    "empty_manifest": ("Žádné soubory s hashem.", "No hashed files."),
    # ── sekce 7 — audit trail ──────────────────────────────────
    "sec_audit": (
        "Audit trail — neměnná stopa operací",
        "Audit trail — immutable operation log",
    ),
    "th_time_utc": ("Čas (UTC)", "Time (UTC)"),
    "th_action": ("Operace", "Operation"),
    "th_actor": ("Aktor", "Actor"),
    "th_details": ("Detaily", "Details"),
    "truncated_audit": (
        "Zobrazeno prvních 500 z {n} operací (plná stopa v case DB — `stopa audit`).",
        "Showing first 500 of {n} operations (full log in the case DB — `stopa audit`).",
    ),
    "empty_audit": ("Žádné zaznamenané operace.", "No recorded operations."),
    # ── sekce 8 — timeline (E10) ───────────────────────────────
    "sec_timeline": (
        "Timeline — chronologické události",
        "Timeline — chronological events",
    ),
    "th_time_local": ("Čas (lokální {tz})", "Local time ({tz})"),
    "th_event_type": ("Typ události", "Event type"),
    "th_event": ("Událost", "Event"),
    "th_confidence": ("Důvěryhodnost", "Confidence"),
    "th_anomalies": ("Nesrovnalosti", "Anomalies"),
    "truncated_timeline": (
        "Zobrazeno prvních {limit} z {n} událostí.",
        "Showing first {limit} of {n} events.",
    ),
    "empty_timeline": (
        "Žádné timeline události (artifacty bez časového otisku).",
        "No timeline events (artifacts without timestamps).",
    ),
    # ── sekce 9 — korelace entity (E10) ────────────────────────
    "sec_correlations": ("Propojení entity (korelace)", "Entity correlations"),
    "th_entity_a": ("Entita A", "Entity A"),
    "th_entity_b": ("Entita B", "Entity B"),
    "th_relation": ("Vztah", "Relation"),
    "th_evidence": ("Důkaz (evidence)", "Evidence"),
    "empty_correlations": (
        "Žádná propojení — spusťte `stopa correlate <case>`.",
        "No correlations — run `stopa correlate <case>`.",
    ),
    # ── confidence štítky (E10) ────────────────────────────────
    "conf_extracted": ("extrahováno", "extracted"),
    "conf_verified": ("ověřeno", "verified"),
    "conf_hypothesis": ("hypotéza", "hypothesis"),
    "conf_inferred": ("odvozeno", "inferred"),
    # ── patička ────────────────────────────────────────────────
    "footer": (
        ("STOPA report — případ {case_id}, vygenerován {ts}. Hash manifest slouží "
         "jako důkaz integrity (SHA-256 + MD5); re-ingest je idempotentní podle "
         "(source, rel_path)."),
        ("STOPA report — case {case_id}, generated at {ts}. The hash manifest serves "
         "as proof of integrity (SHA-256 + MD5); re-ingest is idempotent by "
         "(source, rel_path)."),
    ),
}


def normalize_lang(lang: str | None) -> str:
    """Normalizace jazyka — 'CS'/'Czech' → 'cs'; neznámá hodnota → výchozí cs."""
    if not lang:
        return DEFAULT_LANG
    key = lang.strip().lower()
    if key in SUPPORTED_LANGS:
        return key
    aliases = {"czech": "cs", "čeština": "cs", "english": "en"}
    return aliases.get(key, DEFAULT_LANG)


def t(key: str, lang: str | None = None) -> str:
    """Překlad klíče do daného jazyka (fallback cs; neznámý klíč → klíč sám)."""
    idx = SUPPORTED_LANGS.index(normalize_lang(lang)) if normalize_lang(lang) in SUPPORTED_LANGS else 0
    pair = _STRINGS.get(key)
    if pair is None:
        return key
    return pair[idx]


def t_fmt(key: str, lang: str | None = None, **kwargs: object) -> str:
    """Překlad + interpolace parametrů (``{files}``, ``{n}`` …)."""
    return t(key, lang).format(**kwargs)
