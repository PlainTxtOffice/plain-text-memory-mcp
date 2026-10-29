"""Tests for step-by-step recall: sessions, dedupe, and the recall tool."""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, Implementation

from plain_text_memory_mcp import storage
from plain_text_memory_mcp.graph import (
    Entity,
    Graph,
    Note,
    Relation,
    Tag,
)
from plain_text_memory_mcp.search import ranking
from plain_text_memory_mcp.search.recall import (
    AUTO_OPEN_LIMIT,
    AUTO_OPEN_MAX_FACTS,
    STEP_HIT_LIMIT,
    UNOPENED_LIMIT,
    Session,
    SessionRegistry,
    StepHits,
    calc_step_hits,
    update_opened,
)
from plain_text_memory_mcp.server import build_server

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
TAG = Tag("2026-10-01T10:00:00-04:00", "codex")


def _entity(name: str, *texts: str) -> Entity:
    return Entity(name, "module", [Note(t, TAG) for t in texts], TAG)


# Facts no query matches; they lift an entity past the auto-open size so
# tests about hits, dedupe, and sessions see hits rather than entities.
PADDING = [f"padding line {i}" for i in range(AUTO_OPEN_MAX_FACTS)]


def _big(name: str, *texts: str) -> Entity:
    return _entity(name, *texts, *PADDING)


def _memory() -> Graph:
    return Graph(
        entities=[
            _big("app", "app stores notes in sqlite", "app has a cli"),
            _big("sqlite", "sqlite runs in wal mode"),
            _big("cli", "cli parses args with click"),
            _big("docs", "docs live in the docs folder"),
        ],
        relations=[
            Relation("app", "sqlite", "uses", TAG),
            Relation("app", "cli", "has", TAG),
            Relation("docs", "app", "describes", TAG),
        ],
    )


def _step(memory: Graph, queries: list[str], session: Session) -> StepHits:
    return calc_step_hits(memory, queries, session, accesses=[], now=NOW)


def _texts(found: StepHits) -> set[str]:
    return {hit.note.text for hit in found.hits}


def test_registry_inits_unique_sessions_and_looks_them_up() -> None:
    registry = SessionRegistry()
    first = registry.init()
    second = registry.init()
    assert first.session_id != second.session_id
    assert len(first.session_id) == 8
    int(first.session_id, 16)
    assert registry.look(first.session_id) is first
    assert registry.look("missing") is None
    assert registry.look(None) is None


def test_later_steps_skip_hits_already_returned() -> None:
    memory = _memory()
    session = SessionRegistry().init()
    first = _step(memory, ["sqlite"], session)
    second = _step(memory, ["sqlite", "cli"], session)
    assert _texts(first) == {
        "app stores notes in sqlite",
        "sqlite runs in wal mode",
    }
    assert _texts(second) == {"app has a cli", "cli parses args with click"}
    assert second.seen == 2


def test_step_caps_hits_and_puts_strongest_at_edges() -> None:
    memory = Graph(
        entities=[_big(f"e{i}", f"sqlite note {i}") for i in range(12)]
    )
    session = SessionRegistry().init()
    found = _step(memory, ["sqlite", "note", "sqlite note"], session)
    assert len(found.hits) == STEP_HIT_LIMIT
    assert [hit.rank for hit in found.hits] == [1, 3, 5, 7, 8, 6, 4, 2]
    assert len(_texts(found)) == STEP_HIT_LIMIT
    later = _step(memory, ["sqlite"], session)
    assert len(later.hits) == 4
    assert later.seen == STEP_HIT_LIMIT


def test_unopened_lists_linked_entities_not_opened_or_hit() -> None:
    memory = _memory()
    session = SessionRegistry().init()
    session.opened.add("cli")
    assert _step(memory, ["wal"], session).unopened == ["app"]
    assert _step(memory, ["notes"], session).unopened == ["sqlite", "docs"]


def test_step_without_queries_returns_nothing() -> None:
    found = _step(_memory(), [], SessionRegistry().init())
    assert found == StepHits([], 0, [], [])


def test_step_without_words_skips_indexing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_: object) -> None:
        raise AssertionError("indexed a step with nothing to search")

    memory = _memory()
    expected = _step(memory, ["", "  "], SessionRegistry().init())
    monkeypatch.setattr(ranking, "prepare_corpus", fail)
    assert _step(memory, [], SessionRegistry().init()) == StepHits(
        [], 0, [], []
    )
    assert _step(memory, ["", "  "], SessionRegistry().init()) == expected


