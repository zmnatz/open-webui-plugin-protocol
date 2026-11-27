# Contributing

This page says what a change to this repository includes. Then the person who [reviews it](reviewing.md) can follow and repeat it.

## Before you start

1. Find or open an issue on [GitHub Issues](https://github.com/zmnatz/open-webui-plugin-protocol/issues) that says what you change and why.
2. Create your branch from `develop`, not `main` ([branches](#branches)).
3. Install [uv](https://docs.astral.sh/uv/).
4. Run `uv sync`.
5. To work on this site, also run `uv sync --group docs`. It needs Python 3.11 or newer.

The triage labels are `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human` and `wontfix`.

## What a change includes

| Part | Where | Why |
| --- | --- | --- |
| The code | `src/owpp/` (the CLI, bundler and deploy), `src/owpp/runtime/`, or a plugin in `examples/plugins/`. A deploy copies the runtime byte for byte, so never reformat it. | |
| Tests | `tests/` for owpp, `examples/plugins/<id>/tests/` for a plugin | They show that it works, and keep it working. |
| A docstring on each plugin test | In the test: what it checks, then `By hand:` steps ([describe every test](testing/writing.md#describe-every-test)) | A reviewer repeats the steps on a live Open-WebUI. The [test catalogue](reference/test-catalogue.md) is built from them. |
| The guide | `docs/` | Change it when behaviour or a command changes. |
| A changelog entry | `CHANGELOG.md`, in the section of the next version (`## Unreleased` until the release) | It says in one sentence what users will notice. The details belong in the docs. |
| A review of the docs around it | The pages that the change touches, and the ones next to them | For an issue labelled `documentation`: explain each thing in full once and link to it. Fix what no longer matches the code. |
| A commit message that says why | git, with a [conventional-commit prefix](#commit-messages) | A reviewer reads it with the diff. |

## Step by step

1. Write the test first, with its docstring.
2. Run it, and see it fail: `uv run pytest -k <name>`, or `uv run owpp test --dir examples/plugins <id> -- -k <name>`.
3. Change the code until the test passes.
4. Run what CI runs ([reviewing, step 3](reviewing.md#3-run-it-yourself)).
5. If you changed a plugin, deploy it to a test instance ([reviewing, step 4](reviewing.md#4-see-it-work-on-a-live-open-webui)).
6. Do its **By hand** steps on that instance.
7. Update the guide and the changelog.
8. Check this site: `uv run --group docs python tools/build_docs.py`. A broken link fails the build.
9. To run the [live suite](testing/live.md#this-repositorys-live-suite) before you push, run `uv run python tools/screenshots/run.py --live`.
10. Open a pull request into `develop`. Say what changed, why, and which live checks you did.

The live suite also runs on the pull request.

## Commit messages

Start each commit message with a conventional-commit type. The issue's labels choose the type:

| Label | Type |
| --- | --- |
| `enhancement` | `feat` |
| `bug` | `fix` |
| `documentation` (alone) | `docs` |
| `refactor` | `refactor` |
| `test` | `test` |
| `chore` | `chore`, `ci` or `build` |
| `breaking` | `!` after the type, and a `BREAKING CHANGE:` footer |

If an issue has `documentation` and another type label, the change includes the [docs review](#what-a-change-includes). The other label still chooses the type: `enhancement` with `documentation` is `feat`.

## Branches

The repository follows [gitflow](https://nvie.com/posts/a-successful-git-branching-model/) ([why](adr/0001-gitflow.md)):

- `develop` is the next release, and the default branch.
- `main` is the latest release, and what the docs site shows. It moves only when a release or hotfix merges into it.

| Branch | Starts from | Merges into | How |
| --- | --- | --- | --- |
| a change: `feat/…`, `fix/…`, `docs/…`, named after its type | `develop` | `develop` | squash |
| `release/<version>` | `develop` | `main`, then `main` into `develop` | merge commit |
| `hotfix/<version>` | `main` | `main`, then `main` into `develop` | merge commit |

**Caution: never squash or rebase into `main`, or from `main` back into `develop`.** If you do, `develop` lacks commits that `main` has, and the next release conflicts. The repository's rules allow only merge commits into `main`.

## Releasing

You start a release from the Actions tab. After you merge its pull request, workflows do the rest. Shared workflows in [zmnatz/github-workflows](https://github.com/zmnatz/github-workflows) do the branches, the tag and the merge-back. This repository's `release.yml`, `tag.yml` and `merge-back.yml` call them with its own commands. Publishing on the tag belongs to this repository.

Those three workflows need a `RELEASE_TOKEN` Actions secret, and fail at once without it. It is a fine-grained token (or a GitHub App's) for this repository, with **Contents** and **Pull requests: read and write** ([the token](https://github.com/zmnatz/github-workflows#the-token)). GitHub starts no workflows for what a workflow's own token does. So with that token, the release pull request would get no checks, and the tag would release nothing. When the token expires, renew it and update the secret.

To make a release:

1. Run **Actions > release > Run workflow** with the version: `patch`, `minor`, `major`, or a number such as `0.5.0`.
2. Push only fixes for this release to the `release/<version>` branch.
3. Wait until CI is green.
4. Merge the pull request into `main` with a merge commit.

In step 1, `.github/workflows/release.yml` creates `release/<version>` from `develop`, prepares it with `tools/release.py`, and opens its pull request into `main`. The script sets `__version__` in `src/owpp/__init__.py`. It turns `## Unreleased` in `CHANGELOG.md` into `## <version> (<date>)`. It also moves the version pins in the README, the docs and the skills. To prepare a branch by hand instead, run `python tools/release.py prepare <version>` on it.

CI's `release` job checks a `release/` or `hotfix/` pull request into `main` as publishing will. `v<__version__>` must not be a tag yet, and the changelog must have a dated section for it, with entries.

After the merge, these steps are automatic:

- **Tag.** `.github/workflows/tag.yml` tags the merge on `main` as `v<version>`, and does nothing else. If a push to `main` has a version that already has a tag, it tags nothing.
- **Release.** A `v*` tag starts everything a release does, whether `tag.yml` or a person pushed it. `.github/workflows/publish.yml` publishes the package to PyPI. It also creates the GitHub release, with the changelog section as its notes and the package attached. `.github/workflows/docs.yml` publishes [the docs site](#this-site).
- **Merge-back.** `.github/workflows/merge-back.yml` opens a pull request from `main` into `develop`, and merges it with a merge commit.

If the merge-back cannot merge (usually a conflict in `CHANGELOG.md`, when `develop` has new entries), the run fails. It leaves the pull request open, with the steps to resolve it on a branch cut from `main`. GitHub's **Resolve conflicts** works on that branch, but not on `main` itself. To try again, run **Actions > merge-back > Run workflow**.

### A hotfix

1. Run **Actions > release > Run workflow** with **kind** set to `hotfix` and the version set to `patch`.
2. Push the fix and its changelog entry to the `hotfix/<version>` branch.
3. Mark the pull request ready.
4. Merge it into `main` with a merge commit.

In step 1, the workflow creates the branch from `main`, adds an empty dated changelog section, and opens a draft pull request. The steps after the merge are those of a release.

## This site

[Zensical](https://zensical.org/) builds the site, as `zensical.toml` configures it. The pages are the Markdown files in `docs/`, except `docs/agents/`.

1. Build the site with `uv run --group docs python tools/build_docs.py`. To preview it, add `serve`.
2. If you edit `docs/` during a preview, stop `serve` and run it again, because it assembles the pages once.

Do not run `zensical` directly. The script puts `docs/` and the generated pages into `build/docs/`, and Zensical builds that folder. Nothing generated is checked in, so none of it can go stale. The script adds these:

- the root `CHANGELOG.md`, `SECURITY.md`, `LICENSE` and `NOTICE.md`, and each example plugin's `README.md`;
- the examples overview, from each `plugin.yaml`;
- each example's built function, as a `.py` file to import by URL, which a button at the top of its page shows in a popup (`docs/assets/built-function.js`);
- the screenshot pages and galleries, from `docs/screenshots/screenshots.json`;
- the test catalogue, from the test docstrings;
- the library table in [libraries](libraries.md), from the library catalogue;
- `llms.txt` and `llms-full.txt`, for language models.

The script rewrites links written for GitHub (`../SECURITY.md`, a plugin's `config.yaml`) to the page that carries the file, or to the file on GitHub. The build fails on a link to a file or heading that does not exist. It also fails if the menu in `zensical.toml` lacks an example.

`.github/workflows/docs.yml` builds the site on every pull request. It publishes the site to GitHub Pages from each `v*` tag, so the site matches the latest release. To publish it again, run **Actions > docs > Run workflow** on the latest tag.

The published site also gets Google Analytics, from [the shared `google-analytics` action](https://github.com/zmnatz/github-workflows#google-analytics). The action takes the `G-` measurement ID from the `GA_ID` Actions secret, and publishing fails without it.

Set up GitHub Pages once per repository:

1. Set **Settings > Pages > Source** to **GitHub Actions**.
2. In **Settings > Environments**, make the `github-pages` environment allow `v*` tags.
