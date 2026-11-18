"""ETAPA B vlna 11 — cloud SNS rodina Twitter/X + Facebook.

P1-4 vlna E — datová sekce rejstříku; záznamy byte-přesně z monolitu.
"""

from __future__ import annotations

from ._types import ParserValidation

_PART = {
    # ── ETAPA B vlna 11 — cloud SNS rodina Twitter/X + Facebook ──────────────
    "twitter_posts": ParserValidation(
        parser_id="twitter_posts",
        version="",
        formats=(
            "Twitter/X Posts JSON (cloud export / warrant return — veřejné i soukromé příspěvky)",
        ),
        limitations=(
            "detekce name-based (twitter marker + post/tweet/status) — SNS pre-pass PŘED basename chainem",
            "příspěvek = sns_post; retweety/odpovědi nesou post_type; limit MAX_POSTS_PER_FILE=5000 záznamů",
        ),
        test_files=(
            "tests/test_w11_parsers.py",
            "tests/test_p11_quality_sns.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    "twitter_messages": ParserValidation(
        parser_id="twitter_messages",
        version="",
        formats=(
            "Twitter/X Direct Messages JSON (cloud export / warrant return — DM konverzace)",
        ),
        limitations=(
            "detekce name-based (twitter marker + message/direct) — SNS pre-pass PŘED basename chainem",
            "konverzační i plošný formát; limit MAX_MESSAGES_PER_FILE=20000 záznamů",
        ),
        test_files=(
            "tests/test_w11_parsers.py",
            "tests/test_p11_quality_sns.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    "twitter_users": ParserValidation(
        parser_id="twitter_users",
        version="",
        formats=(
            "Twitter/X Users JSON (cloud export / warrant return — účet + sociální graf)",
        ),
        limitations=(
            "detekce name-based (twitter marker + user/follower) — SNS pre-pass PŘED basename chainem",
            "uživatel = contact (mimetype sns:twitter); limit MAX_USERS_PER_FILE=20000 záznamů",
        ),
        test_files=(
            "tests/test_w11_parsers.py",
            "tests/test_p11_quality_sns.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
    "facebook_wr": ParserValidation(
        parser_id="facebook_wr",
        version="",
        formats=(
            "Facebook Warrant Return JSON (cloud export — Messenger/přátelé/timeline/profil)",
        ),
        limitations=(
            "detekce name-based (facebook marker) — SNS pre-pass PŘED basename chainem",
            "auto-detekce sekcí podle struktury payloadu; zprávy = chat_message, přátelé/profil = contact,",
            "timeline = sns_post",
        ),
        test_files=(
            "tests/test_w11_parsers.py",
            "tests/test_p11_quality_sns.py",
            "tests/test_p11_quality_locale.py",
        ),
    ),
}
