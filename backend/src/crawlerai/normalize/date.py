"""Date and datetime normalizer (SPEC-04 §4.4).

Only the `equal` hook exists yet (SPEC-03 PR 2); SPEC-04 PR 5 adds `normalize`.
"""

from pydantic import JsonValue


def equal(a: JsonValue, b: JsonValue) -> bool:
    """Stub until SPEC-04 PR 9 implements §4.5 (exact).

    Exact equality of two normalized values, which labels and engine output both hold (SPEC-03 §4.3).
    """
    return a == b
