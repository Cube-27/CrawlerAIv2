"""Anti-bot challenge signatures (D-1326): site data, which names vendors and so lives in the adapter package (C3).

`acquire.challenge` labels a refused response with the vendor whose signature it shows: a response header only that
vendor sends, a cookie only it sets, or the path of its challenge resource. The label is recorded on the attempt and
counted; it never changes the block class or the remembered fetch method (INV-24). `portable` says whether the
cookies a browser earns from that vendor's challenge are documented to serve a later plain HTTP client with the same
user agent and address, which a site session's cookie handoff reads.
"""

from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["SIGNATURES", "ChallengeSignature", "vendor_of"]


@dataclass(frozen=True)
class ChallengeSignature:
    vendor: str
    header_names: frozenset[str] = frozenset()  # lowercase response header names
    cookie_prefixes: tuple[str, ...] = ()  # cookie names, or the fixed start of names the vendor numbers
    script_paths: tuple[str, ...] = ()  # in a challenge document's markup
    portable: bool = True


SIGNATURES: tuple[ChallengeSignature, ...] = (
    ChallengeSignature(
        "cloudflare",
        header_names=frozenset({"cf-mitigated", "cf-chl-bypass"}),
        cookie_prefixes=("__cf_bm", "cf_clearance", "__cf_chl_"),
        script_paths=("/cdn-cgi/challenge-platform/",),
    ),
    ChallengeSignature(
        "datadome",
        header_names=frozenset({"x-datadome", "x-datadome-cid", "x-dd-b"}),
        cookie_prefixes=("datadome",),
        script_paths=("captcha-delivery.com", "js.datadome.co"),
    ),
    ChallengeSignature(
        "akamai",
        cookie_prefixes=("_abck", "bm_sz", "ak_bmsc", "bm_sv"),
        script_paths=("/akam/",),
    ),
    ChallengeSignature(
        "imperva",
        header_names=frozenset({"x-iinfo"}),
        cookie_prefixes=("incap_ses_", "visid_incap_", "reese84", "nlbi_"),
        script_paths=("/_Incapsula_Resource",),
    ),
    ChallengeSignature(
        "human",
        cookie_prefixes=("_px3", "_pxhd", "_pxvid", "_px2", "_pxde"),
        script_paths=("captcha.px-cdn.net", "client.perimeterx.net"),
    ),
    ChallengeSignature(
        # Its tokens are made per request by the page's script and sent as headers, so cookies alone serve nothing.
        "kasada",
        header_names=frozenset({"x-kpsdk-ct", "x-kpsdk-cd", "x-kpsdk-c"}),
        script_paths=("/ips.js?",),
        portable=False,
    ),
    ChallengeSignature(
        "aws_waf",
        header_names=frozenset({"x-amzn-waf-action"}),
        cookie_prefixes=("aws-waf-token",),
        script_paths=("token.awswaf.com", "captcha.awswaf.com"),
    ),
)


def vendor_of(header_names: Iterable[str], cookie_names: Iterable[str], body: bytes) -> ChallengeSignature | None:
    """The first signature the response shows, if any: header names compared case-insensitively (RFC 9110 §5.1),
    cookie names exactly (RFC 6265 §4.1.1)."""
    headers = {name.lower() for name in header_names}
    cookies = tuple(cookie_names)
    for signature in SIGNATURES:
        if not headers.isdisjoint(signature.header_names):
            return signature
        if any(name.startswith(signature.cookie_prefixes) for name in cookies if signature.cookie_prefixes):
            return signature
        if any(path.encode() in body for path in signature.script_paths):
            return signature
    return None
