"""Tests for graph models and pure graph operations."""

from datetime import datetime, timedelta, timezone

import pytest

from plain_text_memory_mcp import graph
from plain_text_memory_mcp.graph import Graph, Observation, Relation, Tag

TAG_A = Tag("2026-09-29T10:00:00-04:00", "claude-code")
TAG_B = Tag("2026-09-29T11:00:00-04:00", "codex")


def _names(memory: Graph) -> list[str]:
    return [entity.name for entity in memory.entities]


def test_init_tag_formats_local_time_to_seconds() -> None:
    eastern = timezone(timedelta(hours=-4))
    moment = datetime(2026, 9, 29, 14, 3, 11, 123456, tzinfo=eastern)
    assert graph.init_tag("codex", moment) == Tag(
        "2026-09-29T14:03:11-04:00", "codex"
    )


def test_init_tag_defaults_to_now_with_offset() -> None:
    tag = graph.init_tag("codex")
    parsed = datetime.fromisoformat(tag.added_at or "")
    assert parsed.tzinfo is not None
    assert parsed.microsecond == 0


def test_build_entity_dedupes_observations() -> None:
    entity = graph.build_entity("app", "project", ["a", "b", "a"], TAG_A)
    assert entity.observations == [
        Observation("a", TAG_A),
        Observation("b", TAG_A),
    ]
    assert entity.tag == TAG_A


def test_create_entities_skips_existing_names() -> None:
    memory = Graph()
    first = graph.build_entity("app", "project", ["a"], TAG_A)
    assert graph.create_entities(memory, [first]) == [first]
    again = graph.build_entity("app", "library", ["b"], TAG_B)
    assert graph.create_entities(memory, [again]) == []
    assert memory.entities == [first]


def _graph_with(*names: str) -> Graph:
    return Graph([graph.build_entity(name, "x", [], TAG_A) for name in names])


def test_create_relations_matches_on_content_only() -> None:
    memory = _graph_with("a", "b")
    first = Relation("a", "b", "uses", TAG_A)
    same_content = Relation("a", "b", "uses", TAG_B)
    assert graph.create_relations(memory, [first, same_content]) == [first]
    assert memory.relations == [first]


def test_look_missing_names_lists_each_absent_endpoint_once() -> None:
    memory = _graph_with("app")
    assert (
        graph.look_missing_names(memory, Relation("app", "app", "x", TAG_A))
        == []
    )
    assert graph.look_missing_names(
        memory, Relation("app", "sqlte", "uses", TAG_A)
    ) == ["sqlte"]
    assert graph.look_missing_names(
        memory, Relation("ghost", "ghost", "is", TAG_A)
    ) == ["ghost"]


def test_create_relations_skips_missing_endpoints() -> None:
    memory = _graph_with("app", "sqlite")
    good = Relation("app", "sqlite", "uses", TAG_A)
    typo = Relation("app", "sqlte", "uses", TAG_A)
    assert graph.create_relations(memory, [typo, good]) == [good]
    assert memory.relations == [good]


def test_update_observations_keeps_original_tag() -> None:
    memory = Graph([graph.build_entity("app", "project", ["a"], TAG_A)])
    added = graph.update_observations(memory, "app", ["a", "b"], TAG_B)
    assert added == [Observation("b", TAG_B)]
    assert memory.entities[0].observations == [
        Observation("a", TAG_A),
        Observation("b", TAG_B),
    ]


def test_update_observations_missing_entity_raises() -> None:
    with pytest.raises(graph.EntityNotFoundError, match="ghost"):
        graph.update_observations(Graph(), "ghost", ["x"], TAG_A)


def test_remove_entities_drops_their_relations() -> None:
    memory = Graph(
        [
            graph.build_entity("a", "x", [], TAG_A),
            graph.build_entity("b", "x", [], TAG_A),
            graph.build_entity("c", "x", [], TAG_A),
        ],
        [Relation("a", "b", "uses", TAG_A), Relation("b", "c", "uses", TAG_A)],
    )
    removed, removed_relations = graph.remove_entities(memory, ["a", "ghost"])
    assert [entity.name for entity in removed] == ["a"]
    assert removed_relations == [Relation("a", "b", "uses", TAG_A)]
    assert _names(memory) == ["b", "c"]
    assert memory.relations == [Relation("b", "c", "uses", TAG_A)]


def test_remove_observations_by_text() -> None:
    memory = Graph([graph.build_entity("app", "project", ["a", "b"], TAG_A)])
    removed = graph.remove_observations(memory, "app", ["a", "zzz"])
    assert removed == [Observation("a", TAG_A)]
    assert memory.entities[0].observations == [Observation("b", TAG_A)]


def test_remove_observations_ignores_missing_entity() -> None:
    memory = Graph()
    assert graph.remove_observations(memory, "ghost", ["x"]) == []
    assert memory == Graph()


