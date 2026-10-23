"""A listing's row sources and the one rule picking its rows among them.

The sources, in precedence order: the rows structured data states (`resolve.listing`), the rows of the site's config,
the rows of the page's captured calls (`collect.xhr`) with the aligned groups of its repeated item blocks
(`collect.items.align`), and the rows of its state JSON (`collect.items.state_rows`). The first source that gives rows
gives the stated rows; the item blocks are the rows beside the stated rows (`collect.items.bind`) except beside a
config's alone, whose row selector was validated against every item. The state JSON's rows serve only where no other
source, item blocks included, gives any, and only then do their candidates join: so the state is read only where the
call rows and the item blocks are none (`RowSources.read`), as no source after them can take its place.

Structured data's rows need the page's entity graph, built from the collectors' entities and the config's rows, so
`collect` reads the sources it holds and resolution picks with the structured and config rows (`RowSources.pick`).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from crawlerai.collect.base import Candidate, Entity
from crawlerai.collect.items.align import Items
from crawlerai.collect.items.state_rows import StateRows


@dataclass(frozen=True, slots=True)
class Picked:
    """A listing's rows: its stated rows, the item groups bound to them, and the candidates that join only with these
    rows (the state JSON's)."""

    stated: tuple[Entity, ...] = ()
    items: tuple[Items, ...] = ()
    candidates: tuple[Candidate, ...] = ()


@dataclass(frozen=True, slots=True)
class RowSources:
    """The row sources `collect` reads (module docstring). The call rows' entities and candidates and the item groups'
    are among the collected ones; the state rows' entities too, their candidates only here."""

    calls: tuple[Entity, ...] = ()
    # The aligned groups of item blocks, best first.
    items: tuple[Items, ...] = ()
    state: StateRows = field(default_factory=StateRows)

    @classmethod
    def read(cls, calls: tuple[Entity, ...], items: tuple[Items, ...], state: Callable[[], StateRows]) -> "RowSources":
        """The sources, the state JSON's read only where the call rows and the item blocks are none."""
        return cls(calls, items, StateRows() if calls or items else state())

    def pick(self, structured: Sequence[Entity], config: Sequence[Entity]) -> Picked:
        """The listing's rows given the rows structured data and the config state (module docstring)."""
        if structured:
            return Picked(tuple(structured), self.items)
        if config:
            return Picked(tuple(config))
        if self.calls or self.items:
            return Picked(self.calls, self.items)
        return Picked(self.state.rows, (), self.state.candidates if self.state.rows else ())
