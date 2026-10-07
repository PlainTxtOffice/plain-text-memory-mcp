"""End-to-end test: launch the server as a subprocess over stdio."""

import json
import sys
from pathlib import Path

import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.types import Implementation

TOOL_NAMES = {
    "create_entities",
    "create_relations",
    "add_observations",
    "delete_entities",
    "delete_observations",
    "delete_relations",
    "read_graph",
    "search_nodes",
    "open_nodes",
    "initialize_memory",
    "export_taxonomy",
    "rename_entity",
    "merge_entities",
    "edit_observation",
    "supersede_observation",
}


def test_stdio_server_writes_tagged_file_at_repo_root(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    workdir = tmp_path / "src"
    workdir.mkdir()
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "plain_text_memory_mcp.server"],
        cwd=workdir,
    )
    info = Implementation(name="codex-mcp-client", version="0")
    entity = {"name": "app", "entityType": "project", "observations": ["x"]}

    async def scenario() -> set[str]:
        async with Client(params, client_info=info) as client:
            tools = await client.list_tools()
            result = await client.call_tool(
                "create_entities", {"entities": [entity]}
            )
            assert not result.is_error, result.content
            return {tool.name for tool in tools.tools}

    assert anyio.run(scenario) == TOOL_NAMES
    memory_path = tmp_path / ".agents" / "memory.local.jsonl"
    header_line, line = memory_path.read_text(encoding="utf-8").splitlines()
    assert json.loads(header_line)["repo_root"] == tmp_path.as_posix()
    record = json.loads(line)
    assert record["agent"] == "codex"
    assert record["observations"][0]["agent"] == "codex"


def _stdio_params(repo_root: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "plain_text_memory_mcp.server"],
        cwd=repo_root,
    )


def test_stdio_server_blocks_memory_copied_from_another_repo(
    tmp_path: Path,
) -> None:
    template = tmp_path / "python-vscode-template"
    project = tmp_path / "new_project"
    for repo_root in (template, project):
        (repo_root / ".git").mkdir(parents=True)
    info = Implementation(name="claude-code", version="0")
    entity = {"name": "app", "entityType": "project", "observations": ["x"]}

    async def write_template() -> None:
        async with Client(_stdio_params(template), client_info=info) as client:
            await client.call_tool("create_entities", {"entities": [entity]})

    async def read_project() -> tuple[bool, str, bool]:
        async with Client(_stdio_params(project), client_info=info) as client:
            blocked = await client.call_tool("read_graph", {})
            await client.call_tool("initialize_memory", {"mode": "fresh"})
            after = await client.call_tool("read_graph", {})
            return blocked.is_error, blocked.content[0].text, after.is_error

    anyio.run(write_template)
    relative = Path(".agents") / "memory.local.jsonl"
    (project / ".agents").mkdir()
    (project / relative).write_bytes((template / relative).read_bytes())
    blocked, message, still_blocked = anyio.run(read_project)
    assert blocked
    assert "python-vscode-template" in message
    assert not still_blocked
