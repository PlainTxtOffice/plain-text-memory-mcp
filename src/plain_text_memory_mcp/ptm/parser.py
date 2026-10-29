"""Parse a MEMORY.ptm.md file into entities, notes, and relations.

- `# name` names the folder entity; prose under it is the folder summary.
- `## name` starts another entity; bullets after it belong to it.
- A bullet is one note. `~~text~~` marks it retired; nested under a live
  bullet, it was superseded by that bullet.
- A bullet that is only a short verb phrase and one `[[link]]` is a
  relation from the current entity to the linked one.
- Fenced code blocks and other Markdown are skipped.
- `parse_agents_file` reads read-only sources such as AGENTS.md, which
  follow no format, into unstamped notes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from plain_text_memory_mcp.ptm.stamps import Stamp, split_stamp

FILE_NAME = "MEMORY.ptm.md"
ARCHIVE_FILE_NAME = "MEMORY.ptm.archive.md"

# A memory file longer than this many lines draws a warning when stamped,
# so each file stays short enough to read whole.
MAX_FILE_LINES = 200

# A relation verb is at most this many words, so a sentence that happens
# to end in a link stays a note.
MAX_VERB_WORDS = 3

_HEADING_PATTERN = re.compile(r"^(?P<level>#{1,6})\s+(?P<name>.+?)\s*$")
_BULLET_PATTERN = re.compile(r"^(?P<indent>[ \t]*)[-*+]\s+(?P<body>.*)$")
_FENCE_PATTERN = re.compile(r"^\s*(```|~~~)")
_STRUCK_PATTERN = re.compile(r"^~~(?P<text>.+)~~$")
_RELATION_PATTERN = re.compile(
    r"^(?P<verb>[A-Za-z][\w-]*(?: [A-Za-z][\w-]*)*)\s+"
    r"\[\[(?P<target>[^\[\]]+)\]\]$"
)


@dataclass(frozen=True)
class Bullet:
    """Hold one note or relation bullet and where it sits in the file.

    - `line` is the 0-based index into the file's lines.
    - `text` excludes the stamp and, on a struck bullet, the `~~` marks.
    - `parent` is the line of the bullet this one is nested under, or None.
    - `relation` is (verb, target) when the bullet is a relation.
    """

    line: int
    indent: int
    entity: str
    text: str
    struck: bool
    stamp: Stamp | None
    parent: int | None = None
    relation: tuple[str, str] | None = None


@dataclass(frozen=True)
class MemoryFile:
    """Hold everything parsed from one memory file.

    - `entities` lists entity names in file order, the folder entity first.
    """

    folder_entity: str
    summary: str
    entities: tuple[str, ...]
    bullets: tuple[Bullet, ...]


def _parse_relation(text: str) -> tuple[str, str] | None:
    match = _RELATION_PATTERN.match(text)
    if match is None:
        return None
    words = match["verb"].split()
    if len(words) > MAX_VERB_WORDS:
        return None
    return "_".join(word.lower() for word in words), match["target"].strip()


def _calc_indent(indent: str) -> int:
    return len(indent.expandtabs(4))


def _look_parent(stack: list[Bullet], indent: int) -> int | None:
    while stack and stack[-1].indent >= indent:
        stack.pop()
    return stack[-1].line if stack else None


def _build_bullet(
    index: int, match: re.Match[str], entity: str, stack: list[Bullet]
) -> Bullet | None:
    body, stamp = split_stamp(match["body"])
    struck_match = _STRUCK_PATTERN.match(body)
    text = struck_match["text"].strip() if struck_match else body
    if not text:
        return None
    indent = _calc_indent(match["indent"])
    return Bullet(
        line=index,
        indent=indent,
        entity=entity,
        text=text,
        struck=struck_match is not None,
        stamp=stamp,
        parent=_look_parent(stack, indent),
        relation=_parse_relation(text),
    )


def parse_file(text: str, default_name: str) -> MemoryFile:
    """Return the entities and bullets in a memory file's text.

    - `default_name` names the folder entity when the file has no `#`
      heading before its first bullet or `##` heading.
    - Lines may end in CRLF; the `\\r` is ignored.
    """
    folder_entity = default_name
    entity = default_name
    entities = [default_name]
    summary: list[str] = []
    bullets: list[Bullet] = []
    stack: list[Bullet] = []
    in_fence = False
    in_summary = True
    for index, raw in enumerate(text.split("\n")):
        line = raw.rstrip("\r")
        if _FENCE_PATTERN.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = _HEADING_PATTERN.match(line)
        if heading and heading["level"] == "#" and in_summary:
            if not bullets and entity == folder_entity:
                folder_entity = entity = heading["name"]
                entities[0] = folder_entity
            continue
        if heading and heading["level"] == "##":
            in_summary = False
            entity = heading["name"]
            if entity not in entities:
                entities.append(entity)
            stack.clear()
            continue
        if heading:
            continue
        bullet_match = _BULLET_PATTERN.match(line)
        if bullet_match is None:
            if in_summary and line.strip():
                summary.append(line.strip())
            continue
        in_summary = False
        bullet = _build_bullet(index, bullet_match, entity, stack)
        if bullet is not None:
            bullets.append(bullet)
            stack.append(bullet)
    return MemoryFile(
        folder_entity=folder_entity,
        summary=" ".join(summary),
        entities=tuple(entities),
        bullets=tuple(bullets),
    )


def _to_note_bullets(blocks: list[tuple[int, str, list[str]]]) -> list[Bullet]:
    return [
        Bullet(
            line=index,
            indent=0,
            entity=entity,
            text=" ".join(parts),
            struck=False,
            stamp=None,
        )
        for index, entity, parts in blocks
    ]


def parse_agents_file(text: str, default_name: str) -> MemoryFile:
    """Return the notes in a read-only instruction file such as AGENTS.md.

    - A `##` or deeper heading starts an entity named after its text; text
      before it, including under the `#` title, belongs to `default_name`.
    - Each bullet, with its wrapped lines, and each paragraph is one
      unstamped note. Code blocks and tables are skipped.
    """
    entity = default_name
    entities = [default_name]
    blocks: list[tuple[int, str, list[str]]] = []
    is_open = False
    in_fence = False
    for index, raw in enumerate(text.split("\n")):
        line = raw.rstrip("\r").strip()
        if _FENCE_PATTERN.match(line):
            in_fence = not in_fence
            is_open = False
            continue
        if in_fence or not line or line.startswith("|"):
            is_open = False
            continue
        heading = _HEADING_PATTERN.match(line)
        if heading:
            if heading["level"] != "#":
                entity = heading["name"]
                if entity not in entities:
                    entities.append(entity)
            is_open = False
            continue
        bullet_match = _BULLET_PATTERN.match(line)
        if bullet_match is not None:
            blocks.append((index, entity, [bullet_match["body"].strip()]))
        elif is_open:
            blocks[-1][2].append(line)
        else:
            blocks.append((index, entity, [line]))
        is_open = True
    return MemoryFile(
        folder_entity=default_name,
        summary="",
        entities=tuple(entities),
        bullets=tuple(_to_note_bullets(blocks)),
    )
