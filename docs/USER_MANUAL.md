---
last_updated: 2026-10-09
version: 3.1.0
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

The program has two interfaces:

- **MCP tools** that your agent calls: `recall`, `search_nodes`,
  `open_nodes`, and `stamp_notes`, plus one read-only resource,
  `memory://taxonomy`.
- **Memory files** that you or your agent edit with any text editor.
<!-- Verified from: src/plain_text_memory_mcp/server.py [build_server] -->

The program has no window or menus of its own. You use it by asking your
agent, and the agent calls the tools. This manual does not cover
installation or adding the server to an agent's configuration.

## Starting the Program

Your agent normally starts the server for you when a session begins and
stops it when the session ends. You can also start it by hand from the repo
folder.

From the project folder, with the project's interpreter:

```powershell
.venv/Scripts/python.exe -m plain_text_memory_mcp.server
```

With the installed command:

```powershell
plain-text-memory-mcp
```
<!-- Verified from: pyproject.toml [project.scripts]; src/plain_text_memory_mcp/server.py [main] -->

What to expect on startup:

1. The server looks for the repo root: the nearest folder at or above the
   folder it was started in that contains `.git`. Outside git, it uses the
   start folder itself.
1. It prints nothing and waits for an MCP client on standard input.
1. When an agent connects, the server sends it instructions on how to
   recall and record memory, so the agent needs no extra setup.
<!-- Verified from: src/plain_text_memory_mcp/server.py [main, INSTRUCTIONS]; src/plain_text_memory_mcp/storage.py [look_repo_root] -->

Because the repo is found from the start folder, the server must start
inside the repo whose memory you want.

To quit, end the agent session. If you started the server by hand in a
terminal, press Ctrl+C.

## Getting Around

You work with memory in two places.

| Where | What you do there |
| --- | --- |
| Your agent's chat | Ask the agent to remember, look up, or update facts. The agent calls the tools. |
| `MEMORY.ptm.md` files | Read or edit facts directly. Changes show up in the next search without a restart. |
<!-- Verified from: src/plain_text_memory_mcp/ptm/index.py [read_memory_file, build_index] -->

The tools fall into two groups:

- **Reading memory:** `recall` searches in steps before a task;
  `search_nodes` runs one ranked search; `open_nodes` fetches entities by
  exact name.
- **Recording memory:** the agent edits a `MEMORY.ptm.md` file, then calls
  `stamp_notes` so the server stamps the new lines and checks them.
<!-- Verified from: src/plain_text_memory_mcp/server.py [recall, search_nodes, open_nodes, stamp_notes] -->

Memory is organized as a graph:

- An **entity** is a named thing, such as a folder or a module.
- A **note** is one fact on an entity.
- A **relation** links one entity to another, such as `uses [[sqlite]]`.

Each note in a result carries `path`, the file it came from, so you know
which file to open to change it.
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS]; dev-docs/specs/PTM_FILE_SPEC.md [Tools] -->

For the full list of record types, tools, parameters, and results, ask
your agent to read the resource `memory://taxonomy`.
<!-- Verified from: src/plain_text_memory_mcp/server.py [read_taxonomy] -->

## Everyday Tasks

### Write a Fact to Memory

Prerequisite: the server is connected to your agent.

1. Pick the narrowest folder the fact is about. Facts about the whole repo
   go in the repo root.
1. Open `MEMORY.ptm.md` in that folder, or create it. The name must match
   exactly, including case.
1. Under a `## <entity>` heading, add one bullet, a line starting with
   `-`, with the fact as a plain sentence on one line.
1. Save the file, then stamp it (see
   [Stamp Your Edits](#stamp-your-edits)).
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS]; dev-docs/specs/PTM_FILE_SPEC.md [Discovery, Format] -->

Usually you just ask your agent, for example "remember that the tests use
temporary paths because settings.json points at the live file". The
agent's instructions tell it to search first, show you the exact lines
and wait for your yes before it adds, rewords, strikes, or deletes a fact,
then edit the right file, stamp it, and tell you in one line what it
saved. They also tell it to save what
the code cannot show: decisions and their reasons, options tried and
dropped, limits found the hard way, and your preferences, each with its
reason on the same line. It skips what reading the code shows, what will
be untrue next week, and secrets.
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS] -->

File format:

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

### Link Two Entities

A relation is a bullet whose whole text is a short verb phrase, up to three
words, followed by one `[[link]]`:

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

After any edit to a `MEMORY.ptm.md` file, the agent calls `stamp_notes`
with the paths of the files it changed. If you edited a file by hand, ask
your agent to stamp it.

