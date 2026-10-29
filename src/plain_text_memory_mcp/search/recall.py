"""Track step-by-step recall sessions over ranked search.

- A session remembers the hits it returned and the entities it opened, so
  each later step returns only new hits.
- Hits from several queries merge by note, keeping the best score;
  the strongest few return, strongest at both edges.
"""

from __future__ import annotations

import secrets
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from plain_text_memory_mcp.graph import Access, Entity, Graph
from plain_text_memory_mcp.search import bm25, ranking

# Most hits one step returns; a constant keeps the tool schema small.
STEP_HIT_LIMIT = 8
# Most linked names one step suggests opening; a hub entity has many.
UNOPENED_LIMIT = 8
# A hit entity this small comes back whole, so one call carries the facts
# around a hit; larger ones, such as a repo hub, stay closed.
AUTO_OPEN_MAX_FACTS = 8
# Most entities one step opens on its own.
AUTO_OPEN_LIMIT = 3

HitKey = tuple[str, str]


@dataclass
class Session:
    """Hold what one recall session has returned and opened so far."""

    session_id: str
    steps: set[int] = field(default_factory=set)
    returned: set[HitKey] = field(default_factory=set)
    opened: set[str] = field(default_factory=set)
    # Tool calls run in worker threads; hold this while reading or
    # changing the sets above, so parallel steps never repeat a hit.
    lock: threading.RLock = field(
        default_factory=threading.RLock, repr=False, compare=False
    )


@dataclass(frozen=True)
class StepHits:
    """Hold one step's new hits, the repeats it dropped, and what to open."""

    hits: list[ranking.Hit]
    seen: int
    unopened: list[str]
    auto_opened: list[str]


class SessionRegistry:
    """Store recall sessions by id for the life of the server."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def look(self, session_id: str | None) -> Session | None:
        """Return the session with `session_id`, or None if unknown."""
        if session_id is None:
            return None
        with self._lock:
            return self._sessions.get(session_id)

    def init(self) -> Session:
        """Start a session under a new 8-hex-digit id."""
        with self._lock:
            session_id = secrets.token_hex(4)
            while session_id in self._sessions:
                session_id = secrets.token_hex(4)
            session = Session(session_id)
            self._sessions[session_id] = session
            return session


def update_opened(session: Session, entities: list[Entity]) -> None:
    """Record entities an agent opened in `session`.

    - Their facts count as returned, so later hits never repeat a fact the
      agent already holds in full.
    """
    with session.lock:
        for entity in entities:
            session.opened.add(entity.name)
            session.returned.update((entity.name, o.text) for o in entity.notes)


def _key(hit: ranking.Hit) -> HitKey:
    return (hit.entity_name, hit.note.text)


def _list_unopened(
    memory: Graph, hit_names: set[str], opened: set[str]
) -> list[str]:
    links: Counter[str] = Counter()
    for relation in memory.relations:
        for near, far in (
            (relation.source, relation.target),
            (relation.target, relation.source),
        ):
            if near in hit_names and far not in hit_names | opened:
                links[far] += 1
    # Counter.most_common keeps first-seen order among equal counts.
    return [name for name, _ in links.most_common(UNOPENED_LIMIT)]


def _list_auto_opened(
    memory: Graph, candidates: list[str], opened: set[str]
) -> list[str]:
    sizes = {entity.name: len(entity.notes) for entity in memory.entities}
    chosen: list[str] = []
    for name in candidates:
        if (
            name not in chosen
            and name not in opened
            and sizes.get(name, 0) <= AUTO_OPEN_MAX_FACTS
        ):
            chosen.append(name)
        if len(chosen) == AUTO_OPEN_LIMIT:
            break
    return chosen


def calc_step_hits(
    memory: Graph,
    queries: list[str],
    session: Session,
    *,
    accesses: list[Access],
    now: datetime,
    scope: str | None = None,
) -> StepHits:
    """Run `queries` and return the strongest hits `session` has not seen.

    - Records the returned hits in `session`, so later steps skip them.
      New hits past the cap are not recorded and can return later.
    - `seen` counts matching hits dropped because the session returned
      them before.
    - `unopened` names at most `UNOPENED_LIMIT` entities linked to a hit's
      entity that hold no hit in this step and that the session has not
      opened; names linked to more hit entities come first, then relation
      order.
    - `auto_opened` names up to `AUTO_OPEN_LIMIT` entities that hold at
      most `AUTO_OPEN_MAX_FACTS` notes and that the session has not
      opened: hit entities, strongest hit first, then entities matched
      only by name or type. Their facts all count as returned, and their
      hits leave `hits`, since the whole entity carries them.
    - An entity matched only by name or type that is too large to open on
      its own leads `unopened`, so a name match is never lost.
    - Searches without the session lock, then filters and records under
      it, so parallel steps of one session never return the same hit.
    - `scope` boosts notes from files whose folder covers it.
    """
    best: dict[HitKey, ranking.Hit] = {}
    matched: list[str] = []
    # Blank queries never touch the index, so build it only for real ones.
    corpus = (
        ranking.prepare_corpus(memory, accesses, now, scope)
        if any(not bm25.parse_query(query).is_blank() for query in queries)
        else None
    )
    for query in queries:
        found = ranking.search(
            memory, query, accesses=accesses, now=now, corpus=corpus
        )
        matched += [entity.name for entity in found.memory.entities]
        for hit in found.hits:
            key = _key(hit)
            if key not in best or hit.score > best[key].score:
                best[key] = hit
    with_facts = {hit.entity_name for hit in best.values()}
    name_only = [
        name for name in dict.fromkeys(matched) if name not in with_facts
    ]
    with session.lock:
        fresh = [h for key, h in best.items() if key not in session.returned]
        strongest = sorted(fresh, key=lambda h: -h.score)[:STEP_HIT_LIMIT]
        auto_opened = _list_auto_opened(
            memory,
            [*(hit.entity_name for hit in strongest), *name_only],
            session.opened,
        )
        update_opened(
            session, [e for e in memory.entities if e.name in auto_opened]
        )
        session.returned.update(_key(hit) for hit in strongest)
        hit_names = {hit.entity_name for hit in strongest}
        closed = [n for n in name_only if n not in session.opened]
        linked = _list_unopened(memory, hit_names, session.opened)
        unopened = list(dict.fromkeys([*closed, *linked]))[:UNOPENED_LIMIT]
    kept = [hit for hit in strongest if hit.entity_name not in auto_opened]
    hits = [
        ranking.Hit(hit.entity_name, hit.note, hit.score, rank)
        for rank, hit in enumerate(kept, start=1)
    ]
    return StepHits(
        ranking.arrange_edges(hits),
        len(best) - len(fresh),
        unopened,
        auto_opened,
    )
