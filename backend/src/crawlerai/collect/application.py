"""Whether a job page holds its own application (resolution spec, "Derived values"; owner decision 2026-10-22): where a
candidate applies on the page itself, the page is the posting's apply link.

The page says so in its markup only: an HTML form that asks for an applicant's documents and contact
(`_application_form`), or a platform's documented embed of its application form (`adapters.base.ApplicationEmbed`),
whose names live in the adapter package (C3). Nothing is read from words on the page.
"""

from typing import Final
from urllib.parse import parse_qs, urljoin, urlsplit

from selectolax.lexbor import LexborNode

from crawlerai.adapters.base import ApplicationEmbed
from crawlerai.adapters.greenhouse import APPLICATION_EMBED
from crawlerai.content.page import ParsedPage

_EMBEDS: Final[tuple[ApplicationEmbed, ...]] = (APPLICATION_EMBED,)
# HTML Standard §4.10.18.7.1, autofill field names of the person's own name and contact details.
_CONTACT_AUTOFILL: Final = frozenset({"name", "given-name", "family-name", "email", "tel"})
# HTML Standard §4.10.5.1: the input states that take an e-mail address or a telephone number.
_CONTACT_TYPES: Final = frozenset({"email", "tel"})
_CONTROLS: Final = "input, select, textarea"


def holds_application(page: ParsedPage, final_url: str) -> bool:
    """Whether the HTML page fetched at `final_url` holds a posting's application form, by its own markup or by a
    platform's documented embed; a JSON body holds no HTML elements (`ParsedPage.json_body`)."""
    if page.json_body:
        return False
    return any(_application_form(page, form) for form in page.tree.css("form")) or any(
        _embeds(page, final_url, embed) for embed in _EMBEDS
    )


def _application_form(page: ParsedPage, form: LexborNode) -> bool:
    """A form (HTML Standard §4.10.3) one of whose controls uploads a file (§4.10.5.1.18, the File Upload state: the
    applicant's documents) and another asks for the person's name or contact (`_CONTACT_AUTOFILL`, `_CONTACT_TYPES`).
    A form's controls are its descendants and the controls naming it by their `form` attribute (§4.10.17.3, form
    owner)."""
    form_id = form.attributes.get("id")
    # A descendant naming another form by its `form` attribute is that form's.
    controls = [c for c in form.css(_CONTROLS) if c.attributes.get("form") in (None, form_id)]
    if form_id:
        controls += [
            c for c in page.tree.css(_CONTROLS) if c.attributes.get("form") == form_id
        ]  # a descendant twice is one control
    # The `type` attribute is an enumerated attribute (ASCII case-insensitive, §2.3.3); `autocomplete`, a list of
    # tokens whose last names the field (§4.10.18.7.1).
    types = {(c.attributes.get("type") or "").strip().lower() for c in controls if c.tag == "input"}
    autofill = {((c.attributes.get("autocomplete") or "").lower().split() or [""])[-1] for c in controls}
    return "file" in types and bool(types & _CONTACT_TYPES or autofill & _CONTACT_AUTOFILL)


def _embeds(page: ParsedPage, final_url: str, embed: ApplicationEmbed) -> bool:
    """Whether the page shows `embed`'s application form: its URL's query names one posting by the embed's parameter
    (RFC 3986 §3.4), and the page holds the embed's container element and loads its loader script for one board
    (HTML Standard §4.12.1, `script src`, resolved against the page URL)."""
    posting = parse_qs(urlsplit(final_url).query).get(embed.posting_param, [])
    if len(posting) != 1 or not embed.posting_id.fullmatch(posting[0]):
        return False
    if page.tree.css_first(f'[id="{embed.container}"]') is None:
        return False
    for script in page.tree.css("script[src]"):
        try:
            loader = urlsplit(urljoin(final_url, (script.attributes.get("src") or "").strip()))
        except ValueError:  # RFC 3986 §3.2.2: an authority no URL parser reads names no script
            continue
        board = parse_qs(loader.query).get(embed.loader_param, [])
        if loader.hostname in embed.loader_hosts and loader.path == embed.loader_path and len(board) == 1:
            return True
    return False
