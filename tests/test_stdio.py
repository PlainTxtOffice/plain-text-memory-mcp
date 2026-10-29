"""End-to-end test: launch the server as a subprocess over stdio."""

import subprocess
import sys
from pathlib import Path

import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.types import Implementation

TOOL_NAMES = {"search_nodes", "open_nodes", "recall", "stamp_notes"}


def test_stdio_server_stamps_files_from_the_repo_root(tmp_path: Path) -> None:
    # A real repo, so git never falls through to an enclosing repo's
    # ignore rules when the temp folder sits inside one.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    workdir = tmp_path / "src"
    workdir.mkdir()
    memory_file = workdir / "MEMORY.ptm.md"
    memory_file.write_bytes(b"- The app stores notes in SQLite.\n")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "plain_text_memory_mcp.server"],
        cwd=workdir,
    )
    info = Implementation(name="codex-mcp-client", version="0")

    async def scenario() -> tuple[set[str], list[str]]:
        async with Client(params, client_info=info) as client:
            tools = await client.list_tools()
            result = await client.call_tool(
                "stamp_notes", {"paths": ["src/MEMORY.ptm.md"]}
            )
            assert not result.is_error, result.content
            found = await client.call_tool("search_nodes", {"query": "sqlite"})
            assert found.structured_content is not None
            hits = found.structured_content["hits"]
            paths = [hit["note"]["path"] for hit in hits]
            return {tool.name for tool in tools.tools}, paths

    tool_names, paths = anyio.run(scenario)
    assert tool_names == TOOL_NAMES
    assert paths == ["src/MEMORY.ptm.md"]
    assert " codex #" in memory_file.read_bytes().decode("utf-8")
    assert (tmp_path / ".agents" / "ptm").is_dir()
