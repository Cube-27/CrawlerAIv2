"""The release executor (learning-configs spec): a minimal second executor of the config IR, run only by
the release check on held-out pages.

It shares no code with the engine executor beyond the IR model (`.importlinter`), so a field on which the two agree is
evidence that the exported config reproduces the engine (INV-20). It parses the page body itself, the one exception to
INV-26, and reads it with lxml (XPath 1.0), `re`, `json` and jsonpath-ng: no collector, normalizer or vocabulary. What
it knows of the schema comes from the caller as one `FieldRule` per field. Selectors are data interpreted by lxml and
jsonpath-ng, never code (INV-17).
"""

import json
import math
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from urllib.parse import urljoin

from jsonpath_ng import parse as parse_jsonpath  # type: ignore[import-untyped]
from jsonpath_ng.exceptions import JsonPathLexerError, JsonPathParserError  # type: ignore[import-untyped]
from lxml import etree
from lxml import html as lxml_html

from crawlerai.config_ir.model import (
    NEXT_PAGE_FIELD,
    AbsolutizeUrlOp,
    AttrStep,
    CssStep,
    ExtractionConfigIR,
    FieldSteps,
    JsonLdStep,
    JsonPathStep,
    JsonSource,
    ListingSpec,
    NormalizeOp,
    PostOp,
    RegexReplaceOp,
    RegexStep,
    Step,
    TrimOp,
    XPathStep,
)

type Value = str | int | float | bool | list[Value] | dict[str, Value] | None

# The IR's regexes are the subset Python and PCRE read alike when Python matches ASCII-only, as PCRE does without its
# UCP option (learning-configs spec).
_REGEX_FLAGS = re.ASCII
# IANA media types: JSON-LD (embedded in HTML by a script of this type, JSON-LD 1.1 §7.1) and JSON (RFC 8259).
_JSONLD = "application/ld+json"
_JSON = "application/json"
# Adobe Commerce, JavaScript initialization: a `text/x-magento-init` script holds JSON.
_MAGENTO_INIT = "text/x-magento-init"
_ASTRO_PROPS = "props"
# Astro `serializeObject` PROP_TYPE: 0..11, the last ±Infinity.
_ASTRO_LAST_TYPE = 11
# The attributes documented to hold JSON, on their elements (extraction spec, "Source documents"): Inertia `data-page`,
# Livewire `wire:snapshot`, WooCommerce `data-product_variations`, Adobe Commerce `data-mage-init`, Astro island
# `props`, revived from its `[type, value]` tuples as the engine does (`_astro_props`).
_JSON_ATTRIBUTES = (
    ("*", "data-page"),
    ("*", "wire:snapshot"),
    ("*", "data-product_variations"),
    ("*", "data-mage-init"),
    ("astro-island", _ASTRO_PROPS),
)
# ECMAScript: an assignment to a property of `window` (the global object, HTML Standard) or a variable declaration
# with an initializer; `=` not followed by `=` or `>` is assignment, not comparison or an arrow. The match ends where
# the value starts.
_ASSIGNMENT = re.compile(r"(?:\bwindow\s*\.\s*|\b(?:var|let|const)\s+)(?!\d)[\w$]+\s*=(?![=>])\s*")
_DECODER = json.JSONDecoder()
# schema.org: a type's IRI is the vocabulary IRI plus its name; either scheme names the same term.
_SCHEMA_ORG = re.compile(r"^https?://schema\.org/")
# XPath 1.0 §4.2: `string()` is the context node's string-value.
_STRING_VALUE = etree.XPath("string()")


def _as_written(value: Value) -> Value:
    return value


