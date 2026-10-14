"""The content fingerprint of a page (SPEC-11 §4.3, ARCHITECTURE §14): a 64-bit SimHash of its visible text, so that a
page whose text barely moved between runs is `unchanged` and is not extracted again.

SimHash (Charikar, "Similarity estimation techniques from rounding algorithms", STOC 2002) sums, bit by bit, the
±1 votes of a hash of each feature; near-identical texts get fingerprints a few bits apart. The features are word
3-gram shingles, hashed with BLAKE2b at an 8-byte digest (RFC 7693), which is fixed across processes and versions,
unlike Python's `hash`.
"""

import re
from hashlib import blake2b

__all__ = ["BITS", "hamming", "simhash64", "words"]

BITS = 64
_SHINGLE = 3
# A nonce, session id or cache-busting token, defined structurally (SPEC-11 §4.3): at least 16 characters, all from
# the URL- and filename-safe base64 alphabet (RFC 4648 §5). It changes on every load without the page changing.
_NONCE = re.compile(r"[A-Za-z0-9_-]{16,}")


def words(text: str) -> list[str]:
    """The text's words, split on whitespace (`str.split`: Unicode White_Space), without nonce-like tokens."""
    return [word for word in text.split() if not _NONCE.fullmatch(word)]


def simhash64(text: str) -> int | None:
    """The SimHash of `text` over its word 3-grams; a text shorter than three words is one shingle of all its words.
    None for a text without words: it has nothing to fingerprint. Pure: the same text always gives the same value."""
    tokens = words(text)
    if not tokens:
        return None
    shingles = [" ".join(tokens[i : i + _SHINGLE]) for i in range(max(len(tokens) - _SHINGLE + 1, 1))]
    # Each hash as its bits, most significant first; a column of them is one bit position's votes.
    bits = [
        format(int.from_bytes(blake2b(s.encode(), digest_size=BITS // 8).digest(), "big"), f"0{BITS}b")
        for s in shingles
    ]
    fingerprint = 0
    for column in zip(*bits, strict=True):
        # The bit is set when more shingles set it than clear it; a tie clears it.
        fingerprint = fingerprint << 1 | (2 * column.count("1") > len(shingles))
    return fingerprint


def hamming(a: int, b: int) -> int:
    """How many bits two fingerprints differ in."""
    return (a ^ b).bit_count()
