"""The SDKs are generated from `frontend/openapi.json`; `sdk/openapi.sha256` records which version of it they were
generated from, so a change to the API document that leaves the SDKs behind fails `tools/tests/test_sdk_digest.py`.

`python3 tools/sdk_digest.py` (run by `make sdk`, after the generators) writes the file; the test compares it.
"""

import hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OPENAPI = REPO / "frontend/openapi.json"
DIGEST = REPO / "sdk/openapi.sha256"


def current() -> str:
    """The SHA-256 (FIPS 180-4) of the API document, as hex."""
    return hashlib.sha256(OPENAPI.read_bytes()).hexdigest()


def main() -> None:
    DIGEST.write_text(current() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
