# Reviewing a change

How a person checks a pull request or a release before it reaches an Open-WebUI instance. Everything a plugin does runs inside Open-WebUI with admin rights, so a change is not done until someone has read it and seen it work.

## 1. Know what changed and why

| Look at | It tells you |
| --- | --- |
| The pull request's description and commits | What the author meant to do. Each commit message says why. |
| The [audit trail](project/audit-trail.md) | Every commit so far, with the files it touched. It is built from `git log`. |
| The [changelog](project/changelog.md), `## Unreleased` | What users will notice. A change they would notice needs an entry here. |
| [Decisions](decisions.md) | Why things are the way they are. A change that reverses one of these should update it. |

A change of behaviour with no changelog entry, or a new design choice with no line in decisions, is a review comment.

## 2. Let CI run

The pull request's checks run `.github/workflows/ci.yml` and `docs.yml`:

| Check | What it proves |
| --- | --- |
| `ruff check`, `ruff format --check` | Lint and formatting, on Python 3.10 and 3.14. |
| `pytest` | owpp itself: bundler, runtime, libraries, deploy, CLI. |
| `owpp test --dir examples/plugins` | Each example plugin's own tests, against the mock Open-WebUI ([testing](testing.md)). |
| `owpp check --strict --dir examples/plugins` | Every example bundles and compiles against its real, pinned upstream sources, with no undefined names. |
| `uv build`, then the wheel runs `owpp check` | The package that goes to PyPI carries the runtime and works. |
| `mkdocs build --strict` | This site builds, and no link in it is broken. |

## 3. Run it yourself

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pytest
uv run owpp test --dir examples/plugins
uv run owpp check --strict --dir examples/plugins
uv run --group docs mkdocs serve      # this site, at http://127.0.0.1:8000
```

## 4. See it work on a live Open-WebUI

The unit tests run against a mock. It covers what plugins call, not Open-WebUI's chat pipeline, sign-in providers, Redis or permission groups ([what it is not](testing.md#what-it-is-not)). So for a change to a plugin:

1. Deploy to a test instance, never production: `owpp deploy --only <id> --dry-run` lists what would change, then run it without `--dry-run` ([tooling](tooling.md)).
2. Open the [test catalogue](reference/test-catalogue.md) at that plugin and work through the **By hand** boxes for the tests the change touches. Before a release, work through all of them.
3. Work through the `## Test` list in the plugin's README.
4. Disable the function and check that what it installed (tools, skills, routes, files) is gone.

## 5. Check what you are trusting

- **Remote code is pinned** by full commit SHA in `plugin.yaml` (`source:`). A changed SHA means new upstream code: read the upstream diff between the two commits.
- **Only its own objects.** The deploy updates and deletes only what carries its `managed_by` marker. A change to that logic needs a test showing hand-made objects are left alone.
- **Routes say who may use them.** A route without a signed-in user must be marked `public` in so many words ([libraries](libraries.md)).
- Anything else in [security](project/security.md).

## 6. Approve

Approve when CI is green, the live checks for the change pass, and the changelog and decisions are up to date. A release is a `v*` tag on `main`. `.github/workflows/publish.yml` publishes that tag to PyPI.
