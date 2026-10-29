# plain-text-memory-mcp

MCP server that gathers a repo's Markdown memory files into one searchable,
stamped knowledge graph.

Agents keep memory in `MEMORY.ptm.md` files, one per folder that needs it,
and edit them with their normal file tools. The server reads every such file,
plus each `AGENTS.md`, and serves them as one graph: search returns only the
facts that match, ranked and scoped to the folder in question, instead of an
agent reading whole files on every task. After an agent edits a file, the
server stamps each new line with the date and the agent that wrote it.

It grew out of `@modelcontextprotocol/server-memory`, but stores nothing of
its own: the Markdown files are the memory, and they belong in git.

## Install

The server runs with [uv](https://docs.astral.sh/uv/); `uvx` downloads and
starts it on demand, so there is nothing else to install.

```shell
uvx plain-text-memory-mcp
```

Started by hand, it waits for an MCP client on stdin; press Ctrl+C to stop.

## Configure

Add the server to each agent's MCP config. The server finds the repo from the
folder the agent starts it in, so register it per project.

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

## Memory files

A `MEMORY.ptm.md` file holds facts about the folder it sits in and every
folder below it. The one at the repo root holds repo-wide facts.

```markdown
# search

Ranks notes with BM25 plus spreading activation.

## bm25.py
- Tokenizes with a lowercase word regex and does no stemming. <!-- 2026-10-09T14:02-04:00 claude-code #9f2ce -->
- uses [[ranking.py]] <!-- 2026-10-09T14:02-04:00 claude-code #41b0e -->
- Ranking uses BM25 over TF-IDF, because TF-IDF ranked long notes too high. <!-- 2026-10-09T14:05-04:00 codex #c3d4e -->
  - ~~Ranking uses TF-IDF.~~ <!-- 2026-10-01T09:15-04:00 codex #a1b2e retired 2026-10-09T14:05-04:00 -->
```

- `# name` names the folder. Without it, the folder's own name is used.
- `## name` starts an entity, such as a module; bullets after it belong to
  it.
- Each `-` bullet is one fact on one line. The facts worth saving are the
  ones the code cannot show: decisions and why they were made, options
  tried and dropped, and limits found the hard way.
- A bullet that is only a short verb and a `[[link]]` is a relation to
  another entity, in any memory file.
- A fact that stops being true is struck through with `~~` and nested under
  the fact that replaced it, which says why, so its history stays in the
  file.

The server finds the files with `git ls-files`, so `.gitignore` decides
which are skipped; outside git, it skips dot folders. It reads `AGENTS.md`
files too, as read-only notes grouped by heading. Edits show up in the next
search without a restart.

## Stamps

Agents never write the `<!-- -->` comments. After editing, an agent calls
`stamp_notes` with the files it changed, and the server adds a stamp to each
new or reworded line:

- the time (local, to the minute, with UTC offset),
- the agent (`claude-code`, `codex`, or the client's own name; set
  `MEMORY_AGENT` to override it), and
- a short hash of the text, so a reworded line is stamped again.

A newly struck line gets its retirement time. Struck lines retired more than
90 days ago move to `MEMORY.ptm.archive.md` in the same folder, so live
files stay short. Only the named files change. Lines nobody has stamped,
and all `AGENTS.md` text, show `null` for the date and agent.

`stamp_notes` also returns `warnings` for lines that:

- reword a fact already saved (`near_duplicate`, word-shingle resemblance;
  Broder, 1997),
- read as instructions to an agent (`instruction_like`),
- look like a secret, such as an API key or private key (`secret`),
- state a fact with no word such as "because" or "so" that gives its
  reason (`no_reason`), or
- link to an entity no memory file names (`broken_link`);

and for any named file longer than 200 lines (`long_file`).

## Search

`search_nodes` ranks with BM25 (Robertson & Zaragoza, 2009): words match
whole, ignoring case and plain plurals, a `"quoted phrase"` must appear
whole, and rare words count more than common ones. Each note is scored on
its own and returned under `hits` with its entity name, rank, and the `path`
of the file it came from, alongside the matching entities. Scores get a
small boost from ACT-R base-level activation (Anderson et al., 2004), which
counts when a line was stamped and when agents opened its entity; with no
opens, this is power-law recency (Anderson & Schooler, 1991).

- `limit` caps the entities and hits returned.
- `since`, `before`, and `agent` filter by stamp.
- `expand` spreads scores along relations with personalized PageRank
  (HippoRAG, Gutiérrez et al., 2024), so linked entities can join the
  results.
- Struck facts are hidden unless `include_superseded` is set.
- Both lists put the strongest results at the start and end and the weakest
  in the middle, because models read the middle of a long context worst
  (Liu et al., 2024).

`recall` searches in numbered steps, after the
[sequentialthinking](https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking)
server. Each step gives a reason, runs up to three queries, and can open
entities. A step returns at most eight hits, and never one that an earlier
step of the same session returned, plus the linked entities not yet opened.
Given a `path`, notes from memory files in folders covering it rank higher.
The last step records a conclusion and the notes it rests on.

`open_nodes` returns entities by exact name.

## Local files

The server keeps a few local files in `<repo root>/.agents/ptm/`; ignore
them with the `.gitignore` line `.agents/ptm/`.

- `stamp.lock` serializes stamping, so Claude Code and Codex can
  stamp the same repo at the same time.
- `access.jsonl` logs each opened entity; search uses it to
  rank often-opened entities higher. Deleting it only resets that ranking.

## Guidance for agents

On connect, the server sends every MCP client instructions for using memory
well: recall in steps before planning, verify what memory says against the
repo, save only lasting facts in the narrowest folder, and call
`stamp_notes` after editing. Tool and parameter descriptions say what each
tool does and returns. No agent-specific setup is needed.

## Taxonomy

[taxonomy.json](src/plain_text_memory_mcp/taxonomy.json) lists every record
type with its purpose and fields, every tool with its parameters and results,
every MCP resource, and the allowed values for enum fields such as `agent`.
It is generated from the code; do not edit it by hand. Record type purposes
live in `RECORD_PURPOSES` in `records.py`. The file ships inside the
package, and MCP clients can read it as the resource `memory://taxonomy`.

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

Set `MEMORY_RECALL_LOG=1` in the server's environment to append every
`recall` step, `search_nodes` call, and `open_nodes` call to
`.agents/ptm/recall.jsonl`: what was searched, why, the hits, and
the conclusion. The log is for developing the server; it is off by default
and never read back.

## License

MIT, copyright Plain Text Office LLC. See [LICENSE](LICENSE).
