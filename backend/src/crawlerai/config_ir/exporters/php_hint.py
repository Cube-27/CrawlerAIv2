"""The PHP code hint of an API recipe (SPEC-09 §4.9, ARCHITECTURE §12.2, OPEN_QUESTIONS #12): the recipe's request as
curl calls, rendered from `templates/api_recipe.php.j2`. It is a rendering of the data for a reader, never a program we
run (§18, INV-17).

The hint builds the request as `fetch_json` sends it (`replay.request_for`): each `{name}` placeholder filled with its
parameter, percent-encoded for the path or the query (`binding.render_url`) or escaped as JSON string content in a body
(`binding.render_body`); `Accept: application/json` first, replaced by a recipe header of the same name; `{page_url}` in
a header value replaced by the page URL. The caller supplies the parameters, read from the page as each binder says.

Every recipe string reaches the template only through `php_literal` (a PHP single-quoted literal) or `php_comment`
(a JSON string in a `//` comment), and the template refuses any other value, so no recipe string ends a literal, a
comment or PHP mode.
"""

import json
from collections.abc import Mapping
from typing import Final

from jinja2 import Environment, PackageLoader, StrictUndefined
from markupsafe import Markup

from crawlerai.acquire.api import ACCEPT
from crawlerai.acquire.redirects import MAX_REDIRECTS
from crawlerai.config_ir.api_recipe.binding import PATH_SAFE, QUERY_SAFE
from crawlerai.config_ir.api_recipe.model import PAGE_URL, ApiRecipe


class _Php(Markup):
    """Text that is PHP source as it stands: a literal, a comment's text or a number. A `Markup`, so autoescaping
    (which escapes for HTML) leaves it as it is."""

    __slots__ = ()


def php_literal(value: str) -> _Php:
    """`value` as a PHP single-quoted string literal (PHP manual, "Single quoted"): `\\` and `'` are escaped and nothing
    else is interpreted."""
    return _Php("'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'")


def php_comment(value: str) -> _Php:
    """`value` as a JSON string (RFC 8259 §7) for a `//` comment: ASCII, one line, with `>` escaped so the comment never
    holds `?>`, which ends PHP mode even inside a `//` comment (PHP manual, "Comments")."""
    return _Php(json.dumps(value).replace(">", "\\u003e"))


def _php_int(value: int) -> _Php:
    return _Php(str(value))


def _only_php(value: object) -> object:
    if not isinstance(value, _Php):
        raise TypeError(f"the PHP hint template writes only php_literal, php_comment or php_int values: {value!r}")
    return value


_ENV: Final = Environment(
    loader=PackageLoader("crawlerai.config_ir.exporters"),
    autoescape=True,
    undefined=StrictUndefined,
    finalize=_only_php,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)
_ENV.filters.update(php_literal=php_literal, php_comment=php_comment, php_int=_php_int)
_TEMPLATE: Final = _ENV.get_template("api_recipe.php.j2")


def php_hint(recipe: ApiRecipe) -> str:
    """The PHP hint of `recipe`."""
    path, question, query = recipe.url.partition("?")
    return _TEMPLATE.render(
        recipe=recipe,
        path=path,
        query=query if question else None,
        path_decode=_decode_map(PATH_SAFE),
        query_decode=_decode_map(QUERY_SAFE),
        headers=_headers(recipe),
        no_content_type=recipe.method == "POST" and not _has_header(recipe.headers, "content-type"),
        max_redirects=MAX_REDIRECTS,
        page_url=f"{{{PAGE_URL}}}",
    )


def _decode_map(safe: str) -> dict[str, str]:
    """`rawurlencode` (PHP manual) keeps only the RFC 3986 §2.3 unreserved characters, as Python's `quote` does; this
    map gives back the `safe` characters the engine leaves unencoded."""
    return {f"%{ord(char):02X}": char for char in safe}


def _has_header(headers: Mapping[str, str], name: str) -> bool:
    return any(header.lower() == name for header in headers)  # RFC 9110 §5.1: field names are case-insensitive


def _headers(recipe: ApiRecipe) -> list[str]:
    """The header lines `fetch_json` sends: `Accept` first, unless the recipe names it, then the recipe's in order."""
    lines = [] if _has_header(recipe.headers, "accept") else [f"Accept: {ACCEPT}"]
    return lines + [f"{name}: {value}" for name, value in recipe.headers.items()]
