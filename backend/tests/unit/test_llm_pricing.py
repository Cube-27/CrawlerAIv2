"""LLM prices (SPEC-06 §4.8): the shipped price lists, the one-price-per-call rule, and the lookup by provider, model,
date and prompt length. Models in the synthetic lists are made-up names."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from crawlerai.core.engine_version import backend_dir, data_dir
from crawlerai.core.settings import LLMSettings
from crawlerai.llm import pricing as pricing_module
from crawlerai.llm.pricing import OverlappingPrices, PriceList, Pricing

D1 = date(2030, 1, 1)
D2 = date(2030, 6, 1)


def _row(model: str, **fields: Any) -> dict[str, Any]:
    return {
        "model": model,
        "effective_from": D1.isoformat(),
        "effective_until": None,
        "min_prompt_tokens": 0,
        "max_prompt_tokens": None,
        "input_usd_per_mtok": "1",
        "output_usd_per_mtok": "2",
    } | fields


def _list(*rows: dict[str, Any], provider: str = "fakeai") -> PriceList:
    return PriceList.model_validate(
        {
            "provider": provider,
            "currency": "USD",
            "checked": D1.isoformat(),
            "scope": "synthetic",
            "prices": list(rows),
        }
    )


# A model whose price changes on D2, and one priced by prompt length (up to 1000 tokens, then over).
SYNTHETIC = Pricing.of(
    [
        _list(
            _row("dated", effective_until=D2.isoformat()),
            _row("dated", effective_from=D2.isoformat(), input_usd_per_mtok="3", output_usd_per_mtok="6"),
            _row("tiered", max_prompt_tokens=1000),
            _row("tiered", min_prompt_tokens=1001, input_usd_per_mtok="5", output_usd_per_mtok="10"),
        )
    ]
)


def test_the_shipped_price_lists_price_every_default_model_of_the_settings() -> None:
    backend = backend_dir(Path(pricing_module.__file__))
    assert backend is not None
    shipped = Pricing.read(data_dir(backend))
    settings = LLMSettings()
    defaults = {
        ("anthropic", settings.llm_fast_model_anthropic),
        ("anthropic", settings.llm_strong_model_anthropic),
        ("gemini", settings.llm_fast_model_gemini),
        ("gemini", settings.llm_strong_model_gemini),
    }
    checked = date(2026, 10, 14)
    assert {(p, m) for p, m in defaults if shipped.price(p, m, checked, prompt_tokens=1) is None} == set()


def test_a_price_is_found_by_provider_model_date_and_prompt_length() -> None:
    assert SYNTHETIC.price("fakeai", "dated", D1, prompt_tokens=10) is not None
    found = SYNTHETIC.price("fakeai", "dated", D2, prompt_tokens=10)
    assert found is not None
    assert (found.input_usd_per_mtok, found.output_usd_per_mtok) == (Decimal(3), Decimal(6))
    over = SYNTHETIC.price("fakeai", "tiered", D1, prompt_tokens=1001)
    assert over is not None
    assert over.input_usd_per_mtok == Decimal(5)
    up_to = SYNTHETIC.price("fakeai", "tiered", D1, prompt_tokens=1000)
    assert up_to is not None
    assert up_to.input_usd_per_mtok == Decimal(1)


def test_there_is_no_price_for_an_unknown_model_provider_or_date() -> None:
    assert SYNTHETIC.price("fakeai", "unlisted", D1, prompt_tokens=1) is None
    assert SYNTHETIC.price("otherai", "dated", D1, prompt_tokens=1) is None
    # Before the first effective date nothing was checked, so nothing is assumed (C7).
    assert SYNTHETIC.price("fakeai", "dated", date(2029, 12, 31), prompt_tokens=1) is None


def test_a_tiered_price_needs_the_prompt_length() -> None:
    assert SYNTHETIC.price("fakeai", "tiered", D1, prompt_tokens=None) is None
    assert SYNTHETIC.price("fakeai", "dated", D1, prompt_tokens=None) is not None


@given(st.dates(min_value=D1, max_value=date(2040, 1, 1)), st.integers(min_value=0, max_value=10**7))
def test_every_call_after_the_first_date_has_exactly_one_price(on: date, prompt_tokens: int) -> None:
    for model in ("dated", "tiered"):
        assert len([p for p in SYNTHETIC.prices if p.model == model and p.applies(on, prompt_tokens)]) == 1


@pytest.mark.parametrize(
    "rows",
    [
        # Two prices for the same dates and prompt lengths.
        (_row("m"), _row("m", input_usd_per_mtok="9")),
        # Periods that overlap from D2 on.
        (_row("m"), _row("m", effective_from=D2.isoformat())),
        # Prompt-length tiers that share 1000.
        (_row("m", max_prompt_tokens=1000), _row("m", min_prompt_tokens=1000)),
    ],
)
def test_prices_that_could_both_apply_to_one_call_are_refused(rows: tuple[dict[str, Any], ...]) -> None:
    price_list = _list(*rows)
    with pytest.raises(OverlappingPrices):
        Pricing.of([price_list])


def test_the_same_model_of_two_providers_is_two_prices() -> None:
    both = Pricing.of([_list(_row("m")), _list(_row("m", input_usd_per_mtok="7"), provider="otherai")])
    other = both.price("otherai", "m", D1, prompt_tokens=1)
    assert other is not None
    assert other.input_usd_per_mtok == Decimal(7)


@pytest.mark.parametrize(
    "fields",
    [
        {"input_usd_per_mtok": "-1"},
        {"effective_until": D1.isoformat()},
        {"min_prompt_tokens": 10, "max_prompt_tokens": 9},
    ],
)
def test_a_malformed_price_is_refused(fields: dict[str, Any]) -> None:
    row = _row("m", **fields)
    with pytest.raises(ValidationError):
        _list(row)