def test_remove_relations_by_key_ignores_tag() -> None:
    memory = Graph([], [Relation("a", "b", "uses", TAG_A)])
    removed = graph.remove_relations(
        memory, [("a", "b", "uses"), ("x", "y", "z")]
    )
    assert removed == [Relation("a", "b", "uses", TAG_A)]
    assert memory.relations == []


def test_filter_by_names_keeps_relations_touching_named() -> None:
    memory = Graph(
        [
            graph.build_entity("a", "x", [], TAG_A),
            graph.build_entity("b", "x", [], TAG_A),
            graph.build_entity("c", "x", [], TAG_A),
        ],
        [Relation("a", "b", "uses", TAG_A), Relation("b", "c", "uses", TAG_A)],
    )
    result = graph.filter_by_names(memory, ["a", "ghost"])
    assert _names(result) == ["a"]
    assert result.relations == [Relation("a", "b", "uses", TAG_A)]


def _tagged_graph() -> Graph:
    old = graph.build_entity("app", "project", ["Uses SQLite"], TAG_A)
    old.observations.append(Observation("Moved to Postgres", TAG_B))
    return Graph(
        [old, graph.build_entity("legacy", "x", ["untagged"], graph.UNTAGGED)],
        [
            Relation("app", "legacy", "replaces", TAG_A),
            Relation("legacy", "app", "feeds", TAG_B),
        ],
    )


def test_filter_by_tag_keeps_only_matching_entries() -> None:
    since = datetime.fromisoformat("2026-09-29T10:30:00-04:00")
    found = graph.filter_by_tag(_tagged_graph(), since=since)
    assert _names(found) == ["app"]
    assert found.entities[0].observations == [
        Observation("Moved to Postgres", TAG_B)
    ]
    assert found.relations == [Relation("legacy", "app", "feeds", TAG_B)]


def test_filter_by_tag_before_and_agent() -> None:
    before = datetime.fromisoformat("2026-09-29T10:30:00-04:00")
    found = graph.filter_by_tag(_tagged_graph(), before=before)
    assert [o.text for o in found.entities[0].observations] == ["Uses SQLite"]
    by_agent = graph.filter_by_tag(_tagged_graph(), agent="codex")
    assert [o.text for o in by_agent.entities[0].observations] == [
        "Moved to Postgres"
    ]


def test_filter_by_tag_without_filters_changes_nothing() -> None:
    memory = _tagged_graph()
    assert graph.filter_by_tag(memory) == memory


def _merge_graph() -> Graph:
    return Graph(
        [
            graph.build_entity("readinglist", "repo", ["Uses SQLite"], TAG_B),
            graph.build_entity(
                "reading_list", "project", ["Uses SQLite", "CLI app"], TAG_A
            ),
            graph.build_entity("sqlite", "library", [], TAG_A),
        ],
        [
            Relation("readinglist", "sqlite", "uses", TAG_B),
            Relation("reading_list", "sqlite", "uses", TAG_A),
            Relation("readinglist", "reading_list", "same_as", TAG_B),
        ],
    )


def test_rename_entity_moves_relations_and_keeps_tags() -> None:
    memory = _merge_graph()
    renamed = graph.rename_entity(memory, "sqlite", "sqlite3")
    assert renamed.name == "sqlite3"
    assert renamed.tag == TAG_A
    assert [r.target for r in memory.relations[:2]] == ["sqlite3", "sqlite3"]
    assert memory.relations[0].tag == TAG_B


def test_rename_entity_rejects_missing_and_taken_names() -> None:
    with pytest.raises(graph.EntityNotFoundError):
        graph.rename_entity(_merge_graph(), "ghost", "x")
    with pytest.raises(graph.EntityExistsError):
        graph.rename_entity(_merge_graph(), "sqlite", "reading_list")


def test_merge_entities_keeps_tags_and_drops_duplicates() -> None:
    memory = _merge_graph()
    merged, relations = graph.merge_entities(
        memory, "readinglist", "reading_list"
    )
    assert _names(memory) == ["reading_list", "sqlite"]
    assert merged.entity_type == "project"
    assert merged.observations == [
        Observation("Uses SQLite", TAG_A),
        Observation("CLI app", TAG_A),
    ]
    # The duplicate "uses" and the self-reference "same_as" are dropped.
    assert memory.relations == [
        Relation("reading_list", "sqlite", "uses", TAG_A)
    ]
    assert relations == []


def test_merge_entities_rejects_missing_or_same_names() -> None:
    with pytest.raises(graph.EntityNotFoundError):
        graph.merge_entities(_merge_graph(), "ghost", "reading_list")
    with pytest.raises(ValueError, match="itself"):
        graph.merge_entities(_merge_graph(), "sqlite", "sqlite")


