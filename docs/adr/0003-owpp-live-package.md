# owpp live is a second package, released with owpp

Tests on a real Open-WebUI need Docker, an Open-WebUI and aimock pinned together, signed-in accounts and Playwright. Before it, only this repository had them (`tools/screenshots/`, `tools/live/`), and a plugins repository was told to copy four files. They now ship as **owpp-live** (`packages/owpp-live`, a uv workspace member here), which adds `owpp live` to owpp and gives pytest the live fixtures.

What this means:

- **A package of its own, not an extra.** Playwright, the compose file and the pytest plugin stay out of owpp, whose only dependency is PyYAML. owpp-live's pytest plugin loads only where owpp-live is installed, so the unit tests of a repository that never runs live tests do not get its fixtures, and do not need Playwright installed for an import to succeed.
- **Released together, at one version.** One `v*` tag publishes both, and owpp-live requires exactly that owpp (`owpp==<version>`). `tools/release.py` bumps both versions and the pin, and refuses to when they differ; `tools/release_notes.py`, which gates publishing, refuses a tag when they differ. Nobody has to ask which owpp-live goes with which owpp, and a change to how owpp deploys or signs in can change owpp live in the same pull request.
- **`owpp live`, through an entry point.** owpp reads `owpp.commands` entry points: each is a function that takes owpp's own `add(name, handler, help)`, so a command from another package gets `--dir` and `-- pytest args` as owpp's own do. Without owpp-live, `owpp live` is still listed, and says how to get it. A command that fails to load is reported, and the others still work.
- **Live tests live with the repository**, in one folder (`live/` beside `plugins/`), not in each plugin's `tests/`. A live test is about Open-WebUI and the plugins together (a filter's effect on a chat with a tool in it, a grant), and one stack serves the whole run.
- **The repository's services are its own.** owpp's compose file has only Open-WebUI and aimock. A repository's `compose.yaml` is layered on it (`docker compose -f owpp's -f yours`), so it adds stand-ins and changes settings while owpp's version pins still apply. Its aimock fixtures replace owpp's, since a repository that writes fixtures names its own models.
- **Every user may use every model** on owpp's stack (`BYPASS_MODEL_ACCESS_CONTROL`), so a first test can chat as the user account. A repository that tests grants turns it off, as this one does.

## Considered Options

- **An `owpp[live]` extra**: no second release, but the compose file and the pytest plugin would be in every install of owpp, the plugin's fixtures (`api`, `user`, `admin`) would be in every pytest run, and an import of Playwright would have to be guarded everywhere.
- **Its own release cadence** (`owpp-live-v*` tags): a new Open-WebUI pin without an owpp release, but a second release process, and a compatibility table between the two.
- **Copying the files** (the state before): no packaging, but every repository keeps its own copy of the stack and the fixtures, and none of them move with owpp.
- **A repository's compose file replacing owpp's**: full control, but each repository copies Open-WebUI's and aimock's settings and keeps their pins up to date itself.