def _hub_memory() -> Graph:
    """A todo_txt-shaped graph: a large hub and a small settings entity."""
    hub_facts = [f"repo fact {i} about todo files" for i in range(9)]
    return Graph(
        entities=[
            _entity("hub", *hub_facts),
            _entity(
                "settings",
                "settings.json points at the live dropbox todo file",
                "tests pass temporary paths to load_settings",
                "save_settings writes atomically",
            ),
            *(_entity(f"small{i}", f"small {i} todo note") for i in range(4)),
        ],
        relations=[Relation("hub", "settings", "contains", TAG)],
    )


def test_small_hit_entity_comes_back_whole() -> None:
    session = SessionRegistry().init()
    found = _step(_hub_memory(), ["dropbox"], session)
    assert found.auto_opened == ["settings"]
    assert found.hits == []
    assert "settings" in session.opened
    later = _step(_hub_memory(), ["temporary paths"], session)
    assert later.hits == []
    assert later.auto_opened == []
    assert later.seen == 1


def test_large_hit_entity_stays_closed() -> None:
    found = _step(_hub_memory(), ["repo fact"], SessionRegistry().init())
    assert found.auto_opened == []
    assert {hit.entity_name for hit in found.hits} == {"hub"}


def test_auto_open_is_capped_per_step() -> None:
    found = _step(_hub_memory(), ["small todo"], SessionRegistry().init())
    assert len(found.auto_opened) == AUTO_OPEN_LIMIT
    opened = set(found.auto_opened)
    assert all(hit.entity_name not in opened for hit in found.hits)


def test_opened_entity_is_not_auto_opened_again() -> None:
    session = SessionRegistry().init()
    session.opened.add("settings")
    found = _step(_hub_memory(), ["dropbox"], session)
    assert found.auto_opened == []
    assert [hit.entity_name for hit in found.hits] == ["settings"]


ENTITIES = [
    {
        "name": "app",
        "entityType": "project",
        "notes": [
            "app stores notes in sqlite",
            "app has a cli",
            *PADDING,
        ],
    },
    {
        "name": "sqlite",
        "entityType": "library",
        "notes": ["sqlite runs in wal mode", *PADDING],
    },
    {
        "name": "cli",
        "entityType": "module",
        "notes": ["cli parses args with click", *PADDING],
    },
]
RELATIONS = [
    {"from": "app", "to": "sqlite", "relationType": "uses"},
    {"from": "app", "to": "cli", "relationType": "has"},
]
STEP = {
    "thought": "find storage facts",
    "step": 1,
    "total_steps": 2,
    "next_step_needed": True,
}


def _run_calls(
    server: MCPServer, calls: list[tuple[str, dict]]
) -> list[CallToolResult]:
    async def scenario() -> list[CallToolResult]:
        info = Implementation(name="claude-code", version="0")
        async with Client(server, client_info=info) as client:
            return [await client.call_tool(name, args) for name, args in calls]

    return anyio.run(scenario)


def _call(server: MCPServer, name: str, args: dict) -> CallToolResult:
    [result] = _run_calls(server, [(name, args)])
    return result


def _content(result: CallToolResult) -> dict:
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


def _to_markdown(entities: list[dict], relations: list[dict]) -> str:
    """Return entities and relations written as a MEMORY.ptm.md file."""
    lines: list[str] = []
    for entity in entities:
        lines += [f"## {entity['name']}", *(f"- {t}" for t in entity["notes"])]
        lines += [
            f"- {r['relationType']} [[{r['to']}]]"
            for r in relations
            if r["from"] == entity["name"]
        ]
    return "\n".join(lines) + "\n"


def _write_memory(root: Path, text: str, path: str = "MEMORY.ptm.md") -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))


def _server(tmp_path: Path, *, recall_log: bool = False) -> MCPServer:
    state = storage.calc_state_path(tmp_path)
    return build_server(state, None, tmp_path, recall_log=recall_log)


def _seeded(tmp_path: Path, *, recall_log: bool = False) -> MCPServer:
    _write_memory(tmp_path, _to_markdown(ENTITIES, RELATIONS))
    return _server(tmp_path, recall_log=recall_log)


def _hit_texts(found: dict) -> set[str]:
    return {hit["note"]["text"] for hit in found["hits"]}


