"""The SDKs match the API document they were generated from (`tools/sdk_digest.py`)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdk_digest import DIGEST, current


def test_the_sdks_were_generated_from_the_current_openapi_document() -> None:
    recorded = DIGEST.read_text(encoding="utf-8").strip()

    assert recorded == current(), "frontend/openapi.json changed: run `make api-client`, then `make sdk`"
