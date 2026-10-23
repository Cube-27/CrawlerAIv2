"""A listing's row keys: each row's item URL without the page's session parameters
(`normalize.url_key.session_parameters`), so two visits of one listing key its items alike and an item's URL is the one
its page states without the visit's query."""

from collections.abc import Collection, Iterable, Sequence

from crawlerai.normalize.url_key import session_parameters, without_parameters
from crawlerai.resolve.types import FieldOutcome, FieldSet


def keyed_rows(
    rows: Sequence[FieldSet], url_fields: Iterable[str], page_urls: Iterable[str]
) -> tuple[tuple[FieldSet, ...], dict[str, tuple[str, ...]]]:
    """`rows` with each published item URL field (`url_fields`) rid of the parameters its values share across the rows
    and the page's own URLs lack, and per field the names of the parameters dropped, sorted."""
    page = tuple(page_urls)
    keyed = [dict(row) for row in rows]
    dropped: dict[str, tuple[str, ...]] = {}
    for name in url_fields:
        urls = [url for row in keyed if (url := _published_url(row.get(name))) is not None]
        names = session_parameters(urls, page)
        if names:
            dropped[name] = tuple(sorted(names))
            for row in keyed:
                if name in row:
                    row[name] = _without(row[name], names)
    return tuple(keyed), dropped


def _published_url(outcome: FieldOutcome | None) -> str | None:
    if outcome is None or outcome.status != "published" or not isinstance(outcome.value, str):
        return None
    return outcome.value


def _without(outcome: FieldOutcome, names: Collection[str]) -> FieldOutcome:
    """The outcome keyed without `names`; it publishes as the page states it (`FieldOutcome.stated`)."""
    url = _published_url(outcome)
    if url is None:
        return outcome
    return outcome.model_copy(update={"value": without_parameters(url, names), "stated": outcome.published})
