"""Map graph models to the JSON records that tools return and logs hold.

- Key names match the original server where they overlap: `entityType`,
  `relationType`, `from`, and `to`.
- The access log is the only file of records the server reads back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NotRequired, TypedDict

from plain_text_memory_mcp.graph import (
    Access,
    Entity,
    Graph,
    Note,
    Relation,
    Source,
)

Record = dict[str, object]


class NoteRecord(TypedDict):
    """One note as JSON, inside an entity's notes list."""

    text: str
    added_at: str | None
    agent: str | None
    superseded_at: NotRequired[str | None]
    replaced_by: NotRequired[str | None]
    path: NotRequired[str]


class EntityRecord(TypedDict):
    """One entity as JSON, with its notes."""

    type: Literal["entity"]
    name: str
    entityType: str
    added_at: str | None
    agent: str | None
    notes: list[NoteRecord]


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
RelationRecord.__doc__ = "One relation as JSON."


class AccessRecord(TypedDict):
    """One line of the access log in `.agents/ptm/`."""

    type: Literal["access"]
    at: str
    entity: str


RecallEventKind = Literal["recall", "search", "open"]

# Log lines quote only the start of each hit; the memory files hold the rest.
HIT_EXCERPT_LENGTH = 80


@dataclass(frozen=True)
class RecallHit:
    """Point at one hit a recall step or search returned, for the log."""

    entity_name: str
    rank: int
    text: str


@dataclass(frozen=True)
class RecallEvent:
    """Hold one recall log line: a recall step, a search, or an open.

    - A "recall" line uses every field; a "search" line uses `queries` and
      `hits`; an "open" line uses `names`.
    """

    kind: RecallEventKind
    at: str
    agent: str
    session: str | None = None
    step: int | None = None
    total_steps: int | None = None
    revises_step: int | None = None
    thought: str | None = None
    queries: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    hits: tuple[RecallHit, ...] = ()
    seen: int = 0
    conclusion: str | None = None
    sources: tuple[Source, ...] = ()


class GraphRecord(TypedDict):
    """Entities and the relations between them, as tools return them."""

    entities: list[EntityRecord]
    relations: list[RelationRecord]


# What each record type is for; published in the taxonomy.
RECORD_PURPOSES = {
    "entity": (
        "A named thing the agents remember, such as a folder, module,"
        " library, or decision, with its notes. A heading in a MEMORY.ptm.md"
        " or AGENTS.md file starts one; a name used in several files is one"
        " entity."
    ),
    "relation": (
        "A directed link between two entities, read from a bullet that is"
        " one verb and one [[link]], in active voice: reading_list uses"
        " sqlite."
    ),
    "note": (
        "One fact about an entity, inside its notes list: a bullet of a"
        " MEMORY.ptm.md file, or a bullet or paragraph of an AGENTS.md file."
        " path is the file it came from. superseded_at and replaced_by"
        " appear once the bullet is struck through: superseded_at is its"
        " retirement stamp and replaced_by the live bullet it is nested"
        " under."
    ),
    "access": (
        "One line of .agents/ptm/access.jsonl, appended when an agent opens"
        " an entity; search ranks often-opened entities higher."
    ),
    "recall": (
        "One line of .agents/ptm/recall.jsonl, a development log written"
        " only when MEMORY_RECALL_LOG=1: a recall step with its thought,"
        " queries, hits, and conclusion, or a search_nodes or open_nodes"
        " call."
    ),
}


class RecordError(ValueError):
    """Raised when a memory record does not match the expected shape."""


def to_note_record(note: Note) -> NoteRecord:
    """Return the JSON record for one note.

    - `superseded_at` and `replaced_by` appear only once the note was
      struck through.
    - `path` appears only for notes read from a memory file.
    """
    record: NoteRecord = {
        "text": note.text,
        "added_at": note.tag.added_at,
        "agent": note.tag.agent,
    }
    if note.superseded is not None:
        record["superseded_at"] = note.superseded.added_at
        record["replaced_by"] = note.replaced_by
    if note.path is not None:
        record["path"] = note.path
    return record


def to_entity_record(entity: Entity) -> EntityRecord:
    """Return the JSON record for one entity and its notes."""
    return {
        "type": "entity",
        "name": entity.name,
        "entityType": entity.entity_type,
        "added_at": entity.tag.added_at,
        "agent": entity.tag.agent,
        "notes": [to_note_record(note) for note in entity.notes],
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


def to_access_record(access: Access) -> AccessRecord:
    """Return the JSON record for one access log line."""
    return {"type": "access", "at": access.at, "entity": access.entity_name}


def to_recall_record(event: RecallEvent) -> Record:
    """Return the JSON record for one recall log line.

    - Every line has type, kind, at, and agent; the other fields depend on
      the kind.
    """
    record: Record = {
        "type": "recall",
        "kind": event.kind,
        "at": event.at,
        "agent": event.agent,
    }
    if event.kind == "open":
        record["names"] = list(event.names)
        return record
    record["queries"] = list(event.queries)
    record["hits"] = [
        {
            "entity": hit.entity_name,
            "rank": hit.rank,
            "text": hit.text[:HIT_EXCERPT_LENGTH],
        }
        for hit in event.hits
    ]
    if event.kind == "search":
        return record
    record.update(
        {
            "session": event.session,
            "step": event.step,
            "total_steps": event.total_steps,
            "revises_step": event.revises_step,
            "thought": event.thought,
            "names": list(event.names),
            "seen": event.seen,
            "conclusion": event.conclusion,
            "sources": [
                {"entityName": s.entity_name, "text": s.text}
                for s in event.sources
            ],
        }
    )
    return record


def to_graph_record(memory: Graph) -> GraphRecord:
    """Return a JSON record holding every entity and relation."""
    return {
        "entities": [to_entity_record(entity) for entity in memory.entities],
        "relations": [
            to_relation_record(relation) for relation in memory.relations
        ],
    }


def _parse_text(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        message = f"field {key!r} must be a string, found {value!r}"
        raise RecordError(message)
    return value


def parse_access(raw: object) -> Access:
    """Parse one decoded access log line.

    - Raises `RecordError` when the line is not an access record.
    """
    if not isinstance(raw, dict) or raw.get("type") != "access":
        message = f"not an access record: {raw!r}"
        raise RecordError(message)
    return Access(_parse_text(raw, "at"), _parse_text(raw, "entity"))
