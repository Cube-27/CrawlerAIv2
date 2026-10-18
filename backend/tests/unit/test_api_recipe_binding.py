"""Deterministic binding (SPEC-09 §4.4): sample pages and the endpoint requests made for them bind to a request spec
whose templates reproduce every request, or to `Ambiguous` with the reason."""

import pytest

from crawlerai.config_ir.api_recipe.binding import (
    Ambiguous,
    CapturedRequest,
    PageData,
    Sample,
    bind,
    render_body,
    render_url,
    resolve,
    resolve_params,
    withhold_tokens,
)
from crawlerai.config_ir.api_recipe.model import Binder, RequestSpec

_PAGE = "https://shop.example.test"
_API = "https://api.example.test"


def _sample(
    page_url: str, url: str, body: str | None = None, method: str = "GET", page_data: PageData | None = None
) -> Sample:
    return Sample(page_url, CapturedRequest(method, url, body), page_data or {})


def _spec(result: RequestSpec | Ambiguous) -> RequestSpec:
    assert isinstance(result, RequestSpec), result
    return result


def test_a_page_path_segment_binds_an_endpoint_path_segment_and_constants_stay_literal() -> None:
    samples = [
        _sample(f"{_PAGE}/p/blue-mug", f"{_API}/v1/products/blue-mug?lang=en"),
        _sample(f"{_PAGE}/p/red-cup", f"{_API}/v1/products/red-cup?lang=en"),
    ]

    spec = _spec(bind(samples))

    assert spec.url == f"{_API}/v1/products/{{p1}}?lang=en"
    assert spec.params_from_url == {"p1": "path:1"}
    assert (spec.method, spec.headers, spec.body, spec.requires_page_fetch) == ("GET", {}, None, False)


def test_a_page_query_value_binds_and_a_value_used_twice_is_one_parameter() -> None:
    samples = [
        _sample(f"{_PAGE}/item?id=17&ref=x", f"{_API}/items/17?expand=17"),
        _sample(f"{_PAGE}/item?id=42&ref=x", f"{_API}/items/42?expand=42"),
    ]

    spec = _spec(bind(samples))

    assert spec.url == f"{_API}/items/{{p1}}?expand={{p1}}"
    assert spec.params_from_url == {"p1": "query:id"}


def test_a_constant_that_the_page_url_holds_is_bound_too() -> None:
    samples = [
        _sample(f"{_PAGE}/de/p/1", f"{_API}/de/products/1"),
        _sample(f"{_PAGE}/de/p/2", f"{_API}/de/products/2"),
    ]

    assert _spec(bind(samples)).url == f"{_API}/{{p1}}/products/{{p2}}"


def test_an_id_only_in_the_page_data_binds_by_its_path_and_needs_the_page() -> None:
    samples = [
        _sample(f"{_PAGE}/p/blue-mug", f"{_API}/sku/9001", page_data={"jsonld": [{"@type": "Product", "sku": 9001}]}),
        _sample(f"{_PAGE}/p/red-cup", f"{_API}/sku/9002", page_data={"jsonld": [{"@type": "Product", "sku": 9002}]}),
    ]

    spec = _spec(bind(samples))

    assert spec.url == f"{_API}/sku/{{p1}}"
    assert spec.params_from_url == {"p1": "jsonld:$[0]['sku']"}
    assert spec.requires_page_fetch is True


def test_a_constant_in_the_page_data_stays_literal() -> None:
    samples = [
        _sample(f"{_PAGE}/p/a", f"{_API}/en/a", page_data={"js_state": {"locale": "en"}}),
        _sample(f"{_PAGE}/p/b", f"{_API}/en/b", page_data={"js_state": {"locale": "en"}}),
    ]

    spec = _spec(bind(samples))

    assert (spec.url, spec.requires_page_fetch) == (f"{_API}/en/{{p1}}", False)


