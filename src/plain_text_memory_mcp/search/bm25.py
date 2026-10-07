"""Score texts against a query with Okapi BM25, in pure Python.

- Follows Robertson & Zaragoza, "The Probabilistic Relevance Framework:
  BM25 and Beyond" (2009), with the non-negative idf Lucene uses so a term
  found in most texts still scores above zero.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

K1 = 1.2
B = 0.75

# Letters and digits; underscores split, so reading_list is two words.
_WORD = re.compile(r"[^\W_]+")
# A query term is a "quoted phrase" or a run of non-space characters.
_QUERY_TERM = re.compile(r'"([^"]+)"|(\S+)')


@dataclass(frozen=True)
class Query:
    """Hold a parsed query: loose words and quoted phrases.

    - `words` are tokens; `phrases` are lowercased text matched as a whole.
    """

    words: tuple[str, ...]
    phrases: tuple[str, ...]

    def is_blank(self) -> bool:
        """Return whether the query has nothing to match."""
        return not self.words and not self.phrases


@dataclass(frozen=True)
class Bm25Index:
    """Hold the term statistics of a fixed list of texts."""

    texts: tuple[str, ...]
    term_counts: tuple[Counter[str], ...]
    lengths: tuple[int, ...]
    average_length: float
    text_counts: Counter[str]


def _stem(word: str) -> str:
    """Fold a plain plural onto its singular: tests -> test, not class."""
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def to_tokens(text: str) -> list[str]:
    """Return the lowercase, plural-folded words of `text`, in order."""
    return [_stem(word) for word in _WORD.findall(text.lower())]


def parse_query(query: str) -> Query:
    """Split a query into words and "quoted phrases", each kept once."""
    words: list[str] = []
    phrases: list[str] = []
    for phrase, word in _QUERY_TERM.findall(query):
        if phrase.strip():
            phrases.append(phrase.strip().lower())
        else:
            words.extend(to_tokens(word))
    return Query(tuple(dict.fromkeys(words)), tuple(dict.fromkeys(phrases)))


def build_index(texts: list[str]) -> Bm25Index:
    """Return the BM25 statistics for `texts`."""
    term_counts = tuple(Counter(to_tokens(text)) for text in texts)
    lengths = tuple(sum(counts.values()) for counts in term_counts)
    text_counts: Counter[str] = Counter()
    for counts in term_counts:
        text_counts.update(counts.keys())
    average = sum(lengths) / len(lengths) if lengths else 0.0
    return Bm25Index(
        tuple(text.lower() for text in texts),
        term_counts,
        lengths,
        average,
        text_counts,
    )


def _calc_idf(index: Bm25Index, term: str) -> float:
    total = len(index.texts)
    found = index.text_counts.get(term, 0)
    return math.log(1 + (total - found + 0.5) / (found + 0.5))


def _calc_term_score(index: Bm25Index, position: int, term: str) -> float:
    frequency = index.term_counts[position].get(term, 0)
    if not frequency:
        return 0.0
    length_ratio = index.lengths[position] / (index.average_length or 1.0)
    saturation = frequency + K1 * (1 - B + B * length_ratio)
    return _calc_idf(index, term) * frequency * (K1 + 1) / saturation


def calc_scores(index: Bm25Index, query: Query) -> list[float]:
    """Return each text's BM25 score for `query`, in index order.

    - A phrase scores its words only in texts that contain the whole phrase.
    """
    scores = []
    for position, text in enumerate(index.texts):
        terms = list(query.words)
        for phrase in query.phrases:
            if phrase in text:
                terms.extend(to_tokens(phrase))
        scores.append(
            sum(_calc_term_score(index, position, term) for term in terms)
        )
    return scores
