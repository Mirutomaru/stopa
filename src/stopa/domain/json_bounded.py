"""P3 — omezené JSON parsování pro nedůvěryhodná důkazová data.

Doplňuje :mod:`stopa.domain.xml_bounded` (P1): oba moduly chrání C parsery
před patologicky hlubokým vnořením, které by jinak vyčerpalo pythonovský
rekurzní limit (``RecursionError``) nebo — u ``json.loads`` — mohlo při
extrémní hloubce dopadnout až na stack C parseru.

Definice hloubky: počet vnořených kontejnerů (``{`` a ``[``) podél cesty od
kořene; kořenový kontejner počítá jako úroveň 1. Většina reálných důkazových
souborů (Takeout, CloudTrail apod.) má hloubku < 30 — limit 200 je s velkou
rezervou pod prahem, kde by C parser začal tlakat na rekurzní limit
interpreteru.

Implementační poznámka: sken hloubky je lineární (C-level regex přes tokény
"řetězec | závorka"), takže závorky uvnitř JSON řetězců se nepochytí.
Rychlá prekontrola (celkový počet otevíracích závorek) sken vůbec nespustí,
pokud hloubka zjevně nemůže limit překročit — typické malé dokumenty tak
projdou jen dvěma C-level passy; větší dokumenty zdraží řádově milisekundy.

Čistá doménová vrstva — žádné I/O; offline testovatelné.
"""

from __future__ import annotations

import json
import re
from typing import Any

#: Výchozí limit vnoření (modulová globála čtená v době volání → monkeypatchovatelné).
DEFAULT_MAX_DEPTH = 200

# Jeden tokén: kompletní JSON řetězec (s escape sekvencemi) nebo jedna závorka.
# Pro platné JSON je sken přesný; pro neplatné vstup hloubka nemusí sedět,
# ale tu už rozhodne json.loads (oba výstupy = ValueError).
_TOKEN_RE = re.compile(r'"(?:\\.|[^"\\\n])*"|[\[\]{}]', re.DOTALL)


class JsonLimitError(ValueError):
    """Hloubka vnoření JSON překročila limit.

    Sémantika: sémantická chyba (JSON je syntakticky platné, jen příliš
    hluboké na bezpečné parsování). Podtřída :class:`ValueError` — volající
    místa, která chytají ValueError/Exception, zachovávají kontrakt.
    """


def _max_depth(s: str) -> int:
    """Maximální hloubka vnoření kontejnerů (kořen = 1)."""
    depth = 0
    max_d = 0
    for m in _TOKEN_RE.finditer(s):
        tok = m.group(0)
        c = tok[0]
        if c == '"':
            continue  # řetězec — závorky uvnitř se nepočítají
        if c == "{" or c == "[":
            depth += 1
            max_d = max(max_d, depth)
        else:
            depth -= 1
    return max_d


def bounded_json_loads(
    data: str | bytes | bytearray, *, max_depth: int | None = None
) -> Any:
    """``json.loads`` s limitem hloubky vnoření.

    Args:
        data: ``str``, ``bytes`` nebo ``bytearray`` (binární → decode UTF-8 s
            ``errors="replace"`` — stejná sémantika jako předchozí volající
            místa, která dekovala sama).
        max_depth: limit úrovní vnoření; default :data:`DEFAULT_MAX_DEPTH`.

    Returns:
        To samé, co ``json.loads(data)``.

    Raises:
        JsonLimitError: hloubka > limit (před samotným parse).
        ValueError/TypeError: jinak přesně jako ``json.loads``.
    """
    if max_depth is None:
        max_depth = DEFAULT_MAX_DEPTH
    if max_depth < 1:
        raise ValueError(f"max_depth musí být ≥ 1, dostalo se {max_depth}")
    if isinstance(data, (bytes, bytearray)):
        data = bytes(data).decode("utf-8", errors="replace")
    # Rychlá cesta: celkový počet otevíracích závorek je horní hranice
    # maximální hloubky — pokud limit nedosahuje, lineární sken nemusíme
    # spouštět (typické malé dokumenty tak projdou jen dvěma C-level passy).
    if data.count("[") + data.count("{") <= max_depth:
        return json.loads(data)
    d = _max_depth(data)
    if d > max_depth:
        raise JsonLimitError(f"JSON hloubka {d} překročila limit {max_depth}")
    return json.loads(data)
