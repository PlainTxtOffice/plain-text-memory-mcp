"""Model the tagged knowledge graph and its pure operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import TypedDict

RelationKey = tuple[str, str, str]


@dataclass(frozen=True)
class Tag:
    """Record when an entry was added and which agent added it."""

    added_at: str | None
    agent: str | None


UNTAGGED = Tag(None, None)


@dataclass(frozen=True)
class Source:
    """Point at the observation a derived fact, such as a summary, cites."""

    entity_name: str
    text: str


@dataclass(frozen=True)
class Observation:
    """Hold one tagged fact about an entity.

    - `tag` records when and by whom the fact was first added; `edited`
      records the latest edit, or None when the text was never changed.
    - `superseded` records when and by whom the fact was retired, or None
      while it is current; `replaced_by` names the text that replaced it.
    - `sources` lists the observations this one was derived from.
    """

    text: str
    tag: Tag
    edited: Tag | None = None
    superseded: Tag | None = None
    replaced_by: str | None = None
    sources: tuple[Source, ...] = ()


@dataclass
class Entity:
    """Hold a named node and its observations."""

    name: str
    entity_type: str
    observations: list[Observation]
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


@dataclass(frozen=True)
class Header:
    """Record which repo a memory file belongs to."""

    repo_name: str
    repo_root: str
    tag: Tag


@dataclass
class Graph:
    """Hold every entity and relation in one memory file.

    - `header` is None until the first write stamps the owning repo.
    """

    entities: list[Entity] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    header: Header | None = None


class UsageCounts(TypedDict):
    """Count the entries in one memory file."""

    entities: int
    observations: int
    relations: int


class Usage(TypedDict):
    """Summarize what one memory file contains."""

    counts: UsageCounts
    entity_types: dict[str, int]
    relation_types: dict[str, int]
    agents: dict[str, int]


class EntityNotFoundError(LookupError):
    """Raised when an operation names an entity that does not exist."""


class EntityExistsError(ValueError):
    """Raised when a new entity name is already taken."""


class ObservationNotFoundError(LookupError):
    """Raised when an entity has no observation with the given text."""


def is_current(observation: Observation) -> bool:
    """Return whether an observation has not been superseded."""
    return observation.superseded is None


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


def init_tag(agent: str, now: datetime | None = None) -> Tag:
    """Return a tag for the given agent stamped with local time.

    - `now` exists for tests; production callers omit it.
    """
    moment = now or datetime.now().astimezone()
    return Tag(moment.isoformat(timespec="seconds"), agent)


def init_header(repo_root: Path, tag: Tag) -> Header:
    """Return a header naming `repo_root` as the memory file's owner."""
    return Header(repo_root.name, repo_root.as_posix(), tag)


def build_entity(
    name: str, entity_type: str, texts: list[str], tag: Tag
) -> Entity:
    """Return a new entity whose observations all carry the given tag.

    - Repeated texts are kept once, in first-seen order.
    """
    unique_texts = dict.fromkeys(texts)
    observations = [Observation(text, tag) for text in unique_texts]
    return Entity(name, entity_type, observations, tag)


def look_entity(memory: Graph, name: str) -> Entity | None:
    """Return the entity with the given name, or None."""
    for entity in memory.entities:
        if entity.name == name:
            return entity
    return None


def create_entities(memory: Graph, entities: list[Entity]) -> list[Entity]:
    """Append entities whose names are new and return the ones appended."""
    known_names = {entity.name for entity in memory.entities}
    created: list[Entity] = []
    for entity in entities:
        if entity.name in known_names:
            continue
        known_names.add(entity.name)
        memory.entities.append(entity)
        created.append(entity)
    return created


def _relation_key(relation: Relation) -> RelationKey:
    return (relation.source, relation.target, relation.relation_type)


def look_missing_names(memory: Graph, relation: Relation) -> list[str]:
    """Return the relation's endpoint names that name no entity, once each."""
    known_names = {entity.name for entity in memory.entities}
    endpoints = dict.fromkeys((relation.source, relation.target))
    return [name for name in endpoints if name not in known_names]


