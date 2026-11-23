"""P1 security — omezené XML parsování nedůvěryhodných důkazových souborů.

``xml.etree.ElementTree`` nemá žádnou ochranu proti dvěma klasickým bombám:

- **billion laughs** (expanze entit): ``<!DOCTYPE ... [<!ENTITY x "...">]>``
  se vzájemnými definicemi → exponenciální růst paměti,
- **hloubková bomba**: miliony vnořených prvků → RecursionError / přetečení C-stacku.

Tento modul poskytuje :func:`bounded_xml_parse` — stejný ElementTree výsledek,
ale s limitem hloubky prvků a zákazem uživatelských entit (předdefinované
``&amp;``/``&lt;`` apod. řeší expat interně a nespádají do handleru).

Implementace: ruční propojení ``xml.parsers.expat`` (stejným způsobem, jak to
dělá čistě-pythonová ElementTree) — C-akcelerovaný ``ET.XMLParser`` si totiž
svoj interní expat objekt neukládá jako přístupný atribut a ElementTree sám
``EntityDeclHandler`` nikdy nepropojí.

Doménová vrstva = čistá logika bez I/O (stream se čte jen z předaného
souborového objektu v kusech 64 KiB — špičková paměť ≈ délka jednoho tagu).

Použití: všude, kde se parsují důkazové soubory (OOXML/ODF metadata, Windows
XML artefakty, UFED report.xml) — místo ``ET.fromstring`` / ``ET.parse``.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET
from xml.parsers import expat

__all__ = ["DEFAULT_MAX_DEPTH", "XmlLimitError", "bounded_xml_parse"]

#: Maximální hloubka vnoření prvků pro důkazové soubory (legitimní XML < 100).
DEFAULT_MAX_DEPTH: int = 200


class XmlLimitError(ValueError):
    """XML překročil bezpečnostní limit (hloubka / riziko expanze entit)."""


def _entity_decl(name, is_parameter_entity, value, base, *rest) -> None:
    """EntityDeclHandler — jakákoli uživatelská entity = riziko expanze.

    ElementTree si tento handler sám nepropojí; předdefinované entity
    (``&amp;`` apod.) expat řeší interně a sem nedorazí. (pyexpat volá s 7
    argumenty — plná expat signatura.)
    """
    raise XmlLimitError(
        f"XML definuje vlastní entitu {name!r} (riziko expanze — billion laughs)"
    )


class _DepthTarget(ET.TreeBuilder):
    """TreeBuilder, který počítá hloubku prvků a při překročení limitu hodí."""

    def __init__(self, max_depth: int) -> None:
        self._max = max_depth
        self._depth = 0
        super().__init__()

    def start(self, tag, attrib):
        self._depth += 1
        if self._depth > self._max:
            raise XmlLimitError(f"XML hloubka {self._depth} překročila limit {self._max}")
        return super().start(tag, attrib)

    def end(self, name):
        super().end(name)
        self._depth -= 1


def bounded_xml_parse(source, *, max_depth: int = DEFAULT_MAX_DEPTH):
    """Parsovat XML s limitem hloubky a entit → kořenový ``Element``.

    Args:
        source: ``bytes``, ``str`` nebo binárně čitelný file-like objekt (stream).
        max_depth: maximální hloubka vnoření prvků; překročení → :class:`XmlLimitError`.

    Raises:
        XmlLimitError: hloubkový limit, nebo uživatelská entity v dokumentu.
        ET.ParseError: poškozené XML (stejná sémantika jako ``ET.fromstring``).
    """
    target = _DepthTarget(max_depth)
    parser = expat.ParserCreate(None, "}")  # namespace režim — stejně jako ElementTree

    # pyexpat v namespace režimu podává názvy jako "uri}local" (bez vedoucího "{") —
    # ElementTree vlastní _fixname ho doplní; děláme totéž pro tagy i klíče atributů.
    def _fixname(key):
        if "}" in key:
            return "{" + key
        return key

    def _start(tag, attr_list):
        # pyexpat s ordered_attributes=1 podává atributy jako plochý list
        # [name, value, ...] (prázdný = []) — C TreeBuilder očekává dict.
        if isinstance(attr_list, dict):
            attrib = {_fixname(k): v for k, v in attr_list.items()}
        else:
            attrib = {
                _fixname(attr_list[i]): attr_list[i + 1] for i in range(0, len(attr_list), 2)
            }
        return target.start(_fixname(tag), attrib)

    def _end(tag):
        # stejná normalizace jako u start — jinak C TreeBuilder nezapojí close tag
        target.end(_fixname(tag))

    def _data(text):
        target.data(text)

    parser.StartElementHandler = _start
    parser.EndElementHandler = _end
    parser.CharacterDataHandler = target.data
    parser.DefaultHandlerExpand = _data  # expanze entit (&amp; apod.)
    parser.EntityDeclHandler = _entity_decl
    parser.buffer_text = 1
    parser.ordered_attributes = 1

    try:
        if isinstance(source, str):
            source = source.encode("utf-8")
        if isinstance(source, (bytes, bytearray, memoryview)):
            parser.Parse(bytes(source))
        else:  # file-like — stream v kusech, celý soubor se do RAM nečte
            while True:
                chunk = source.read(65536)
                if not chunk:
                    break
                parser.Parse(chunk)
        parser.Parse(b"", True)  # konec dat; useknutý dokument → ExpatError tady
    except expat.ExpatError as e:
        raise ET.ParseError(str(e)) from e

    return target.close()
