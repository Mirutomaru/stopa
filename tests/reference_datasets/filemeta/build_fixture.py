"""STP-075 / vlna 31 — deterministická reference data pro parser ``file_meta``.

Vytvoří 4 dokumentové fixtury (PDF + OOXML rodina docx/xlsx/pptx) s
per-fixture SHA-256 piny v manifestu a goldeny normalizovaných záznamů
(produkované přes `differential.normalize_dataset` referenční cesty —
nezávislá STOPA cesta musí produkovat byte-stejný tvar po JSON serializaci).

Determinismus: čistě stdlib; ZIP členy s fixním date_time=(1980,1,1) a
ZIP_STORED (žádná závislost na verzi zlib), PDF = ručně skládané bajty.

Běh: ``python build_fixture.py [outdir]`` (výchozí = adresář tohoto skriptu).
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

# ── PDF fixtura — ručně skládané bajty (všechny 6 /Info klíčů) ──────────
# Title: escaped parens → "Annual Report (Q4) - final version 2"
# Author: oktalový escape \101 = 'A' → "Jane A. Doe"
# CreationDate/ModDate: dva tvary PDF data s časovým offsetem (parita testu).
SAMPLE_PDF = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Info 3 0 R >>
endobj
3 0 obj
<< /Title (Annual Report \\(Q4\\) - final version 2) /Author (Jane \\101. Doe) /Creator (STOPA Pilot Generator) /Producer (diffref-wave2/1.0) /CreationDate (D:20260315143000+02'00') /ModDate (D:20260401090000Z) >>
endobj
trailer << /Root 1 0 R >>
%%EOF
"""

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>
"""

DOCX_CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Quarterly Planning Document</dc:title>
  <dc:creator>Miroslav Mat\u00fa\u0161</dc:creator>
  <cp:lastModifiedBy>Jana Nov\u00e1kov\u00e1</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">2026-05-10T08:00:00Z</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">2026-06-01T17:45:30Z</dcterms:modified>
</cp:coreProperties>
"""

DOCX_APP = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Application>Microsoft Office Word</Application>
  <Company>Komunik\u00e1tor s.r.o.</Company>
  <Pages>12</Pages>
  <Words>3456</Words>
  <Characters>21034</Characters>
</Properties>
"""

# XLSX — méně polí (bez lastModifiedBy/modified; bez Pages/Words) → sjednocení
# klíčů musí na obou cestách dojít ke stejnému výsledku (chybějící ≡ None).
XLSX_CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Budget Overview FY26</dc:title>
  <dc:creator>Petr Sv\u00ed\u0159ek</dc:creator>
  <dcterms:created xsi:type="dcterms:W3CDTF">2026-01-20T11:30:00Z</dcterms:created>
</cp:coreProperties>
"""

XLSX_APP = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Application>Microsoft Excel</Application>
  <Company>Komunik\u00e1tor s.r.o.</Company>
  <Characters>89204</Characters>
  <Lines>1204</Lines>
  <Paragraphs>632</Paragraphs>
</Properties>
"""

# PPTX — kompletní core (daty s offsetem, ne Z) + Slides v app.xml.
PPTX_CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Product Roadmap Q3</dc:title>
  <dc:creator>T\u00e1ňa Dvo\u0159\u00e1kov\u00e1</dc:creator>
  <cp:lastModifiedBy>Miroslav Mat\u00fa\u0161</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">2026-07-04T09:00:00+02:00</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">2026-08-15T16:20:10+02:00</dcterms:modified>
</cp:coreProperties>
"""

PPTX_APP = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Application>Microsoft PowerPoint</Application>
  <Company>Komunik\u00e1tor s.r.o.</Company>
  <Slides>24</Slides>
