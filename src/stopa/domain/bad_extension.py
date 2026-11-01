"""FTK „Flag Bad Extensions“ — rozpor mezi reálným typem (signatura) a příponou.

ČISTÁ logika: dostane kanonický typ z magic bytes + příponu souboru,
vrátí True pokud se neshodují (např. .jpg co je ve skutečnosti PE executable).
"""

from __future__ import annotations

# kanonický typ → množina akceptovatelných přípon (malá písmena, bez tečky)
TYPE_EXTENSIONS: dict[str, frozenset[str]] = {
    "png": frozenset({"png"}),
    "jpeg": frozenset({"jpg", "jpeg", "jpe", "jfif"}),
    "gif": frozenset({"gif"}),
    "bmp": frozenset({"bmp"}),
    "tiff": frozenset({"tif", "tiff"}),
    "webp": frozenset({"webp"}),
    "pdf": frozenset({"pdf"}),
    "zip": frozenset({"zip"}),
    "docx": frozenset({"docx"}),
    "xlsx": frozenset({"xlsx"}),
    "pptx": frozenset({"pptx"}),
    "ooxml": frozenset({"docx", "xlsx", "pptx"}),
    "apk": frozenset({"apk"}),
    "ole2": frozenset({"doc", "xls", "ppt", "mdb", "msi", "msg", "pst"}),
    "sqlite": frozenset({"db", "sqlite", "sqlite3", "sdf", "wlp", "webstorage"}),
    "elf": frozenset({"so", "bin", "out", "exe", "elf"}),  # ELF bez přípony je běžné → neflagovat
    "pe": frozenset({"exe", "dll", "sys", "ocx", "scr", "com", "msi"}),
    "macho32": frozenset({"dylib", "app", "bin"}),
    "macho64": frozenset({"dylib", "app", "bin"}),
    "7zip": frozenset({"7z"}),
    "rar": frozenset({"rar"}),
    "iso_bmff": frozenset({"mp4", "m4v", "mov", "m4a", "m4b", "3gp"}),
    "mp3_id3": frozenset({"mp3"}),
    "mp3_frame": frozenset({"mp3"}),
    "wav": frozenset({"wav"}),
    "avi": frozenset({"avi"}),
    # E6 Windows artefakty — LNK jako .exe/.dll se flaguje (rozpor signatury)
    "lnk": frozenset({"lnk", "url"}),
    "win_prefetch": frozenset({"pf"}),
}


def extension_of(name: str) -> str | None:
    """Přípona bez tečky, malá písmena; bez přípony → None."""
    if "." not in name or name.startswith(".") and name.count(".") == 1:
        return None
    ext = name.rsplit(".", 1)[-1].lower()
    return ext or None


def is_bad_extension(signature_type: str | None, filename: str) -> bool:
    """True pokud signatura říká jiný typ než přípona naznačuje.

    Pravidla (konzervativní — FTK flaguje jen jisté rozporné případy):
    - neznámá signatura → False (nemůžeme nic tvrdit)
    - chybějící přípona → False (ELF binárky bez přípony jsou normální)
    - přípona v akceptovatelné množině typu → False
    - jinak → True
    """
    if signature_type is None:
        return False
    ext = extension_of(filename)
    if ext is None:
        return False
    allowed = TYPE_EXTENSIONS.get(signature_type)
    if allowed is None:  # typ bez definovaných přípon — neflagovat
        return False
    return ext not in allowed