def test_edit_observation_keeps_origin_and_records_edit() -> None:
    memory = Graph([graph.build_entity("app", "x", ["Uses SQLite"], TAG_A)])
    edited = graph.edit_observation(
        memory, "app", "Uses SQLite", "Uses Postgres", TAG_B
    )
    assert edited == Observation("Uses Postgres", TAG_A, edited=TAG_B)
    assert memory.entities[0].observations == [edited]


def test_edit_observation_rejects_bad_requests() -> None:
    memory = Graph([graph.build_entity("app", "x", ["a", "b"], TAG_A)])
    with pytest.raises(graph.EntityNotFoundError):
        graph.edit_observation(memory, "ghost", "a", "c", TAG_B)
    with pytest.raises(graph.ObservationNotFoundError):
        graph.edit_observation(memory, "app", "zzz", "c", TAG_B)
    with pytest.raises(ValueError, match="already"):
        graph.edit_observation(memory, "app", "a", "b", TAG_B)


def test_filter_by_tag_matches_edits() -> None:
    memory = Graph([graph.build_entity("app", "x", ["old"], TAG_A)])
    graph.edit_observation(memory, "app", "old", "new", TAG_B)
    found = graph.filter_by_tag(memory, agent="codex")
    assert [o.text for o in found.entities[0].observations] == ["new"]


def test_supersede_keeps_old_fact_and_points_to_new() -> None:
    memory = Graph([graph.build_entity("app", "x", ["Uses MySQL"], TAG_A)])
    retired, replacement = graph.supersede_observation(
        memory, "app", "Uses MySQL", "Uses SQLite", TAG_B
    )
    assert retired == Observation(
        "Uses MySQL", TAG_A, superseded=TAG_B, replaced_by="Uses SQLite"
    )
    assert replacement == Observation("Uses SQLite", TAG_B)
    assert memory.entities[0].observations == [retired, replacement]
    current = graph.filter_current(memory)
    assert current.entities[0].observations == [replacement]


def test_supersede_without_replacement_retires_the_fact() -> None:
    memory = Graph([graph.build_entity("app", "x", ["Has a CLI"], TAG_A)])
    retired, replacement = graph.supersede_observation(
        memory, "app", "Has a CLI", None, TAG_B
    )
    assert replacement is None
    assert retired.superseded == TAG_B
    assert retired.replaced_by is None


def test_supersede_rejects_a_fact_already_superseded() -> None:
    memory = Graph([graph.build_entity("app", "x", ["a"], TAG_A)])
    graph.supersede_observation(memory, "app", "a", "b", TAG_B)
    with pytest.raises(ValueError, match="already superseded"):
        graph.supersede_observation(memory, "app", "a", "c", TAG_B)


def test_superseding_back_revives_the_old_fact() -> None:
    memory = Graph([graph.build_entity("app", "x", ["a"], TAG_A)])
    graph.supersede_observation(memory, "app", "a", "b", TAG_B)
    _, revived = graph.supersede_observation(memory, "app", "b", "a", TAG_B)
    assert revived == Observation("a", TAG_A)


def test_add_observations_revives_a_superseded_text() -> None:
    memory = Graph([graph.build_entity("app", "x", ["a"], TAG_A)])
    graph.supersede_observation(memory, "app", "a", None, TAG_B)
    added = graph.update_observations(memory, "app", ["a"], TAG_B)
    assert added == [Observation("a", TAG_A)]


def test_sources_follow_edits_renames_and_merges() -> None:
    source = graph.Source("app", "Uses pytest")
    memory = Graph(
        [
            graph.build_entity("app", "x", ["Uses pytest"], TAG_A),
            graph.build_entity("summary", "x", [], TAG_A),
            graph.build_entity("app_twin", "x", [], TAG_A),
        ]
    )
    graph.update_observations(memory, "summary", ["Tested"], TAG_A, (source,))
    assert graph.look_missing_sources(memory, (source,)) == []

    def cited() -> tuple[graph.Source, ...]:
        summary = graph.look_entity(memory, "summary")
        assert summary is not None
        return summary.observations[0].sources

    graph.edit_observation(memory, "app", "Uses pytest", "Runs pytest", TAG_B)
    assert cited() == (graph.Source("app", "Runs pytest"),)
    graph.rename_entity(memory, "app", "app_renamed")
    assert cited() == (graph.Source("app_renamed", "Runs pytest"),)
    graph.merge_entities(memory, "app_renamed", "app_twin")
    assert cited() == (graph.Source("app_twin", "Runs pytest"),)


def test_edit_repoints_replaced_by() -> None:
    memory = Graph([graph.build_entity("app", "x", ["a"], TAG_A)])
    graph.supersede_observation(memory, "app", "a", "b", TAG_B)
    graph.edit_observation(memory, "app", "b", "b2", TAG_B)
    assert memory.entities[0].observations[0].replaced_by == "b2"