def create_relations(
    memory: Graph, relations: list[Relation]
) -> list[Relation]:
    """Append relations that are new by content and return them.

    - Two relations with the same endpoints and relation type are duplicates
      even when their tags differ.
    - Relations naming an entity that does not exist are skipped; see
      `look_missing_names`.
    """
    known_keys = {_relation_key(relation) for relation in memory.relations}
    created: list[Relation] = []
    for relation in relations:
        key = _relation_key(relation)
        if key in known_keys or look_missing_names(memory, relation):
            continue
        known_keys.add(key)
        memory.relations.append(relation)
        created.append(relation)
    return created


def update_observations(
    memory: Graph,
    entity_name: str,
    texts: list[str],
    tag: Tag,
    sources: tuple[Source, ...] = (),
) -> list[Observation]:
    """Append new observation texts to an entity and return the added ones.

    - Texts already current on the entity are skipped and keep their tag.
    - A text that was superseded becomes current again, with its original
      tag, and counts as added.
    - Every added text cites `sources`.
    - Raises `EntityNotFoundError` when the entity does not exist.
    """
    entity = _look_or_raise(memory, entity_name)
    positions = {o.text: i for i, o in enumerate(entity.observations)}
    added: list[Observation] = []
    for text in texts:
        index = positions.get(text)
        if index is None:
            observation = Observation(text, tag, sources=sources)
            positions[text] = len(entity.observations)
            entity.observations.append(observation)
        elif is_current(entity.observations[index]):
            continue
        else:
            observation = replace(
                entity.observations[index], superseded=None, replaced_by=None
            )
            entity.observations[index] = observation
        added.append(observation)
    return added


def _split[T](items: list[T], is_doomed: Callable[[T], bool]) -> list[T]:
    """Remove items matching `is_doomed` in place and return them."""
    removed = [item for item in items if is_doomed(item)]
    items[:] = [item for item in items if not is_doomed(item)]
    return removed


def edit_observation(
    memory: Graph, entity_name: str, old_text: str, new_text: str, tag: Tag
) -> Observation:
    """Replace an observation's text in place and return the new version.

    - Keeps the original tag and stamps `tag` as the edit.
    - Raises `EntityNotFoundError` or `ObservationNotFoundError` when the
      entity or text is missing, and `ValueError` when the entity already
      has `new_text` as another observation.
    """
    entity = _look_or_raise(memory, entity_name)
    texts = [observation.text for observation in entity.observations]
    index = _look_text_index(entity, old_text)
    if new_text != old_text and new_text in texts:
        message = f"Entity {entity_name} already has observation {new_text!r}"
        raise ValueError(message)
    edited = replace(entity.observations[index], text=new_text, edited=tag)
    entity.observations[index] = edited
    _repoint_sources(
        memory, Source(entity_name, old_text), Source(entity_name, new_text)
    )
    return edited


def supersede_observation(
    memory: Graph,
    entity_name: str,
    old_text: str,
    new_text: str | None,
    tag: Tag,
) -> tuple[Observation, Observation | None]:
    """Retire an observation, keeping it, and return it and its replacement.

    - The old observation keeps its text and tags, gains `superseded`, and
      points at `new_text` through `replaced_by`.
    - A `new_text` the entity lacks is appended with `tag`; one the entity
      already has is reused, and becomes current again if it was retired.
    - A None `new_text` retires the fact with no replacement.
    - Raises `EntityNotFoundError` or `ObservationNotFoundError` when the
      entity or old text is missing, and `ValueError` when the old text is
      already superseded or equals `new_text`.
    """
    entity = _look_or_raise(memory, entity_name)
    index = _look_text_index(entity, old_text)
    if not is_current(entity.observations[index]):
        message = f"Observation {old_text!r} is already superseded"
        raise ValueError(message)
    if new_text == old_text:
        message = "The replacement text must differ from the old text"
        raise ValueError(message)
    retired = replace(
        entity.observations[index], superseded=tag, replaced_by=new_text
    )
    entity.observations[index] = retired
    if new_text is None:
        return retired, None
    added = update_observations(memory, entity_name, [new_text], tag)
    if added:
        return retired, added[0]
    return retired, entity.observations[_look_text_index(entity, new_text)]


