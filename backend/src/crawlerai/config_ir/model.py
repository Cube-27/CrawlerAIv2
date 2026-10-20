"""The extraction config IR (learning-configs spec): everything learned about a site, as one versioned
document that the engine executes and the exporters translate.

These models are the boundary every config crosses (induction, role A, operator corrections, the DB row), so a
document that validates here is one both executors can run: each step has exactly one selector, XPath is XPath 1.0,
regexes are in the portable subset and CSS carries its XPath translation. Site strings live in IR documents only
(C3); this module holds none.
"""

import re
from typing import Annotated, Any, Literal, Self

from cssselect import HTMLTranslator, SelectorError
from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    StringConstraints,
    Tag,
    model_serializer,
    model_validator,
)

from crawlerai.config_ir.api_recipe.model import ApiRecipe, check_jsonpath
from crawlerai.config_ir.portable_regex import PCRE_FLAGS, check_pattern, check_replacement
from crawlerai.config_ir.xpath1 import check_xpath1
from crawlerai.db.models import CaptureId, ConfigOrigin, FetchMethod, FieldStatus, PageKind
from crawlerai.schemas.types import NEXT_PAGE_FIELD as NEXT_PAGE_FIELD  # the executors read it from here (§12.1)
from crawlerai.schemas.types import FieldType, Name

# Where a `jsonpath` step reads JSON: the page's JSON-LD, its script state, its documented JSON attributes
# (`attr`, extraction spec "Source documents"), each row of its inline RSC Flight stream (`rsc`), a captured network
# body, an API response.
JsonSource = Literal["jsonld", "js_state", "attr", "rsc", "xhr", "api"]
# What a field's located source needs fetched (learning-configs spec, "Locate run"): the HTTP page (its HTML or an
# embedded document), the HTTP page and a replayed call (`call`), or the browser's render.
Needs = Literal["http", "call", "browser"]

XPath1 = Annotated[str, AfterValidator(check_xpath1)]
PortableRegex = Annotated[str, AfterValidator(check_pattern)]
# RFC 9535: the subset the engine reads (the `select` of `json_doc`: `$` and name, wildcard and index segments), so
# that a step that validates is one both executors run (§4.2); RFC 9535 §2.2: it starts with the root identifier `$`.
JsonPath = Annotated[str, StringConstraints(pattern=r"^\$"), AfterValidator(check_jsonpath)]
# schema.org naming conventions: a type is UpperCamelCase.
SchemaOrgType = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Za-z0-9]*$")]
# An HTML attribute name an XPath `@name` test can reach: an XML NCName (Namespaces in XML §3), ASCII here.
AttrName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_.\-]*$")]
Ratio = Annotated[float, Field(ge=0, le=1)]

_HTML_CSS = HTMLTranslator()


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_by_name=True, serialize_by_alias=True)


# --- post ops -------------------------------------------------------------------------------------------------------


class _NoParams(_Model):
    """`{}`: the op takes no parameters."""


def _has_own_values(type_: FieldType) -> FieldType:
    # schemas spec: `list` and `object` have no values of their own, so no normalizer runs on them.
    if type_ in (FieldType.LIST, FieldType.OBJECT):
        raise ValueError(f"{type_} has no normalizer of its own")
    return type_


class NormalizeOp(_Model):
    """`{"<field type>": {}}`: the type's normalizer (schemas spec) runs on the value."""

    type: Annotated[FieldType, AfterValidator(_has_own_values)]

    @model_validator(mode="before")
    @classmethod
    def _from_document(cls, data: Any) -> Any:
        if isinstance(data, dict) and len(data) == 1 and "type" not in data:
            ((type_, params),) = data.items()
            _NoParams.model_validate(params)
            return {"type": type_}
        return data

    @model_serializer
    def _to_document(self) -> dict[str, dict[str, Any]]:
        return {self.type.value: {}}


class TrimOp(_Model):
    trim: _NoParams


class AbsolutizeUrlOp(_Model):
    """Resolves the value against the page's base URL (RFC 3986 §5)."""

    absolutize_url: _NoParams


class RegexReplaceParams(_Model):
    pattern: PortableRegex
    repl: str

    @model_validator(mode="after")
    def _replacement_is_portable(self) -> Self:
        check_replacement(self.repl, re.compile(self.pattern, PCRE_FLAGS))
        return self


class RegexReplaceOp(_Model):
    regex_replace: RegexReplaceParams


_FIELD_TYPES = frozenset(FieldType)


def _post_op_kind(value: Any) -> str | None:
    """The op a post-op document names by its one key: a field type, `trim`, `regex_replace` or `absolutize_url`."""
    keys = list(value) if isinstance(value, dict) else [_model_key(value)]
    if len(keys) != 1:
        return None
    return "normalize" if keys[0] in _FIELD_TYPES else keys[0]


def _model_key(value: Any) -> str | None:
    if isinstance(value, NormalizeOp):
        return value.type.value
    fields = type(value).model_fields if isinstance(value, BaseModel) else {}
    return next(iter(fields), None)


PostOp = Annotated[
    Annotated[NormalizeOp, Tag("normalize")]
    | Annotated[TrimOp, Tag("trim")]
    | Annotated[AbsolutizeUrlOp, Tag("absolutize_url")]
    | Annotated[RegexReplaceOp, Tag("regex_replace")],
    Discriminator(
        _post_op_kind,
        custom_error_type="post_op",
        custom_error_message="a post op has one key: a field type, trim, regex_replace or absolutize_url",
    ),
]


# --- steps ----------------------------------------------------------------------------------------------------------


class _Step(_Model):
    post: list[PostOp] = []


class XPathStep(_Step):
    xpath: XPath1


