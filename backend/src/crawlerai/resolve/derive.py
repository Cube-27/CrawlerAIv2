"""Derived values (SPEC-05 §4.8, ARCHITECTURE §9, C7, INV-07): the only values core publishes without a candidate
stating them, each from a named function with its standard.

A derivation fills a field only when preference left it missing: a published field keeps its value, and a conflict
stays a conflict. Each value carries `derived_by`. Adding a derivation is a C2/C13 review item.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import JsonValue

from crawlerai.collect.base import Candidate
from crawlerai.collect.schema_org_map import parse_paths
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.normalize.url import RELATIVE_WITHOUT_BASE
from crawlerai.resolve.preference import Chosen, Preference, Resolver, Unpublished
from crawlerai.resolve.types import Derivation
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef


@dataclass(frozen=True, slots=True)
class Derived:
    """A value no candidate stated as it publishes; `source` is the candidate it was derived from, if any."""

    value: JsonValue
    derived_by: Derivation
    source: Candidate | None


def is_page_url_field(schema: SchemaDef, spec: FieldSpec, primary: frozenset[str]) -> bool:
    """Whether the field is the URL of the page's entity: on a detail page, a url field whose path is `T.url` for a
    primary type T (schema.org Thing.url, "URL of the item"; intent's primary types, §4.6), in every alternative of its
    last rank: the page's URL stands in only where no alternative reaches a value, after every rank (D-1493)."""
    if schema.page_kind != "detail" or spec.type is not FieldType.URL or spec.schema_org is None:
        return False
    paths = parse_paths(spec.schema_org)
    last = paths[-1].rank
    return all(
        path.root in primary and path.steps == ("url",) and path.joined is None for path in paths if path.rank == last
    )


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
    """The field's derived value when preference left it missing (INV-07), else `preference` unchanged.

    A value from the field's own candidate comes first; the page URL only when the field is the page's
    (`is_page_url_field`): the canonical link, then the final URL.
    """
    if not (isinstance(preference, Unpublished) and preference.status == "missing"):
        return preference
    derived = absolutize(spec, candidates, resolver, ctx)
    if derived is None and page_url_field:
        derived = canonical_link(spec, canonical_url, ctx) or final_url(spec, ctx)
    return preference if derived is None else derived


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
