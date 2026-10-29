"""Tests for graph models and the read-only views of a graph."""

from datetime import datetime

from plain_text_memory_mcp import graph
from plain_text_memory_mcp.graph import Entity, Graph, Note, Relation, Tag

TAG_A = Tag("2026-09-29T10:00:00-04:00", "claude-code")
TAG_B = Tag("2026-09-29T11:00:00-04:00", "codex")


def _entity(name: str, texts: list[str], tag: Tag = TAG_A) -> Entity:
    return Entity(name, "x", [Note(text, tag) for text in texts], tag)


def _names(memory: Graph) -> list[str]:
    return [entity.name for entity in memory.entities]


def test_parse_moment_reads_offsets_and_rejects_junk() -> None:
    moment = graph.parse_moment("2026-09-29T10:00:00-04:00")
    assert moment is not None
    assert moment.utcoffset() is not None
    local = graph.parse_moment("2026-09-29")
    assert local is not None
    assert local.tzinfo is not None
    assert graph.parse_moment("soon") is None
    assert graph.parse_moment(None) is None


def test_look_missing_sources_lists_unknown_notes() -> None:
    memory = Graph([_entity("app", ["Uses pytest"])])
    known = graph.Source("app", "Uses pytest")
    missing = graph.Source("app", "Uses nose")
    assert graph.look_missing_sources(memory, (known, missing)) == [missing]


def test_filter_by_names_keeps_relations_touching_named() -> None:
    memory = Graph(
        [_entity("a", []), _entity("b", []), _entity("c", [])],
        [Relation("a", "b", "uses", TAG_A), Relation("b", "c", "uses", TAG_A)],
    )
    result = graph.filter_by_names(memory, ["a", "ghost"])
    assert _names(result) == ["a"]
    assert result.relations == [Relation("a", "b", "uses", TAG_A)]


def test_filter_current_hides_struck_notes_and_keeps_entities() -> None:
    live = Note("Uses SQLite", TAG_B)
    struck = Note(
        "Uses MySQL",
        TAG_A,
        superseded=Tag("2026-09-30T09:00-04:00", None),
        replaced_by="Uses SQLite",
    )
    memory = Graph(
        [
            Entity("app", "x", [struck, live], TAG_A),
            Entity("old", "x", [struck], TAG_A),
        ]
    )
    current = graph.filter_current(memory)
    assert [e.notes for e in current.entities] == [[live], []]
    assert memory.entities[0].notes == [struck, live]


def _tagged_graph() -> Graph:
    old = _entity("app", ["Uses SQLite"])
    old.notes.append(Note("Moved to Postgres", TAG_B))
    return Graph(
        [old, _entity("legacy", ["untagged"], graph.UNTAGGED)],
        [
            Relation("app", "legacy", "replaces", TAG_A),
            Relation("legacy", "app", "feeds", TAG_B),
        ],
    )


def test_filter_by_tag_keeps_only_matching_entries() -> None:
    since = datetime.fromisoformat("2026-09-29T10:30:00-04:00")
    found = graph.filter_by_tag(_tagged_graph(), since=since)
    assert _names(found) == ["app"]
    assert found.entities[0].notes == [Note("Moved to Postgres", TAG_B)]
    assert found.relations == [Relation("legacy", "app", "feeds", TAG_B)]


def test_filter_by_tag_before_and_agent() -> None:
    before = datetime.fromisoformat("2026-09-29T10:30:00-04:00")
    found = graph.filter_by_tag(_tagged_graph(), before=before)
    assert [o.text for o in found.entities[0].notes] == ["Uses SQLite"]
    by_agent = graph.filter_by_tag(_tagged_graph(), agent="codex")
    assert [o.text for o in by_agent.entities[0].notes] == ["Moved to Postgres"]


def test_filter_by_tag_without_filters_changes_nothing() -> None:
    memory = _tagged_graph()
    assert graph.filter_by_tag(memory) == memory
