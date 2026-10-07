"""Map graph models to and from JSONL records.

- Key names match the original server where they overlap: `entityType`,
  `relationType`, `from`, and `to`.
- Records written before tagging existed load with `UNTAGGED`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NotRequired, TypedDict

from plain_text_memory_mcp.graph import (
    UNTAGGED,
    Access,
    Entity,
    Graph,
    Header,
    Observation,
    Relation,
    RelationKey,
    Source,
    Tag,
)

Record = dict[str, object]


class SourceRecord(TypedDict):
    """An observation that another observation was derived from."""

    entityName: str
    text: str


class ObservationRecord(TypedDict):
    """One observation as JSON, inside an entity's observations list."""

    text: str
    added_at: str | None
    agent: str | None
    edited_at: NotRequired[str | None]
    edited_by: NotRequired[str | None]
    superseded_at: NotRequired[str | None]
    superseded_by: NotRequired[str | None]
    replaced_by: NotRequired[str | None]
    sources: NotRequired[list[SourceRecord]]


class EntityRecord(TypedDict):
    """One entity line of the memory file."""

    type: Literal["entity"]
    name: str
    entityType: str
    added_at: str | None
    agent: str | None
    observations: list[ObservationRecord]


# Functional form: "from" is a Python keyword.
RelationRecord = TypedDict(
    "RelationRecord",
    {
        "type": Literal["relation"],
        "from": str,
        "to": str,
        "relationType": str,
        "added_at": str | None,
        "agent": str | None,
    },
)
RelationRecord.__doc__ = "One relation line of the memory file."


class HeaderRecord(TypedDict):
    """The header line naming the repo that owns the memory file."""

    type: Literal["header"]
    repo_name: str
    repo_root: str
    added_at: str | None
    agent: str | None


class AccessRecord(TypedDict):
    """One line of the access log beside the memory file."""

    type: Literal["access"]
    at: str
    entity: str


@dataclass(frozen=True)
class Tombstone:
    """Mark an entity or relation removed by a line after it.

    - Exactly one of `entity_name` and `relation_key` is set.
    """

    entity_name: str | None = None
    relation_key: RelationKey | None = None


class GraphRecord(TypedDict):
    """Entities and the relations between them, as tools return them."""

    entities: list[EntityRecord]
    relations: list[RelationRecord]


# What each record type is for; published in the taxonomy and its export.
RECORD_PURPOSES = {
    "header": (
        "First line of the memory file. Names the repo that owns it, so a"
        " copy in another repo is detected."
    ),
    "entity": (
        "A named thing the agents remember, such as a repo, module, library,"
        " person, or decision, with its observations."
    ),
    "relation": (
        "A directed link between two entities, in active voice:"
        " reading_list uses sqlite."
    ),
    "observation": (
        "One fact about an entity, stored inside the entity's observations"
        " list. edited_at and edited_by appear once its text is edited;"
        " superseded_at, superseded_by, and replaced_by once it is retired;"
        " sources when it was derived from other observations."
    ),
    "tombstone": (
        "Removes the entity or relation it names. Writes append changed"
        " records and tombstones; a later line for the same entity or"
        " relation replaces an earlier one, until compaction rewrites the"
        " file with one line per record."
    ),
    "access": (
        "One line of memory.local.access.jsonl, appended when an agent opens"
        " an entity; search ranks often-opened entities higher."
    ),
}


class RecordError(ValueError):
    """Raised when a memory record does not match the expected shape."""


def to_observation_record(observation: Observation) -> ObservationRecord:
    """Return the JSON record for one observation.

    - `edited_at` and `edited_by` appear only once the text was edited.
    """
    record: ObservationRecord = {
        "text": observation.text,
        "added_at": observation.tag.added_at,
        "agent": observation.tag.agent,
    }
    if observation.edited is not None:
        record["edited_at"] = observation.edited.added_at
        record["edited_by"] = observation.edited.agent
    if observation.superseded is not None:
        record["superseded_at"] = observation.superseded.added_at
        record["superseded_by"] = observation.superseded.agent
        record["replaced_by"] = observation.replaced_by
    if observation.sources:
        record["sources"] = [
            {"entityName": source.entity_name, "text": source.text}
            for source in observation.sources
        ]
    return record


def to_entity_record(entity: Entity) -> EntityRecord:
    """Return the JSON record for one entity and its observations."""
    return {
        "type": "entity",
        "name": entity.name,
        "entityType": entity.entity_type,
        "added_at": entity.tag.added_at,
        "agent": entity.tag.agent,
        "observations": [
            to_observation_record(observation)
            for observation in entity.observations
        ],
    }


def to_relation_record(relation: Relation) -> RelationRecord:
    """Return the JSON record for one relation."""
    return {
        "type": "relation",
        "from": relation.source,
        "to": relation.target,
        "relationType": relation.relation_type,
        "added_at": relation.tag.added_at,
        "agent": relation.tag.agent,
    }


def to_header_record(header: Header) -> HeaderRecord:
    """Return the JSON record for the memory file's owning repo."""
    return {
        "type": "header",
        "repo_name": header.repo_name,
        "repo_root": header.repo_root,
        "added_at": header.tag.added_at,
        "agent": header.tag.agent,
    }


