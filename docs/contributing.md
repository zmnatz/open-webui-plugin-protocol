# Contributing

What a change to this repository includes, so that the person who [reviews it](reviewing.md) can follow and repeat it.

## Before you start

- Find or open an issue on [GitHub Issues](https://github.com/zmnatz/open-webui-plugin-protocol/issues) that says what you are changing and why. The triage labels are `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human` and `wontfix`.
- Branch from `develop`, not `main` ([branches](#branches)).
- Install the tools: [uv](https://docs.astral.sh/uv/), then `uv sync`. For this site: `uv sync --group docs` (Python 3.11 or newer).

## What a change includes

| Part | Where | Why |
| --- | --- | --- |
| The code | `src/owpp/` (the CLI, bundler and deploy), `src/owpp/runtime/` (deployed byte for byte, never reformatted), or a plugin in `examples/plugins/` | |
| Tests | `tests/` for owpp, `examples/plugins/<id>/tests/` for a plugin | They show it works, and keep it working. |
| A docstring on each plugin test | the test itself: what it checks, then `By hand:` steps ([describe every test](testing/writing.md#describe-every-test)) | A reviewer repeats them on a live Open-WebUI. The [test catalogue](reference/test-catalogue.md) is built from them. |
| The guide | `docs/*.md` | When behaviour or a command changes. |
| A changelog entry | `CHANGELOG.md`, in the section of the version being prepared (`## Unreleased` until it is released) | What users will notice, in one sentence; the details belong in the docs. |
| A review of the docs around it | the pages the change touches, and the ones next to them | For an issue labelled `documentation`: the same thing explained in full in two places becomes one explanation and a link, and anything that no longer matches the code is fixed. |
| A commit message that says why | git, with a [conventional-commit prefix](#commit-messages) | A reviewer reads it with the diff. |

## Step by step

1. Write the test first, with its docstring, and see it fail: `uv run pytest -k <name>` or `uv run owpp test --dir examples/plugins <id> -- -k <name>`.
2. Make the change, until it passes.
3. Run everything CI runs ([reviewing, step 3](reviewing.md#3-run-it-yourself)).
4. If you changed a plugin, deploy it to a test instance and do its **By hand** steps yourself.
5. Update the guide and the changelog.
6. Check this site: `uv run --group docs python tools/build_docs.py`. A broken link fails the build.
7. Open a pull request into `develop`: say what changed, why, and which live checks you did. The [live suite](testing/live.md#the-live-suite) runs on it; to run it before you push, `run.py --live`.

## Commit messages

A commit message starts with a conventional-commit type, chosen from the issue's labels:

| Label | Type |
| --- | --- |
| `enhancement` | `feat` |
| `bug` | `fix` |
| `documentation` (alone) | `docs` |
| `refactor` | `refactor` |
| `test` | `test` |
| `chore` | `chore`, `ci` or `build` |
| `breaking` | `!` after the type, and a `BREAKING CHANGE:` footer |

`documentation` next to another type label means the change includes the docs review above, not that the commit is `docs`: an `enhancement` with `documentation` is `feat`.

## Branches

The repository follows [gitflow](https://nvie.com/posts/a-successful-git-branching-model/) ([why](adr/0001-gitflow.md)):

- `develop` is the next release, and the default branch.
- `main` is the latest release, and what the docs site shows. It moves only when a release or hotfix merges into it.

| Branch | Starts from | Merges into | How |
| --- | --- | --- | --- |
| a change: `feat/…`, `fix/…`, `docs/…`, named after its type | `develop` | `develop` | squash |
| `release/<version>` | `develop` | `main`, then `main` into `develop` | merge commit |
| `hotfix/<version>` | `main` | `main`, then `main` into `develop` | merge commit |

Never squash or rebase into `main`, or back from it into `develop`: `develop` would then lack commits that `main` has, and the next release would conflict. The repository's rules allow only merge commits into `main`.

## Releasing

1. Cut `release/<version>` from `develop`. On it: set `__version__` in `src/owpp/__init__.py`, turn `## Unreleased` in `CHANGELOG.md` into `## <version> (<date>)`, and move the docs' version pins. Only fixes for the release go on this branch after that.
2. Open a pull request into `main` and merge it with a merge commit.
3. Tag the merge on `main`: `git switch main && git pull && git tag -a v<version> -m "owpp <version>" && git push origin v<version>`. `.github/workflows/publish.yml` refuses a tag that is not `v<__version__>` or has no dated changelog section, publishes the package to PyPI, and then creates the GitHub release with that section as its notes and the built package attached.
4. Open a pull request from `main` into `develop`, and merge it with a merge commit.

A hotfix is the same from step 1, with `hotfix/<version>` cut from `main` and a patch version.

## This site

The site is built with [Zensical](https://zensical.org/), configured in `zensical.toml`. The pages are `docs/*.md`. Build it with `uv run --group docs python tools/build_docs.py` (or `serve` to preview), not `zensical` directly: the script puts `docs/` and the generated pages into `build/docs/`, which is what Zensical builds. Nothing generated is checked in, so none of it can go stale:

- the root `CHANGELOG.md`, `SECURITY.md`, `LICENSE` and `NOTICE.md`, and each example plugin's `README.md`;
- the examples overview, from each `plugin.yaml`;
- the test catalogue, from the test docstrings.

Links written for GitHub (`../SECURITY.md`, a plugin's `config.yaml`) are rewritten to the page that carries the file, or to the file on GitHub. A link to a file or heading that does not exist fails the build. `serve` assembles the pages once, so after editing `docs/`, run it again.

`.github/workflows/docs.yml` builds the site on every pull request and publishes it to GitHub Pages from `main`, so the site matches the latest release. To publish, the repository's **Settings > Pages > Source** must be set to **GitHub Actions** once.
