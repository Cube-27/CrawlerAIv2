"""Okapi BM25 (Robertson and Zaragoza, "The Probabilistic Relevance Framework: BM25 and Beyond", 2009) over a few
texts: how relevant each is to a query. Words are the folded words of `strings.fold_words` (letters, marks and
digits, case folded); no stop-word list is applied (C4): a word every block holds scores low through its
inverse document frequency instead."""

import math
from collections import Counter

from snowcrawl.normalize.strings import fold_words

# The published defaults: k1 in [1.2, 2.0] and b = 0.75 (Robertson and Zaragoza §3.2).
_K1 = 1.2
_B = 0.75


def scores(query: str, texts: list[str]) -> list[float]:
    """The BM25 score of each of `texts` against `query`, with the non-negative inverse document frequency
    `ln(1 + (N - n + 0.5) / (n + 0.5))` Lucene uses; 0 for a text with no query word."""
    wanted = set(fold_words(query))
    documents = [Counter(fold_words(text)) for text in texts]
    if not wanted or not documents:
        return [0.0] * len(texts)
    lengths = [sum(document.values()) for document in documents]
    average = (sum(lengths) / len(lengths)) or 1.0
    holding = {word: sum(1 for document in documents if word in document) for word in wanted}
    out: list[float] = []
    for document, length in zip(documents, lengths, strict=True):
        score = 0.0
        for word in wanted:
            frequency = document.get(word, 0)
            if frequency:
                idf = math.log(1 + (len(documents) - holding[word] + 0.5) / (holding[word] + 0.5))
                score += idf * frequency * (_K1 + 1) / (frequency + _K1 * (1 - _B + _B * length / average))
        out.append(score)
    return out
