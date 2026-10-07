"""Tests for mapping graph models to and from JSONL records."""

import pytest

from plain_text_memory_mcp import records
from plain_text_memory_mcp.graph import (
    UNTAGGED,
    Entity,
    Graph,
    Observation,
    Relation,
    Tag,
)

TAG_A = Tag("2026-09-29T10:00:00-04:00", "claude-code")
TAG_B = Tag("2026-09-29T11:00:00-04:00", "codex")


def test_entity_record_round_trip() -> None:
    entity = Entity(
        "app", "project", [Observation("Uses SQLite", TAG_A)], TAG_B
    )
    record = records.to_entity_record(entity)
    assert record == {
        "type": "entity",
        "name": "app",
        "entityType": "project",
        "added_at": "2026-09-29T11:00:00-04:00",
        "agent": "codex",
        "observations": [
            {
                "text": "Uses SQLite",
                "added_at": "2026-09-29T10:00:00-04:00",
                "agent": "claude-code",
            }
        ],
    }
    assert records.parse_record(record) == entity


def test_relation_record_round_trip() -> None:
    relation = Relation("app", "sqlite", "uses", TAG_A)
    record = records.to_relation_record(relation)
    assert record == {
        "type": "relation",
        "from": "app",
        "to": "sqlite",
        "relationType": "uses",
        "added_at": "2026-09-29T10:00:00-04:00",
        "agent": "claude-code",
    }
    assert records.parse_record(record) == relation


def test_legacy_entity_loads_untagged() -> None:
    raw = {
        "type": "entity",
        "name": "python-vscode-template",
        "entityType": "repository",
        "observations": ["This is a template."],
    }
    assert records.parse_record(raw) == Entity(
        "python-vscode-template",
        "repository",
        [Observation("This is a template.", UNTAGGED)],
        UNTAGGED,
    )


def test_legacy_entity_without_observations_loads_empty() -> None:
    raw = {"type": "entity", "name": "a", "entityType": "x"}
    assert records.parse_record(raw) == Entity("a", "x", [], UNTAGGED)


def test_legacy_relation_loads_untagged() -> None:
    raw = {"type": "relation", "from": "a", "to": "b", "relationType": "uses"}
    assert records.parse_record(raw) == Relation("a", "b", "uses", UNTAGGED)


def test_untagged_entity_writes_nulls() -> None:
    record = records.to_entity_record(Entity("a", "x", [], UNTAGGED))
    assert record["added_at"] is None
    assert record["agent"] is None


@pytest.mark.parametrize(
    "raw",
    [
        [],
        "text",
        {"type": "widget"},
        {"type": "entity", "name": "a"},
        {"type": "entity", "name": "a", "entityType": "x", "observations": [3]},
        {"type": "entity", "name": "a", "entityType": "x", "observations": "a"},
        {"type": "relation", "from": "a", "to": "b"},
    ],
)
def test_invalid_records_raise(raw: object) -> None:
    with pytest.raises(records.RecordError):
        records.parse_record(raw)


def test_graph_record_lists_entities_and_relations() -> None:
    memory = Graph(
        [Entity("a", "x", [], TAG_A)], [Relation("a", "a", "self", TAG_A)]
    )
    assert records.to_graph_record(memory) == {
        "entities": [records.to_entity_record(memory.entities[0])],
        "relations": [records.to_relation_record(memory.relations[0])],
    }


def test_edited_observation_round_trip() -> None:
    observation = Observation("Uses Postgres", TAG_A, edited=TAG_B)
    record = records.to_observation_record(observation)
    assert record == {
        "text": "Uses Postgres",
        "added_at": "2026-09-29T10:00:00-04:00",
        "agent": "claude-code",
        "edited_at": "2026-09-29T11:00:00-04:00",
        "edited_by": "codex",
    }
    entity = Entity("app", "project", [observation], TAG_A)
    parsed = records.parse_record(records.to_entity_record(entity))
    assert parsed == entity


def test_unedited_observation_has_no_edit_fields() -> None:
    record = records.to_observation_record(Observation("x", TAG_A))
    assert "edited_at" not in record
