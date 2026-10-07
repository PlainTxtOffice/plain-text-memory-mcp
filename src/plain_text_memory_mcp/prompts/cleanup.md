# Memory cleanup

Review this repo's plain-text-memory graph and propose a cleanup. Deleting
memory cannot be undone, so work in two phases: propose, then apply only
what I approve. A request to clean up is a request for a proposal, not
permission to delete.

## Phase 1: propose

1. Read the graph with `read_graph`.
1. For each candidate, check the repo before judging it. When two
   observations contradict each other, the code decides which one is true,
   not the newer `added_at`. When the repo cannot settle it, mark the item
   "ask".
1. Present one table and stop:

| # | Entity | Item | Action | Evidence |
| --- | --- | --- | --- | --- |
| 1 | reading_list | "Tests run with unittest" | delete | `pyproject.toml` configures pytest |
| 2 | readinglist | whole entity | merge into reading_list | same repo, misspelled name |

Actions are `delete`, `merge into <entity>`, `rename to <name>`,
`rewrite`, `supersede`, `keep`, or `ask`. Use `supersede` for a fact that
was true once and has changed, so its history stays.
Entries marked "safe to delete" or starting with `TEST:` are ordinary
`delete` rows. They still wait for my approval.

## Phase 2: apply

Apply only the rows I approve, then list what changed. Use
`merge_entities` for a merge, which keeps every observation's original tags,
`rename_entity` for a misspelled name with no twin, `edit_observation`
for a rewrite, which keeps when and by whom the fact was first added, and
`supersede_observation` for a fact that changed, which keeps the old fact
hidden with a pointer to the new one. The delete tools return everything
they deleted.

Go back to phase 1 instead of deleting anything I have not seen in the
table, settling a contradiction by date alone, or treating "safe to delete"
or empty tags as approval.