def test_a_post_body_binds_string_and_number_values_in_place() -> None:
    body = '{{"query":"q1","variables":{{"slug":"{slug}","n":{n},"draft":false}}}}'
    samples = [
        _sample(f"{_PAGE}/p/a-b?n=3", f"{_API}/graphql", body.format(slug="a-b", n=3), "POST"),
        _sample(f"{_PAGE}/p/c-d?n=5", f"{_API}/graphql", body.format(slug="c-d", n=5), "post"),
    ]

    spec = _spec(bind(samples))

    assert spec.method == "POST"
    assert spec.body is not None
    assert spec.body.template == '{"query":"q1","variables":{"slug":"{p1}","n":{p2},"draft":false}}'
    assert spec.params_from_url == {"p1": "path:1", "p2": "query:n"}


def test_percent_encoded_values_bind_decoded_and_render_encoded_for_their_place() -> None:
    samples = [
        _sample(f"{_PAGE}/s/caf%C3%A9", f"{_API}/search?q=caf%C3%A9"),
        _sample(f"{_PAGE}/s/a%20b", f"{_API}/search?q=a%20b"),
    ]

    spec = _spec(bind(samples))

    assert spec.url == f"{_API}/search?q={{p1}}"
    assert resolve_params(spec, f"{_PAGE}/s/caf%C3%A9", {}) == {"p1": "café"}


_AMBIGUOUS = {
    "one sample page": (
        [_sample(f"{_PAGE}/p/a", f"{_API}/x/a")],
        "two sample pages",
    ),
    "a varying value no page value holds": (
        [_sample(f"{_PAGE}/p/a", f"{_API}/x/a/111"), _sample(f"{_PAGE}/p/b", f"{_API}/x/b/222")],
        "path segment 2 varies",
    ),
    "different hosts": (
        [_sample(f"{_PAGE}/p/a", f"{_API}/a"), _sample(f"{_PAGE}/p/b", "https://cdn.example.test/b")],
        "host, path length or query names differ",
    ),
    "different methods": (
        [_sample(f"{_PAGE}/p/a", f"{_API}/a"), _sample(f"{_PAGE}/p/b", f"{_API}/b", "{}", "POST")],
        "methods",
    ),
    "a body on some requests only": (
        [_sample(f"{_PAGE}/p/a", f"{_API}/a", "{}", "POST"), _sample(f"{_PAGE}/p/b", f"{_API}/b", None, "POST")],
        "some sample requests have a body",
    ),
    "a body that is not JSON": (
        [_sample(f"{_PAGE}/p/a", f"{_API}/a", "a=1", "POST"), _sample(f"{_PAGE}/p/b", f"{_API}/b", "a=2", "POST")],
        "not JSON",
    ),
    "a value that is part of a segment": (
        [_sample(f"{_PAGE}/p/a", f"{_API}/x/a.json"), _sample(f"{_PAGE}/p/b", f"{_API}/x/b.json")],
        "path segment 1 varies",
    ),
}


@pytest.mark.parametrize(("samples", "reason"), _AMBIGUOUS.values(), ids=_AMBIGUOUS.keys())
def test_binding_without_a_reproducing_template_is_ambiguous(samples: list[Sample], reason: str) -> None:
    result = bind(samples)

    assert isinstance(result, Ambiguous)
    assert reason in result.reason


def test_a_regex_binder_reads_its_group_from_the_page_path() -> None:
    assert resolve(Binder("regex", "^/p/([^/]+)"), f"{_PAGE}/p/blue%20mug/reviews?x=1", {}) == "blue mug"
    assert resolve(Binder("regex", "^/p/([^/]+)"), f"{_PAGE}/c/blue-mug", {}) is None


def test_a_missing_or_empty_value_resolves_to_none() -> None:
    jsonld: PageData = {"jsonld": [{"sku": 1}, {"sku": 2}]}
    js_state: PageData = {"js_state": {"flag": True, "n": 7}}

    assert [resolve(Binder("path", arg), f"{_PAGE}/p/a", {}) for arg in ("1", "3")] == ["a", None]
    assert [resolve(Binder("query", arg), f"{_PAGE}/p?id=&x=1", {}) for arg in ("x", "id")] == ["1", None]
    assert [resolve(Binder("jsonld", arg), _PAGE, jsonld) for arg in ("$[0]['sku']", "$[*]['sku']")] == ["1", None]
    assert [resolve(Binder("js_state", arg), _PAGE, js_state) for arg in ("$['n']", "$['flag']")] == ["7", None]


