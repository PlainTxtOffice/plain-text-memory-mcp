"""Tests for finding memory files and merging them into one graph."""

import shutil
import subprocess
from pathlib import Path

import pytest

from plain_text_memory_mcp import graph
from plain_text_memory_mcp.ptm import index, parser


def _look_entity(memory: graph.Graph, name: str) -> graph.Entity | None:
    return next((e for e in memory.entities if e.name == name), None)


AGENTS_TEXT = """\
# AGENTS.md

Rules for agents.

## Checks

Run these before every commit;
CI runs them again.

```sh
pytest
```

## Commits

- Commit only when the user asks. Commit to `main`; do not create
  branches unless the user asks.
- Stage files by name.

| a | b |
| --- | --- |
"""

ROOT_MEMORY = """\
- The repo is a personal todo app. <!-- 2026-10-01T09:00-04:00 codex #aaaa -->
- uses [[sqlite]]
"""

SEARCH_MEMORY = """\
# search

Ranks notes.

## bm25.py
- Ranking uses BM25. <!-- 2026-10-09T14:02-04:00 claude-code #bbbb -->
  - ~~Ranking uses TF-IDF.~~ <!-- 2026-10-01T09:15-04:00 codex #cccc retired 2026-10-09T14:02-04:00 -->
"""


def _write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))


def _make_repo(root: Path) -> None:
    _write(root, "MEMORY.ptm.md", ROOT_MEMORY)
    _write(root, "src/search/MEMORY.ptm.md", SEARCH_MEMORY)
    _write(root, "AGENTS.md", AGENTS_TEXT)
    _write(root, "src/search/MEMORY.ptm.archive.md", "- ~~Old.~~\n")
    _write(root, ".hidden/MEMORY.ptm.md", "- Hidden.\n")
    _write(root, "src/memory.ptm.md", "- Wrong case.\n")


def test_parse_agents_file_reads_paragraphs_and_wrapped_bullets() -> None:
    memory = parser.parse_agents_file(AGENTS_TEXT, "repo")
    notes = [(bullet.entity, bullet.text) for bullet in memory.bullets]
    assert notes == [
        ("repo", "Rules for agents."),
        ("Checks", "Run these before every commit; CI runs them again."),
        (
            "Commits",
            (
                "Commit only when the user asks. Commit to `main`; do not"
                " create branches unless the user asks."
            ),
        ),
        ("Commits", "Stage files by name."),
    ]
    assert memory.entities == ("repo", "Checks", "Commits")
    assert all(bullet.stamp is None for bullet in memory.bullets)


def test_look_memory_files_walks_outside_git(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    assert index.look_memory_files(tmp_path) == [
        "AGENTS.md",
        "MEMORY.ptm.md",
        "src/search/MEMORY.ptm.md",
    ]
    assert "src/search/MEMORY.ptm.archive.md" in index.look_memory_files(
        tmp_path, with_archives=True
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_look_memory_files_follows_git_ignore_rules(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _make_repo(tmp_path)
    _write(tmp_path, ".gitignore", "build/\n")
    _write(tmp_path, "build/MEMORY.ptm.md", "- Ignored.\n")
    assert index.look_memory_files(tmp_path) == [
        ".hidden/MEMORY.ptm.md",
        "AGENTS.md",
        "MEMORY.ptm.md",
        "src/search/MEMORY.ptm.md",
    ]


def test_build_index_merges_files_into_one_graph(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    memory = index.build_index(tmp_path, {})
    names = [entity.name for entity in memory.entities]
    assert names == [tmp_path.name, "Checks", "Commits", "search", "bm25.py"]
    repo = _look_entity(memory, tmp_path.name)
    assert repo is not None
    assert {note.path for note in repo.notes} == {"AGENTS.md", "MEMORY.ptm.md"}
    assert [
        (relation.source, relation.target, relation.relation_type)
        for relation in memory.relations
    ] == [(tmp_path.name, "sqlite", "uses")]


def test_build_index_maps_stamps_and_struck_notes(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    memory = index.build_index(tmp_path, {})
    bm25 = _look_entity(memory, "bm25.py")
    assert bm25 is not None
    live, retired = bm25.notes
    assert live.tag == graph.Tag("2026-10-09T14:02-04:00", "claude-code")
    assert graph.is_current(live)
    assert not graph.is_current(retired)
    assert retired.superseded == graph.Tag("2026-10-09T14:02-04:00", None)
    assert retired.replaced_by == "Ranking uses BM25."
    assert bm25.tag == retired.tag
    search = _look_entity(memory, "search")
    assert search is not None
    assert [note.text for note in search.notes] == ["Ranks notes."]


def test_build_index_rereads_only_changed_files(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    cache: index.FileCache = {}
    index.build_index(tmp_path, cache)
    before = cache["AGENTS.md"][1]
    _write(tmp_path, "MEMORY.ptm.md", "- Changed fact.\n")
    memory = index.build_index(tmp_path, cache)
    assert cache["AGENTS.md"][1] is before
    repo = _look_entity(memory, tmp_path.name)
    assert repo is not None
    assert "Changed fact." in [note.text for note in repo.notes]


def test_build_index_drops_deleted_files_from_cache(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    cache: index.FileCache = {}
    index.build_index(tmp_path, cache)
    (tmp_path / "AGENTS.md").unlink()
    index.build_index(tmp_path, cache)
    assert "AGENTS.md" not in cache