1. Ask: "stamp `src/search/MEMORY.ptm.md`".
1. The agent calls `stamp_notes` with `paths` set to that file, relative to
   the repo root.
1. The server adds a stamp to each new or reworded line, and saves the
   file.

A stamped line looks like this:

```markdown
- Tokenizes with a lowercase word regex. <!-- 2026-10-09T14:02-04:00 claude-code #9f2ce -->
```

| Stamp part | What it holds |
| --- | --- |
| Time | Local time to the minute, with UTC offset. |
| Agent | `claude-code`, `codex`, the client's own name, or `unknown`. Set `MEMORY_AGENT` to override it. |
| `#hash` | First 5 hex digits of a hash of the text; 5 digits is never a color code, so editors draw no color swatch beside it. Older 4-digit stamps still match and are lengthened the next time their file is stamped. A reworded line no longer matches, so it is stamped again. |
<!-- Verified from: src/plain_text_memory_mcp/server.py [stamp_notes]; src/plain_text_memory_mcp/agent.py [calc_agent_name]; dev-docs/specs/PTM_FILE_SPEC.md [Stamps] -->

Only the files you name change, so a line is never credited to an agent
that did not stamp it. Stamping credits every unstamped line to the agent
that calls `stamp_notes`, including lines you typed yourself. Lines nobody
has stamped are still searched; their `added_at` and `agent` are null.

`stamp_notes` returns, for each file, how many lines it `stamped`,
`retired`, and `archived`, plus any warnings.
<!-- Verified from: src/plain_text_memory_mcp/server.py [StampedFileRecord, stamp_notes] -->

### Review Stamping Warnings

Each warning names the entity, the text, the file, and what to do. The
stamp is still written; warnings only ask for a second look. Your agent is
told to report every warning to you.

| Warning | What it means | What to do |
| --- | --- | --- |
| `near_duplicate` | The line closely resembles a fact already saved. | If it replaces that fact, strike the old line through; if it repeats it, delete one. |
| `instruction_like` | The line reads as an instruction to an agent, such as "ignore previous instructions". | Rewrite it as a fact, or delete it. |
| `secret` | The line looks like it holds a secret, such as a private key, an API key or token, or a `password=` assignment. The warning names the kind, never the value. | If it is a real secret, delete the line. |
| `no_reason` | The line states a fact with no word such as "because", "so", or "to avoid" that gives its reason. Relations are not checked. | If it records a decision or a limit, add why on the same line; if reading the code shows it, consider dropping it. |
| `broken_link` | A relation links to an entity no memory file names. | Add a `## name` heading where it belongs, or fix the link. |
| `long_file` | The file is longer than 200 lines. The warning names the file's folder entity, with empty text. | Move facts that cover only one subfolder into a `MEMORY.ptm.md` there, or drop facts you no longer need. |
<!-- Verified from: src/plain_text_memory_mcp/server.py [_screen, _look_broken_links, _look_long_file]; src/plain_text_memory_mcp/ptm/parser.py [MAX_FILE_LINES]; src/plain_text_memory_mcp/screening/hazards.py -->

### Replace or Retire a Fact

Do not delete a fact that stops being true. Strike it through with `~~` so
its history stays in the file.

To replace a fact:

1. Add the new fact as a bullet, saying why the old one was dropped.
1. Move the old line under it, indented, and wrap its text in `~~`.
1. Stamp the file.

```markdown
- Ranking uses BM25 over TF-IDF, because TF-IDF ranked long notes too high. <!-- 2026-10-09T14:05-04:00 codex #c3d4e -->
  - ~~Ranking uses TF-IDF.~~ <!-- 2026-10-01T09:15-04:00 codex #a1b2e retired 2026-10-09T14:05-04:00 -->
```

To retire a fact with no replacement, strike it through where it is, at
the top level.

- The struck line keeps its original stamp; stamping adds
  `retired <time>`.
- If a fact is still true but badly worded, fix the wording in place
  instead; it is stamped again.
- Search and recall hide struck facts unless asked for them. See
  [See Retired Facts](#see-retired-facts).
- Struck lines retired 90 days or more ago move to
  `MEMORY.ptm.archive.md` in the same folder the next time that file is
  stamped.
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS, stamp_notes]; src/plain_text_memory_mcp/ptm/stamping.py [ARCHIVE_AFTER]; dev-docs/specs/PTM_FILE_SPEC.md [Retiring facts, Archive] -->

### Recall Memory Before a Task

`recall` is how agents read memory before planning. It searches in
numbered steps and records why each search was made. The agent's
instructions tell it to call `recall` on its own; you can also ask, for
example "check memory about the search module before you start".

