"""Rank entities and notes for a query, strongest at the edges.

- Every entity contributes two kinds of text to one BM25 index: its name
  and type, and each note on its own.
- A text's score is its BM25 score times one plus its activation prior, so
  relevance decides and recent or often-opened memories break near-ties.
- With a scope, notes from a memory file whose folder covers it score
  `SCOPE_BOOST` times higher. Root files cover every path, so they get no
  boost.
- Results are ordered for the reader, not the sorter: models use the start
  and end of a long context better than the middle (Liu et al., "Lost in
  the Middle", TACL 2024), so the strongest results go at both edges.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath

from plain_text_memory_mcp import graph
from plain_text_memory_mcp.graph import Access, Entity, Graph, Note
from plain_text_memory_mcp.search import activation, bm25, expansion

SCOPE_BOOST = 1.5


@dataclass(frozen=True)
class Hit:
    """Hold one matching note and its rank, 1 being the strongest."""

    entity_name: str
    note: Note
    score: float
    rank: int


@dataclass(frozen=True)
class SearchResult:
    """Hold the matched entities with their relations, and the top hits."""

    memory: Graph
    hits: list[Hit]


def arrange_edges[T](ranked: Sequence[T]) -> list[T]:
    """Reorder a best-first list so the strongest sit at both ends.

    - Ranks 1, 2, 3, 4, 5 come out as 1, 3, 5, 4, 2.
    """
    return [*ranked[0::2], *reversed(ranked[1::2])]


def _map_access_times(accesses: list[Access]) -> dict[str, list[str]]:
    times: dict[str, list[str]] = {}
    for access in accesses:
        times.setdefault(access.entity_name, []).append(access.at)
    return times


def _list_entity_times(entity: Entity, opened: list[str]) -> list[str | None]:
    times: list[str | None] = [entity.tag.added_at, *opened]
    times.extend(note.tag.added_at for note in entity.notes)
    return times


def filter_strongest(
    memory: Graph, accesses: list[Access], now: datetime, limit: int
) -> Graph:
    """Return the `limit` most active entities, in file order.

    - Activity counts when the entity and its notes were added, and when
      agents opened it.
    """
    opened = _map_access_times(accesses)
    priors = [
        activation.calc_prior(
            _list_entity_times(entity, opened.get(entity.name, [])), now
        )
        for entity in memory.entities
    ]
    order = sorted(range(len(priors)), key=lambda i: -priors[i])
    kept = sorted(order[:limit])
    return graph.filter_to_entities(memory, [memory.entities[i] for i in kept])


@dataclass(frozen=True)
class Corpus:
    """Hold the indexed texts of a graph, ready to score many queries.

    - `owners` pairs each text with its entity's position and its note,
      None for the name and type text; `opened` holds each entity's access
      times.
    - `scope` is the repo-relative folder or file a search is about.
    - `boosts` caches each scored text's boost, filled only for texts a
      query matches.
    """

    entities: tuple[Entity, ...]
    owners: tuple[tuple[int, Note | None], ...]
    index: bm25.Bm25Index
    opened: tuple[list[str], ...]
    now: datetime
    scope: str | None = None
    boosts: dict[int, float] = field(default_factory=dict)


def is_in_scope(note: Note, scope: str | None) -> bool:
    """Return whether the note's file sits in a folder covering `scope`.

    - A note from a root file, or with no file, is never in scope.
    """
    if not scope or note.path is None:
        return False
    folder = PurePosixPath(note.path).parent.as_posix()
    if folder == ".":
        return False
    return scope == folder or scope.startswith(f"{folder}/")


def prepare_corpus(
    memory: Graph,
    accesses: list[Access],
    now: datetime,
    scope: str | None = None,
) -> Corpus:
    """Return the BM25 index of `memory`, with what its boosts need."""
    opened = _map_access_times(accesses)
    owners: list[tuple[int, Note | None]] = []
    texts: list[str] = []
    for position, entity in enumerate(memory.entities):
        owners.append((position, None))
        texts.append(f"{entity.name} {entity.entity_type}")
        for note in entity.notes:
            owners.append((position, note))
            texts.append(note.text)
    return Corpus(
        tuple(memory.entities),
        tuple(owners),
        bm25.build_index(texts),
        tuple(opened.get(entity.name, []) for entity in memory.entities),
        now,
        scope,
    )


def _calc_boost(corpus: Corpus, text_position: int) -> float:
    cached = corpus.boosts.get(text_position)
    if cached is not None:
        return cached
    entity_position, note = corpus.owners[text_position]
    entity_opened = corpus.opened[entity_position]
    if note is None:
        added = corpus.entities[entity_position].tag.added_at
        times = [added, *entity_opened]
    else:
        times = [note.tag.added_at, *entity_opened]
    boost = 1 + activation.calc_prior(times, corpus.now)
    if note is not None and is_in_scope(note, corpus.scope):
        boost *= SCOPE_BOOST
    corpus.boosts[text_position] = boost
    return boost


@dataclass(frozen=True)
class _Scored:
    entity_index: int
    note: Note | None
    score: float


def _score_texts(corpus: Corpus, query: bm25.Query) -> list[_Scored]:
    scores = bm25.calc_scores(corpus.index, query)
    return [
        _Scored(position, note, score * _calc_boost(corpus, text_position))
        for text_position, ((position, note), score) in enumerate(
            zip(corpus.owners, scores, strict=True)
        )
        if score > 0
    ]


def _calc_entity_scores(
    memory: Graph, scored: list[_Scored], expand: bool
) -> list[float]:
    names = [entity.name for entity in memory.entities]
    name_scores = [0.0] * len(names)
    best_note = [0.0] * len(names)
    for entry in scored:
        if entry.note is None:
            name_scores[entry.entity_index] = entry.score
        else:
            best_note[entry.entity_index] = max(
                best_note[entry.entity_index], entry.score
            )
    direct = [a + b for a, b in zip(name_scores, best_note, strict=True)]
    if not expand:
        return direct
    rank = expansion.calc_personalized_pagerank(
        names,
        ((r.source, r.target) for r in memory.relations),
        dict(zip(names, direct, strict=True)),
    )
    total = sum(direct)
    return [rank[name] * total for name in names]


def search(
    memory: Graph,
    query: str,
    *,
    accesses: list[Access],
    now: datetime,
    limit: int | None = None,
    expand: bool = False,
    corpus: Corpus | None = None,
    scope: str | None = None,
) -> SearchResult:
    """Rank the entities and notes of `memory` for `query`.

    - Returns matching entities, at most `limit`, strongest at both edges,
      with every relation that touches them; and the top `limit` matching
      notes as hits, also strongest at both edges, each with its
      rank.
    - `expand` spreads scores along relations, so linked entities rerank
      and may join the results without matching any word.
    - A query with no words returns every entity, or the `limit` most
      active ones, in file order, and no hits.
    - `corpus` reuses a `prepare_corpus` result for the same `memory`,
      `accesses`, `now`, and `scope`, so several queries index the graph
      once.
    - `scope` boosts notes from files whose folder covers it.
    """
    parsed = bm25.parse_query(query)
    if parsed.is_blank():
        if limit is None:
            return SearchResult(
                graph.filter_to_entities(memory, memory.entities), []
            )
        return SearchResult(filter_strongest(memory, accesses, now, limit), [])
    if corpus is None:
        corpus = prepare_corpus(memory, accesses, now, scope)
    scored = _score_texts(corpus, parsed)
    entity_scores = _calc_entity_scores(memory, scored, expand)
    ranked = sorted(
        (i for i, score in enumerate(entity_scores) if score > 0),
        key=lambda i: -entity_scores[i],
    )[:limit]
    observed = sorted(
        (entry for entry in scored if entry.note is not None),
        key=lambda entry: -entry.score,
    )[:limit]
    hits = [
        Hit(
            memory.entities[entry.entity_index].name,
            entry.note,
            entry.score,
            rank,
        )
        for rank, entry in enumerate(observed, start=1)
        if entry.note is not None
    ]
    entities = [memory.entities[i] for i in arrange_edges(ranked)]
    return SearchResult(
        graph.filter_to_entities(memory, entities), arrange_edges(hits)
    )
