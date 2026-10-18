"""LLM prices (llm spec): the shipped price lists, the one-price-per-call rule, and the lookup by provider, model,
date and prompt length. Models in the synthetic lists are made-up names."""

from datetime import date
from decimal import Decimal
from typing import Any

from crawlerai.llm.pricing import CacheTokens, PriceList, Pricing

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
