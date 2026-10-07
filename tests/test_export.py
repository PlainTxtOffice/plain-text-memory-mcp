"""Tests for export_taxonomy: the schema plus this repo's memory usage."""

import json
from pathlib import Path

import anyio
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, Implementation

from plain_text_memory_mcp import graph, records, storage
from plain_text_memory_mcp.graph import (
    UNTAGGED,
    Entity,
    Graph,
    Observation,
    Relation,
    Tag,
)
from plain_text_memory_mcp.server import build_server

TAG_A = Tag("2026-09-29T10:00:00-04:00", "claude-code")
TAG_B = Tag("2026-09-29T11:00:00-04:00", "codex")
APP = {"name": "app", "entityType": "project", "observations": ["Uses SQLite"]}
DB = {"name": "db", "entityType": "library", "observations": []}
USES = {"from": "app", "to": "db", "relationType": "uses"}


def _call(server: MCPServer, tool: str, arguments: dict) -> CallToolResult:
    async def scenario() -> CallToolResult:
        info = Implementation(name="codex-mcp-client", version="0")
        async with Client(server, client_info=info) as client:
            return await client.call_tool(tool, arguments)

    return anyio.run(scenario)


def _load_jsonc(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    code = [line for line in lines if not line.lstrip().startswith("//")]
    return json.loads("\n".join(code))


def _make_repo(parent: Path, name: str) -> Path:
    repo_root = parent / name
    (repo_root / ".agents").mkdir(parents=True)
    return repo_root


def test_calc_usage_counts_types_and_agents() -> None:
    memory = Graph(
        [
            Entity(
                "app",
                "project",
                [Observation("a", TAG_A), Observation("b", UNTAGGED)],
                TAG_B,
            ),
            Entity("db", "library", [], TAG_A),
        ],
        [Relation("app", "db", "uses", TAG_B)],
    )
    assert graph.calc_usage(memory) == {
        "counts": {"entities": 2, "observations": 2, "relations": 1},
        "entity_types": {"library": 1, "project": 1},
        "relation_types": {"uses": 1},
        "agents": {"claude-code": 2, "codex": 2, "untagged": 1},
    }


def test_load_schema_reads_package_taxonomy() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "src" / "plain_text_memory_mcp" / "taxonomy.json"
    assert storage.load_schema() == json.loads(path.read_text(encoding="utf-8"))


def test_export_taxonomy_writes_schema_and_usage(tmp_path: Path) -> None:
    repo_root = _make_repo(tmp_path, "reading_list")
    path = repo_root / ".agents" / "memory.local.jsonl"
    server = build_server(path, None, repo_root)
    _call(server, "create_entities", {"entities": [APP, DB]})
    _call(server, "create_relations", {"relations": [USES]})
    result = _call(server, "export_taxonomy", {})
    assert not result.is_error, result.content
    export_path = repo_root / ".agents" / "memory.local.taxonomy.jsonc"
    assert result.structured_content["path"] == str(export_path)
    exported = _load_jsonc(export_path)
    expected_schema = storage.load_schema()
    for record_type in expected_schema["record_types"].values():
        record_type.pop("purpose")
    assert exported["schema"] == expected_schema
    repo = exported["repo"]
    assert repo["repo_name"] == "reading_list"
    assert repo["exported_by"] == "codex"
    assert repo["counts"] == {"entities": 2, "observations": 1, "relations": 1}
    assert repo["entity_types"] == {"library": 1, "project": 1}
    assert repo["relation_types"] == {"uses": 1}


def test_export_taxonomy_blocked_for_copied_memory(tmp_path: Path) -> None:
    template = _make_repo(tmp_path, "python-vscode-template")
    template_path = template / ".agents" / "memory.local.jsonl"
    _call(
        build_server(template_path, None, template),
        "create_entities",
        {"entities": [APP]},
    )
    project = _make_repo(tmp_path, "new_project")
    project_path = project / ".agents" / "memory.local.jsonl"
    project_path.write_bytes(template_path.read_bytes())
    result = _call(
        build_server(project_path, None, project), "export_taxonomy", {}
    )
    assert result.is_error
    assert "python-vscode-template" in result.content[0].text
    assert not (project / ".agents" / "memory.local.taxonomy.json").exists()


def test_export_comments_each_record_type_with_its_purpose(
    tmp_path: Path,
) -> None:
    repo_root = _make_repo(tmp_path, "reading_list")
    path = repo_root / ".agents" / "memory.local.jsonl"
    _call(build_server(path, None, repo_root), "export_taxonomy", {})
    export_path = repo_root / ".agents" / "memory.local.taxonomy.jsonc"
    lines = export_path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("// ")
    for kind, purpose in records.RECORD_PURPOSES.items():
        index = next(
            i for i, line in enumerate(lines) if line.strip() == f'"{kind}": {{'
        )
        assert lines[index - 1].strip() == f"// {purpose}"
    record_types = next(
        i for i, line in enumerate(lines) if '"record_types": {' in line
    )
    assert lines[record_types - 1].strip().startswith("// Record types")


def test_format_jsonc_places_comments_and_stays_valid() -> None:
    value = {"a": {"b": [1, 2], "c": {}}, "d": "x"}
    comments = {(): "top", ("a",): "about a", ("a", "c"): "about c"}
    text = storage.format_jsonc(value, comments)
    assert text.splitlines() == [
        "// top",
        "{",
        "  // about a",
        '  "a": {',
        '    "b": [',
        "      1,",
        "      2",
        "    ],",
        "    // about c",
        '    "c": {}',
        "  },",
        '  "d": "x"',
        "}",
    ]
