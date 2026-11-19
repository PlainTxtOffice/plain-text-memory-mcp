"""Tests for locating the server's local state and writing its logs."""

import json
import threading
import time
from pathlib import Path

import pytest

from plain_text_memory_mcp import storage
from plain_text_memory_mcp.graph import Access
from plain_text_memory_mcp.records import RecallEvent, RecallHit


def test_look_repo_root_walks_up(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)
    assert storage.look_repo_root(nested) == tmp_path


def test_look_repo_root_accepts_worktree_git_file(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
    assert storage.look_repo_root(tmp_path) == tmp_path


def test_calc_state_path_sits_in_agents_folder(tmp_path: Path) -> None:
    state = storage.calc_state_path(tmp_path)
    assert state == tmp_path / ".agents" / "ptm"
    assert storage.calc_access_path(state) == state / "access.jsonl"
    assert storage.calc_recall_path(state) == state / "recall.jsonl"


def test_lock_memory_waits_for_other_holder(tmp_path: Path) -> None:
    path = storage.calc_state_path(tmp_path)
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
    path = storage.calc_state_path(tmp_path)
    monkeypatch.setattr(storage, "_LOCK_TIMEOUT_SECONDS", 0.2)
    with (
        storage.lock_memory(path),
        pytest.raises(TimeoutError, match=r"stamp\.lock"),
        storage.lock_memory(path),
    ):
        pass


def test_access_log_round_trips_and_skips_bad_lines(tmp_path: Path) -> None:
    path = storage.calc_access_path(storage.calc_state_path(tmp_path))
    assert storage.read_accesses(path) == []
    opened = [Access("2026-10-01T09:00:00-04:00", "app")]
    storage.append_accesses(path, opened)
    with path.open("a", encoding="utf-8") as file:
        file.write('{"type": "access", "at": "2026')
    assert storage.read_accesses(path) == opened


def test_recall_log_is_on_only_for_one() -> None:
    assert storage.is_recall_log_on({"MEMORY_RECALL_LOG": "1"})
    assert storage.is_recall_log_on({"MEMORY_RECALL_LOG": " 1 "})
    assert not storage.is_recall_log_on({"MEMORY_RECALL_LOG": "true"})
    assert not storage.is_recall_log_on({"MEMORY_RECALL_LOG": "0"})
    assert not storage.is_recall_log_on({})


def test_recall_log_appends_lf_lines(tmp_path: Path) -> None:
    path = storage.calc_recall_path(storage.calc_state_path(tmp_path))
    events = [
        RecallEvent("open", "2026-10-07T09:00:00-04:00", "codex", names=("a",)),
        RecallEvent(
            "search",
            "2026-10-07T09:00:01-04:00",
            "codex",
            queries=("a",),
            hits=(RecallHit("a", 1, "text"),),
        ),
    ]
    storage.append_recall_events(path, events[:1])
    storage.append_recall_events(path, [])
    storage.append_recall_events(path, events[1:])
    raw = path.read_bytes()
    assert b"\r\n" not in raw
    lines = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    assert [line["kind"] for line in lines] == ["open", "search"]


def test_load_schema_reads_package_taxonomy() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "src" / "plain_text_memory_mcp" / "taxonomy.json"
    assert storage.load_schema() == json.loads(path.read_text(encoding="utf-8"))


def test_look_memory_root_prefers_the_git_root(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src"
    nested.mkdir()
    assert storage.look_memory_root(nested, ("AGENTS.md",)) == tmp_path


def test_look_memory_root_outside_git_needs_a_marker(tmp_path: Path) -> None:
    assert storage.look_memory_root(tmp_path, ("AGENTS.md",)) is None
    (tmp_path / "AGENTS.md").write_bytes(b"# notes\n")
    assert storage.look_memory_root(tmp_path, ("AGENTS.md",)) == tmp_path


def test_write_atomic_replaces_and_leaves_no_temp(tmp_path: Path) -> None:
    target = tmp_path / "MEMORY.ptm.md"
    target.write_bytes(b"old\n")
    storage.write_atomic(target, b"new\n")
    assert target.read_bytes() == b"new\n"
    assert [p.name for p in tmp_path.iterdir()] == ["MEMORY.ptm.md"]


def test_trim_accesses_keeps_newest_per_name_and_in_all() -> None:
    accesses = [Access(f"t{i}", "a" if i % 2 else "b") for i in range(10)]
    kept = storage.trim_accesses(accesses, keep_per_name=2, keep_total=3)
    assert kept == [Access("t7", "a"), Access("t8", "b"), Access("t9", "a")]


def test_compact_accesses_rewrites_the_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage, "ACCESS_COMPACT_AT", 4)
    monkeypatch.setattr(storage, "ACCESS_KEEP_PER_NAME", 1)
    path = tmp_path / "access.jsonl"
    accesses = [Access(f"2026-10-0{i}T00:00:00", f"e{i % 3}") for i in range(6)]
    storage.append_accesses(path, accesses)
    kept = storage.compact_accesses(path, storage.read_accesses(path))
    assert kept == accesses[-2:]
    assert storage.read_accesses(path) == kept
