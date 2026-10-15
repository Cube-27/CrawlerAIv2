"""API keys are `ck_` followed by 32 random bytes in base62 (SPEC-07 §4.2), and only their SHA-256 is stored."""

import string

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.services.keys import base62, generate_key, hash_key

BASE62 = string.digits + string.ascii_uppercase + string.ascii_lowercase


def _decode(digits: str) -> int:
    value = 0
    for digit in digits:
        value = value * 62 + BASE62.index(digit)
    return value


@given(st.binary(min_size=32, max_size=32))
def test_base62_is_43_digits_that_decode_to_the_bytes(raw: bytes) -> None:
    digits = base62(raw)

    assert len(digits) == 43  # 62**43 > 2**256, so every 32-byte value fits
    assert set(digits) <= set(BASE62)
    assert _decode(digits) == int.from_bytes(raw)


def test_a_generated_key_is_the_prefix_and_43_base62_digits() -> None:
    keys = {generate_key() for _ in range(100)}

    assert len(keys) == 100
    for key in keys:
        assert key.startswith("ck_")
        assert len(key) == 46
        assert set(key[3:]) <= set(BASE62)


def test_the_hash_of_a_known_key() -> None:
    assert hash_key("ck_abc") == "ba922d62198a7dd6d28219d648822a23f8dbb379a5973e3ae35b94b30c66fbe5"