</Properties>
"""

#: (názv, varianta, obsah) — pořadí = pořadí v manifestu.
FIXTURES: dict[str, str] = {
    "sample.pdf": "pdf",
    "sample.docx": "ooxml",
    "sample.xlsx": "ooxml",
    "sample.pptx": "ooxml",
}


def _zip_bytes(members: dict[str, str]) -> bytes:
    """Deterministický ZIP — STORED + fixní date_time (zlib-verze nehrává)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for name, content in members.items():
            info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            zf.writestr(info, content)
    return buf.getvalue()


def fixture_bytes(name: str) -> bytes:
    if name == "sample.pdf":
        return SAMPLE_PDF
    common = {"[Content_Types].xml": CONTENT_TYPES}
    if name == "sample.docx":
        members = dict(common, **{"docProps/core.xml": DOCX_CORE, "docProps/app.xml": DOCX_APP})
    elif name == "sample.xlsx":
        members = dict(common, **{"docProps/core.xml": XLSX_CORE, "docProps/app.xml": XLSX_APP})
    else:  # sample.pptx
        members = dict(common, **{"docProps/core.xml": PPTX_CORE, "docProps/app.xml": PPTX_APP})
    return _zip_bytes(members)


def build(outdir: Path) -> None:
    """Vytvoří fixtury + manifest (SHA-256 piny) + goldeny normalizovaných záznamů."""
    from stopa.diffref.meta_ref import load_meta_manifest, read_reference_entries
    from stopa.domain.differential import JoinKeySpec, normalize_dataset

    outdir.mkdir(parents=True, exist_ok=True)
    pins: dict[str, str] = {}
    for name in FIXTURES:
        data = fixture_bytes(name)
        (outdir / name).write_bytes(data)
        pins[name] = hashlib.sha256(data).hexdigest()

    manifest = {
        "version": 1,
        "parser_id": "file_meta",
        "reference_tool": (
            "diffref-meta-stdlib/1.0 (hand-written parsers: PDF /Info byte scan + "
            "OOXML docProps via stdlib zipfile+ElementTree)"
        ),
        # Dokumentová metadata nemají event čas → na obou cestách ts=None;
        # created/modified se porovnávají jako stringová pole (§3).
        "time_note": (
            "document metadata has no event time — both sides emit ts=None; "
            "created/modified are compared as string fields per format"
        ),
        "field_contract": (
            "name = evidence file name (join key); field set is format-defined: "
            "PDF /Info -> title/author/creator/producer/created/modified "
            "(D:... normalized to ISO 8601, same contract as domain), "
            "OOXML core.xml -> title/author(=dc:creator)/modified_by/created/modified, "
            "OOXML app.xml -> application/company/pages/words/characters/slides/"
            "lines/paragraphs; missing field == None on both sides (union compare)"
        ),
        # Identita dokumentu = název důkazového souboru (1 záznam na dokument).
        "join_keys": {"document_metadata": ["name"]},
        "fixtures": [
            {"file": name, "sha256": pins[name], "variant": FIXTURES[name]} for name in FIXTURES
        ],
    }
    (outdir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )

    # Goldeny: referenční cesta → sdílená normalizační vrstva (§3) → JSON.
    validated = load_meta_manifest(outdir / "manifest.json")
    join_spec: dict[str, JoinKeySpec] = {
        artifact_type: tuple(fields) for artifact_type, fields in manifest["join_keys"].items()
    }
    for name in FIXTURES:
        entries = read_reference_entries(outdir / name, validated)
        records = normalize_dataset(entries, join_keys=join_spec)
        # fields je mappingproxy — asdict() selže; explicitní serializace tvaru golden.
        payload = [
            {"type": record.type, "ts_epoch": record.ts_epoch, "fields": dict(record.fields)}
            for record in records
        ]
        ext = name.rsplit(".", 1)[-1]
        golden = outdir / f"expected_sample_{ext}.json"
        golden.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    print(
        "STP-075 reference dataset: "
        + ", ".join(f"{k}={v[:12]}…" for k, v in pins.items())
    )


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent)