@dataclass(frozen=True, slots=True)
class FieldRule:
    """What the release check tells the executor of one schema field. `many`: a list field takes every match, any other
    exactly one. `accepts(value, type)`: whether `value` is valid for the field type a normalizer post op names, or,
    with `None`, for the field itself. `structured(value)`: what the field reads of a value a `jsonld` or `jsonpath`
    step selects, as the engine's structured collectors read it (a text field reads markup as its rendered text). The
    caller runs the normalizers and that read, the one definition of each (schemas spec, C8); what this module checks
    independently is that the steps select and transform the values the engine did."""

    many: bool
    accepts: Callable[[Value, str | None], bool]
    structured: Callable[[Value], Value] = _as_written


@dataclass(frozen=True, slots=True)
class ReleasePage:
    """A held-out page: its decoded body, its captured network bodies in request order, and its base URL."""

    html: str
    network: Sequence[bytes] = ()
    base_url: str | None = None


@dataclass(frozen=True, slots=True)
class Released:
    """The value of each field the IR's steps reproduce on a page: page-level fields (with `next_page_url` from a
    listing's `next`) and one mapping per listing row. A field without a valid value is absent."""

    fields: dict[str, Value]
    rows: tuple[dict[str, Value], ...]
    diagnostics: tuple[str, ...]


def release_run(ir: ExtractionConfigIR, page: ReleasePage, rules: Mapping[str, FieldRule]) -> Released:
    """The IR's values on `page`. In each field the first step whose value passes its post ops and the field's rule
    wins (§12.1); a field without a rule, or `suspended`, does not run."""
    run = _Run(page, _parse(page.html), rules)
    fields = run.fields(ir.fields, run.root, in_row=False)
    rows: tuple[dict[str, Value], ...] = ()
    if ir.listing is not None:
        rows = tuple(run.fields(ir.listing.fields, node, in_row=True) for node in run.rows(ir.listing.row))
        found = run.next_page(ir.listing)
        if found is not None:
            fields[NEXT_PAGE_FIELD] = found
    return Released(fields=fields, rows=rows, diagnostics=tuple(run.diagnostics))


class _Unreadable(Exception):
    """A step this executor cannot run on the page; its message becomes a diagnostic and the next step runs."""


@dataclass
class _Run:
    page: ReleasePage
    root: etree._Element
    rules: Mapping[str, FieldRule]
    diagnostics: list[str] = field(default_factory=list)
    _json: dict[JsonSource, list[Value]] = field(default_factory=dict)

    def fields(self, fields: Mapping[str, FieldSteps], node: etree._Element, *, in_row: bool) -> dict[str, Value]:
        values: dict[str, Value] = {}
        for name, steps in fields.items():
            rule = self.rules.get(name)
            if rule is None:
                self.diagnostics.append(f"{name}: no rule")
            elif steps.status != "suspended":  # §8.3: a suspended field is not run
                found = self.first_valid(name, steps.steps, rule, node, in_row=in_row)
                if found is not None:
                    values[name] = found
        return values

    def first_valid(
        self, name: str, steps: Sequence[Step], rule: FieldRule, node: etree._Element, *, in_row: bool
    ) -> Value | None:
        for index, step in enumerate(steps):
            try:
                matches = self.matches(step, node, in_row=in_row)
            except _Unreadable as unreadable:
                self.diagnostics.append(f"{name}:{index}: {unreadable}")
                continue
            if isinstance(step, (JsonLdStep, JsonPathStep)):
                matches = [rule.structured(match) for match in matches]
            value = _take(matches, step.post, rule, self.page.base_url)
            if value is not None:
                return value
        return None

    def matches(self, step: Step, node: etree._Element, *, in_row: bool) -> list[Value]:
        if in_row and isinstance(step, (RegexStep, JsonLdStep, JsonPathStep)):
            raise _Unreadable("regex, jsonld and jsonpath steps read the whole page, not a row")
        match step:
            case XPathStep() | CssStep():  # a CSS step carries its XPath translation
                return _xpath(step.xpath, node)
            case AttrStep():
                found = node.get(step.attr)
                return [] if found is None else [str(found)]
            case RegexStep():
                return _regex(step.regex, self.page.html)
            case JsonLdStep():
                nodes = [typed for document in self.json("jsonld") for typed in _typed(document, step.when_type)]
                return _query(step.jsonld, nodes)
            case JsonPathStep():
                return _query(step.jsonpath, self.json(step.source))

    def json(self, source: JsonSource) -> list[Value]:
        if source not in self._json:
            self._json[source] = list(_documents(source, self.page, self.root))
        return self._json[source]

    def rows(self, step: Step) -> list[etree._Element]:
        if not isinstance(step, (XPathStep, CssStep)):
            self.diagnostics.append("row: a row step is an xpath or css step")
            return []
        try:
            found = self.root.xpath(step.xpath)
        except etree.XPathError as error:
            self.diagnostics.append(f"row: invalid_xpath: {error}")
            return []
        return [node for node in found if isinstance(node, etree._Element)] if isinstance(found, list) else []

    def next_page(self, listing: ListingSpec) -> Value | None:
        rule = self.rules.get(NEXT_PAGE_FIELD)
        if listing.next is None or rule is None:
            return None
        return self.first_valid(NEXT_PAGE_FIELD, [listing.next], rule, self.root, in_row=False)


