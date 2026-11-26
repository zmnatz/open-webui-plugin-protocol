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

Releases are started from the Actions tab, and everything after the merge is automatic. The branching, tagging and merge-back are the shared workflows in [zmnatz/github-workflows](https://github.com/zmnatz/github-workflows), which this repository's `release.yml`, `tag.yml` and `merge-back.yml` call with its own commands; publishing is this repository's, on the tag:

1. **Start it.** Run **Actions > release > Run workflow** with the version (`patch`, `minor`, `major`, or one such as `0.5.0`). `.github/workflows/release.yml` cuts `release/<version>` from `develop`, prepares it with `tools/release.py` (it sets `__version__` in `src/owpp/__init__.py`, turns `## Unreleased` in `CHANGELOG.md` into `## <version> (<date>)`, and moves the docs' version pins), and opens its pull request into `main`. Only fixes for the release go on that branch now. To prepare one by hand instead, run `python tools/release.py prepare <version>` on the branch.
2. **Merge it** with a merge commit, once CI is green. CI's `release` job checks a `release/` or `hotfix/` pull request into `main` the way publishing will: `v<__version__>` is not a tag yet, and the changelog has a dated section for it with entries.
3. **Tagging.** The merge into `main` starts `.github/workflows/tag.yml`, which tags it `v<version>`, and does nothing else. A push to `main` whose version is already tagged tags nothing.
4. **Releasing the tag.** Everything a release does runs on the `v*` tag, whether `tag.yml` pushed it or you did by hand: `.github/workflows/publish.yml` publishes the package to PyPI and creates the GitHub release with the changelog section as its notes and the built package attached, and `.github/workflows/docs.yml` publishes the docs site.
5. **Merge-back.** The same merge starts `.github/workflows/merge-back.yml`, which opens a pull request from `main` into `develop` and merges it with a merge commit. When it conflicts (usually `CHANGELOG.md`, when `develop` has new entries), it leaves the pull request open with the steps to resolve it on a branch cut from `main` (GitHub's **Resolve conflicts** works there, as it can't on `main` itself), and the run fails so it is not missed. **Actions > merge-back > Run workflow** tries again.

A hotfix is the same with **kind** set to `hotfix`: `hotfix/<version>` is cut from `main`, with a patch version and an empty dated changelog section, and its pull request opens as a draft. Push the fix and its changelog entry to that branch, then mark it ready and merge it.

`release.yml`, `tag.yml` and `merge-back.yml` need a `RELEASE_TOKEN` Actions secret, and fail at once without it: a fine-grained token (or a GitHub App's) for this repository with **Contents** and **Pull requests: read and write** ([the token](https://github.com/zmnatz/github-workflows#the-token)). GitHub starts no workflows for what a workflow's own token does, so with that token the release pull request would get no checks and the tag would release nothing. When the token expires, renew it and update the secret.

## This site

The site is built with [Zensical](https://zensical.org/), configured in `zensical.toml`. The pages are `docs/*.md`. Build it with `uv run --group docs python tools/build_docs.py` (or `serve` to preview), not `zensical` directly: the script puts `docs/` and the generated pages into `build/docs/`, which is what Zensical builds. Nothing generated is checked in, so none of it can go stale:

- the root `CHANGELOG.md`, `SECURITY.md`, `LICENSE` and `NOTICE.md`, and each example plugin's `README.md`;
- the examples overview, from each `plugin.yaml`;
- each example's built function, as a `.py` file to import by URL. A button atop the example's page shows it in a popup (`docs/assets/built-function.js`);
- the test catalogue, from the test docstrings.

Links written for GitHub (`../SECURITY.md`, a plugin's `config.yaml`) are rewritten to the page that carries the file, or to the file on GitHub. A link to a file or heading that does not exist fails the build. `serve` assembles the pages once, so after editing `docs/`, run it again.

`.github/workflows/docs.yml` builds the site on every pull request and publishes it to GitHub Pages from each `v*` tag, so the site matches the latest release. What it publishes also gets Google Analytics, added by [the shared `google-analytics` action](https://github.com/zmnatz/github-workflows#google-analytics) with the `G-` measurement ID in the `GA_ID` Actions secret; publishing fails without it. To publish it again, run **Actions > docs > Run workflow** on the latest tag. Once per repository, **Settings > Pages > Source** must be set to **GitHub Actions**, and the `github-pages` environment (**Settings > Environments**) must allow `v*` tags.
