# owpp live

```
owpp live [--tests FOLDER] [--compose FILE] [--fixtures FOLDER] [--port PORT] [--aimock-port PORT]
          [--up | --keep | --down] [--dir FOLDER] [-- pytest args]
```

`owpp live` tests the plugins on a real Open-WebUI. By default, it does these steps:

1. It starts a throwaway Open-WebUI in Docker, with [aimock](../testing/live.md#the-model-aimock) to answer as its models.
2. It signs up an admin and a user.
3. It deploys the plugins folder with [`owpp deploy`](deploy.md).
4. It runs the live tests of the repository with pytest.
5. It stops the containers and removes their data.

The exit code is the exit code of pytest. If the deploy fails, the command stops with an error. To write the tests, and for their fixtures, see [on a real Open-WebUI](../testing/live.md#live-tests-in-your-repository).

## What you need

You need Docker with its compose plugin, and your user must have access to Docker. The tests need pytest. Tests in the browser also need Playwright and Chromium. The `live` extra of owpp adds pytest and Playwright:

```sh
uvx --from 'owpp[live]' playwright install chromium   # once
uvx --from 'owpp[live]' owpp live
```

Tests that use only the API need no Chromium, so you can skip the first command.

## What it starts

The command starts these two services, called the **stack**:

| Service | Is |
| --- | --- |
| `open-webui` | Open-WebUI v0.13.5 (the version that the protocol targets) as the `-slim` image, on `127.0.0.1:3000`. Its only models are aimock's. Every user can use every model (`BYPASS_MODEL_ACCESS_CONTROL`), so the user account can chat without a grant. It downloads nothing at startup (`OFFLINE_MODE`). |
| `aimock` | [aimock](https://github.com/CopilotKit/aimock) 1.48.1 on `127.0.0.1:4010`. It answers from the fixtures of the repository. Without them, it uses owpp's, which give one model, `owpp-live-model`, with a fixed chat reply. |

The compose project is `owpp-live`, so a machine runs only one stack at a time. The stack has no volumes. When it stops, its data and accounts are gone.

### Your own services and settings

owpp **layers** your compose file on its own, as `docker compose -f owpp's -f yours` does. Your file is the `compose.yaml` beside the tests, or the file that `--compose` names. It can add services and change owpp's services. The image versions that owpp pins stay, unless your file changes them. Paths in your file are relative to its folder.

This example adds a stand-in for a service that a plugin calls. It also points the plugin to the stand-in:

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

`owpp live` sets three variables for the compose files: `OWPP_LIVE_PORT`, `OWPP_LIVE_AIMOCK_PORT` and `OWPP_LIVE_FIXTURES` (the fixtures folder that aimock reads).

### The model's answers

An `aimock/` folder beside the tests, or the folder that `--fixtures` names, **replaces** owpp's fixtures. The models that your fixtures name are the models of the stack. For how to write a fixture, see [the model, aimock](../testing/live.md#the-model-aimock).

## Running it

| Mode | Starts it | Deploys | Runs the tests | Stops it |
| --- | --- | --- | --- | --- |
| `owpp live` | yes | yes | yes | yes |
| `owpp live --keep` | yes | yes | yes | no |
| `owpp live --up` | yes | yes | no: prints the address, the accounts and how to run the tests | no |
| `owpp live --down` | | | | yes |

If a stack still runs, `owpp live` uses it. It signs in to the accounts of the stack and deploys again.

`--up` prints the [variables](../environment-variables.md#set-by-owpp-live-for-the-live-tests) to export, and the two variables that `owpp deploy` needs. With them, you can run the tests again or deploy a change: see [trying things out](../testing/live.md#trying-things-out).

The deploy signs in to the throwaway instance only with its admin token. It does not read the `OPEN_WEBUI_*` variables in your environment, which are for a real instance.

## Options

| Option | Meaning |
| --- | --- |
| `--tests FOLDER` | The folder of the live tests, which can also hold `compose.yaml` and `aimock/`. Default `./live`. |
| `--compose FILE` | A compose file to layer on owpp's. Default: `compose.yaml` in the tests folder, if there is one. |
| `--fixtures FOLDER` | The fixtures for aimock, instead of owpp's. Default: `aimock/` in the tests folder, if there is one. |
| `--port PORT` | The port of Open-WebUI on `127.0.0.1`. Default 3000. |
| `--aimock-port PORT` | The port of aimock on `127.0.0.1`. Default 4010. |
| `--up` | Start the stack and deploy, run no tests, and keep the stack running. |
| `--keep` | Keep the stack running after the tests. |
| `--down` | Stop a stack that still runs. |
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

- [On a real Open-WebUI](../testing/live.md): how to write live tests, the fixtures, aimock.
- [A live check in CI](../testing/ci.md#a-live-check): the workflow.
- [`owpp test`](test.md): the unit tests on the test harness, which need no Docker.