def test_recall_steps_share_a_session(tmp_path: Path) -> None:
    server = _seeded(tmp_path)
    first = _content(_call(server, "recall", {**STEP, "queries": ["sqlite"]}))
    second = _content(
        _call(
            server,
            "recall",
            {
                **STEP,
                "step": 2,
                "queries": ["sqlite", "cli"],
                "session": first["session"],
            },
        )
    )
    assert second["session"] == first["session"]
    assert _hit_texts(first).isdisjoint(_hit_texts(second))
    assert second["seen"] == 2
    assert first["unopened"] == ["cli"]


def test_unknown_session_starts_fresh(tmp_path: Path) -> None:
    server = _seeded(tmp_path)
    found = _content(
        _call(
            server,
            "recall",
            {**STEP, "queries": ["sqlite"], "session": "deadbeef"},
        )
    )
    assert found["session"] != "deadbeef"
    assert found["seen"] == 0
    assert len(found["hits"]) == 2


def test_sessions_do_not_share_dedupe(tmp_path: Path) -> None:
    server = _seeded(tmp_path)
    first, second = (
        _content(r)
        for r in _run_calls(
            server,
            [
                ("recall", {**STEP, "queries": ["sqlite"]}),
                ("recall", {**STEP, "queries": ["sqlite"]}),
            ],
        )
    )
    assert first["session"] != second["session"]
    assert _hit_texts(first) == _hit_texts(second)


def test_recall_opens_entities_and_logs_access(tmp_path: Path) -> None:
    server = _seeded(tmp_path)
    found = _content(
        _call(server, "recall", {**STEP, "queries": ["wal"], "open": ["app"]})
    )
    assert [entity["name"] for entity in found["entities"]] == ["app"]
    assert {r["to"] for r in found["relations"]} == {"sqlite", "cli"}
    assert found["unopened"] == []
    access_path = storage.calc_access_path(storage.calc_state_path(tmp_path))
    accesses = storage.read_accesses(access_path)
    assert [access.entity_name for access in accesses] == ["app"]


def test_recall_ignores_unknown_open_names(tmp_path: Path) -> None:
    server = _seeded(tmp_path)
    found = _content(_call(server, "recall", {**STEP, "open": ["ghost"]}))
    assert found["entities"] == []
    access_path = storage.calc_access_path(storage.calc_state_path(tmp_path))
    assert storage.read_accesses(access_path) == []


def test_recall_hides_superseded_facts(tmp_path: Path) -> None:
    server = _seeded(tmp_path)
    text = (tmp_path / "MEMORY.ptm.md").read_bytes().decode("utf-8")
    struck = text.replace(
        "- sqlite runs in wal mode",
        "- sqlite runs in rollback mode\n  - ~~sqlite runs in wal mode~~",
    )
    _write_memory(tmp_path, struck)
    found = _content(_call(server, "recall", {**STEP, "queries": ["mode"]}))
    assert _hit_texts(found) == {"sqlite runs in rollback mode"}


def test_step_past_total_raises_total(tmp_path: Path) -> None:
    server = _seeded(tmp_path)
    found = _content(_call(server, "recall", {**STEP, "step": 3}))
    assert found["total_steps"] == 3


def test_revises_step_must_name_an_earlier_step(tmp_path: Path) -> None:
    server = _seeded(tmp_path)
    assert _call(server, "recall", {**STEP, "revises_step": 1}).is_error
    first = _content(_call(server, "recall", STEP))
    revised = _call(
        server,
        "recall",
        {**STEP, "step": 2, "revises_step": 1, "session": first["session"]},
    )
    assert not revised.is_error


def test_last_step_needs_a_conclusion(tmp_path: Path) -> None:
    server = _seeded(tmp_path)
    last = {**STEP, "next_step_needed": False}
    assert _call(server, "recall", last).is_error
    assert _call(server, "recall", {**last, "conclusion": "   "}).is_error
    sources = [
        {"entityName": "app", "text": "app has a cli"},
        {"entityName": "app", "text": "nope"},
    ]
    found = _content(
        _call(
            server,
            "recall",
            {**last, "conclusion": "app has a cli", "sources": sources},
        )
    )
    assert found["next_step_needed"] is False
    [warning] = found["warnings"]
    assert "nope" in warning


