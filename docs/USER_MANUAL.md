---
last_updated: 2026-10-28
version: 1.1.0
product_version: "0.4.0"
generated_from: "dev-docs/specs/USER_MANUAL_SPEC.instructions.md"
---

# User Manual

## Overview

Plain Text Memory (`plain-text-memory-mcp`) is an MCP server that gives AI
coding agents a shared, searchable memory for one repo. The memory is plain
Markdown: facts live in `MEMORY.ptm.md` files, one per folder that needs
them, and each `AGENTS.md` file is read as well. The server gathers every
such file into one graph, searches it, and stamps each fact with when it was
written and which agent wrote it.
<!-- Verified from: pyproject.toml [project.description]; src/plain_text_memory_mcp/server.py [INSTRUCTIONS] -->

It is for people who work with AI agents such as Claude Code or Codex in a
repo and want those agents to remember facts about the project between
sessions, and to share them with each other. Because the memory is ordinary
text, you can read and edit it yourself and keep it in git.

You work with the server in two ways:

- **Through your agent.** You ask the agent to remember, look up, or update
  facts, and the agent calls the server's tools: `recall`, `search_nodes`,
  `open_nodes`, and `stamp_notes`, plus one read-only resource,
  `memory://taxonomy`.
- **In the memory files.** You or your agent edit `MEMORY.ptm.md` files with
  any text editor. Changes show up in the next search without a restart.
<!-- Verified from: src/plain_text_memory_mcp/server.py [build_server]; src/plain_text_memory_mcp/ptm/index.py [read_memory_file, build_index] -->

The server has no window or menus of its own. When an agent connects, the
server sends it instructions on how to recall and record memory, so the
agent needs no extra setup. This manual shows how to connect Claude Code,
Codex, Cursor, and VS Code. Stamps name Claude Code and Codex as
`claude-code` and `codex`; any other client is named as it reports itself.
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS, build_server]; src/plain_text_memory_mcp/agent.py [KNOWN_AGENTS, calc_agent_name] -->

## Installation and Setup

### Check the Requirements

