"""The documented platform JSON collector (a data call): the product JSON a platform
documents, fetched beside a detail page's HTTP fetch and kept only when it stated the requested product
(`acquire.identity`), read as the schema.org nodes the platform's documentation says it holds
(`adapters.platforms.answer_shape`).

Such a body is structured evidence of the requested product, as an adapter's answer is: its values are `adapter`
candidates read by the schema.org path rules (`read_shapes` of `collect/adapter.py`), located under `<platform>_json`,
not admitted by the equality-or-visibility rule the captured network JSON of unknown keys takes (`collect.admission`),
which never reads these bodies. Every other network body keeps that rule. The answer's root is the requested product
by construction (`Entity.requested`), so identity merges it into the page's own product (`resolve.identity`).
"""

from collections.abc import Iterator

from pydantic import JsonValue

from snowcrawl.adapters.base import ADAPTER_CALL
from snowcrawl.adapters.platforms import answer_shape
from snowcrawl.collect.adapter import read_shapes
from snowcrawl.collect.base import Candidate, CollectResult, Entity
from snowcrawl.collect.vocabulary import Vocabulary
from snowcrawl.content.page import ParsedPage
from snowcrawl.normalize.base import Context
from snowcrawl.schemas.types import SchemaDef
from snowcrawl.storage.capture_bundle import network_json, recipe_mark

__all__ = ["PlatformJsonCollector", "data_call_bodies"]


def data_call_bodies(page: ParsedPage) -> frozenset[int]:
    """The indexes of the page's network bodies that are identity-checked platform data calls."""
    return frozenset(i for i, entry in enumerate(page.network_entries) if entry.data_call is not None)


class PlatformJsonCollector:
    def __init__(self, vocabulary: Vocabulary) -> None:
        self._vocabulary = vocabulary

    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> CollectResult:
        entities: list[Entity] = []
        candidates: list[Candidate] = []
        diagnostics: list[str] = []
        for platform, answer in _answers(page, diagnostics):
            shape = answer_shape(platform, answer, ctx.page_url)
            shapes = () if shape is None else (shape,)
            read = read_shapes(f"{platform}_json", shapes, answer, schema, ctx, self._vocabulary)
            entities.extend(_requested(e) for e in read.entities)
            candidates.extend(read.candidates)
            diagnostics.extend(read.diagnostics)
        return CollectResult(entities=tuple(entities), candidates=tuple(candidates), diagnostics=tuple(diagnostics))


def _requested(entity: Entity) -> Entity:
    """The answer's root marked as the requested item: the answer passed the identity check (`acquire.identity`)."""
    return entity.model_copy(update={"requested": True}) if entity.parent is None else entity


def _answers(page: ParsedPage, diagnostics: list[str]) -> Iterator[tuple[str, JsonValue]]:
    if len(page.network_entries) != len(page.network):
        return
    for index in sorted(data_call_bodies(page)):
        platform = page.network_entries[index].data_call
        if platform == ADAPTER_CALL or recipe_mark(platform):
            continue  # an adapter's answer, which its adapter's shapes read (`collect.run`), or a recipe's, its map's
        try:
            answer = network_json(page.network[index])
        except ValueError as e:
            diagnostics.append(f"{platform}_json:{index}: not UTF-8 JSON ({e})")
            continue
        if platform is not None:
            yield platform, answer
