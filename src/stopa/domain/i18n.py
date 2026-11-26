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
    # H3 — verze výstupního schématu (cover, strojově čitelná i v <head>)
    "meta_schema_version": ("Verze výstupního schématu", "Output schema version"),
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
    # ── STP-018 — Timeline Intelligence 2.0 (podsekce 8.1) ────────
    "intel_contradictions": (
        "Rozpory — souběžná aktivita jednoho subjektu: {n} událostí.",
        "Contradictions — concurrent activity of one subject: {n} events.",
    ),
    "intel_duplicates": (
        "Duplikáty napříč zdroji — stejný obsah z různých souborů/zdrojů: {n} událostí.",
        "Cross-source duplicates — same content from different files/sources: {n} events.",
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
    # ── confidence štítky (E10 + P0 I3 Entity Resolution 2.0) ────────
    "conf_extracted": ("extrahováno", "extracted"),
    "conf_verified": ("ověřeno", "verified"),
    "conf_hypothesis": ("hypotéza", "hypothesis"),
    "conf_inferred": ("odvozeno", "inferred"),
    # P0 I3: čtyři úrovně vztahů (Entity Resolution 2.0)
    "conf_strong_candidate": ("silný kandidát", "strong candidate"),
    "conf_unverified": ("neověřeno", "unverified"),
    # ── STP-020 — report engine 9 → 20 sekcí (sekce 10–20) ───────
    "sec_methodology": ("Metodika analýzy", "Analysis methodology"),
    "meth_sources": (
        "Zpracováno {n} evidence zdrojů ({files} souborů, {bytes}).",
        "{n} evidence sources processed ({files} files, {bytes}).",
    ),
    "meth_signatures": (
        "Detekce typů souborů podle magic bytes (signatur); identifikováno {signed} souborů.",
        "File type detection by magic bytes (signatures); {signed} files identified.",
    ),
    "meth_artifacts": (
        "Extrakce artifactů přes {n} verzovaných parserů (C3 Parser Validation Registry, 1:1 sync s pipeline).",
        "Artifact extraction via {n} versioned parsers (C3 Parser Validation Registry, 1:1 pipeline sync).",
    ),
    "meth_correlation": (
        "Korelace entit: {n} propojení (Entity Resolution 2.0 — čtyřúrovňová škála důvěryhodnosti vztahů).",
        "Entity correlation: {n} links (Entity Resolution 2.0 — four-level relation confidence scale).",
    ),
    "meth_timeline": (
        "Timeline Intelligence 2.0: detekce rozporů (souběžná aktivita jednoho subjektu v okně {w} s) a duplikátů napříč zdroji.",
        "Timeline Intelligence 2.0: contradiction detection (concurrent activity of one subject within a {w}s window) and cross-source duplicates.",
    ),
    # ── sekce 11 — nástroje a verze ─────────────────────────────
    "sec_tools": ("Nástroje a verze", "Tools and versions"),
    "th_component": ("Komponenta", "Component"),
    "th_version": ("Verze / stav", "Version / status"),
    "tool_stopa": ("STOPA (unifikovaná forenzní workbench)", "STOPA (unified forensic workbench)"),
    "tool_python": ("Python", "Python"),
    "tool_sqlite": ("SQLite", "SQLite"),
    "tool_platform": ("Platforma", "Platform"),
    "tool_tsk": ("TSK (pytsk3) — filesystem walk diskových obrazů", "TSK (pytsk3) — disk image filesystem walk"),
    "tool_ewf": ("EWF/libewf — kontejnery E01/AFF4", "EWF/libewf — E01/AFF4 containers"),
    "tool_cryptsetup": ("cryptsetup — FDE LUKS/FBE dešifrování", "cryptsetup — FDE LUKS/FBE decryption"),
    "avail_yes": ("dostupná", "available"),
    "avail_no": ("nedostupná (volitelná závislost)", "not available (optional dependency)"),
    # ── sekce 12 — omezení analýzy ──────────────────────────────
    "sec_limitations": ("Omezení analýzy", "Analysis limitations"),
    "lim_ram": (
        "Velikostní limit: u velkých E01 obrazů může být RAM peak omezen (BLK-001); stream parsing je plánován v STP-021.",
        "Size limit: large E01 images may hit a RAM peak ceiling (BLK-001); stream parsing is planned in STP-021.",
    ),
    "lim_confidence": (
        "Důvěryhodnost: artifacty bez explicitního skóre nebo se skóre < 0.5 jsou klasifikovány jako „hypotéza“ — nejslabší tvrzení.",
        "Confidence: artifacts without an explicit score or with a score < 0.5 are classified as “hypothesis” — the weakest claim.",
    ),
    "lim_trunc_timeline": (
        "Timeline je v reportu omezena na prvních {n} událostí (plný seznam: `stopa timeline <case>`).",
        "The timeline is limited to the first {n} events in this report (full list: `stopa timeline <case>`).",
    ),
    "lim_trunc_flagged": (
        "Flagované soubory jsou v reportu omezeny na prvních {n} položek.",
        "Flagged files are limited to the first {n} entries in this report.",
    ),
    "lim_trunc_manifest": (
        "Hash manifest je v reportu omezen na prvních {n} souborů (plný manifest v case DB).",
        "The hash manifest is limited to the first {n} files in this report (full manifest in the case DB).",
    ),
    # ── sekce 13 — závěr ────────────────────────────────────────
    "sec_conclusion": ("Závěr", "Conclusion"),
    "concl_summary": (
        ("Souhrn: {artifacts} artifactů, {flagged} flagovaných souborů, {marked} ručně označených souborů, "
         "{corr} korelací entit, {entities} entit, {events} timeline událostí."),
        ("Summary: {artifacts} artifacts, {flagged} flagged files, {marked} manually marked files, "
         "{corr} entity correlations, {entities} entities, {events} timeline events."),
    ),
    "concl_contra": (
        "Detekováno {n} rozporových skupin — souběžná aktivita jednoho subjektu v časovém okně (viz sekce 8.1).",
        "{n} contradiction groups detected — concurrent activity of one subject within the time window (see section 8.1).",
    ),
    "concl_dup": (
        "Detekováno {n} duplikátových skupin napříč zdroji — stejný obsah z různých souborů/zdrojů (viz sekce 8.1).",
        "{n} cross-source duplicate groups detected — same content from different files/sources (see section 8.1).",
    ),
    "concl_none": (
        "Žádné výrazné nálezy — případ obsahuje pouze základní evidence data.",
        "No significant findings — the case contains only basic evidence data.",
    ),
    # ── sekce 14 — provenience timestampů (STP-018) ─────────────
    "sec_provenance": ("Provenience timestampů (source vs derived)", "Timestamp provenance (source vs derived)"),
    "prov_source": (
        "Zdrojové timestamps (z obsahu souboru): {n}",
        "Source timestamps (from file content): {n}",
    ),
    "prov_derived": (
        "Odvozené timestamps (systémový/FS fallback): {n}",
        "Derived timestamps (system/FS fallback): {n}",
    ),
    "prov_none": ("Žádné timeline události s provenience.", "No timeline events with provenance."),
    # ── sekce 15 — evidence lineage (C2) ────────────────────────
    "sec_lineage": ("Evidence lineage — řetězec původu zjištění", "Evidence lineage — chain of origin"),
    "lineage_steps": (
        "Zaznamenáno {n} kroků v append-only řetězci (verze nástroje + hash konfigurace + vstupní/výstupní reference) — zpětné dohledání tvrzení až k původnímu zdroji.",
        "{n} steps recorded in the append-only chain (tool version + config hash + input/output references) — back-tracing any claim to its original source.",
    ),
    "lineage_none": ("Žádné zaznamenané kroky lineage pro tento případ.", "No lineage steps recorded for this case."),
    # ── sekce 16 — integrity Ed25519 (C4) ───────────────────────
    "sec_integrity": ("Integrity — Ed25519 kontrolní body", "Integrity — Ed25519 checkpoints"),
    "th_pubkey": ("Veřejný klíč (Ed25519, base64)", "Public key (Ed25519, base64)"),
    "integrity_none_key": (
        "Klíč nevygenerován — použij `stopa integrity <case> --init-key`.",
        "Key not generated — run `stopa integrity <case> --init-key`.",
    ),
    "th_audit_row": ("Audit řádek", "Audit row"),
    "th_last_hash": ("Poslední hash (SHA-256)", "Last hash (SHA-256)"),
    "th_reason": ("Důvod", "Reason"),
    "integrity_none_cp": ("Žádné kontrolní body.", "No checkpoints."),
    # ── sekce 17 — rejstřík entit (E4/I3) ───────────────────────
    "sec_entities": ("Rejstřík entit", "Entity registry"),
    "th_entity_kind": ("Typ entity", "Entity kind"),
    "th_entity_value": ("Hodnota (normalizovaná)", "Value (normalized)"),
    "th_first_seen": ("První výskyt (UTC)", "First seen (UTC)"),
    "th_last_seen": ("Poslední výskyt (UTC)", "Last seen (UTC)"),
    "empty_entities": ("Žádné extrahované entity.", "No extracted entities."),
    "truncated_entities": (
        "Zobrazeno prvních 500 z {n} entit (plný rejstřík v case DB).",
        "Showing first 500 of {n} entities (full registry in the case DB).",
    ),
    # ── sekce 18 — Příloha A: validace parserů (C3) ─────────────
    "sec_app_parsers": ("Příloha A — Validace parserů (C3)", "Appendix A — Parser validation (C3)"),
    "th_parser": ("Parser", "Parser"),
    "th_formats": ("Formáty / varianty", "Formats / variants"),
    "parsers_none": ("Registry se nepodařilo načíst (nesoulad s pipeline).", "The registry could not be loaded (pipeline mismatch)."),
    # ── sekce 19 — Příloha B: reprodukční prostředí (C5) ────────
    "sec_app_env": ("Příloha B — Reprodukční prostředí (C5)", "Appendix B — Reproducibility environment (C5)"),
    "env_note": (
        "Snapshot prostředí pro reprodukovatelnost běhu — stejné hodnoty jako v manifestu exportů.",
        "Environment snapshot for run reproducibility — the same values as in the export manifests.",
    ),
    # ── sekce 20 — Příloha C: rozložení důvěryhodnosti ──────────
    "sec_app_confidence": ("Příloha C — Rozložení důvěryhodnosti", "Appendix C — Confidence distribution"),
    "th_level": ("Úroveň", "Level"),
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
