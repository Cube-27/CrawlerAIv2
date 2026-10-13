"""The engine the replay harness runs (SPEC-03 §4.5, SPEC-05 §7, G7): `resolve.pipeline.extract_page`, the function
the worker runs, with the engine's data and the schemas of the split's pages. A page with its site's config snapshot
runs that config through the engine executor (`config` mode, SPEC-08 §4.8)."""

from collections.abc import Mapping
from dataclasses import dataclass

from crawlerai.config_ir.executor import EngineExecutor
from crawlerai.config_ir.role_c import role_c
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
        executor = None
        if config is not None:
            executor = EngineExecutor(config.ir, self.data.vocabulary)
        if (executor is None) != (mode == "adhoc"):
            raise ValueError(f"{mode} mode with{'out' if executor is None else ''} a config")
        # Role C reads `llm`, the harness's `RecordedLLM`; a replay is charged to no job.
        return await extract_page(bundle, schema, executor, role_c(llm, job_id=None), data=self.data)
