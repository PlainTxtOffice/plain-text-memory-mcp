"""Model the tagged knowledge graph and the read-only views of it."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime


@dataclass(frozen=True)
class Tag:
    """Record when an entry was added and which agent added it."""

    added_at: str | None
    agent: str | None


UNTAGGED = Tag(None, None)


@dataclass(frozen=True)
class Source:
    """Point at the note a derived fact, such as a conclusion, cites."""

    entity_name: str
    text: str


@dataclass(frozen=True)
class Note:
    """Hold one tagged fact about an entity.

    - `tag` records when and by whom the fact was added.
    - `superseded` records when the fact was retired, or None while it is
      current; `replaced_by` names the text that replaced it.
    - `path` is the repo-relative file the note was read from, or None for
      a note built in memory.
    """

    text: str
    tag: Tag
    superseded: Tag | None = None
    replaced_by: str | None = None
    path: str | None = None


@dataclass
class Entity:
    """Hold a named node and its notes."""

    name: str
    entity_type: str
    notes: list[Note]
    tag: Tag


@dataclass(frozen=True)
class Relation:
    """Hold a directed, typed edge between two entity names."""

    source: str
    target: str
    relation_type: str
    tag: Tag


@dataclass(frozen=True)
class Access:
    """Record that an agent opened an entity, for ranking by use."""

    at: str
    entity_name: str


@dataclass
class Graph:
    """Hold every entity and relation read from the repo's memory files."""

    entities: list[Entity] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)


def is_current(note: Note) -> bool:
    """Return whether a note has not been superseded."""
    return note.superseded is None


def parse_moment(value: str | None) -> datetime | None:
    """Parse a tag time; None or unparseable text returns None.

    - A time without an offset is local time.
    """
    if value is None:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.astimezone()


def look_missing_sources(
    memory: Graph, sources: tuple[Source, ...]
) -> list[Source]:
    """Return the sources that name no existing note."""
    known = {
        (entity.name, note.text)
        for entity in memory.entities
        for note in entity.notes
    }
    return [s for s in sources if (s.entity_name, s.text) not in known]


def filter_to_entities(memory: Graph, entities: list[Entity]) -> Graph:
    """Return the given entities and every relation that touches them."""
    names = {entity.name for entity in entities}
    relations = [
        relation
        for relation in memory.relations
        if relation.source in names or relation.target in names
    ]
    return Graph(entities, relations)


def filter_current(memory: Graph) -> Graph:
    """Return the graph without superseded notes.

    - Every entity and relation stays, even an entity whose notes
      were all superseded.
    """
    entities = [
        replace(
            entity,
            notes=[o for o in entity.notes if is_current(o)],
        )
        for entity in memory.entities
    ]
    return Graph(entities, list(memory.relations))


def filter_by_names(memory: Graph, names: list[str]) -> Graph:
    """Return the named entities and every relation that touches them."""
    wanted = set(names)
    matches = [entity for entity in memory.entities if entity.name in wanted]
    return filter_to_entities(memory, matches)


def _is_tag_match(
    tag: Tag,
    since: datetime | None,
    before: datetime | None,
    agent: str | None,
) -> bool:
    if agent is not None and tag.agent != agent:
        return False
    if since is None and before is None:
        return True
    moment = parse_moment(tag.added_at)
    if moment is None:
        return False
    if since is not None and moment < since:
        return False
    return before is None or moment < before


def filter_by_tag(
    memory: Graph,
    *,
    since: datetime | None = None,
    before: datetime | None = None,
    agent: str | None = None,
) -> Graph:
    """Return only the entries whose tags fall in a date range or agent.

    - `since` is inclusive and `before` exclusive; both must be aware.
    - An entity stays when it or any note matches, and keeps only its
      matching notes. Relations stay when their own tag matches.
    - Untagged entries never match a date or agent filter.
    - With no filters, returns `memory` unchanged.
    """
    if since is None and before is None and agent is None:
        return memory

    def is_match(tag: Tag) -> bool:
        return _is_tag_match(tag, since, before, agent)

    entities = []
    for entity in memory.entities:
        notes = [o for o in entity.notes if is_match(o.tag)]
        if notes or is_match(entity.tag):
            entities.append(
                Entity(entity.name, entity.entity_type, notes, entity.tag)
            )
    relations = [r for r in memory.relations if is_match(r.tag)]
    return Graph(entities, relations)
