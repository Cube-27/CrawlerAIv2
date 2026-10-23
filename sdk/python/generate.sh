#!/usr/bin/env bash
# Regenerates src/crawlerai_sdk/models.py from the API's OpenAPI document (frontend/openapi.json, which `uv run
# tools/dev.py api-client` writes), with the code generator the lock file pins. Run `uv run tools/dev.py sdk`.
set -euo pipefail
cd "$(dirname "$0")"
uv run --frozen --no-build --no-binary-package crawlerai-sdk --extra dev datamodel-codegen \
  --input ../../frontend/openapi.json --input-file-type openapi \
  --output-model-type pydantic_v2.BaseModel --output src/crawlerai_sdk/models.py \
  --use-annotated --use-standard-collections --use-union-operator --target-python-version 3.12 \
  --disable-timestamp --field-constraints --use-double-quotes
