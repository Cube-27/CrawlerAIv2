"""A value derived from a frozen model's fields, derived once per model (INV-26: a page read twice for the same work
is read once)."""

from collections.abc import Callable


def held[T](model: object, name: str, inputs: tuple[object, ...], derive: Callable[[], T]) -> T:
    """`derive()`, kept in `model`'s instance dict under `name` with the `inputs` it was derived from, and returned
    again while each input is the same object. A frozen model's copy (`model_copy`) copies that dict, so a copy that
    replaced an input derives its own; one that kept them shares the value."""
    kept = model.__dict__.get(name)
    if kept is not None and all(a is b for a, b in zip(kept[0], inputs, strict=True)):
        value: T = kept[1]
        return value
    value = derive()
    model.__dict__[name] = (inputs, value)
    return value
