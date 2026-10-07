# plain-text-memory-mcp

Knowledge-graph memory MCP server that tags every entry with the date it was
added and the agent that added it. Memory lives in a plain JSONL file inside
each repo, so every agent working in that repo shares it.

It is a drop-in replacement for `@modelcontextprotocol/server-memory`: the
same nine tools and input keys, and it reads files written by the original
server. It adds `edit_observation`, `supersede_observation`,
`rename_entity`, `merge_entities`, `initialize_memory`, and
`export_taxonomy`; ranked search with observation-level hits; date, agent,
and limit filters on `read_graph` and `search_nodes`; write warnings; the
`cleanup`, `reflect`, and `export` prompts; and the `memory://taxonomy`
resource.

## Install

The server runs with [uv](https://docs.astral.sh/uv/); `uvx` downloads and
starts it on demand, so there is nothing else to install.

```shell
uvx plain-text-memory-mcp
```

Started by hand, it waits for an MCP client on stdin; press Ctrl+C to stop.

## Configure

Add the server to each agent's MCP config. The server finds the repo from the
folder the agent starts it in, so register it per project, or set
`MEMORY_FILE_PATH` if a client starts servers somewhere else.

Claude Code, `.mcp.json` in the repo:

```json
{
  "mcpServers": {
    "plain-text-memory": {
      "type": "stdio",
      "command": "uvx",
      "args": ["plain-text-memory-mcp"]
    }
  }
}
```

Codex, `.codex/config.toml`:

```toml
[mcp_servers.plain-text-memory]
command = "uvx"
args = ["plain-text-memory-mcp"]
```

Cursor, `.cursor/mcp.json` in the repo:

```json
{
  "mcpServers": {
    "plain-text-memory": {
      "command": "uvx",
      "args": ["plain-text-memory-mcp"]
    }
  }
}
```

VS Code, `.vscode/mcp.json` in the repo:

```json
{
  "servers": {
    "plain-text-memory": {
      "type": "stdio",
      "command": "uvx",
      "args": ["plain-text-memory-mcp"]
    }
  }
}
```

## Where memory is stored

1. `MEMORY_FILE_PATH`, if set. A relative path resolves against the folder
   the agent starts the server in.
1. `<git root>/.agents/memory.local.jsonl`.
1. `<start folder>/.agents/memory.local.jsonl` outside a git repo.

Writes hold a lock on `memory.local.jsonl.lock` beside the memory file, so
Claude Code and Codex can write to the same repo's memory at the same time
without losing each other's changes. The file stays after the server exits;
leave it in place.

The file is a log. Writes append only the entities and relations that
changed, plus a `tombstone` line for each removal; a later line for the same
entity or relation replaces the earlier one. Once the log grows past about
twice the size of a fresh copy, the next write compacts it back to one line
per record. The original `@modelcontextprotocol/server-memory` cannot read
tombstone lines, so switch back only from a compacted file.

`open_nodes` appends one line per opened entity to
`memory.local.access.jsonl` beside the memory file; search uses it to rank
often-opened entities higher. Deleting it only resets that ranking.

## Tags

Every entity, relation, and observation carries `added_at` (local time with
UTC offset) and `agent` (`claude-code`, `codex`, or the client's own name).
Set `MEMORY_AGENT` to override the agent name. Entries written by the original
server show `null` for both.

## Repo guard

The first write adds a header line recording which repo the memory file
belongs to. If the file is later found in a different repo, for example after
copying `.agents/` from a template, every tool returns an error instead of
serving the other repo's memories. Resolve it with the `initialize_memory`
tool:

- `mode: "fresh"` renames the old file to `memory.local.jsonl.bak-<time>` and
  starts an empty graph.
- `mode: "adopt"` keeps the memories and points the header at this repo, for
  a repo that was moved or renamed.

Files without a header, including ones written by the original server, are
claimed by the repo that writes to them first.

## Search

`search_nodes` ranks with BM25 (Robertson & Zaragoza, 2009): words match
whole, ignoring case and plain plurals, a `"quoted phrase"` must appear
whole, and rare words count more than common ones. Each observation is
scored on its own and returned under `hits` with its entity name and rank,
alongside the matching entities. Scores get a small boost from ACT-R
base-level activation (Anderson et al., 2004), which counts when an entry
was added or edited and when agents opened it with `open_nodes`; with no
opens, this is power-law recency (Anderson & Schooler, 1991).

- `limit` caps the entities and hits returned.
- `expand` spreads scores along relations with personalized PageRank
  (HippoRAG, Gutiérrez et al., 2024), so linked entities can join the
  results.
- Both lists put the strongest results at the start and end and the weakest
  in the middle, because models read the middle of a long context worst
  (Liu et al., 2024).

## Superseded facts

When a fact stops being true, `supersede_observation` keeps it with
`superseded_at`, `superseded_by`, and `replaced_by` instead of deleting or
overwriting it. Reads hide superseded facts unless `include_superseded` is
set. `edit_observation` stays for fixing the wording of a fact that is still
true.

## Write warnings

`create_entities`, `add_observations`, `edit_observation`, and
`supersede_observation` save every fact and return `warnings` for facts
that:

- reword one already saved (`near_duplicate`, word-shingle resemblance;
  Broder, 1997),
- read as instructions to an agent (`instruction_like`), or
- look like a secret, such as an API key or private key (`secret`).

The server's instructions tell agents that memory is data, not commands.

## Prompts

The server publishes three MCP prompts, which clients offer as commands;
Claude Code shows them as `/mcp__plain-text-memory__cleanup`, for example.

| Prompt | Use |
| --- | --- |
| `cleanup` | Propose deletions and merges; nothing is deleted until approved |
| `reflect` | Propose summary facts that cite their sources; nothing is saved until approved |
| `export` | Write the repo's taxonomy and usage to `.agents/` and report it |

## Guidance for agents

On connect, the server sends every MCP client instructions for using memory
well: search before planning, verify what memory says against the repo, save
only lasting facts, and resolve the repo guard. Tool and parameter
descriptions say what each tool does and returns, and the prompts above
carry the cleanup and export workflows. No agent-specific setup is needed.

## Taxonomy

[taxonomy.json](src/plain_text_memory_mcp/taxonomy.json) lists every record
type with its purpose and fields, every tool with its parameters and results,
every MCP resource and prompt, and the allowed values for enum fields such
as `agent` and `initialize_memory.mode`. It is generated from the code; do
not edit it by hand. Record type purposes live in `RECORD_PURPOSES`
in `records.py`. The file ships inside the package, where the server's
`export_taxonomy` tool reads it. MCP clients can also read it as the
resource `memory://taxonomy`.

`taxonomy_version` follows semantic versioning and bumps itself: a removed
item, section, or changed type is major, an added item is minor, and a
description, purpose, title, or package version change is patch. Each bump
adds a `changelog` entry listing what changed.

Regenerate it with:

```powershell
.venv/Scripts/python.exe scripts/build_taxonomy.py
```

The pre-commit hook runs this and stops the commit when the file changes, so
the new version is reviewed and staged. A test also fails when the committed
file is stale. Enable the hook once per clone:

```powershell
git config core.hooksPath .githooks
```

### Exporting to a repo

Ask an agent to call the `export_taxonomy` tool. It writes
`.agents/memory.local.taxonomy.jsonc` beside the repo's memory file, holding
the versioned schema above plus this repo's usage: entry counts, the entity
and relation types in use, and entries per agent. `//` comments explain each
section and each record type's purpose. Use it to keep type names consistent
within a repo. The export is local, like the memory file; ignore both with
`.agents/*memory.local.*`.

## Develop

```powershell
py -3.13 -m venv .venv
.venv/Scripts/python.exe -m pip install -e . --group dev
.venv/Scripts/python.exe -m pytest
```

To have agents run your working copy instead of the published package,
install it as an editable tool and use `plain-text-memory-mcp` as the
config's command, with no args:

```powershell
uv tool install -e .
```

Code changes then take effect the next time an agent starts the server.

## License

MIT, copyright Plain Text Office LLC. See [LICENSE](LICENSE).
