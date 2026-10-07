"""Tests for the generated, versioned taxonomy shipped in the package."""

import copy
import json
from pathlib import Path

import taxonomy

from plain_text_memory_mcp import records

REPO_ROOT = Path(__file__).resolve().parents[1]
TODAY = "2026-09-29"

CONTENT = {
    "package": {"name": "plain-text-memory-mcp", "version": "0.1.0"},
    "record_types": {"header": {"fields": {"repo_root": "string"}}},
    "enums": {"agent": ["claude-code", "codex", "unknown"]},
    "tools": {
        "read_graph": {
            "description": "Read the entire knowledge graph.",
            "params": {},
        }
    },
    "prompts": {
        "cleanup": {
            "title": "Clean up memory",
            "description": "Propose deletions for approval.",
            "arguments": [],
        }
    },
}


def _first_document() -> dict:
    document = taxonomy.update_document(None, CONTENT, TODAY)
    assert document is not None
    return document


def _changed(edit: callable) -> dict:
    content = copy.deepcopy(CONTENT)
    edit(content)
    return content


def test_first_build_starts_at_1_0_0() -> None:
    document = _first_document()
    assert document["taxonomy_version"] == "1.0.0"
    assert document["changelog"] == [
        {"version": "1.0.0", "date": TODAY, "changes": ["initial taxonomy"]}
    ]
    assert document["tools"] == CONTENT["tools"]


def test_unchanged_content_is_not_rewritten() -> None:
    document = _first_document()
    assert taxonomy.update_document(document, CONTENT, "2026-10-01") is None


def test_added_tool_bumps_minor() -> None:
    content = _changed(
        lambda c: c["tools"].update(
            {"open_nodes": {"description": "Open nodes.", "params": {}}}
        )
    )
    document = taxonomy.update_document(_first_document(), content, TODAY)
    assert document["taxonomy_version"] == "1.1.0"
    assert "added: tools.open_nodes" in document["changelog"][0]["changes"]


def test_added_enum_value_bumps_minor() -> None:
    content = _changed(lambda c: c["enums"]["agent"].append("copilot"))
    document = taxonomy.update_document(_first_document(), content, TODAY)
    assert document["taxonomy_version"] == "1.1.0"
    assert document["changelog"][0]["changes"] == [
        "added: enums.agent[copilot]"
    ]


def test_removed_field_bumps_major() -> None:
    content = _changed(
        lambda c: c["record_types"]["header"]["fields"].pop("repo_root")
    )
    document = taxonomy.update_document(_first_document(), content, TODAY)
    assert document["taxonomy_version"] == "2.0.0"
    assert document["changelog"][0]["changes"] == [
        "removed: record_types.header.fields.repo_root"
    ]


def test_changed_field_type_bumps_major() -> None:
    def edit(content: dict) -> None:
        content["record_types"]["header"]["fields"]["repo_root"] = "number"

    document = taxonomy.update_document(
        _first_document(), _changed(edit), TODAY
    )
    assert document["taxonomy_version"] == "2.0.0"
    assert document["changelog"][0]["changes"] == [
        "changed: record_types.header.fields.repo_root (string -> number)"
    ]


def test_description_or_title_change_bumps_patch() -> None:
    def edit(content: dict) -> None:
        content["tools"]["read_graph"]["description"] = "Read everything."
        content["prompts"]["cleanup"]["title"] = "Tidy memory"

    document = taxonomy.update_document(
        _first_document(), _changed(edit), TODAY
    )
    assert document["taxonomy_version"] == "1.0.1"


def test_highest_bump_wins_and_changelog_is_newest_first() -> None:
    def edit(content: dict) -> None:
        content["tools"]["read_graph"]["description"] = "Read everything."
        content["enums"]["agent"].remove("unknown")

    document = taxonomy.update_document(
        _first_document(), _changed(edit), TODAY
    )
    assert document["taxonomy_version"] == "2.0.0"
    assert [entry["version"] for entry in document["changelog"]] == [
        "2.0.0",
        "1.0.0",
    ]


