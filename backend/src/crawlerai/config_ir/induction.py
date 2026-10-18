"""Induction (SPEC-08 §4.5, ARCHITECTURE §8.3 step 1): selectors generalized from the locators of the values the engine
published on the learning sample, without an LLM.

For each field, every sample page's published locator proposes candidate steps:
- `jsonld:<block>:<path>`: a `jsonld` step relative to each schema.org node the value is nested in (nearest first),
  typed by the node's types, with array indices stripped (`[*]`), then with them kept;
- `microdata:<xpath>`, `dom:<xpath>` and `config:` XPaths that select one element: for each anchor on the element and
  its ancestors (nearest first), the path from the anchored ancestor down to the element without positional
  predicates, read as `normalize-space(...)`, then as each of the element's attributes;
- `adapter:`/`api:` with the same mapping name on every page: the field comes from that mapping (`origin=adapter`);
- anything else (`text:` from role C, `meta:`, `js_state:`, `xhr:`): no induction, the field goes to synthesis.

A candidate is kept only if every sample page proposes it and, on every page, it selects exactly one node whose value
the engine executor normalizes to the published value (`equal`). The first such candidate wins; a field without one
goes to synthesis (§4.6). Site strings exist only in the steps produced, which are IR data (C3, INV-03).
"""

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field

from lxml import etree
from lxml.html import HtmlElement
from pydantic import JsonValue, ValidationError

from crawlerai.collect.induce import induced
from crawlerai.collect.json_doc import ROOT, segments
from crawlerai.collect.jsonld import JsonLdCollector
from crawlerai.collect.locator import InvalidLocator, Locator, parse_locator
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.executor import field_candidate
from crawlerai.config_ir.model import FieldSteps, JsonLdStep, Step, XPathStep
from crawlerai.content.dom import tokens
from crawlerai.content.page import ParsedPage
from crawlerai.content.text import name_test
from crawlerai.db.models import FieldStatus
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import equal
from crawlerai.schemas.types import FieldSpec, SchemaDef

# A class token that reads as a word or kebab-case words is a stable anchor; tokens that build tools hash carry
# uppercase letters, underscores or long digit runs. A structural property of the token (SPEC-08 §4.5, D-0031), not a
# list of names.
_STABLE_CLASS = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")
_DIGIT_RUN = re.compile(r"\d{3}", re.ASCII)
# RFC 9535 §2.3.3: an index segment.
_INDEX = re.compile(r"\[\d+\]", re.ASCII)
_STATUS: FieldStatus = "uncorroborated"  # until validation (§4.7) records corroboration


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
    """Steps for the fields of a detail schema whose published locators generalize over `sample`. A listing's rows
    are synthesized (§4.6), so a listing schema induces nothing."""
    if schema.page_kind != "detail" or not sample:
        return Induction(to_synthesize=dict.fromkeys(schema.fields, "listing" if sample else "no_sample"))
    result = Induction()
    for name, spec in schema.fields.items():
        _induce_field(_Field(name, spec, schema, sample, vocabulary), result)
    return result


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
    if len(schemes) != 1:
        result.to_synthesize[f.name] = "no_common_pattern"
        return
    (scheme,) = schemes
    if scheme in ("adapter", "api"):
        _mapped(f.name, scheme, locators, result)
        return
    if not (scheme == "jsonld" or (scheme in ("microdata", "dom", "config") and f.spec.item is None)):
        result.to_synthesize[f.name] = f"not_induced:{scheme}"
        return
    step = _induced_step(
        [_proposals(locator, sample, f) for locator, sample in zip(locators, f.sample, strict=True)], f
    )
    if step is None:
        result.to_synthesize[f.name] = "no_verified_selector"
    else:
        result.fields[f.name] = FieldSteps(steps=[step], status=_STATUS)


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
    # SPEC-08 §4.5: values an adapter or API recipe published come from its mapping, which the config reuses.
    mappings = {locator.parts[0] for locator in locators}
    if len(mappings) == 1:
        result.mapped[name] = f"{scheme}:{mappings.pop()}"
    else:
        result.to_synthesize[name] = "no_common_pattern"


def _proposals(locator: Locator, sample: SamplePage, f: _Field) -> list[_Candidate]:
    """The page's candidate steps for its `jsonld`, `microdata`, `dom` or `config` locator, in order of preference."""
    if locator.scheme == "jsonld":
        return list(_jsonld_candidates(sample.page, f.vocabulary, locator))
    return list(_xpath_candidates(sample.page.lxml_tree, locator.parts[-1]))


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
    to the value with array indices stripped, then as written."""
    block, path = locator.parts
    try:
        parts = segments(path)
    except ValueError:  # a member name the engine's JSONPath reader does not take
        return
    typed = {node: types for node, types, _ in JsonLdCollector(vocabulary).nodes(page)}
    for at in range(len(parts), -1, -1):
        types = typed.get(f"jsonld:{block}:{ROOT}" + "".join(parts[:at]), ())
        rest = parts[at:]
        stripped = ROOT + "".join("[*]" if _INDEX.fullmatch(s) else s for s in rest)
        written = ROOT + "".join(rest)
        for type_ in types:
            for query in dict.fromkeys((stripped, written)):
                if (step := _jsonld_step(query, type_)) is not None:
                    yield _Candidate(step)


def _jsonld_step(query: str, type_: str) -> JsonLdStep | None:
    try:
        return JsonLdStep(jsonld=query, when_type=type_)
    except ValidationError:  # a type name outside schema.org's naming conventions
        return None


# --- xpath ----------------------------------------------------------------------------------------------------------


def _xpath_candidates(tree: HtmlElement, xpath: str) -> Iterator[_Candidate]:
    """For a selector of one element: each anchored path to it, nearest anchor first, read as its normalized text, then
    as each of its attributes. Any other selector (an expression of a config step) is proposed as it is."""
    found = _select(tree, xpath)
    if len(found) == 1 and isinstance(found[0], HtmlElement):
        element = found[0]
        for nodes in _anchored_paths(element):
            for reading in _readings(nodes, element):
                yield _Candidate(reading, nodes)
    elif (step := _xpath_step(xpath)) is not None:
        yield _Candidate(step)


def _anchored_paths(element: HtmlElement) -> Iterator[str]:
    """`//anchor-test[anchor]/child/.../element` for each anchor of `element` and its ancestors, nearest first, without
    positional predicates (SPEC-08 §4.5)."""
    below = ""
    node: HtmlElement | None = element
    while node is not None and isinstance(node.tag, str):
        test = name_test(node.tag)
        for anchor in _anchors(node):
            yield f"//{test}[{anchor}]{below}"
        below = f"/{test}{below}"
        node = node.getparent()


def _anchors(node: HtmlElement) -> Iterator[str]:
    """The node's stable anchors: `@id`, `@itemprop`, `@data-*` and stable class tokens (SPEC-08 §4.5)."""
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


def _readings(nodes: str, element: HtmlElement) -> Iterator[Step]:
    """The node's normalized text (XPath 1.0 §4.2 `normalize-space`), then each of its attributes."""
    for xpath in (f"normalize-space({nodes})", *(f"{nodes}/@{name}" for name in element.attrib)):
        if (step := _xpath_step(xpath)) is not None:
            yield step


def _xpath_step(xpath: str) -> XPathStep | None:
    try:
        return XPathStep(xpath=xpath)
    except ValidationError:  # outside XPath 1.0 as the IR accepts it (an attribute name with a prefix)
        return None