| Requirement | Why |
| --- | --- |
| [uv](https://docs.astral.sh/uv/) | Provides `uvx`, which downloads and runs the server, and `uv tool install` for a local copy. |
| Python 3.12 or later | The package requires it. |
| A git repo (recommended) | The server finds the repo root from `.git` and uses git to decide which files to skip. Without git it still works on the folder it starts in. |
<!-- Verified from: pyproject.toml [project.requires-python, project.dependencies]; src/plain_text_memory_mcp/server.py [main]; src/plain_text_memory_mcp/ptm/index.py [look_memory_files] -->

### Run the Published Package

The published route needs no install step. Your client runs this command,
and you can run it yourself to check it works:

```shell
uvx plain-text-memory-mcp
```
<!-- Verified from: pyproject.toml [project.name, project.scripts] -->

On the first run, `uvx` downloads the latest release. After that it reuses
its cached copy, so a newer release on PyPI is not picked up on its own.
<!-- Verified from: https://docs.astral.sh/uv/concepts/tools/ -->

### Get the Latest Release

| To | Run or set |
| --- | --- |
| Get the latest release once and refresh the cache | `uvx plain-text-memory-mcp@latest` |
| Check for the latest release every time a client starts the server | `"plain-text-memory-mcp@latest"` in the client's `args` instead of `"plain-text-memory-mcp"` |
| Remove the cached copy, so the next run downloads again | `uv cache clean` |
<!-- Verified from: https://docs.astral.sh/uv/concepts/tools/ -->

### Use a Local Copy

If you have a copy of the server's source folder, install it as a uv tool
instead:

1. Run `uv tool install --editable path/to/plain_text_memory_mcp`.
1. In each client's configuration, set the command to
   `plain-text-memory-mcp` with no arguments, in place of the `uvx` command
   shown in [Connecting Clients](#connecting-clients).
<!-- Verified from: https://docs.astral.sh/uv/reference/cli/#uv-tool-install [--editable]; pyproject.toml [project.scripts] -->

uv places the `plain-text-memory-mcp` command in its executable folder, which
must be on your `PATH` for clients to find it.
<!-- Verified from: https://docs.astral.sh/uv/concepts/tools/ -->

When the local copy's version changes:

1. Close every client that uses the server.
1. Run `uv tool install --editable --reinstall path/to/plain_text_memory_mcp`.
<!-- Verified from: https://docs.astral.sh/uv/reference/cli/#uv-tool-install [--reinstall] -->

On Windows, uv copies the command into its executable folder, and a running
`plain-text-memory-mcp.exe` blocks the reinstall. That is why every client
must be closed first.
<!-- Verified from: https://docs.astral.sh/uv/concepts/tools/ -->

While a local copy is installed, `uvx plain-text-memory-mcp` runs the local
copy instead of the published package. To run the published package, use
`uvx --isolated plain-text-memory-mcp`.
<!-- Verified from: https://docs.astral.sh/uv/concepts/tools/ -->

### Confirm the Command Runs

1. Open a terminal in a folder inside your repo.
1. Run `uvx plain-text-memory-mcp`, or `plain-text-memory-mcp` for a local
   copy.
1. The server prints nothing and waits for an MCP client on standard input.
   That means it started.
1. Press Ctrl+C to stop it.
<!-- Verified from: src/plain_text_memory_mcp/server.py [main] -->

You do not need to start the server by hand for daily use. Each client
starts it from the configuration in the next section.

## Connecting Clients

### How the Server Finds Your Repo

The server serves the repo that contains its working directory, the folder
the client starts it in:

1. It looks for the nearest folder at or above the working directory that
   contains `.git`. A `.git` file counts too, so a git worktree uses its own
   root.
1. Outside git, it uses the working directory itself.
<!-- Verified from: src/plain_text_memory_mcp/server.py [main]; src/plain_text_memory_mcp/storage.py [look_repo_root] -->

So the server must start inside the repo whose memory you want. The
configuration blocks below go in each project's own configuration file.
Codex and VS Code also let you set the working directory with `cwd`.

Every block below uses the published route. For a local copy, replace the
command with `plain-text-memory-mcp` and remove the arguments.

### Register the Server in Each Client

#### Connect Claude Code

Claude Code reads project servers from `.mcp.json` at the project's root:

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

You can also add it from a terminal in the project folder. Everything after
`--` is the command that runs the server:

```shell
claude mcp add --transport stdio --scope project plain-text-memory -- uvx plain-text-memory-mcp
```
<!-- Verified from: https://code.claude.com/docs/en/mcp -->

Where the configuration is kept depends on the scope:

| Scope | Where Claude Code keeps it | Who sees it |
| --- | --- | --- |
| `project` | `.mcp.json` at the project's root | Everyone in the project |
| `local` (the default for `claude mcp add`) | `~/.claude.json`, under that project's path | You, in that project only |
| `user` | `~/.claude.json` | You, in all projects |
<!-- Verified from: https://code.claude.com/docs/en/mcp -->

In interactive sessions, Claude Code asks for your approval before it uses a
server from `.mcp.json`.

To confirm the server connected, run `/mcp` in a session, or run
`claude mcp list` in a terminal, which shows a status such as `✔ Connected`
next to each server.
<!-- Verified from: https://code.claude.com/docs/en/mcp -->

#### Connect Codex

Codex reads servers from `.codex/config.toml` in a project, in trusted
projects only, and from `~/.codex/config.toml` for your user:

```toml
[mcp_servers.plain-text-memory]
command = "uvx"
args = ["plain-text-memory-mcp"]
```

To set the folder the server starts from, add `cwd`, the working directory
to start the server from.

You can also add a server with
`codex mcp add plain-text-memory -- uvx plain-text-memory-mcp`.
<!-- Verified from: https://learn.chatgpt.com/docs/extend/mcp?surface=cli -->

To confirm the server connected, run `/mcp` in a Codex session to see the
active servers, or run `codex mcp list` in a terminal to see the configured
servers.
<!-- Verified from: https://learn.chatgpt.com/docs/extend/mcp?surface=cli -->

#### Connect Cursor

Cursor reads servers from `.cursor/mcp.json` in a project, and from
`~/.cursor/mcp.json` for servers available everywhere:

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
<!-- Verified from: https://cursor.com/docs/context/mcp -->

To confirm the server connected:

1. Open **Customize** in the sidebar, where servers are turned on and off.
   Make sure `plain-text-memory` is on.
1. For details, open the Output panel and select **MCP Logs** from the
   dropdown.
<!-- Verified from: https://cursor.com/docs/context/mcp -->

Cursor asks for approval before using MCP tools by default. Cursor's
documentation says that to update a custom server, you update your local
files and restart Cursor.
<!-- Verified from: https://cursor.com/docs/context/mcp -->

#### Connect VS Code

VS Code reads servers from `.vscode/mcp.json` in a workspace, or from the
`mcp.json` in your user profile. The VS Code format uses a `servers` key:

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
<!-- Verified from: https://code.visualstudio.com/docs/copilot/reference/mcp-configuration; https://code.visualstudio.com/docs/copilot/customization/mcp-servers -->

The `cwd` field sets the server's working directory. It defaults to the
workspace folder when run in a workspace.
<!-- Verified from: https://code.visualstudio.com/docs/copilot/reference/mcp-configuration -->

To confirm the server connected:

1. Run **MCP: List Servers** from the Command Palette and select
   `plain-text-memory`.
1. Choose **Show Output** to see the server's output.
<!-- Verified from: https://code.visualstudio.com/docs/agents/run/manage-mcp-servers -->

After changing the configuration, choose **Restart Server** from the same
list.
<!-- Verified from: https://code.visualstudio.com/docs/agents/run/manage-mcp-servers -->

## Tools

The agent calls these tools; you ask the agent. No tool reaches outside the
repo.

| Tool | What it does | Changes files |
| --- | --- | --- |
| `recall` | Searches memory in steps before a task. | Only the server's local logs in `.agents/ptm/`. |
| `search_nodes` | Runs one ranked search. | Only the recall log, when `MEMORY_RECALL_LOG=1`. |
| `open_nodes` | Returns entities by exact name. | Only the server's local logs in `.agents/ptm/`. |
| `stamp_notes` | Stamps new and changed lines, archives old retired ones, and returns warnings. | Yes: the named `MEMORY.ptm.md` files and their `MEMORY.ptm.archive.md` files. |
| `memory://taxonomy` (resource) | Returns the server's versioned schema. | No. |
<!-- Verified from: src/plain_text_memory_mcp/server.py [register_tool, stamp_notes, search_nodes, open_nodes, recall, read_taxonomy, log_accesses, log_recall] -->

The server tells clients that `recall`, `search_nodes`, and `open_nodes`
are read-only, that `stamp_notes` is not destructive, and that no tool works
outside the repo. The server has no prompts.
<!-- Verified from: src/plain_text_memory_mcp/server.py [register_tool]; src/plain_text_memory_mcp/taxonomy.json [prompts] -->

Every tool reads the memory files fresh, so edits made between calls are
always seen. Results name notes, entities, and relations:

- An **entity** is a named thing, such as a folder or a module.
- A **note** is one fact on an entity. Each note carries `text`, `added_at`,
  `agent`, and `path`, the file it came from, so you know which file to open
  to change it.
- A **relation** links one entity to another, such as `uses [[sqlite]]`.
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS, build_server]; src/plain_text_memory_mcp/records.py [NoteRecord, EntityRecord]; dev-docs/specs/PTM_FILE_SPEC.md [Tools] -->

### `recall`

Title: "Recall memory in steps". `recall` is how agents read memory before
planning. It searches in numbered steps and records why each search was
made. The agent's instructions tell it to call `recall` on its own.

| Parameter | Required | What to pass |
| --- | --- | --- |
| `thought` | Yes | Why this step is taken. |
| `step` | Yes | This step's number, from 1. |
| `total_steps` | Yes | The estimated total; raised to `step` when `step` is larger. |
| `next_step_needed` | Yes | `true` if another step follows. |
| `queries` | No | Up to 3 searches, in the same syntax as `search_nodes`. |
| `open` | No | Exact entity names to return in full. |
| `path` | No | The folder or file the task is about. Notes from memory files in folders covering it rank 1.5 times higher; the root file covers everything, so it gets no boost. |
| `session` | No | The session id from the first step's result; leave it out on the first step. |
| `revises_step` | No | An earlier step of this session that this one corrects. |
| `conclusion` | On the last step | What memory showed. |
| `sources` | No | The notes the conclusion rests on, each as `entityName` and exact `text`. |
<!-- Verified from: src/plain_text_memory_mcp/server.py [recall, SourceInput]; src/plain_text_memory_mcp/search/ranking.py [SCOPE_BOOST] -->

Each step:

1. Runs its `queries` and opens the entities named in `open`.
1. Returns at most eight hits, never one an earlier step of the same session
   already returned. `seen` counts those skipped.
1. Returns up to three small matching entities whole, so the facts around a
   hit come along. Larger entities, and linked ones not yet opened, are
   listed under `unopened`, up to eight names.
<!-- Verified from: src/plain_text_memory_mcp/server.py [recall]; src/plain_text_memory_mcp/search/recall.py [STEP_HIT_LIMIT, AUTO_OPEN_MAX_FACTS, AUTO_OPEN_LIMIT, UNOPENED_LIMIT] -->

The result holds `session`, `step`, `total_steps`, `next_step_needed`,
`hits`, `entities`, `relations`, `unopened`, `seen`, and `warnings`. The last
step sets `next_step_needed` to false and must give a `conclusion`.
<!-- Verified from: src/plain_text_memory_mcp/server.py [RecallRecord, recall] -->

Sessions last only while the server runs. A session id from before a restart
starts a new session, with a warning saying so. A source that does not match
any note also returns a warning. Struck-through facts are never returned.
<!-- Verified from: src/plain_text_memory_mcp/server.py [recall] -->

Side effects: entities named in `open` are added to the access log, and each
step is added to the recall log when `MEMORY_RECALL_LOG=1`.
<!-- Verified from: src/plain_text_memory_mcp/server.py [recall, log_accesses, log_recall] -->

### `search_nodes`

Title: "Search memory". `search_nodes` runs one ranked search and returns
`hits`, the matching notes, plus the matching `entities` and every relation
that touches them, whose other end may be outside the results.

| Parameter | Required | What to pass |
| --- | --- | --- |
| `query` | Yes | The words to find in entity names and notes. |
| `limit` | No | Whole number, 1 or more: the most entities and most hits to return. Omit for all. |
| `since` | No | ISO date or timestamp: only entries stamped at or after this time. |
| `before` | No | ISO date or timestamp: only entries stamped before this time. |
| `agent` | No | Agent name, such as `claude-code`: only entries that agent stamped. |
| `expand` | No | `true` spreads scores along relations, so linked entities can join the results. Default `false`. |
| `include_superseded` | No | `true` also returns struck-through facts. Default `false`. |
<!-- Verified from: src/plain_text_memory_mcp/server.py [search_nodes, SinceParam, BeforeParam, AgentParam, LimitParam, IncludeSupersededParam] -->

Query syntax:

- Words match whole, ignoring case.
- Plain plurals match their singular: `tests` finds `test`. Words ending in
  `ss`, such as `class`, are left alone.
- Underscores split words: `reading_list` is two words.
- A `"quoted phrase"` matches only as a whole.
- Rare words count more than common ones.
- A query with no words returns every entity and no hits.
<!-- Verified from: src/plain_text_memory_mcp/search/bm25.py [to_tokens, _stem, _QUERY_TERM]; src/plain_text_memory_mcp/server.py [search_nodes] -->

Reading the results:

- Each hit has a `rank`; 1 is the strongest.
- Both lists put the strongest results at the start and the end, and the
  weakest in the middle, so read by `rank`, not by position.
- Recently stamped and often-opened entities rank a little higher.
<!-- Verified from: src/plain_text_memory_mcp/search/ranking.py; src/plain_text_memory_mcp/server.py [search_nodes] -->

Side effects: the search is added to the recall log when
`MEMORY_RECALL_LOG=1`.
<!-- Verified from: src/plain_text_memory_mcp/server.py [search_nodes, log_recall] -->

### `open_nodes`

Title: "Open entities". `open_nodes` returns the named entities in full,
with every relation that touches them.

| Parameter | Required | What to pass |
| --- | --- | --- |
| `names` | Yes | Exact names of the entities to open. |
| `include_superseded` | No | `true` also returns struck-through facts. Default `false`. |
<!-- Verified from: src/plain_text_memory_mcp/server.py [open_nodes] -->

Names must match exactly; names that do not exist are ignored. Side effects:
each open is added to the access log, so often-opened entities rank higher
in later searches, and to the recall log when `MEMORY_RECALL_LOG=1`.
<!-- Verified from: src/plain_text_memory_mcp/server.py [open_nodes] -->

### `stamp_notes`

Title: "Stamp notes". After any edit to a `MEMORY.ptm.md` file, the agent
calls `stamp_notes` with the paths of the files it changed.

| Parameter | Required | What to pass |
| --- | --- | --- |
| `paths` | Yes | One or more `MEMORY.ptm.md` files, relative to the repo root, such as `src/search/MEMORY.ptm.md`. |
<!-- Verified from: src/plain_text_memory_mcp/server.py [stamp_notes, _resolve_memory_file] -->

What it changes, in the named files only:

- Adds a stamp to each line with no stamp, or whose text changed since it
  was stamped. See [Stamps](#stamps).
- Adds the retirement time to each newly struck line.
- Moves struck lines retired 90 days or more ago to `MEMORY.ptm.archive.md`
  in the same folder.
<!-- Verified from: src/plain_text_memory_mcp/server.py [stamp_notes, stamp_file]; src/plain_text_memory_mcp/ptm/stamping.py [ARCHIVE_AFTER] -->

It returns `files`, with how many lines each file had `stamped`, `retired`,
and `archived`, and `warnings`. See
[Review Stamping Warnings](#review-stamping-warnings). Only one agent stamps
at a time; a call that waits more than 10 seconds for another fails and can
be retried.
<!-- Verified from: src/plain_text_memory_mcp/server.py [StampResult, StampedFileRecord, stamp_notes]; src/plain_text_memory_mcp/storage.py [lock_memory] -->

### `memory://taxonomy` Resource

Title: "Memory taxonomy". A read-only JSON resource with the server's
versioned schema: record types and their fields, tools with their parameters
and results, allowed values, resources, prompts, and a changelog. Ask your
agent to read it for the full detail of any tool.
<!-- Verified from: src/plain_text_memory_mcp/server.py [read_taxonomy] -->

## Everyday Tasks

Prerequisite for every task: the server is connected to your agent. See
[Connecting Clients](#connecting-clients).

### Recall Memory Before a Task

Ask, for example: "check memory about the search module before you start".
The agent's instructions tell it to do this on its own before planning.

The agent calls `recall` one or more times. In the first step it states what
it is looking for, searches two or three topic words, and names the task's
folder in `path`. It steps again while hits name entities it has not opened,
then ends with a conclusion citing the facts it relies on.
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS, recall] -->

You see the agent's plan draw on what memory holds. The agent is told to
verify any file, command, or setting memory names against the repo first:
the repo wins over memory, and you win over both.
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS] -->

### Save a Fact to Memory

Ask, for example: "remember that the tests use temporary paths because
settings.json points at the live file".
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS] -->

The agent's instructions tell it to:

1. Search memory first, with `search_nodes` or `recall`.
1. Show you the exact lines and wait for your yes before it adds, rewords,
   strikes, or deletes a fact.
1. Edit the `MEMORY.ptm.md` in the narrowest folder the fact covers,
   creating it if needed. Facts about the whole repo go in the repo root.
1. Call `stamp_notes` on the edited file.
1. Tell you every warning, and in one line what it saved.
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS] -->

