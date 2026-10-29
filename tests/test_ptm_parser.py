"""Tests for parsing MEMORY.ptm.md files and their stamps."""

from datetime import UTC, datetime, timedelta, timezone

from plain_text_memory_mcp.ptm import parser, stamps
from plain_text_memory_mcp.ptm.stamps import Stamp

SAMPLE = """\
# search

Ranks notes with BM25
plus spreading activation.

- Search lives under src/search.

## bm25.py
- Tokenizes with a lowercase word regex. <!-- 2026-10-09T14:02-04:00 claude-code #9f2c -->
- uses [[ranking.py]]
- Ranking uses BM25.
  - ~~Ranking uses TF-IDF.~~ <!-- 2026-10-01T09:15-04:00 codex #a1b2 retired 2026-10-09T14:02-04:00 -->
- ~~Stems with Porter.~~

```markdown
- not a note
## not an entity
```

### Details
- Still belongs to bm25.py.
"""


def test_stamp_round_trips_through_format_and_split() -> None:
    stamp = Stamp("2026-10-09T14:02-04:00", "claude-code", "9f2c", None, "c3d4")
    body = f"Uses BM25. {stamps.format_stamp(stamp)}"
    assert stamps.split_stamp(body) == ("Uses BM25.", stamp)


def test_split_stamp_without_stamp_returns_text_and_none() -> None:
    assert stamps.split_stamp("  Uses BM25.  ") == ("Uses BM25.", None)


def test_hash_ignores_spacing_but_not_wording() -> None:
    assert stamps.calc_hash("Uses  BM25 ") == stamps.calc_hash("Uses BM25")
    assert stamps.calc_hash("Uses BM25") != stamps.calc_hash("Uses TF-IDF")
    assert len(stamps.calc_hash("x")) == stamps.HASH_LENGTH


def test_format_stamp_keeps_agent_to_one_word() -> None:
    stamp = Stamp("2026-10-09T14:02-04:00", "Visual Studio Code", "9f2c")
    assert stamps.format_stamp(stamp) == (
        "<!-- 2026-10-09T14:02-04:00 Visual-Studio-Code #9f2c -->"
    )


def test_format_moment_is_minute_precision_with_offset() -> None:
    moment = datetime(2026, 10, 9, 18, 2, 30, tzinfo=UTC)
    local = moment.astimezone(timezone(timedelta(hours=-4)))
    text = stamps.format_moment(local)
    assert datetime.fromisoformat(text) == moment.replace(second=0)
    assert text.count(":") == 2  # hh:mm and the offset


def test_parse_file_reads_entities_and_summary() -> None:
    memory = parser.parse_file(SAMPLE, "fallback")
    assert memory.folder_entity == "search"
    assert memory.entities == ("search", "bm25.py")
    assert memory.summary == "Ranks notes with BM25 plus spreading activation."


def test_parse_file_assigns_bullets_to_entities() -> None:
    memory = parser.parse_file(SAMPLE, "fallback")
    owners = {bullet.text: bullet.entity for bullet in memory.bullets}
    assert owners["Search lives under src/search."] == "search"
    assert owners["Still belongs to bm25.py."] == "bm25.py"
    assert "not a note" not in owners


def test_parse_file_reads_stamps_and_relations() -> None:
    memory = parser.parse_file(SAMPLE, "fallback")
    by_text = {bullet.text: bullet for bullet in memory.bullets}
    stamped = by_text["Tokenizes with a lowercase word regex."]
    assert stamped.stamp == Stamp(
        "2026-10-09T14:02-04:00", "claude-code", "9f2c"
    )
    assert by_text["uses [[ranking.py]]"].relation == ("uses", "ranking.py")
    assert by_text["Ranking uses BM25."].relation is None


def test_parse_file_reads_struck_bullets_and_their_parent() -> None:
    memory = parser.parse_file(SAMPLE, "fallback")
    by_text = {bullet.text: bullet for bullet in memory.bullets}
    superseded = by_text["Ranking uses TF-IDF."]
    assert superseded.struck
    assert superseded.parent == by_text["Ranking uses BM25."].line
    assert superseded.stamp is not None
    assert superseded.stamp.retired_at == "2026-10-09T14:02-04:00"
    retired = by_text["Stems with Porter."]
    assert retired.struck
    assert retired.parent is None


def test_parse_file_without_heading_uses_default_name() -> None:
    memory = parser.parse_file("- A repo-wide fact.\n", "my_repo")
    assert memory.folder_entity == "my_repo"
    assert memory.bullets[0].entity == "my_repo"


def test_parse_file_ignores_carriage_returns() -> None:
    memory = parser.parse_file("# app\r\n- Uses SQLite.\r\n", "x")
    assert memory.folder_entity == "app"
    assert memory.bullets[0].text == "Uses SQLite."


def test_long_verb_phrase_with_link_stays_a_note() -> None:
    text = "- The ranking code was heavily shaped by [[bm25.py]]\n"
    memory = parser.parse_file(text, "x")
    assert memory.bullets[0].relation is None


def test_multi_word_verb_becomes_snake_case_relation() -> None:
    memory = parser.parse_file("- depends on [[sqlite]]\n", "x")
    assert memory.bullets[0].relation == ("depends_on", "sqlite")
