"""STP-051 — File Preview klasifikace (oblast G, File Intelligence).

ČISTÁ logika nad bajty + názvem souboru — žádné IO → offline testovatelné.
Rozhoduje, jaký preview UI zobrazit: image / audio / video / text / None.

Heuristika je konzervativní (jako signatures.py): známá signatura mimo
image/audio/media rodiny → žádný preview (PDF/DOCX/exe se netiskou raw),
neznámá signatura → textová heuristika (printable ratio, bez NUL).
"""

from __future__ import annotations

from stopa.domain.signatures import detect_signature

# ── MIME mapy pro inline preview (typ z detekce > přípona) ────────────
_PREVIEW_MIME_BY_TYPE: dict[str, str] = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "webp": "image/webp",
    "mp3_id3": "audio/mpeg",
    "mp3_frame": "audio/mpeg",
    "wav": "audio/wav",
    "iso_bmff": "video/mp4",  # MP4/MOV — M4A audio se v UI stejně nezobrazí
    "avi": "video/x-msvideo",
}

_PREVIEW_MIME_BY_EXT: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
}


def classify_preview(head: bytes, name: str) -> str | None:
    """Typ previewu pro UI: ``image`` / ``audio`` / ``video`` / ``text`` / None.

    ``head`` = první kilobajty souboru (stačí hlavička + textová vzorka).
    ``name`` se používá jen pro MIME fallback, ne pro klasifikaci.
    """
    if not head:
        return None
    detected = detect_signature(head)
    if detected is not None:
        _typ, family = detected
        if family == "image":
            return "image"
        if family == "audio":
            return "audio"
        if family == "media":
            return "video"
        # známý formát mimo preview rodiny (pdf/docx/zip/exe/db…) → žádné preview
        return None
    # neznámá signatura → textová heuristika
    return "text" if _looks_like_text(head) else None


def preview_media_type(signature_type: str | None, name: str) -> str | None:
    """MIME pro inline odpověď — detekovaný typ má prioritu před příponou."""
    if signature_type and signature_type in _PREVIEW_MIME_BY_TYPE:
        return _PREVIEW_MIME_BY_TYPE[signature_type]
    lower = (name or "").lower()
    dot = lower.rfind(".")
    if dot >= 0:
        ext = lower[dot:]
        if ext in _PREVIEW_MIME_BY_EXT:
            return _PREVIEW_MIME_BY_EXT[ext]
    return None


def extract_text_preview(data: bytes, max_chars: int = 4000) -> tuple[str, bool]:
    """Textový obsah pro preview — ``(text, truncated)``.

    Dekódování UTF-8 strict → fallback latin-1 (cp1250 texty). Truncace na
    ``max_chars`` znaků; ``truncated=True`` když bylo více.
    """
    try:
        s = data.decode("utf-8")
    except UnicodeDecodeError:
        s = data.decode("latin-1", errors="replace")
    if len(s) <= max_chars:
        return s, False
    return s[:max_chars], True


def _looks_like_text(data: bytes) -> bool:
    """Konzervativní textová heuristika — NUL = binárka, printable ≥ 95 %."""
    if b"\x00" in data:
        return False
    try:
        s = data.decode("utf-8")
    except UnicodeDecodeError:
        s = data.decode("latin-1", errors="replace")
    if not s:
        return False
    printable = sum(1 for c in s if c.isprintable() or c in "\t\n\r")
    return printable / len(s) >= 0.95
