"""Deterministic binding (adapters spec): sample pages and the endpoint requests made for them bind to a request spec
whose templates reproduce every request, or to `Ambiguous` with the reason."""

from crawlerai.config_ir.api_recipe.binding import (
    Ambiguous,
    CapturedRequest,
    PageData,
    Sample,
    bind,
    withhold_tokens,
)
from crawlerai.config_ir.api_recipe.model import RequestSpec

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
