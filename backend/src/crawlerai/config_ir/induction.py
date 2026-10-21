"""Induction (learning-configs spec): selectors generalized from the locators of the values the engine
published on the learning sample, without an LLM. What the engine published is the learning oracle: its own values and
role C's grounded ones (a verbatim span of the cleaned text, INV-12, or a link's or image's element).

For each field, every sample page's published locator proposes candidate steps:
- `jsonld:<block>:<path>`: a `jsonld` step relative to each schema.org node the value is nested in (nearest first),
  typed by the node's types, with array indices stripped (`[*]`), then with them kept;
- `js_state:`, `attr:`, `rsc:` and `xhr:` paths: a `jsonpath` step over the page's documents of that source (an RSC
  path reads every row of the Flight stream), indices stripped, then kept;
- `meta:<name>`: the `content` of the `meta` element with that `property`, then that `name`;
- `microdata:<xpath>`, `dom:<xpath>` and `config:` XPaths that select one element, and `text:` spans (the innermost
  element holding the span): for each anchor on the element and its ancestors (nearest first), the path from the
  anchored ancestor down to the element without positional predicates, read as `normalize-space(...)`, then as each of
  the element's attributes (a URL field's resolved against the base URL first);
- `adapter:`/`api:` with the same mapping name on every page: the field comes from that mapping (`origin=adapter`);
- anything else (`derived:`): no induction, the field goes to synthesis.

A page's locators may differ in scheme from another's (a value role C found on one page, the DOM collector on another):
a candidate is kept only if every sample page proposes it and, on every page, it selects exactly one node whose value
the engine executor normalizes to the published value (`equal`). Of those, the one most pages propose, then the first,
wins; a field without one goes to synthesis (§4.6). Site strings exist only in the steps produced, which are IR data
(C3, INV-03). A listing's rows are induced from the item layer's blocks (`listing_induction`).

A locate run (learning-configs spec, "Locate run" step 3) induces a value in every source document of a page that
holds it, whatever locator its candidate was published with (`source_steps`): a `jsonpath` step in each JSON document
(JSON-LD, embedded state, JSON attributes, RSC rows, captured calls) where a member normalizes to the value, and the
anchored paths of each element whose text or attribute does.
"""

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from lxml import etree
from lxml.html import HtmlElement
from pydantic import JsonValue, ValidationError

from crawlerai.collect.induce import induced
from crawlerai.collect.json_doc import ROOT, scalars, segments
from crawlerai.collect.jsonld import JsonLdCollector
from crawlerai.collect.locator import InvalidLocator, Locator, parse_locator
from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.config_ir.executor import documents, field_candidate
from crawlerai.config_ir.model import (
    FieldSteps,
    JsonLdStep,
    JsonPathStep,
    JsonSource,
    Step,
    XPathStep,
)
from crawlerai.content.dom import tokens
from crawlerai.content.page import ParsedPage
from crawlerai.content.text import name_test
from crawlerai.db.models import FieldStatus
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import equal, normalize
from crawlerai.schemas.types import NEXT_PAGE_FIELD, FieldSpec, SchemaDef

# A class token that reads as a word or kebab-case words is a stable anchor; tokens that build tools hash carry
# uppercase letters, underscores or long digit runs. A structural property of the token (learning-configs spec, D-0031),
# not a list of names.
_STABLE_CLASS = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")
_DIGIT_RUN = re.compile(r"\d{3}", re.ASCII)
# RFC 9535 §2.3.3: an index segment.
_INDEX = re.compile(r"\[\d+\]", re.ASCII)
_STATUS: FieldStatus = "uncorroborated"  # until validation (§4.7) records corroboration
# The schemes whose values come from an adapter's or API recipe's mapping, which the config reuses.
MAPPED: Final = frozenset({"adapter", "api"})
# The schemes of values read from a JSON document or a meta element: one step reads a list as well as a value.
STRUCTURED: Final = frozenset({"jsonld", "meta", "js_state", "attr", "rsc", "xhr"})
# The schemes of values read from one element: structured markup, the DOM, a config's step, and role C's grounded
# claims (a verbatim span of the cleaned text, INV-12, or a link's or image's element).
ELEMENTS: Final = frozenset({"microdata", "dom", "config", "text"})
# The JSON documents a located value is searched in, and how many steps each source proposes at most.
LOCATED_SOURCES: Final[tuple[JsonSource, ...]] = ("jsonld", "js_state", "attr", "rsc", "xhr")
_STEPS_PER_SOURCE: Final = 3
# An element whose text is longer holds more than one value; its descendants are searched instead.
_MAX_ELEMENT_TEXT: Final = 200


