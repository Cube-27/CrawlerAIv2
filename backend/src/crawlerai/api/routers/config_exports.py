"""`POST /v1/configs/{id}/export` (SPEC-08 §4.10, ARCHITECTURE §13.1): a config as `json` or `platform_draft`, with its
release check."""

from fastapi import APIRouter, Depends, Request

from crawlerai.api.auth import require_api_key
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.api.problems import not_found
from crawlerai.config_ir.exporters.configs import ConfigExport
from crawlerai.db.models import ExtractionConfigId
from crawlerai.schemas.registry import SchemaNotFound
from crawlerai.services import config_exports
from crawlerai.services.config_exports import ConfigNotFound, ExportRequest
from crawlerai.services.scrape import Fetching

router = APIRouter(
    prefix="/v1/configs",
    tags=["configs"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 404: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.post("/{config_id}/export")
async def export_config(config_id: ExtractionConfigId, body: ExportRequest, request: Request) -> ConfigExport:
    """The config as `json` (the IR as stored) or `platform_draft` (`draft: true` until the platform's format is known),
    and the release check on the pages the config was validated on: a field the independent release executor does not
    reproduce on every such page with an engine value while there are fewer than 10, or on 95% from 10 on, is
    `manual`."""
    fetching: Fetching = request.app.state.fetching
    try:
        return await config_exports.export(request.app.state.database, fetching.store, config_id, body.format)
    except (ConfigNotFound, SchemaNotFound) as e:
        raise not_found(str(e)) from e