def test_failed_last_step_keeps_hits_for_retry(tmp_path: Path) -> None:
    server = _seeded(tmp_path)
    first = _content(_call(server, "recall", STEP))
    last = {
        **STEP,
        "step": 2,
        "next_step_needed": False,
        "queries": ["wal"],
        "session": first["session"],
    }
    assert _call(server, "recall", last).is_error
    retried = _content(
        _call(server, "recall", {**last, "conclusion": "sqlite uses wal"})
    )
    assert _hit_texts(retried) == {"sqlite runs in wal mode"}


def test_recall_log_is_off_by_default(tmp_path: Path) -> None:
    server = _seeded(tmp_path)
    _run_calls(
        server,
        [
            ("recall", {**STEP, "queries": ["wal"]}),
            ("search_nodes", {"query": "cli"}),
            ("open_nodes", {"names": ["app"]}),
        ],
    )
    assert not storage.calc_recall_path(
        storage.calc_state_path(tmp_path)
    ).exists()


def test_recall_log_records_steps_searches_and_opens(tmp_path: Path) -> None:
    server = _seeded(tmp_path, recall_log=True)
    _run_calls(
        server,
        [
            ("recall", {**STEP, "queries": ["wal"]}),
            ("search_nodes", {"query": "cli"}),
            ("open_nodes", {"names": ["app"]}),
        ],
    )
    path = storage.calc_recall_path(storage.calc_state_path(tmp_path))
    lines = [json.loads(line) for line in path.read_bytes().splitlines()]
    assert [line["kind"] for line in lines] == ["recall", "search", "open"]
    step, search, opened = lines
    assert step["thought"] == "find storage facts"
    assert step["queries"] == ["wal"]
    assert [hit["entity"] for hit in step["hits"]] == ["sqlite"]
    assert step["agent"] == "claude-code"
    assert search["queries"] == ["cli"]
    assert opened["names"] == ["app"]


def test_recall_log_failure_never_fails_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_: object) -> None:
        raise OSError("disk full")

    server = _seeded(tmp_path, recall_log=True)
    monkeypatch.setattr(storage, "append_recall_events", fail)
    found = _content(_call(server, "recall", {**STEP, "queries": ["wal"]}))
    assert _hit_texts(found) == {"sqlite runs in wal mode"}


TOPICS = ("sqlite", "cache", "auth", "build", "release", "search", "export")


def _size(result: CallToolResult) -> int:
    return len(json.dumps(_content(result), ensure_ascii=False))


def test_recall_costs_less_than_search_open_or_reading_the_file(
    tmp_path: Path,
) -> None:
    entities = [
        {
            "name": f"{topic}-{i}",
            "entityType": "module",
            "notes": [
                f"{topic} part {i} detail {j} about the storage layer"
                for j in range(4)
            ],
        }
        for topic in TOPICS
        for i in range(6)
    ]
    relations = [
        {
            "from": f"{topic}-{i}",
            "to": f"{topic}-{i + 1}",
            "relationType": "uses",
        }
        for topic in TOPICS
        for i in range(5)
    ]
    text = _to_markdown(entities, relations)
    _write_memory(tmp_path, text)
    server = _server(tmp_path)
    query = "sqlite storage"
    names = ["sqlite-0", "sqlite-1"]
    search, opened = _run_calls(
        server,
        [
            ("search_nodes", {"query": query}),
            ("open_nodes", {"names": names}),
        ],
    )
    first = _call(server, "recall", {**STEP, "queries": [query]})
    session = _content(first)["session"]
    steps = [
        first,
        _call(
            server,
            "recall",
            {**STEP, "step": 2, "open": names, "session": session},
        ),
        _call(
            server,
            "recall",
            {
                **STEP,
                "step": 3,
                "total_steps": 3,
                "next_step_needed": False,
                "conclusion": "sqlite parts sit on the storage layer",
                "session": session,
            },
        ),
    ]
    recall_size = sum(_size(result) for result in steps)
    assert recall_size <= _size(search) + _size(opened)
    # The point of the server: cheaper than reading the memory file whole.
    assert recall_size < len(text)


def test_stale_session_revising_a_step_starts_fresh(tmp_path: Path) -> None:
    server = _seeded(tmp_path)
    found = _content(
        _call(
            server,
            "recall",
            {
                **STEP,
                "step": 2,
                "revises_step": 1,
                "queries": ["wal"],
                "session": "deadbeef",
            },
        )
    )
    assert found["session"] != "deadbeef"
    assert _hit_texts(found) == {"sqlite runs in wal mode"}
    [warning] = found["warnings"]
    assert "deadbeef" in warning
    assert found["session"] in warning