@dataclass(frozen=True, slots=True)
class Published:
    """A field's published value on a sample page and the locator of the candidate it was chosen from."""

    value: JsonValue
    locator: str


@dataclass(frozen=True, slots=True)
class SamplePage:
    """A learning sample page: the page entity's published values and, on a listing, each row's, in document order.
    Induction reads the page's; synthesis (§4.6) reads both."""

    page: ParsedPage
    ctx: Context
    published: Mapping[str, Published]
    rows: Sequence[Mapping[str, Published]] = ()


@dataclass(frozen=True, slots=True)
class Induction:
    """`fields`: induced steps by field. `mapped`: fields every sample page took from one adapter or API recipe
    mapping (`adapter:<name>` / `api:<name>`). `to_synthesize`: the other fields, with the reason they were left."""

    fields: dict[str, FieldSteps] = field(default_factory=dict)
    mapped: dict[str, str] = field(default_factory=dict)
    to_synthesize: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Candidate:
    """A step, and for an XPath step the node path that must select exactly one node."""

    step: Step
    nodes: str | None = None

    @property
    def key(self) -> str:
        return self.step.model_dump_json()


def induce(schema: SchemaDef, sample: Sequence[SamplePage], vocabulary: Vocabulary) -> Induction:
    """Steps for the page-level fields whose published locators generalize over `sample`: every field of a detail
    schema, a listing's page-scoped fields and its next page's URL. A listing's rows are `listing_induction`'s."""
    names = [name for name in schema.fields if page_level(schema, name)]
    if not sample:
        return Induction(to_synthesize=dict.fromkeys(names, "no_sample"))
    result = Induction()
    for name in names:
        _induce_field(_Field(name, schema.fields[name], schema, sample, vocabulary), result)
    return result


def page_level(schema: SchemaDef, name: str) -> bool:
    """Whether a field runs on the whole page: any field of a detail schema; a listing's page-scoped fields and its next
    page's URL, which the listing's `next` step locates (IR §12.1)."""
    return schema.page_kind == "detail" or name == NEXT_PAGE_FIELD or schema.fields[name].scope == "page"


@dataclass(frozen=True, slots=True)
class _Field:
    name: str
    spec: FieldSpec
    schema: SchemaDef
    sample: Sequence[SamplePage]
    vocabulary: Vocabulary


def _induce_field(f: _Field, result: Induction) -> None:
    locators = _locators(f)
    if locators is None:
        result.to_synthesize[f.name] = "not_published_on_every_page"
        return
    schemes = {locator.scheme for locator in locators}
    if schemes & MAPPED:
        if len(schemes) == 1:
            _mapped(f.name, schemes.pop(), locators, result)
        else:
            result.to_synthesize[f.name] = "no_common_pattern"
        return
    if unread := sorted(scheme for scheme in schemes if not _reads(scheme, f.spec)):
        result.to_synthesize[f.name] = f"not_induced:{unread[0]}"
        return
    step = _induced_step(
        [_proposals(locator, sample, f) for locator, sample in zip(locators, f.sample, strict=True)], f
    )
    if step is None:
        result.to_synthesize[f.name] = "no_verified_selector"
    else:
        result.fields[f.name] = FieldSteps(steps=[step], status=_STATUS)


def _reads(scheme: str, spec: FieldSpec) -> bool:
    """Whether induction proposes steps for a value located under `scheme`: an element's (one per value, so not for a
    list), a JSON document's, or a meta element's."""
    return scheme in STRUCTURED or (scheme in ELEMENTS and spec.item is None)


def _induced_step(proposals: Sequence[list[_Candidate]], f: _Field) -> Step | None:
    """The first step every sample page proposes that selects the published value on each (`collect.induce`)."""
    by_key: dict[str, _Candidate] = {}
    for page in proposals:
        for c in page:
            by_key.setdefault(c.key, c)
    key = induced([[c.key for c in page] for page in proposals], len(proposals), lambda k: _verified(by_key[k], f))
    return None if key is None else by_key[key].step


def _locators(f: _Field) -> list[Locator] | None:
    """The published locator on every sample page, or `None` when a page did not publish the field."""
    found: list[Locator] = []
    for sample in f.sample:
        published = sample.published.get(f.name)
        if published is None:
            return None
        try:
            found.append(parse_locator(published.locator))
        except InvalidLocator:
            return None
    return found


