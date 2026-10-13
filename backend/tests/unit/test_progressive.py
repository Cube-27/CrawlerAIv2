from typing import get_args

import pytest

from crawlerai.config_ir.progressive import LearnEvent, next_mode
from crawlerai.db.models import ProgressiveMode

# Every (mode, event) pair: the mode it leads to, or None where the event is refused (SPEC-08 §4.4, §4.8, §4.10).
EXPECTED: dict[tuple[ProgressiveMode, LearnEvent], ProgressiveMode | None] = {
    ("cold", "start"): "learning",
    ("cold", "start_forced"): "learning",
    ("cold", "activate"): None,
    ("cold", "fail"): None,
    ("cold", "operator"): "active",
    ("learning", "start"): None,
    ("learning", "start_forced"): None,
    ("learning", "activate"): "active",
    ("learning", "fail"): "cold",
    ("learning", "operator"): "active",
    ("active", "start"): None,
    ("active", "start_forced"): "active",
    ("active", "activate"): "active",
    ("active", "fail"): "active",
    ("active", "operator"): "active",
}


def test_the_table_covers_every_mode_and_event() -> None:
    assert set(EXPECTED) == {(mode, event) for mode in get_args(ProgressiveMode) for event in get_args(LearnEvent)}


@pytest.mark.parametrize(("mode", "event"), list(EXPECTED))
def test_transitions(mode: ProgressiveMode, event: LearnEvent) -> None:
    assert next_mode(mode, event) == EXPECTED[mode, event]
