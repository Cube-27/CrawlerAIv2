"""A listing's row keys: each row's item URL without the page's session parameters (extraction spec, "Row item URLs
without session parameters"; `normalize.url_key.session_parameters`), so two visits of one listing key its items
alike and an item's URL is the one its page states without the visit's query."""

from collections.abc import Iterable, Sequence

from crawlerai.normalize.url_key import session_parameters, without_parameters
from crawlerai.resolve.types import FieldSet


def keyed_rows(
    rows: Sequence[FieldSet], url_fields: Iterable[str], page_urls: Iterable[str]
) -> tuple[tuple[FieldSet, ...], tuple[str, ...]]:
    """`rows` with each published item URL field (`url_fields`) rid of the parameters its values share across the rows
    and the page's own URLs lack, and the names of the parameters dropped, sorted."""
    page = tuple(page_urls)
    keyed = [dict(row) for row in rows]
    dropped: set[str] = set()
    for name in url_fields:
        published = [row[name] for row in keyed if name in row and row[name].status == "published"]
        names = session_parameters([o.value for o in published if isinstance(o.value, str)], page)
        if not names:
            continue
        dropped |= names
        for row in keyed:
            outcome = row.get(name)
            if outcome is not None and outcome.status == "published" and isinstance(outcome.value, str):
                row[name] = outcome.model_copy(update={"value": without_parameters(outcome.value, names)})
    return tuple(keyed), tuple(sorted(dropped))
