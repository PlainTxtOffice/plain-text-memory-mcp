"""Tests for the header record that ties a memory file to its repo."""

import sys
from pathlib import Path

import pytest

from plain_text_memory_mcp import graph, records, storage
from plain_text_memory_mcp.graph import Entity, Graph, Header, Tag
from plain_text_memory_mcp.records import RecordError

TAG_A = Tag("2026-09-29T10:00:00-04:00", "claude-code")
ENTITY_LINE = '{"type": "entity", "name": "a", "entityType": "x"}'
# Backslashes and lowercase drive letters are Windows spellings of a path.
WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows path spelling"
)


def test_init_header_names_repo_folder(tmp_path: Path) -> None:
    repo_root = tmp_path / "reading_list"
    header = graph.init_header(repo_root, TAG_A)
    assert header == Header("reading_list", repo_root.as_posix(), TAG_A)


def test_header_record_round_trip() -> None:
    header = Header("reading_list", "D:/projects/reading_list", TAG_A)
    record = records.to_header_record(header)
    assert record == {
        "type": "header",
        "repo_name": "reading_list",
        "repo_root": "D:/projects/reading_list",
        "added_at": "2026-09-29T10:00:00-04:00",
        "agent": "claude-code",
    }
    assert records.parse_record(record) == header


def test_header_record_requires_repo_root() -> None:
    with pytest.raises(RecordError):
        records.parse_record({"type": "header", "repo_name": "x"})


def test_write_graph_puts_header_first(tmp_path: Path) -> None:
    path = tmp_path / "memory.jsonl"
    header = Header("repo", "D:/repo", TAG_A)
    memory = Graph([Entity("a", "x", [], TAG_A)], [], header)
    storage.write_graph(path, memory)
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    assert '"type": "header"' in first_line
    assert storage.read_graph(path) == memory


def test_read_graph_without_header_has_none(tmp_path: Path) -> None:
    path = tmp_path / "memory.jsonl"
    path.write_text(ENTITY_LINE + "\n", encoding="utf-8")
    assert storage.read_graph(path).header is None


def test_read_graph_rejects_second_header(tmp_path: Path) -> None:
    path = tmp_path / "memory.jsonl"
    header_line = (
        '{"type": "header", "repo_name": "r", "repo_root": "D:/r",'
        ' "added_at": null, "agent": null}'
    )
    path.write_text(f"{header_line}\n{header_line}\n", encoding="utf-8")
    with pytest.raises(RecordError, match=r"memory\.jsonl:2: .*header"):
        storage.read_graph(path)


@pytest.mark.parametrize(
    "recorded",
    [
        "D:/projects/reading_list",
        pytest.param("d:\\projects\\reading_list", marks=WINDOWS_ONLY),
        pytest.param("\\\\?\\D:\\projects\\reading_list", marks=WINDOWS_ONLY),
        "D:/projects/reading_list/",
    ],
)
def test_is_same_repo_ignores_spelling(recorded: str) -> None:
    repo_root = Path("D:/projects/reading_list")
    assert storage.is_same_repo(recorded, repo_root)


def test_is_same_repo_detects_other_repo() -> None:
    repo_root = Path("D:/projects/new_project")
    recorded = "D:/templates/python-template"
    assert not storage.is_same_repo(recorded, repo_root)


def test_backup_memory_renames_file(tmp_path: Path) -> None:
    path = tmp_path / "memory.local.jsonl"
    path.write_text(ENTITY_LINE + "\n", encoding="utf-8")
    backup = storage.backup_memory(path, "20260929T031500")
    assert backup == tmp_path / "memory.local.jsonl.bak-20260929T031500"
    assert not path.exists()
    assert backup.read_text(encoding="utf-8") == ENTITY_LINE + "\n"
