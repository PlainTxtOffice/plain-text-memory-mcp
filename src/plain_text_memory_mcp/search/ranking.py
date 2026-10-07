"""Rank entities and observations for a query, strongest at the edges.

- Every entity contributes two kinds of text to one BM25 index: its name
  and type, and each observation on its own.
- A text's score is its BM25 score times one plus its activation prior, so
  relevance decides and recent or often-opened memories break near-ties.
- Results are ordered for the reader, not the sorter: models use the start
  and end of a long context better than the middle (Liu et al., "Lost in
  the Middle", TACL 2024), so the strongest results go at both edges.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from plain_text_memory_mcp import graph
from plain_text_memory_mcp.graph import Access, Entity, Graph, Observation
from plain_text_memory_mcp.search import activation, bm25, expansion


@dataclass(frozen=True)
class Hit:
    """Hold one matching observation and its rank, 1 being the strongest."""

    entity_name: str
    observation: Observation
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


def _list_observation_times(observation: Observation) -> list[str | None]:
    edited = observation.edited.added_at if observation.edited else None
    return [observation.tag.added_at, edited]


def _list_entity_times(entity: Entity, opened: list[str]) -> list[str | None]:
    times: list[str | None] = [entity.tag.added_at, *opened]
    for observation in entity.observations:
        times.extend(_list_observation_times(observation))
    return times


def filter_strongest(
    memory: Graph, accesses: list[Access], now: datetime, limit: int
) -> Graph:
    """Return the `limit` most active entities, in file order.

    - Activity counts when the entity and its observations were added or
      edited, and when agents opened it.
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
class _Scored:
    entity_index: int
    observation: Observation | None
    score: float


def _score_texts(
    memory: Graph, query: bm25.Query, accesses: list[Access], now: datetime
) -> list[_Scored]:
    opened = _map_access_times(accesses)
    owners: list[tuple[int, Observation | None]] = []
    texts: list[str] = []
    times: list[list[str | None]] = []
    for position, entity in enumerate(memory.entities):
        entity_opened = opened.get(entity.name, [])
        owners.append((position, None))
        texts.append(f"{entity.name} {entity.entity_type}")
        times.append([entity.tag.added_at, *entity_opened])
        for observation in entity.observations:
            owners.append((position, observation))
            texts.append(observation.text)
            times.append(
                [*_list_observation_times(observation), *entity_opened]
            )
    scores = bm25.calc_scores(bm25.build_index(texts), query)
    return [
        _Scored(
            position,
            observation,
            score * (1 + activation.calc_prior(text_times, now)),
        )
        for (position, observation), score, text_times in zip(
            owners, scores, times, strict=True
        )
        if score > 0
    ]


def _calc_entity_scores(
    memory: Graph, scored: list[_Scored], expand: bool
) -> list[float]:
    names = [entity.name for entity in memory.entities]
    name_scores = [0.0] * len(names)
    best_observation = [0.0] * len(names)
    for entry in scored:
        if entry.observation is None:
            name_scores[entry.entity_index] = entry.score
        else:
            best_observation[entry.entity_index] = max(
                best_observation[entry.entity_index], entry.score
            )
    direct = [a + b for a, b in zip(name_scores, best_observation, strict=True)]
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
) -> SearchResult:
    """Rank the entities and observations of `memory` for `query`.

    - Returns matching entities, at most `limit`, strongest at both edges,
      with every relation that touches them; and the top `limit` matching
      observations as hits, also strongest at both edges, each with its
      rank.
    - `expand` spreads scores along relations, so linked entities rerank
      and may join the results without matching any word.
    - A query with no words returns every entity, or the `limit` most
      active ones, in file order, and no hits.
    """
    parsed = bm25.parse_query(query)
    if parsed.is_blank():
        if limit is None:
            return SearchResult(
                graph.filter_to_entities(memory, memory.entities), []
            )
        return SearchResult(filter_strongest(memory, accesses, now, limit), [])
    scored = _score_texts(memory, parsed, accesses, now)
    entity_scores = _calc_entity_scores(memory, scored, expand)
    ranked = sorted(
        (i for i, score in enumerate(entity_scores) if score > 0),
        key=lambda i: -entity_scores[i],
    )[:limit]
    observed = sorted(
        (entry for entry in scored if entry.observation is not None),
        key=lambda entry: -entry.score,
    )[:limit]
    hits = [
        Hit(
            memory.entities[entry.entity_index].name,
            entry.observation,
            entry.score,
            rank,
        )
        for rank, entry in enumerate(observed, start=1)
        if entry.observation is not None
    ]
    entities = [memory.entities[i] for i in arrange_edges(ranked)]
    return SearchResult(
        graph.filter_to_entities(memory, entities), arrange_edges(hits)
    )
