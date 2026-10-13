"""Config exports (SPEC-08 §4.10, §4.11): a config in `json` (the IR as stored) or `platform_draft`, with the release
check (§12.3) of the steps the export carries, run on the held-out pages."""

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from crawlerai.config_ir.exporters.platform_draft import PlatformDraft, as_xpath, platform_draft
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
    if fmt == "json":
        return ConfigExport(format=fmt, export=ir, release=release_check(ir, schema, held_out))
    steps = as_xpath(ir)
    report = release_check(steps, schema, held_out)
    return ConfigExport(format=fmt, export=platform_draft(steps, report), release=report)
