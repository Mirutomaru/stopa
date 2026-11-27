"""STP-075 — referenční strana parseru ``file_meta`` (pilot vlna 2, design §7).

Nezávislá implementace čtení PDF /Info + OOXML docProps pro dvě nezávislé
cesty nad stejným vstupem (design §3):

- STOPA cesta: ``stopa.artifacts.file_meta`` → pipeline Artifact → entry fields
- referenční cesta: tento modul — ručně psané parsery (jen stdlib, žádný
  import ze ``stopa.domain`` / ``stopa.artifacts``) + per-fixture SHA-256 pin.

Varianty (deklarované per fixture v manifestu): ``pdf``, ``ooxml``.

Smlouva záznamů: entry fields = ``name`` (join klíč, název důkazového
souboru) + metadata pole ve tvaru daném formátem:

    PDF /Info        → title/author/creator/producer/created/modified
                       (daty D:… normalizovány na ISO 8601 — stejný kontrakt
                        jako doména; nezávislá implementace)
    OOXML core.xml   → title/author(=dc:creator)/modified_by/created/modified
    OOXML app.xml    → application/company/pages/words/characters/slides/
                       lines/paragraphs

``ts=None`` (dokumentová metadata nemají event čas) → field-based join klíč
(``name``). Množina klíčů = sjednocení nalezených polí; doménová komparace
treatuje chybějící ≡ None, takže obě cesty musí najít stejná pole pro
stejné bajty — přesně to pilot vlna 2 ověřuje. Prázdná metadata = žádný
záznam na obou stranách (shoda s ``build_file_meta_artifacts``).
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Mapping
from pathlib import Path

ARTIFACT_TYPE = "document_metadata"

#: varianta → implementace (dispatch přes globals(), pattern text_ref)
_VARIANTS: dict[str, str] = {
    "pdf": "_ref_pdf",
    "ooxml": "_ref_ooxml",
}


# ── PDF /Info — nezávislý sken (žádný import z domény) ─────────────────

_PDF_KEYS: dict[bytes, str] = {
    b"/Title": "title",
    b"/Author": "author",
    b"/Creator": "creator",
    b"/Producer": "producer",
    b"/CreationDate": "created",
    b"/ModDate": "modified",
}


def _ref_pdf_token(data: bytes, i: int) -> tuple[str | None, int]:
    """PDF string token na offsetu ``i`` — literal ``(…)`` s escapes/nestingem
    nebo hex ``<…>``. Vrací (text, konec). Sémantika ekvivalentní doméně,
    implementace nezávislá (pilot = dvě cesty nad stejnými bajty)."""
    if data[i:i + 1] == b"(":
        depth = 1
        j = i + 1
        out = bytearray()
        while j < len(data) and depth > 0:
            c = data[j:j + 1]
            if c == b"\\" and j + 1 < len(data):
                n = data[j + 1:j + 2]
                plain = {b"(": b"(", b")": b")", b"\\": b"\\"}
                ctrl = {b"n": b"\n", b"r": b"\r", b"t": b"\t"}
                if n in plain:
                    out += plain[n]
                    j += 2
                    continue
                if n in ctrl:
                    out += ctrl[n]
                    j += 2
                    continue
                # oktalový escape — maximálně 3 číslice (sémantika PDF)
                k = j + 1
                count = 0
                while k < len(data) and data[k:k + 1].isdigit() and count < 3:
                    count += 1
                    k += 1
                if count > 0:
                    out.append(int(data[j + 1:j + 1 + count], 8))
                    j = k
                else:
                    j += 2
                continue
            if c == b"(":
                depth += 1
                out += c
            elif c == b")":
                depth -= 1
                if depth > 0:
                    out += c
            else:
                out += c
            j += 1
        return out.decode("latin-1", "replace"), j

    # hex string <…> — bílé znaky ignorovány, lichý počet → doplněno '0'
    end = data.find(b">", i)
    if end == -1:
        return None, len(data)
    hx = bytes(c for c in data[i + 1:end] if chr(c) not in " \t\r\n")
    if len(hx) % 2:
        hx += b"0"
    try:
        value = bytes.fromhex(hx.decode("ascii")).decode("latin-1", "replace")
    except ValueError:
        return None, end + 1
    return value, end + 1


def _ref_clean_pdf_date(raw: str) -> str:
    """PDF date ``D:20260101120000+01'00'`` → ISO 8601 (vlastní implementace).

    Pravidla shodná s doménovým kontraktem: chybějící komponenty
    doplněny na minimum (01/00), ``Z`` → ``+00:00``, offset bez minut
    ignorován; neparsabilní vstup vrací nezměněn.
    """
    t = raw.strip()
    if not t.startswith("D:") or len(t) < 6:
        return raw
    body = t[2:]
    parts: list[str] = []
    for size in (4, 2, 2, 2, 2, 2):
        chunk = body[:size]
        if not chunk or not chunk.isdigit():
            break
        parts.append(chunk)
        body = body[size:]
    if not parts:
        return raw
    y = parts[0]
    mo = parts[1] if len(parts) > 1 else ""
    d = parts[2] if len(parts) > 2 else ""
    h = parts[3] if len(parts) > 3 else ""
    mi = parts[4] if len(parts) > 4 else ""
    s_ = parts[5] if len(parts) > 5 else ""
    ts = f"{y}-{mo or '01'}-{d or '01'}T{h or '00'}:{mi or '00'}:{s_ or '00'}"
    if body.startswith("Z"):
        return ts + "+00:00"
    m = re.match(r"([+-])(\d\d)'?(\d\d)'?", body)
    if m:
        sign, oh, omi = m.groups()
        return ts + f"{sign}{oh}:{omi or '00'}"
    return ts


def _ref_pdf_info(data: bytes) -> dict[str, str]:
    """PDF /Info — sken klíčů s validním string tokenem.

    Heuristika ekvivalentní doméně (první platná hodnota vyhrává; /Info bývá
    indirect reference), implementace nezávislá."""
    out: dict[str, str] = {}
    for key_bytes, field in _PDF_KEYS.items():
        start = 0
        while True:
            i = data.find(key_bytes, start)
            if i == -1:
                break
            j = i + len(key_bytes)
            while j < len(data) and data[j:j + 1] in b" \t\r\n":
                j += 1
            if j < len(data) and data[j:j + 1] in (b"(", b"<"):
                val, _end = _ref_pdf_token(data, j)
                if val:
                    v = val.strip()
                    if field in ("created", "modified"):
                        v = _ref_clean_pdf_date(v)
                    if v:
                        out.setdefault(field, v)
                        break
            start = i + len(key_bytes)
    return out


def _ref_pdf(data: bytes) -> list[dict]:
    """Varianta ``pdf`` — %PDF magic + /Info sken."""
    if not data.startswith(b"%PDF"):
        raise ValueError("očekávána %PDF magic v hlavičce fixtury")
    meta = _ref_pdf_info(data)
    if not meta:
        return []
    return [{"type": ARTIFACT_TYPE, "ts": None, "fields": {"name": "", **meta}}]


# ── OOXML docProps — nezávislé čtení (stdlib zipfile + ElementTree) ─────

_OOXML_CORE_FIELDS: dict[str, str] = {
    "title": "title",
    "creator": "author",
    "lastModifiedBy": "modified_by",
    "created": "created",
    "modified": "modified",
}

_OOXML_APP_FIELDS: dict[str, str] = {
    "Application": "application",
    "Company": "company",
    "Pages": "pages",
    "Words": "words",
    "Characters": "characters",
    "Slides": "slides",
    "Lines": "lines",
    "Paragraphs": "paragraphs",
}

#: Parita se stopa.domain.file_meta — max. velikost jednoho docProps člena.
_MAX_DOCPROPS_BYTES: int = 256 * 1024


def _ref_read_member(zf: zipfile.ZipFile, name: str) -> bytes | None:
    """Omezené čtení docProps člena (abnormálně velký člen → přeskočí se)."""
    try:
        with zf.open(name) as fh:
            data = fh.read(_MAX_DOCPROPS_BYTES + 1)
    except (KeyError, OSError):
        return None
    if len(data) > _MAX_DOCPROPS_BYTES:
        return None
    return data


def _ref_ooxml_info(data: bytes) -> dict[str, str]:
    """OOXML docProps — core.xml (Dublin Core) + app.xml.

    Rozlišení prvků podle lokálního jména tagu (namespace agnosticky),
    plain ``ElementTree.fromstring`` (fixtury jsou malé; bounded parse je
    doménová bezpečnostní vrstva, referenční cesta ověřuje obsah)."""
    out: dict[str, str] = {}
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return out

    names = set(zf.namelist())
    if "docProps/core.xml" in names:
        raw = _ref_read_member(zf, "docProps/core.xml")
        root: ET.Element | None = None
        if raw is not None:
            try:
                root = ET.fromstring(raw)
            except ET.ParseError:
                root = None
        if root is not None:
            for local, field in _OOXML_CORE_FIELDS.items():
                for el in root.iter():
                    if el.tag.split("}")[-1] != local:
                        continue
                    text = (el.text or "").strip()
                    if text:
                        out.setdefault(field, text)
                        break

    if "docProps/app.xml" in names:
        raw = _ref_read_member(zf, "docProps/app.xml")
        root = None
        if raw is not None:
            try:
                root = ET.fromstring(raw)
            except ET.ParseError:
                root = None
        if root is not None:
            for el in root.iter():
                field = _OOXML_APP_FIELDS.get(el.tag.split("}")[-1])
                if not field:
                    continue
                text = (el.text or "").strip()
                if text:
                    out.setdefault(field, text)
    return out


def _ref_ooxml(data: bytes) -> list[dict]:
    """Varianta ``ooxml`` — PK zip magic + docProps."""
    if data[:4] != b"PK\x03\x04":
        raise ValueError("očekávána PK zip magic v hlavičce fixtury")
    meta = _ref_ooxml_info(data)
    if not meta:
        return []
    return [{"type": ARTIFACT_TYPE, "ts": None, "fields": {"name": "", **meta}}]


# ── manifest + entry body (pattern text_ref / sqlite_ref) ───────────────


def load_meta_manifest(path: Path) -> Mapping[str, object]:
    """Načte + validuje manifest file_meta reference datasetu.

    Povinné klíče: ``version`` (== 1), ``parser_id``, ``reference_tool``,
    ``join_keys`` (mapa typ → list neprázdných str) a ``fixtures`` (neprázdný
    list záznamů ``{file, sha256, variant}`` s deklarovanou variantou).

    Raises:
        ValueError: souborová chyba / neplatný JSON / nesplněná validace.
        TypeError: JSON objekt není dict / fixture záznam není objekt.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{path}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: neplatný JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise TypeError(f"{path}: očekáván JSON objekt, dostalo {type(data).__name__}")

    if data.get("version") != 1:
        raise ValueError(f"{path}: nepodporovaná verze manifestu (očekáváno 1)")
    for key in ("parser_id", "reference_tool"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{path}: klíč {key!r} musí být neprázdný string")

    join_keys = data.get("join_keys")
    if not isinstance(join_keys, dict) or not join_keys:
        raise ValueError(f"{path}: 'join_keys' musí být neprázdná mapa typ → pole")
    for type_name, fields in join_keys.items():
        if (
            not isinstance(type_name, str)
            or not isinstance(fields, list)
            or not all(isinstance(f, str) and f.strip() for f in fields)
        ):
            raise ValueError(f"{path}: join_keys[{type_name!r}] musí být list neprázdných pole")

    fixtures = data.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError(f"{path}: 'fixtures' musí být neprázdný list záznamů")
    for fx in fixtures:
        if not isinstance(fx, dict):
            raise TypeError(f"{path}: fixture záznam musí být objekt")
        name = fx.get("file")
        sha = fx.get("sha256")
        variant = fx.get("variant")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{path}: fixture klíč 'file' chybí nebo je prázdný")
        if not isinstance(sha, str) or len(sha) != 64:
            raise ValueError(f"{path}: fixture {name!r} — 'sha256' musí být 64-znakový hex")
        if variant not in _VARIANTS:
            known = ", ".join(sorted(_VARIANTS))
            raise ValueError(
                f"{path}: fixture {name!r} — neznámá reference varianta "
                f"{variant!r} (deklarované: {known})"
            )
    return data


def run_stopa_filemeta(path: Path) -> list[dict]:
    """STOPA strana: pipeline extraktor → surové entry.

    Entry fields = ``name`` + nalezená metadata pole (klíč ``engine`` je
    provenience a do komparace se nebere). Prázdná metadata = žádný záznam."""
    from stopa.artifacts.file_meta import extract_file_meta_artifacts  # I/O vrstva

    entries: list[dict] = []
    for artifact in extract_file_meta_artifacts(path):
        details = dict(artifact.details or {})
        fields = {key: value for key, value in details.items() if key != "engine"}
        entries.append({"type": ARTIFACT_TYPE, "ts": None, "fields": fields})
    return entries


def _fixture_for(manifest: Mapping[str, object], name: str) -> Mapping[str, object]:
    """Fixture záznam manifestu podle názvu souboru (fail-fast)."""
    fixtures = manifest["fixtures"]  # validováno v load_meta_manifest
    for fx in fixtures:  # type: ignore[union-attr]
        if isinstance(fx, Mapping) and fx.get("file") == name:
            return fx
    declared = ", ".join(
        str(fx.get("file")) for fx in fixtures if isinstance(fx, Mapping)  # type: ignore[union-attr]
    ) or "(žádné)"
    raise ValueError(f"manifest: fixture {name!r} není deklarovaná (deklarováno: {declared})")


def read_reference_entries(path: Path, manifest: Mapping[str, object]) -> list[dict]:
    """Referenční strana: vlastní čtení dle varianty deklarované v manifestu.

    Fail-fast kontrola SHA-256 pinu fixtury (drift důkazu = vstupní chyba) a
    dispatch na nezávislý parser varianty. Pole ``name`` se doplní až zde —
    parsery pracují jen s obsahem.

    Raises:
        ValueError: fixture nedeklarovaná, hash-pin se neshoduje, chyba čtení,
            magic nesedí s deklarovanou variantou.
    """
    fx = _fixture_for(manifest, path.name)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{path}: {exc.strerror or exc}") from exc
    actual = hashlib.sha256(data).hexdigest()
    if actual != fx["sha256"]:
        raise ValueError(
            f"hash fixtury se neshoduje s pinem v manifestu "
            f"(manifest {str(fx['sha256'])[:12]}… vs vstup {actual[:12]}…)"
        )
    parser_name = str(fx["variant"])  # validováno při načtení manifestu
    entries = globals()[_VARIANTS[parser_name]](data)
    for entry in entries:
        entry["fields"]["name"] = path.name
    return entries
