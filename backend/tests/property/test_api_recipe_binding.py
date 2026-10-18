"""Binder round trips (SPEC-09 §6): a value placed in a page URL is read back by its binder, and endpoint requests
generated from a template bind back to binders that reproduce every request."""

from dataclasses import dataclass
from urllib.parse import quote

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.config_ir.api_recipe.binding import CapturedRequest, Sample, bind, render_url, resolve, resolve_params
from crawlerai.config_ir.api_recipe.model import Binder, RequestSpec

# Values hold characters that need percent-encoding (space, `%`, `&`, `/`, `+`, non-ASCII) beside plain ones. Literal
# path segments are upper case, so no value meets a literal.
_value = st.text(alphabet="abcxyz0189-._~ %&/+=é", min_size=1, max_size=8)


@given(_value, st.integers(min_value=0, max_value=3))
def test_a_value_in_the_page_url_is_read_back_by_its_binder(value: str, index: int) -> None:
    segments = ["S"] * index + [quote(value, safe="")]
    page_url = "https://www.example.test/" + "/".join(segments) + "?k=" + quote(value, safe="")

    assert resolve(Binder("path", str(index)), page_url, {}) == value
    assert resolve(Binder("query", "k"), page_url, {}) == value


@dataclass(frozen=True)
class _Layout:
    """Where each parameter sits on the page (`path:<i>` or `query:<name>`) and in the endpoint URL."""

    page_binders: list[Binder]
    endpoint_template: str

    def page_url(self, values: list[str]) -> str:
        path = ["P"] * (1 + sum(binder.kind == "path" for binder in self.page_binders))
        query = []
        for binder, value in zip(self.page_binders, values, strict=True):
            if binder.kind == "path":
                path[int(binder.arg)] = quote(value, safe="")
            else:
                query.append(f"{binder.arg}={quote(value, safe='')}")
        return "https://www.example.test/" + "/".join(path) + ("?" + "&".join(query) if query else "")

    def endpoint_url(self, values: list[str]) -> str:
        return render_url(self.endpoint_template, {f"v{i}": value for i, value in enumerate(values)})


@st.composite
def _layouts(draw: st.DrawFn) -> _Layout:
    count = draw(st.integers(min_value=1, max_value=3))
    in_path = draw(st.lists(st.booleans(), min_size=count, max_size=count))
    path_indexes = iter(range(1, count + 1))
    binders = [
        Binder("path", str(next(path_indexes))) if p else Binder("query", f"q{i}") for i, p in enumerate(in_path)
    ]
    order = draw(st.permutations(range(count)))
    in_endpoint_query = draw(st.lists(st.booleans(), min_size=count, max_size=count))
    segments = ["API", "V1"] + [f"{{v{i}}}" for i in order if not in_endpoint_query[i]]
    query = [f"k{i}={{v{i}}}" for i in order if in_endpoint_query[i]] + ["fmt=JSON"]
    return _Layout(binders, "https://api.example.test/" + "/".join(segments) + "?" + "&".join(query))


@given(_layouts(), st.data())
def test_generated_requests_bind_back_to_their_binders(layout: _Layout, data: st.DataObject) -> None:
    count, pages = len(layout.page_binders), data.draw(st.integers(min_value=2, max_value=4))
    values = data.draw(st.lists(_value, min_size=count * pages, max_size=count * pages, unique=True))
    rows = [values[page * count : (page + 1) * count] for page in range(pages)]
    samples = [Sample(layout.page_url(row), CapturedRequest("GET", layout.endpoint_url(row))) for row in rows]

    spec = bind(samples)

    assert isinstance(spec, RequestSpec), spec
    assert set(spec.binders.values()) == set(layout.page_binders)
    for sample, row in zip(samples, rows, strict=True):
        params = resolve_params(spec, sample.page_url, {})
        assert params is not None
        assert sorted(params.values()) == sorted(row)
        assert render_url(spec.url, params) == sample.request.url
