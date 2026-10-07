"""Spread search scores along relations with personalized PageRank.

- Follows HippoRAG (Gutierrez et al., NeurIPS 2024): seed the walk with the
  direct matches, so entities linked to several strong hits rise and a
  linked entity with no matching words can still surface.
- Relations count in both directions.
"""

from __future__ import annotations

from collections.abc import Iterable

RESTART = 0.5
ITERATIONS = 30


def _build_neighbors(
    nodes: list[str], edges: Iterable[tuple[str, str]]
) -> dict[str, list[str]]:
    neighbors: dict[str, list[str]] = {node: [] for node in nodes}
    for source, target in edges:
        if source in neighbors and target in neighbors and source != target:
            neighbors[source].append(target)
            neighbors[target].append(source)
    return neighbors


def calc_personalized_pagerank(
    nodes: list[str],
    edges: Iterable[tuple[str, str]],
    seeds: dict[str, float],
) -> dict[str, float]:
    """Return each node's PageRank mass for a walk that restarts at `seeds`.

    - `seeds` maps nodes to positive weights; they are normalized to sum 1.
    - A node with no neighbors sends its mass back to the seeds.
    - With no positive seed, every node scores 0.
    """
    total = sum(weight for weight in seeds.values() if weight > 0)
    if not total:
        return dict.fromkeys(nodes, 0.0)
    restart = {node: max(seeds.get(node, 0.0), 0.0) / total for node in nodes}
    neighbors = _build_neighbors(nodes, edges)
    rank = dict(restart)
    for _ in range(ITERATIONS):
        spread = {node: RESTART * restart[node] for node in nodes}
        for node, mass in rank.items():
            walk = (1 - RESTART) * mass
            linked = neighbors[node]
            if not linked:
                for seed, share in restart.items():
                    spread[seed] += walk * share
                continue
            for neighbor in linked:
                spread[neighbor] += walk / len(linked)
        rank = spread
    return rank
