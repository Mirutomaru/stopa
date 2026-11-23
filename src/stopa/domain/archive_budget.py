"""P2 security — sdílená budget logika pro neomezené zdroje import-mobile.

Jedna čistá (bez I/O) implementace použitá oběma větvemi ``cmd_import_mobile``:

  - ZIP/složková větev (.ufd/.zip/rozbalený export),
  - ADB logical dump (složka s .db/.sqlite/.vcf).

Limity přicházejí přes konstruktor; produkční defaults = module globály v
``cli/commands/forensics.py`` (``_MAX_ARCHIVE_MEMBER/_TOTAL/_MEMBERS``, čtené
v době volání → monkeypatchovatelné testy — P1 kontrakt).

Třída sama nevydává warnings — výstup rozhoduje volající (zprávy liší se
podle typu zdroje; audit stopa si zachovává kontext, co bylo omezeno).
"""

from __future__ import annotations


class ArchiveBudget:
    """Per-member / celková velikost / počet — budget neomezeného zdroje.

    Semantika (identická v obou větvích, navazující na P1 S2 ZIP bombu):

      - per-member limit → volající ticho přeskočí člena ještě před sběrem
        (``fits_member``, bez změny stavu),
      - celkový velikostní limit → přeskočí konkrétní členy, sběr pokračuje
        (``fits_total``, bez změny stavu; forenzní pokrytí co nejširší),
      - počtový limit → konec sběru (``exhausted``).

    Hranice jsou inkluzivní: ``size == limit`` je povolená (shoda s P1 větví,
    kde se porovnávalo přes striktní ``>``).
    """

    def __init__(self, *, max_member: int, max_total: int, max_members: int) -> None:
        if min(max_member, max_total, max_members) <= 0:
            raise ValueError("budget limity musí být kladné")
        self.max_member = int(max_member)
        self.max_total = int(max_total)
        self.max_members = int(max_members)
        self.accepted_count = 0
        self.total_bytes = 0

    @property
    def exhausted(self) -> bool:
        """Počtový limit dosažen → volající ukončí sběr."""
        return self.accepted_count >= self.max_members

    def fits_member(self, size: int) -> bool:
        """Pre-check jednoho člena (tichý skip); bez změny stavu."""
        return size <= self.max_member

    def fits_total(self, size: int) -> bool:
        """Celkový velikostní check proti rozpočtu; bez změny stavu."""
        return self.total_bytes + size <= self.max_total

    def accept(self, size: int) -> None:
        """Zaregistruje přijatého člena/souboru (aktualizuje počítadla)."""
        self.accepted_count += 1
        self.total_bytes += size
