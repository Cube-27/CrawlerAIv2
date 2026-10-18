"""Config exports (learning-configs spec): a config in `json` (the IR as stored) or `platform_draft`, with the release
check (§12.3) run on the held-out pages."""

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from crawlerai.config_ir.exporters.platform_draft import PlatformDraft, platform_draft
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.config_ir.release_check import ReleaseReport, release_check
from crawlerai.config_ir.validation import HeldOutPage
from crawlerai.schemas.types import SchemaDef

ConfigFormat = Literal["json", "platform_draft"]


class ConfigExport(BaseModel):
    """`export` is the IR for `json` and the draft for `platform_draft`; `release` says which fields are `manual`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    format: ConfigFormat
    export: ExtractionConfigIR | PlatformDraft
    release: ReleaseReport


def export_config(
    fmt: ConfigFormat, ir: ExtractionConfigIR, schema: SchemaDef, held_out: Sequence[HeldOutPage]
) -> ConfigExport:
    report = release_check(ir, schema, held_out)
    export = ir if fmt == "json" else platform_draft(ir, report)
    return ConfigExport(format=fmt, export=export, release=report)
