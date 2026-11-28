# Git sources are kept in `.owpp/` in the project

Before, each run fetched every `source:` again, so nothing worked offline. Each run wrote a whole plugin from git to a temporary folder, and then deleted it. Thus the deployed code was hard to read. Paths to it also went dead. owpp now keeps both in [`.owpp/`](../bundling.md#the-owpp-folder), as Node keeps `node_modules`. The pins in `plugin.yaml` are the lock file.

What this means:

- **Two layers.** `store/` holds upstream files by repository and commit, and never changes them. `modules/` holds each whole plugin with its local overrides. A build at another commit cannot change the pinned code.
- **No install step.** A command fetches what the store does not hold.
- **owpp checks what it reads.** It records a hash of each file that it writes, and refuses a changed file. The records catch an accidental change, not a person who can also change the records.
- **owpp refuses a tracked `.owpp/`.** A commit could add files and records together, and change the bundle without a change to a pin.
- **The folder ignores itself.** owpp writes a `.gitignore` inside it, so that no project commits it by accident.
- **The project's `.gitignore` stays the project's.** owpp suggests the line and does not write it.
- **CI can cache the store.** The GitHub Action does so only when asked. Other workflows of a repository can write that cache, and the records in it cannot show where its files came from.
- **A `Sources` without a plugins folder keeps nothing.** The test stand-ins and library callers write nothing in a project.

## Considered Options

- **A temporary folder for each run** (the state before): no stale files and no writes to the project, but the problems above.
- **A cache in `OWPP_CACHE_DIR`**: speed and offline builds, shared between projects, but the code stays hard to find.
- **A visible `owpp_modules/`**: easy to find, but pytest and search tools can read its third-party tests.
- **A bare git repository as the store**: git names each object by its hash. But owpp would run git in a folder where a project can put git settings.
