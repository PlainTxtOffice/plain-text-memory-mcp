"""Tests for BM25 scoring, activation, expansion, and result ranking."""

import math
from datetime import UTC, datetime, timedelta

from plain_text_memory_mcp import graph
from plain_text_memory_mcp.graph import Access, Graph, Relation, Tag
from plain_text_memory_mcp.search import activation, bm25, expansion, ranking

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
TAG_A = Tag("2026-09-29T10:00:00-04:00", "claude-code")


def _days_ago(days: float) -> Tag:
    moment = NOW - timedelta(days=days)
    return Tag(moment.isoformat(timespec="seconds"), "codex")


def _names(memory: Graph) -> list[str]:
    return [entity.name for entity in memory.entities]


def _search(
    memory: Graph, query: str, **options: object
) -> ranking.SearchResult:
    accesses = options.pop("accesses", [])
    return ranking.search(memory, query, accesses=accesses, now=NOW, **options)


def test_to_tokens_splits_identifiers_and_folds_plurals() -> None:
    assert bm25.to_tokens("reading_list Tests pass; class") == [
        "reading",
        "list",
        "test",
        "pass",
        "class",
    ]


def test_parse_query_keeps_quoted_phrases_whole() -> None:
    query = bm25.parse_query('sqlite "Uses SQLite" sqlite')
    assert query.words == ("sqlite",)
    assert query.phrases == ("uses sqlite",)


def test_rare_terms_outweigh_common_ones() -> None:
    texts = ["sqlite storage", "uses python", "uses python", "uses python"]
    index = bm25.build_index(texts)
    rare = bm25.calc_scores(index, bm25.parse_query("sqlite"))[0]
    common = bm25.calc_scores(index, bm25.parse_query("uses"))[1]
    assert rare > common > 0


def test_phrase_scores_only_where_it_appears_whole() -> None:
    index = bm25.build_index(["uses sqlite", "sqlite uses"])
    scores = bm25.calc_scores(index, bm25.parse_query('"uses sqlite"'))
    assert scores[0] > 0
    assert scores[1] == 0


def test_activation_follows_power_law_of_age() -> None:
    fresh = activation.calc_activation([NOW.isoformat()], NOW)
    old = activation.calc_activation(
        [(NOW - timedelta(days=99)).isoformat()], NOW
    )
    assert fresh == 0
    assert math.isclose(old, -0.5 * math.log(100))


def test_activation_grows_with_each_use() -> None:
    once = activation.calc_activation([_days_ago(10).added_at], NOW)
    twice = activation.calc_activation(
        [_days_ago(10).added_at, _days_ago(1).added_at], NOW
    )
    assert twice > once


def test_prior_of_untagged_memory_is_zero() -> None:
    assert activation.calc_prior([None, "not a date"], NOW) == 0


def test_pagerank_reaches_linked_nodes_only() -> None:
    rank = expansion.calc_personalized_pagerank(
        ["a", "b", "c"], [("a", "b")], {"a": 1.0}
    )
    assert rank["a"] > rank["b"] > 0
    assert rank["c"] == 0
    assert math.isclose(sum(rank.values()), 1)


def test_arrange_edges_puts_strongest_at_both_ends() -> None:
    assert ranking.arrange_edges([1, 2, 3, 4, 5]) == [1, 3, 5, 4, 2]
    assert ranking.arrange_edges([1, 2]) == [1, 2]
    assert ranking.arrange_edges([]) == []


def test_search_matches_name_type_and_text() -> None:
    memory = Graph(
        [
            graph.build_entity(
                "reading_list", "Repository", ["Uses SQLite"], TAG_A
            ),
            graph.build_entity("sqlite", "library", [], TAG_A),
            graph.build_entity("other", "thing", ["nothing here"], TAG_A),
        ],
        [
            Relation("reading_list", "sqlite", "uses", TAG_A),
            Relation("reading_list", "other", "has", TAG_A),
        ],
    )
    by_text = _search(memory, "SQLITE").memory
    assert set(_names(by_text)) == {"reading_list", "sqlite"}
    assert by_text.relations == memory.relations
    assert _names(_search(memory, "repository").memory) == ["reading_list"]


