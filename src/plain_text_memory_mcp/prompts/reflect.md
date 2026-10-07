# Memory reflection

Review this repo's plain-text-memory graph and propose summary facts that
consolidate what the observations say together. A summary saves the next
agent from reading many facts to learn one thing. Work in two phases:
propose, then save only what I approve.

## Phase 1: propose

1. Read the graph with `read_graph`.
1. Find groups of three or more observations that support one higher-level
   fact, such as several notes about how tests run that together say how
   to test the repo. Groups may span entities.
1. Write one summary per group: a plain sentence, true by itself, that adds
   no claim the sources do not make. Check it against the repo when it
   names a file, command, or setting.
1. Pick the entity each summary belongs on: the repo folder name for
   repo-wide summaries, otherwise the entity the group is about.
1. Present one table and stop:

| # | Entity | Summary | Sources |
| --- | --- | --- | --- |
| 1 | reading_list | "Tests run with pytest through uv." | reading_list: "Uses pytest"; reading_list: "Run commands with uv run" |

## Phase 2: save

Save only the rows I approve, with `add_observations`, listing each source
observation in `sources` by entity name and exact text. The sources stay;
a summary cites them and replaces none of them. Then list what you saved
and any warnings the tool returned.

Go back to phase 1 instead of saving a summary I have not seen in the
table, or one whose sources do not all exist.
