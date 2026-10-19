"""The documented platform JSON collector (extraction spec, acquisition spec "Data calls"): the product JSON a platform
documents, fetched beside a detail page's HTTP fetch and kept only when it stated the requested product
(`acquire.identity`), read as the schema.org nodes the platform's documentation says it holds
(`adapters.platforms.answer_shapes`).

Such a body is structured evidence of the requested product, as an adapter's answer is: its values are `adapter`
candidates read by the schema.org path rules (`read_shapes` of `collect/adapter.py`), located under `<platform>_json`,
not admitted by the equality-or-visibility rule the captured network JSON of unknown keys takes (`collect.admission`),
which never reads these bodies. Every other network body keeps that rule.
"""

from collections.abc import Iterator

from pydantic import JsonValue

from crawlerai.adapters.platforms import answer_shapes
from crawlerai.collect.adapter import read_shapes
from crawlerai.collect.base import Candidate, CollectResult, Entity
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.capture_bundle import network_json

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
            read = read_shapes(
                f"{platform}_json", answer_shapes(platform, answer), answer, schema, ctx, self._vocabulary
            )
            entities.extend(read.entities)
            candidates.extend(read.candidates)
            diagnostics.extend(read.diagnostics)
        return CollectResult(entities=tuple(entities), candidates=tuple(candidates), diagnostics=tuple(diagnostics))


def _answers(page: ParsedPage, diagnostics: list[str]) -> Iterator[tuple[str, JsonValue]]:
    if len(page.network_entries) != len(page.network):
        return
    for index in sorted(data_call_bodies(page)):
        platform = page.network_entries[index].data_call
        try:
            answer = network_json(page.network[index])
        except ValueError as e:
            diagnostics.append(f"{platform}_json:{index}: not UTF-8 JSON ({e})")
            continue
        if platform is not None:
            yield platform, answer
