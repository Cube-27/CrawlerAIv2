"""Vendor resources the browser never blocks (acquisition spec, "HTTP and browser rungs", request blocking): site
data, which names vendors and so lives in the adapter package (C3). Two categories, each a vendor list, not a site
table:

- Bot defence: fraud-prevention, device-fingerprinting and bot-detection vendors, beside the challenge vendors of
  `adapters.challenges`. A page whose bot defence cannot run is refused or scored as a bot, so their scripts and the
  calls they make load whatever the ad and tracking lists say.
- Tag managers: a tag manager's container (its loader) can inject the page's structured data (JSON-LD, a product's
  data layer), so it loads; the analytics, ad and pixel endpoints it loads in turn are blocked as any other.

A host entry matches the host and its subdomains; a path entry, when given, must start the URL's path.
"""

from typing import Final
from urllib.parse import urlsplit

from crawlerai.adapters.challenges import challenge_resource

__all__ = ["BOT_DEFENCE", "TAG_MANAGERS", "kept_resource"]

# Fraud prevention, device fingerprinting, bot detection, CAPTCHA and waiting-room vendors.
BOT_DEFENCE: Final[tuple[tuple[str, str | None], ...]] = (
    ("forter.com", None),
    ("fpjs.io", None),
    ("fpcdn.io", None),
    ("fpnpmcdn.net", None),
    ("fingerprint.com", None),
    ("iovation.com", None),
    ("iesnare.com", None),
    ("online-metrix.net", None),  # ThreatMetrix
    ("sift.com", None),
    ("siftscience.com", None),
    ("signifyd.com", None),
    ("kount.net", None),
    ("kaptcha.com", None),
    ("riskified.com", None),
    ("nofraud.com", None),
    ("accertify.net", None),
    ("perimeterx.net", None),
    ("px-cdn.net", None),
    ("px-cloud.net", None),
    ("datadome.co", None),
    ("captcha-delivery.com", None),
    ("hcaptcha.com", None),
    ("arkoselabs.com", None),
    ("funcaptcha.com", None),
    ("queue-it.net", None),
    ("google.com", "/recaptcha/"),
    ("gstatic.com", "/recaptcha/"),
    ("recaptcha.net", None),
    ("challenges.cloudflare.com", None),
)
# Tag-manager containers (loaders) only, never the endpoints they send to.
TAG_MANAGERS: Final[tuple[tuple[str, str | None], ...]] = (
    ("googletagmanager.com", "/gtm.js"),
    ("tags.tiqcdn.com", "/utag/"),  # Tealium iQ
    ("assets.adobedtm.com", None),  # Adobe Launch / Experience Platform Tags
    ("cdn.segment.com", "/analytics.js/"),  # Segment's loader; its collection API is another host
    ("nexus.ensighten.com", None),
    ("cdn.tagcommander.com", None),
)


def _listed(host: str, path: str, entries: tuple[tuple[str, str | None], ...]) -> bool:
    return any(
        (host == listed or host.endswith("." + listed)) and (prefix is None or path.startswith(prefix))
        for listed, prefix in entries
    )


def kept_resource(url: str) -> bool:
    """Whether a request is for a resource the browser never blocks: an anti-bot challenge resource
    (`challenge_resource`), a bot-defence vendor's, or a tag manager's container (module docstring)."""
    if challenge_resource(url):
        return True
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return _listed(host, parts.path, BOT_DEFENCE) or _listed(host, parts.path, TAG_MANAGERS)
