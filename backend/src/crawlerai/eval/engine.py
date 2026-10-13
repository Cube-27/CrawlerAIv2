"""The engine the replay harness runs (SPEC-03 §4.5, SPEC-05 §7, G7): `resolve.pipeline.extract_page`, the function
the worker runs, with the engine's data and the schemas of the split's pages."""

from collections.abc import Mapping
from dataclasses import dataclass

from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.db.models import ExtractionMode
from crawlerai.eval.replay import ConfigSnapshot
from crawlerai.llm.client import LLMClient
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle


@dataclass(frozen=True)
class PipelineEngine:
    data: EngineData
    schemas: Mapping[str, SchemaDef]  # by name
    version: str = ENGINE_VERSION

    def schema(self, name: str) -> SchemaDef:
        try:
            return self.schemas[name]
        except KeyError:
            raise LookupError(f"no schema named {name!r}") from None

    async def replay_page(
        self,
        bundle: CaptureBundle,
        schema: SchemaDef,
        config: ConfigSnapshot | None,
        llm: LLMClient,
        mode: ExtractionMode,
    ) -> ExtractionResult:
        # Role C reads `llm` once SPEC-06 PR 4 binds it; until then the gap-filling hook is empty (§4.13).
        return await extract_page(bundle, schema, config, None, mode, data=self.data)
