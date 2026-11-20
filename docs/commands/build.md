# owpp build

```
owpp build [id ...] [--out FOLDER] [--latest] [--dir FOLDER]
```

Bundles the plugins into a folder that [`owpp deploy --from`](deploy.md#deploying-a-build) deploys somewhere else. It is the deploy's input, written down, as `dist/` is for a package: build where the plugins' [git sources](../bundling.md#git-sources) can be fetched (CI, with `git` and the network), and deploy where the instance can be reached, with no checkout, no `git` and no access to the source repositories.

```
$ owpp build --out dist
built dist/excalidraw.py
built dist/stale_data.py
2 function(s) in dist: every plugin
```

The folder holds, for each plugin:

| File | What it is |
| --- | --- |
| `<id>.py` | The bundle Open-WebUI stores, as [`owpp bundle`](bundle.md) prints it. |
| `<id>.json` | What the deploy needs besides the code: the function's type, name, description, `global`, valves, the commits of its sources, and `requires:`. With a digest of the bundle, so an edited bundle is refused. |

and `build.json`: the owpp version that built it, whether it holds every plugin, and the commits of a `--latest` build.

- **Generated, never committed.** Put the folder in `.gitignore`. The same repository commit and owpp version build it byte for byte the same, so two builds can be diffed to see what a deploy would change.
- **The same owpp deploys it.** A bundle embeds the runtime and libraries of the owpp that built it, so `owpp deploy --from` refuses a build made by another version.
- **Only a build of every plugin prunes.** Built with ids, the build is partial: it deploys like [`--only`](deploy.md#options) and never deletes a function.
- **A `--latest` build only deploys as a dry run**, like [`owpp deploy --dry-run --latest`](deploy.md#the-report-what-changes-in-versions): to deploy newer commits, [`owpp pull`](pull.md) them in a reviewed change, then build.
- **An existing folder** is replaced when it is an earlier build, and refused when it holds anything else.

## Options

| Option | Meaning |
| --- | --- |
| `id ...` | Build just these plugins: a partial build, which never prunes. Default: all. |
| `--out FOLDER` | The folder to write. Default `./dist`. |
| `--latest` | Build at the latest commit each git-sourced plugin follows, as [`owpp pull`](pull.md) would move it, without changing `plugin.yaml`. Such a build deploys only as a dry run. |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |

## Examples

```sh
owpp build                          # every plugin, into ./dist
owpp build excalidraw --out build   # one plugin: a partial build
owpp deploy --from dist --dry-run   # elsewhere: what deploying it would change
```

Building in one job and deploying in another, with the [GitHub Action](../tooling.md#github-action):

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - run: uvx owpp@0.3.1 check --strict && uvx owpp@0.3.1 build --out dist
      - uses: actions/upload-artifact@v4
        with: { name: plugins, path: dist }
  deploy:
    needs: build
    runs-on: ubuntu-latest   # or a runner that can reach the instance
    steps:
      - uses: actions/download-artifact@v4
        with: { name: plugins, path: dist }
      - uses: zmnatz/open-webui-plugin-protocol@v0.3.1
        with:
          url: https://chat.example.com
          api-key: ${{ secrets.OPEN_WEBUI_API_KEY }}
          from: dist
```

## Related

- [`owpp deploy`](deploy.md): `--from` deploys a build, `--no-prune` deletes nothing.
- [`owpp bundle`](bundle.md): one plugin's bundle, to read or diff.
- [`owpp check`](check.md): run it before building; a build does not check.
