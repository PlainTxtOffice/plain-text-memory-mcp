"""Locate, read, and write the JSONL memory file and its access log.

- The memory file is a log: a snapshot of one line per record, then lines
  appended by later writes. A later line for the same entity or relation
  replaces the earlier one, and a tombstone line removes it. Compaction
  rewrites the file as a fresh snapshot once the log grows.
"""

from __future__ import annotations

import codecs
import json
import os
import sys
import tempfile
import time
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from plain_text_memory_mcp.graph import (
    Access,
    Entity,
    Graph,
    Header,
    Relation,
    RelationKey,
)
from plain_text_memory_mcp.records import (
    RecordError,
    Tombstone,
    parse_access,
    parse_record,
    to_access_record,
    to_entity_record,
    to_header_record,
    to_relation_record,
    to_tombstone_record,
)

# Each record's line in the file, keyed by what a later line replaces.
Snapshot = dict[tuple[str, ...], str]

MEMORY_RELATIVE_PATH = Path(".agents") / "memory.local.jsonl"
SCHEMA_FILE_NAME = "taxonomy.json"

# Waits between attempts while another process holds the file (~1.5 s total).
_LOCK_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)

# Compact once the file holds more lines than this many per live record,
# plus the slack, so the log stays within about twice the snapshot.
_COMPACT_FACTOR = 2
_COMPACT_SLACK = 100

# How long a write waits for another process to finish its own write.
_LOCK_TIMEOUT_SECONDS = 10.0
_LOCK_POLL_SECONDS = 0.05

if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except PermissionError:
            return False
        return True

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


def look_repo_root(start: Path) -> Path | None:
    """Return the nearest folder at or above `start` that contains `.git`.

    - A `.git` file counts, so git worktrees resolve to their own root.
    """
    for folder in (start, *start.parents):
        if (folder / ".git").exists():
            return folder
    return None


def calc_memory_path(environ: Mapping[str, str], cwd: Path) -> Path:
    """Return the memory file path for a server started in `cwd`.

    - `MEMORY_FILE_PATH` wins; a relative value resolves against `cwd`.
    - Otherwise the file lives at `.agents/memory.local.jsonl` under the git
      root, or under `cwd` when no git root exists.
    """
    override = environ.get("MEMORY_FILE_PATH", "").strip()
    if override:
        return cwd / override
    root = look_repo_root(cwd) or cwd
    return root / MEMORY_RELATIVE_PATH


def _normalize_root(root: str) -> str:
    return os.path.normcase(os.path.normpath(root.removeprefix("\\\\?\\")))


def is_same_repo(recorded_root: str, repo_root: Path) -> bool:
    """Return whether a header's recorded root names `repo_root`.

    - Ignores drive-letter case, slash direction, a trailing slash, and the
      Windows `\\\\?\\` long-path prefix.
    """
    return _normalize_root(recorded_root) == _normalize_root(str(repo_root))


