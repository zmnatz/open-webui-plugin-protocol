# owpp pull

```
owpp pull [id ...] [--dry-run] [--bump patch|minor|major|none] [--dir FOLDER]
```

Moves the pinned commit of each plugin taken from git to the latest commit of the branch or tag it follows. A plugin with a `source:` is pinned to a full commit SHA, so what is deployed changes only when the SHA moves, as a change you review and commit. `owpp pull` makes that change:

```
$ owpp pull
new   inline_visualizer: moved f668387 -> 917c88f (default branch)
        changed inline-visualizer-v2/SKILL.md
        changed inline-visualizer-v2/tool.py
        https://github.com/Classic298/open-webui-plugins/compare/f668387...917c88f
ok    other_plugin: up to date (branch v2), 3c1e9a0
1 plugin(s) moved: review the upstream changes, run `owpp check` and `owpp test`, then commit plugin.yaml
```

For each plugin with a `source:` (or just the ids given), it:

1. looks up the latest commit of the branch in `source: branch:`, or the commit of the tag in `source: tag:`, or the latest of the repository's default branch when there is neither, with `git ls-remote`;
2. fetches the files the plugin takes at the pinned commit and at the latest one, and lists which were **changed**, **added** or **removed** (under a `dir:`, file by file), with a compare link for GitHub;
3. rewrites the `ref:` line of `plugin.yaml` to the new SHA, keeping every comment and the layout, or adds it after `git:` when the source has none yet (a first pin: `pinned to <sha>`, with a link to the files);
4. when files it takes changed, bumps the plugin's version (`--bump`) and adds a `CHANGELOG.md` entry naming the commits and the files. A plugin whose function is the upstream's own, or that is a [whole plugin from git](../plugin-format.md#a-whole-plugin-from-git), keeps the upstream's version.

It commits nothing and deploys nothing: the change is yours to review and commit. A plugin whose ref cannot be looked up, or whose files are not all there at the new commit, is reported as `FAIL` and left as it was, and the command exits 1. To see what the move would change on the live instance first, run [`owpp deploy --dry-run --latest`](deploy.md#the-report-what-changes-in-versions).

## Options

| Option | Meaning |
| --- | --- |
| `id ...` | The plugins to pull. Default: every plugin with a `source:`. |
| `--dry-run` | Say what would move; write nothing. |
| `--bump` | How to bump a moved plugin's version, with a `CHANGELOG.md` entry: `patch` (default), `minor`, `major`, or `none`. |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |

## A pull request for each upgrade

Run it on a schedule:

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
      - run: uvx owpp@0.4.1 pull | tee pull.txt
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

The pull request is where the upstream diff is reviewed; the deploy runs when it is merged.

## Examples

```sh
owpp pull --dry-run                  # what would move
owpp pull                            # move every plugin taken from git
owpp pull inline_visualizer --bump minor
```

## Related

- [`owpp deploy --dry-run --latest`](deploy.md#the-report-what-changes-in-versions): what the move would change on the instance.
- [`owpp check`](check.md) and [`owpp test`](test.md): run them on the moved code before committing.
- [Plugin format: `source:`](../plugin-format.md): `ref`, `branch` and `tag`.
- [Bundling](../bundling.md): why only a full commit SHA is accepted.
