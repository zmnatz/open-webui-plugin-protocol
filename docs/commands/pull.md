# owpp pull

```
owpp pull [id ...] [--dry-run] [--bump patch|minor|major|none] [--dir FOLDER]
```

`owpp pull` moves each plugin taken from git to the latest commit of the branch or tag that it follows. A plugin with a `source:` is pinned to a full commit SHA. Thus the deployed code changes only when the SHA moves, in a change that you review and commit. `owpp pull` makes that change:

```
$ owpp pull
new   inline_visualizer: moved f668387 -> 917c88f (default branch)
        changed inline-visualizer-v2/SKILL.md
        changed inline-visualizer-v2/tool.py
        https://github.com/Classic298/open-webui-plugins/compare/f668387...917c88f
        bumped the version 1.0.0 -> 1.0.1
ok    other_plugin: up to date (branch v2), 3c1e9a0
1 plugin(s) moved: review the upstream changes, run `owpp check` and `owpp test`, then commit plugin.yaml
```

## Upgrade a plugin

**Caution:** Review the upstream changes before you commit them. The new code runs on your Open-WebUI server.

1. Run `owpp pull`.
2. Review the upstream changes that it lists.
3. Run [`owpp check`](check.md).
4. Run [`owpp test`](test.md).
5. Commit `plugin.yaml` and, if it changed, `CHANGELOG.md`.

To see first what the move changes on the live instance, run [`owpp deploy --dry-run --latest`](deploy.md#the-report-what-changes-in-versions).

## What it does

The command reads each plugin with a `source:`, or only the ids that you give. For each one, it does these steps:

1. It finds the latest commit with `git ls-remote`. It uses the branch in `source: branch:` or the tag in `source: tag:`. If there is neither, it uses the default branch of the repository.
2. It fetches the files that the plugin takes, at the pinned commit and at the latest one. It lists each file that was **changed**, **added** or **removed**, including each file under a `dir:`. For GitHub, it adds a compare link.
3. It writes the new SHA in the `ref:` line of `plugin.yaml`, and keeps every comment and the layout. If there is no `ref:` yet, it adds one after `git:`. This first pin shows `pinned to <sha>` and, for GitHub, a link to the files.
4. If the files changed, it gives the plugin a new version (`--bump`). It also adds a `CHANGELOG.md` entry that names the commits and the files.

Step 4 does not apply to a first pin. It also does not apply if the plugin takes its function from upstream, or is a [whole plugin from git](../plugin-format.md#a-whole-plugin-from-git). Such a plugin keeps the upstream's version.

The command commits nothing and deploys nothing. It reports `FAIL` for a plugin if it cannot find the commit, or if a file is missing at the new commit. It does not change that plugin, and it exits 1.

## Options

| Option | Meaning |
| --- | --- |
| `id ...` | The plugins to pull. Default: every plugin with a `source:`. |
| `--dry-run` | Show what moves, and write nothing. |
| `--bump` | Which part of a moved plugin's version to raise, with a `CHANGELOG.md` entry: `patch` (default), `minor`, `major`, or `none`. |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |

## A pull request for each upgrade

This workflow runs `owpp pull` on a schedule and opens a pull request:

```yaml
# .github/workflows/pull-plugins.yml
on:
  schedule: [{ cron: "0 6 * * 1" }]   # Mondays
  workflow_dispatch:
jobs:
  pull:
    runs-on: ubuntu-latest
    permissions: { contents: write, pull-requests: write }
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - run: uvx owpp@0.7.1 pull | tee pull.txt
      - name: Open a pull request
        env: { GH_TOKEN: "${{ github.token }}" }
        run: |
          git diff --quiet && exit 0
          branch="owpp-pull/$(date +%Y-%m-%d)"
          git switch -c "$branch"
          git -c user.name=owpp-pull -c user.email=owpp-pull@users.noreply.github.com commit -qam "Pull plugins taken from git"
          git push -q origin "$branch"
          gh pr create --title "Pull plugins taken from git" --body-file pull.txt
```

Review the upstream changes in the pull request. Then merge it, so that your deploy workflow can deploy them.

## Examples

```sh
owpp pull --dry-run                  # what would move
owpp pull                            # move every plugin taken from git
owpp pull inline_visualizer --bump minor
```

## Related

- [`owpp deploy --dry-run --latest`](deploy.md#the-report-what-changes-in-versions): what the move changes on the instance.
- [`owpp check`](check.md) and [`owpp test`](test.md): run them on the new code before you commit it.
- [Plugin format: `source:`](../plugin-format.md): `ref`, `branch` and `tag`.
- [Bundling](../bundling.md): why owpp accepts only a full commit SHA.