def to_access_record(access: Access) -> AccessRecord:
    """Return the JSON record for one access log line."""
    return {"type": "access", "at": access.at, "entity": access.entity_name}


def to_tombstone_record(tombstone: Tombstone) -> dict[str, str]:
    """Return the JSON record that removes an entity or a relation."""
    if tombstone.relation_key is None:
        return {"type": "tombstone", "entity": str(tombstone.entity_name)}
    source, target, relation_type = tombstone.relation_key
    return {
        "type": "tombstone",
        "from": source,
        "to": target,
        "relationType": relation_type,
    }


def to_graph_record(memory: Graph) -> GraphRecord:
    """Return a JSON record holding every entity and relation."""
    return {
        "entities": [to_entity_record(entity) for entity in memory.entities],
        "relations": [
            to_relation_record(relation) for relation in memory.relations
        ],
    }


def _parse_tag(raw: dict[str, object]) -> Tag:
    added_at = raw.get("added_at")
    agent = raw.get("agent")
    if added_at is None and agent is None:
        return UNTAGGED
    return Tag(
        added_at if isinstance(added_at, str) else None,
        agent if isinstance(agent, str) else None,
    )


def _parse_text(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        message = f"field {key!r} must be a string, found {value!r}"
        raise RecordError(message)
    return value


def _parse_tag_pair(raw: dict[str, object], at: str, by: str) -> Tag | None:
    if at not in raw and by not in raw:
        return None
    return _parse_tag({"added_at": raw.get(at), "agent": raw.get(by)})


def _parse_sources(raw: object) -> tuple[Source, ...]:
    if not isinstance(raw, list):
        message = f"sources must be a list, found {raw!r}"
        raise RecordError(message)
    sources = []
    for entry in raw:
        if not isinstance(entry, dict):
            message = f"source must be an object, found {entry!r}"
            raise RecordError(message)
        sources.append(
            Source(_parse_text(entry, "entityName"), _parse_text(entry, "text"))
        )
    return tuple(sources)


def _parse_observation(raw: object) -> Observation:
    if isinstance(raw, str):
        return Observation(raw, UNTAGGED)
    if isinstance(raw, dict):
        replaced_by = raw.get("replaced_by")
        return Observation(
            _parse_text(raw, "text"),
            _parse_tag(raw),
            edited=_parse_tag_pair(raw, "edited_at", "edited_by"),
            superseded=_parse_tag_pair(raw, "superseded_at", "superseded_by"),
            replaced_by=replaced_by if isinstance(replaced_by, str) else None,
            sources=_parse_sources(raw.get("sources", [])),
        )
    message = f"observation must be a string or object, found {raw!r}"
    raise RecordError(message)


def _parse_entity(raw: dict[str, object]) -> Entity:
    observations = raw.get("observations", [])
    if not isinstance(observations, list):
        message = f"observations must be a list, found {observations!r}"
        raise RecordError(message)
    return Entity(
        _parse_text(raw, "name"),
        _parse_text(raw, "entityType"),
        [_parse_observation(observation) for observation in observations],
        _parse_tag(raw),
    )


def _parse_relation(raw: dict[str, object]) -> Relation:
    return Relation(
        _parse_text(raw, "from"),
        _parse_text(raw, "to"),
        _parse_text(raw, "relationType"),
        _parse_tag(raw),
    )


def _parse_header(raw: dict[str, object]) -> Header:
    return Header(
        _parse_text(raw, "repo_name"),
        _parse_text(raw, "repo_root"),
        _parse_tag(raw),
    )


def _parse_tombstone(raw: dict[str, object]) -> Tombstone:
    if "entity" in raw:
        return Tombstone(entity_name=_parse_text(raw, "entity"))
    return Tombstone(
        relation_key=(
            _parse_text(raw, "from"),
            _parse_text(raw, "to"),
            _parse_text(raw, "relationType"),
        )
    )


def parse_access(raw: object) -> Access:
    """Parse one decoded access log line.

    - Raises `RecordError` when the line is not an access record.
    """
    if not isinstance(raw, dict) or raw.get("type") != "access":
        message = f"not an access record: {raw!r}"
        raise RecordError(message)
    return Access(_parse_text(raw, "at"), _parse_text(raw, "entity"))


def parse_record(raw: object) -> Entity | Relation | Header | Tombstone:
    """Parse one decoded JSON line into a graph record or a tombstone.

    - Accepts legacy untagged records and plain-string observations.
    - Raises `RecordError` for any other shape.
    """
    if not isinstance(raw, dict):
        message = f"record must be a JSON object, found {raw!r}"
        raise RecordError(message)
    kind = raw.get("type")
    if kind == "entity":
        return _parse_entity(raw)
    if kind == "relation":
        return _parse_relation(raw)
    if kind == "header":
        return _parse_header(raw)
    if kind == "tombstone":
        return _parse_tombstone(raw)
    message = f"unknown record type {kind!r}"
    raise RecordError(message)