def test_build_content_reads_tools_records_and_enums() -> None:
    content = taxonomy.build_content()
    tools = content["tools"]
    assert tools["initialize_memory"]["params"] == {"mode": "fresh|adopt"}
    assert tools["create_entities"]["params"] == {
        "entities": [
            {
                "name": "string",
                "entityType": "string",
                "observations": ["string"],
            }
        ]
    }
    assert content["enums"]["initialize_memory.status"] == [
        "unchanged",
        "fresh",
        "initialized",
        "adopted",
    ]
    assert content["enums"]["agent"] == ["claude-code", "codex", "unknown"]
    # An optional parameter is a type, not a set of allowed values.
    assert "read_graph.since" not in content["enums"]
    header = content["record_types"]["header"]["fields"]
    assert header["type"] == '"header"'
    assert header["added_at"] == "string|null"
    entity = content["record_types"]["entity"]["fields"]
    assert entity["observations"] == "observation[]"
    observation = content["record_types"]["observation"]["fields"]
    assert observation["agent"] == "string|null"
    assert observation["edited_at"] == "string|null (optional)"


def test_committed_taxonomy_is_current() -> None:
    path = REPO_ROOT / "src" / "plain_text_memory_mcp" / "taxonomy.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    content = taxonomy.build_content()
    assert taxonomy.update_document(document, content, TODAY) is None, (
        "taxonomy.json is stale; run "
        "`.venv/Scripts/python.exe scripts/build_taxonomy.py`"
    )


def test_build_content_gives_each_record_type_a_purpose() -> None:
    record_types = taxonomy.build_content()["record_types"]
    purposes = {kind: spec["purpose"] for kind, spec in record_types.items()}
    assert purposes == records.RECORD_PURPOSES
    assert set(purposes) == {
        "header",
        "entity",
        "relation",
        "observation",
        "tombstone",
        "access",
    }


def test_purpose_change_bumps_patch() -> None:
    first = taxonomy.update_document(None, CONTENT, TODAY)
    content = copy.deepcopy(CONTENT)
    content["record_types"]["header"]["purpose"] = "Names the owning repo."
    first["record_types"]["header"]["purpose"] = "Old wording."
    document = taxonomy.update_document(first, content, TODAY)
    assert document["taxonomy_version"] == "1.0.1"


def test_build_content_reads_tool_returns() -> None:
    tools = taxonomy.build_content()["tools"]
    assert all("returns" in spec for spec in tools.values())
    assert tools["create_relations"]["returns"]["skipped"] == [
        {
            "from": "string",
            "to": "string",
            "relationType": "string",
            "missing": ["string"],
        }
    ]
    relation = tools["read_graph"]["returns"]["relations"][0]
    assert relation["type"] == '"relation"'
    assert relation["added_at"] == "string|null"
    assert tools["initialize_memory"]["returns"]["status"] == (
        "unchanged|fresh|initialized|adopted"
    )


def test_build_content_reads_resources() -> None:
    content = taxonomy.build_content()
    assert list(content) == [*taxonomy.CONTENT_KEYS]
    resource = content["resources"]["memory://taxonomy"]
    assert resource["name"] == "taxonomy"
    assert resource["title"] == "Memory taxonomy"
    assert resource["mime_type"] == "application/json"
    assert resource["description"].startswith("The server's versioned schema")


def test_build_content_reads_prompts() -> None:
    prompts = taxonomy.build_content()["prompts"]
    assert list(prompts) == ["cleanup", "export", "reflect"]
    assert prompts["cleanup"]["title"] == "Clean up memory"
    assert prompts["export"]["arguments"] == []
    assert prompts["export"]["description"].startswith("Write this repo's")


def test_dropped_section_bumps_major() -> None:
    document = _first_document()
    document["retired"] = {"old-item": {"version": "1.0.0"}}
    updated = taxonomy.update_document(document, copy.deepcopy(CONTENT), TODAY)
    assert updated is not None
    assert updated["taxonomy_version"] == "2.0.0"
    assert "retired" not in updated
    assert any(
        change.startswith("removed: retired")
        for change in updated["changelog"][0]["changes"]
    )