def _look_text_index(entity: Entity, text: str) -> int:
    for index, observation in enumerate(entity.observations):
        if observation.text == text:
            return index
    message = f"Entity {entity.name} has no observation {text!r}"
    raise ObservationNotFoundError(message)


def _repoint_sources(memory: Graph, old: Source, new: Source) -> None:
    """Point every reference to `old` at `new`, which is on the same entity.

    - Covers sources anywhere in the graph, and `replaced_by` on the entity.
    """
    for entity in memory.entities:
        for index, observation in enumerate(entity.observations):
            sources = tuple(
                new if source == old else source
                for source in observation.sources
            )
            replaced_by = observation.replaced_by
            if entity.name == old.entity_name and replaced_by == old.text:
                replaced_by = new.text
            if sources != observation.sources or (
                replaced_by != observation.replaced_by
            ):
                entity.observations[index] = replace(
                    observation, sources=sources, replaced_by=replaced_by
                )


def _rename_sources(memory: Graph, old_name: str, new_name: str) -> None:
    for entity in memory.entities:
        for index, observation in enumerate(entity.observations):
            if any(s.entity_name == old_name for s in observation.sources):
                sources = tuple(
                    replace(s, entity_name=new_name)
                    if s.entity_name == old_name
                    else s
                    for s in observation.sources
                )
                entity.observations[index] = replace(
                    observation, sources=sources
                )


def look_missing_sources(
    memory: Graph, sources: tuple[Source, ...]
) -> list[Source]:
    """Return the sources that name no existing observation."""
    known = {
        (entity.name, observation.text)
        for entity in memory.entities
        for observation in entity.observations
    }
    return [s for s in sources if (s.entity_name, s.text) not in known]


def remove_entities(
    memory: Graph, names: list[str]
) -> tuple[list[Entity], list[Relation]]:
    """Remove the named entities and every relation that touches them.

    - Returns the removed entities and relations; unknown names are ignored.
    """
    doomed = set(names)
    entities = _split(memory.entities, lambda e: e.name in doomed)
    relations = _split(
        memory.relations,
        lambda r: r.source in doomed or r.target in doomed,
    )
    return entities, relations


def remove_observations(
    memory: Graph, entity_name: str, texts: list[str]
) -> list[Observation]:
    """Remove observations by text and return the removed ones.

    - A missing entity or text is ignored.
    """
    entity = look_entity(memory, entity_name)
    if entity is None:
        return []
    doomed = set(texts)
    return _split(entity.observations, lambda o: o.text in doomed)


def remove_relations(memory: Graph, keys: list[RelationKey]) -> list[Relation]:
    """Remove relations matching a key and return the removed ones.

    - A key matches on endpoints and relation type, ignoring the tag.
    """
    doomed = set(keys)
    return _split(memory.relations, lambda r: _relation_key(r) in doomed)


def _look_or_raise(memory: Graph, name: str) -> Entity:
    entity = look_entity(memory, name)
    if entity is None:
        message = f"Entity with name {name} not found"
        raise EntityNotFoundError(message)
    return entity


def _rename_endpoints(relation: Relation, old: str, new: str) -> Relation:
    return replace(
        relation,
        source=new if relation.source == old else relation.source,
        target=new if relation.target == old else relation.target,
    )


def rename_entity(memory: Graph, name: str, new_name: str) -> Entity:
    """Rename an entity and every relation endpoint that names it.

    - Every tag stays as it was.
    - Raises `EntityNotFoundError` when `name` does not exist, and
      `EntityExistsError` when another entity already has `new_name`.
    """
    entity = _look_or_raise(memory, name)
    if new_name != name and look_entity(memory, new_name) is not None:
        message = f"Entity with name {new_name} already exists"
        raise EntityExistsError(message)
    entity.name = new_name
    _rename_sources(memory, name, new_name)
    memory.relations[:] = [
        _rename_endpoints(relation, name, new_name)
        for relation in memory.relations
    ]
    return entity


