# owpp build

```
owpp build [id ...] [--out FOLDER] [--latest] [--dir FOLDER]
```

`owpp build` bundles the plugins into a folder, the **build**. [`owpp deploy --from`](deploy.md#deploying-a-build) deploys that folder, possibly on a different machine:

- Make the build where owpp can fetch the plugins' [git sources](../bundling.md#git-sources), for example in CI, with `git` and the network.
- Deploy it where owpp can reach the instance. That machine needs no copy of your repository, no `git` and no access to the source repositories.

```
$ owpp build --out dist
built dist/excalidraw.py
built dist/stale_data.py
2 function(s) in dist: every plugin
```

## What a build holds

The folder holds these two files for each plugin:

| File | What it is |
| --- | --- |
| `<id>.py` | The bundle that Open-WebUI stores, as [`owpp bundle`](bundle.md) prints it. |
| `<id>.json` | The other data that the deploy needs: the function's type, name, description, `global`, valves, source commits and `requires:`. It also holds a digest of the bundle, so the deploy refuses an edited bundle. |

It also holds `build.json`. That file records the owpp version, the plugin ids, and whether the build holds every plugin. For a `--latest` build, it also records the commits.

These rules apply to a build:

- **Do not commit a build.** Put the folder in `.gitignore`. The same repository commit and owpp version give the same bytes. Thus you can compare two builds to see what a deploy changes.
- **Build and deploy with the same owpp version.** A bundle embeds the runtime and libraries of the owpp that built it. `owpp deploy --from` refuses a build from a different version.
- **Only a build of every plugin prunes.** A build with ids is partial. It deploys like [`--only`](deploy.md#options) and never deletes a function.
- **A `--latest` build deploys only as a dry run**, like [`owpp deploy --dry-run --latest`](deploy.md#the-report-what-changes-in-versions). To deploy newer commits, [`owpp pull`](pull.md) them, review and commit the change, then build.
- **A new build replaces an earlier one** in the same folder. The command refuses a folder that holds other files.

## Options

| Option | Meaning |
| --- | --- |
| `id ...` | Build only these plugins: a partial build, which never prunes. Default: all. |
| `--out FOLDER` | The folder to write. Default `./dist`. |
| `--latest` | Build at the latest commit that each git-sourced plugin follows, as [`owpp pull`](pull.md) moves it. `plugin.yaml` does not change. Such a build deploys only as a dry run. |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |

## Examples

```sh
owpp build                          # every plugin, into ./dist
owpp build excalidraw --out build   # one plugin: a partial build
owpp deploy --from dist --dry-run   # elsewhere: what deploying it would change
```

To make the build in one job and deploy it in another with the [GitHub Action](../tooling.md#github-action):

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - run: uvx owpp@0.7.2 check --strict && uvx owpp@0.7.2 build --out dist
      - uses: actions/upload-artifact@v4
        with: { name: plugins, path: dist }
  deploy:
    needs: build
    runs-on: ubuntu-latest   # or a runner that can reach the instance
    steps:
      - uses: actions/download-artifact@v4
        with: { name: plugins, path: dist }
      - uses: zmnatz/open-webui-plugin-protocol@v0.7.2
        with:
          url: https://chat.example.com
          api-key: ${{ secrets.OPEN_WEBUI_API_KEY }}
          from: dist
```

## Related

- [`owpp deploy`](deploy.md): `--from` deploys a build, and `--no-prune` deletes nothing.
- [`owpp bundle`](bundle.md): read or compare one plugin's bundle.
- [`owpp check`](check.md): run it before you build, because a build does not check the plugins.
