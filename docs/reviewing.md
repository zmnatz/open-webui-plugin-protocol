# Reviewing a change

This page tells you how to check a pull request or a release before it reaches an Open-WebUI instance. Everything a plugin does runs inside Open-WebUI with admin rights. So a change is not done until a person has read it and seen it work.

## 1. Know what changed and why

| Look at | It tells you |
| --- | --- |
| The pull request's description and commits | What the author meant to do. Each commit message says why. |
| The [changelog](project/changelog.md) section of the next version | What users will notice ([what a change includes](contributing.md#what-a-change-includes)). |

If users will notice a change of behaviour and it has no changelog entry, ask for one in a review comment.

## 2. Let CI run

The pull request's checks run `.github/workflows/ci.yml`, `docs.yml` and `live.yml`:

| Check | What it proves |
| --- | --- |
| `ruff check`, `ruff format --check` | The code passes lint and formatting. |
| `pytest` | owpp itself works: bundler, runtime, libraries, deploy, CLI. |
| `owpp test --dir examples/plugins` | Each example plugin passes its own tests on the test harness ([testing](testing.md)). |
| `owpp check --strict --dir examples/plugins` | Every example bundles and compiles with its pinned upstream sources, with no undefined names and no warnings. |
| `uv build`, then the wheel runs `owpp check` | The package for PyPI carries the runtime and the files of `owpp live`, and works. |
| `tools/build_docs.py` | This site builds. No link or heading that it points to is missing, and the menu lists every example. |
| `tools/screenshots/run.py --live` | The [live suite](testing/live.md#this-repositorys-live-suite) passes on a real Open-WebUI. |

`ci.yml` runs the first four checks on Python 3.12, the Python of the pinned Open-WebUI.

## 3. Run it yourself

Run these commands:

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pytest -n auto
uv run owpp test --dir examples/plugins -- -n auto
uv run owpp check --strict --dir examples/plugins
uv run --group docs python tools/build_docs.py serve   # preview this site (Python 3.11+)
```

To run the live suite too, see [this repository's live suite](testing/live.md#this-repositorys-live-suite).

## 4. See it work on a live Open-WebUI

The unit tests run on the test harness, which fakes some parts of Open-WebUI ([what the harness fakes](testing/harness.md#what-the-harness-fakes)). So for a change to a plugin, do these steps. For a throwaway instance, see [trying things out](testing/live.md#trying-things-out).

**Caution: use a test instance, never production.** A deploy changes the functions on the instance.

1. List what a deploy would change: `uv run owpp deploy --dir examples/plugins --only <id> --dry-run`.
2. Run the same command without `--dry-run` ([`owpp deploy`](commands/deploy.md)).
3. Open the [test catalogue](reference/test-catalogue.md) at that plugin.
4. Do the **By hand** steps of the tests that the change touches. Before a release, do all of them.
5. Do the steps in the `## Test` list of the plugin's README.
6. Disable the function.
7. Make sure that its tools and skills are gone, and that its routes and static files answer 404.
8. If the change alters what users see, take the [screenshots](screenshots.md) again.
9. Compare the new screenshots with the committed ones. The diff of `docs/screenshots/` is part of the review.

## 5. Check what you are trusting

- **Remote code is pinned** by full commit SHA in `plugin.yaml` (`source:`). A changed SHA means new upstream code. Read the upstream diff between the two commits.
- **The deploy deletes only its own functions**: those that carry its `managed_by` marker. It does update, and mark, any function whose id matches a plugin ([adopting](adopting.md)). A change to this logic needs a test that shows that hand-made objects are left alone.
- **Routes say who may use them.** A mount serves people who are not signed in only with `access="public"` or `static: {access: public}` ([routes](libraries.md#routes)). `owpp check` lists each one as a `note`.
- **A `guard=` mount replaces the sign-in check.** `owpp check` does not list it, so search the code for it, and read [what it must verify](libraries.md#the-one-exception-guard).
- Check everything else in [security](project/security.md).

## 6. Approve

Approve when all of these are true:

- CI is green.
- The live checks for the change pass.
- The changelog is up to date.

A change merges into `develop`. A release goes from `develop` to `main` on a release branch ([releasing](contributing.md#releasing)).
