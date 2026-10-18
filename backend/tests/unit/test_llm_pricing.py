"""LLM prices (SPEC-06 §4.8): the shipped price lists, the one-price-per-call rule, and the lookup by provider, model,
date and prompt length. Models in the synthetic lists are made-up names."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from crawlerai.core.settings import LLMSettings
from crawlerai.llm.pricing import CacheTokens, OverlappingPrices, PriceList, Pricing

BACKEND = Path(__file__).resolve().parents[2]
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


def test_the_shipped_price_lists_price_every_default_model_of_the_settings() -> None:
    # Read from this source tree: CI installs the package as a wheel, which has no backend/data.
    shipped = Pricing.read(BACKEND / "data")
    fields = LLMSettings.model_fields
    defaults = {
        (provider, fields[f"llm_{model_class}_model_{provider}"].default)
        for provider in ("anthropic", "gemini")
        for model_class in ("fast", "strong")
    }
    checked = date(2026, 10, 14)
    priced = {
        (p.provider, p.model)
        for p in shipped.prices
        if p.min_prompt_tokens == 0
        and p.effective_from <= checked
        and (p.effective_until is None or checked < p.effective_until)
    }
    assert defaults - priced == set()


def test_a_price_change_and_prompt_length_tiers_that_meet_are_accepted() -> None:
    pricing = Pricing.of(
        [
            _list(
                _row("dated", effective_until=D2.isoformat()),
                _row("dated", effective_from=D2.isoformat(), input_usd_per_mtok="3"),
                _row("tiered", max_prompt_tokens=1000),
                _row("tiered", min_prompt_tokens=1001, input_usd_per_mtok="5"),
            )
        ]
    )
    assert [(p.model, p.input_usd_per_mtok) for p in pricing.prices] == [
        ("dated", Decimal(1)),
        ("dated", Decimal(3)),
        ("tiered", Decimal(1)),
        ("tiered", Decimal(5)),
    ]


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
    assert [(p.provider, p.input_usd_per_mtok) for p in both.prices] == [
        ("fakeai", Decimal(1)),
        ("otherai", Decimal(7)),
    ]


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


def test_a_call_is_priced_by_the_price_of_its_day_and_prompt_length() -> None:
    pricing = Pricing.of(
        [
            _list(
                _row("dated", effective_until=D2.isoformat()),
                _row("dated", effective_from=D2.isoformat(), input_usd_per_mtok="3"),
                _row("tiered", max_prompt_tokens=1000),
                _row("tiered", min_prompt_tokens=1001, input_usd_per_mtok="5"),
            )
        ]
    )

    assert pricing.call_usd("fakeai", "dated", 1_000_000, 500_000, D1) == Decimal(2)
    assert pricing.call_usd("fakeai", "dated", 1_000_000, 0, D2) == Decimal(3)
    assert pricing.call_usd("fakeai", "tiered", 2000, 0, D1) == Decimal("0.01")
    # Before any price, another provider, an unknown model: unpriced, never guessed.
    assert pricing.call_usd("fakeai", "dated", 10, 10, date(2029, 1, 1)) is None
    assert pricing.call_usd("otherai", "dated", 10, 10, D1) is None
    assert pricing.call_usd("fakeai", "unknown", 10, 10, D1) is None


def test_cache_tokens_are_priced_by_the_cache_prices_and_count_toward_the_prompt_tier() -> None:
    pricing = Pricing.of(
        [
            _list(
                _row(
                    "cached", cache_read_usd_per_mtok="0.1", cache_write_usd_per_mtok="1.25", max_prompt_tokens=10_000
                ),
                _row("cached", min_prompt_tokens=10_001, input_usd_per_mtok="9"),
                _row("uncached"),
            )
        ]
    )
    cache = CacheTokens(read=1_000_000, write=2_000_000)
    # 1,000 input tokens at 1 and 5,000 read at 0.1 per MTok; a prompt past the first tier has that tier's price, which
    # has no cache prices.
    assert pricing.call_usd("fakeai", "cached", 1_000, 0, D1, CacheTokens(read=5_000, write=0)) == Decimal("0.0015")
    assert pricing.call_usd("fakeai", "cached", 1_000_000, 0, D1, cache) is None
    # A price without cache prices leaves cache tokens unpriced; without cache tokens it prices as before.
    assert pricing.call_usd("fakeai", "uncached", 10, 10, D1, CacheTokens(read=1, write=0)) is None
    assert pricing.call_usd("fakeai", "uncached", 1_000_000, 0, D1, CacheTokens(0, 0)) == Decimal(1)


def test_the_shipped_anthropic_prices_have_cache_prices_of_a_tenth_and_one_and_a_quarter_of_the_input_price() -> None:
    shipped = Pricing.read(BACKEND / "data")
    for price in (p for p in shipped.prices if p.provider == "anthropic"):
        assert price.cache_read_usd_per_mtok == price.input_usd_per_mtok / 10
        assert price.cache_write_usd_per_mtok == price.input_usd_per_mtok * Decimal("1.25")
