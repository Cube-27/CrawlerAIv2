"""A listing's row sources over every combination of sources giving rows or none (`collect.row_sources`): the stated
rows are the first source's in precedence order that gives any; the item groups bind beside every stated rows but a
config's alone; the state JSON is read only where the call rows and the item groups are none, and its rows and their
candidates serve only where no other source gives any. Entities are synthetic (C3)."""

from hypothesis import given
from hypothesis import strategies as st

from snowcrawl.collect.base import ARRAY_ROW, Candidate, Entity
from snowcrawl.collect.items.align import Items
from snowcrawl.collect.items.state_rows import StateRows
from snowcrawl.collect.row_sources import RowSources
from snowcrawl.normalize.base import Ok


def _rows(kind: str, count: int) -> tuple[Entity, ...]:
    return tuple(Entity(id=f"{kind}:{n}", types=(ARRAY_ROW,), urls=(), parent=None) for n in range(count))


def _state(count: int) -> StateRows:
    rows = _rows("js_state", count)
    candidates = tuple(
        Candidate(
            field="url",
            entity_id=row.id,
            source_kind="js_state",
            raw=f"https://example.test/i/{n}",
            normalized=Ok(f"https://example.test/i/{n}"),
            locator=f"js_state:/html[1]/head[1]/script[1]:$[{n}]['url']",
            independent=True,
        )
        for n, row in enumerate(rows)
    )
    return StateRows(rows, candidates)


_COUNTS = st.integers(min_value=0, max_value=3)


@given(structured=_COUNTS, config=_COUNTS, calls=_COUNTS, groups=_COUNTS, state=_COUNTS)
def test_the_first_source_giving_rows_is_the_stated_rows(
    structured: int, config: int, calls: int, groups: int, state: int
) -> None:
    read: list[StateRows] = []

    def state_rows() -> StateRows:
        read.append(_state(state))
        return read[-1]

    items = tuple(Items(diagnostics=(f"group {n}",)) for n in range(groups))
    sources = RowSources.read(_rows("xhr", calls), items, state_rows)
    picked = sources.pick(_rows("jsonld", structured), _rows("config", config))

    assert bool(read) == (not calls and not groups)
    order = [_rows("jsonld", structured), _rows("config", config), _rows("xhr", calls)]
    if not items:
        order.append(_rows("js_state", state) if read else ())
    assert picked.stated == next((rows for rows in order if rows), ())
    assert picked.items == (() if config and not structured else items)
    state_won = bool(picked.stated) and picked.stated == _rows("js_state", state)
    assert picked.candidates == (_state(state).candidates if state_won else ())
