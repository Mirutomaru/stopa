"""STOPA — F4.5 Case sharing & collaboration: čistá doménová logika.

Bez I/O — plně offline testovatelná (pattern jako ``rbac.py`` / ``review.py``):

- :func:`parse_mentions` — @mentions v těle komentáře → seznam username
  (deduplikace, zachování pořadí prvního výskytu).
- :func:`case_access_level` — read/write úroveň sdílení případu na pravidlech F4.4:
  efektivní role examiner/admin → ``"write"``, analyst → ``"read"``, bez přístupu
  → ``None`` (fail-closed).
- :func:`validate_comment_body` — strip + omezení délky komentáře.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from stopa.domain.multitenant import access_for_case

#: Maximální délka těla komentáře (doménová validace + DB CHECK jako pojistka).
MAX_COMMENT_LEN = 4000

#: @mention: `@` musí být předchozeno ne-písmenem/ne-cifrou (e-mail ``a@b.c``
#: tedy mention NEVYTVÁRÍ); token = písmeno/cifra + 1–31 znaků [A-Za-z0-9._\-]
#: končící písmenem/cifrou (koncová tečka/zpomínka od interpunkce nepatří k jménu).
_MENTION_RE = re.compile(r"(?<![A-Za-z0-9])@([A-Za-z0-9](?:[A-Za-z0-9._\-]*[A-Za-z0-9])?)")


def parse_mentions(body: str) -> list[str]:
    """Vytáhne @mentions z textu; deduplikovano, pořadí prvního výskytu.

    >>> parse_mentions("videl to @bob a znovu @bob, viz x@y.z")
    ['bob']
    """
    if not body:
        return []
    seen: list[str] = []
    for m in _MENTION_RE.finditer(body):
        tok = m.group(1)
        if len(tok) <= 32 and tok not in seen:
            seen.append(tok)
    return seen


def case_access_level(global_role: str | None, case_grants: Sequence[str]) -> str | None:
    """Read/write úroveň přístupu uživatele k případu (fail-closed).

    Vrací ``"write"`` (efektivní role examiner/admin), ``"read"`` (analyst)
    nebo ``None`` (žádný přístup). Pravidla efektivní role z F4.4 —
    :func:`stopa.domain.multitenant.access_for_case` (per-case grant vyhrává,
    org-level admin = fallback bez členství).
    """
    has_access, role = access_for_case(global_role, case_grants)
    if not has_access or role is None:
        return None
    return "write" if role in ("examiner", "admin") else "read"


def validate_comment_body(body: str | None) -> str:
    """Validuje tělo komentáře — strip; prázdné/příliš dlouhé → :class:`ValueError`."""
    text = (body or "").strip()
    if not text:
        raise ValueError("komentář je prázdný")
    if len(text) > MAX_COMMENT_LEN:
        raise ValueError(f"komentář příliš dlouhý ({len(text)} > {MAX_COMMENT_LEN} znaků)")
    return text