def _mapped(name: str, scheme: str, locators: Sequence[Locator], result: Induction) -> None:
    # learning-configs spec: values an adapter or API recipe published come from its mapping, which the config reuses.
    mappings = {locator.parts[0] for locator in locators}
    if len(mappings) == 1:
        result.mapped[name] = f"{scheme}:{mappings.pop()}"
    else:
        result.to_synthesize[name] = "no_common_pattern"


def _proposals(locator: Locator, sample: SamplePage, f: _Field) -> list[_Candidate]:
    """The page's candidate steps for the locator of its published value, in order of preference."""
    match locator.scheme:
        case "jsonld":
            return list(_jsonld_candidates(sample.page, f.vocabulary, locator))
        case "meta":
            return list(_meta_candidates(locator.parts[0]))
        case "js_state" | "attr" | "rsc" | "xhr":
            return list(_jsonpath_candidates(locator))
        case "text":
            element = span_element(sample.page, int(locator.parts[0]), int(locator.parts[1]))
            return [] if element is None else list(xpath_candidates(element, f.spec))
        case _:
            return list(_xpath_candidates(sample.page.lxml_tree, locator.parts[-1], f.spec))


def _verified(candidate: _Candidate, f: _Field) -> bool:
    return all(_selects_published(candidate, sample, f) for sample in f.sample)


def _selects_published(candidate: _Candidate, sample: SamplePage, f: _Field) -> bool:
    if candidate.nodes is not None and len(_select(sample.page.lxml_tree, candidate.nodes)) != 1:
        return False
    found = field_candidate(sample.page, f.schema, sample.ctx, f.vocabulary, f.name, [candidate.step])
    if found is None or not isinstance(found.normalized, Ok):
        return False
    return equal(found.normalized.value, sample.published[f.name].value, f.spec)


def _select(tree: HtmlElement, xpath: str) -> list[object]:
    """The node-set `xpath` selects; empty for an XPath error or a result that is not a node-set."""
    try:
        found = tree.xpath(xpath)
    except etree.XPathError:
        return []
    return found if isinstance(found, list) else []


# --- jsonld ---------------------------------------------------------------------------------------------------------


def _jsonld_candidates(page: ParsedPage, vocabulary: Vocabulary, locator: Locator) -> Iterator[_Candidate]:
    """For each schema.org node the value is nested in, nearest first, and each of its types: the path from the node
    to the value with array indices stripped, then as written; then the same for the object holding the value, which a
    composite field reads whole (`Offer.price+priceCurrency` is the offer, not its `price` alone)."""
    block, path = locator.parts
    try:
        written = segments(path)
    except ValueError:  # a member name the engine's JSONPath reader does not take
        return
    typed = {node: types for node, types, _ in JsonLdCollector(vocabulary).nodes(page)}
    for parts in _and_holder(written):
        for at in range(len(parts), -1, -1):
            types = typed.get(f"jsonld:{block}:{ROOT}" + "".join(parts[:at]), ())
            yield from _typed_candidates(types, parts[at:])


def _typed_candidates(types: Sequence[str], rest: Sequence[str]) -> Iterator[_Candidate]:
    """A `jsonld` step for each of the node's types, reading `rest` from it."""
    for type_ in types:
        for query in _queries(rest):
            if (step := _jsonld_step(query, type_)) is not None:
                yield _Candidate(step)


def _and_holder(parts: list[str]) -> Iterator[list[str]]:
    """A JSON value's path, then its holder's: the object it is a member of (RFC 9535 §2.5.1 name segments)."""
    yield parts
    if parts and not _INDEX.fullmatch(parts[-1]):
        yield parts[:-1]


def _queries(parts: Sequence[str]) -> Iterator[str]:
    """The path with array indices stripped (`[*]`), then as written, each once."""
    stripped = ROOT + "".join("[*]" if _INDEX.fullmatch(s) else s for s in parts)
    yield from dict.fromkeys((stripped, ROOT + "".join(parts)))


def _jsonld_step(query: str, type_: str) -> JsonLdStep | None:
    try:
        return JsonLdStep(jsonld=query, when_type=type_)
    except ValidationError:  # a type name outside schema.org's naming conventions
        return None


# --- meta, embedded state, captured calls ---------------------------------------------------------------------------