The instructions also tell it to save what the code cannot show: decisions
and their reasons, options tried and dropped, limits found the hard way, and
your preferences, each with its reason on the same line. It skips what
reading the code shows, what will be untrue next week, and secrets.
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS] -->

To write a fact yourself:

1. Open `MEMORY.ptm.md` in the right folder, or create it. The name must
   match exactly, including case.
1. Under a `## <entity>` heading, add one bullet, a line starting with `-`,
   with the fact as a plain sentence on one line.
1. Save the file, then stamp it (see [Stamp Your Edits](#stamp-your-edits)).
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS]; dev-docs/specs/PTM_FILE_SPEC.md [Discovery, Format] -->

The full file format is in
[The MEMORY.ptm.md Format](#the-memoryptmmd-format).

### Link Two Entities

Ask, for example: "note in memory that bm25.py uses ranking.py". The agent
adds a relation: a bullet whose whole text is a short verb phrase, up to
three words, followed by one `[[link]]`:

```markdown
## bm25.py
- uses [[ranking.py]]
- is tested by [[test_bm25.py]]
```

- Write it in active voice, from the entity it sits under.
- A link inside a longer sentence is only a mention, not a relation.
- The link resolves by entity name across all memory files. If no file has
  an entity by that name, stamping returns a `broken_link` warning.
<!-- Verified from: src/plain_text_memory_mcp/ptm/parser.py [MAX_VERB_WORDS, _parse_relation]; src/plain_text_memory_mcp/server.py [_look_broken_links] -->

### Stamp Your Edits

If you edited a memory file by hand, ask your agent to stamp it:

1. Ask: "stamp `src/search/MEMORY.ptm.md`".
1. The agent calls `stamp_notes` with `paths` set to that file, relative to
   the repo root.
1. The server adds a stamp to each new or reworded line, and saves the file.
<!-- Verified from: src/plain_text_memory_mcp/server.py [stamp_notes] -->

Only the files you name change, so a line is never credited to an agent that
did not stamp it. Stamping credits every unstamped line to the agent that
calls `stamp_notes`, including lines you typed yourself. Lines nobody has
stamped are still searched; their `added_at` and `agent` are null.
<!-- Verified from: src/plain_text_memory_mcp/server.py [stamp_notes]; src/plain_text_memory_mcp/ptm/index.py [_to_tag] -->

### Review Stamping Warnings

After stamping, the agent tells you each warning `stamp_notes` returned.
Each warning names the entity, the text, the file, and what to do. The stamp
is still written; warnings only ask for a second look.

| Warning | What it means | What to do |
| --- | --- | --- |
| `near_duplicate` | The line closely resembles a fact already saved. | If it replaces that fact, strike the old line through; if it repeats it, delete one. |
| `instruction_like` | The line reads as an instruction to an agent, such as "ignore previous instructions". | Rewrite it as a fact, or delete it. |
| `secret` | The line looks like it holds a secret, such as a private key, an API key or token, or a `password=` assignment. The warning names the kind, never the value. | If it is a real secret, delete the line. |
| `no_reason` | The line states a fact with no word such as "because", "so", or "to avoid" that gives its reason. Relations are not checked. | If it records a decision or a limit, add why on the same line; if reading the code shows it, consider dropping it. |
| `broken_link` | A relation links to an entity no memory file names. | Add a `## name` heading where it belongs, or fix the link. |
| `long_file` | The file is longer than 200 lines. The warning names the file's folder entity, with empty text. | Move facts that cover only one subfolder into a `MEMORY.ptm.md` there, or drop facts you no longer need. |
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS, WriteWarning, _screen, _look_no_reason, _look_broken_links, _look_long_file]; src/plain_text_memory_mcp/ptm/parser.py [MAX_FILE_LINES]; src/plain_text_memory_mcp/screening/hazards.py; src/plain_text_memory_mcp/screening/reasons.py -->

### Replace or Retire a Fact

Ask, for example: "ranking now uses BM25, not TF-IDF; update memory". Agents
are told not to delete a fact that stops being true but to strike it through
with `~~`, so its history stays in the file.

To replace a fact:

1. Add the new fact as a bullet, saying why the old one was dropped.
1. Move the old line under it, indented, and wrap its text in `~~`.
1. Stamp the file.

```markdown
- Ranking uses BM25 over TF-IDF, because TF-IDF ranked long notes too high. <!-- 2026-10-09T14:05-04:00 codex #c3d4e -->
  - ~~Ranking uses TF-IDF.~~ <!-- 2026-10-01T09:15-04:00 codex #a1b2e retired 2026-10-09T14:05-04:00 -->
```

To retire a fact with no replacement, strike it through where it is, at the
top level.

- The struck line keeps its original stamp; stamping adds `retired <time>`.
- If a fact is still true but badly worded, fix the wording in place
  instead; it is stamped again.
- Search and recall hide struck facts unless asked for them. See
  [See Retired Facts](#see-retired-facts).
- Struck lines retired 90 days or more ago move to `MEMORY.ptm.archive.md`
  in the same folder the next time that file is stamped.
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS, stamp_notes]; src/plain_text_memory_mcp/ptm/stamping.py [ARCHIVE_AFTER]; dev-docs/specs/PTM_FILE_SPEC.md [Retiring facts, Archive] -->

### Look Up a Fact

Ask, for example: "what does memory say about the bm25 tokenizer?" The agent
calls `search_nodes` with a few words from your question and shows you the
matching facts, each with the file it came from. For more than one search in
a row, it uses `recall` instead.
<!-- Verified from: src/plain_text_memory_mcp/server.py [search_nodes] -->

### Filter Memory by Date or Agent

Ask, for example: "what did Codex save since October 1?" The agent calls
`search_nodes` with `agent` set to `codex` and `since` set to `2026-10-01`.

- Dates are ISO, such as `2026-10-01`, or timestamps, such as
  `2026-10-01T09:00:00-04:00`. A value with no offset is local time.
- Any of these filters leaves out unstamped entries, including all
  `AGENTS.md` text.
<!-- Verified from: src/plain_text_memory_mcp/server.py [_parse_moment, search_nodes] -->

### Read an Entity in Full

Ask, for example: "show me everything memory has on bm25.py". The agent
calls `open_nodes` with that exact name and shows every fact on the entity
and every relation that touches it.
<!-- Verified from: src/plain_text_memory_mcp/server.py [open_nodes] -->

### See Retired Facts

Ask, for example: "show retired facts about ranking too". The agent sets
`include_superseded` to `true` on `search_nodes` or `open_nodes`. Struck
facts then come back with `superseded_at` and, if they were replaced,
`replaced_by`.

Facts already moved to `MEMORY.ptm.archive.md` are not searched. Open the
archive file to read them.
<!-- Verified from: src/plain_text_memory_mcp/server.py [IncludeSupersededParam, build_memory]; src/plain_text_memory_mcp/ptm/index.py [build_index] -->

## Settings

The server reads two environment variables when it starts and takes no
command-line options. Set the variables in the client's server
configuration; they take effect the next time the client starts the server.
<!-- Verified from: src/plain_text_memory_mcp/server.py [main] -->

| Setting | Default | Accepted values | Where to set it |
| --- | --- | --- | --- |
| `MEMORY_AGENT` | Not set: the agent name comes from the MCP client | Any non-blank name. It replaces the agent name in every stamp that server writes. | The server's environment in the client configuration. |
| `MEMORY_RECALL_LOG` | Off | `1` turns it on; any other value leaves it off. When on, every `recall` step, `search_nodes` call, and `open_nodes` call is logged. | The server's environment in the client configuration. |
| Which files are memory | Every `MEMORY.ptm.md` and `AGENTS.md` git does not ignore | `.gitignore` patterns | `.gitignore`. Takes effect on the next tool call. |
| Repo root | Nearest folder with `.git` at or above the working directory | A folder | The folder the client starts the server in. See [How the Server Finds Your Repo](#how-the-server-finds-your-repo). |
<!-- Verified from: src/plain_text_memory_mcp/server.py [main]; src/plain_text_memory_mcp/agent.py [calc_agent_name]; src/plain_text_memory_mcp/storage.py [is_recall_log_on, look_repo_root]; src/plain_text_memory_mcp/ptm/index.py [look_memory_files] -->

Where each client takes environment variables:

| Client | Where to set them |
| --- | --- |
| Claude Code | An `env` object in the server's entry, or `--env MEMORY_AGENT=name` on `claude mcp add`. |
| Codex | A `[mcp_servers.plain-text-memory.env]` table, such as `MEMORY_AGENT = "name"`. |
| Cursor | An `env` object in the server's entry. |
| VS Code | An `env` object in the server's entry. |
<!-- Verified from: https://code.claude.com/docs/en/mcp; https://learn.chatgpt.com/docs/extend/mcp?surface=cli; https://cursor.com/docs/context/mcp; https://code.visualstudio.com/docs/copilot/reference/mcp-configuration -->

For example, in Codex:

```toml
[mcp_servers.plain-text-memory]
command = "uvx"
args = ["plain-text-memory-mcp"]

[mcp_servers.plain-text-memory.env]
MEMORY_AGENT = "my-agent"
```
<!-- Verified from: https://learn.chatgpt.com/docs/extend/mcp?surface=cli -->

How the agent name is chosen when `MEMORY_AGENT` is not set:

| MCP client name | Name in stamps |
| --- | --- |
| Contains `claude`, ignoring case | `claude-code` |
| Contains `codex`, ignoring case | `codex` |
| Any other name | The name as sent |
| Missing or blank | `unknown` |
<!-- Verified from: src/plain_text_memory_mcp/agent.py [KNOWN_AGENTS, calc_agent_name] -->

## Your Data Files

The server reads and writes only files inside the repo.

| File | Where | Purpose | Edit by hand? |
| --- | --- | --- | --- |
| `MEMORY.ptm.md` | Any folder in the repo | Facts about that folder and every folder below it. | Yes. Do not write stamps; stamp after editing. |
| `MEMORY.ptm.archive.md` | Beside a `MEMORY.ptm.md` | Struck facts retired 90 days or more ago. Not searched. | Yes, but it is a record; usually leave it. |
| `AGENTS.md` | Any folder in the repo | Agent instructions, read as unstamped notes. | Yes. The server never changes it. |
| `.agents/ptm/stamp.lock` | Repo root | Lets one agent stamp at a time, so two agents can share a repo. | No. A leftover file is harmless. |
| `.agents/ptm/access.jsonl` | Repo root | Logs each opened entity, to rank often-opened ones higher. | No. Deleting it only resets that ranking. |
| `.agents/ptm/recall.jsonl` | Repo root | Logs searches, opens, and recall steps when `MEMORY_RECALL_LOG=1`. | No. Never read back by the server. |
<!-- Verified from: src/plain_text_memory_mcp/storage.py [calc_state_path, lock_memory, calc_access_path, read_accesses, calc_recall_path]; src/plain_text_memory_mcp/ptm/parser.py [FILE_NAME, ARCHIVE_FILE_NAME]; src/plain_text_memory_mcp/ptm/index.py -->

### What Belongs in Git

Keep the memory, archive, and `AGENTS.md` files in git. Keep the local files
out with this `.gitignore` line:

```text
.agents/ptm/
```
<!-- Verified from: src/plain_text_memory_mcp/storage.py [module docstring] -->

### How Memory Files Are Found

- In a git repo, the server lists tracked files and untracked files that are
  not ignored, so `.gitignore` decides what is skipped.
- Outside git, or if git cannot be run, it walks the repo folder and skips
  dot folders, `node_modules`, and `__pycache__`.
- File names match case-sensitively, even on Windows.
- Changed files are re-read on the next tool call; no restart is needed.
- The server reads and writes memory files as UTF-8.
<!-- Verified from: src/plain_text_memory_mcp/ptm/index.py [look_memory_files, _list_git_files, _walk_files, read_memory_file]; src/plain_text_memory_mcp/server.py [_read_text, _write_text] -->

### The MEMORY.ptm.md Format

```markdown
# search

Ranks notes with BM25 plus spreading activation.

## bm25.py
- Tokenizes with a lowercase word regex and does no stemming.
- uses [[ranking.py]]
```

| Line | Meaning |
| --- | --- |
| `# name` | Names the folder entity. Optional; without it, the folder's name is used, or the repo folder's name at the root. Only the first one counts. |
| Text under `#` | A summary of the folder, indexed as an unstamped note on the folder entity. |
| `## name` | Starts an entity. Bullets after it belong to it until the next `##`. |
| `- text` | One fact. Keep it on one line: a wrapped second line is not part of the fact. |
| `- verb [[name]]` | A relation from the current entity to `name`. See [Link Two Entities](#link-two-entities). |
| `###` and deeper headings, code blocks, tables | Kept in the file but not indexed. |
<!-- Verified from: src/plain_text_memory_mcp/ptm/parser.py [parse_file]; src/plain_text_memory_mcp/ptm/index.py [calc_default_name, build_graph] -->

Rules:

- An entity named in more than one file is one entity; each note keeps the
  path of its own file.
- Do not write dates, agent names, labels such as "Convention:", or
  `<!-- -->` stamps. The server adds stamps.
- Leave `AGENTS.md` to people; the server reads it but never changes it.
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS]; src/plain_text_memory_mcp/ptm/index.py [build_graph] -->

### Stamps

A stamped line looks like this:

```markdown
- Tokenizes with a lowercase word regex. <!-- 2026-10-09T14:02-04:00 claude-code #9f2ce -->
```

| Stamp part | What it holds |
| --- | --- |
| Time | Local time to the minute, with UTC offset. |
| Agent | `claude-code`, `codex`, the client's own name, or `unknown`. Set `MEMORY_AGENT` to override it. |
| `#hash` | First 5 hex digits of a hash of the text; 5 digits is never a color code, so editors draw no color swatch beside it. Older 4-digit stamps still match and are lengthened the next time their file is stamped. A reworded line no longer matches, so it is stamped again. |
| `retired <time>` | On a struck line only: when it was struck. |
<!-- Verified from: src/plain_text_memory_mcp/server.py [stamp_notes]; src/plain_text_memory_mcp/agent.py [calc_agent_name]; src/plain_text_memory_mcp/ptm/stamps.py [HASH_LENGTH, OLD_HASH_LENGTH]; dev-docs/specs/PTM_FILE_SPEC.md [Stamps] -->

### AGENTS.md as a Memory Source

Every `AGENTS.md` file in the repo is searched along with the memory files.
It follows no special format:

- Each `##` or deeper heading becomes an entity named after its text. Text
  before the first such heading, including under the `#` title, belongs to
  the folder entity.
- Each bullet, with its wrapped lines, and each paragraph is one note.
- Code blocks and tables are skipped.
- The server never stamps or changes `AGENTS.md`, so its notes always show
  null `added_at` and `agent`.
<!-- Verified from: src/plain_text_memory_mcp/ptm/parser.py [parse_agents_file]; src/plain_text_memory_mcp/ptm/index.py [read_memory_file] -->

## Troubleshooting

| Symptom | Likely Cause | Resolution |
| --- | --- | --- |
| The client cannot start the server: `uvx` is not found. | uv is not installed, or not on the `PATH` the client sees. | Install [uv](https://docs.astral.sh/uv/) and make sure `uvx` is on `PATH`. |
| The client cannot start `plain-text-memory-mcp`. | The local copy is not installed, or uv's executable folder is not on `PATH`. | Run `uv tool install --editable path/to/plain_text_memory_mcp`, and make sure uv's executable folder is on `PATH`. |
| `uv tool install --editable --reinstall` fails on Windows. | A client is still running `plain-text-memory-mcp.exe`. | Close every client that uses the server, then run the reinstall again. |
| A new release on PyPI is not picked up. | `uvx` reuses its cached copy. | Run `uvx plain-text-memory-mcp@latest`, or use `plain-text-memory-mcp@latest` in the client's `args`. |
| `uvx plain-text-memory-mcp` runs your local copy, not the published package. | A local copy is installed with `uv tool install`. | Run `uvx --isolated plain-text-memory-mcp`. |
| Claude Code does not use the server from `.mcp.json`. | The server is waiting for your approval. | Start an interactive Claude Code session in the project and approve it. Check with `claude mcp list`. |
| Codex ignores the project's `.codex/config.toml`. | Codex reads project configuration only in trusted projects. | Make the project a trusted project, or add the server to `~/.codex/config.toml`. |
| The server does not appear in Cursor's chat. | The server is turned off. | Turn it on under **Customize** in the sidebar, and check **MCP Logs** in the Output panel. |
| VS Code still runs the old configuration. | The server was not restarted. | Run **MCP: List Servers**, select the server, and choose **Restart Server**. |
| Search shows memory from the wrong repo, or none. | The server started outside the repo. | Make sure the client starts the server in a folder inside the repo. In Codex or VS Code, set `cwd` to a folder inside the repo. |
| A fact you wrote never turns up in search. | The file is ignored by `.gitignore`, its name differs in case (such as `Memory.ptm.md`), or it is under a `###` heading or in a code block. | Name it exactly `MEMORY.ptm.md`, make sure git does not ignore it, and put facts under `##` headings. |
| Only the first part of a fact is found. | The fact wraps onto a second line, which is not part of the bullet. | Keep each fact on one line. |
| A relation shows up as a plain note. | The verb is longer than three words, or the bullet has text besides the verb and the link. | Shorten it to `- verb [[name]]`. |
| `added_at` and `agent` are null. | The line has not been stamped, or it comes from `AGENTS.md`. | Ask your agent to call `stamp_notes` on the file. `AGENTS.md` is never stamped. |
| Stamps say `unknown` or the wrong agent. | The MCP client sent no name, or a name the server does not map. | Set `MEMORY_AGENT` in the server's environment. |
| "… is not a memory file." | `stamp_notes` got a path that is not a `MEMORY.ptm.md` inside the repo. | Give paths relative to the repo root, such as `src/search/MEMORY.ptm.md`. |
| "… does not exist." | The file named in `stamp_notes` was not found. | Check the path and create the file first. |
| "… another process held the lock for over 10 s … retry the call." | Another agent was stamping memory at the same time. | Retry the call. |
| An error naming a file, ending "Close any program that has the file open …" | The file could not be read or written. | Close any program holding the file, check that it is writable, then retry. |
| "since … is not a date." | A filter time is not ISO format. | Use a date such as `2026-10-01` or a timestamp such as `2026-10-01T09:00:00-04:00`. |
| "The last step needs a conclusion …" | A `recall` step ended the session without a conclusion. | Give `conclusion`, or set `next_step_needed` to true. |
| "Step N is not in this recall's session …" | `revises_step` names a step this session never took. | Name an earlier step of the same session. |
| `recall` warns "Session … is unknown, perhaps from before a server restart". | Sessions are lost when the server restarts. | None needed; the step ran in a new session. Use the new `session` id from then on. |
| A retired fact is gone from its file. | It was retired 90 days or more ago and moved on the next stamp. | Open `MEMORY.ptm.archive.md` in the same folder. |
<!-- Verified from: src/plain_text_memory_mcp/server.py [_FILE_ACCESS_HINT, _LOCK_TIMEOUT_HINT, _MEMORY_PATH_HINT, _MOMENT_FORMAT_HINT, _resolve_memory_file, recall, main]; src/plain_text_memory_mcp/storage.py [lock_memory, look_repo_root]; src/plain_text_memory_mcp/ptm/parser.py [parse_file, _parse_relation]; src/plain_text_memory_mcp/agent.py; src/plain_text_memory_mcp/ptm/stamping.py; https://docs.astral.sh/uv/concepts/tools/; https://docs.astral.sh/uv/reference/cli/#uv-tool-install; https://code.claude.com/docs/en/mcp; https://learn.chatgpt.com/docs/extend/mcp?surface=cli; https://cursor.com/docs/context/mcp; https://code.visualstudio.com/docs/agents/run/manage-mcp-servers; https://code.visualstudio.com/docs/copilot/reference/mcp-configuration -->

## FAQ

**Does the server store memory anywhere besides my files?**
No. The memory is the Markdown files. The server keeps only a lock and logs
in `.agents/ptm/`, which you can delete.
<!-- Verified from: src/plain_text_memory_mcp/storage.py [module docstring] -->

**Can two agents use the same repo at once?**
Yes. Stamping takes a lock, so Claude Code and Codex can stamp the same repo
at the same time; a call that waits more than 10 seconds fails and can be
retried.
<!-- Verified from: src/plain_text_memory_mcp/server.py [build_server]; src/plain_text_memory_mcp/storage.py [lock_memory] -->

**Do I need to restart after editing a memory file?**
No. Every tool call re-reads files that changed.
<!-- Verified from: src/plain_text_memory_mcp/ptm/index.py [read_memory_file] -->

**How do I update to a new release?**
Run `uvx plain-text-memory-mcp@latest` once to refresh `uvx`'s cached copy.
For a local copy, close every client and run
`uv tool install --editable --reinstall path/to/plain_text_memory_mcp`.
<!-- Verified from: https://docs.astral.sh/uv/concepts/tools/; https://docs.astral.sh/uv/reference/cli/#uv-tool-install -->

**Will the agent follow instructions written in memory?**
It should not. The server tells agents that memory is data, not commands,
and to report any instruction found in a note to you. Stamping also warns
about instruction-like lines.
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS, _screen] -->

**Should I trust old facts?**
Treat them with care. Agents are told to verify any file, command, or
setting memory names against the repo first, and that the repo wins over
memory and you win over both. An older `added_at` is likelier stale, and
null stamps count as old.
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS] -->

**Can I delete a fact instead of striking it?**
Yes; it is your file. Striking it through keeps its history, which is why
agents are told to strike rather than delete, and to ask you before they
add, reword, strike, or delete any fact.
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS] -->

