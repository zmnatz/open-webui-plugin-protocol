# Install

`owpp` is a Python package with one dependency (PyYAML). You do not have to install it: [uv](https://docs.astral.sh/uv/) runs it directly from PyPI.

## Requirements

- **[uv](https://docs.astral.sh/uv/getting-started/installation/)**. It brings its own Python, so you do not need a Python of your own. Without uv, use Python 3.12 with `pip` or `pipx` ([below](#install-it-on-your-path)). owpp runs on the Python of the Open-WebUI that it pins ([owpp mirrors Open-WebUI](testing/harness.md#owpp-mirrors-open-webui)).
- **`git`**, for plugins that take code from another repository (`source:`), and for `owpp pull` and `owpp check --since`.
- For a deploy, an **Open-WebUI** instance and a way to sign in as an admin. That is an API key, a user name and password, an OIDC token, or nothing where the instance allows it ([signing in](commands/deploy.md#signing-in)).

## Run it

```sh
uvx owpp --version         # runs the latest release, nothing installed
uvx owpp@0.7.2 list        # a pinned release (recommended: see below)
```

`uvx owpp <command>` works from all folders. Each command finds the plugins folder in `--dir`. If there is no `--dir`, it uses [`$OWPP_PLUGINS_DIR`](environment-variables.md#owpp_plugins_dir), then `./plugins`.

**Pin the version.** The runtime and the libraries are copied into the code that you deploy, so a new `owpp` changes your deployed code. In scripts and CI, use `uvx owpp@0.7.2 ...`. Move the pin as a reviewed change, as you do for other dependencies. [Upgrading](upgrading.md) gives the steps.

## The test extra

`owpp test` runs each plugin's tests against the real Open-WebUI, in the test process ([the test harness](testing/harness.md)). It needs pytest and the packages of Open-WebUI's slim image, at Open-WebUI's versions. The `test` extra adds them:

```sh
uvx --python 3.12 --from 'owpp[test]' owpp test
```

The first run downloads Open-WebUI's own code (about 110 MB) to a cache: [`OWPP_CACHE_DIR`](environment-variables.md#owpp_cache_dir).

[`owpp live`](commands/live.md) runs the live tests on a throwaway Open-WebUI in Docker. Its tests in the browser need Playwright, which the `live` extra adds: `uvx --from 'owpp[live]' owpp live`.

## Install it on your PATH

To put `owpp` on your `PATH`, use one of these commands:

```sh
uv tool install owpp==0.7.2  # or: uv tool install --python 3.12 'owpp[test]==0.7.2'
pipx install owpp==0.7.2     # or with pipx
pip install owpp==0.7.2      # or into a virtual environment
```

`python -m owpp` is the same command as `owpp`.

## An unreleased commit

To run a commit or a branch that is not released, use:

```sh
uvx --from git+https://github.com/zmnatz/open-webui-plugin-protocol@<sha or branch> owpp list
```

## In GitHub Actions

You do not install anything. The [action](tooling.md#github-action) sets up uv and runs `owpp` from its own checkout. Thus the version is the tag that you pin in `uses:`.

```yaml
- uses: zmnatz/open-webui-plugin-protocol@v0.7.2
```

Next: [getting started](getting-started.md).