def _meta_candidates(name: str) -> Iterator[_Candidate]:
    """HTML Standard §4.2.5: a `meta` element names its value by `name`, and RDFa (as OpenGraph writes it) by
    `property`; the value is its `content`."""
    if (literal := _literal(name)) is None:
        return
    for attribute in ("property", "name"):
        nodes = f"//meta[@{attribute}={literal}]"
        if (step := _xpath_step(f"{nodes}/@content")) is not None:
            yield _Candidate(step, nodes)


def _jsonpath_candidates(locator: Locator) -> Iterator[_Candidate]:
    """A `jsonpath` step over the page's documents of the locator's source (embedded state, JSON attributes, captured
    calls): the path with array indices stripped (`[*]`), then as written; then the same for the object holding the
    value."""
    source: JsonSource = locator.scheme if locator.scheme in ("js_state", "attr", "rsc") else "xhr"
    try:
        written = segments(locator.parts[-1])
    except ValueError:  # a member name the engine's JSONPath reader does not take
        return
    for parts in _and_holder(written):
        for query in _queries(parts):
            try:
                yield _Candidate(JsonPathStep(jsonpath=query, source=source))
            except ValidationError:  # outside the RFC 9535 subset the IR accepts
                continue


# --- every source document (locate run) -------------------------------------------------------------------------------


def source_steps(
    page: ParsedPage, ctx: Context, schema: SchemaDef, vocabulary: Vocabulary, name: str, value: JsonValue
) -> dict[JsonSource | None, list[Step]]:
    """The steps that select `value` for the page-level field `name` on `page`, by source document (None: the DOM),
    each source's first `_STEPS_PER_SOURCE` (module docstring). A step is proposed only when the engine executor reads
    `value` with it on `page`."""
    spec = schema.fields[name]
    f = _Field(name, spec, schema, [SamplePage(page, ctx, {name: Published(value, "")})], vocabulary)
    found: dict[JsonSource | None, list[Step]] = {}
    for source in LOCATED_SOURCES:
        paths = (path for document in documents(source, page) for path in holding(document, value, spec, ctx))
        steps = (_first_verified(list(_json_candidates(source, path)), f) for path in paths)
        found[source] = _distinct(steps)
    elements = _elements_holding(page.lxml_tree, value, spec, ctx)
    found[None] = _distinct(_first_verified(list(xpath_candidates(element, spec)), f) for element in elements)
    return {source: steps for source, steps in found.items() if steps}


def _first_verified(candidates: list[_Candidate], f: _Field) -> Step | None:
    return _induced_step([candidates], f) if candidates else None


def _distinct(steps: Iterator[Step | None]) -> list[Step]:
    """The first `_STEPS_PER_SOURCE` distinct steps."""
    found: dict[str, Step] = {}
    for step in steps:
        if step is not None:
            found.setdefault(step.model_dump_json(), step)
            if len(found) == _STEPS_PER_SOURCE:
                break
    return list(found.values())


def holding(document: JsonValue, value: JsonValue, spec: FieldSpec, ctx: Context) -> Iterator[str]:
    """The normalized path of each member of `document` that normalizes to `value`."""
    for path, scalar in scalars(document):
        if _normalizes_to(scalar, value, spec, ctx):
            yield path


def _json_candidates(source: JsonSource, path: str) -> Iterator[_Candidate]:
    """`jsonpath` steps over `source`'s documents reading `path`: indices stripped, then kept; then its holder's."""
    try:
        written = segments(path)
    except ValueError:  # a member name the engine's JSONPath reader does not take
        return
    for parts in _and_holder(written):
        for query in _queries(parts):
            try:
                yield _Candidate(JsonPathStep(jsonpath=query, source=source))
            except ValidationError:  # outside the RFC 9535 subset the IR accepts
                continue


def _elements_holding(tree: HtmlElement, value: JsonValue, spec: FieldSpec, ctx: Context) -> Iterator[HtmlElement]:
    """Each element, in document order, whose normalized text (an element with at most three children: a larger one
    holds more than one value) or one of whose attributes normalizes to `value`."""
    for element in tree.iter():
        if not isinstance(element.tag, str):
            continue
        text = " ".join(element.text_content().split()) if len(element) <= 3 else ""
        readings = [text] if 0 < len(text) <= _MAX_ELEMENT_TEXT else []
        readings += [v for v in element.attrib.values() if 0 < len(v) <= _MAX_ELEMENT_TEXT]
        if any(_normalizes_to(reading, value, spec, ctx) for reading in readings):
            yield element


def _normalizes_to(raw: str | int | float, value: JsonValue, spec: FieldSpec, ctx: Context) -> bool:
    result = normalize(raw, spec, ctx)
    return isinstance(result, Ok) and equal(result.value, value, spec)