Each step:

1. States what it is looking for in `thought`.
1. Runs up to three searches in `queries`.
1. Can open entities by exact name in `open`.
1. Returns at most eight hits, never one an earlier step of the same
   session already returned. `seen` counts those skipped.
1. Returns small matching entities whole, so the facts around a hit come
   along. Larger entities and linked ones not yet opened are listed under
   `unopened`.

The last step sets `next_step_needed` to false and must give a
`conclusion`, with the notes it rests on in `sources`.
<!-- Verified from: src/plain_text_memory_mcp/server.py [recall]; src/plain_text_memory_mcp/search/recall.py [STEP_HIT_LIMIT, AUTO_OPEN_MAX_FACTS, UNOPENED_LIMIT] -->

| Field | What to enter |
| --- | --- |
| `thought` | Why this step is taken. |
| `step`, `total_steps` | This step's number from 1, and the estimated total. |
| `next_step_needed` | `true` if another step follows. |
| `queries` | Up to 3 searches, in the same syntax as `search_nodes`. |
| `open` | Exact entity names to return in full. |
| `path` | The folder or file the task is about. Notes from memory files in folders covering it rank 1.5 times higher; the root file covers everything, so it gets no boost. |
| `session` | The session id from the first step's result; leave it out on the first step. |
| `revises_step` | An earlier step of this session that this one corrects. |
| `conclusion`, `sources` | What memory showed, and the notes it rests on, each as `entityName` and exact `text`. |
<!-- Verified from: src/plain_text_memory_mcp/server.py [recall]; src/plain_text_memory_mcp/search/ranking.py [SCOPE_BOOST] -->

Sessions last only while the server runs. A session id from before a
restart starts a new session, with a warning saying so. A source that does
not match any note also returns a warning.
<!-- Verified from: src/plain_text_memory_mcp/server.py [recall] -->

### Search Memory Once

`search_nodes` runs one ranked search and returns `hits`, the matching
notes, plus the matching entities and every relation that touches them.

Query syntax:

- Words match whole, ignoring case.
- Plain plurals match their singular: `tests` finds `test`. Words ending in
  `ss`, such as `class`, are left alone.
- Underscores split words: `reading_list` is two words.
- A `"quoted phrase"` matches only as a whole.
- Rare words count more than common ones.
- A query with no words returns every entity and no hits.
<!-- Verified from: src/plain_text_memory_mcp/search/bm25.py [to_tokens, _stem, _QUERY_TERM]; src/plain_text_memory_mcp/server.py [search_nodes] -->

| Option | Accepted values | What it does |
| --- | --- | --- |
| `query` | Text | The words to find in entity names and notes. |
| `limit` | Whole number, 1 or more | Most entities and most hits to return. Omit for all. |
| `since` | ISO date or timestamp | Only entries stamped at or after this time. |
| `before` | ISO date or timestamp | Only entries stamped before this time. |
| `agent` | Agent name, such as `claude-code` | Only entries that agent stamped. |
| `expand` | `true` or `false` (default) | Spreads scores along relations, so linked entities can join the results. |
| `include_superseded` | `true` or `false` (default) | Also returns struck-through facts. |
<!-- Verified from: src/plain_text_memory_mcp/server.py [search_nodes, SinceParam, BeforeParam, AgentParam, LimitParam] -->

Reading the results:

- Each hit has a `rank`; 1 is the strongest.
- Both lists put the strongest results at the start and the end, and the
  weakest in the middle, so read by `rank`, not by position.
- Recently stamped and often-opened entities rank a little higher.
<!-- Verified from: src/plain_text_memory_mcp/search/ranking.py; src/plain_text_memory_mcp/server.py [search_nodes] -->

### Filter Memory by Date or Agent

Ask, for example, "what did Codex save since October 1?" The agent calls
`search_nodes` with `agent` set to `codex` and `since` set to `2026-10-01`.

- Dates are ISO, such as `2026-10-01`, or timestamps, such as
  `2026-10-01T09:00:00-04:00`. A value with no offset is local time.
- Any of these filters leaves out unstamped entries, including all
  `AGENTS.md` text.
<!-- Verified from: src/plain_text_memory_mcp/server.py [_parse_moment, search_nodes] -->

### Open Entities by Name

`open_nodes` returns the named entities in full, with every relation that
touches them. Names must match exactly; names that do not exist are
ignored. Set `include_superseded` to see struck facts too. Each open is
logged, and often-opened entities rank higher in later searches.
<!-- Verified from: src/plain_text_memory_mcp/server.py [open_nodes] -->

### See Retired Facts

