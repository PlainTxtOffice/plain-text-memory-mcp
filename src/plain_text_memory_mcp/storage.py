"""Locate the server's local state and read and write its logs.

- The state lives in `<repo root>/.agents/ptm/`: the stamping lock, the
  access log, and the recall log, so one ignore pattern, `.agents/ptm/`,
  covers them all.
- Memory itself lives in the repo's MEMORY.ptm.md files; see `ptm.index`.
"""

from __future__ import annotations

import codecs
import json
import os
import sys
import time
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from plain_text_memory_mcp.graph import Access
from plain_text_memory_mcp.records import (
    RecallEvent,
    RecordError,
    parse_access,
    to_access_record,
    to_recall_record,
)

STATE_FOLDER = Path(".agents", "ptm")
LOCK_FILE_NAME = "stamp.lock"
ACCESS_FILE_NAME = "access.jsonl"
RECALL_FILE_NAME = "recall.jsonl"
SCHEMA_FILE_NAME = "taxonomy.json"

# Waits between attempts while another process holds the file (~1.5 s total).
_LOCK_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)

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


def calc_state_path(repo_root: Path) -> Path:
    """Return the folder of the server's local state for `repo_root`.

    - The folder is `<repo root>/.agents/ptm`; the lock and each log sit in
      it.
    """
    return repo_root / STATE_FOLDER


@contextmanager
def lock_memory(state_path: Path) -> Generator[None, None, None]:
    """Hold a cross-process lock in the state folder for the block.

    - Locks the file `stamp.lock` in `state_path`, creating the folder when
      missing.
    - The OS frees the lock when its holder exits, even after a crash; the
      leftover lock file is harmless.
    - Raises `TimeoutError` naming the lock file after about 10 s.
    """
    lock_path = state_path / LOCK_FILE_NAME
    state_path.mkdir(parents=True, exist_ok=True)
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


def _dump(record: object) -> str:
    return json.dumps(record, ensure_ascii=False)


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


def calc_access_path(state_path: Path) -> Path:
    """Return the access log path in the state folder `state_path`."""
    return state_path / ACCESS_FILE_NAME


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


def is_recall_log_on(environ: Mapping[str, str]) -> bool:
    """Return whether `MEMORY_RECALL_LOG=1` turns on the recall log.

    - The log is a development aid, so any other value leaves it off.
    """
    return environ.get("MEMORY_RECALL_LOG", "").strip() == "1"


def calc_recall_path(state_path: Path) -> Path:
    """Return the recall log path in the state folder `state_path`."""
    return state_path / RECALL_FILE_NAME


def append_recall_events(path: Path, events: list[RecallEvent]) -> None:
    """Append recall log lines to `path`, creating it if needed."""
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(f"{_dump(to_recall_record(e))}\n" for e in events)
    _append_with_retry(path, text)


def load_schema() -> dict[str, object]:
    """Load the versioned taxonomy shipped inside the package."""
    package = resources.files("plain_text_memory_mcp")
    text = package.joinpath(SCHEMA_FILE_NAME).read_text(encoding="utf-8")
    return json.loads(text)