def _take(matches: list[Value], post: Sequence[PostOp], rule: FieldRule, base_url: str | None) -> Value | None:
    """The step's valid value: every match through the post ops for a list field, else the one match; `None` when there
    is none, more than one, or a value is not valid. A JSON `null` is no value of any field type (schemas spec: an
    absent value is a field status), so `None` is never a valid value."""
    if not matches or (len(matches) > 1 and not rule.many):
        return None
    processed: list[Value] = []
    for match in matches:
        value = _post(match, post, rule, base_url)
        if value is None:
            return None
        processed.append(value)
    result: Value = processed if rule.many else processed[0]
    return result if rule.accepts(result, None) else None


def _post(value: Value, ops: Sequence[PostOp], rule: FieldRule, base_url: str | None) -> Value | None:
    """`value` through `ops` in order, or `None` when one declines it. A normalizer op is a check: the value passes on
    unchanged, since the field's normalizer makes the value (schemas spec)."""
    if value is None:
        return None
    for op in ops:
        if isinstance(op, NormalizeOp):
            if not rule.accepts(value, op.type.value):
                return None
            continue
        if not isinstance(value, str):  # trim, regex_replace and absolutize_url work on text
            return None
        match op:
            case TrimOp():
                value = value.strip()
            case RegexReplaceOp():
                value = re.sub(op.regex_replace.pattern, op.regex_replace.repl, value, flags=_REGEX_FLAGS)
            case AbsolutizeUrlOp():
                if base_url is None:  # RFC 3986 §5 resolves against a base URL; none is assumed (C7)
                    return None
                value = urljoin(base_url, value)
    return value


def _xpath(xpath: str, node: etree._Element) -> list[Value]:
    """XPath 1.0 §1: a result is a node-set, a string, a number or a boolean. A node's value is its string-value (§5);
    an empty string or NaN is no match, and a boolean is no value."""
    try:
        result = node.xpath(xpath)
    except etree.XPathError as error:
        raise _Unreadable(f"invalid_xpath: {error}") from None
    if isinstance(result, bool):
        raise _Unreadable("a boolean XPath result is not a value")
    if isinstance(result, float):
        return [] if math.isnan(result) else [result]
    if isinstance(result, str):
        return [str(result)] if result else []
    if not isinstance(result, list):
        raise _Unreadable(f"unexpected XPath result {type(result).__name__}")
    return [str(_STRING_VALUE(item)) if isinstance(item, etree._Element) else str(item) for item in result]


def _regex(pattern: str, text: str) -> list[Value]:
    """Each match's first group, or the whole match when the pattern has none."""
    compiled = re.compile(pattern, _REGEX_FLAGS)
    group = 1 if compiled.groups else 0
    return [found for m in compiled.finditer(text) if (found := m.group(group)) is not None]