Set `include_superseded` to `true` on `search_nodes` or `open_nodes`.
Struck facts then come back with `superseded_at` and, if they were
replaced, `replaced_by`.

Facts already moved to `MEMORY.ptm.archive.md` are not searched. Open the
archive file to read them.
<!-- Verified from: src/plain_text_memory_mcp/server.py [IncludeSupersededParam, build_memory]; src/plain_text_memory_mcp/ptm/index.py [build_index] -->

### Use AGENTS.md as Memory

Every `AGENTS.md` file in the repo is searched along with the memory
files. It follows no special format:

- Each `##` or deeper heading becomes an entity named after its text. Text
  before the first such heading, including under the `#` title, belongs to
  the folder entity.
- Each bullet, with its wrapped lines, and each paragraph is one note.
- Code blocks and tables are skipped.
- The server never stamps or changes `AGENTS.md`, so its notes always show
  null `added_at` and `agent`.
<!-- Verified from: src/plain_text_memory_mcp/ptm/parser.py [parse_agents_file]; src/plain_text_memory_mcp/ptm/index.py [read_memory_file] -->

## Settings and Preferences

Settings are environment variables set where the agent starts the server,
plus which files git ignores. They take effect the next time the server
starts and last as long as they stay set.

| Setting | Default | Accepted values | How to change it |
| --- | --- | --- | --- |
| `MEMORY_AGENT` | Not set: the agent name comes from the MCP client | Any non-blank name | Set it in the server's environment. It replaces the agent name in every stamp that server writes. |
| `MEMORY_RECALL_LOG` | Off | `1` turns it on; any other value leaves it off | Set it in the server's environment to log every `recall` step, `search_nodes` call, and `open_nodes` call. |
| Which files are memory | Every `MEMORY.ptm.md` and `AGENTS.md` git does not ignore | `.gitignore` patterns | Edit `.gitignore`. Takes effect on the next tool call. |
| Repo root | Nearest folder with `.git` at or above the start folder | A folder | Start the server from a folder inside the repo you want. |
<!-- Verified from: src/plain_text_memory_mcp/server.py [main]; src/plain_text_memory_mcp/agent.py [calc_agent_name]; src/plain_text_memory_mcp/storage.py [is_recall_log_on, look_repo_root]; src/plain_text_memory_mcp/ptm/index.py [look_memory_files] -->

How the agent name is chosen when `MEMORY_AGENT` is not set:

| MCP client name | Name in stamps |
| --- | --- |
| Contains `claude` | `claude-code` |
| Contains `codex` | `codex` |
| Any other name | The name as sent |
| Missing or blank | `unknown` |
<!-- Verified from: src/plain_text_memory_mcp/agent.py [KNOWN_AGENTS, calc_agent_name] -->

## Importing and Exporting

Not Applicable.
<!-- Verified from: src/plain_text_memory_mcp/server.py -->

## Commands and Shortcuts

The program has no keyboard shortcuts or menus. It has one terminal
command, and the MCP tools and resource your agent calls.

| Command or option | Accepted values | What it does |
| --- | --- | --- |
| `plain-text-memory-mcp` | None | Starts the server on standard input and output for the repo containing the current folder. |
| `.venv/Scripts/python.exe -m plain_text_memory_mcp.server` | None | Same, from the project folder. |
<!-- Verified from: pyproject.toml [project.scripts]; src/plain_text_memory_mcp/server.py [main] -->

| Tool or resource | Changes files | What it does |
| --- | --- | --- |
| `recall` | No | Searches memory in steps before a task. |
| `search_nodes` | No | Runs one ranked search. |
| `open_nodes` | No | Returns entities by exact name. |
| `stamp_notes` | Yes, only the files named | Stamps new and changed lines, archives old retired ones, and returns warnings. |
| `memory://taxonomy` | No | Returns the server's versioned schema: record types, tools, parameters, results, allowed values, and a changelog. |
<!-- Verified from: src/plain_text_memory_mcp/server.py [register_tool calls, read_taxonomy] -->

## Your Data Files

