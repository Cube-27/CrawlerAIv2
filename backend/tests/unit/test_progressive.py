from itertools import product
from typing import get_args

import pytest

from crawlerai.config_ir.progressive import LearnEvent, next_mode
from crawlerai.db.models import ProgressiveMode

# Every (mode, event) pair: the mode it leads to, or None where the event is refused (SPEC-08 §4.4, §4.8, §4.10;
# SPEC-04 §4.1).
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
    ("cold", "schema_edit"): "cold",
    ("learning", "schema_edit"): "cold",
    ("active", "schema_edit"): "cold",
}


# Parametrized over every (mode, event) pair the types allow, so a pair missing from EXPECTED fails with a KeyError.
@pytest.mark.parametrize(("mode", "event"), list(product(get_args(ProgressiveMode), get_args(LearnEvent))))
def test_transitions(mode: ProgressiveMode, event: LearnEvent) -> None:
    assert next_mode(mode, event) == EXPECTED[mode, event]
