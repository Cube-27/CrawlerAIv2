#!/usr/bin/env bash
# Regenerates src/crawlerai_sdk/models.py from the API's OpenAPI document (frontend/openapi.json, which `make
# api-client` writes). CI runs this and fails when the committed file differs.
set -euo pipefail
cd "$(dirname "$0")"
uvx --from "datamodel-code-generator==0.35.0" --with "black==26.10.1" --with "isort==6.1.0" datamodel-codegen \
  --input ../../frontend/openapi.json --input-file-type openapi \
  --output-model-type pydantic_v2.BaseModel --output src/crawlerai_sdk/models.py \
  --use-annotated --use-standard-collections --use-union-operator --target-python-version 3.12 \
  --disable-timestamp --field-constraints --use-double-quotes
