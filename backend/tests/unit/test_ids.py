import uuid

from snowcrawl.core.ids import uuid7


def test_uuid7_has_version_7_and_the_rfc_9562_variant() -> None:
    value = uuid7()

    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_uuid7_values_from_one_process_strictly_increase() -> None:
    values = [uuid7() for _ in range(10_000)]

    assert values == sorted(set(values))
