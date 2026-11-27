# owpp live

```
owpp live [--tests FOLDER] [--compose FILE] [--fixtures FOLDER] [--port PORT] [--aimock-port PORT]
          [--up | --keep | --down] [--dir FOLDER] [-- pytest args]
```

Tests the plugins on a real Open-WebUI. It starts a throwaway one in Docker, with [aimock](../testing/live.md#the-model-aimock) answering as its models, signs up an admin and a user, deploys the plugins folder with [`owpp deploy`](deploy.md), runs the repository's live tests with pytest, and removes it all again. Its exit code is pytest's. How to write the tests, and the fixtures they get: [on a real Open-WebUI](../testing/live.md#live-tests-in-your-repository).

It needs Docker with its compose plugin, reachable by your user. Tests in the browser also need Playwright, which owpp's `live` extra adds, and Chromium:

```sh
uvx --from 'owpp[live]' playwright install chromium   # once
uvx --from 'owpp[live]' owpp live
```

Tests over the API alone need neither: `uvx owpp live` runs them.

## What it starts

| Service | Is |
| --- | --- |
| `open-webui` | Open-WebUI v0.13.5 (the version the protocol targets) as the `-slim` image, on `127.0.0.1:3000`. Its only models are aimock's. Every user may use every model (`BYPASS_MODEL_ACCESS_CONTROL`), so the user account can chat without a grant. Nothing is downloaded at startup (`OFFLINE_MODE`). |
| `aimock` | [aimock](https://github.com/CopilotKit/aimock) 1.48.1 on `127.0.0.1:4010`, answering from the fixtures: the repository's, else owpp's own, which give one model, `owpp-live-model`, that answers every message the same way. |

The compose project is `owpp-live`, so one stack runs at a time on a machine. Nothing is kept between runs: no volumes, fresh accounts.

### Your own services and settings

A `compose.yaml` beside the tests (or the file `--compose` names) is **layered on** owpp's, as `docker compose -f owpp's -f yours` does: it adds services and changes the ones there, and owpp's version pins still apply. Paths in it are relative to its own folder. For a stand-in for a service a plugin calls, and the setting that points the plugin at it:

```yaml
services:
  open-webui:
    environment:
      MY_SERVICE_URL: http://my-service   # read by the plugin
      BYPASS_MODEL_ACCESS_CONTROL: "false" # to test model grants as a real instance has them
    depends_on: [my-service]
  my-service:
    image: nginx:1.27-alpine
    volumes: ["./my-service:/usr/share/nginx/html:ro"]
```

owpp live sets three variables for the compose files: `OWPP_LIVE_PORT`, `OWPP_LIVE_AIMOCK_PORT` and `OWPP_LIVE_FIXTURES` (the fixtures folder mounted into aimock).

### The model's answers

An `aimock/` folder beside the tests (or the folder `--fixtures` names) **replaces** owpp's fixtures: the models it names are the stack's models. Each fixture says what to match and what to answer, and the first that matches wins: [the model, aimock](../testing/live.md#the-model-aimock).

## Running it

| Mode | Starts it | Deploys | Runs the tests | Stops it |
| --- | --- | --- | --- | --- |
| `owpp live` | yes | yes | yes | yes |
| `owpp live --keep` | yes | yes | yes | no |
| `owpp live --up` | yes | yes | no: prints the address, the accounts and how to run the tests | no |
| `owpp live --down` | | | | yes |

With a stack left running, `owpp live` again uses it (signing in to the accounts already there) and deploys again. `--up` prints the [variables](../environment-variables.md#set-by-owpp-live-for-the-live-tests) to export (the accounts, and `PYTEST_PLUGINS=owpp.live.fixtures`, which loads the fixtures), after which `pytest live/` runs the tests against it as often as you like, and the two variables for `owpp deploy` to put a change on it.

The deploy signs in to the throwaway instance's address with its admin token and nothing else: it does not read the `OPEN_WEBUI_*` variables in your environment, which are for a real instance.

## Options

| Option | Meaning |
| --- | --- |
| `--tests FOLDER` | The live tests, and the `compose.yaml` and `aimock/` beside them. Default `./live`. |
| `--compose FILE` | A compose file layered on owpp's. Default: `compose.yaml` in `--tests`, if there. |
| `--fixtures FOLDER` | aimock's fixtures, in place of owpp's. Default: `aimock/` in `--tests`, if there. |
| `--port PORT` | Open-WebUI's port on `127.0.0.1`. Default 3000. |
| `--aimock-port PORT` | aimock's port on `127.0.0.1`. Default 4010. |
| `--up` | Start it and deploy, run no tests, and leave it running. |
| `--keep` | Leave it running after the tests. |
| `--down` | Stop a stack left running. |
| `-- pytest args` | Everything after `--` goes to pytest. |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |

## Examples

```sh
uvx --from 'owpp[live]' owpp live                    # the tests in ./live
uvx --from 'owpp[live]' owpp live -- -k chat -x      # after --: arguments for pytest
uvx --from 'owpp[live]' owpp live --up               # leave it running, to try things or rerun tests
uvx --from 'owpp[live]' owpp live --down
```

## Related

- [On a real Open-WebUI](../testing/live.md): writing live tests, the fixtures, aimock.
- [A live check in CI](../testing/ci.md#a-live-check): the workflow.
- [`owpp test`](test.md): the tests against the mock, which need no Docker.
