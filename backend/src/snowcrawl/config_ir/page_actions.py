"""Page actions as a caller writes them: the one vocabulary of browser steps a request names, translated into
the steps the browser rung runs (`acquire.types.PageStep`).

A step is an object with a `type` (`wait`, `click`, `scroll`, `press`, `type`) and its parameters. An element is named
as an IR step names one: a CSS `selector`, carried as its XPath 1.0 translation exactly as a
`css` step is (`model.CssStep`), or an `xpath` checked as XPath 1.0; a click may name the element by its visible `text`
instead. A request holds at most `MAX_ACTIONS` steps, each ending within its `timeout_ms`. `wait_for` is a wait step
written short: milliseconds, `network_idle`, or a CSS selector.
"""

from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Discriminator, Field, StringConstraints, model_validator

from snowcrawl.acquire.types import PageStep, ScrollMode
from snowcrawl.config_ir.model import CssStep, XPath1

__all__ = [
    "MAX_ACTIONS",
    "Action",
    "ClickAction",
    "PressAction",
    "ScrollAction",
    "TypeAction",
    "WaitAction",
    "WaitFor",
    "to_steps",
]

MAX_ACTIONS: Final = 20
# A step's own timeout, and the longest one; a wait of milliseconds lasts at most as long.
_DEFAULT_TIMEOUT_MS: Final = 5_000
_MAX_TIMEOUT_MS: Final = 15_000
NETWORK_IDLE: Final = "network_idle"
# UI Events KeyboardEvent `key` values (W3C UI Events Key Values), optionally with modifiers joined by `+`, as
# Playwright's keyboard press takes them: `Enter`, `PageDown`, `a`, `Control+A`.
_KEY: Final = r"^(?:(?:Shift|Control|Alt|Meta|ControlOrMeta)\+)*(?:[A-Za-z][A-Za-z0-9]*|\S)$"

Timeout = Annotated[int, Field(ge=1, le=_MAX_TIMEOUT_MS)]
Text = Annotated[str, StringConstraints(min_length=1, max_length=1_000)]


class _Action(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)

    timeout_ms: Timeout = _DEFAULT_TIMEOUT_MS


class _Targeted(_Action):
    """A step on an element: a CSS `selector` or an `xpath`."""

    selector: str | None = None
    xpath: XPath1 | None = None

    def element(self) -> str | None:
        """The element's XPath 1.0 expression: the selector's translation (as an IR `css` step's), or `xpath`."""
        if self.selector is not None:
            return CssStep.model_validate({"css": self.selector}).xpath
        return self.xpath

    def _one_target(self, *, text: str | None = None) -> None:
        named = [value for value in (self.selector, self.xpath, text) if value is not None]
        if len(named) != 1:
            raise ValueError(f"a {getattr(self, 'type', 'targeted')} step names one element")
        if self.selector is not None:
            self.element()  # raises for a selector cssselect does not translate


class WaitAction(_Targeted):
    """Wait `ms` milliseconds, for an element to be visible, or for the network to be idle (`network_idle`)."""

    type: Literal["wait"] = "wait"
    ms: Annotated[int, Field(ge=1, le=_MAX_TIMEOUT_MS)] | None = None
    network_idle: bool = False

    @model_validator(mode="after")
    def _one_kind(self) -> Self:
        kinds = [self.ms is not None, self.network_idle, self.selector is not None or self.xpath is not None]
        if sum(kinds) != 1:
            raise ValueError("a wait step waits for ms, network_idle, or one element")
        if kinds[2]:
            self._one_target()
        return self


class ClickAction(_Targeted):
    """Click an element, or the first visible element whose text holds `text`."""

    type: Literal["click"] = "click"
    text: Text | None = None

    @model_validator(mode="after")
    def _one(self) -> Self:
        self._one_target(text=self.text)
        return self


class ScrollAction(_Action):
    """Scroll to the end (`to: bottom`), by `by` CSS pixels, or until the document stops growing (`until: stable`)."""

    type: Literal["scroll"] = "scroll"
    to: Literal["bottom"] | None = None
    by: Annotated[int, Field(ge=-100_000, le=100_000)] | None = None
    until: Literal["stable"] | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> Self:
        if sum(value is not None for value in (self.to, self.by, self.until)) != 1:
            raise ValueError("a scroll step has one of to, by or until")
        return self


class PressAction(_Action):
    type: Literal["press"] = "press"
    key: Annotated[str, StringConstraints(pattern=_KEY)]


class TypeAction(_Targeted):
    """Type `text` into an element; refused in the browser for a password or credential field."""

    type: Literal["type"] = "type"
    text: Annotated[str, StringConstraints(max_length=1_000)]

    @model_validator(mode="after")
    def _one(self) -> Self:
        self._one_target()
        return self


Action = Annotated[WaitAction | ClickAction | ScrollAction | PressAction | TypeAction, Discriminator("type")]
# `wait_for`: milliseconds, `network_idle`, or a CSS selector.
WaitFor = Annotated[int, Field(ge=1, le=_MAX_TIMEOUT_MS)] | Annotated[str, StringConstraints(min_length=1)]


def wait_for_action(wait_for: WaitFor) -> WaitAction:
    """`wait_for` as the wait step it stands for. Raises `ValueError` for a selector cssselect does not translate."""
    if isinstance(wait_for, int):
        return WaitAction(ms=wait_for, timeout_ms=wait_for)
    if wait_for == NETWORK_IDLE:
        return WaitAction(network_idle=True)
    return WaitAction(selector=wait_for, timeout_ms=_MAX_TIMEOUT_MS)


def to_steps(actions: list[Action], wait_for: WaitFor | None = None) -> tuple[PageStep, ...]:
    """The browser steps for `wait_for` (first) and `actions`, in order."""
    written = ([] if wait_for is None else [wait_for_action(wait_for)]) + list(actions)
    return tuple(_step(action) for action in written)


def _step(action: WaitAction | ClickAction | ScrollAction | PressAction | TypeAction) -> PageStep:
    match action:
        case WaitAction():
            timeout = max(action.timeout_ms, action.ms or 0)
            return PageStep(
                action="wait",
                timeout_ms=timeout,
                xpath=action.element(),
                ms=action.ms,
                network_idle=action.network_idle,
            )
        case ClickAction():
            return PageStep(action="click", timeout_ms=action.timeout_ms, xpath=action.element(), text=action.text)
        case ScrollAction():
            mode: ScrollMode = "stable"
            if action.to is not None:
                mode = "end"
            elif action.by is not None:
                mode = "by"
            return PageStep(action="scroll", timeout_ms=action.timeout_ms, scroll=mode, px=action.by)
        case PressAction():
            return PageStep(action="press", timeout_ms=action.timeout_ms, key=action.key)
        case TypeAction():
            return PageStep(action="type", timeout_ms=action.timeout_ms, xpath=action.element(), text=action.text)