def _query(query: str, documents: Sequence[Value]) -> list[Value]:
    try:
        compiled = _jsonpath(query)
    except (JsonPathLexerError, JsonPathParserError) as error:
        raise _Unreadable(f"invalid_jsonpath: {error}") from None
    return [found.value for document in documents for found in compiled.find(document)]


@lru_cache(maxsize=256)
def _jsonpath(query: str) -> Any:
    """The parsed query; jsonpath-ng builds a parser per call, and a config's queries repeat on every held-out page."""
    return parse_jsonpath(query)


def _parse(html: str) -> etree._Element:
    # Parsed from UTF-8 with the encoding named, so that an XML encoding declaration in the text is ignored.
    try:
        return lxml_html.document_fromstring(html.encode("utf-8"), parser=lxml_html.HTMLParser(encoding="utf-8"))
    except etree.ParserError:  # an empty or all-whitespace body has no root element
        return lxml_html.Element("html")


def _documents(source: JsonSource, page: ReleasePage, root: etree._Element) -> Iterator[Value]:
    """The JSON documents of `source`; one that is not JSON is skipped."""
    match source:
        case "jsonld" | "js_state":
            for media_type, text in _scripts(root):
                yield from _script_json(source, media_type, text)
        case "attr":
            for name, value in _json_attributes(root):
                for document in _loads(value):
                    yield _astro_props(document) if name == _ASTRO_PROPS else document
        case "xhr":
            for body in page.network:
                yield from _loads(body)
        case "api":
            raise _Unreadable("an api source is read through adapters spec's api recipe executor")


def _json_attributes(root: etree._Element) -> Iterator[tuple[str, str]]:
    """The values of the documented JSON attributes that start with `{` or `[` (RFC 8259 whitespace before), in
    document order."""
    for element in root.iter(etree.Element):
        for tag, name in _JSON_ATTRIBUTES:
            value = element.get(name)
            if value is not None and tag in ("*", element.tag) and value.lstrip(" \t\n\r")[:1] in ("{", "["):
                yield name, value


def _astro_props(props: Value) -> Value:
    """Astro island props as Astro's client revives them (`astro-island.ts`), as JSON: an object whose every value is a
    `[type, value]` tuple (type 0..11) has each tuple replaced by its value; a JSON array, Map or Set (1, 4, 5) holds
    tuples itself, ±Infinity (11) and `undefined` (`[0]`) are `null`, every other type its written value. Any other
    document, or one nested deeper than the stack follows, is read as written."""
    if not isinstance(props, dict) or not props or not all(_is_astro_tuple(v) for v in props.values()):
        return props
    try:
        return {key: _astro_value(value) for key, value in props.items()}
    except RecursionError:
        return props


def _is_astro_tuple(value: Value) -> bool:
    return (
        isinstance(value, list)
        and 1 <= len(value) <= 2
        and isinstance(value[0], int)
        and not isinstance(value[0], bool)
        and 0 <= value[0] <= _ASTRO_LAST_TYPE
    )


def _astro_value(raw: Value) -> Value:
    if not isinstance(raw, list) or len(raw) != 2 or not _is_astro_tuple(raw):
        return None
    kind, value = raw
    if kind == 0 and isinstance(value, dict):
        return {key: _astro_value(member) for key, member in value.items()}
    if kind in (1, 4, 5) and isinstance(value, list):
        return [_astro_value(item) for item in value]
    return None if kind == _ASTRO_LAST_TYPE else value


def _scripts(root: etree._Element) -> Iterator[tuple[str, str]]:
    """Each inline script's media type essence and text. HTML Standard: a script with `src` runs the external resource,
    not its text; the type is compared by its essence (WHATWG MIME Sniffing: parameters dropped, lower-cased)."""
    for script in root.iter("script"):
        if script.get("src") is None:
            media_type = (script.get("type") or "").split(";", 1)[0].strip().lower()
            yield media_type, script.text or ""