@contextmanager
def lock_memory(path: Path) -> Generator[None, None, None]:
    """Hold an exclusive lock on `path` across processes for the block.

    - Locks a sidecar `<name>.lock` file, not the memory file, so the atomic
      swap in `write_graph` still works while the lock is held.
    - The OS frees the lock when its holder exits, even after a crash; the
      leftover lock file is harmless.
    - Raises `TimeoutError` naming the lock file after about 10 s.
    """
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT)
    try:
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                message = (
                    f"{lock_path}: another process held the lock for over"
                    f" {_LOCK_TIMEOUT_SECONDS:g} s"
                )
                raise TimeoutError(message)
            time.sleep(_LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


def _read_bytes_with_retry(path: Path) -> bytes:
    for delay in _LOCK_RETRY_DELAYS:
        try:
            return path.read_bytes()
        except PermissionError:
            time.sleep(delay)
    return path.read_bytes()


def _parse_line(raw_line: bytes) -> Entity | Relation | Header | Tombstone:
    return parse_record(json.loads(raw_line.decode("utf-8")))


class _Replay:
    """Collect records in file order, letting later lines replace earlier."""

    def __init__(self) -> None:
        self.header: Header | None = None
        self.entities: dict[str, Entity] = {}
        self.relations: dict[RelationKey, Relation] = {}

    def apply(self, record: Entity | Relation | Header | Tombstone) -> None:
        if isinstance(record, Entity):
            self.entities[record.name] = record
        elif isinstance(record, Relation):
            self.relations[_to_relation_key(record)] = record
        elif isinstance(record, Tombstone):
            if record.entity_name is not None:
                self.entities.pop(record.entity_name, None)
            if record.relation_key is not None:
                self.relations.pop(record.relation_key, None)
        elif self.header is not None:
            raise RecordError("memory file has more than one header")
        else:
            self.header = record


def _to_relation_key(relation: Relation) -> RelationKey:
    return (relation.source, relation.target, relation.relation_type)


def read_graph(path: Path) -> Graph:
    """Read the memory file into a graph; a missing file is empty.

    - Replays the log: a later line for an entity name or relation replaces
      the earlier one in place, and a tombstone removes it.
    - Tolerates a UTF-8 BOM, CRLF line endings, and blank lines.
    - Retries for about 1.5 s while another process holds the file.
    - Raises `RecordError` naming the file and line of the first bad line,
      including a line that is not valid UTF-8.
    """
    if not path.exists():
        return Graph()
    replay = _Replay()
    content = _read_bytes_with_retry(path).removeprefix(codecs.BOM_UTF8)
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            replay.apply(_parse_line(raw_line))
        except (UnicodeDecodeError, json.JSONDecodeError, RecordError) as exc:
            message = f"{path}:{line_number}: {exc}"
            raise RecordError(message) from exc
    return Graph(
        list(replay.entities.values()),
        list(replay.relations.values()),
        replay.header,
    )


def _dump(record: object) -> str:
    return json.dumps(record, ensure_ascii=False)


def snapshot_graph(memory: Graph) -> Snapshot:
    """Return each record's file line, keyed by entity name or relation.

    - Pass the result to `write_changes` after changing the graph.
    """
    lines: Snapshot = {}
    if memory.header is not None:
        lines[("header",)] = _dump(to_header_record(memory.header))
    for entity in memory.entities:
        lines[("entity", entity.name)] = _dump(to_entity_record(entity))
    for relation in memory.relations:
        key = ("relation", *_to_relation_key(relation))
        lines[key] = _dump(to_relation_record(relation))
    return lines


def _to_lines(memory: Graph) -> list[str]:
    return list(snapshot_graph(memory).values())


def _to_tombstone_line(key: tuple[str, ...]) -> str:
    if key[0] == "entity":
        return _dump(to_tombstone_record(Tombstone(entity_name=key[1])))
    source, target, relation_type = key[1:]
    tombstone = Tombstone(relation_key=(source, target, relation_type))
    return _dump(to_tombstone_record(tombstone))


def _replace_with_retry(source: str, target: Path) -> None:
    for delay in _LOCK_RETRY_DELAYS:
        try:
            os.replace(source, target)
        except PermissionError:
            time.sleep(delay)
        else:
            return
    os.replace(source, target)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as file:
            file.write(text)
        _replace_with_retry(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def write_graph(path: Path, memory: Graph) -> None:
    """Write the graph to `path` without ever leaving a partial file.

    - Creates the parent folder when missing.
    - Writes a temp file beside `path`, then swaps it in; on Windows the swap
      retries for about 1.5 s while another process has the file open.
    - Removes the temp file if the swap finally fails.
    """
    text = "".join(f"{line}\n" for line in _to_lines(memory))
    _write_text_atomic(path, text)


def _append_with_retry(path: Path, text: str) -> None:
    payload = text.encode("utf-8")
    for delay in _LOCK_RETRY_DELAYS:
        try:
            with path.open("ab") as file:
                file.write(payload)
        except PermissionError:
            time.sleep(delay)
        else:
            return
    with path.open("ab") as file:
        file.write(payload)


def _is_due_for_compaction(path: Path, appended: int, live: int) -> bool:
    if not path.exists():
        return True
    content = _read_bytes_with_retry(path)
    if content and not content.endswith(b"\n"):
        return True
    limit = _COMPACT_FACTOR * live + _COMPACT_SLACK
    return content.count(b"\n") + appended > limit


def write_changes(path: Path, before: Snapshot, memory: Graph) -> None:
    """Save what changed in `memory` since `before`, appending when it can.

    - Appends a line for each new or changed record and a tombstone for
      each removed one, in one write; nothing changed writes nothing.
    - Rewrites the whole file instead, through `write_graph`, when the
      header changed, the file is missing or lacks a final newline, or the
      log would pass about twice the snapshot's length.
    """
    after = snapshot_graph(memory)
    if after == before:
        return
    removed = [_to_tombstone_line(key) for key in before if key not in after]
    changed = [line for key, line in after.items() if before.get(key) != line]
    lines = removed + changed
    header_key = ("header",)
    if before.get(header_key) != after.get(header_key) or (
        _is_due_for_compaction(path, len(lines), len(after))
    ):
        write_graph(path, memory)
        return
    _append_with_retry(path, "".join(f"{line}\n" for line in lines))


def calc_access_path(memory_path: Path) -> Path:
    """Return the access log path beside the memory file.

    - `memory.local.jsonl` logs to `memory.local.access.jsonl`, which the
      `.agents/*memory.local.*` ignore pattern also covers.
    """
    return memory_path.with_name(f"{memory_path.stem}.access.jsonl")


def append_accesses(path: Path, accesses: list[Access]) -> None:
    """Append access records to the log at `path`, creating it if needed."""
    if not accesses:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(f"{_dump(to_access_record(a))}\n" for a in accesses)
    _append_with_retry(path, text)


def read_accesses(path: Path) -> list[Access]:
    """Read the access log; a missing file is empty.

    - Skips lines that do not parse, such as one cut short by a crash: the
      log only tunes ranking, so a lost line costs nothing.
    """
    if not path.exists():
        return []
    accesses = []
    content = _read_bytes_with_retry(path).removeprefix(codecs.BOM_UTF8)
    for raw_line in content.splitlines():
        try:
            accesses.append(parse_access(json.loads(raw_line.decode("utf-8"))))
        except (UnicodeDecodeError, json.JSONDecodeError, RecordError):
            continue
    return accesses


def calc_export_path(memory_path: Path) -> Path:
    """Return the taxonomy export path beside the memory file.

    - `memory.local.jsonl` exports to `memory.local.taxonomy.jsonc`, which the
      `.agents/*memory.local.*` ignore pattern also covers.
    """
    return memory_path.with_name(f"{memory_path.stem}.taxonomy.jsonc")


def load_schema() -> dict[str, object]:
    """Load the versioned taxonomy shipped inside the package."""
    package = resources.files("plain_text_memory_mcp")
    text = package.joinpath(SCHEMA_FILE_NAME).read_text(encoding="utf-8")
    return json.loads(text)


def load_prompt(name: str) -> str:
    """Load the Markdown text of a prompt shipped inside the package."""
    package = resources.files("plain_text_memory_mcp")
    prompt = package.joinpath("prompts", f"{name}.md")
    return prompt.read_text(encoding="utf-8")


def _format_jsonc_value(
    value: object,
    comments: Mapping[tuple[str, ...], str],
    path: tuple[str, ...],
    depth: int,
) -> str:
    pad = "  " * (depth + 1)
    closing_pad = "  " * depth
    if isinstance(value, dict) and value:
        members = []
        for key, part in value.items():
            key_path = (*path, str(key))
            comment = comments.get(key_path)
            line = (
                f"{pad}{json.dumps(str(key), ensure_ascii=False)}: "
                f"{_format_jsonc_value(part, comments, key_path, depth + 1)}"
            )
            members.append(f"{pad}// {comment}\n{line}" if comment else line)
        return "{\n" + ",\n".join(members) + f"\n{closing_pad}}}"
    if isinstance(value, list) and value:
        items = [
            f"{pad}{_format_jsonc_value(part, comments, path, depth + 1)}"
            for part in value
        ]
        return "[\n" + ",\n".join(items) + f"\n{closing_pad}]"
    return json.dumps(value, ensure_ascii=False)


def format_jsonc(value: object, comments: Mapping[tuple[str, ...], str]) -> str:
    """Return `value` as indented JSON with `//` comments above chosen keys.

    - `comments` maps a key path, such as `("schema", "enums")`, to one line
      of text placed above that key; the empty path comments the whole file.
    - Removing the comment lines leaves valid JSON.
    """
    body = _format_jsonc_value(value, comments, (), 0)
    top = comments.get(())
    return (f"// {top}\n" if top else "") + body + "\n"


def write_export(
    path: Path,
    document: Mapping[str, object],
    comments: Mapping[tuple[str, ...], str],
) -> None:
    """Write the taxonomy export as commented JSONC, atomically."""
    _write_text_atomic(path, format_jsonc(document, comments))


def backup_memory(path: Path, stamp: str) -> Path:
    """Rename the memory file aside as `<name>.bak-<stamp>` and return it.

    - Retries for about 1.5 s while another process holds the file.
    """
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    _replace_with_retry(str(path), backup)
    return backup
