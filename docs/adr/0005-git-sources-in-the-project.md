# Git sources are kept in `.owpp/` in the project

Before, each run fetched every `source:` again. A whole plugin from git was written to a temporary folder, which was deleted with the run. Thus nothing worked offline, the deployed code was hard to read, and paths to it went dead. owpp now keeps both in [`.owpp/`](../bundling.md#the-owpp-folder), as Node keeps `node_modules`. The pins in `plugin.yaml` are the lock file.

What this means:

- **Two layers.** `store/` holds upstream files by repository and commit, and never changes them. `modules/` holds a whole plugin with the local overrides. A build at another commit cannot change the pinned code.
- **No install step.** A command fetches what the store does not hold.
- **owpp checks what it reads.** It records a hash of each file that it writes, and refuses a changed file. The records catch an accidental change, not a person who can also change the records.
- **A tracked `.owpp/` is refused.** A commit could add files and records together, and change the bundle without a change to a pin.
- **The project's `.gitignore` stays the project's.** owpp suggests the line and does not write it.
- **A `Sources` without a plugins folder keeps nothing.** The test stand-ins and library callers write nothing in a project.

## Considered Options

- **A temporary folder for each run** (the state before): no stale files and no writes to the project, but the problems above.
- **A cache in `OWPP_CACHE_DIR`**: speed and offline builds, shared between projects, but the code stays hard to find.
- **A visible `owpp_modules/`**: easy to find, but pytest and search tools can read its third-party tests.
- **A bare git repository as the store**: git names each object by its hash. But owpp would run git in a folder where a project can put git settings.
- **A `.gitignore` inside `.owpp/`**: the folder would be ignored with no work, but then the project's own files do not say so.
