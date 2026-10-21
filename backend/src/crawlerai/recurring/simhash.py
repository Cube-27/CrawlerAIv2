"""The content fingerprint of a page (jobs spec): the exact digest of its visible words, which says whether a page's
text changed between runs, and a 64-bit SimHash of them, which says how far a changed page moved.

Only an equal digest is no change (owner #40, D-1340): SimHash flips a bit only where a vote total was near zero, so an
equal SimHash does not bound the change (a one-word edit of a 500-word text keeps it on about 1 in 10 texts, D-0915).
Both read the same words (`words`), so both ignore what changes on every load without the page changing: nonce-like
tokens and whitespace.

SimHash (Charikar, "Similarity estimation techniques from rounding algorithms", STOC 2002) sums, bit by bit, the
±1 votes of a hash of each feature; near-identical texts get fingerprints a few bits apart. The features are word
3-gram shingles, hashed with BLAKE2b at an 8-byte digest (RFC 7693), which is fixed across processes and versions,
unlike Python's `hash`.
"""

import re
from dataclasses import dataclass
from hashlib import blake2b

__all__ = ["BITS", "ContentFingerprint", "content_digest", "content_fingerprint", "hamming", "simhash64", "words"]

BITS = 64
_SHINGLE = 3
# A nonce, session id or cache-busting token, defined structurally (jobs spec): at least 16 characters, all from
# the URL- and filename-safe base64 alphabet (RFC 4648 §5). It changes on every load without the page changing.
_NONCE = re.compile(r"[A-Za-z0-9_-]{16,}")


def words(text: str) -> list[str]:
    """The text's words, split on whitespace (`str.split`: Unicode White_Space), without nonce-like tokens."""
    return [word for word in text.split() if not _NONCE.fullmatch(word)]


@dataclass(frozen=True, slots=True)
class ContentFingerprint:
    """A page's visible text as `recurring.state.record_content` compares it: the exact digest of its words, and their
    SimHash."""

    digest: str
    simhash: int


def content_fingerprint(text: str) -> ContentFingerprint | None:
    """`text`'s digest and SimHash; None for a text without words: it has nothing to fingerprint."""
    digest, simhash = content_digest(text), simhash64(text)
    return None if digest is None or simhash is None else ContentFingerprint(digest, simhash)


def content_digest(text: str) -> str | None:
    """The BLAKE2b digest (RFC 7693, 16 bytes, as lower-case hex) of `text`'s words joined by one space: equal exactly
    when the words are, whatever the whitespace between them. None for a text without words, as `simhash64`."""
    tokens = words(text)
    if not tokens:
        return None
    return blake2b(" ".join(tokens).encode(), digest_size=_DIGEST_BYTES).hexdigest()


# 128 bits: two different texts of one URL share a digest with a probability of about 2^-128.
_DIGEST_BYTES = 16


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