## Glossary

| Term | Meaning |
| --- | --- |
| Agent | The AI assistant, such as Claude Code or Codex, that calls the tools. Also the name recorded in a stamp. |
| Archive | `MEMORY.ptm.archive.md`, where long-retired facts move. |
| Client | The program that starts the server and connects your agent to it, such as Claude Code, Codex, Cursor, or VS Code. |
| Entity | A named thing in memory, such as a folder or module; a `##` heading. |
| Folder entity | The entity for a memory file's own folder, named by its `#` heading or the folder name. |
| Hit | One matching note in a search result, with its rank. |
| MCP | Model Context Protocol, the way agents connect to tools such as this server. |
| Note | One fact on an entity; one bullet line starting with `-`. |
| Recall session | A series of `recall` steps sharing one `session` id; later steps skip hits already returned. |
| Relation | A link from one entity to another, written `- verb [[name]]`. |
| Repo root | The nearest folder with `.git` at or above where the server started. |
| Resource | Read-only data a server offers to agents, such as `memory://taxonomy`. |
| Retired fact | A fact struck through with `~~`; superseded if nested under its replacement. |
| Scope | The folder a memory file covers: its own and every folder below it. |
| Server | A program that offers tools to agents over MCP; here, `plain-text-memory-mcp`. |
| Stamp | The `<!-- time agent #hash -->` comment the server adds to a line. |
| stdio | Standard input and output, the channel a client uses to talk to this server. |
| Tool | An action a server offers that an agent can call, such as `search_nodes`. |
| `uvx` | uv's command that downloads and runs a Python tool, such as this server. |
<!-- Verified from: src/plain_text_memory_mcp/server.py [build_server, main]; src/plain_text_memory_mcp/storage.py [look_repo_root]; https://docs.astral.sh/uv/concepts/tools/ -->
