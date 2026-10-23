"""The page's languages and locales, and the ISO 3166-1 country codes: the one
reading every normalizer that depends on a language (vocab, date, numbers, money, range) shares.

Precedence: the page's own declarations count together: `<html lang>` (HTML Standard, the `lang` attribute),
`og:locale` (Open Graph protocol, `language_TERRITORY`), JSON-LD `inLanguage` (schema.org), Content-Language
(RFC 9110 §8.5 and its HTML pragma) and the `hreflang` of the alternate links to the page itself (HTML Living Standard
§4.6.7.1, `content/context.py`). The request's locale is the caller's hint, read only when the page declares no
language and only by a reader that takes it (`request=True`). A tag counts only when its primary language subtag is
one (RFC 5646 §2.2.1: two or three letters, not `und`), so `x-default` or a private-use tag declares nothing. The
locale only guides how a value is read; it never changes a value the page states.
"""

from functools import cache

from babel import Locale

from crawlerai.normalize.base import Context

# ISO 3166-1 "exceptional reservations" (the standard's list of codes reserved at a body's request, which the
# standard does not assign to a country): CLDR names regions by some of them, and some are ccTLDs (RFC 1591: `.eu`).
_EXCEPTIONALLY_RESERVED = frozenset({"AC", "CP", "CQ", "DG", "EA", "EU", "EZ", "FX", "IC", "SU", "TA", "UK", "UN"})


def page_locales(ctx: Context, *, request: bool) -> tuple[str, ...]:
    """The language tags the page declares for itself, as written (BCP 47, or `ll_TT` from Open Graph), each once in
    the order the module docstring lists them; else, with `request`, the request's locale; else none."""
    declared = (ctx.html_lang, ctx.og_locale, *ctx.in_language, *ctx.content_language, *ctx.hreflang)
    own = tuple(dict.fromkeys(tag for tag in map(_tag, declared) if tag))
    if own or not request:
        return own
    return tuple(filter(None, (_tag(ctx.request_locale),)))


def page_languages(ctx: Context, *, request: bool) -> frozenset[str]:
    """The primary language subtags (lowercase, RFC 5646 §2.2.1) of `page_locales`."""
    return frozenset(primary_language(tag) for tag in page_locales(ctx, request=request))


def _tag(written: str | None) -> str | None:
    tag = (written or "").strip()
    language = primary_language(tag)
    return tag if 2 <= len(language) <= 3 and language.isascii() and language.isalpha() and language != "und" else None


def primary_language(tag: str) -> str:
    """The primary language subtag of a BCP 47 tag or an `ll_TT` Open Graph locale, lowercase (RFC 5646 §2.2.1)."""
    return tag.replace("_", "-").split("-")[0].lower()


@cache
def iso_3166_alpha2(*, reserved: bool = False) -> frozenset[str]:
    """The ISO 3166-1 alpha-2 codes CLDR names regions by (via Babel), less the ranges ISO 3166-1 leaves to users
    (AA, QM to QZ, XA to XZ, ZZ) and its exceptional reservations (EU, EZ, UN, ...), which name no country. With
    `reserved`, the exceptional reservations CLDR names a region by count too: a ccTLD may be one (RFC 1591, `.eu`)."""
    return frozenset(
        code
        for code in Locale("en").territories
        if isinstance(code, str)
        and len(code) == 2
        and code.isascii()
        and code.isalpha()
        and (reserved or code not in _EXCEPTIONALLY_RESERVED)
        and not (code in {"AA", "ZZ"} or code[0] == "X" or ("QM" <= code <= "QZ"))
    )
