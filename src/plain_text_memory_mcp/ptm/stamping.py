"""Stamp new and changed notes, and move old retired notes to the archive.

- These functions take and return file text; the server reads and writes
  the files.
- A bullet with no stamp, or whose text no longer matches its stamp's
  hash, is stamped as the calling agent at the current time.
- A bullet whose 4-digit hash still matches its text keeps its stamp,
  with the hash rewritten at 5 digits.
- A struck bullet whose stamp has no retirement time gets one.
- A struck bullet retired longer than `ARCHIVE_AFTER` ago moves to the
  archive file beside it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from plain_text_memory_mcp.graph import parse_moment
from plain_text_memory_mcp.ptm import parser, stamps
from plain_text_memory_mcp.ptm.parser import Bullet, MemoryFile
from plain_text_memory_mcp.ptm.stamps import Stamp

ARCHIVE_AFTER = timedelta(days=90)


@dataclass(frozen=True)
class StampedFile:
    """Hold a memory file's text after stamping, and what changed.

    - `stamped` lists bullets that were new or reworded, for screening.
    - `retired` counts struck bullets that were given a retirement time.
    """

    text: str
    stamped: tuple[Bullet, ...]
    retired: int


@dataclass(frozen=True)
class ArchivedFile:
    """Hold a memory file and its archive after moving retired notes."""

    text: str
    archive_text: str
    moved: tuple[Bullet, ...]


def _write_stamp(line: str, stamp: Stamp) -> str:
    ending = "\r" if line.endswith("\r") else ""
    body = stamps.remove_stamp(line.rstrip("\r"))
    return f"{body} {stamps.format_stamp(stamp)}{ending}"


def _calc_stamp(bullet: Bullet, agent: str, at: str) -> tuple[Stamp, bool]:
    """Return the bullet's new stamp and whether its note is new or changed."""
    text_hash = stamps.calc_hash(bullet.text)
    stamp = bullet.stamp
    is_new = stamp is None or not stamps.is_hash_of(stamp.hash, text_hash)
    if stamp is None or is_new:
        retired_at = stamp.retired_at if stamp else None
        stamp = Stamp(at, stamps.normalize_agent(agent), text_hash, retired_at)
    elif stamp.hash != text_hash:
        stamp = replace(stamp, hash=text_hash)
    if bullet.struck and stamp.retired_at is None:
        stamp = replace(stamp, retired_at=at)
    return stamp, is_new


def update_stamps(
    text: str, default_name: str, agent: str, now: datetime
) -> StampedFile:
    """Return a memory file's text with every bullet's stamp brought current.

    - Bullets whose stamp is already current are left byte for byte.
    """
    lines = text.split("\n")
    at = stamps.format_moment(now)
    stamped: list[Bullet] = []
    retired = 0
    for bullet in parser.parse_file(text, default_name).bullets:
        stamp, is_new = _calc_stamp(bullet, agent, at)
        if stamp == bullet.stamp:
            continue
        lines[bullet.line] = _write_stamp(lines[bullet.line], stamp)
        if is_new and not bullet.struck:
            stamped.append(bullet)
        old_retired = bullet.stamp.retired_at if bullet.stamp else None
        if bullet.struck and old_retired is None:
            retired += 1
    return StampedFile("\n".join(lines), tuple(stamped), retired)


def _is_due(bullet: Bullet, now: datetime) -> bool:
    if not bullet.struck or bullet.stamp is None:
        return False
    retired_at = parse_moment(bullet.stamp.retired_at)
    return retired_at is not None and now - retired_at >= ARCHIVE_AFTER


def _calc_archive_line(bullet: Bullet, memory_file: MemoryFile) -> str:
    stamp = bullet.stamp
    assert stamp is not None  # _is_due checked it
    by_line = {other.line: other for other in memory_file.bullets}
    parent = by_line.get(bullet.parent) if bullet.parent is not None else None
    if parent is not None and not parent.struck:
        parent_hash = stamps.calc_hash(parent.text)
        stamp = replace(stamp, superseded_by=parent_hash)
    return f"- ~~{bullet.text}~~ {stamps.format_stamp(stamp)}"


def _look_insert_index(lines: list[str], entity: str, folder: str) -> int:
    """Return where a note for `entity` goes in the archive's lines.

    - Adds a `## entity` heading at the end when the archive has none.
    """
    headings = [
        index for index, line in enumerate(lines) if line.startswith("## ")
    ]
    if entity == folder:
        return headings[0] if headings else len(lines)
    for position, index in enumerate(headings):
        if lines[index][3:].strip() == entity:
            after = headings[position + 1 :]
            return after[0] if after else len(lines)
    if lines and lines[-1].strip():
        lines.append("")
    lines.append(f"## {entity}")
    return len(lines)


def _trim_blank_end(lines: list[str]) -> list[str]:
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def archive_retired(
    text: str, archive_text: str, default_name: str, now: datetime
) -> ArchivedFile:
    """Return the file and its archive after moving notes retired long ago.

    - A moved note keeps its stamp; a superseded one also records its
      replacement's hash, since its nesting does not survive the move.
    - The archive's notes go under the same entity heading as before.
    """
    memory_file = parser.parse_file(text, default_name)
    due = [bullet for bullet in memory_file.bullets if _is_due(bullet, now)]
    if not due:
        return ArchivedFile(text, archive_text, ())
    folder = memory_file.folder_entity
    archive_lines = _trim_blank_end(archive_text.split("\n"))
    if not archive_lines:
        archive_lines = [f"# {folder}", ""]
    for bullet in due:
        index = _look_insert_index(archive_lines, bullet.entity, folder)
        while index > 0 and not archive_lines[index - 1].strip():
            index -= 1
        line = _calc_archive_line(bullet, memory_file)
        archive_lines.insert(index, line)
    doomed = {bullet.line for bullet in due}
    kept = [
        line
        for index, line in enumerate(text.split("\n"))
        if index not in doomed
    ]
    return ArchivedFile(
        "\n".join(kept), "\n".join(archive_lines) + "\n", tuple(due)
    )
