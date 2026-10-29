"""Find the memory files in a repo and merge them into one graph.

- MEMORY.ptm.md files hold the memory this server stamps; AGENTS.md files
  are read-only sources. Archives are read only when asked for.
- Parsed files are cached by mtime and size, so a long-running server
  re-reads only the files that changed.
- An entity named in several files becomes one entity; each note keeps the
  path of the file it came from.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePosixPath

from plain_text_memory_mcp.graph import (
    UNTAGGED,
    Entity,
    Graph,
    Note,
    Relation,
    Tag,
    parse_moment,
)
from plain_text_memory_mcp.ptm import parser
from plain_text_memory_mcp.ptm.parser import Bullet, MemoryFile
from plain_text_memory_mcp.ptm.stamps import Stamp

AGENTS_FILE_NAME = "AGENTS.md"
SOURCE_NAMES = (parser.FILE_NAME, AGENTS_FILE_NAME)

# Folders the walk skips when the repo is not under git; dot folders are
# always skipped.
_SKIPPED_FOLDERS = frozenset({"node_modules", "__pycache__"})

FileCache = dict[str, tuple[tuple[int, int], MemoryFile]]


def _list_git_files(root: Path, names: tuple[str, ...]) -> list[str] | None:
    pathspecs = [f":(glob)**/{name}" for name in names]
    command = [
        "git",
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        *pathspecs,
    ]
    try:
        result = subprocess.run(
            command, cwd=root, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.decode("utf-8").split("\0")


def _walk_files(root: Path, names: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for folder, subfolders, files in os.walk(root):
        subfolders[:] = [
            name
            for name in subfolders
            if not name.startswith(".") and name not in _SKIPPED_FOLDERS
        ]
        found.extend(
            Path(folder, name).relative_to(root).as_posix()
            for name in files
            if name in names
        )
    return found


def look_memory_files(root: Path, *, with_archives: bool = False) -> list[str]:
    """Return the repo-relative paths of memory files under `root`, sorted.

    - Under git, lists tracked files plus untracked ones that are not
      ignored; otherwise walks `root`, skipping dot folders.
    - File names match case-sensitively, even on Windows.
    """
    names: tuple[str, ...] = SOURCE_NAMES
    if with_archives:
        names = (*names, parser.ARCHIVE_FILE_NAME)
    listed = _list_git_files(root, names) if (root / ".git").exists() else None
    paths = listed if listed is not None else _walk_files(root, names)
    return sorted(
        {
            path
            for path in paths
            if PurePosixPath(path).name in names and (root / path).is_file()
        }
    )


def calc_default_name(root: Path, path: str) -> str:
    """Return the folder entity name for a file: its folder, or the repo."""
    folder = PurePosixPath(path).parent
    return folder.name or root.name


def read_memory_file(root: Path, path: str, cache: FileCache) -> MemoryFile:
    """Return the parsed file at `path`, re-reading it only if it changed.

    - AGENTS.md is parsed as a read-only source; any other name as a
      MEMORY.ptm.md file.
    """
    stat = (root / path).stat()
    key = (stat.st_mtime_ns, stat.st_size)
    cached = cache.get(path)
    if cached is not None and cached[0] == key:
        return cached[1]
    text = (root / path).read_bytes().decode("utf-8", errors="replace")
    name = calc_default_name(root, path)
    if PurePosixPath(path).name == AGENTS_FILE_NAME:
        memory_file = parser.parse_agents_file(text, name)
    else:
        memory_file = parser.parse_file(text, name)
    cache[path] = (key, memory_file)
    return memory_file


def _to_tag(stamp: Stamp | None) -> Tag:
    return Tag(stamp.added_at, stamp.agent) if stamp else UNTAGGED


def _to_note(bullet: Bullet, by_line: dict[int, Bullet], path: str) -> Note:
    if not bullet.struck:
        return Note(bullet.text, _to_tag(bullet.stamp), path=path)
    retired_at = bullet.stamp.retired_at if bullet.stamp else None
    parent = by_line.get(bullet.parent) if bullet.parent is not None else None
    replaced_by = parent.text if parent and not parent.struck else None
    return Note(
        bullet.text,
        _to_tag(bullet.stamp),
        superseded=Tag(retired_at, None),
        replaced_by=replaced_by,
        path=path,
    )


def _calc_entity_tag(entity: Entity) -> Tag:
    dated = [
        (moment, note.tag)
        for note in entity.notes
        if (moment := parse_moment(note.tag.added_at)) is not None
    ]
    return min(dated, key=lambda pair: pair[0])[1] if dated else UNTAGGED


def build_graph(files: list[tuple[str, MemoryFile]]) -> Graph:
    """Return one graph holding every entity, note, and relation in `files`.

    - A folder summary is indexed as an untagged note on the folder entity.
    - A live relation bullet becomes a relation; a struck one stays a
      retired note, so its history is kept.
    - An entity's tag is that of its earliest stamped note.
    """
    entities: dict[str, Entity] = {}
    relations: dict[tuple[str, str, str], Relation] = {}
    for path, memory_file in files:
        for name in memory_file.entities:
            entities.setdefault(name, Entity(name, "", [], UNTAGGED))
        if memory_file.summary:
            folder = entities[memory_file.folder_entity]
            folder.notes.append(Note(memory_file.summary, UNTAGGED, path=path))
        by_line = {bullet.line: bullet for bullet in memory_file.bullets}
        for bullet in memory_file.bullets:
            if bullet.relation and not bullet.struck:
                verb, target = bullet.relation
                relations.setdefault(
                    (bullet.entity, target, verb),
                    Relation(
                        bullet.entity, target, verb, _to_tag(bullet.stamp)
                    ),
                )
                continue
            entities[bullet.entity].notes.append(
                _to_note(bullet, by_line, path)
            )
    for entity in entities.values():
        entity.tag = _calc_entity_tag(entity)
    return Graph(list(entities.values()), list(relations.values()))


def build_index(
    root: Path, cache: FileCache, *, with_archives: bool = False
) -> Graph:
    """Return the graph of every memory file under `root`.

    - Drops cache entries for files that no longer exist.
    """
    paths = look_memory_files(root, with_archives=with_archives)
    for gone in set(cache) - set(paths):
        del cache[gone]
    files = [(path, read_memory_file(root, path, cache)) for path in paths]
    return build_graph(files)