def test_values_render_encoded_in_the_url_and_escaped_in_the_body() -> None:
    params = {"a": 'x/y&z "q"'}

    assert render_url(f"{_API}/{{a}}?k={{a}}", params) == f"{_API}/x%2Fy&z%20%22q%22?k=x/y%26z%20%22q%22"
    assert render_body('{"k":"{a}"}', params) == '{"k":"x/y&z \\"q\\""}'


# --- token-like query values (owner delegation 2026-10-17) ---

_KEY = "Zk3Q9xLm2Vb7Rt4Ws8Np1Hc6"  # 24 characters of the base64url alphabet: token-like


def test_a_constant_token_like_query_value_no_page_value_holds_is_left_out() -> None:
    samples = [
        _sample(f"{_PAGE}/c/mugs", f"{_API}/search?q=mugs&key={_KEY}&lang=en"),
        _sample(f"{_PAGE}/c/cups", f"{_API}/search?q=cups&key={_KEY}&lang=en"),
    ]

    stripped, withheld = withhold_tokens(samples)

    assert withheld == ("key",)
    assert [s.request.url for s in stripped] == [f"{_API}/search?q=mugs&lang=en", f"{_API}/search?q=cups&lang=en"]
    spec = _spec(bind(stripped))
    assert spec.url == f"{_API}/search?q={{p1}}&lang=en"
    assert _KEY not in spec.model_dump_json()


def test_a_constant_token_the_page_data_states_is_bound_from_the_page() -> None:
    state: PageData = {"js_state": [{"config": {"searchKey": _KEY}}]}
    samples = [
        _sample(f"{_PAGE}/c/mugs", f"{_API}/search?q=mugs&key={_KEY}", page_data=state),
        _sample(f"{_PAGE}/c/cups", f"{_API}/search?q=cups&key={_KEY}", page_data=state),
    ]

    stripped, withheld = withhold_tokens(samples)
    spec = _spec(bind(stripped))

    assert (withheld, stripped) == ((), samples)
    assert spec.url == f"{_API}/search?q={{p1}}&key={{p2}}"
    assert spec.params_from_url["p2"] == "js_state:$[0]['config']['searchKey']"
    assert spec.requires_page_fetch is True


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("en", "en"),  # a constant too short to be a token
        (_KEY, _KEY[::-1]),  # token-like, but it varies: binding binds it or declines, as before
    ],
)
def test_short_or_varying_query_values_are_not_withheld(first: str, second: str) -> None:
    samples = [
        _sample(f"{_PAGE}/c/mugs", f"{_API}/search?q=mugs&v={first}"),
        _sample(f"{_PAGE}/c/cups", f"{_API}/search?q=cups&v={second}"),
    ]

    stripped, withheld = withhold_tokens(samples)

    assert (withheld, stripped) == ((), samples)


def test_a_withheld_token_leaves_an_ordinary_item_of_the_same_name() -> None:
    samples = [
        _sample(f"{_PAGE}/c/mugs", f"{_API}/search?q=mugs&id=1&id={_KEY}"),
        _sample(f"{_PAGE}/c/cups", f"{_API}/search?q=cups&id=1&id={_KEY}"),
    ]

    stripped, withheld = withhold_tokens(samples)

    assert withheld == ("id",)
    assert [s.request.url for s in stripped] == [f"{_API}/search?q=mugs&id=1", f"{_API}/search?q=cups&id=1"]


def test_a_token_of_a_single_sample_is_withheld_before_role_d() -> None:
    samples = [_sample(f"{_PAGE}/p/mug", f"{_API}/item?slug=mug&key={_KEY}")]

    stripped, withheld = withhold_tokens(samples)

    assert withheld == ("key",)
    assert [s.request.url for s in stripped] == [f"{_API}/item?slug=mug"]


def test_a_shared_token_is_withheld_when_the_samples_query_names_differ() -> None:
    samples = [
        _sample(f"{_PAGE}/c/mugs", f"{_API}/search?key={_KEY}&page=1"),
        _sample(f"{_PAGE}/c/cups", f"{_API}/search?key={_KEY}&sort=x"),
    ]

    stripped, withheld = withhold_tokens(samples)

    assert withheld == ("key",)
    assert [s.request.url for s in stripped] == [f"{_API}/search?page=1", f"{_API}/search?sort=x"]
