"""Find notes that reword one already saved.

- Measures resemblance as Broder does ("On the resemblance and containment
  of documents", 1997): the Jaccard overlap of two texts' shingle sets.
  Notes are one sentence, so the shingles are single words and word
  pairs together; pairs keep word order from counting for nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from plain_text_memory_mcp import graph
from plain_text_memory_mcp.graph import Graph
from plain_text_memory_mcp.search import bm25

THRESHOLD = 0.6


@dataclass(frozen=True)
class NearDuplicate:
    """Hold the saved note most like a new text."""

    entity_name: str
    text: str
    resemblance: float


def _build_shingles(text: str) -> set[tuple[str, ...]]:
    words = bm25.to_tokens(text)
    return {(word,) for word in words} | set(pairwise(words))


def calc_resemblance(first: str, second: str) -> float:
    """Return the Jaccard overlap, 0 to 1, of two texts' shingles."""
    a, b = _build_shingles(first), _build_shingles(second)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def look_near_duplicate(
    memory: Graph, entity_name: str, text: str
) -> NearDuplicate | None:
    """Return the current note most like `text`, if close enough.

    - Searches every entity; the exact same text on the same entity is not
      a near-duplicate of itself.
    - Returns None when nothing reaches `THRESHOLD`.
    """
    best: NearDuplicate | None = None
    for entity in memory.entities:
        for note in entity.notes:
            if not graph.is_current(note):
                continue
            if entity.name == entity_name and note.text == text:
                continue
            score = calc_resemblance(text, note.text)
            if score >= THRESHOLD and (
                best is None or score > best.resemblance
            ):
                best = NearDuplicate(entity.name, note.text, score)
    return best