class CssStep(_Step):
    """A CSS selector, kept for readability, and its XPath 1.0 translation, which is what executors run."""

    css: str
    xpath: XPath1

    @model_validator(mode="before")
    @classmethod
    def _translate(cls, data: Any) -> Any:
        if not isinstance(data, dict) or not isinstance(data.get("css"), str):
            return data
        try:
            xpath = _HTML_CSS.css_to_xpath(data["css"])
        except SelectorError as error:
            raise ValueError(f"not a CSS selector cssselect translates: {error}") from None
        if data.get("xpath", xpath) != xpath:
            raise ValueError("xpath is not the translation of css")
        return {**data, "xpath": xpath}


class JsonLdStep(_Step):
    """A JSONPath into the page's expanded JSON-LD nodes, optionally only those of one schema.org type."""

    jsonld: JsonPath
    when_type: SchemaOrgType | None = None


class JsonPathStep(_Step):
    jsonpath: JsonPath
    source: JsonSource


class RegexStep(_Step):
    regex: PortableRegex


class AttrStep(_Step):
    """An attribute of the context node: the row in a listing."""

    attr: AttrName


_SELECTOR_KEYS = ("xpath", "css", "jsonld", "jsonpath", "regex", "attr")


def selector_key(value: Any) -> str | None:
    """The step's one selector key. A CSS step also carries `xpath`, its translation."""
    present = {key for key in _SELECTOR_KEYS if _has_key(value, key)}
    if "css" in present:
        present.discard("xpath")
    return present.pop() if len(present) == 1 else None


def _has_key(value: Any, key: str) -> bool:
    return key in value if isinstance(value, dict) else getattr(value, key, None) is not None


Step = Annotated[
    Annotated[XPathStep, Tag("xpath")]
    | Annotated[CssStep, Tag("css")]
    | Annotated[JsonLdStep, Tag("jsonld")]
    | Annotated[JsonPathStep, Tag("jsonpath")]
    | Annotated[RegexStep, Tag("regex")]
    | Annotated[AttrStep, Tag("attr")],
    Discriminator(
        selector_key,
        custom_error_type="step",
        custom_error_message="a step has exactly one selector key: xpath, css, jsonld, jsonpath, regex or attr",
    ),
]


# --- the IR ---------------------------------------------------------------------------------------------------------


class FieldSteps(_Model):
    """A field's steps in order (the first valid value wins, §12.1), its status, and its held-out yield and validity
    (learning-configs spec) once validated."""

    steps: list[Step] = Field(min_length=1)
    status: FieldStatus
    yield_: Ratio | None = Field(default=None, alias="yield")
    validity: Ratio | None = None
    # What the field's source needs fetched (`http` when absent); a `call` field names its recipe in the config's
    # `recipes`, whose answer its `xhr` step reads.
    needs: Needs = "http"
    call: Name | None = None

    @model_validator(mode="after")
    def _has_steps_to_run(self) -> Self:
        # An absent field has no steps: the config lists it in `absent` (`config_ir.absent`).
        if self.status == "absent":
            raise ValueError("a field with steps is not absent")
        if (self.needs == "call") != (self.call is not None):
            raise ValueError("a field names a recipe exactly when it needs a call")
        return self


class ListingSpec(_Model):
    """Rows of a listing page: `row` selects the row nodes, `fields` run relative to each row, `next` locates the next
    page's URL."""

    row: Step
    fields: dict[Name, FieldSteps]
    next: Step | None = None


class SchemaRef(_Model):
    """The schema a config is for: its name, and the digest of its document at learning (`document_digest`). A schema
    is edited in place (D-0950), so only the digest says which document the config was learned for."""

    name: Name
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class Fetch(_Model):
    method: FetchMethod


class Provenance(_Model):
    origin: ConfigOrigin
    validated_on: list[CaptureId]
    learned_at: AwareDatetime
    engine_version: str = Field(min_length=1)


class ExtractionConfigIR(_Model):
    ir_version: Literal["1"]
    site: str = Field(min_length=1)
    schema_: SchemaRef = Field(alias="schema")
    page_kind: PageKind
    fetch: Fetch
    fields: dict[Name, FieldSteps]
    listing: ListingSpec | None = None
    # The recipe held-out validation accepted (adapters spec), served by the acquisition's API rung (§7.1).
    api_recipe: ApiRecipe | None = None
    # The recipes of the `call` fields (learning-configs spec, "Locate run"), one per endpoint, by id: each is a
    # companion call of the HTTP page (acquisition spec, "Data calls").
    recipes: dict[Name, ApiRecipe] = Field(default_factory=dict)
    provenance: Provenance
    # The required fields the learning pages never stated, which role C is not asked for (`config_ir.absent`, D-1341).
    absent: list[Name] = Field(default_factory=list)

    @model_validator(mode="after")
    def _absent_fields_have_no_steps(self) -> Self:
        listed = self.listing.fields if self.listing is not None else {}
        if any(name in self.fields or name in listed for name in self.absent):
            raise ValueError("an absent field has no steps")
        return self

    @model_validator(mode="after")
    def _calls_name_recipes(self) -> Self:
        listed = self.listing.fields.values() if self.listing is not None else ()
        named = {steps.call for steps in (*self.fields.values(), *listed) if steps.call is not None}
        if unknown := sorted(named - self.recipes.keys()):
            raise ValueError(f"fields name recipes the config does not hold: {unknown}")
        if unused := sorted(self.recipes.keys() - named):
            raise ValueError(f"recipes no field names: {unused}")
        return self

    def needs(self, *, running: bool = True) -> dict[str, Needs]:
        """Each page-level field's `needs`, the suspended ones left out when `running`."""
        return {name: steps.needs for name, steps in self.fields.items() if not running or steps.status != "suspended"}
