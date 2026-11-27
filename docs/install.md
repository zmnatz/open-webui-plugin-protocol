# Install

`owpp` is a Python package with one dependency (PyYAML). You do not have to install it: [uv](https://docs.astral.sh/uv/) runs it straight from PyPI.

## Requirements

- **[uv](https://docs.astral.sh/uv/getting-started/installation/)**. It brings its own Python, so you need no Python of your own. Without uv, Python 3.10 or newer works with `pip` or `pipx` (below).
- **`git`**, for plugins that take code from another repository (`source:`), and for `owpp pull` and `owpp check --since`.
- For a deploy, an **Open-WebUI** instance and a way to sign in as an admin: an API key, a user name and password, an OIDC token, or none where the instance allows it (see [signing in](commands/deploy.md#signing-in)).

## Run it

```sh
uvx owpp --version         # runs the latest release, nothing installed
uvx owpp@0.7.0 list        # a pinned release (recommended: see below)
```

`uvx owpp <command>` works from any folder. Every command reads the plugins folder from `--dir`, else [`$OWPP_PLUGINS_DIR`](environment-variables.md#owpp_plugins_dir), else `./plugins`.

**Pin the version.** The runtime and the libraries are copied into what you deploy, so a new `owpp` changes your deployed code. Use `uvx owpp@0.7.0 ...` in scripts and CI, and move the pin as a reviewed change, the same way you would move any other dependency.

## The test extra

`owpp test` runs each plugin's tests against a mock Open-WebUI. It needs pytest and the packages Open-WebUI ships (FastAPI, httpx, SQLAlchemy, aiohttp), in the `test` extra:

```sh
uvx --from 'owpp[test]' owpp test
```

[`owpp live`](commands/live.md), the live tests on a throwaway Open-WebUI in Docker, is one of owpp's commands. Its tests in the browser need Playwright, which the `live` extra adds: `uvx --from 'owpp[live]' owpp live`.

## Installing it for good

To have `owpp` on your `PATH`:

```sh
uv tool install owpp==0.7.0          # or: uv tool install 'owpp[test]==0.7.0'
pipx install owpp==0.7.0             # or with pipx
pip install owpp==0.7.0              # or into a virtual environment
```

`python -m owpp` is the same command as `owpp`.

## An unreleased commit

```sh
uvx --from git+https://github.com/zmnatz/open-webui-plugin-protocol@<sha or branch> owpp list
```

## In GitHub Actions

Nothing to install: the [action](tooling.md#github-action) sets up uv and runs `owpp` from its own checkout, so the version is the tag you pin in `uses:`.

```yaml
- uses: zmnatz/open-webui-plugin-protocol@v0.7.0
```

Next: [getting started](getting-started.md).
