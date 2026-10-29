"""Tests for mapping graph models to JSON records."""

import pytest

from plain_text_memory_mcp import records
from plain_text_memory_mcp.graph import (
    UNTAGGED,
    Entity,
    Graph,
    Note,
    Relation,
    Source,
    Tag,
)

TAG_A = Tag("2026-09-29T10:00:00-04:00", "claude-code")
TAG_B = Tag("2026-09-29T11:00:00-04:00", "codex")


def test_entity_record_lists_notes() -> None:
    entity = Entity("app", "project", [Note("Uses SQLite", TAG_A)], TAG_B)
    record = records.to_entity_record(entity)
    assert record == {
        "type": "entity",
        "name": "app",
        "entityType": "project",
        "added_at": "2026-09-29T11:00:00-04:00",
        "agent": "codex",
        "notes": [
            {
                "text": "Uses SQLite",
                "added_at": "2026-09-29T10:00:00-04:00",
                "agent": "claude-code",
            }
        ],
    }


def test_relation_record_uses_original_keys() -> None:
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


def test_untagged_entity_writes_nulls() -> None:
    record = records.to_entity_record(Entity("a", "x", [], UNTAGGED))
    assert record["added_at"] is None
    assert record["agent"] is None


def test_graph_record_lists_entities_and_relations() -> None:
    memory = Graph(
        [Entity("a", "x", [], TAG_A)], [Relation("a", "a", "self", TAG_A)]
    )
    assert records.to_graph_record(memory) == {
        "entities": [records.to_entity_record(memory.entities[0])],
        "relations": [records.to_relation_record(memory.relations[0])],
    }


def test_struck_note_record_carries_retirement_and_path() -> None:
    note = Note(
        "Uses MySQL",
        TAG_A,
        superseded=Tag("2026-09-30T09:00-04:00", None),
        replaced_by="Uses SQLite",
        path="src/MEMORY.ptm.md",
    )
    assert records.to_note_record(note) == {
        "text": "Uses MySQL",
        "added_at": "2026-09-29T10:00:00-04:00",
        "agent": "claude-code",
        "superseded_at": "2026-09-30T09:00-04:00",
        "replaced_by": "Uses SQLite",
        "path": "src/MEMORY.ptm.md",
    }


def test_live_note_record_has_no_retirement_fields() -> None:
    record = records.to_note_record(Note("x", TAG_A))
    assert record == {
        "text": "x",
        "added_at": TAG_A.added_at,
        "agent": TAG_A.agent,
    }


@pytest.mark.parametrize(
    "raw",
    [[], {"type": "recall"}, {"type": "access", "at": 1, "entity": "a"}],
)
def test_parse_access_rejects_other_lines(raw: object) -> None:
    with pytest.raises(records.RecordError):
        records.parse_access(raw)


AT = "2026-10-07T09:00:00-04:00"


def test_recall_record_carries_step_fields() -> None:
    event = records.RecallEvent(
        "recall",
        AT,
        "codex",
        session="1a2b3c4d",
        step=2,
        total_steps=3,
        revises_step=1,
        thought="why",
        queries=("sqlite",),
        names=("app",),
        hits=(records.RecallHit("app", 1, "x" * 100),),
        seen=4,
        conclusion="done",
        sources=(Source("app", "Uses SQLite"),),
    )
    assert records.to_recall_record(event) == {
        "type": "recall",
        "kind": "recall",
        "at": AT,
        "agent": "codex",
        "queries": ["sqlite"],
        "hits": [{"entity": "app", "rank": 1, "text": "x" * 80}],
        "session": "1a2b3c4d",
        "step": 2,
        "total_steps": 3,
        "revises_step": 1,
        "thought": "why",
        "names": ["app"],
        "seen": 4,
        "conclusion": "done",
        "sources": [{"entityName": "app", "text": "Uses SQLite"}],
    }


def test_recall_record_keeps_search_and_open_lines_short() -> None:
    search = records.RecallEvent(
        "search",
        AT,
        "codex",
        queries=("cli",),
        hits=(records.RecallHit("cli", 1, "cli parses args"),),
    )
    opened = records.RecallEvent("open", AT, "codex", names=("app",))
    assert records.to_recall_record(search) == {
        "type": "recall",
        "kind": "search",
        "at": AT,
        "agent": "codex",
        "queries": ["cli"],
        "hits": [{"entity": "cli", "rank": 1, "text": "cli parses args"}],
    }
    assert records.to_recall_record(opened) == {
        "type": "recall",
        "kind": "open",
        "at": AT,
        "agent": "codex",
        "names": ["app"],
    }
