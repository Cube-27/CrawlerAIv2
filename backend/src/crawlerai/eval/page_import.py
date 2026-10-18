"""`crawlerai eval import-pages`: the pages of a site list captured into the dev split through the worker's acquisition
path (as `import-labels` does), each stored as an unlabeled page. They give the learning simulation pages of a host it
can hold out; no label is read or stored, so they take no part in a scored run."""

from collections.abc import Mapping, Sequence, Set

from crawlerai.eval.cli import Outcome, PageRequest, SchemaRef, Skipped, store_page
from crawlerai.eval.label_file import PageFetch
from crawlerai.eval.store import EvalStore
from crawlerai.schemas.types import SchemaDef


async def import_pages(
    store: EvalStore,
    schemas: Mapping[str, SchemaDef],
    requests: Sequence[PageRequest],
    fetch: PageFetch,
    existing: Set[str] = frozenset(),
) -> list[Outcome]:
    """Fetch each page in order with `fetch` (polite and serial: the caller's, which retries a page not reached and
    keeps its best capture, `best_fetch`), and store it whatever its outcome as an unlabeled page of `store`'s split. A
    page whose URL is in `existing` (the split's pages) is skipped, so an interrupted import can be run again."""
    outcomes: list[Outcome] = []
    for request in requests:
        if request.url in existing:
            outcomes.append(Skipped(request.n, "already_in_split"))
            continue
        schema = schemas[request.schema_name]
        result = await fetch(request.url, schema)
        if isinstance(result, str):
            outcomes.append(Skipped(request.n, result))
            continue
        outcomes.append(await store_page(store, SchemaRef(schema.id, schema.name, schema.page_kind), request, result))
    return outcomes
