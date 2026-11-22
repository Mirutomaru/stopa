"""Web routes — i18n katalogy (P4-8: /api/i18n/{lang} pro legacy UI).

Legacy static UI (``static/``, ``?ui=legacy``) si může stáhnout celý překladový
katalog a lokalizovat vlastní labely bez dalšího endpointu. SPA má vlastní
i18n slovník ve frontendu — tato routa je smluvní povrch pro legacy vrstvu
+ testovací plochu (zlatý Web surface).
"""

from fastapi import HTTPException

from stopa.i18n import SUPPORTED_LANGS, catalog


def register(app, ctx) -> None:  # ctx = konzistence signatury s ostatními routery
    """Registruje i18n routy; ``ctx`` = sdílený stav create_app()."""

    @app.get("/api/i18n/{lang}")
    def i18n_catalog(lang: str) -> dict:
        """Celý katalog pro požadovaný jazyk (cs|en). Neznámý → 404."""
        try:
            return {"lang": lang, "messages": catalog(lang)}
        except ValueError as exc:
            raise HTTPException(
                404, f"neznámý jazyk {lang!r} (povoleno: {', '.join(SUPPORTED_LANGS)})"
            ) from exc