def merge_entities(
    memory: Graph, source: str, target: str
) -> tuple[Entity, list[Relation]]:
    """Fold `source` into `target` and delete `source`.

    - Moves the source's observations with their original tags; a text the
      target already has keeps the target's copy.
    - Points the source's relations at the target, dropping any that would
      duplicate an existing relation or point the target at itself.
    - Returns the target and the relations that moved to it.
    - Raises `EntityNotFoundError` for a missing name and `ValueError` when
      both names are the same.
    """
    if source == target:
        message = f"Cannot merge entity {source} into itself"
        raise ValueError(message)
    folded = _look_or_raise(memory, source)
    kept = _look_or_raise(memory, target)
    known_texts = {observation.text for observation in kept.observations}
    for observation in folded.observations:
        if observation.text not in known_texts:
            known_texts.add(observation.text)
            kept.observations.append(observation)
    memory.entities[:] = [e for e in memory.entities if e is not folded]
    _rename_sources(memory, source, target)
    known_keys = {
        _relation_key(r)
        for r in memory.relations
        if source not in (r.source, r.target)
    }
    relations: list[Relation] = []
    moved: list[Relation] = []
    for relation in memory.relations:
        if source not in (relation.source, relation.target):
            relations.append(relation)
            continue
        repointed = _rename_endpoints(relation, source, target)
        key = _relation_key(repointed)
        if repointed.source == repointed.target or key in known_keys:
            continue
        known_keys.add(key)
        relations.append(repointed)
        moved.append(repointed)
    memory.relations[:] = relations
    return kept, moved


def filter_to_entities(memory: Graph, entities: list[Entity]) -> Graph:
    """Return the given entities and every relation that touches them."""
    names = {entity.name for entity in entities}
    relations = [
        relation
        for relation in memory.relations
        if relation.source in names or relation.target in names
    ]
    return Graph(entities, relations, memory.header)


def filter_current(memory: Graph) -> Graph:
    """Return the graph without superseded observations.

    - Every entity and relation stays, even an entity whose observations
      were all superseded.
    """
    entities = [
        replace(
            entity,
            observations=[o for o in entity.observations if is_current(o)],
        )
        for entity in memory.entities
    ]
    return Graph(entities, list(memory.relations), memory.header)


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
    - An entity stays when it or any observation matches, and keeps only its
      matching observations; an observation's edit also counts. Relations
      stay when their own tag matches.
    - Untagged entries never match a date or agent filter.
    - With no filters, returns `memory` unchanged.
    """
    if since is None and before is None and agent is None:
        return memory

    def is_match(tag: Tag) -> bool:
        return _is_tag_match(tag, since, before, agent)

    def is_observation_match(observation: Observation) -> bool:
        edit = observation.edited
        return is_match(observation.tag) or (
            edit is not None and is_match(edit)
        )

    entities = []
    for entity in memory.entities:
        observations = [
            o for o in entity.observations if is_observation_match(o)
        ]
        if observations or is_match(entity.tag):
            entities.append(
                Entity(
                    entity.name, entity.entity_type, observations, entity.tag
                )
            )
    relations = [r for r in memory.relations if is_match(r.tag)]
    return Graph(entities, relations, memory.header)


def _count_sorted(names: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def calc_usage(memory: Graph) -> Usage:
    """Return counts of entries, entity and relation types, and agents.

    - Agents are counted over entities, observations, and relations;
      untagged entries count as `untagged`.
    """
    observations = [
        observation
        for entity in memory.entities
        for observation in entity.observations
    ]
    tags = [
        *(entity.tag for entity in memory.entities),
        *(observation.tag for observation in observations),
        *(relation.tag for relation in memory.relations),
    ]
    return {
        "counts": {
            "entities": len(memory.entities),
            "observations": len(observations),
            "relations": len(memory.relations),
        },
        "entity_types": _count_sorted(
            [entity.entity_type for entity in memory.entities]
        ),
        "relation_types": _count_sorted(
            [relation.relation_type for relation in memory.relations]
        ),
        "agents": _count_sorted([tag.agent or "untagged" for tag in tags]),
    }
