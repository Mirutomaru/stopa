# Changelog

Všechno významné změny v STOPA jsou dokumentovány v tomto souboru.

Formát následuje [Keep a Changelog](https://keepachangelog.com/cs/1.0.0/) a projekt
respektuje [Semantické verzování](https://semver.org/lang/cs/).

## [Unreleased]

## [1.0.0] — 2026-11-10

První stabilní release. Konsoliduje celý vývoj od vývojové verze 0.1.0 (září–listopad
2026). **Žádné breaking changes** — veřejné API, CLI i DB schéma jsou nadstavbou;
DB migrace běží automaticky při otevření starších případů (v8→v14).

### Přidáno (Added)

#### Jádro a pipeline
- Unifikovaný forenzní ingest: case DB (SQLite), hashing SHA-256/MD5, signatury souborů,
  bad-extension detekce, deduplikace, hash sety, profily.
- Paralelizace ingestu (`process_source(max_workers=)`) + checkpointing `add --resume`.
- Disk images: detekce typu (E01/AFF4/RAW-DD), TSK file systems přes **pytsk3** s fallbackem
  na CLI binárky, streaming carving (mmap sliding window).
- E01/AFF4 kontejnery přes ctypes (`libewf`/`libafflib`, `STOPA_EWF_LIB`).
- Mobilní extrakce: logická (kontakty, WhatsApp, iOS Safari) + physical/FDE.

#### Forenzní formáty (FDE / šifrování)
- STOPAFDE + Android FBE (AES-256-XTS sektorová šifra) v čistém Pythonu.
- LUKS1/2 detekce a dešifrování (cryptsetup, vyžaduje root).
- Keyfile import pro FDE/FBE/LUKS (`mobile --keyfile`).
- Streaming FDE dekódování (peak RAM ~420→~17 MB na 100 MB obrazu).

#### Artefaktové extraktory (88)
- Windows: MS-LNK, MS-PREFETCH (MAM + LZXPRESS Huffman), Jump Lists, Event Log `.evtx`
  (EVTX/CHUNK i `ElfFile` varianta s BinXML deflate dekomprezi), AppCompatCache, ShimCache,
  NTFS `$UsnJrnl`.
- Registry hives (regf/regipy) + Apple plists (binární i XML).
- SQLite extraktoři: browser history, messaging (iMessage `chat.db`, Android SMS, call logy),
  iCloud Messages warrant return.
- Port AXIOM extraktorů (ETAPA B): email, WiFi, ScheduledTasks, netstat, Google Takeout,
  Chrome profily/sync, cloud SNS exporty (Instagram/Snapchat/Twitter/X/Facebook/Box/Dropbox/Mega),
  Microsoft+Amazon cloud, memory forensics.
- File metadata: PDF/OOXML/ID3v2/MP4/EXIF + porovnání (`diff_metadata`).

#### Analýza a inteligence
- Full-text search FTS5 (external-content index) + rozšířené filtry
  (`size:>1MB`, `mtime:A..B`, `ext:jpg`, hash lookup, `in-artifact:X`).
- Timeline Engine: materializovaná timeline, TZ konverze, detekce nesrovnalostí a duplikátů.
- Entity + Correlation Engine (normalizace entit, 3 korelační pravidla) + SVG entity graph GUI.
- Evidence Manager: audit log (neměnná SWGDE-style stopa), custody items, verze parserů.
- Unified Evidence Model + Lineage Engine + Parser Validation Registry.
- AI Forensic Assistant (LM Studio): 3 režimy, **100 % validace citací** proti DB,
  grounding engine (ověřování tvrzení vs data citovaných artifactů), PII redaktor.

#### Reporting a export
- Court-ready HTML/PDF reporty s chain of custody (SHA-256+MD5 manifest).
- Report rozšířen na 20 sekcí + i18n cs/en + confidence štítky [ověřeno/odvozeno/hypotéza].
- Export: CSV/JSON/JSONL/XML/**STIX 2.1** + interop formáty (Plaso `l2tcsv`, UCO mapping).
- Interop: Plaso import/export, Timesketch push (klient + UI polling status), ZIP bundle,
  plánované/periodické auto-bundle exporty (`--auto-export`).

#### Web GUI
- FastAPI backend + vanilla JS SPA bez build kroku; 47 endpointů.
- 3-pane desktop layout, File Inspector (hex dump + metadata + porovnání), partition map.
- Cmd+K FTS5 search, data grid s nekonečným scrollováním a klávesovou navigací.
- Entity Graph + Correlation sekce, AI Assistant panel, Audit Center, Diagnostics, Settings.
- RBAC (role-based access control) + role switch UI.

#### Bezpečnost a integrity
- Evidence Integrity 2.0: hash chaining, Ed25519 kontrolní body, manifesty.
- Reproducibility Engine: záznam operací, replay, porovnání výsledků.
- SHA-512 integrity vrstva + minimální RBAC + pip-audit CI.
- Parser sandbox kontrakt (izolace parserů, fix hang bugu sqlite_carver).
- Opravy path traversal (case_id validace, `_read_file_bytes` resolve+prefix check).

#### Distribuce a CLI
- **R0.2 — distributivní balíčky**: `.deb`/`.rpm`/AppImage/Docker image (<1.5 GB) + wheel/sdist;
  offline instalace přes vendored wheels (cp310–cp313), `postinst.sh` postaví venv bez sítě.
- **R0.4 — CLI UX**: `--json` na všech subpříkazách (validní JSON i error cesty),
  Rich progress bary, `--help` s příklady u každého subpříkazu.
- Nový top-level flag `stopa --version`.

### Změněno (Changed)
- DB schéma migrace v8→v14 (automatické, backward-kompatibilní).
- EVTX parser verze 1.0→1.1: ElfFile varianta už nevrací `None` v event_id/timestamp
  (ElfR walk + BinXML deflate dekomprese + timestamp z MS-EVLOG headeru).
- Rozdělení monolitu `data/db.py` na repozitáře (Case/File/Audit/Artifact/Entity) + facade.

### Opraveno (Fixed)
- Argparse crash v `timeline --path --help` (neescape `%text%`).
- Chybějící help epilog u subpříkazu `serve`.
- JSON error cesty v `analyze` (plain text narušoval validitu stdout).
- RAM peak při streamingu FDE a velkých E01.

### Bezpečnostní opravy (Security)
- Path traversal ×2 (case_id + čtení souborů ven z kořene zdroje).
- PII redaktor pro AI odpovědi; ochrana proti prompt injection v RAG.

## [0.1.0] — 2026-09/10 (vývojová)
Počáteční vývoj: case DB, ingest pipeline, SQLite extraktoři, FTS5 search, disk images,
mobilní extrakce, web GUI a court-ready reporty. Podrobnosti viz commit historie
(`git log`); od 1.0.0 se všechny změny evidují v tomto souboru.

[Unreleased]: https://github.com/Mirutomaru/stopa/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Mirutomaru/stopa/releases/tag/v1.0.0