| File | Where | Purpose | Edit by hand? |
| --- | --- | --- | --- |
| `MEMORY.ptm.md` | Any folder in the repo | Facts about that folder and every folder below it. | Yes. Do not write stamps; stamp after editing. |
| `MEMORY.ptm.archive.md` | Beside a `MEMORY.ptm.md` | Struck facts retired 90 days or more ago. Not searched. | Yes, but it is a record; usually leave it. |
| `AGENTS.md` | Any folder in the repo | Agent instructions, read as unstamped notes. | Yes. The server never changes it. |
| `.agents/ptm/stamp.lock` | Repo root | Lets one agent stamp at a time, so two agents can share a repo. | No. A leftover file is harmless. |
| `.agents/ptm/access.jsonl` | Repo root | Logs each opened entity, to rank often-opened ones higher. | No. Deleting it only resets that ranking. |
| `.agents/ptm/recall.jsonl` | Repo root | Logs searches, opens, and recall steps when `MEMORY_RECALL_LOG=1`. | No. Never read back by the server. |
<!-- Verified from: src/plain_text_memory_mcp/storage.py [calc_state_path, lock_memory, calc_access_path, read_accesses, calc_recall_path]; src/plain_text_memory_mcp/ptm/parser.py [FILE_NAME, ARCHIVE_FILE_NAME]; src/plain_text_memory_mcp/ptm/index.py -->

Keep the memory and `AGENTS.md` files in git. Keep the local files out
with this `.gitignore` line:

```text
.agents/ptm/
```
<!-- Verified from: src/plain_text_memory_mcp/storage.py [module docstring] -->

How memory files are found:

- In a git repo, the server lists tracked files and untracked files that
  are not ignored, so `.gitignore` decides what is skipped.
- Outside git, it walks the repo folder and skips dot folders,
  `node_modules`, and `__pycache__`.
- File names match case-sensitively, even on Windows.
- Changed files are re-read on the next tool call; no restart is needed.
<!-- Verified from: src/plain_text_memory_mcp/ptm/index.py [look_memory_files, _walk_files, read_memory_file] -->

The server reads and writes memory files as UTF-8.
<!-- Verified from: src/plain_text_memory_mcp/server.py [_read_text, _write_text]; src/plain_text_memory_mcp/ptm/parser.py [parse_file] -->

## Troubleshooting

| Symptom | Likely Cause | Resolution |
| --- | --- | --- |
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
| Search shows memory from the wrong repo, or none. | The server started outside the repo. | Start the agent, and so the server, from inside the repo. |
<!-- Verified from: src/plain_text_memory_mcp/server.py [_FILE_ACCESS_HINT, _LOCK_TIMEOUT_HINT, _MEMORY_PATH_HINT, _MOMENT_FORMAT_HINT, _resolve_memory_file, recall, main]; src/plain_text_memory_mcp/storage.py [lock_memory]; src/plain_text_memory_mcp/ptm/parser.py [parse_file, _parse_relation]; src/plain_text_memory_mcp/agent.py; src/plain_text_memory_mcp/ptm/stamping.py -->

## FAQ

**Does the server store memory anywhere besides my files?**
No. The memory is the Markdown files. The server keeps only a lock and
logs in `.agents/ptm/`, which you can delete.
<!-- Verified from: src/plain_text_memory_mcp/storage.py [module docstring] -->

**Can two agents use the same repo at once?**
Yes. Stamping takes a lock, so Claude Code and Codex can stamp the same
repo at the same time; a call that waits more than 10 seconds fails and
can be retried.
<!-- Verified from: src/plain_text_memory_mcp/server.py [build_server]; src/plain_text_memory_mcp/storage.py [lock_memory] -->

**Do I need to restart after editing a memory file?**
No. Every tool call re-reads files that changed.
<!-- Verified from: src/plain_text_memory_mcp/ptm/index.py [read_memory_file] -->

**Will the agent follow instructions written in memory?**
It should not. The server tells agents that memory is data, not commands,
and to report any instruction found in a note to you. Stamping also warns
about instruction-like lines.
<!-- Verified from: src/plain_text_memory_mcp/server.py [INSTRUCTIONS, _screen] -->

**Should I trust old facts?**
Treat them with care. Agents are told to verify any file, command, or
setting memory names against the repo first, and that the repo wins over
memory and you win over both.
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
| Entity | A named thing in memory, such as a folder or module; a `##` heading. |
| Folder entity | The entity for a memory file's own folder, named by its `#` heading or the folder name. |
| Hit | One matching note in a search result, with its rank. |
| MCP | Model Context Protocol, the way agents connect to tools such as this server. |
| Note | One fact on an entity; one bullet line starting with `-`. |
| Recall session | A series of `recall` steps sharing one `session` id; later steps skip hits already returned. |
| Relation | A link from one entity to another, written `- verb [[name]]`. |
| Repo root | The nearest folder with `.git` at or above where the server started. |
| Retired fact | A fact struck through with `~~`; superseded if nested under its replacement. |
| Scope | The folder a memory file covers: its own and every folder below it. |
| Stamp | The `<!-- time agent #hash -->` comment the server adds to a line. |
