# Making a change

What a change to this repository includes, so that the person who [reviews it](reviewing.md) can follow and repeat it.

## Before you start

- Find or open an issue on [GitHub Issues](https://github.com/zmnatz/open-webui-plugin-protocol/issues) that says what you are changing and why. Labels are in [triage labels](agents/triage-labels.md).
- Work on a branch, not `main`.
- Install the tools: [uv](https://docs.astral.sh/uv/), then `uv sync`. For this site: `uv sync --group docs` (Python 3.11 or newer).

## What a change includes

| Part | Where | Why |
| --- | --- | --- |
| The code | `src/owpp/` (the CLI, bundler and deploy), `src/owpp/runtime/` (deployed byte for byte, never reformatted), or a plugin in `examples/plugins/` | |
| Tests | `tests/` for owpp, `examples/plugins/<id>/tests/` for a plugin | They show it works, and keep it working. |
| A docstring on each plugin test | the test itself: what it checks, then `By hand:` steps ([describe every test](testing.md#describe-every-test)) | A reviewer repeats them on a live Open-WebUI. The [test catalogue](reference/test-catalogue.md) is built from them. |
| The guide | `docs/*.md` | When behaviour or a command changes. |
| A changelog entry | `CHANGELOG.md`, in the section of the version being prepared (`## 0.1.0 (not released yet)` until the first release) | What users will notice. |
| A decision | `docs/decisions.md` | When you chose one way over another, so the choice can be revisited. |
| A commit message that says why | git | It becomes the change's entry in the [audit trail](project/audit-trail.md). |

## Step by step

1. Write the test first, with its docstring, and see it fail: `uv run pytest -k <name>` or `uv run owpp test --dir examples/plugins <id> -- -k <name>`.
2. Make the change, until it passes.
3. Run everything CI runs ([reviewing, step 3](reviewing.md#3-run-it-yourself)).
4. If you changed a plugin, deploy it to a test instance and do its **By hand** steps yourself.
5. Update the guide, the changelog and decisions.
6. Check this site: `uv run --group docs python tools/build_docs.py`. A broken link fails the build.
7. Open a pull request: say what changed, why, and which live checks you did.

## This site

The site is built with [Zensical](https://zensical.org/), configured in `zensical.toml`. The pages are `docs/*.md`. Build it with `uv run --group docs python tools/build_docs.py` (or `serve` to preview), not `zensical` directly: the script puts `docs/` and the generated pages into `build/docs/`, which is what Zensical builds. Nothing generated is checked in, so none of it can go stale:

- the root `CHANGELOG.md`, `SECURITY.md` and `NOTICE.md`, and each example plugin's `README.md`;
- the examples overview, from each `plugin.yaml`;
- the test catalogue, from the test docstrings;
- the audit trail, from `git log`.

Links written for GitHub (`../SECURITY.md`, a plugin's `config.yaml`) are rewritten to the page that carries the file, or to the file on GitHub. A link to a file or heading that does not exist fails the build. `serve` assembles the pages once, so after editing `docs/`, run it again.

`.github/workflows/docs.yml` builds the site on every pull request and publishes it to GitHub Pages from `main`. To publish, the repository's **Settings > Pages > Source** must be set to **GitHub Actions** once.
