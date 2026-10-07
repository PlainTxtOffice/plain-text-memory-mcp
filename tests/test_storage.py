"""Tests for locating, reading, and writing the memory file."""

import os
import threading
import time
from pathlib import Path

import pytest

from plain_text_memory_mcp import graph, storage
from plain_text_memory_mcp.graph import (
    Access,
    Entity,
    Graph,
    Header,
    Observation,
    Relation,
    Tag,
)
from plain_text_memory_mcp.records import RecordError

TAG_A = Tag("2026-09-29T10:00:00-04:00", "claude-code")
ENTITY_LINE = '{"type": "entity", "name": "a", "entityType": "x"}'


def test_look_repo_root_walks_up(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)
    assert storage.look_repo_root(nested) == tmp_path


def test_look_repo_root_accepts_worktree_git_file(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
    assert storage.look_repo_root(tmp_path) == tmp_path


def test_calc_memory_path_prefers_absolute_env(tmp_path: Path) -> None:
    target = tmp_path / "custom.jsonl"
    environ = {"MEMORY_FILE_PATH": str(target)}
    assert storage.calc_memory_path(environ, tmp_path / "other") == target


def test_calc_memory_path_relative_env_uses_cwd(tmp_path: Path) -> None:
    environ = {"MEMORY_FILE_PATH": "mem/custom.jsonl"}
    expected = tmp_path / "mem" / "custom.jsonl"
    assert storage.calc_memory_path(environ, tmp_path) == expected


def test_calc_memory_path_uses_repo_root(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src"
    nested.mkdir()
    expected = tmp_path / ".agents" / "memory.local.jsonl"
    assert storage.calc_memory_path({}, nested) == expected


def test_calc_memory_path_falls_back_to_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage, "look_repo_root", lambda start: None)
    expected = tmp_path / ".agents" / "memory.local.jsonl"
    assert storage.calc_memory_path({}, tmp_path) == expected


def test_read_graph_missing_file_is_empty(tmp_path: Path) -> None:
    assert storage.read_graph(tmp_path / "missing.jsonl") == Graph()


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    path = tmp_path / ".agents" / "memory.local.jsonl"
    memory = Graph(
        [
            Entity(
                "café", "project", [Observation("naïve — note", TAG_A)], TAG_A
            )
        ],
        [Relation("café", "café", "self", TAG_A)],
    )
    storage.write_graph(path, memory)
    assert storage.read_graph(path) == memory
    assert "naïve — note" in path.read_text(encoding="utf-8")
    assert list(path.parent.iterdir()) == [path]


def test_read_graph_tolerates_bom_crlf_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "memory.jsonl"
    content = "﻿" + ENTITY_LINE + "\r\n\r\n   \r\n"
    path.write_bytes(content.encode("utf-8"))
    expected = Graph([Entity("a", "x", [], Tag(None, None))])
    assert storage.read_graph(path) == expected


def test_read_graph_reports_bad_line_number(tmp_path: Path) -> None:
    path = tmp_path / "memory.jsonl"
    path.write_text(ENTITY_LINE + "\nnot json\n", encoding="utf-8")
    with pytest.raises(RecordError, match=r"memory\.jsonl:2:"):
        storage.read_graph(path)


def test_read_graph_reports_bad_record_line_number(tmp_path: Path) -> None:
    path = tmp_path / "memory.jsonl"
    path.write_text('{"type": "widget"}\n', encoding="utf-8")
    with pytest.raises(RecordError, match=r"memory\.jsonl:1: unknown"):
        storage.read_graph(path)


def test_write_graph_retries_locked_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "memory.jsonl"
    calls: list[str] = []
    real_replace = os.replace

    def flaky_replace(source: str, target: str) -> None:
        calls.append(source)
        if len(calls) == 1:
            raise PermissionError("locked by another process")
        real_replace(source, target)

    monkeypatch.setattr(storage.os, "replace", flaky_replace)
    monkeypatch.setattr(storage.time, "sleep", lambda seconds: None)
    storage.write_graph(path, Graph([Entity("a", "x", [], TAG_A)]))
    assert len(calls) == 2
    assert storage.read_graph(path).entities[0].name == "a"


def test_write_graph_gives_up_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def locked_replace(source: str, target: str) -> None:
        raise PermissionError("locked by another process")

    monkeypatch.setattr(storage.os, "replace", locked_replace)
    monkeypatch.setattr(storage.time, "sleep", lambda seconds: None)
    with pytest.raises(PermissionError):
        storage.write_graph(tmp_path / "memory.jsonl", Graph())
    assert list(tmp_path.iterdir()) == []


def test_write_graph_waits_out_a_longer_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "memory.jsonl"
    calls: list[str] = []
    real_replace = os.replace

    def slow_unlock_replace(source: str, target: str) -> None:
        calls.append(source)
        if len(calls) <= 5:
            raise PermissionError("locked by another process")
        real_replace(source, target)

    monkeypatch.setattr(storage.os, "replace", slow_unlock_replace)
    monkeypatch.setattr(storage.time, "sleep", lambda seconds: None)
    storage.write_graph(path, Graph([Entity("a", "x", [], TAG_A)]))
    assert len(calls) == 6


def test_read_graph_retries_locked_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "memory.jsonl"
    path.write_text(ENTITY_LINE + "\n", encoding="utf-8")
    calls: list[Path] = []
    real_read_bytes = Path.read_bytes

    def flaky_read_bytes(self: Path) -> bytes:
        calls.append(self)
        if len(calls) == 1:
            raise PermissionError("locked by another process")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", flaky_read_bytes)
    monkeypatch.setattr(storage.time, "sleep", lambda seconds: None)
    assert storage.read_graph(path).entities[0].name == "a"
    assert len(calls) == 2


def test_read_graph_reports_non_utf8_line_number(tmp_path: Path) -> None:
    path = tmp_path / "memory.jsonl"
    cp1252_line = '{"type": "entity", "name": "café", "entityType": "x"}'
    path.write_bytes(
        ENTITY_LINE.encode("utf-8") + b"\n" + cp1252_line.encode("cp1252")
    )
    with pytest.raises(RecordError, match=r"memory\.jsonl:2:"):
        storage.read_graph(path)


def test_lock_memory_waits_for_other_holder(tmp_path: Path) -> None:
    path = tmp_path / "memory.jsonl"
    events: list[str] = []
    holding = threading.Event()

    def hold_briefly() -> None:
        with storage.lock_memory(path):
            holding.set()
            time.sleep(0.3)
            events.append("first released")

    thread = threading.Thread(target=hold_briefly)
    thread.start()
    assert holding.wait(timeout=5), "first holder never took the lock"
    with storage.lock_memory(path):
        events.append("second acquired")
    thread.join()
    assert events == ["first released", "second acquired"]


def test_lock_memory_times_out_readably(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "memory.jsonl"
    monkeypatch.setattr(storage, "_LOCK_TIMEOUT_SECONDS", 0.2)
    with (
        storage.lock_memory(path),
        pytest.raises(TimeoutError, match=r"memory\.jsonl\.lock"),
        storage.lock_memory(path),
    ):
        pass


def _header() -> Header:
    return Header("repo", "D:/repo", TAG_A)


def _count_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_write_changes_appends_only_what_changed(tmp_path: Path) -> None:
    path = tmp_path / "memory.jsonl"
    memory = Graph(
        [graph.build_entity("a", "x", ["one"], TAG_A)], [], _header()
    )
    storage.write_graph(path, memory)
    before = storage.snapshot_graph(memory)
    graph.update_observations(memory, "a", ["two"], TAG_A)
    memory.entities.append(graph.build_entity("b", "x", [], TAG_A))
    storage.write_changes(path, before, memory)
    assert _count_lines(path) == 4
    assert storage.read_graph(path) == memory


def test_write_changes_tombstones_removed_records(tmp_path: Path) -> None:
    path = tmp_path / "memory.jsonl"
    memory = Graph(
        [graph.build_entity(n, "x", [], TAG_A) for n in ("a", "b")],
        [Relation("a", "b", "uses", TAG_A)],
        _header(),
    )
    storage.write_graph(path, memory)
    before = storage.snapshot_graph(memory)
    graph.remove_entities(memory, ["b"])
    storage.write_changes(path, before, memory)
    text = path.read_text(encoding="utf-8")
    assert '"type": "tombstone", "entity": "b"' in text
    assert '"type": "tombstone", "from": "a"' in text
    assert storage.read_graph(path) == memory


def test_write_changes_writes_nothing_when_nothing_changed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "memory.jsonl"
    memory = Graph([graph.build_entity("a", "x", [], TAG_A)], [], _header())
    storage.write_graph(path, memory)
    before_bytes = path.read_bytes()
    storage.write_changes(path, storage.snapshot_graph(memory), memory)
    assert path.read_bytes() == before_bytes


def test_write_changes_compacts_a_long_log(tmp_path: Path) -> None:
    path = tmp_path / "memory.jsonl"
    memory = Graph([graph.build_entity("a", "x", [], TAG_A)], [], _header())
    storage.write_graph(path, memory)
    for count in range(150):
        before = storage.snapshot_graph(memory)
        graph.update_observations(memory, "a", [f"fact {count}"], TAG_A)
        storage.write_changes(path, before, memory)
    assert _count_lines(path) < 2 + 105
    assert storage.read_graph(path) == memory


def test_write_changes_rewrites_when_header_changes(tmp_path: Path) -> None:
    path = tmp_path / "memory.jsonl"
    memory = Graph([graph.build_entity("a", "x", [], TAG_A)])
    storage.write_graph(path, memory)
    before = storage.snapshot_graph(memory)
    memory.header = _header()
    storage.write_changes(path, before, memory)
    assert _count_lines(path) == 2
    assert storage.read_graph(path) == memory


def test_write_changes_rewrites_after_a_missing_final_newline(
    tmp_path: Path,
) -> None:
    path = tmp_path / "memory.jsonl"
    memory = Graph([graph.build_entity("a", "x", [], TAG_A)], [], _header())
    storage.write_graph(path, memory)
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    before = storage.snapshot_graph(memory)
    memory.entities.append(graph.build_entity("b", "x", [], TAG_A))
    storage.write_changes(path, before, memory)
    assert _count_lines(path) == 3
    assert storage.read_graph(path) == memory


def test_read_graph_lets_later_lines_replace_earlier(tmp_path: Path) -> None:
    path = tmp_path / "memory.jsonl"
    path.write_text(
        '{"type": "entity", "name": "a", "entityType": "old"}\n'
        '{"type": "entity", "name": "b", "entityType": "x"}\n'
        '{"type": "entity", "name": "a", "entityType": "new"}\n'
        '{"type": "tombstone", "entity": "b"}\n',
        encoding="utf-8",
    )
    [entity] = storage.read_graph(path).entities
    assert (entity.name, entity.entity_type) == ("a", "new")


def test_access_log_round_trips_and_skips_bad_lines(tmp_path: Path) -> None:
    path = storage.calc_access_path(tmp_path / "memory.local.jsonl")
    assert path.name == "memory.local.access.jsonl"
    assert storage.read_accesses(path) == []
    opened = [Access("2026-10-01T09:00:00-04:00", "app")]
    storage.append_accesses(path, opened)
    with path.open("a", encoding="utf-8") as file:
        file.write('{"type": "access", "at": "2026')
    assert storage.read_accesses(path) == opened
