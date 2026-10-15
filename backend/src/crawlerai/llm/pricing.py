"""LLM prices (SPEC-06 §4.8): what a provider charges per million input and output tokens of a model, for the
estimated LLM cost shown for visibility. It is not billing (ARCHITECTURE §1, Appendix A #2).

Prices are versioned external data (C4): one file per provider under `backend/data/llm/`, pinned in the data
manifest with the pricing page it was transcribed from; the file holds the date it was checked. A price applies from its
`effective_from` date to its `effective_until` date (exclusive; UTC dates), and, for a model priced by prompt length,
to calls whose input tokens are within its `[min_prompt_tokens, max_prompt_tokens]`. A call no price applies to has
no cost estimate: no default price, no nearest model, no earlier price carried back (C7).
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import cache
from itertools import combinations
from pathlib import Path
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from crawlerai.core.engine_version import data_dir, engine_dir

# The price lists the engine reads, one per provider (`backend/data/manifest.json`).
PRICE_FILES: Final = (Path("llm") / "anthropic-pricing.json", Path("llm") / "gemini-pricing.json")
TOKENS_PER_PRICE_UNIT: Final = 1_000_000  # prices are per million tokens ("MTok"), as both providers quote them


class OverlappingPrices(ValueError):
    """Two prices of one model could both apply to the same call."""


class _Row(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str = Field(min_length=1)
    effective_from: date
    effective_until: date | None
    min_prompt_tokens: int = Field(ge=0)
    max_prompt_tokens: int | None
    input_usd_per_mtok: Decimal = Field(ge=0)
    output_usd_per_mtok: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def _ranges(self) -> Self:
        if self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValueError("effective_until must be after effective_from")
        if self.max_prompt_tokens is not None and self.max_prompt_tokens < self.min_prompt_tokens:
            raise ValueError("max_prompt_tokens must not be below min_prompt_tokens")
        return self


class PriceList(BaseModel):
    """One provider's price file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(min_length=1)
    currency: Literal["USD"]
    checked: date
    scope: str
    prices: list[_Row]


class Price(_Row):
    provider: str

    def overlaps(self, other: "Price") -> bool:
        """Whether both prices could apply to one call: same provider and model, shared dates and prompt lengths."""
        if (self.provider, self.model) != (other.provider, other.model):
            return False
        ends = [d for d in (self.effective_until, other.effective_until) if d is not None]
        dates_shared = max(self.effective_from, other.effective_from) < min(ends, default=date.max)
        uppers = [n for n in (self.max_prompt_tokens, other.max_prompt_tokens) if n is not None]
        lengths_shared = max(self.min_prompt_tokens, other.min_prompt_tokens) <= min(uppers, default=2**63 - 1)
        return dates_shared and lengths_shared


@dataclass(frozen=True)
class Pricing:
    """Every known price; at most one applies to any call (`of` refuses lists where two could). The matching rule
    itself is SQL, where the calls are (`crawlerai.services.llm_costs`)."""

    prices: tuple[Price, ...]

    @classmethod
    def of(cls, lists: Iterable[PriceList]) -> Self:
        prices = tuple(
            Price(provider=price_list.provider, **row.model_dump()) for price_list in lists for row in price_list.prices
        )
        for a, b in combinations(prices, 2):
            if a.overlaps(b):
                raise OverlappingPrices(f"{a.provider} {a.model}: two prices apply to the same calls")
        return cls(prices)

    @classmethod
    def read(cls, directory: Path) -> Self:
        """The price lists of `PRICE_FILES` under the data directory `directory`."""
        lists = [
            PriceList.model_validate(json.loads((directory / name).read_text(encoding="utf-8"))) for name in PRICE_FILES
        ]
        return cls.of(lists)


@cache
def default_pricing() -> Pricing:
    """The prices in the engine directory's `data/`, read once. Without an engine directory there are no prices and
    every cost is unknown, never guessed."""
    engine = engine_dir(Path(__file__))
    return Pricing(()) if engine is None else Pricing.read(data_dir(engine))