# --- role C's spans ---------------------------------------------------------------------------------------------------


def span_element(page: ParsedPage, start: int, end: int) -> HtmlElement | None:
    """The innermost element whose text holds the cleaned text's `[start, end)` (a role C value grounded as a verbatim
    span, INV-12), when its node path resolves to one element of the lxml tree; None otherwise."""
    paths = [run.node_path for run in page.cleaned_text.offsets if run.start < end and start < run.end]
    if not paths:
        return None
    steps = [path.split("/") for path in paths]
    common = []
    for parts in zip(*steps, strict=False):
        if len(set(parts)) != 1:
            break
        common.append(parts[0])
    found = _select(page.lxml_tree, "/".join(common))
    return found[0] if len(found) == 1 and isinstance(found[0], HtmlElement) else None


# --- xpath ----------------------------------------------------------------------------------------------------------


def _xpath_candidates(tree: HtmlElement, xpath: str, spec: FieldSpec) -> Iterator[_Candidate]:
    """For a selector of one element: each anchored path to it (`xpath_candidates`). Any other selector (an expression
    of a config step) is proposed as it is."""
    found = _select(tree, xpath)
    if len(found) == 1 and isinstance(found[0], HtmlElement):
        yield from xpath_candidates(found[0], spec)
    elif (step := _xpath_step(xpath)) is not None:
        yield _Candidate(step)


def xpath_candidates(element: HtmlElement, spec: FieldSpec) -> Iterator[_Candidate]:
    """Each anchored path to `element`, nearest anchor first, read as its normalized text, then as each of its
    attributes."""
    for nodes in anchored_paths(element):
        for reading in readings(nodes, element, spec):
            yield _Candidate(reading, nodes)


def anchored_paths(element: HtmlElement) -> Iterator[str]:
    """`//anchor-test[anchor]/child/.../element` for each anchor of `element` and its ancestors, nearest first, without
    positional predicates (learning-configs spec)."""
    below = ""
    node: HtmlElement | None = element
    while node is not None and isinstance(node.tag, str):
        test = name_test(node.tag)
        for anchor in anchors(node):
            yield f"//{test}[{anchor}]{below}"
        below = f"/{test}{below}"
        node = node.getparent()


def anchors(node: HtmlElement) -> Iterator[str]:
    """The node's stable anchors: `@id`, `@itemprop`, `@data-*` and stable class tokens (learning-configs spec)."""
    for name in ("id", "itemprop"):
        if (value := node.get(name)) and (literal := _literal(value)) is not None:
            yield f"@{name}={literal}"
    for name, value in node.attrib.items():
        if name.startswith("data-") and (literal := _literal(value)) is not None:
            yield f"@{name}={literal}"
    for token in dict.fromkeys(tokens(node.get("class"))):
        if stable_class_token(token):
            # The XPath 1.0 idiom for "the class attribute holds this token" (what cssselect writes for `.token`).
            yield f"contains(concat(' ', normalize-space(@class), ' '), ' {token} ')"


def stable_class_token(token: str) -> bool:
    return _STABLE_CLASS.fullmatch(token) is not None and _DIGIT_RUN.search(token) is None


def _literal(value: str) -> str | None:
    # XPath 1.0 §3.7: a literal is quoted with `'` or `"` and has no escapes, so a value holding both is not anchored.
    if "'" not in value:
        return f"'{value}'"
    return f'"{value}"' if '"' not in value else None


def readings(nodes: str, element: HtmlElement, spec: FieldSpec) -> Iterator[Step]:
    """The node's normalized text (XPath 1.0 §4.2 `normalize-space`), then each of its attributes."""
    for attribute in (None, *element.attrib):
        yield from reading(nodes, attribute, spec)


def reading(nodes: str, attribute: str | None, _spec: FieldSpec) -> Iterator[Step]:
    """The node's normalized text, or its `attribute` as the page writes it: a relative `href` or `src` stays as
    written, the published form, and the url normalizer resolves it for comparison (normalization spec)."""
    xpath = f"normalize-space({nodes})" if attribute is None else f"{nodes}/@{attribute}"
    if (step := _xpath_step(xpath)) is not None:
        yield step


def _xpath_step(xpath: str) -> XPathStep | None:
    try:
        return XPathStep(xpath=xpath, post=[])
    except ValidationError:  # outside XPath 1.0 as the IR accepts it (an attribute name with a prefix)
        return None
