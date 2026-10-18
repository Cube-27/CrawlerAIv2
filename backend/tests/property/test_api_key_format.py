"""API keys are `ck_` followed by 32 random bytes in base62 (SPEC-07 §4.2), and only their SHA-256 is stored."""

import string

from crawlerai.db.keys import generate_key, hash_key

BASE62 = set(string.digits + string.ascii_letters)


def test_a_generated_key_is_the_prefix_and_43_base62_digits() -> None:
    keys = {generate_key() for _ in range(50)}

    assert len(keys) == 50
    for key in keys:
        assert key.startswith("ck_")
        assert len(key) == 46
        assert set(key[3:]) <= BASE62


def test_the_hash_of_a_known_key() -> None:
    assert hash_key("ck_abc") == "ba922d62198a7dd6d28219d648822a23f8dbb379a5973e3ae35b94b30c66fbe5"
