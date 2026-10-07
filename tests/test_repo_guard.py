"""Tests for the header stamp, repo mismatch block, and initialize_memory."""

import json
from pathlib import Path

import anyio
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, Implementation

from plain_text_memory_mcp.server import build_server

APP = {"name": "app", "entityType": "project", "observations": ["Uses SQLite"]}


def _client(server: MCPServer) -> Client:
    info = Implementation(name="codex-mcp-client", version="0")
    return Client(server, client_info=info)


def _call(server: MCPServer, tool: str, arguments: dict) -> CallToolResult:
    async def scenario() -> CallToolResult:
        async with _client(server) as client:
            return await client.call_tool(tool, arguments)

    return anyio.run(scenario)


def _read_lines(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


def _make_repo(parent: Path, name: str) -> Path:
    repo_root = parent / name
    (repo_root / ".agents").mkdir(parents=True)
    return repo_root


def test_first_write_stamps_header(tmp_path: Path) -> None:
    repo_root = _make_repo(tmp_path, "reading_list")
    path = repo_root / ".agents" / "memory.local.jsonl"
    server = build_server(path, None, repo_root)
    assert not _call(server, "create_entities", {"entities": [APP]}).is_error
    header, entity = _read_lines(path)
    assert header["type"] == "header"
    assert header["repo_name"] == "reading_list"
    assert header["repo_root"] == repo_root.as_posix()
    assert header["agent"] == "codex"
    assert entity["name"] == "app"


def test_copied_memory_blocks_reads_and_writes(tmp_path: Path) -> None:
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
    before = project_path.read_bytes()
    server = build_server(project_path, None, project)
    for tool, arguments in [
        ("read_graph", {}),
        ("search_nodes", {"query": "app"}),
        ("create_entities", {"entities": [APP]}),
        ("delete_entities", {"entityNames": ["app"]}),
    ]:
        result = _call(server, tool, arguments)
        assert result.is_error, tool
        text = result.content[0].text
        assert "python-vscode-template" in text
        assert "initialize_memory" in text
    assert project_path.read_bytes() == before


def test_initialize_fresh_backs_up_copied_memory(tmp_path: Path) -> None:
    template = _make_repo(tmp_path, "python-vscode-template")
    template_path = template / ".agents" / "memory.local.jsonl"
    _call(
        build_server(template_path, None, template),
        "create_entities",
        {"entities": [APP]},
    )
    project = _make_repo(tmp_path, "new_project")
    project_path = project / ".agents" / "memory.local.jsonl"
    copied = template_path.read_bytes()
    project_path.write_bytes(copied)
    server = build_server(project_path, None, project)
    result = _call(server, "initialize_memory", {"mode": "fresh"})
    assert not result.is_error, result.content
    content = result.structured_content
    assert content is not None
    assert content["status"] == "fresh"
    backup = Path(content["backup"])
    assert backup.parent == project_path.parent
    assert backup.name.startswith("memory.local.jsonl.bak-")
    assert backup.read_bytes() == copied
    [header] = _read_lines(project_path)
    assert header["repo_name"] == "new_project"
    graph = _call(server, "read_graph", {}).structured_content
    assert graph == {"entities": [], "relations": []}


def test_initialize_adopt_keeps_memories(tmp_path: Path) -> None:
    old_root = _make_repo(tmp_path, "old_name")
    path = old_root / ".agents" / "memory.local.jsonl"
    _call(
        build_server(path, None, old_root),
        "create_entities",
        {"entities": [APP]},
    )
    new_root = tmp_path / "new_name"
    old_root.rename(new_root)
    new_path = new_root / ".agents" / "memory.local.jsonl"
    server = build_server(new_path, None, new_root)
    assert _call(server, "read_graph", {}).is_error
    result = _call(server, "initialize_memory", {"mode": "adopt"})
    assert result.structured_content["status"] == "adopted"
    header, entity = _read_lines(new_path)
    assert header["repo_root"] == new_root.as_posix()
    assert entity["name"] == "app"
    graph = _call(server, "read_graph", {}).structured_content
    assert [e["name"] for e in graph["entities"]] == ["app"]


def test_initialize_matching_header_is_unchanged(tmp_path: Path) -> None:
    repo_root = _make_repo(tmp_path, "repo")
    path = repo_root / ".agents" / "memory.local.jsonl"
    server = build_server(path, None, repo_root)
    _call(server, "create_entities", {"entities": [APP]})
    before = path.read_bytes()
    for mode in ("fresh", "adopt"):
        result = _call(server, "initialize_memory", {"mode": mode})
        assert result.structured_content["status"] == "unchanged"
    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.bak-*"))


def test_initialize_on_missing_file_creates_header(tmp_path: Path) -> None:
    repo_root = _make_repo(tmp_path, "repo")
    path = repo_root / ".agents" / "memory.local.jsonl"
    server = build_server(path, None, repo_root)
    result = _call(server, "initialize_memory", {"mode": "fresh"})
    assert result.structured_content["status"] == "initialized"
    [header] = _read_lines(path)
    assert header["repo_root"] == repo_root.as_posix()


def test_legacy_file_without_header_is_adopted_on_write(
    tmp_path: Path,
) -> None:
    repo_root = _make_repo(tmp_path, "reading_list")
    path = repo_root / ".agents" / "memory.local.jsonl"
    legacy = {"type": "entity", "name": "old", "entityType": "repo"}
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    server = build_server(path, None, repo_root)
    assert not _call(server, "read_graph", {}).is_error
    _call(server, "create_entities", {"entities": [APP]})
    header, old, app = _read_lines(path)
    assert header["repo_name"] == "reading_list"
    assert [old["name"], app["name"]] == ["old", "app"]