def test_unopened_is_capped_and_ranks_shared_links_first() -> None:
    spokes = [_entity(f"s{i}", f"spoke {i}") for i in range(12)]
    memory = Graph(
        entities=[
            _entity("hub", "hub holds wal notes"),
            _entity("side", "side holds wal notes"),
            *spokes,
        ],
        relations=[
            *(Relation("hub", s.name, "has", TAG) for s in spokes),
            Relation("side", "s11", "has", TAG),
        ],
    )
    found = _step(memory, ["wal"], SessionRegistry().init())
    assert len(found.unopened) == UNOPENED_LIMIT
    assert found.unopened[0] == "s11"


def test_step_hits_wait_for_the_session_lock() -> None:
    session = SessionRegistry().init()
    results: list[StepHits] = []
    with session.lock:
        worker = threading.Thread(
            target=lambda: results.append(_step(_memory(), ["wal"], session))
        )
        worker.start()
        worker.join(0.2)
        assert worker.is_alive()
    worker.join(5)
    assert len(results) == 1


def test_recall_returns_small_hit_entities_without_logging_access(
    tmp_path: Path,
) -> None:
    server = _seeded(tmp_path)
    _write_memory(
        tmp_path,
        "## journal\n- journal writes frames\n- journal syncs on close\n",
        "src/journal/MEMORY.ptm.md",
    )
    found = _content(_call(server, "recall", {**STEP, "queries": ["frames"]}))
    assert found["hits"] == []
    [entity] = found["entities"]
    assert entity["name"] == "journal"
    assert len(entity["notes"]) == 2
    access_path = storage.calc_access_path(storage.calc_state_path(tmp_path))
    assert storage.read_accesses(access_path) == []


def test_name_match_auto_opens_small_entity() -> None:
    memory = Graph(
        entities=[_entity("settings", "Tests must use temporary paths.")]
    )
    found = _step(memory, ["settings"], SessionRegistry().init())
    assert found.auto_opened == ["settings"]
    assert found.hits == []


def test_large_name_match_leads_unopened() -> None:
    memory = Graph(
        entities=[
            _big("settings", "defaults live in code"),
            _big("app", "app reads settings files"),
        ],
        relations=[Relation("app", "cli", "has", TAG)],
    )
    found = _step(memory, ["settings"], SessionRegistry().init())
    assert found.auto_opened == []
    assert found.unopened[0] == "settings"
    assert [hit.entity_name for hit in found.hits] == ["app"]


def test_opened_entity_facts_do_not_return_as_hits() -> None:
    memory = _memory()
    session = SessionRegistry().init()
    update_opened(session, [memory.entities[0]])
    found = _step(memory, ["notes"], session)
    assert found.hits == []
    assert found.seen == 1
    assert "app" in session.opened


def test_recall_open_then_search_returns_no_repeats(tmp_path: Path) -> None:
    server = _seeded(tmp_path)
    first = _content(_call(server, "recall", {**STEP, "open": ["app"]}))
    second = _content(
        _call(
            server,
            "recall",
            {
                **STEP,
                "step": 2,
                "queries": ["notes"],
                "session": first["session"],
            },
        )
    )
    assert second["hits"] == []
    assert second["seen"] == 1


def test_recall_path_ranks_notes_from_covering_files_first(
    tmp_path: Path,
) -> None:
    padding = "".join(f"- {line}\n" for line in PADDING)
    _write_memory(tmp_path, f"## cache\n- cache keys use sha1\n{padding}")
    _write_memory(
        tmp_path,
        f"## store\n- store keys use sha1\n{padding}",
        "src/store/MEMORY.ptm.md",
    )
    server = _server(tmp_path)
    step = {**STEP, "queries": ["keys sha1"]}
    plain, scoped = (
        _content(_call(server, "recall", args))
        for args in (step, {**step, "path": "src/store/db.py"})
    )

    def by_rank(found: dict) -> list[str]:
        hits = sorted(found["hits"], key=lambda hit: hit["rank"])
        return [hit["entityName"] for hit in hits]

    assert by_rank(plain) == ["cache", "store"]
    assert by_rank(scoped) == ["store", "cache"]
