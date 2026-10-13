"""Properties of the hidden rotation's choice of sites (ARCHITECTURE §16.1, SPEC-03 §4.4): within each category it
takes the fraction of sites, rounded half up, and only sites that exist; a seed fixes the choice."""

import copy
import math
import random
from collections import Counter
from typing import get_args

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.db.models import EvalCategory
from crawlerai.eval.promote import choose_sites

_sites = st.dictionaries(
    st.from_regex(r"[a-z]{1,8}\.example\.test", fullmatch=True), st.sampled_from(get_args(EvalCategory)), max_size=40
)
_fractions = st.floats(min_value=0.01, max_value=0.99)


@given(_sites, _fractions, st.randoms())
def test_each_category_gives_its_fraction_of_sites(
    sites: dict[str, EvalCategory], fraction: float, rng: random.Random
) -> None:
    chosen = choose_sites(sites, fraction, rng)

    assert chosen <= sites.keys()
    per_category = Counter(sites.values())
    chosen_per_category = Counter(sites[host] for host in chosen)
    assert {c: chosen_per_category[c] for c in per_category} == {
        c: math.floor(fraction * n + 0.5) for c, n in per_category.items()
    }


@given(_sites, _fractions, st.randoms(use_true_random=False))
def test_a_seed_fixes_the_choice_whatever_the_order_sites_are_read_in(
    sites: dict[str, EvalCategory], fraction: float, rng: random.Random
) -> None:
    same_seed = copy.deepcopy(rng)

    assert choose_sites(sites, fraction, rng) == choose_sites(dict(reversed(sites.items())), fraction, same_seed)


def test_a_third_of_three_sites_is_one() -> None:
    sites: dict[str, EvalCategory] = {"a.example.test": "mixed", "b.example.test": "mixed", "c.example.test": "mixed"}

    assert len(choose_sites(sites, 0.33)) == 1


@pytest.mark.parametrize("fraction", [0.0, 1.0, -0.5, 1.5])
def test_a_fraction_outside_zero_to_one_is_refused(fraction: float) -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        choose_sites({"a.example.test": "mixed"}, fraction)
