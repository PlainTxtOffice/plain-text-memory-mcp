"""Format and parse the stamp the server appends to each note.

- A stamp is an HTML comment at the end of a bullet, hidden when the
  Markdown is rendered:
  `<!-- <added_at> <agent> #<hash> [retired <at>] [superseded_by #<hash>] -->`.
- The hash covers the note text, so a reworded note is detected and
  restamped.
- The hash is 5 hex digits because CSS colors have 3, 4, 6, or 8, so
  editors do not draw a color swatch beside it. Stamps written before
  this kept 4 digits and still match by prefix.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime

HASH_LENGTH = 5
OLD_HASH_LENGTH = 4

_STAMP_PATTERN = re.compile(
    r"\s*<!--\s*(?P<added_at>\S+)\s+(?P<agent>\S+)"
    r"\s+#(?P<hash>[0-9a-f]+)"
    r"(?:\s+retired\s+(?P<retired_at>\S+))?"
    r"(?:\s+superseded_by\s+#(?P<superseded_by>[0-9a-f]+))?"
    r"\s*-->\s*$"
)


@dataclass(frozen=True)
class Stamp:
    """Record when and by whom a note was written, and when it was retired.

    - `hash` is the note text's hash when the stamp was written.
    - `superseded_by` is the replacement's hash, set only on archived
      notes, whose nesting no longer shows the replacement.
    """

    added_at: str
    agent: str
    hash: str
    retired_at: str | None = None
    superseded_by: str | None = None


def calc_hash(text: str) -> str:
    """Return the short hash of a note's text, ignoring spacing."""
    normalized = " ".join(text.split())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[:HASH_LENGTH]


def is_hash_of(stamp_hash: str, text_hash: str) -> bool:
    """Return whether a stamp's hash matches a note's current hash.

    - A 4-digit hash from before the 5-digit change matches the first 4
      digits of the current hash.
    """
    if len(stamp_hash) == OLD_HASH_LENGTH:
        return text_hash.startswith(stamp_hash)
    return stamp_hash == text_hash


def format_moment(moment: datetime) -> str:
    """Return a stamp time: ISO 8601 to the minute, with UTC offset."""
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.isoformat(timespec="minutes")


def normalize_agent(agent: str) -> str:
    """Return the agent name with spaces replaced, so it fits one token."""
    return "-".join(agent.split()) or "unknown"


def format_stamp(stamp: Stamp) -> str:
    """Return the stamp as the HTML comment written after a note."""
    parts = [stamp.added_at, normalize_agent(stamp.agent), f"#{stamp.hash}"]
    if stamp.retired_at is not None:
        parts += ["retired", stamp.retired_at]
    if stamp.superseded_by is not None:
        parts += ["superseded_by", f"#{stamp.superseded_by}"]
    return f"<!-- {' '.join(parts)} -->"


def split_stamp(body: str) -> tuple[str, Stamp | None]:
    """Return a bullet body without its trailing stamp, and the stamp.

    - A body with no stamp returns itself, stripped, and None.
    """
    match = _STAMP_PATTERN.search(body)
    if match is None:
        return body.strip(), None
    stamp = Stamp(
        added_at=match["added_at"],
        agent=match["agent"],
        hash=match["hash"],
        retired_at=match["retired_at"],
        superseded_by=match["superseded_by"],
    )
    return body[: match.start()].strip(), stamp


def remove_stamp(line: str) -> str:
    """Return a file line without its trailing stamp or trailing space.

    - Keeps the line's indentation and bullet marker.
    """
    match = _STAMP_PATTERN.search(line)
    return (line[: match.start()] if match else line).rstrip()