def _script_json(source: JsonSource, media_type: str, text: str) -> Iterator[Value]:
    """A script's JSON documents for `source`: a JSON-LD block's; for script state, a JSON block's, or the objects and
    arrays its state assignments (`window.x =`, `var x =`) start with, in order, each searched for after the value
    before it."""
    if source == "jsonld":
        if media_type == _JSONLD:
            # As the jsonld collector reads it (extraction spec): raw control characters inside strings, which RFC 8259
            # §7 requires escaped and §9 lets a parser accept, read as their escaped form (`strict=False`).
            yield from _loads(text, strict=False)
        return
    if media_type in (_JSON, _MAGENTO_INIT):
        yield from _loads(text)
    if media_type in (_JSONLD, _JSON, _MAGENTO_INIT):
        return
    start = 0
    while (found := _ASSIGNMENT.search(text, start)) is not None:
        start = found.end()
        try:
            value, start = _DECODER.raw_decode(text, start)
        except (ValueError, RecursionError):  # not JSON, or nested deeper than the parser follows
            continue
        if isinstance(value, (dict, list)):  # a scalar initializer is a script variable
            yield value


def _loads(data: str | bytes, *, strict: bool = True) -> Iterator[Value]:
    """The JSON value `data` holds, or none: a body that is not JSON (RFC 8259; bytes decoded as `json.loads` decodes
    them, UTF-8 or the UTF-16/32 forms RFC 4627 §3 tells apart), or nests deeper than the parser follows. The engine's
    reader is `core.json_text`; this is the executor's own copy (INV-20)."""
    try:
        yield json.loads(data, strict=strict)
    except (ValueError, RecursionError):
        return


def _typed(document: Value, when_type: str | None) -> Iterator[Value]:
    """Every JSON-LD node object in `document` that has a schema.org `@type`, in document order, keeping those of
    `when_type` when one is given. A type is a schema.org IRI anywhere, or a term where schema.org is the vocabulary in
    scope (JSON-LD 1.1 §4.1.2)."""
    for value, in_schema in _scoped(document):
        types = _type_names(value.get("@type"), in_schema)
        if types and (when_type is None or when_type in types):
            yield value


def _scoped(document: Value) -> Iterator[tuple[dict[str, Value], bool]]:
    """Every object of `document` in document order, with whether schema.org is the vocabulary in its scope."""
    stack: list[tuple[Value, bool]] = [(document, False)]
    while stack:
        value, in_schema = stack.pop()
        if isinstance(value, list):
            stack.extend((item, in_schema) for item in reversed(value))
        elif isinstance(value, dict):
            if "@context" in value:
                in_schema = _schema_org_after(value["@context"], in_schema)
            yield value, in_schema
            stack.extend((child, in_schema) for key, child in reversed(value.items()) if key != "@context")


def _schema_org_after(context: Value, in_schema: bool) -> bool:
    """Whether schema.org is the vocabulary after `context` (JSON-LD 1.1 §4.1): a context is processed item by item; a
    string names a remote context (only schema.org's is known, unfetched); an object sets `@vocab` or keeps the one in
    scope; `null` resets it."""
    for item in context if isinstance(context, list) else [context]:
        if isinstance(item, str):
            in_schema = _SCHEMA_ORG.fullmatch(item.rstrip("/") + "/") is not None
        elif isinstance(item, dict) and "@vocab" in item:
            vocab = item["@vocab"]
            in_schema = isinstance(vocab, str) and _SCHEMA_ORG.fullmatch(vocab) is not None
        elif not isinstance(item, dict):
            in_schema = False
    return in_schema


def _type_names(declared: Value, in_schema: bool) -> set[str]:
    items = declared if isinstance(declared, list) else [declared]
    names = {_SCHEMA_ORG.sub("", item) for item in items if isinstance(item, str) and _SCHEMA_ORG.match(item)}
    return names | {item for item in items if in_schema and isinstance(item, str) and ":" not in item}
