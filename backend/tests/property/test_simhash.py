"""The content fingerprint (SPEC-11 §4.3, §6): the exact digest of the visible words, which every edit changes, and a
pure SimHash-64 over their 3-grams, close for a one-word edit and far for another text; both blind to whitespace layout
and to nonce-like tokens."""

import string
from hashlib import blake2b

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.recurring.simhash import BITS, content_digest, content_fingerprint, hamming, simhash64, words

# Unicode White_Space characters `str.split` splits on: space, tab, LF, CR, VT, FF, no-break, em and ideographic space.
_SPACES = "".join(map(chr, (0x20, 0x09, 0x0A, 0x0D, 0x0B, 0x0C, 0xA0, 0x2003, 0x3000)))

_word = st.from_regex(r"[a-z]{1,12}", fullmatch=True)
_text = st.lists(_word, min_size=1, max_size=60)
_space = st.text(alphabet=_SPACES, min_size=1, max_size=4)
_nonce = st.from_regex(r"[A-Za-z0-9_-]{16,40}", fullmatch=True)
_fingerprint = st.integers(min_value=0, max_value=2**BITS - 1)


@given(_text, st.data())
def test_whitespace_layout_does_not_change_the_fingerprint(tokens: list[str], data: st.DataObject) -> None:
    spaced = "".join(word + data.draw(_space) for word in tokens)

    assert simhash64(spaced) == simhash64(" ".join(tokens))


@given(_text, st.data())
def test_nonce_like_tokens_do_not_change_the_fingerprint(tokens: list[str], data: st.DataObject) -> None:
    with_nonces = [part for word in tokens for part in (word, *data.draw(st.lists(_nonce, max_size=2)))]

    assert simhash64(" ".join(with_nonces)) == simhash64(" ".join(tokens))


def test_the_nonce_rule_is_structural() -> None:
    kept = ["abcdefghijklmno", "abcdefghijklmnop.html", "naïve-fingerprinting", "1234567890123,45"]
    dropped = ["abcdefghijklmnop", "a1B2-c3D4_e5F6g7H8", "0123456789abcdef0123"]

    # 15 characters, a dot, a letter outside ASCII and a comma all keep a token; 16 or more of [A-Za-z0-9_-] drop it.
    assert words(" ".join(kept + dropped)) == kept


@given(st.text(alphabet=_SPACES, max_size=10))
def test_a_text_without_words_has_no_fingerprint(text: str) -> None:
    assert simhash64(text) is None
    assert simhash64(f"{text}abcdefghijklmnopqrstuvwxyz{text}") is None


def _blake2b64(text: str) -> int:
    return int.from_bytes(blake2b(text.encode(), digest_size=8).digest(), "big")


def test_a_text_of_one_shingle_is_that_shingles_hash() -> None:
    # Every bit gets one vote, so the fingerprint is the shingle's own BLAKE2b-64.
    assert simhash64(f"blue{_SPACES}steel  kettle") == _blake2b64("blue steel kettle")
    assert simhash64("blue kettle") == _blake2b64("blue kettle")


@given(_fingerprint, _fingerprint, _fingerprint)
def test_hamming_is_a_metric_on_64_bits(a: int, b: int, c: int) -> None:
    assert hamming(a, a) == 0
    assert hamming(a, b) == hamming(b, a) <= BITS
    assert hamming(a, c) <= hamming(a, b) + hamming(b, c)
    assert (hamming(a, b) == 0) == (a == b)


def _prose(seed: int, length: int = 500) -> list[str]:
    """`length` synthetic words of 2 to 9 letters, the same on every run and platform."""
    prose = []
    for i in range(length):
        digest = blake2b(f"{seed}/{i}".encode(), digest_size=10).digest()
        prose.append("".join(string.ascii_lowercase[byte % 26] for byte in digest[: 2 + digest[-1] % 8]))
    return prose


def _fingerprint_of(prose: list[str]) -> int:
    fingerprint = simhash64(" ".join(prose))
    assert fingerprint is not None
    return fingerprint


def test_every_one_word_edit_of_a_500_word_text_is_a_change() -> None:
    distances = []
    for seed in range(100):
        prose = _prose(seed)
        edited = list(prose)
        edited[_blake2b64(str(seed)) % len(prose)] = "kettle"
        distances.append(hamming(_fingerprint_of(prose), _fingerprint_of(edited)))
        # Only an equal digest is unchanged (§4.3, D-1340): every edit is seen.
        assert content_digest(" ".join(prose)) != content_digest(" ".join(edited))

    # SimHash alone would miss some (D-0915): a one-word edit changes 3 of 498 shingles, and a bit flips only where its
    # vote total was that close to zero.
    assert min(distances) == 0


@given(_text, st.lists(_space, min_size=1), _nonce)
def test_the_digest_ignores_whitespace_and_nonces_as_simhash_does(
    tokens: list[str], spaces: list[str], nonce: str
) -> None:
    spaced = "".join(token + spaces[i % len(spaces)] for i, token in enumerate(tokens))
    with_nonces = [part for token in tokens for part in (token, nonce)]

    assert content_digest(spaced) == content_digest(" ".join(tokens)) == content_digest(" ".join(with_nonces))
    assert content_fingerprint(spaced) == content_fingerprint(" ".join(tokens))


def test_a_text_without_words_has_no_digest() -> None:
    assert content_digest(" \n ") is None
    assert content_fingerprint("AbCdEfGhIjKlMnOpQrStUv_-12") is None


def test_another_text_is_far() -> None:
    for seed in range(100):
        assert hamming(_fingerprint_of(_prose(seed)), _fingerprint_of(_prose(seed + 10_000))) > 3