def test_search_ranks_hits_and_names_their_entities() -> None:
    memory = Graph(
        [
            graph.build_entity("csv_export", "module", ["Writes CSV"], TAG_A),
            graph.build_entity("app", "project", ["Uses SQLite"], TAG_A),
            graph.build_entity(
                "decision", "decision", ["Export CSV with SQLite rows"], TAG_A
            ),
        ]
    )
    found = _search(memory, "sqlite export")
    ranked = sorted(found.hits, key=lambda hit: hit.rank)
    assert ranked[0].entity_name == "decision"
    assert ranked[0].observation.text == "Export CSV with SQLite rows"
    assert {hit.entity_name for hit in found.hits} == {"decision", "app"}
    assert _names(found.memory)[0] == "decision"


def test_search_no_longer_matches_inside_words() -> None:
    memory = Graph([graph.build_entity("app", "x", ["A happy path"], TAG_A)])
    assert _search(memory, "py").memory.entities == []


def test_search_blank_query_returns_everything_without_hits() -> None:
    memory = Graph(
        [graph.build_entity(name, "x", [], TAG_A) for name in ("a", "b")]
    )
    found = _search(memory, "  ")
    assert _names(found.memory) == ["a", "b"]
    assert found.hits == []


def test_search_limit_caps_entities_and_hits() -> None:
    memory = Graph(
        [
            graph.build_entity(f"e{i}", "x", [f"sqlite note {i}"], TAG_A)
            for i in range(5)
        ]
    )
    found = _search(memory, "sqlite", limit=2)
    assert len(found.memory.entities) == 2
    assert sorted(hit.rank for hit in found.hits) == [1, 2]


def test_search_prefers_recent_facts_on_equal_relevance() -> None:
    memory = Graph(
        [
            graph.build_entity("old", "x", ["Uses SQLite"], _days_ago(300)),
            graph.build_entity("new", "x", ["Uses SQLite"], _days_ago(1)),
        ]
    )
    [first] = [hit for hit in _search(memory, "sqlite").hits if hit.rank == 1]
    assert first.entity_name == "new"


def test_search_prefers_often_opened_entities() -> None:
    tag = _days_ago(30)
    memory = Graph(
        [
            graph.build_entity("quiet", "x", ["Uses SQLite"], tag),
            graph.build_entity("busy", "x", ["Uses SQLite"], tag),
        ]
    )
    opens = [Access(_days_ago(d).added_at or "", "busy") for d in (1, 2, 3)]
    found = _search(memory, "sqlite", accesses=opens)
    assert _names(found.memory)[0] == "busy"


def test_search_expand_pulls_in_linked_entities() -> None:
    memory = Graph(
        [
            graph.build_entity("app", "project", ["Uses SQLite"], TAG_A),
            graph.build_entity(
                "storage_layer", "module", ["Owns files"], TAG_A
            ),
            graph.build_entity("unrelated", "module", ["Draws charts"], TAG_A),
        ],
        [Relation("app", "storage_layer", "contains", TAG_A)],
    )
    assert _names(_search(memory, "sqlite").memory) == ["app"]
    expanded = _names(_search(memory, "sqlite", expand=True).memory)
    assert expanded == ["app", "storage_layer"]


def test_filter_strongest_keeps_most_active_in_file_order() -> None:
    memory = Graph(
        [
            graph.build_entity("old", "x", [], _days_ago(300)),
            graph.build_entity("mid", "x", [], _days_ago(30)),
            graph.build_entity("new", "x", [], _days_ago(1)),
        ]
    )
    kept = ranking.filter_strongest(memory, [], NOW, 2)
    assert _names(kept) == ["mid", "new"]
