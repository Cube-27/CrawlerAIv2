"""LLM prices (llm spec): the shipped price lists, the one-price-per-call rule, and the lookup by provider, model,
date and prompt length. Models in the synthetic lists are made-up names."""

from datetime import date
from decimal import Decimal
from typing import Any

from crawlerai.llm.pricing import PriceList, Pricing

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
