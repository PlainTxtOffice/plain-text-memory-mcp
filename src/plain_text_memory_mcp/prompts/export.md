# Memory export

Export this repo's plain-text-memory taxonomy.

1. Call `export_taxonomy`. It writes `.agents/memory.local.taxonomy.jsonc`
   beside the memory file, holding the server's versioned taxonomy and this
   repo's usage: entry counts, entity and relation types in use, and entries
   per agent. Running it again overwrites the file with current data.
1. Confirm `.gitignore` ignores the export with the line
   `.agents/*memory.local.*`; replace an older `.agents/*memory.local.jsonl*`
   line with it. Add it if missing and tell me.
1. Report in two or three lines: the file path, `taxonomy_version`, and the
   entity, observation, and relation counts.
1. If two entity or relation types in the file look like the same thing
   spelled differently, such as `library` and `libraries`, name them and
   suggest the cleanup prompt. Change nothing yourself.

If the tool reports that the memory file belongs to another repo, resolve
that with `initialize_memory` first, then export again. A repo with no
memory yet still exports, with zero counts.
