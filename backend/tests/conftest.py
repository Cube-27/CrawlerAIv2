"""Hypothesis profiles: CI runs every property test with a fixed `max_examples=200` (SPEC-04 §6); local runs keep
the Hypothesis default. GitHub Actions sets `CI`."""

import os

from hypothesis import settings

settings.register_profile("ci", max_examples=200)
settings.load_profile("ci" if os.environ.get("CI") else "default")
