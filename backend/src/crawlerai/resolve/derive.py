"""Derived values (resolution spec, INV-07): the only values core publishes without a candidate
stating them, each from a named function with its standard.

A derivation fills a field only when preference left it missing: a published field keeps its value, and a conflict
stays a conflict. Each value carries `derived_by`. Adding a derivation is a C2/C13 review item.

The page-URL field's candidates are first held to the page: when its canonical link and its final URL name one URL, a
candidate naming another document is not the page's URL (`OTHER_DOCUMENT`), and preference decides among the rest.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final
from urllib.parse import urlsplit

from pydantic import JsonValue

from crawlerai.collect.base import Candidate
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.normalize.url import RELATIVE_WITHOUT_BASE
from crawlerai.resolve.preference import Chosen, Preference, Rejection, Resolver, Unpublished
from crawlerai.resolve.types import Derivation
from crawlerai.schemas.paths import parse_paths
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

# Why a candidate of the page-URL field does not publish: it names another document than the page (`_held_to_page`).
OTHER_DOCUMENT: Final = "other_document"


@dataclass(frozen=True, slots=True)
class Derived:
    """A value no candidate stated as it publishes; `source` is the candidate it was derived from, if any; `rejected`,
    the field's candidates that did not publish, with their reasons."""

    value: JsonValue
    derived_by: Derivation
    source: Candidate | None
    rejected: tuple[Rejection, ...] = ()


def is_page_url_field(schema: SchemaDef, spec: FieldSpec, primary: frozenset[str]) -> bool:
    """Whether the field is the URL of the page's entity: on a detail page, a url field whose path is `T.url` for a
    primary type T (schema.org Thing.url, "URL of the item"; the primary types of identity-and-intent's target
    selection) in every alternative. A field with any other alternative (an apply link,
    `JobPosting.potentialAction.target`) names a link the page states, which the page's own URL never stands in for
    (resolution spec, "Derived values")."""
    if schema.page_kind != "detail" or spec.type is not FieldType.URL or spec.schema_org is None:
        return False
    paths = parse_paths(spec.schema_org)
    return all(path.root in primary and path.steps == ("url",) and not path.joined for path in paths)


def fill(
    spec: FieldSpec,
    preference: Preference,
    candidates: Sequence[Candidate],
    resolver: Resolver,
    ctx: Context,
    *,
    canonical_url: str | None,
    page_url_field: bool,
) -> Preference | Derived:
    """The field's derived value when preference left it missing (INV-07), else `preference`, the page-URL field's
    held to the page first (`_held_to_page`).

    A value from the field's own candidate comes first; the page URL only when the field is the page's
    (`is_page_url_field`): the canonical link, then the final URL.
    """
    if page_url_field:
        preference = _held_to_page(spec, preference, candidates, resolver, _own_url(spec, canonical_url, ctx))
    if not (isinstance(preference, Unpublished) and preference.status == "missing"):
        return preference
    derived = absolutize(spec, candidates, resolver, ctx)
    if derived is None and page_url_field:
        derived = canonical_link(spec, canonical_url, ctx) or final_url(spec, ctx)
    return preference if derived is None else replace(derived, rejected=preference.rejected)


def _own_url(spec: FieldSpec, canonical_url: str | None, ctx: Context) -> str | None:
    """The page's own URL when its canonical link (RFC 6596) and its final URL (RFC 9110 §15.4) name one, else None:
    a canonical link to another page (a parent, the home page) says nothing about which document this one is."""
    found = [normalize(url, spec, ctx) for url in (canonical_url, ctx.page_url) if url is not None]
    values = {r.value for r in found if isinstance(r, Ok) and isinstance(r.value, str)}
    return values.pop() if len(found) == 2 and len(values) == 1 else None


def _held_to_page(
    spec: FieldSpec, preference: Preference, candidates: Sequence[Candidate], resolver: Resolver, own: str | None
) -> Preference:
    """`preference` with the kept candidates naming another document than the page's own URL `own` rejected
    `OTHER_DOCUMENT`, preference deciding among the rest: a structured `url` built from another id than the page's
    (a SKU) names another document, while the page states its own by both its canonical link and its final URL."""
    others = [c for c in preference.kept if own is not None and _another_document(c, own)]
    if not others:
        return preference
    rest = [c for c in candidates if not any(c is other for other in others)]
    held = resolver.prefer_field(spec, rest)
    return replace(held, rejected=(*held.rejected, *((c, OTHER_DOCUMENT) for c in others)))


def _another_document(candidate: Candidate, own: str) -> bool:
    """Whether the candidate's URL names another document than `own`: another host, port or path (RFC 3986 §3.2, §3.3),
    a trailing slash aside (§6.2.4). A query or a fragment the page's URL does not carry may select a view or a part
    of the same document (a variant, an anchor), so it alone names no other one."""
    value = candidate.normalized.value if isinstance(candidate.normalized, Ok) else None
    if not isinstance(value, str):
        return False
    a, b = urlsplit(value), urlsplit(own)
    return (a.hostname, a.port, a.path.rstrip("/")) != (b.hostname, b.port, b.path.rstrip("/"))


def absolutize(spec: FieldSpec, candidates: Sequence[Candidate], resolver: Resolver, ctx: Context) -> Derived | None:
    """RFC 3986 §5.2 (reference resolution) against the HTML document base URL: a relative url or image_url reference
    a collector could not resolve, resolved and then put through preference like any candidate."""
    if spec.type not in (FieldType.URL, FieldType.IMAGE_URL) or ctx.base_url is None:
        return None
    pairs = [
        (candidate.model_copy(update={"normalized": normalize(candidate.raw, spec, ctx)}), candidate)
        for candidate in candidates
        if candidate.normalized == RELATIVE_WITHOUT_BASE
    ]
    preference = resolver.prefer_field(spec, [resolved for resolved, _ in pairs])
    if not isinstance(preference, Chosen) or not isinstance(preference.candidate.normalized, Ok):
        return None
    source = next(original for resolved, original in pairs if resolved is preference.candidate)
    return Derived(preference.candidate.normalized.value, "absolutize", source)


def canonical_link(spec: FieldSpec, canonical_url: str | None, ctx: Context) -> Derived | None:
    """RFC 6596: the canonical link relation names the page's preferred URL. `canonical_url` is the `<link
    rel=canonical>` href resolved against the document base URL."""
    return _page_url(spec, canonical_url, ctx, "canonical_link")


def final_url(spec: FieldSpec, ctx: Context) -> Derived | None:
    """RFC 9110 §15.4: the URL the request ended at after redirects, which is the page's own: the context's page URL."""
    return _page_url(spec, ctx.page_url, ctx, "final_url")


def _page_url(spec: FieldSpec, url: str | None, ctx: Context, derived_by: Derivation) -> Derived | None:
    if url is None:
        return None
    result = normalize(url, spec, ctx)
    return Derived(result.value, derived_by, None) if isinstance(result, Ok) else None
