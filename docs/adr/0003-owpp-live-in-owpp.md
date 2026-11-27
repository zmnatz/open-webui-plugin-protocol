# owpp live is one of owpp's commands, with a `live` extra

Tests on a real Open-WebUI need Docker, an Open-WebUI and aimock pinned together, signed-in accounts and Playwright. Before it, only this repository had them (`tools/screenshots/`, `tools/live/`), and a plugins repository was told to copy four files. They now ship in owpp as `owpp.live` (`src/owpp/live/`): the `owpp live` command, the stack's compose file and aimock fixtures, and the pytest fixtures. `owpp[live]` adds Playwright, for the browser fixtures.

What this means:

- **No second package.** `owpp live` runs Docker and pytest as subprocesses and talks to Open-WebUI over the standard library's `urllib`: none of it needs a dependency owpp does not already have. Only the browser fixtures import Playwright, inside the fixture, so owpp, its CLI and `owpp live` load without it, and tests over the API alone run with `uvx owpp live`. The compose file and the fixtures are a few dozen lines of data.
- **The fixtures are not in every pytest run.** `owpp.live.fixtures` is not a `pytest11` entry point: `owpp live` loads it with `PYTEST_PLUGINS=owpp.live.fixtures` (added to any the caller set), and `--up` prints that with the accounts. A repository's unit tests, run where owpp is installed, get no `api` or `user` fixture.
- **Released as owpp is.** A new Open-WebUI or aimock pin, or a change to how owpp deploys or signs in, ships in the next owpp release, with no second version to keep in step.
- **Live tests live with the repository**, in one folder (`live/` beside `plugins/`), not in each plugin's `tests/`. A live test is about Open-WebUI and the plugins together (a filter's effect on a chat with a tool in it, a grant), and one stack serves the whole run.
- **The repository's services are its own.** owpp's compose file has only Open-WebUI and aimock. A repository's `compose.yaml` is layered on it (`docker compose -f owpp's -f yours`), so it adds stand-ins and changes settings while owpp's version pins still apply. Its aimock fixtures replace owpp's, since a repository that writes fixtures names its own models.
- **Every user may use every model** on owpp's stack (`BYPASS_MODEL_ACCESS_CONTROL`), so a first test can chat as the user account. A repository that tests grants turns it off, as this one does.

## Considered Options

- **A second package, `owpp-live`, released with owpp at one version**, adding its command through an `owpp.commands` entry point: kept Playwright and the fixtures out of an owpp install, but Playwright is already imported only where used, and the fixtures need not be registered everywhere. It cost a uv workspace, an entry-point hook and a stub for when it is missing, lockstep version checks in the release tools, a second PyPI project, and a release that could publish one package and not the other.
- **The fixtures as a `pytest11` entry point**: no `PYTEST_PLUGINS`, but `api`, `user` and `admin` in every pytest run where owpp is installed, shadowing or shadowed by a repository's own.
- **Copying the files** (the state before): no packaging, but every repository keeps its own copy of the stack and the fixtures, and none of them move with owpp.
- **A repository's compose file replacing owpp's**: full control, but each repository copies Open-WebUI's and aimock's settings and keeps their pins up to date itself.
