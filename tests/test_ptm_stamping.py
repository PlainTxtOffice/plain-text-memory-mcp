"""Tests for stamping memory files and archiving retired notes."""

from datetime import datetime, timedelta, timezone

from plain_text_memory_mcp.ptm import parser, stamping, stamps

EDT = timezone(timedelta(hours=-4))
NOW = datetime(2026, 10, 9, 14, 2, tzinfo=EDT)
AT = "2026-10-09T14:02-04:00"


def _stamp_of(text: str, note: str) -> stamps.Stamp | None:
    for bullet in parser.parse_file(text, "x").bullets:
        if bullet.text == note:
            return bullet.stamp
    raise AssertionError(note)


def test_update_stamps_stamps_new_bullets_as_the_caller() -> None:
    result = stamping.update_stamps(
        "# app\n- Uses SQLite.\n", "x", "claude-code", NOW
    )
    assert result.text == (
        "# app\n- Uses SQLite. "
        f"<!-- {AT} claude-code #{stamps.calc_hash('Uses SQLite.')} -->\n"
    )
    assert [bullet.text for bullet in result.stamped] == ["Uses SQLite."]


def test_update_stamps_leaves_current_stamps_alone() -> None:
    first = stamping.update_stamps("- Uses SQLite.\n", "x", "codex", NOW)
    later = NOW + timedelta(days=3)
    second = stamping.update_stamps(first.text, "x", "claude-code", later)
    assert second.text == first.text
    assert second.stamped == ()


def test_update_stamps_restamps_reworded_bullets() -> None:
    first = stamping.update_stamps("- Uses SQLite.\n", "x", "codex", NOW)
    edited = first.text.replace("Uses SQLite.", "Uses SQLite 3.45.")
    later = NOW + timedelta(days=3)
    result = stamping.update_stamps(edited, "x", "claude-code", later)
    stamp = _stamp_of(result.text, "Uses SQLite 3.45.")
    assert stamp is not None
    assert stamp.agent == "claude-code"
    assert stamp.added_at == stamps.format_moment(later)
    assert [bullet.text for bullet in result.stamped] == ["Uses SQLite 3.45."]


def test_update_stamps_lengthens_old_hashes_and_keeps_the_stamp() -> None:
    old_hash = stamps.calc_hash("Uses SQLite.")[: stamps.OLD_HASH_LENGTH]
    text = f"- Uses SQLite. <!-- 2026-01-01T09:00-04:00 codex #{old_hash} -->\n"
    result = stamping.update_stamps(text, "x", "claude-code", NOW)
    stamp = _stamp_of(result.text, "Uses SQLite.")
    assert stamp == stamps.Stamp(
        "2026-01-01T09:00-04:00", "codex", stamps.calc_hash("Uses SQLite.")
    )
    assert result.stamped == ()


def test_update_stamps_restamps_old_hashes_that_do_not_match() -> None:
    old_hash = stamps.calc_hash("Uses TF-IDF.")[: stamps.OLD_HASH_LENGTH]
    text = f"- Uses SQLite. <!-- 2026-01-01T09:00-04:00 codex #{old_hash} -->\n"
    result = stamping.update_stamps(text, "x", "claude-code", NOW)
    stamp = _stamp_of(result.text, "Uses SQLite.")
    assert stamp is not None
    assert (stamp.added_at, stamp.agent) == (AT, "claude-code")


def test_striking_a_bullet_records_retirement_but_keeps_its_stamp() -> None:
    first = stamping.update_stamps("- Uses TF-IDF.\n", "x", "codex", NOW)
    struck = first.text.replace("Uses TF-IDF.", "~~Uses TF-IDF.~~")
    later = NOW + timedelta(days=3)
    result = stamping.update_stamps(struck, "x", "claude-code", later)
    stamp = _stamp_of(result.text, "Uses TF-IDF.")
    assert stamp is not None
    assert (stamp.added_at, stamp.agent) == (AT, "codex")
    assert stamp.retired_at == stamps.format_moment(later)
    assert result.retired == 1
    assert result.stamped == ()


def test_update_stamps_keeps_crlf_line_endings() -> None:
    result = stamping.update_stamps("- Uses SQLite.\r\n", "x", "codex", NOW)
    assert result.text.endswith("-->\r\n")


SUPERSEDED = f"""\
# search

- Kept fact. <!-- {AT} codex #aaaa -->

## bm25.py
- Ranking uses BM25. <!-- {AT} codex #bbbb -->
  - ~~Ranking uses TF-IDF.~~ <!-- 2026-01-01T09:00-04:00 codex #cccc retired 2026-06-01T09:00-04:00 -->
  - ~~Ranking uses counts.~~ <!-- 2026-01-01T09:00-04:00 codex #dddd retired 2026-10-01T09:00-04:00 -->
- ~~Stems with Porter.~~ <!-- 2026-01-01T09:00-04:00 codex #eeee retired 2026-05-01T09:00-04:00 -->
"""


def test_archive_retired_moves_only_notes_past_the_age_limit() -> None:
    result = stamping.archive_retired(SUPERSEDED, "", "x", NOW)
    assert [bullet.text for bullet in result.moved] == [
        "Ranking uses TF-IDF.",
        "Stems with Porter.",
    ]
    assert "Ranking uses TF-IDF." not in result.text
    assert "Stems with Porter." not in result.text
    assert "Ranking uses counts." in result.text


def test_archive_retired_records_replacement_and_entity() -> None:
    result = stamping.archive_retired(SUPERSEDED, "", "x", NOW)
    archive = parser.parse_file(result.archive_text, "x")
    assert archive.folder_entity == "search"
    by_text = {bullet.text: bullet for bullet in archive.bullets}
    superseded = by_text["Ranking uses TF-IDF."]
    assert superseded.struck
    assert superseded.entity == "bm25.py"
    assert superseded.stamp is not None
    assert superseded.stamp.superseded_by == stamps.calc_hash(
        "Ranking uses BM25."
    )
    assert by_text["Stems with Porter."].stamp is not None
    assert by_text["Stems with Porter."].stamp.superseded_by is None


def test_archive_retired_appends_to_existing_entity_section() -> None:
    archive_text = (
        "# search\n\n## bm25.py\n- ~~Old.~~ <!-- x y #ffff -->\n\n"
        "## other\n- ~~Other.~~\n"
    )
    result = stamping.archive_retired(SUPERSEDED, archive_text, "x", NOW)
    lines = result.archive_text.split("\n")
    assert lines.index("## bm25.py") < lines.index("## other")
    moved = [line for line in lines if "TF-IDF" in line or "Porter" in line]
    assert all(lines.index(line) < lines.index("## other") for line in moved)


def test_archive_retired_without_due_notes_changes_nothing() -> None:
    result = stamping.archive_retired(
        SUPERSEDED, "", "x", NOW - timedelta(days=365)
    )
    assert (result.text, result.archive_text, result.moved) == (
        SUPERSEDED,
        "",
        (),
    )
